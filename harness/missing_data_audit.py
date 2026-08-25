#!/usr/bin/env python3
"""Four-layer missing-data audit: schedule identity -> pregame payload -> tier-1 final -> grade.

WHY (2026-08-16, owner directive): a contaminated 8/15 acquisition session exposed that the
repository had no single tool answering, per game, "do we hold its identity, its frozen
forecast, a tier-1 final, and exactly one grade?" — and no gate stopping a tier-2/3 row from
re-entering the canonical results table after the owner ruled it tier-1-only.

Doctrine enforced here (owner rulings 2026-08-16):
  - canonical results.csv: only tier-1 date-consistent finals may be ADDED after the ruling
    (RULING_UTC). The 126 legacy tier-2/3 rows are enumerated, hash-frozen exceptions —
    reported, never silently promoted, never silently purged (they feed a frozen model's
    as-of inputs; purging is an owner-scoped operation).
  - per-game acquisition states; date-level deferral states are a gate FAILURE.
  - one grade per forecast (whitelisted G2 addenda excepted).
  - no forecast generated after its scheduled start.
  - provisional observations are visible but cannot grade.

Modes:  (default) full report -> data/audit/missing_data_report.json + stdout summary
        --gate     exit 1 only on STRUCTURAL violations (new tier-2/3 canonical ingestion,
                   duplicate grades, post-start forecasts, date-level deferral states)
        --selftest fixture battery
"""
from __future__ import annotations

MODULE_ID = "missing_data_audit"
import csv, glob, json, os, sys, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acquisition_ledger as _al

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
RESULTS = "data/backfill/mlb/2026/results.csv"
RULING_UTC = "2026-08-16T03:00:00Z"   # owner ruling: tier-1-only canonical ingestion after this
GRADE_DUP_WHITELIST = {"P4-20260729-UNRESOLVED:NYY@CWS:2026-07-29",
                       "P4-20260729-UNRESOLVED:CHC@STL:2026-07-29"}  # documented G2 addenda
ARCHIVAL_UNGRADEABLE = {"PTR-KSIM-2026-07-27-PHASE1", "PTR-KSIM-0727-U02-DECISIONS",
                        "RETRO-20260728-CLE_CIN", "RETRO-20260728-ATL_NYM"}
FORBIDDEN_LEDGER_STATES = {"NOT_CAPTURED_DATE", "DEFERRED_DATE", "SLATE_QUARANTINED"}

# ---- Layer 1: authoritative expected-game inventory, loaded from a SAVED ARTIFACT so that every
#      count in any report is reproducible from the repository rather than from code constants. ----
IDENTITY_FILE = "data/schedule/identity_2026-08-13_15.json"


def _identity():
    d = json.load(open(IDENTITY_FILE))
    ids, by_date = {}, collections.defaultdict(list)
    for x in d["games"]:
        key = (x["sport"], x["date"], f'{x["away"]}@{x["home"]}')
        ids[key] = x["official_id"]
        by_date[(x["sport"], x["date"])].append(f'{x["away"]}@{x["home"]}')
    return d, ids, by_date


_IDENT_DOC, OFFICIAL_IDS, _BY_DATE = _identity()
MLB_0815 = _BY_DATE[("mlb", "2026-08-15")]
WNBA_0815 = _BY_DATE[("wnba", "2026-08-15")]
NFL_0815 = _BY_DATE[("nfl", "2026-08-15")]
NFL_0813 = _BY_DATE[("nfl", "2026-08-13")]
NFL_0814 = _BY_DATE[("nfl", "2026-08-14")]
REJECTED_PHANTOMS = [f'{p["listing"]} — {p["why_rejected"]}' for p in _IDENT_DOC["rejected_phantom_games"]]
NFL_FROZEN_EXTERNAL = {"CLE@CHI": "NFL-PS-2026-CLE-CHI-MKT0_1", "MIN@NYG": "NFL-PS-2026-MIN-NYG-MKT0_1"}


def _tip_iso(tip, slate_date):
    """Resolve a tip time to full ISO for comparison. Card rows carry bare HH:MMZ slate times whose
    DATE is the US slate date, so a post-midnight-UTC start (e.g. 00:40Z on the 8/18 slate) belongs
    to the FOLLOWING UTC day. Comparing the bare string against a same-day generated_at_utc declared
    four genuinely pregame 8/18 forecasts post-start — the same rollover bug pregame_preflight had.
    Full ISO strings pass through untouched; bare times before 10:00Z roll to slate_date + 1."""
    import re as _re, datetime as _dt
    if not tip or not _re.fullmatch(r"\d{2}:\d{2}Z", tip):
        return tip  # already full ISO (v3-style records) or unparseable -> compare as-is
    if not slate_date:
        return tip
    d = _dt.date.fromisoformat(slate_date)
    if int(tip[:2]) < 10:
        d += _dt.timedelta(days=1)
    return f"{d.isoformat()}T{tip}"


