#!/usr/bin/env python3
"""RESULT BINDING — a final is gradable only when it is bound to the SCHEDULED GAME, not a matchup.

THE DEFECT THIS MODULE EXISTS TO PREVENT (2026-08-27, owner-caught).

The end-of-night review graded the 8/27 MLB board against five finals that were actually the
8/26 finals of the SAME MATCHUPS. Every wrong score was the prior day's game of a continuing
series:

    BAL@STL  graded BAL 8-7   <- 8/26 final   actual 8/27: STL 7-5
    HOU@NYY  graded NYY 9-3   <- 8/26 final   actual 8/27: HOU 5-1
    KC@TOR   graded TOR 3-0   <- 8/26 final   actual 8/27: KC 13-2
    MIL@NYM  graded MIL 8-1   <- 8/26 final   actual 8/27: MIL 8-2
    LAD@ATL  graded ATL 6-5   <- 8/26 final   actual 8/27: ATL 1-0

The join was keyed on (away_team, home_team) with no date or game-id requirement. In baseball
that key is NOT unique: a three-game series repeats the same matchup on consecutive days. The
contamination flipped the headline completely — the active path read 5-1 when it was 2-5, and
both side crossovers read as a 1-1 split when they were 0-2.

WHY THE GAME_PK ALONE IS NOT ENOUGH EITHER. Consecutive-series gamePks are ADJACENT integers:

    8/26 KC@TOR  822772      8/27 KC@TOR  822771
    8/26 HOU@NYY 823506      8/27 HOU@NYY 823503
    8/26 LAD@ATL 824878      8/27 LAD@ATL 824879

A one-digit transcription slip lands on the neighbouring day's game of the same series and every
team name still agrees. So the gate requires the pk to match the BOARD's pk for that game AND
the dates to agree AND the matchup to agree — each check can catch what the others miss.

THE CONTRACT. A result row is gradable only with all five identity fields:

    sport + canonical_game_id/game_pk + scheduled_date + away_team + home_team

and it is REFUSED when:

    result_date != board_slate_date              RESULT_DATE_MISMATCH
    same matchup carrying a previous-date game   PRIOR_DATE_SERIES_JOIN
    game_pk unmatched in the board               GAME_PK_UNMATCHED
    game_pk matches more than one board game     GAME_PK_AMBIGUOUS
    final timestamp precedes scheduled start     FINAL_PRECEDES_START
    any aggregate touching a refused row         AGGREGATE_TOUCHES_REFUSED_ROW

The last one is the reason this is a gate and not a linter: the 8/27 damage was not the five bad
rows, it was the RECORDS, BRIER SCORES AND P&L computed over them. An aggregate is refused whole;
there is no partial credit for the rows that happened to be clean.

Usage: python3 harness/result_binding_gate.py [--selftest] [--mutants]
"""
from __future__ import annotations

MODULE_ID = "result_binding_gate"

import datetime as dt
import json
import os
import sys

REQUIRED_FIELDS = ("sport", "game_pk", "scheduled_date", "away", "home")

MISSING_FIELD = "MISSING_IDENTITY_FIELD"
RESULT_DATE_MISMATCH = "RESULT_DATE_MISMATCH"
SCHEDULED_DATE_MISMATCH = "SCHEDULED_DATE_MISMATCH"
PRIOR_DATE_SERIES_JOIN = "PRIOR_DATE_SERIES_JOIN"
GAME_PK_UNMATCHED = "GAME_PK_UNMATCHED"
GAME_PK_AMBIGUOUS = "GAME_PK_AMBIGUOUS"
GAME_PK_MISMATCH_FOR_MATCHUP = "GAME_PK_MISMATCH_FOR_MATCHUP"
MATCHUP_MISMATCH = "MATCHUP_MISMATCH"
FINAL_PRECEDES_START = "FINAL_PRECEDES_START"
AGGREGATE_REFUSED = "AGGREGATE_TOUCHES_REFUSED_ROW"
OK = "BOUND"


def _utc(value):
    if value is None:
        return None
    try:
        p = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return p if p.tzinfo else p.replace(tzinfo=dt.timezone.utc)


