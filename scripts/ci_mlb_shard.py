#!/usr/bin/env python3
"""CI shard runner for scripts/build_mlb_margin_draws.py.

Runs the V13.1 Gamma-Poisson Monte Carlo replay on a deterministic shard of
the features.csv row set (row_index %% shards == shard_index) and writes a
shard manifest + per-game npz artifacts into --out-dir.

Research-only. No market data (the builder stubs load_market_by_gamepk before
any harness call). Per-game draws are order-invariant: seed = 722 + gamePk,
so sharding cannot change any game's draws. The aggregate step cross-checks
shard npz hashes against an unsharded probe run for overlapping games.

Fail-closed: any inconsistency raises OofBuildError with a SCREAMING_SNAKE
code and a non-zero exit.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile


def load_builder(repo_root: str):
    path = os.path.join(repo_root, "scripts", "build_mlb_margin_draws.py")
    if not os.path.exists(path):
        raise SystemExit(f"BUILDER_MISSING: {path}")
    spec = importlib.util.spec_from_file_location("build_mlb_margin_draws", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--shard-index", type=int, required=True)
    p.add_argument("--shards", type=int, required=True)
    p.add_argument("--sims-per-game", type=int, default=30000)
    p.add_argument("--seed", type=int, default=722)
    p.add_argument("--repo-root", default=os.getcwd())
    p.add_argument("--out-dir", required=True)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not (0 <= args.shard_index < args.shards):
        raise SystemExit(
            f"SHARD_INDEX_INVALID: shard-index {args.shard_index} "
            f"not in [0, {args.shards})")
    repo_root = os.path.abspath(args.repo_root)
    B = load_builder(repo_root)

    harness_path = os.path.join(repo_root, "harness", "run_v13_historical.py")
    mod, sb = B.import_harness(harness_path)

    features_sha = B.sha256_file(mod.FEATURES)
    config_sha = B.sha256_file(mod.CAND_CFG)
    if not config_sha.startswith("eede422d"):
        raise B.OofBuildError(
            "CONFIG_HASH_DRIFT", "candidate config sha256 drifted from pin",
            {"expected_prefix": "eede422d", "actual": config_sha})
    harness_sha = B.sha256_file(harness_path)

    orig_load_rows = mod.load_rows
    all_rows = orig_load_rows()
    shard_rows = [r for i, r in enumerate(all_rows)
                  if i % args.shards == args.shard_index]
    if not shard_rows:
        raise B.OofBuildError(
            "SHARD_EMPTY", "shard selected zero games",
            {"shard_index": args.shard_index, "shards": args.shards,
             "total_rows": len(all_rows)})
    mod.load_rows = lambda: list(shard_rows)

    # Replay stdout JSONL carries wall-clock stamps: diagnostic only, tmpdir.
    replay_jsonl = os.path.join(
        tempfile.gettempdir(),
        f"mlb_margin_draws_v1_replay_stdout_shard{args.shard_index}.jsonl")
    rows, cap, _stdout = B.run_replay(
        mod, args.sims_per_game, args.seed, None, replay_jsonl)
    games = B.build_game_records(rows, cap, args.seed, args.sims_per_game)
    files, statuses = B.write_game_artifacts(games, args.out_dir)
    n_written = sum(1 for s in statuses if s["status"] == "written")
    n_noop = sum(1 for s in statuses if s["status"] == "noop_identical")

    summary = B.summarize(games)
    dates = sorted(g["date"] for g in games)
    window = {"start": dates[0], "end": dates[-1]}
    # Shard-level sigma is informational only (shards are typically below the
    # min_n=200 support floor -> SIGMA_MIN_SUPPORT). The aggregate job computes
    # the qualifying overall sigma over the full union.
    sigma_info = B.estimate_oof_sigma(games, repo_root, window)

    manifest = B.build_manifest(
        games, files, args.seed, args.sims_per_game, features_sha, config_sha,
        harness_sha, sigma_info, summary,
        subset_label=f"SHARD_{args.shard_index}_OF_{args.shards}")
    manifest["shard"] = {
        "index": args.shard_index,
        "shards": args.shards,
        "rule": "row_index % shards == shard_index",
        "shard_games": len(games),
        "total_games_unsharded": len(all_rows),
    }
    mbytes = (B.canonical_json(manifest) + "\n").encode()
    B.append_only_write(os.path.join(args.out_dir, "shard_manifest.json"),
                        mbytes)
    print(B.canonical_json({
        "status": "ok",
        "shard_index": args.shard_index,
        "shards": args.shards,
        "n_games": len(games),
        "total_games_unsharded": len(all_rows),
        "sims_per_game": args.sims_per_game,
        "files_written": n_written,
        "files_noop_identical": n_noop,
        "window": window,
        "shard_sigma": sigma_info,
        "summary_residual": summary["residual"],
        "out_dir": args.out_dir,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