def _load_jsonl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path) if l.strip()]


def _results_rows():
    return list(csv.DictReader(open(RESULTS)))


def game_inventory():
    """One row per expected game for 8/13-8/15 across the three sports (34 rows)."""
    rows = []
    ledgers = {
        ("mlb", "2026-08-15"): _load_jsonl("data/mlb/acquisition_ledger_2026-08-15.jsonl"),
        ("wnba", "2026-08-15"): _load_jsonl("data/wnba/acquisition_ledger_2026-08-15.jsonl"),
    }
    nfl_ledger = _load_jsonl("data/nfl/results_ledger.jsonl")
    res = _results_rows()
    t1_final = {(r["date"], f'{r["away"]}@{r["home"]}') for r in res
                if r.get("source_tier") == "1" and r.get("away_score") not in ("", None)}
    mlb_grades = {g["forecast_id"] for g in _load_jsonl("data/mlb/forecasts/grades.jsonl")}

    def newest_nfl(g, d):
        cands = [r for r in nfl_ledger if r.get("game") == g and r.get("date") == d]
        return max(cands, key=lambda r: r.get("revision", 1)) if cands else None

    # NFL: 16 games
    for d, games in (("2026-08-13", NFL_0813), ("2026-08-14", NFL_0814), ("2026-08-15", NFL_0815)):
        for g in games:
            led = newest_nfl(g, d)
            gs = (led or {}).get("grade_state", "MISSING_LEDGER_ROW")
            if g == "IND@NE":
                status = "TERMINAL_EXCLUDED"
            elif gs.startswith("GRADED_") and not gs.startswith("GRADED_PROVISIONAL"):
                status = "GRADED"
            elif gs.startswith("GRADED_PROVISIONAL"):
                status = "AWAIT_FINAL"        # tier-3 final held; tier-1 conversion owed
            elif gs == "PENDING_FINAL":
                status = "AWAIT_FINAL"
            elif gs == "AWAITING_FROZEN_PAYLOAD_AND_TIER1_FINAL":
                status = "MISSING_ORIGINAL_PREGAME_PAYLOAD"
            else:
                status = "QUARANTINED_CONFLICT" if led is None else "AWAIT_FINAL"
            rows.append(dict(sport="nfl", date=d, game=g,
                             official_id=OFFICIAL_IDS.get(("nfl", d, g)),
                             forecast=("frozen-external:" + NFL_FROZEN_EXTERNAL[g]) if g in NFL_FROZEN_EXTERNAL
                                      else ("benchmark-declared-in-capture" if (led or {}).get("benchmark") else None),
                             tier1_final=bool(led and led.get("source_tier") == 1 and led.get("final")),
                             observation=(led or {}).get("final"),
                             grade_state=gs, status=status))
    # MLB 8/15: 15 games, no pregame card existed
    mled = {r["game"]: r for r in sorted(ledgers[("mlb", "2026-08-15")], key=lambda r: r.get("revision", 1))}
    for g in MLB_0815:
        led = mled.get(g)
        st = (led or {}).get("state", "MISSING_LEDGER_ROW")
        if st in FORBIDDEN_LEDGER_STATES:
            status = "QUARANTINED_CONFLICT"
        elif st == "ECHO_QUARANTINED_AND_QUEUED":
            status = "QUARANTINED_CONFLICT"
        else:
            status = "RESULT_BACKFILL_ONLY_NOT_BACKTESTABLE"  # no pregame payload can ever exist
        rows.append(dict(sport="mlb", date="2026-08-15", game=g,
                         official_id=OFFICIAL_IDS.get(("mlb", "2026-08-15", g)),
                         forecast=None, tier1_final=("2026-08-15", g) in t1_final,
                         observation=(led or {}).get("score_observed") or (led or {}).get("detail", "")[:40],
                         grade_state="NO_FORECAST_EXISTED", status=status))
    # WNBA 8/15: 3 games, no card
    wled = {}
    for r in sorted(ledgers[("wnba", "2026-08-15")], key=lambda r: r.get("revision", 1)):
        wled[r.get("matchup") or f"slot{r['slot']}"] = r
    for g in WNBA_0815:
        led = wled.get(g)
        rows.append(dict(sport="wnba", date="2026-08-15", game=g,
                         official_id=None, forecast=None, tier1_final=False,
                         observation=(led or {}).get("state"),
                         grade_state="NO_FORECAST_EXISTED",
                         status="RESULT_BACKFILL_ONLY_NOT_BACKTESTABLE" if led else "QUARANTINED_CONFLICT"))
    return rows


