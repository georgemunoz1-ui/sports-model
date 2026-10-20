#!/usr/bin/env python3
"""Aggregate CI shard outputs into the final mlb_margin_draws_v1 artifact set.

Reads every shard directory (shard_manifest.json + per-game npz), verifies
completeness and integrity against the pinned features.csv, cross-checks the
unsharded probe run for seed order-invariance, computes the qualifying
overall OOF sigma via models.common.margins.sigma.estimate_sigma, and writes:
  <out-dir>/manifest.json    hash-pinned full manifest (append-only)
  <out-dir>/residuals.csv    per-game predictions/actuals/residuals
  <out-dir>/<gamePk>.npz     per-game integer draw banks (append-only)

Fail-closed: any missing/extra game, hash mismatch, or provenance drift
aborts with a SCREAMING_SNAKE code and writes nothing partial to the final
manifest (per-game npz copies are content-identical by verification, so an
aborted run leaves only verified files behind).
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import os
import sys


def load_builder(repo_root: str):
    path = os.path.join(repo_root, "scripts", "build_mlb_margin_draws.py")
    if not os.path.exists(path):
        raise SystemExit(f"BUILDER_MISSING: {path}")
    spec = importlib.util.spec_from_file_location("build_mlb_margin_draws", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AggregateError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details or {}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo-root", default=os.getcwd())
    p.add_argument("--shards-dir", required=True,
                   help="dir containing one subdirectory per shard")
    p.add_argument("--probe-dir", default=None,
                   help="optional unsharded probe out-dir for cross-check")
    p.add_argument("--out-dir", required=True)
    return p.parse_args(argv)


def expected_game_count(features_path: str) -> int:
    """Mirror harness load_rows(): rows with non-empty home_win are replayed."""
    n = 0
    with open(features_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            hw = row.get("home_win")
            if hw is not None and str(hw).strip() != "":
                n += 1
    return n


def load_shard(shards_dir: str, name: str) -> dict:
    mpath = os.path.join(shards_dir, name, "shard_manifest.json")
    if not os.path.exists(mpath):
        raise AggregateError(
            "SHARD_MANIFEST_MISSING", "shard manifest not found",
            {"path": mpath})
    import json
    with open(mpath, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None) -> int:
    args = parse_args(argv)
    repo_root = os.path.abspath(args.repo_root)
    B = load_builder(repo_root)
    import json

    shard_names = sorted(d for d in os.listdir(args.shards_dir)
                         if os.path.isdir(os.path.join(args.shards_dir, d)))
    if not shard_names:
        raise AggregateError(
            "AGGREGATE_NO_SHARDS", "no shard directories found",
            {"shards_dir": args.shards_dir})
    manifests = {name: load_shard(args.shards_dir, name)
                 for name in shard_names}

    # --- shard set coherence -------------------------------------------------
    idx = {}
    K = None
    for name, m in manifests.items():
        sh = m.get("shard") or {}
        k, kk = sh.get("index"), sh.get("shards")
        if k is None or kk is None:
            raise AggregateError(
                "SHARD_METADATA_MISSING", "manifest lacks shard block",
                {"shard": name})
        if K is None:
            K = kk
        elif K != kk:
            raise AggregateError(
                "SHARD_COUNT_MISMATCH", "inconsistent shard counts",
                {"expected": K, "got": kk, "shard": name})
        if k in idx:
            raise AggregateError(
                "SHARD_DUPLICATE", "duplicate shard index",
                {"index": k, "shards": [idx[k], name]})
        idx[k] = name
    missing = [i for i in range(K) if i not in idx]
    if missing:
        raise AggregateError(
            "SHARD_SET_INCOMPLETE", "missing shard indices",
            {"missing": missing, "shards": K})

    # --- provenance consistency across shards --------------------------------
    prov_keys = ("seed_base", "sims_per_game")
    ref = manifests[idx[0]]["provenance"]
    engine_ref = manifests[idx[0]]["engine"]
    for name, m in manifests.items():
        p = m["provenance"]
        for key in prov_keys:
            if p.get(key) != ref.get(key):
                raise AggregateError(
                    "SHARD_PROVENANCE_DRIFT", f"provenance.{key} differs",
                    {"key": key, "ref": ref.get(key), "got": p.get(key),
                     "shard": name})
        for fkey in ("features_file", "config_file", "harness"):
            if p[fkey]["sha256"] != ref[fkey]["sha256"]:
                raise AggregateError(
                    "SHARD_PROVENANCE_DRIFT", f"{fkey} sha differs",
                    {"shard": name})
        e = m["engine"]
        for ekey in ("source_id", "version"):
            if e.get(ekey) != engine_ref.get(ekey):
                raise AggregateError(
                    "SHARD_PROVENANCE_DRIFT", f"engine.{ekey} differs",
                    {"shard": name})

    # --- game union completeness + per-game npz integrity --------------------
    seen = {}
    games = []
    files = []
    for name in shard_names:
        m = manifests[name]
        mdir = os.path.join(args.shards_dir, name)
        fby = {f["file"]: f for f in m["files"]}
        for g in m["games"]:
            pk = g["gamePk"]
            if pk in seen:
                raise AggregateError(
                    "DUPLICATE_GAME", "gamePk in multiple shards",
                    {"gamePk": pk, "shards": [seen[pk], name]})
            seen[pk] = name
            games.append(g)
        for f in m["files"]:
            fpath = os.path.join(mdir, f["file"])
            if not os.path.exists(fpath):
                raise AggregateError(
                    "SHARD_FILE_MISSING", "npz listed but absent",
                    {"file": f["file"], "shard": name})
            data = open(fpath, "rb").read()
            if len(data) != f["bytes"] or B.sha256_bytes(data) != f["sha256"]:
                raise AggregateError(
                    "SHARD_FILE_HASH_MISMATCH", "npz failed hash verification",
                    {"file": f["file"], "shard": name})
            files.append(f)
            B.append_only_write(os.path.join(args.out_dir, f["file"]), data)

    features_path = os.path.join(
        repo_root, "data", "backfill", "mlb", "2026", "features.csv")
    expected = expected_game_count(features_path)
    if len(games) != expected:
        raise AggregateError(
            "AGGREGATE_GAMES_MISSING",
            "shard union does not cover all replayable games",
            {"union": len(games), "expected": expected})
    union_total = sum(m["shard"]["total_games_unsharded"]
                      for m in manifests.values()) / K
    if int(union_total) != expected:
        raise AggregateError(
            "AGGREGATE_COUNT_INCONSISTENT",
            "shard-reported unsharded total disagrees with features.csv",
            {"shards_reported": union_total, "features_count": expected})

    # --- probe cross-check: sharded vs unsharded draws are byte-identical ----
    probe_checked = 0
    if args.probe_dir and os.path.isdir(args.probe_dir):
        pman_path = os.path.join(args.probe_dir, "manifest.json")
        if os.path.exists(pman_path):
            with open(pman_path, encoding="utf-8") as fh:
                pman = json.load(fh)
            shard_by_file = {f["file"]: f for f in files}
            for pf in pman["files"]:
                sf = shard_by_file.get(pf["file"])
                if sf is None:
                    continue
                pdata = open(os.path.join(args.probe_dir, pf["file"]),
                             "rb").read()
                sdata = open(os.path.join(args.out_dir, sf["file"]),
                             "rb").read()
                if pdata != sdata or pf["sha256"] != sf["sha256"]:
                    raise AggregateError(
                        "ORDER_INVARIANCE_VIOLATION",
                        "probe (unsharded) npz differs from sharded npz",
                        {"file": pf["file"]})
                probe_checked += 1
    if probe_checked == 0:
        raise AggregateError(
            "ORDER_INVARIANCE_UNVERIFIED",
            "probe cross-check compared zero games; refusing to aggregate",
            {})

    # --- merged summary + qualifying overall OOF sigma -----------------------
    games.sort(key=lambda g: (g["date"], g["gamePk"]))
    files.sort(key=lambda f: f["file"])
    synth = [{"pred_margin_mean": g["pred_margin_mean"],
              "date": g["date"],
              "actual": {"margin": g["actual_margin"]}} for g in games]
    summary = B.summarize(synth)
    dates = sorted(g["date"] for g in games)
    window = {"start": dates[0], "end": dates[-1]}
    sigma_info = B.estimate_oof_sigma(synth, repo_root, window)
    if sigma_info.get("status") != "ok" or sigma_info.get("sigma") is None:
        raise AggregateError(
            "AGGREGATE_SIGMA_UNAVAILABLE",
            "overall OOF sigma not estimable over full union",
            {"sigma_info": sigma_info})

    lineage = {name: B.sha256_bytes(
        (B.canonical_json(manifests[name]) ).encode())
        for name in shard_names}
    engine = dict(engine_ref)
    engine["run_key"] = (f"oof-{window['start']}-{window['end']}"
                         f"-sims{ref['sims_per_game']}-seed{ref['seed_base']}")
    manifest = {
        "artifact": "mlb_margin_draws_v1",
        "sport": "mlb",
        "engine": engine,
        "provenance": dict(ref),
        "n_games": len(games),
        "games": games,
        "files": files,
        "summary": summary,
        "oof_sigma": sigma_info,
        "aggregation": {
            "shards": K,
            "shard_rule": "row_index % shards == shard_index",
            "shard_manifest_sha256": lineage,
            "probe_order_invariance_checked_games": probe_checked,
            "expected_games_from_features": expected,
        },
    }
    mbytes = (B.canonical_json(manifest) + "\n").encode()
    mstatus = B.append_only_write(os.path.join(args.out_dir, "manifest.json"),
                                  mbytes)

    # --- residuals.csv ---------------------------------------------------------
    import io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["gamePk", "date", "away_team", "home_team", "seed", "n_sims",
                "sp_matched", "pred_margin_mean", "pred_total_mean",
                "actual_margin", "actual_total", "residual"])
    for g in games:
        w.writerow([g["gamePk"], g["date"], g["away_team"], g["home_team"],
                    g["seed"], g["n_sims"], g["sp_matched"],
                    g["pred_margin_mean"], g["pred_total_mean"],
                    g["actual_margin"], g["actual_total"], g["residual"]])
    B.append_only_write(os.path.join(args.out_dir, "residuals.csv"),
                        buf.getvalue().encode())

    print(B.canonical_json({
        "status": "ok",
        "n_games": len(games),
        "n_files": len(files),
        "window": window,
        "oof_sigma": sigma_info,
        "summary_residual": summary["residual"],
        "probe_order_invariance_checked_games": probe_checked,
        "manifest_status": mstatus,
        "out_dir": args.out_dir,
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AggregateError as e:
        print(f"{e.code}: {e}", file=sys.stderr)
        sys.exit(2)