def bind_row(row, board):
    """Bind ONE result row to a board game. Returns (ok, code, detail).

    board: {"sport", "slate_date", "games": {game_key: {"game_pk", "away", "home",
            "start_utc"}}}
    """
    problems = []
    for f in REQUIRED_FIELDS:
        if row.get(f) in (None, "", "TBD"):
            problems.append({"code": MISSING_FIELD, "field": f})
    if problems:
        return False, problems

    if str(row["sport"]).lower() != str(board.get("sport", "")).lower():
        problems.append({"code": MATCHUP_MISMATCH, "detail": "sport differs from board"})
        return False, problems

    pk = str(row["game_pk"])
    matches = [k for k, g in board["games"].items() if str(g["game_pk"]) == pk]
    if len(matches) > 1:
        problems.append({"code": GAME_PK_AMBIGUOUS, "game_pk": pk, "matched": sorted(matches)})
        return False, problems

    matchup = [k for k, g in board["games"].items()
               if g["away"] == row["away"] and g["home"] == row["home"]]

    if not matches:
        # The pk is not on this board. If the MATCHUP is, this is the dangerous case: a
        # same-series game from another date wearing the right team names.
        if matchup:
            r_date = str(row.get("result_date") or row["scheduled_date"])
            code = (PRIOR_DATE_SERIES_JOIN if r_date < str(board["slate_date"])
                    else GAME_PK_MISMATCH_FOR_MATCHUP)
            problems.append({"code": code, "game_pk": pk,
                             "board_game_pk": board["games"][matchup[0]]["game_pk"],
                             "row_date": r_date, "board_slate_date": board["slate_date"],
                             "detail": "matchup is on the board but this is a different game; a "
                                       "repeated series makes (away,home) a non-unique key"})
        else:
            problems.append({"code": GAME_PK_UNMATCHED, "game_pk": pk})
        return False, problems

    key = matches[0]
    g = board["games"][key]

    if g["away"] != row["away"] or g["home"] != row["home"]:
        problems.append({"code": MATCHUP_MISMATCH, "game_pk": pk,
                         "board": f'{g["away"]}@{g["home"]}',
                         "row": f'{row["away"]}@{row["home"]}'})

    if str(row["scheduled_date"]) != str(board["slate_date"]):
        problems.append({"code": SCHEDULED_DATE_MISMATCH,
                         "row": str(row["scheduled_date"]), "board": str(board["slate_date"])})

    r_date = row.get("result_date")
    if r_date is not None and str(r_date) != str(board["slate_date"]):
        code = (PRIOR_DATE_SERIES_JOIN if str(r_date) < str(board["slate_date"])
                else RESULT_DATE_MISMATCH)
        problems.append({"code": code, "result_date": str(r_date),
                         "board_slate_date": str(board["slate_date"])})

    final_utc, start_utc = _utc(row.get("final_utc")), _utc(g.get("start_utc"))
    if final_utc and start_utc and final_utc < start_utc:
        problems.append({"code": FINAL_PRECEDES_START,
                         "final_utc": str(row.get("final_utc")),
                         "scheduled_start_utc": str(g.get("start_utc"))})

    return (not problems), (problems or [{"code": OK, "game_key": key}])


def bind_cohort(rows, board):
    """Bind a whole cohort. Returns {"bound": [...], "refused": [...], "gradable": bool}."""
    bound, refused = [], []
    for i, row in enumerate(rows):
        ok, detail = bind_row(row, board)
        (bound if ok else refused).append({"index": i, "row": row, "detail": detail})
    return {"bound": bound, "refused": refused, "gradable": not refused,
            "n_rows": len(rows), "n_bound": len(bound), "n_refused": len(refused)}


def aggregate_guard(binding, statistic_name):
    """An aggregate over a cohort containing ANY refused row is itself refused.

    This is the check that would have stopped the 8/27 damage: five bad rows became a record, a
    Brier score and a P&L, and those derived numbers are what reached the reader.
    """
    if binding["refused"]:
        return False, {"code": AGGREGATE_REFUSED, "statistic": statistic_name,
                       "n_refused": binding["n_refused"],
                       "refused_codes": sorted({p["code"] for r in binding["refused"]
                                                for p in r["detail"]}),
                       "detail": "no partial credit: the aggregate is refused whole until every "
                                 "row binds or is explicitly excluded with a recorded reason"}
    return True, {"code": OK, "statistic": statistic_name, "n_rows": binding["n_bound"]}