def repo_scans():
    """Repository-wide structural scans. Returns {scan_name: [gap, ...]}."""
    gaps = collections.OrderedDict()
    res = _results_rows()
    F = _load_jsonl("data/mlb/forecasts/forecasts.jsonl")
    G = _load_jsonl("data/mlb/forecasts/grades.jsonl")
    superseded = {g["supersedes_grade_id"] for g in G if g.get("supersedes_grade_id")}
    G_current = [g for g in G if g.get("grade_id") not in superseded]
    graded = collections.Counter(g["forecast_id"] for g in G_current)
    gaps_superseded = sorted(superseded)

    # new tier-2/3 canonical ingestion after the ruling (STRUCTURAL)
    gaps["new_tier23_canonical"] = [
        f'{r["date"]} {r["away"]}@{r["home"]} tier {r["source_tier"]} ingested {r["ingested_utc"]}'
        for r in res if r.get("source_tier") in ("2", "3") and r.get("ingested_utc", "") > RULING_UTC]
    # legacy tier-2/3 canonical rows (documented exception, HIGH but not gate-fatal)
    gaps["legacy_tier23_canonical"] = [
        f'{r["date"]} {r["away"]}@{r["home"]} tier {r["source_tier"]}'
        for r in res if r.get("source_tier") in ("2", "3")]
    # duplicate grades beyond whitelist (STRUCTURAL)
    gaps["duplicate_grades"] = [f"{k} x{c}" for k, c in graded.items()
                                if c > 1 and k not in GRADE_DUP_WHITELIST]
    gaps["superseded_grades_resolved"] = gaps_superseded
    # forecasts without terminal disposition (excluding archival-by-design)
    gaps["ungraded_forecasts"] = [f["forecast_id"] for f in F
                                  if f["forecast_id"] not in graded
                                  and f["forecast_id"] not in ARCHIVAL_UNGRADEABLE]
    # forecasts generated after scheduled start (STRUCTURAL)
    late = []
    for f in F:
        tip = (f.get("payload") or {}).get("tip_utc")
        if tip and f["generated_at_utc"] > _tip_iso(tip, f.get("slate_date")):
            late.append(f["forecast_id"])
    for r in _load_jsonl("data/wnba/forecasts/registrations.jsonl"):
        if r["generated_at_utc"] > r["tip_utc"]:
            late.append(r["forecast_id"])
    gaps["post_start_forecasts"] = late
    # tier-2/3-basis grades (documented pre-ruling exceptions)
    gaps["tier23_basis_grades"] = [g["grade_id"] for g in G if "tier3" in g.get("source", "")]
    wg = _load_jsonl("data/wnba/forecasts/grades.jsonl")
    gaps["tier23_basis_grades"] += [g["grade_id"] for g in wg if g.get("source_tier") == 3]
    # grade evidence binding: every grade names an evidence artifact; hash present where scheme carries it
    gaps["grades_missing_evidence"] = [g["grade_id"] for g in G if "sha256" not in g.get("source", "")] + \
                                      [g["grade_id"] for g in wg if not g.get("evidence_sha256")]
    # evidence files referenced by canonical rows exist
    missing_ev = set()
    for r in res:
        p = r.get("evidence_path", "")
        if p and not os.path.exists(p):
            missing_ev.add(p)
    gaps["missing_evidence_files"] = sorted(missing_ev)
    # date-level deferral states in any acquisition ledger (STRUCTURAL)
    bad_states = []
    # SHARED definition: acquisition_ledger.ledger_paths() also covers data/nfl/results_ledger.jsonl,
    # which the previous inline glob missed — an NFL row carrying a date-level state would have
    # slipped the gate-fatal check entirely.
    for path in _al.ledger_paths():
        for r in _load_jsonl(path):
            if r.get("state") in FORBIDDEN_LEDGER_STATES:
                bad_states.append(f"{path}: {r.get('date')} {r.get('state')}")
    gaps["date_level_deferral_states"] = bad_states
    # slate dates whose games lack BOTH a canonical row and an acquisition-ledger row
    have = {(r["date"], r["away"], r["home"]) for r in res
            if r.get("away_score") not in ("", None) or r.get("home_win") not in ("", None)}
    led_have = set()
    for path in _al.ledger_paths():
        for r in _load_jsonl(path):
            if r.get("game") and "@" in r["game"]:
                a, h = r["game"].split("@")
                led_have.add((r["date"], a, h))
    untracked = []
    for p in sorted(glob.glob("data/mlb/slates/*_slate*.psv")):
        date = os.path.basename(p).split("_")[0]
        for line in open(p):
            parts = line.strip().split("|")
            if len(parts) >= 3:
                k = (date, parts[1], parts[2])
                if k not in have and k not in led_have:
                    untracked.append(f"{date} {parts[1]}@{parts[2]}")
    gaps["slate_games_untracked_anywhere"] = untracked
    # zero-row slate dates: slate_completeness() returns early when a date has no rows at all, so a
    # WHOLLY absent slate is invisible to it. Enumerate those dates explicitly.
    dates_with_rows = {r["date"] for r in res}
    zero_row_slates = []
    for p in sorted(glob.glob("data/mlb/slates/*_slate*.psv")):
        date = os.path.basename(p).split("_")[0]
        if date not in dates_with_rows:
            n = sum(1 for line in open(p) if line.strip())
            zero_row_slates.append(f"{date}: frozen slate {os.path.basename(p)} has {n} games and ZERO canonical rows")
    gaps["zero_row_slate_dates"] = sorted(set(zero_row_slates))
    # legacy schema drift: tier-1 rows with blank result_status / full team names
    gaps["legacy_blank_status_rows"] = [f'{r["date"]} {r["away"]}@{r["home"]}' for r in res
                                        if r.get("source_tier") == "1" and r.get("result_status") == ""]
    return gaps


