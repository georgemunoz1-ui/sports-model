#!/usr/bin/env python3
"""INGEST the lancebroz pitch-level archive into the per-start pitcher logs — PIT-ruled.

SOURCE. /home/user/lancebroz/mlb-pitcher-data, git-cloned through the session proxy (the one
acquisition rail that works). Pitch-level rows: every pitch carries its PA's terminal event and
the MLBAM pitcher_id — the SAME id space as data/backfill/mlb/2026/pitcher_logs/<pid>.txt, so
identity is exact by construction and no name-join is performed.

WHAT CAN AND CANNOT BE DERIVED, stated before any row is written:
  DERIVABLE   per (pitcher, date): TBF, SO, BB, outs->IP, GS (first PA of the half), last date.
  NOT         EARNED RUNS. The archive has no runs column (RJ-001B stands). ER is written as the
              established 0-PLACEHOLDER and every such row is registered in _placeholders.json
              with fields_placeholder=["ER"] — BB is GENUINE in this batch, unlike the 7/21
              batch. ERA is NEVER computed across placeholder rows: the experiment's starter
              resolution excludes placeholder dates from the ERA numerator and denominator, so
              a pitcher's ERA stays exactly his pre-7/23 ERA. An ERA "refreshed" with zero
              fake earned runs would be fabrication wearing a CSV.

PIT RULES ENFORCED IN CODE:
  - only dates strictly BEFORE 2026-09-01 (and the archive itself ends 2026-08-31);
  - per pitcher, only dates strictly AFTER his last existing log row — append, never rewrite;
  - existing bytes of every log are asserted to be a prefix of the new file;
  - malformed rows (null ids, unknown event), duplicate dates, and unmapped pitchers are
    REJECTED with named counters, never silently dropped;
  - pitchers with no existing log file are NOT created (no genuine-ER history -> no ERA ->
    the registry cap must keep governing them).

APPROXIMATIONS, disclosed: baserunning outs not attributable from terminal events are missed
(IP slightly low; IP only gates ip>=1 here); a doubleheader collapses to one dated row (GS set
if either game was a start).
"""

MODULE_ID = "ingest_lancebroz"

import glob
import hashlib
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SRC = "/home/user/lancebroz/mlb-pitcher-data"
DAILY = os.path.join(SRC, "data/raw/2026/daily")
LOGS = "data/backfill/mlb/2026/pitcher_logs"
PLACEHOLDERS = os.path.join(LOGS, "_placeholders.json")
CUTOFF = "2026-09-01"
INGEST_FROM = "2026-07-01"   # per-pitcher window filter does the real work

OUTS = {"strikeout": 1, "strikeout_double_play": 2, "field_out": 1, "force_out": 1,
        "sac_fly": 1, "sac_bunt": 1, "fielders_choice_out": 1,
        "grounded_into_double_play": 2, "double_play": 2, "sac_fly_double_play": 2,
        "sac_bunt_double_play": 2, "triple_play": 3,
        "caught_stealing_home": 1, "caught_stealing_2b": 1, "caught_stealing_3b": 1,
        "pickoff_caught_stealing_home": 1, "pickoff_caught_stealing_2b": 1,
        "pickoff_caught_stealing_3b": 1, "pickoff_1b": 1, "pickoff_2b": 1, "pickoff_3b": 1,
        "other_out": 1}
NOT_A_PA = {k for k in OUTS if "stealing" in k or "pickoff" in k}
ZERO_OUT_PA = {"walk", "intent_walk", "hit_by_pitch", "single", "double", "triple",
               "home_run", "field_error", "fielders_choice", "catcher_interf",
               "catcher_interference", "wild_pitch", "passed_ball", "truncated_pa"}
SO_EVENTS = {"strikeout", "strikeout_double_play"}
BB_EVENTS = {"walk", "intent_walk"}


def existing_last_date(pid):
    p = os.path.join(LOGS, "%s.txt" % pid)
    if not os.path.exists(p):
        return None, None
    last = None
    dates = set()
    for ln in open(p):
        ln = ln.strip()
        if not ln:
            continue
        d = ln.split("|")[0]
        dates.add(d)
        if last is None or d > last:
            last = d
    return last, dates