# =================================================================================================
# FIXTURES — the real 8/27 board and the real 8/26 finals that contaminated it.
BOARD_0827 = {
    "sport": "mlb", "slate_date": "2026-08-27",
    "games": {
        "mlb:COL@WSH": {"game_pk": 822694, "away": "COL", "home": "WSH",
                        "start_utc": "2026-08-27T17:05:00Z"},
        "mlb:BAL@STL": {"game_pk": 823014, "away": "BAL", "home": "STL",
                        "start_utc": "2026-08-27T18:15:00Z"},
        "mlb:HOU@NYY": {"game_pk": 823503, "away": "HOU", "home": "NYY",
                        "start_utc": "2026-08-27T23:05:00Z"},
        "mlb:KC@TOR": {"game_pk": 822771, "away": "KC", "home": "TOR",
                       "start_utc": "2026-08-27T23:07:00Z"},
        "mlb:MIL@NYM": {"game_pk": 823581, "away": "MIL", "home": "NYM",
                        "start_utc": "2026-08-27T23:10:00Z"},
        "mlb:LAD@ATL": {"game_pk": 824879, "away": "LAD", "home": "ATL",
                        "start_utc": "2026-08-27T23:15:00Z"},
        "mlb:AZ@SF": {"game_pk": 825038, "away": "AZ", "home": "SF",
                      "start_utc": "2026-08-28T01:45:00Z"},
    },
}

#: the five 8/26 finals (with their real 8/26 gamePks) that were graded as 8/27 results
CONTAMINATED_0826_ROWS = [
    {"sport": "mlb", "game_pk": 823015, "scheduled_date": "2026-08-26", "result_date":
     "2026-08-26", "away": "BAL", "home": "STL", "away_score": 8, "home_score": 7},
    {"sport": "mlb", "game_pk": 823506, "scheduled_date": "2026-08-26", "result_date":
     "2026-08-26", "away": "HOU", "home": "NYY", "away_score": 3, "home_score": 9},
    {"sport": "mlb", "game_pk": 822772, "scheduled_date": "2026-08-26", "result_date":
     "2026-08-26", "away": "KC", "home": "TOR", "away_score": 0, "home_score": 3},
    {"sport": "mlb", "game_pk": 823584, "scheduled_date": "2026-08-26", "result_date":
     "2026-08-26", "away": "MIL", "home": "NYM", "away_score": 8, "home_score": 1},
    {"sport": "mlb", "game_pk": 824878, "scheduled_date": "2026-08-26", "result_date":
     "2026-08-26", "away": "LAD", "home": "ATL", "away_score": 5, "home_score": 6},
]

#: the true 8/27 finals, which must all bind
CLEAN_0827_ROWS = [
    {"sport": "mlb", "game_pk": 822694, "scheduled_date": "2026-08-27", "result_date":
     "2026-08-27", "away": "COL", "home": "WSH", "away_score": 1, "home_score": 7},
    {"sport": "mlb", "game_pk": 823014, "scheduled_date": "2026-08-27", "result_date":
     "2026-08-27", "away": "BAL", "home": "STL", "away_score": 5, "home_score": 7},
    {"sport": "mlb", "game_pk": 823503, "scheduled_date": "2026-08-27", "result_date":
     "2026-08-27", "away": "HOU", "home": "NYY", "away_score": 5, "home_score": 1},
    {"sport": "mlb", "game_pk": 822771, "scheduled_date": "2026-08-27", "result_date":
     "2026-08-27", "away": "KC", "home": "TOR", "away_score": 13, "home_score": 2},
    {"sport": "mlb", "game_pk": 823581, "scheduled_date": "2026-08-27", "result_date":
     "2026-08-27", "away": "MIL", "home": "NYM", "away_score": 8, "home_score": 2},
    {"sport": "mlb", "game_pk": 824879, "scheduled_date": "2026-08-27", "result_date":
     "2026-08-27", "away": "LAD", "home": "ATL", "away_score": 0, "home_score": 1},
    {"sport": "mlb", "game_pk": 825038, "scheduled_date": "2026-08-27", "result_date":
     "2026-08-27", "away": "AZ", "home": "SF", "away_score": 1, "home_score": 6},
]


