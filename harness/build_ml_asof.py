#!/usr/bin/env python3
"""P1B — deterministic as-of ML dataset builder (the data firewall).

Phase-0 finding V-1: the live ML path has no `date < slate_date` filter anywhere; its as-of safety
is a property of whatever happens to be on disk. This builder is the repair of the MEASUREMENT
system, not of the model: every row carries its own provenance, every feature carries its
observation date, and eligibility is explicit. Nothing is silently dropped — every final in
results.csv appears either as a dataset row or in the exclusion records, and healthcheck fails if
the two do not reconcile.

TIME RULE (owner-frozen): default eligibility is STRICT date < slate_date. Same-day information is
admissible only with an exact source-observation timestamp proving it preceded both the prediction
timestamp and first pitch; no source in this repo carries such timestamps, so same-day rows are
excluded, always. Doubleheaders keep the standing start-of-day treatment: both games share the
slate_date and see identical strictly-before features.

Determinism: rows sorted by (slate_date, gamePk); no wall-clock enters the dataset file; the
vintage hash is sha256 of the dataset bytes, so an identical rebuild is byte-identical. Build
wall-clock lives only in the manifest's non-hashed `built_utc` field.

Market odds are NOT read by this builder at all — benchmarking joins happen downstream against the
odds files, never into predictive features. `assert_no_market_fields` enforces it.

    python3 harness/build_ml_asof.py            # build data/mlb/ml_asof/{dataset.jsonl,manifest.json,reports}
    python3 harness/build_ml_asof.py --check    # rebuild in memory, compare vintage hash to manifest
"""

from __future__ import annotations

MODULE_ID = "build_ml_asof"

import csv
import hashlib
import json
import os
import sys
import datetime as dt
from collections import OrderedDict, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

SCHEMA_VERSION = "ml-asof-v1"
OUT_DIR = "data/mlb/ml_asof"
SOURCES = {
    "results": "data/backfill/mlb/2026/results.csv",
    "starters": "data/backfill/mlb/2026/starters.csv",
    "pitchers": "data/backfill/mlb/2026/pitchers.csv",
    "park_factors": "data/backfill/mlb/2026/park_factors.json",
    "placeholder_manifest": "data/backfill/mlb/2026/pitcher_logs/_placeholders.json",
}
LOGS = "data/backfill/mlb/2026/pitcher_logs"

FORBIDDEN_FEATURE_TOKENS = ("ml_", "odds", "price", "spread", "moneyline", "vig", "line")