def derive_day(df):
    """One daily frame -> {(pid, date): {tbf, so, bb, outs, gs}} + reject counters."""
    import pandas as pd
    rejects = defaultdict(int)
    need = ["game_pk", "game_date", "top_bottom", "pitcher_id", "at_bat_number", "events"]
    for c in need:
        if c not in df.columns:
            raise ValueError("MALFORMED_DAILY_FILE_MISSING_COLUMN:%s" % c)
    df = df[need].copy()
    bad = df["pitcher_id"].isna() | df["events"].isna() | df["at_bat_number"].isna()
    rejects["null_field_rows"] += int(bad.sum())
    df = df[~bad]
    # one row per PA: events is constant within a PA; a conflict is malformed and refused
    pa = df.groupby(["game_pk", "top_bottom", "at_bat_number"]).agg(
        pitcher_id=("pitcher_id", "first"), n_pitchers=("pitcher_id", "nunique"),
        event=("events", "first"), n_events=("events", "nunique"),
        date=("game_date", "first")).reset_index()
    conf = pa["n_events"] > 1
    rejects["conflicting_event_in_pa"] += int(conf.sum())
    midpa = pa["n_pitchers"] > 1
    rejects["mid_pa_pitcher_change_attributed_to_first"] += int(midpa.sum())
    pa = pa[~conf]
    out = {}
    starters = set()
    for (gpk, half), grp in pa.groupby(["game_pk", "top_bottom"]):
        first = grp.loc[grp["at_bat_number"].idxmin()]
        starters.add((gpk, half, int(first["pitcher_id"])))
    for _, r in pa.iterrows():
        ev = r["event"]
        if ev not in OUTS and ev not in ZERO_OUT_PA:
            rejects["unknown_event:%s" % ev] += 1
            continue
        pid = str(int(r["pitcher_id"]))
        key = (pid, str(r["date"]))
        rec = out.setdefault(key, {"tbf": 0, "so": 0, "bb": 0, "outs": 0, "gs": False})
        rec["outs"] += OUTS.get(ev, 0)
        if ev not in NOT_A_PA:
            rec["tbf"] += 1
        rec["so"] += ev in SO_EVENTS
        rec["bb"] += ev in BB_EVENTS
        if (r["game_pk"], r["top_bottom"], int(r["pitcher_id"])) in starters:
            rec["gs"] = True
    return out, dict(rejects)