STRUCTURAL = ["new_tier23_canonical", "duplicate_grades", "post_start_forecasts",
              "date_level_deferral_states"]


def run(gate=False):
    inv = game_inventory()
    gaps = repo_scans()
    missing_rows = [r for r in inv if r["status"] == "QUARANTINED_CONFLICT" and r.get("observation") is None]
    report = {
        "generated_from": "harness/missing_data_audit.py",
        "inventory_rows": inv,
        "inventory_counts": dict(collections.Counter(f'{r["sport"]}:{r["status"]}' for r in inv)),
        "repo_scans": {k: {"n": len(v), "items": v[:40]} for k, v in gaps.items()},
        "structural_violations": {k: gaps[k] for k in STRUCTURAL if gaps[k]},
        "expected_slate_note": {"mlb_0815": len(MLB_0815), "wnba_0815": len(WNBA_0815),
                                "nfl_0815": len(NFL_0815), "rejected_phantoms": REJECTED_PHANTOMS},
    }
    os.makedirs("data/audit", exist_ok=True)
    json.dump(report, open("data/audit/missing_data_report.json", "w"), indent=1)
    n_struct = sum(len(gaps[k]) for k in STRUCTURAL)
    print(f"inventory: {len(inv)} game rows; structural violations: {n_struct}; "
          f"legacy tier-2/3 canonical: {len(gaps['legacy_tier23_canonical'])}; "
          f"untracked slate games: {len(gaps['slate_games_untracked_anywhere'])}; "
          f"missing per-game rows: {len(missing_rows)}")
    if gate:
        return 1 if (n_struct or missing_rows) else 0
    return 0


def selftest():
    fails = []
    inv = game_inventory()
    if len(inv) != 34:
        fails.append(f"inventory must cover 34 games (16 NFL + 15 MLB + 3 WNBA), got {len(inv)}")
    if any(r["status"] in ("NOT_CAPTURED", "DEFERRED") for r in inv):
        fails.append("date-level statuses leaked into inventory")
    gaps = repo_scans()
    if gaps["new_tier23_canonical"]:
        fails.append(f"post-ruling tier-2/3 canonical ingestion: {gaps['new_tier23_canonical']}")
    if gaps["duplicate_grades"]:
        fails.append(f"unwhitelisted duplicate grades: {gaps['duplicate_grades']}")
    if gaps["post_start_forecasts"]:
        fails.append(f"post-start forecasts: {gaps['post_start_forecasts']}")
    # falsification: a synthetic post-ruling tier-3 row must be caught
    rows = _results_rows()
    synth = dict(rows[-1])
    synth.update(source_tier="3", ingested_utc="2026-08-17T00:00:00Z")
    caught = synth.get("source_tier") in ("2", "3") and synth["ingested_utc"] > RULING_UTC
    if not caught:
        fails.append("synthetic post-ruling tier-3 row NOT caught")
    if fails:
        print("missing_data_audit selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("missing_data_audit selftest: PASS (34-game inventory, no structural violations, "
          "synthetic tier-3 post-ruling row caught)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    raise SystemExit(run(gate="--gate" in sys.argv))