def sha(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def log_rows(pid: str):
    """(date, ip, er, so, bb, tbf, gs) via exact-width dispatch; unknown widths raise (R1)."""
    p = os.path.join(LOGS, f"{pid}.txt")
    if not os.path.exists(p):
        return None
    out = []
    for i, ln in enumerate(open(p), 1):
        ln = ln.strip()
        if not ln:
            continue
        f = ln.split("|")
        if len(f) == 10:
            out.append((f[0], float(f[4]), float(f[5]), float(f[6]), float(f[7]), float(f[8]), f[9] == "1"))
        elif len(f) == 8:
            out.append((f[0], float(f[2]), float(f[3]), float(f[4]), float(f[5]), float(f[6]), f[7] == "1"))
        elif len(f) == 7:
            out.append((f[0], float(f[1]), float(f[2]), float(f[3]), float(f[4]), float(f[5]), f[6] == "1"))
        else:
            raise ValueError(f"{p}:{i} unknown log width {len(f)}")
    out.sort()
    return out


def sp_asof_strict(pid: str, slate_date: str, ph_dates: set):
    """Cumulative ERA/GS/K%/BB% from rows with date < slate_date. Returns (features, flags)."""
    rows = log_rows(pid)
    if rows is None:
        return None, {"reason": "NO_LOG_FILE"}
    ip = er = so = bb = tbf = 0.0
    gs = 0
    last = None
    ph_in_window = False
    for d, i_, e_, s_, b_, t_, g_ in rows:
        if d >= slate_date:
            continue
        ip += i_; er += e_; so += s_; bb += b_; tbf += t_
        if g_:
            gs += 1
            last = d
        if d in ph_dates:
            ph_in_window = True
    if tbf < 10:
        return None, {"reason": "INSUFFICIENT_PRIOR_DATA (tbf<10 strictly before slate)"}
    feats = OrderedDict([
        ("era", round(er * 9 / ip, 3) if ip >= 1 else None),
        ("gs", gs),
        ("k_pct", round(so / tbf * 100, 2)),
        ("bb_pct", round(bb / tbf * 100, 2)),
        ("last_start_date", last),
    ])
    return feats, {"placeholder_in_window": ph_in_window}


def build():
    ph = json.load(open(SOURCES["placeholder_manifest"]))
    ph_by_pid = defaultdict(set)
    for r in ph["rows"]:
        ph_by_pid[r["pitcher_id"]].add(r["date"])

    starters = {}
    for ln in open(SOURCES["starters"]):
        f = ln.rstrip("\n").split("|")
        if f[0] == "gamePk" or len(f) < 9:
            continue
        starters[f[0]] = dict(asp_id=f[5], asp_name=f[6], hsp_id=f[7], hsp_name=f[8])

    park = json.load(open(SOURCES["park_factors"]))
    finals = [r for r in csv.DictReader(open(SOURCES["results"]))
              if r["status"] == "final" and r["total"] != ""]
    finals.sort(key=lambda r: (r["date"], r["game_id"]))

    # team as-of accumulators, applied strictly before each date
    rf = defaultdict(float); ra = defaultdict(float); gp = defaultdict(int); last_final = {}
    bydate = defaultdict(list)
    for r in finals:
        bydate[r["date"]].append(r)

    rows, exclusions = [], []
    for date in sorted(bydate):
        for r in bydate[date]:
            gpk = r["game_id"].split(":")[-1]
            a, h = r["away"], r["home"]
            team = {}
            for side, t in (("away", a), ("home", h)):
                team[side] = OrderedDict([
                    ("rf_pg", round(rf[t] / gp[t], 3) if gp[t] else None),
                    ("ra_pg", round(ra[t] / gp[t], 3) if gp[t] else None),
                    ("games_before", gp[t]),
                    ("last_obs_date", last_final.get(t)),
                ])
            st = starters.get(gpk)
            sp = {}
            sp_flags = {}
            if st is None:
                starter_status = "UNRESOLVED (no starter record in starters.csv)"
                sp = {"away": None, "home": None}
                sp_flags = {"away": {"reason": "NO_STARTER_RECORD"}, "home": {"reason": "NO_STARTER_RECORD"}}
            else:
                starter_status = "RESOLVED_POST_HOC (actual starters from starters.csv; NOT a pregame confirmation)"
                for side, pid, nm in (("away", st["asp_id"], st["asp_name"]), ("home", st["hsp_id"], st["hsp_name"])):
                    feats, flags = sp_asof_strict(pid, date, ph_by_pid.get(pid, set()))
                    sp[side] = None if feats is None else OrderedDict([("pid", pid), ("name", nm)] + list(feats.items()))
                    sp_flags[side] = flags
            missing = [s for s in ("away", "home") if sp[s] is None]
            row = OrderedDict([
                ("gamePk", gpk),
                ("game_id", r["game_id"]),
                ("slate_date", date),
                ("scheduled_first_pitch_utc", None),
                ("first_pitch_missing", True),
                ("prediction_generated_utc", None),
                ("source_observation_cutoff", f"strict date < {date} (start-of-day; doubleheaders share it)"),
                ("away", a), ("home", h),
                ("venue", r["venue"]),
                ("park_factor", park.get(r["venue"])),
                ("starter_status", starter_status),
                ("starter_confirmed_pregame", False),
                ("team", team),
                ("sp", sp),
                ("flags", OrderedDict([
                    ("sp_missing_sides", missing),
                    ("sp_flags", sp_flags),
                    ("placeholder_in_window",
                     any((sp_flags.get(s) or {}).get("placeholder_in_window") for s in ("away", "home"))),
                    ("team_obs_missing", [s for s in ("away", "home") if team[s]["rf_pg"] is None]),
                ])),
                ("eligible_for_evaluation", not missing and st is not None),
                ("executable_eligible", False),
                ("executable_eligible_reason", "historical dataset row; executability applies only to forward forecasts with pregame-confirmed starters"),
                ("model_id", None),
                ("label_home_win", int(r["home_win"])),
                ("label_total", int(r["total"])),
                ("label_margin", int(r["margin"])),
                ("schema_version", SCHEMA_VERSION),
            ])
            rows.append(row)
            if missing or st is None:
                exclusions.append(OrderedDict([
                    ("gamePk", gpk), ("slate_date", date), ("matchup", f"{a}@{h}"),
                    ("excluded_from", "evaluation population (row RETAINED in dataset, flagged)"),
                    ("reason", "no starter record" if st is None else
                     "; ".join(f"{s} SP: {sp_flags[s].get('reason','?')}" for s in missing)),
                ]))
        # apply the day's games AFTER snapshotting: strict before
        for r in bydate[date]:
            a, h = r["away"], r["home"]
            asc, hsc = int(r["away_score"]), int(r["home_score"])
            rf[a] += asc; ra[a] += hsc; gp[a] += 1; last_final[a] = date
            rf[h] += hsc; ra[h] += asc; gp[h] += 1; last_final[h] = date
    return rows, exclusions


def assert_no_market_fields(rows):
    bad = []
    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                kl = k.lower()
                if any(t in kl for t in FORBIDDEN_FEATURE_TOKENS) and "cutoff" not in kl:
                    bad.append(path + "/" + k)
                walk(v, path + "/" + k)
        elif isinstance(o, list):
            for v in o:
                walk(v, path)
    # This is an admission gate, not a sample audit: inspect the entire dataset.
    for r in rows:
        walk(r["team"], "team"); walk(r["sp"], "sp")
    return bad


def manifest_check(manifest):
    """Required provenance keys; every declared source hashed. Fixture-attackable."""
    v=[]
    for k in ("schema_version","row_count","vintage_sha256","source_hashes","log_composite_sha256","time_rule"):
        if k not in manifest: v.append(f"manifest missing {k}")
    for k in SOURCES:
        if k not in manifest.get("source_hashes",{}): v.append(f"manifest missing source hash: {k}")
    return v


def validate(rows, n_finals, exclusions, ph_map=None):
    """Pure gate logic — the negative fixtures in test_ml_firewall.py attack THIS function."""
    v = []
    seen = set()
    for r in rows:
        if r["gamePk"] in seen:
            v.append(f"duplicate gamePk {r['gamePk']}")
        seen.add(r["gamePk"])
        sd = r["slate_date"]
        for side in ("away", "home"):
            t = r["team"][side]
            if t["last_obs_date"] is not None and t["last_obs_date"] >= sd:
                v.append(f"{r['gamePk']} {side} team obs {t['last_obs_date']} NOT strictly before {sd}"
                         + (" (same-day without timestamp proof)" if t["last_obs_date"] == sd else " (FUTURE-DATED)"))
            s = r["sp"][side]
            if s and s.get("last_start_date") and s["last_start_date"] >= sd:
                v.append(f"{r['gamePk']} {side} SP obs {s['last_start_date']} NOT strictly before {sd}")
        if r["executable_eligible"] and "UNRESOLVED" in str(r["starter_status"]):
            v.append(f"{r['gamePk']} unresolved starter marked executable_eligible")
        if r["executable_eligible"] and not r["starter_confirmed_pregame"]:
            v.append(f"{r['gamePk']} executable_eligible without pregame-confirmed starter")
    flagged = sum(1 for r in rows if r["flags"]["sp_missing_sides"] or "UNRESOLVED" in str(r["starter_status"]))
    if len(rows) != n_finals:
        v.append(f"silent exclusion: {n_finals} finals but {len(rows)} rows and no reconciliation")
    if flagged != len(exclusions):
        v.append(f"exclusion records ({len(exclusions)}) do not reconcile with flagged rows ({flagged})")
    if ph_map:
        for r in rows:
            for side in ("away","home"):
                s_=r["sp"][side]
                if not s_: continue
                pid=s_.get("pid")
                if pid in ph_map and any(d < r["slate_date"] for d in ph_map[pid]):
                    fl=r["flags"]["sp_flags"].get(side) or {}
                    if not fl.get("placeholder_in_window"):
                        v.append(f"{r['gamePk']} {side} SP {pid}: placeholder in as-of window but UNFLAGGED")
    v += [f"market token in feature path: {p}" for p in assert_no_market_fields(rows)]
    return v


def dataset_bytes(rows):
    return ("\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n").encode()


def main():
    rows, exclusions = build()
    finals_n = len(rows)  # every final becomes a row by construction; validate() re-derives from source
    n_source_finals = sum(1 for r in csv.DictReader(open(SOURCES["results"]))
                          if r["status"] == "final" and r["total"] != "")
    ph = json.load(open(SOURCES["placeholder_manifest"]))
    ph_map = {}
    for pr in ph["rows"]: ph_map.setdefault(pr["pitcher_id"], set()).add(pr["date"])
    problems = validate(rows, n_source_finals, exclusions, ph_map)
    if problems:
        print("VALIDATE FAIL:")
        for p in problems[:12]:
            print("  " + p)
        return 1
    data = dataset_bytes(rows)
    vintage = hashlib.sha256(data).hexdigest()
    if "--check" in sys.argv:
        m = json.load(open(f"{OUT_DIR}/manifest.json"))
        ok = m["vintage_sha256"] == vintage
        print(f"rebuild check: {'IDENTICAL' if ok else 'DRIFT'} (manifest {m['vintage_sha256'][:12]}, rebuilt {vintage[:12]})")
        return 0 if ok else 1
    os.makedirs(OUT_DIR, exist_ok=True)
    open(f"{OUT_DIR}/dataset.jsonl", "wb").write(data)
    manifest = OrderedDict([
        ("schema_version", SCHEMA_VERSION),
        ("built_utc", dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ("row_count", len(rows)),
        ("eligible_for_evaluation", sum(1 for r in rows if r["eligible_for_evaluation"])),
        ("flagged_rows", len(exclusions)),
        ("vintage_sha256", vintage),
        ("source_hashes", OrderedDict((k, sha(p)) for k, p in sorted(SOURCES.items()))),
        ("log_composite_sha256", _log_composite()),
        ("time_rule", "strict date < slate_date; same-day admissible only with source timestamps (none exist -> excluded); doubleheaders start-of-day"),
        ("determinism", "rows sorted (slate_date, gamePk); no wall-clock in dataset bytes; vintage = sha256(dataset.jsonl)"),
    ])
    json.dump(manifest, open(f"{OUT_DIR}/manifest.json", "w"), indent=1)
    json.dump(exclusions, open(f"{OUT_DIR}/exclusions.json", "w"), indent=1)
    print(f"{OUT_DIR}/dataset.jsonl: {len(rows)} rows ({manifest['eligible_for_evaluation']} evaluation-eligible, "
          f"{len(exclusions)} flagged w/ exclusion records)")
    print(f"vintage {vintage}")
    return 0


def _log_composite():
    h = hashlib.sha256()
    for f in sorted(os.listdir(LOGS)):
        if f.endswith(".txt") and not f.startswith(("_", ".", "README")):
            h.update(f.encode() + b"\0" + hashlib.sha256(open(os.path.join(LOGS, f), "rb").read()).digest())
    return h.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