def consecutive_series_fixture():
    """THE fixture: feed the prior day's five same-matchup finals into the 8/27 cohort.

    All five must be refused, and every one must be refused as a PRIOR_DATE_SERIES_JOIN — not as
    some generic mismatch. Naming the failure mode is the point: 'unmatched id' would invite a
    future maintainer to 'fix' it by loosening the id check, which is exactly the bug.
    """
    b = bind_cohort(CONTAMINATED_0826_ROWS, BOARD_0827)
    codes = [{p["code"] for p in r["detail"]} for r in b["refused"]]
    all_refused = b["n_refused"] == 5 and b["n_bound"] == 0
    all_named = all(PRIOR_DATE_SERIES_JOIN in c for c in codes)
    agg_ok, agg = aggregate_guard(b, "winner_record")
    return all_refused and all_named and not agg_ok, b, agg


def selftest():
    f = []

    # 1. THE consecutive-series test
    passed, b, agg = consecutive_series_fixture()
    if not passed:
        f.append(f"consecutive-series fixture did not refuse all five as prior-date joins: "
                 f"{b['n_refused']}/5 refused")
    if agg["code"] != AGGREGATE_REFUSED:
        f.append("an aggregate over the contaminated cohort was not refused")

    # 2. the true finals all bind, and the aggregate is permitted
    cb = bind_cohort(CLEAN_0827_ROWS, BOARD_0827)
    if not cb["gradable"] or cb["n_bound"] != 7:
        f.append(f"clean 8/27 cohort failed to bind ({cb['n_bound']}/7): "
                 f"{[r['detail'] for r in cb['refused']][:2]}")
    ok, _ = aggregate_guard(cb, "winner_record")
    if not ok:
        f.append("a fully bound cohort must permit its aggregate")

    # 3. the adjacent-pk slip: right teams, right dates, neighbouring series pk. Refused as a
    #    pk mismatch (the dates are honest here; only the id is wrong).
    slip = dict(CLEAN_0827_ROWS[3], game_pk=822772)      # KC@TOR 8/27 carrying 8/26's pk
    ok, det = bind_row(slip, BOARD_0827)
    if ok or GAME_PK_MISMATCH_FOR_MATCHUP not in {p["code"] for p in det}:
        f.append(f"an adjacent-series pk with correct teams was not refused: {det}")

    # 3b. the same slip with the prior date attached is named a prior-date series join
    slip2 = dict(slip, scheduled_date="2026-08-26", result_date="2026-08-26")
    ok, det = bind_row(slip2, BOARD_0827)
    if ok or PRIOR_DATE_SERIES_JOIN not in {p["code"] for p in det}:
        f.append(f"a prior-date adjacent-pk row was not named a series join: {det}")

    # 4. each identity field is load-bearing. The field names are LITERAL here on purpose: an
    #    earlier version looped over REQUIRED_FIELDS itself, so a mutant that DELETED a field
    #    from that constant was never tested for it — a fixture comparing against the constant
    #    it polices (the recurring self-referential-fixture defect). The contract is the five
    #    names below, not whatever the constant happens to hold.
    for field in ("sport", "game_pk", "scheduled_date", "away", "home"):
        if field not in REQUIRED_FIELDS:
            f.append(f"{field} was dropped from the identity contract")
            continue
        row = dict(CLEAN_0827_ROWS[0])
        row[field] = None
        ok, det = bind_row(row, BOARD_0827)
        if ok or not any(p["code"] == MISSING_FIELD for p in det):
            f.append(f"a row missing {field} was accepted")

    # 5. result_date drift in the FORWARD direction is refused too (not just prior-date)
    fwd = dict(CLEAN_0827_ROWS[0], result_date="2026-08-28")
    ok, det = bind_row(fwd, BOARD_0827)
    if ok or not any(p["code"] == RESULT_DATE_MISMATCH for p in det):
        f.append("a next-day result_date was accepted")

    # 6. a final that precedes its scheduled start is refused
    early = dict(CLEAN_0827_ROWS[6], final_utc="2026-08-28T01:00:00Z")   # AZ@SF starts 01:45Z
    ok, det = bind_row(early, BOARD_0827)
    if ok or not any(p["code"] == FINAL_PRECEDES_START for p in det):
        f.append("a final timestamp preceding first pitch was accepted")

    # 7. ambiguity is refused rather than resolved by picking one
    dup_board = {**BOARD_0827, "games": {**BOARD_0827["games"],
                                         "mlb:DUP": {"game_pk": 822694, "away": "COL",
                                                     "home": "WSH", "start_utc": None}}}
    ok, det = bind_row(CLEAN_0827_ROWS[0], dup_board)
    if ok or not any(p["code"] == GAME_PK_AMBIGUOUS for p in det):
        f.append("an ambiguous game_pk was resolved instead of refused")

    # 8. a pk from another sport/board entirely is unmatched, not silently joined by teams
    ok, det = bind_row(dict(CLEAN_0827_ROWS[0], game_pk=999999, away="XXX", home="YYY"),
                       BOARD_0827)
    if ok or not any(p["code"] == GAME_PK_UNMATCHED for p in det):
        f.append("an unknown game was not refused as unmatched")

    # 9. ONE bad row poisons the aggregate — the 8/27 damage pattern exactly
    mixed = bind_cohort(CLEAN_0827_ROWS[:6] + [CONTAMINATED_0826_ROWS[0]], BOARD_0827)
    ok, _ = aggregate_guard(mixed, "brier")
    if ok:
        f.append("an aggregate over six clean rows plus one contaminated row was permitted")

    print("result_binding_gate selftest:", "FAIL" if f else
          "PASS (consecutive-series join refused 5/5 by name; adjacent-pk slip, date drift both "
          "directions, pre-start final, ambiguity, missing identity fields and poisoned "
          "aggregates all refused; the true 8/27 cohort binds 7/7)")
    for x in f:
        print("   -", x)
    return 1 if f else 0