def archive_commit():
    import subprocess
    r = subprocess.run(["git", "-C", SRC, "rev-parse", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip()


def run(write=True):
    import pandas as pd
    files = sorted(glob.glob(os.path.join(DAILY, "*.parquet")))
    files = [f for f in files
             if INGEST_FROM <= os.path.basename(f)[:10] < CUTOFF]
    per_day = {}
    rejects = defaultdict(int)
    for f in files:
        day, rej = derive_day(pd.read_parquet(
            f, columns=["game_pk", "game_date", "top_bottom", "pitcher_id",
                        "at_bat_number", "events"]))
        for k, v in rej.items():
            rejects[k] += v
        for k, v in day.items():
            if k in per_day:
                rejects["duplicate_pitcher_date_across_files"] += 1
                continue
            per_day[k] = v

    by_pid = defaultdict(dict)
    for (pid, date), v in per_day.items():
        by_pid[pid][date] = v

    known = {os.path.basename(p)[:-4] for p in glob.glob(os.path.join(LOGS, "*.txt"))
             if not os.path.basename(p).startswith("_")}
    report = {"pitchers_in_archive_window": len(by_pid),
              "pitchers_with_existing_logs": len(known),
              "appended": {}, "skipped_unmapped_no_log_file": 0,
              "rejected_duplicate_dates": 0, "rejects": dict(rejects)}
    new_placeholder_rows = []
    appended_lines = {}
    for pid, days in sorted(by_pid.items()):
        if pid not in known:
            report["skipped_unmapped_no_log_file"] += 1
            continue
        last, have = existing_last_date(pid)
        lines = []
        for date in sorted(days):
            if date >= CUTOFF:
                continue
            if date in have:
                report["rejected_duplicate_dates"] += 1
                continue
            if last is not None and date <= last:
                report["rejected_duplicate_dates"] += 1
                continue
            v = days[date]
            if v["tbf"] == 0:
                rejects["zero_tbf_rows"] += 1
                continue
            ip = round(v["outs"] / 3.0, 2)
            ln = "%s|%s|0|%d|%d|%d|%d" % (date, ip, v["so"], v["bb"], v["tbf"],
                                          1 if v["gs"] else 0)
            lines.append(ln)
            new_placeholder_rows.append({
                "pitcher_id": pid, "date": date, "fields_placeholder": ["ER"],
                "field_indices": [2], "observed_ER": 0.0, "observed_BB": float(v["bb"]),
                "bb_is_genuine": True, "SO": float(v["so"]), "TBF": float(v["tbf"]),
                "GS": bool(v["gs"]), "raw": ln,
                "source": "lancebroz/mlb-pitcher-data@%s" % archive_commit()[:12]})
        if lines:
            appended_lines[pid] = lines
            report["appended"][pid] = {"n_rows": len(lines),
                                       "first": lines[0].split("|")[0],
                                       "last": lines[-1].split("|")[0]}

    if write:
        for pid, lines in appended_lines.items():
            p = os.path.join(LOGS, "%s.txt" % pid)
            before = open(p, "rb").read()
            with open(p, "a") as fh:
                if before and not before.endswith(b"\n"):
                    fh.write("\n")
                fh.write("\n".join(lines) + "\n")
            after = open(p, "rb").read()
            if not after.startswith(before):
                raise AssertionError("APPEND_ONLY_VIOLATED:%s" % pid)
        pm = json.load(open(PLACEHOLDERS))
        pm["rows"].extend(new_placeholder_rows)
        pm["revision_2026-09-01_lancebroz"] = {
            "n_rows_added": len(new_placeholder_rows),
            "er_is_placeholder_bb_is_genuine": True,
            "source_commit": archive_commit(),
            "era_rule": "ERA excludes placeholder dates entirely; see refresh experiment"}
        json.dump(pm, open(PLACEHOLDERS, "w"), indent=1)
    report["n_pitchers_appended"] = len(appended_lines)
    report["n_rows_appended"] = sum(len(v) for v in appended_lines.values())
    report["n_placeholder_rows_added"] = len(new_placeholder_rows)
    report["source_commit"] = archive_commit()
    report["cutoff_exclusive"] = CUTOFF
    return report


def er_placeholder_dates(pid, _cache={}):
    """Dates whose ER is a registered placeholder for this pitcher. ERA must never span them."""
    if not _cache:
        pm = json.load(open(PLACEHOLDERS))
        d = defaultdict(set)
        for r in pm["rows"]:
            if "ER" in (r.get("fields_placeholder") or []):
                d[r["pitcher_id"]].add(r["date"])
        _cache.update(d)
        _cache.setdefault("__loaded__", True)
    return _cache.get(pid, set())


def selftest():
    import pandas as pd
    f = []
    df = pd.DataFrame({
        "game_pk": [1, 1, 1, 1, 1, 1],
        "game_date": ["2026-08-20"] * 6,
        "top_bottom": ["Top"] * 6,
        "pitcher_id": [99, 99, 99, 99, 99, 99],
        "at_bat_number": [0, 0, 1, 2, 3, 4],
        "events": ["strikeout", "strikeout", "walk", "field_out",
                   "grounded_into_double_play", "weird_event"],
    })
    day, rej = derive_day(df)
    r = day[("99", "2026-08-20")]
    if r["tbf"] != 4:
        f.append("tbf wrong: %r" % r)
    if r["so"] != 1 or r["bb"] != 1:
        f.append("so/bb wrong: %r" % r)
    if r["outs"] != 4:
        f.append("outs wrong (K + out + GIDP=2): %r" % r)
    if not r["gs"]:
        f.append("first PA of the half did not mark GS")
    if rej.get("unknown_event:weird_event") != 1:
        f.append("unknown event not rejected explicitly")
    # Selftests must not depend on the session-local /home/user/lancebroz clone or mutable
    # live-log append state. After official boxscore repair, zero appendable archive rows is a
    # legitimate healthy state. Registered refresh artifacts test archive coverage separately.
    if CUTOFF != "2026-09-01" or INGEST_FROM > CUTOFF:
        f.append(f"PIT window constants invalid: {INGEST_FROM=} {CUTOFF=}")
    if OUTS.get("grounded_into_double_play") != 2 or "strikeout" not in SO_EVENTS:
        f.append("event classification constants drifted")
    if not os.path.exists(PLACEHOLDERS):
        f.append("placeholder manifest missing")
    else:
        pm = json.load(open(PLACEHOLDERS))
        if not isinstance(pm.get("rows"), list):
            f.append("placeholder manifest rows malformed")
    print("%s selftest: %s" % (MODULE_ID, "PASS" if not f else "FAIL"))
    for x in f:
        print("  -", x)
    return not f


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    write = "--write" in sys.argv
    rep = run(write=write)
    rep["mode"] = "WRITE" if write else "DRY_RUN"
    print(json.dumps({k: v for k, v in rep.items() if k != "appended"}, indent=1))
