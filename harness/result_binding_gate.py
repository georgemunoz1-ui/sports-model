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

REQUIRED_FIELDS = ("sport", "game_pk", "scheduled_date", "result_date", "away", "home")

#: A final may legitimately land hours after first pitch (extras, rain delay). It may NOT land
#: after the NEXT game of the same series has started — that is the contamination in temporal
#: form. 18h is comfortably past any single game and short of a next-day first pitch. A genuinely
#: suspended-and-resumed game must say so explicitly rather than ride the lag allowance.
MAX_FINAL_LAG_HOURS = 18.0

MISSING_FIELD = "MISSING_IDENTITY_FIELD"
RESULT_DATE_MISMATCH = "RESULT_DATE_MISMATCH"
SCHEDULED_DATE_MISMATCH = "SCHEDULED_DATE_MISMATCH"
PRIOR_DATE_SERIES_JOIN = "PRIOR_DATE_SERIES_JOIN"
GAME_PK_UNMATCHED = "GAME_PK_UNMATCHED"
GAME_PK_AMBIGUOUS = "GAME_PK_AMBIGUOUS"
GAME_PK_MISMATCH_FOR_MATCHUP = "GAME_PK_MISMATCH_FOR_MATCHUP"
MATCHUP_MISMATCH = "MATCHUP_MISMATCH"
FINAL_PRECEDES_START = "FINAL_PRECEDES_START"
FINAL_TOO_LATE_AFTER_START = "FINAL_TOO_LATE_AFTER_START"
BOARD_PK_NOT_A_REAL_IDENTIFIER = "BOARD_PK_NOT_A_REAL_IDENTIFIER"
DOUBLEHEADER_NEEDS_GAME_NUMBER = "DOUBLEHEADER_NEEDS_GAME_NUMBER"
DUPLICATE_BINDING = "DUPLICATE_BINDING_TWO_ROWS_ONE_GAME"
COHORT_COVERAGE_INCOMPLETE = "COHORT_COVERAGE_INCOMPLETE"
EVIDENCE_SCORE_DISAGREEMENT = "EVIDENCE_SCORE_DISAGREEMENT"
TEAMS_REVERSED = "TEAMS_REVERSED"
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

    # A board pk that is itself a placeholder makes the pk check circular: any row echoing the
    # placeholder "matches". The board's identifier must be a real one.
    if str(g["game_pk"]).strip().upper() in ("", "NONE", "TBD", "NULL", "0", "PENDING"):
        problems.append({"code": BOARD_PK_NOT_A_REAL_IDENTIFIER, "board_game_pk": g["game_pk"],
                         "game_key": key})
        return False, problems

    # Doubleheader siblings share sport, teams and BOTH dates, so every check except the pk
    # collapses. When the board holds more than one game for this matchup and date, the row must
    # state which one it is rather than relying on the pk alone.
    siblings = [k for k, x in board["games"].items()
                if x["away"] == row["away"] and x["home"] == row["home"]]
    if len(siblings) > 1:
        rn, bn = row.get("game_number"), g.get("game_number")
        if rn in (None, "") or bn in (None, "") or str(rn) != str(bn):
            problems.append({"code": DOUBLEHEADER_NEEDS_GAME_NUMBER, "game_key": key,
                             "siblings": sorted(siblings), "row_game_number": rn,
                             "board_game_number": bn})
            return False, problems

    if g["away"] != row["away"] or g["home"] != row["home"]:
        # Reversed teams get their own name: it is a transcription/relay error that flips home
        # advantage, the score assignment AND the winner, and "matchup mismatch" reads like a
        # different game rather than the same game backwards.
        reversed_ = (g["away"] == row["home"] and g["home"] == row["away"])
        problems.append({"code": TEAMS_REVERSED if reversed_ else MATCHUP_MISMATCH,
                         "game_pk": pk,
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
    if final_utc and start_utc:
        lag_h = (final_utc - start_utc).total_seconds() / 3600.0
        if lag_h < 0:
            problems.append({"code": FINAL_PRECEDES_START,
                             "final_utc": str(row.get("final_utc")),
                             "scheduled_start_utc": str(g.get("start_utc"))})
        elif lag_h > MAX_FINAL_LAG_HOURS and not row.get("suspended_resumed"):
            # B2: unbounded lag let the NEXT day's game of the same series bind cleanly.
            problems.append({"code": FINAL_TOO_LATE_AFTER_START, "lag_hours": round(lag_h, 2),
                             "ceiling_hours": MAX_FINAL_LAG_HOURS,
                             "detail": "a final this long after first pitch is either the next "
                                       "game of the series or a suspended game; a genuine "
                                       "resumption must set suspended_resumed with a reason"})

    # Identity binding proves WHICH game. It does not prove the scores are that game's scores.
    # A relay can carry the right identity and the wrong numbers — which is one keystroke from the
    # original defect. When retained evidence is supplied, the scores must agree with it.
    ev = (board.get("evidence") or {}).get(str(pk)) or (board.get("evidence") or {}).get(pk)
    if ev:
        for side in ("home_score", "away_score"):
            if side in ev and side in row and str(ev[side]) != str(row[side]):
                problems.append({"code": EVIDENCE_SCORE_DISAGREEMENT, "game_pk": pk,
                                 "field": side, "row": row.get(side), "evidence": ev[side],
                                 "detail": "the row binds to this game but its score disagrees "
                                           "with the retained evidence for it"})

    return (not problems), (problems or [{"code": OK, "game_key": key}])


def bind_cohort(rows, board, require_full_coverage=True):
    """Bind a whole cohort.

    Row-level binding is not enough. Two failure shapes live only at cohort level and both
    produced published numbers on 2026-08-27:

      WRONG SCORE       a row binds to the wrong game            -> caught by bind_row
      WRONG DENOMINATOR two rows bind the SAME game, or the      -> caught only here
                        cohort covers only part of the board

    A record, a Brier score and a P&L are all denominators. "5-1" was wrong partly because the
    seventh game had not finished; a cohort that silently grades six of seven is the same class of
    error as a cohort that grades the wrong six.
    """
    bound, refused = [], []
    for i, row in enumerate(rows):
        ok, detail = bind_row(row, board)
        (bound if ok else refused).append({"index": i, "row": row, "detail": detail})

    cohort_problems = []
    seen = {}
    for b in bound:
        gk = b["detail"][0].get("game_key")
        seen.setdefault(gk, []).append(b["index"])
    for gk, idxs in sorted(seen.items()):
        if len(idxs) > 1:
            cohort_problems.append({"code": DUPLICATE_BINDING, "game_key": gk, "rows": idxs,
                                    "detail": "two result rows bound to one scheduled game; a "
                                              "makeup, a doubleheader half or a duplicated relay"})
    if require_full_coverage:
        missing = sorted(set(board["games"]) - set(seen))
        if missing:
            cohort_problems.append({"code": COHORT_COVERAGE_INCOMPLETE, "missing": missing,
                                    "n_board_games": len(board["games"]), "n_bound": len(seen),
                                    "detail": "an aggregate over a partial cohort reports a "
                                              "denominator it did not earn; exclude explicitly "
                                              "with require_full_coverage=False and say why"})

    cohort_problems.extend(_id_space_problems(board))

    return {"bound": bound, "refused": refused,
            "cohort_problems": cohort_problems,
            "gradable": not refused and not cohort_problems,
            "n_rows": len(rows), "n_bound": len(bound), "n_refused": len(refused)}


def _id_space_problems(board):
    """Catch a board that MIXES namespaced canonical_ids with bare integers.

    The placeholder guard in bind_row rejects "", "TBD", "NULL", "0" and "PENDING" — values that
    announce themselves as empty. It does NOT reject a FABRICATED integer, and that is the shape
    that actually caused damage: every MLB slate through 2026-08-27 opened each row with an
    invented 827000-series key that looks exactly like a real gamePk. Nothing about "827003"
    tells the gate it was made up, so a row echoing it "matched" and the pk check was circular in
    a way no placeholder list could see.

    From 2026-08-28 boards carry "<ID_SPACE>:<integer>". That form is self-describing, and it makes
    the migration hazard checkable: once ANY game on a board is namespaced, a bare integer on the
    SAME board means a pseudo-pk survived the migration. Mixing is refused at cohort level, so it
    blocks every aggregate rather than quietly degrading one row.

    A board that is entirely un-namespaced is left alone — legacy boards are frozen under R3 and
    must stay bindable — but a fully namespaced board is held to the stronger contract.
    """
    pks = {k: str(g.get("game_pk", "")) for k, g in board["games"].items()}
    namespaced = {k for k, v in pks.items() if ":" in v}
    if not namespaced or len(namespaced) == len(pks):
        return []
    bare = sorted(k for k in pks if k not in namespaced)
    return [{"code": BOARD_PK_NOT_A_REAL_IDENTIFIER,
             "detail": "this board mixes namespaced canonical_ids with bare integers. Once a "
                       "board declares the namespaced form, a bare integer on it is a surviving "
                       "synthetic pseudo-pk (the 827000-series contract) — an identifier that "
                       "cannot bind a result but will happily 'match' a row that echoes it.",
             "namespaced_games": sorted(namespaced), "bare_games": bare,
             "bare_values": {k: pks[k] for k in bare}}]


def aggregate_guard(binding, statistic_name):
    """An aggregate over a cohort containing ANY refused row is itself refused.

    This is the check that would have stopped the 8/27 damage: five bad rows became a record, a
    Brier score and a P&L, and those derived numbers are what reached the reader.
    """
    cohort = binding.get("cohort_problems") or []
    if binding["refused"] or cohort:
        return False, {"code": AGGREGATE_REFUSED, "statistic": statistic_name,
                       "n_refused": binding["n_refused"],
                       "refused_codes": sorted({p["code"] for r in binding["refused"]
                                                for p in r["detail"]}
                                               | {c["code"] for c in cohort}),
                       "cohort_problems": cohort,
                       "detail": "no partial credit: the aggregate is refused whole until every "
                                 "row binds, no two rows claim one game, and the cohort covers "
                                 "the board or is explicitly narrowed with a recorded reason"}
    return True, {"code": OK, "statistic": statistic_name, "n_rows": binding["n_bound"]}


# =================================================================================================
# FIXTURES — the real 8/27 board and the real 8/26 finals that contaminated it.
#
# PK PROVENANCE, DECLARED. Five of the seven 8/27 gamePks below were CAPTURED from mlb.com gameday
# URL slugs during the day's checkpoints and are recorded in the audit trail. Two were NOT: BAL@STL
# and AZ@SF were first written into this fixture by DECREMENTING the 8/26 pk (823015 -> 823014,
# 825039 -> 825038) — which is the exact adjacent-pk inference this module exists to forbid,
# committed inside the module's own fixture. They were labelled SYNTHETIC_UNVERIFIED rather than
# quietly left to read as ground truth, and the 2026-08-28 archive check RESOLVED both: 823014
# was right, 825038 was WRONG and is replaced by the real 823179. One of two inferences failed. The refusal logic does not depend on their real-world truth (the
# CONTAMINATED rows carry real 8/26 pks from the evidence extract, which is what the primary
# fixture tests) — but an unverified number sitting in a gate fixture is exactly how the next
# contamination starts.
PK_PROVENANCE = {
    822694: "CAPTURED mlb.com slug (COL@WSH), T-45 record 3f3fef17",
    823503: "CAPTURED mlb.com slug (HOU@NYY), schedule record b9717911",
    822771: "CAPTURED mlb.com slug (KC@TOR), T-90 record 4645b5a3",
    823581: "CAPTURED mlb.com slug (MIL@NYM), night review",
    824879: "CAPTURED mlb.com slug (LAD@ATL), schedule record b9717911",
    823014: "ARCHIVE_VERIFIED 2026-08-28 (lancebroz f9bca28, 8/27 daily parquet) — the earlier "
            "inference from 8/26 pk 823015 was CORRECT, now confirmed rather than assumed",
    823179: "ARCHIVE_VERIFIED 2026-08-28 (lancebroz f9bca28, 8/27 daily parquet). REPLACES the "
            "inferred 825038, which was WRONG: decremented from 825039 = CHC@AZ, a DIFFERENT "
            "matchup, and no game 825038 exists on 8/27 at all. One of the two inferences was "
            "wrong — which is exactly why an inferred id is a fabrication even when plausible.",
}

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
        "mlb:AZ@SF": {"game_pk": 823179, "away": "AZ", "home": "SF",
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
    {"sport": "mlb", "game_pk": 823179, "scheduled_date": "2026-08-27", "result_date":
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

    # 0. every fixture pk declares its provenance, and unverified ones are labelled as such.
    #    A gate fixture that carries an undeclared number is a contamination vector itself.
    for _k, g in BOARD_0827["games"].items():
        p = PK_PROVENANCE.get(g["game_pk"])
        if not p:
            f.append(f"fixture pk {g['game_pk']} ({_k}) has no declared provenance")
        elif not p.startswith(("CAPTURED", "ARCHIVE_VERIFIED", "SYNTHETIC_UNVERIFIED")):
            f.append(f"fixture pk {g['game_pk']} provenance is neither captured nor labelled")
    for r in CONTAMINATED_0826_ROWS:
        if r["game_pk"] not in (823015, 823506, 822772, 823584, 824878):
            f.append(f"contaminated fixture pk {r['game_pk']} is not one of the real 8/26 pks")

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

    # ---- BYPASS REGRESSION FIXTURES (adversarial audit, 2026-08-28) ----------------------
    # Every one of these returned BOUND against the first version of this gate. They are the
    # reason cohort-level checks exist at all: four of the six were invisible row-by-row.

    # B1: omitting result_date was MORE permissive than stating it honestly. This exact row —
    #     the published wrong KC@TOR final, carrying the correct 8/27 pk — bound cleanly.
    b1 = {"sport": "mlb", "game_pk": 822771, "scheduled_date": "2026-08-27",
          "away": "KC", "home": "TOR", "away_score": 0, "home_score": 3}
    ok, det = bind_row(b1, BOARD_0827)
    if ok or not any(p["code"] == MISSING_FIELD and p.get("field") == "result_date"
                     for p in det):
        f.append(f"B1: a row omitting result_date was accepted: {det}")

    # B2: a final 27h after first pitch is the NEXT game of the series, not this one.
    b2 = dict(CLEAN_0827_ROWS[3], final_utc="2026-08-29T02:41:00Z")
    ok, det = bind_row(b2, BOARD_0827)
    if ok or not any(p["code"] == FINAL_TOO_LATE_AFTER_START for p in det):
        f.append(f"B2: a final 27h after first pitch was accepted: {det}")
    # ... but an explicitly declared suspended-and-resumed game is allowed through
    ok, det = bind_row(dict(b2, suspended_resumed="rain, resumed next day"), BOARD_0827)
    if not ok:
        f.append("B2: an explicitly declared suspended resumption was refused")

    # B3a: two rows binding ONE board game — a makeup game, a doubleheader half, or a duplicated
    #      relay. Every row is individually clean; only the cohort sees it.
    dup = bind_cohort(CLEAN_0827_ROWS + [dict(CLEAN_0827_ROWS[1], home_score=8, away_score=7)],
                      BOARD_0827)
    if dup["gradable"] or not any(c["code"] == DUPLICATE_BINDING
                                  for c in dup["cohort_problems"]):
        f.append("B3a: two rows binding one game were not detected")
    ok, _ = aggregate_guard(dup, "winner_record")
    if ok:
        f.append("B3a: an aggregate over a double-bound cohort was permitted")

    # B3b: a partial cohort is a wrong DENOMINATOR — the "5-1" shape, as opposed to the wrong
    #      score shape. Grading 3 of 7 games must not silently produce a record.
    part = bind_cohort(CLEAN_0827_ROWS[:3], BOARD_0827)
    if part["gradable"] or not any(c["code"] == COHORT_COVERAGE_INCOMPLETE
                                   for c in part["cohort_problems"]):
        f.append("B3b: a 3-of-7 cohort was gradable")
    ok, _ = aggregate_guard(part, "brier")
    if ok:
        f.append("B3b: an aggregate over a partial cohort was permitted")
    # an explicitly narrowed cohort is allowed — the caller must say so
    if not bind_cohort(CLEAN_0827_ROWS[:3], BOARD_0827,
                       require_full_coverage=False)["gradable"]:
        f.append("B3b: an explicitly narrowed cohort was refused anyway")

    # B4: doubleheader siblings share every identity field except the pk, so the pk stops being
    #     corroborated. The row must declare its game number.
    dh_board = {"sport": "mlb", "slate_date": "2026-08-27", "games": {
        "mlb:KC@TOR:G1": {"game_pk": 822771, "away": "KC", "home": "TOR",
                          "game_number": 1, "start_utc": "2026-08-27T23:07:00Z"},
        "mlb:KC@TOR:G2": {"game_pk": 822773, "away": "KC", "home": "TOR",
                          "game_number": 2, "start_utc": "2026-08-28T02:37:00Z"}}}
    ok, det = bind_row(CLEAN_0827_ROWS[3], dh_board)          # no game_number on the row
    if ok or not any(p["code"] == DOUBLEHEADER_NEEDS_GAME_NUMBER for p in det):
        f.append(f"B4: a doubleheader row without a game number was accepted: {det}")
    ok, _ = bind_row(dict(CLEAN_0827_ROWS[3], game_number=1), dh_board)
    if not ok:
        f.append("B4: a correctly numbered doubleheader row was refused")

    # B5: a placeholder pk on the BOARD makes the pk check circular — anything echoing it binds.
    ph_board = {"sport": "mlb", "slate_date": "2026-08-27", "games": {
        "mlb:AAA@BBB": {"game_pk": "TBD", "away": "AAA", "home": "BBB", "start_utc": None}}}
    ok, det = bind_row({"sport": "mlb", "game_pk": "TBD", "scheduled_date": "2026-08-27",
                        "result_date": "2026-08-27", "away": "AAA", "home": "BBB"}, ph_board)
    if ok:
        f.append("B5: a placeholder board pk was treated as an identifier")

    # B6: reversed teams — same game, backwards. Flips home advantage, score assignment AND winner.
    ok, det = bind_row(dict(CLEAN_0827_ROWS[0], away="WSH", home="COL"), BOARD_0827)
    if ok or not any(p["code"] == TEAMS_REVERSED for p in det):
        f.append(f"B6: a reversed-team row was not refused by name: {det}")

    # B7: identity right, SCORES wrong. Binding proves which game, not which numbers.
    ev_board = {**BOARD_0827,
                "evidence": {"822771": {"away_score": 13, "home_score": 2}}}   # true KC@TOR 8/27
    ok, det = bind_row(dict(CLEAN_0827_ROWS[3], away_score=0, home_score=3), ev_board)
    if ok or not any(p["code"] == EVIDENCE_SCORE_DISAGREEMENT for p in det):
        f.append(f"B7: a row whose scores contradict retained evidence was accepted: {det}")
    if not bind_row(CLEAN_0827_ROWS[3], ev_board)[0]:
        f.append("B7: the true row was refused against its own evidence")

    # B8: a FUTURE-day result is refused as firmly as a prior-day one (both directions of drift).
    fut = dict(CLEAN_0827_ROWS[3], scheduled_date="2026-08-28", result_date="2026-08-28")
    ok, det = bind_row(fut, BOARD_0827)
    if ok or not any(p["code"] in (RESULT_DATE_MISMATCH, SCHEDULED_DATE_MISMATCH) for p in det):
        f.append(f"B8: a next-day result bound to this board: {det}")

    # B9: a SURVIVING SYNTHETIC PSEUDO-PK. B5 only catches identifiers that announce themselves
    #     empty ("TBD", "0", ""). It cannot catch a fabricated INTEGER, and that is the form that
    #     actually shipped: every MLB slate through 8/27 keyed its rows on invented 827000-series
    #     values. From 8/28 boards are namespaced, which makes the mixture detectable — a bare
    #     integer sitting beside a namespaced id is a pseudo-pk that survived the migration.
    mixed_board = {"sport": "mlb", "slate_date": "2026-08-28", "games": {
        "mlb:BOS@NYY": {"game_pk": "MLB_GAMEPK:823504", "away": "BOS", "home": "NYY",
                        "start_utc": "2026-08-28T23:15:00Z"},
        "mlb:CIN@CHC": {"game_pk": "827001", "away": "CIN", "home": "CHC",     # <- pseudo-pk
                        "start_utc": "2026-08-28T18:20:00Z"}}}
    mixed_rows = [
        {"sport": "mlb", "game_pk": "MLB_GAMEPK:823504", "scheduled_date": "2026-08-28",
         "result_date": "2026-08-28", "away": "BOS", "home": "NYY"},
        {"sport": "mlb", "game_pk": "827001", "scheduled_date": "2026-08-28",
         "result_date": "2026-08-28", "away": "CIN", "home": "CHC"},
    ]
    mixed = bind_cohort(mixed_rows, mixed_board)
    if mixed["gradable"]:
        f.append("B9: a board mixing a namespaced id with a synthetic 827000-series pseudo-pk "
                 "was gradable — every row bound, because a fabricated integer 'matches' the row "
                 "that echoes it")
    if not any(c["code"] == BOARD_PK_NOT_A_REAL_IDENTIFIER for c in mixed["cohort_problems"]):
        f.append(f"B9: the surviving pseudo-pk was not named: {mixed['cohort_problems']}")
    ok, _ = aggregate_guard(mixed, "winner_record")
    if ok:
        f.append("B9: an aggregate over a board carrying a surviving pseudo-pk was permitted")
    # a fully namespaced board of the same shape must still grade — the check targets the MIXTURE,
    # not the namespace, so it cannot become a blanket refusal of the new form
    clean_ns = {"sport": "mlb", "slate_date": "2026-08-28", "games": {
        "mlb:BOS@NYY": {"game_pk": "MLB_GAMEPK:823504", "away": "BOS", "home": "NYY",
                        "start_utc": "2026-08-28T23:15:00Z"},
        "mlb:CIN@CHC": {"game_pk": "ESPN_GAMEID:401816711", "away": "CIN", "home": "CHC",
                        "start_utc": "2026-08-28T18:20:00Z"}}}
    clean_rows = [mixed_rows[0], dict(mixed_rows[1], game_pk="ESPN_GAMEID:401816711")]
    if not bind_cohort(clean_rows, clean_ns)["gradable"]:
        f.append("B9: a fully namespaced board was refused — the check must target the mixture, "
                 "not the namespaced form itself")
    # and a fully LEGACY board must still bind: frozen boards are immutable under R3 and cannot
    # be migrated, so making the new form mandatory would strand every historical cohort
    if not bind_cohort(CLEAN_0827_ROWS, BOARD_0827)["gradable"]:
        f.append("B9: the legacy un-namespaced 8/27 board stopped binding")

    print("result_binding_gate selftest:", "FAIL" if f else
          "PASS (consecutive-series join refused 5/5 by name; adjacent-pk slip, date drift both "
          "directions, pre-start final, ambiguity, missing identity fields, surviving synthetic "
          "pseudo-pks and poisoned aggregates all refused; the true 8/27 cohort binds 7/7)")
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

    # M4: result_date optional again (the B1 bypass, restored)
    run("REQUIRED_FIELDS without result_date",
        {"REQUIRED_FIELDS": ("sport", "game_pk", "scheduled_date", "away", "home")})

    # M5: unbounded final lag (the B2 bypass, restored)
    run("MAX_FINAL_LAG_HOURS unbounded", {"MAX_FINAL_LAG_HOURS": 1e9})

    # M6: cohort-level checks removed (the B3 bypasses, restored)
    def _no_cohort(rows, board, require_full_coverage=True):
        bound, refused = [], []
        for i, row in enumerate(rows):
            ok, detail = bind_row(row, board)
            (bound if ok else refused).append({"index": i, "row": row, "detail": detail})
        return {"bound": bound, "refused": refused, "cohort_problems": [],
                "gradable": not refused, "n_rows": len(rows), "n_bound": len(bound),
                "n_refused": len(refused)}
    run("bind_cohort without injectivity or coverage", {"bind_cohort": _no_cohort})

    # M8: the surviving-pseudo-pk check neutered (the B9 bypass, restored). A mutant that returns
    #     no problems is what "we added the check but it never fires" looks like from the outside.
    run("_id_space_problems never reports a mixed board",
        {"_id_space_problems": lambda board: []})

    # M7: evidence-score verification removed (the B7 bypass, restored)
    _real_bind = bind_row
    def _no_evidence(row, board):
        return _real_bind(row, {k: v for k, v in board.items() if k != "evidence"})
    run("bind_row ignores retained evidence scores", {"bind_row": _no_evidence})

    escaped = [n for n, c in mutants if not c]
    print(f"result_binding_gate mutation suite: {len(mutants) - len(escaped)}/{len(mutants)} "
          f"caught" + (f"; ESCAPED: {escaped}" if escaped else ""))
    return not escaped


def binding_proof(rows, board, cohort_label):
    """The artifact a results card must be able to show, and the counters it must print.

    A card that says "2-5" is asserting a denominator. This makes the denominator auditable:
    every row is listed with the game it bound to and why, refusals are enumerated rather than
    dropped, and the four counters the owner requires are computed here rather than typed by hand.
    """
    b = bind_cohort(rows, board)
    per = []
    for item in b["bound"] + b["refused"]:
        d = item["detail"][0]
        per.append({"index": item["index"],
                    "row": {k: item["row"].get(k) for k in
                            ("sport", "game_pk", "scheduled_date", "result_date", "away", "home",
                             "away_score", "home_score")},
                    "bound_to": d.get("game_key"),
                    "codes": [p["code"] for p in item["detail"]]})
    per.sort(key=lambda x: x["index"])
    n = len(rows)
    n_bound = b["n_bound"]
    date_ok = sum(1 for i in b["bound"]
                  if str(i["row"].get("result_date")) == str(board["slate_date"])
                  and str(i["row"].get("scheduled_date")) == str(board["slate_date"]))
    id_ok = sum(1 for i in b["bound"] if i["detail"][0].get("game_key"))
    return {
        "schema": "ops.binding_proof.v1",
        "cohort": cohort_label,
        "board_slate_date": board["slate_date"],
        "sport": board.get("sport"),
        "counters": {
            "RESULT_BINDING_PASS": f"{n_bound}/{n}",
            "DATE_COHERENCE_PASS": f"{date_ok}/{n}",
            "CANONICAL_ID_MATCH": f"{id_ok}/{n}",
            "REFUSED_ROWS": (0 if not b["refused"] else
                             [{"index": r["index"], "codes": [p["code"] for p in r["detail"]]}
                              for r in b["refused"]]),
        },
        "gradable": b["gradable"],
        "cohort_problems": b["cohort_problems"],
        "rows": per,
        "rule": "a single failed row blocks every aggregate over this cohort; no partial metric "
                "may silently exclude or substitute it",
    }


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