def mutation_suite(verbose=True):
    """Each mutant disables one protection; every mutant must be caught by selftest()."""
    import copy
    mutants = []

    def run(name, patch):
        orig = {}
        for k, v in patch.items():
            orig[k] = globals()[k]
            globals()[k] = v
        try:
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                caught = selftest() != 0
        finally:
            globals().update(orig)
        mutants.append((name, caught))
        if verbose:
            print(f"  {'caught' if caught else 'ESCAPED'}  {name}")

    # M1: drop the date requirement from the row contract (the original bug)
    run("REQUIRED_FIELDS without scheduled_date",
        {"REQUIRED_FIELDS": ("sport", "game_pk", "away", "home")})

    # M2: bind by matchup when the pk misses (the original bug, in join form)
    def _lenient(row, board):
        for k, g in board["games"].items():
            if g["away"] == row.get("away") and g["home"] == row.get("home"):
                return True, [{"code": OK, "game_key": k}]
        return False, [{"code": GAME_PK_UNMATCHED}]
    run("bind_row falls back to a matchup join", {"bind_row": _lenient})

    # M3: aggregates take partial credit
    run("aggregate_guard allows partial credit",
        {"aggregate_guard": lambda binding, s: (True, {"code": OK, "statistic": s})})

    escaped = [n for n, c in mutants if not c]
    print(f"result_binding_gate mutation suite: {len(mutants) - len(escaped)}/{len(mutants)} "
          f"caught" + (f"; ESCAPED: {escaped}" if escaped else ""))
    return not escaped


def gate():
    """Healthcheck entry point: prove the fixtures still hold."""
    passed, b, _ = consecutive_series_fixture()
    cb = bind_cohort(CLEAN_0827_ROWS, BOARD_0827)
    ok = passed and cb["gradable"]
    print(f"result-binding gate: {'PASS' if ok else 'FAIL'} "
          f"(consecutive-series {b['n_refused']}/5 refused; clean cohort {cb['n_bound']}/7 bound)")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--mutants" in sys.argv:
        sys.exit(0 if mutation_suite() else 1)
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--gate" in sys.argv:
        sys.exit(gate())
    print(__doc__)
