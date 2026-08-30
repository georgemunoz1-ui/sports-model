#!/usr/bin/env python3
"""PERMANENT REGRESSION FIXTURES for the score-admission isolation layer.

WHY THIS FILE EXISTS. Two publications, three weeks apart, put scores on a board that no feed had
ever returned.

  2026-08-27  Five MLB finals were PUBLISHED from a summary of web search results. No feed was
              consulted, no game id was bound, no status field was read.
  2026-08-30  13:30 ET, a web search returned three more confident MLB finals:
                "Nationals 9, Marlins 2"   MIA@WSH first pitch 12:15 ET -> 75 minutes into a game
                                           that needs about 170
                "Yankees 1, Red Sox 0"     BOS@NYY first pitch 13:35 ET -> HAD NOT STARTED
                "Braves 6, Rockies 4"      COL@ATL first pitch 13:35 ET -> HAD NOT STARTED
              All three were refused BY HAND. Nothing in code refused them, because nothing in
              code was asked.

Separately, and on the same day, a FROZEN artifact
(cards/2026-08-30_pregame_board_v6_canonical.json, game MIN @ ATL) published the board's only LEAN
on a spread row whose entry.price_american is null, whose 14.3pp edge is measured against an
ASSUMED market_no_vig_cover_pct of 50.0, and whose implied projected margin (+2.60 for ATL) has
the OPPOSITE SIGN to the margin implied by its own moneyline row (-3.65 for ATL) in the same game.

The modules that answer all of that are score_admission.py (the contract), score_collector.py (the
canonical lane), verified_snapshot.py (the immutable store) and board_invariants.py (the
pre-publication gate). This file is the regression suite for the TEN failures the owner named. It
proves the guards fire on the real inputs, and — this is the part the repo keeps having to relearn
— it proves the fixtures would NOTICE if the guards were removed.

WHAT MAKES A FIXTURE HERE LEGITIMATE. Three rules, each written after a specific defect:

  1. A fixture asserts a DISPOSITION and a set of REASON CODES, never "something was rejected".
     A generic refusal invites a future maintainer to "fix" it by loosening the wrong check.
     result_binding_gate.consecutive_series_fixture states the same rule for the same reason:
     "'unmatched id' would invite a future maintainer to 'fix' it by loosening the id check,
     which is exactly the bug."

  2. Every fixture has a GUARD in the GUARDS table below, and the meta-test removes that guard
     from the subject's source and requires THAT fixture to fail. A fixture that still passes
     with its guard removed is testing nothing. The precedent is on file: the 8/27 board carried
     counters that could not fail, and wnba_refresh_espn returned True with no artifact present.

  3. A missing dependency is a FAILURE, never a skip. harness/board_invariants.py,
     harness/score_collector.py and harness/verified_snapshot.py were written in parallel with
     this file; if one is not importable the fixtures that need it FAIL and NAME it. A skipped
     regression fixture and a passing one are the same number in a healthcheck exit code, which
     is how a module stays green while doing nothing.

RUNNABLE TWO WAYS, and the selftest is the primary one:
    python3 harness/test_score_admission.py --selftest      (healthcheck wiring)
    pytest harness/test_score_admission.py                  (when pytest is importable)
pytest is available in this deployment today. It is not depended on: a module that only ran under
pytest went undetected here for a whole delivery, so nothing in the selftest path imports it.

Usage: python3 harness/test_score_admission.py [--selftest] [--mutants] [--gate]
"""
from __future__ import annotations

MODULE_ID = "test_score_admission"

import hashlib
import importlib
import json
import math
import os
import shutil
import statistics
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# Flat imports after the sys.path insert — the established idiom (feed_sweep, test_feed_adapter).
# There is no "harness." package on sys.path and inventing one here would fork the convention.
import score_admission as sa                    # noqa: E402  THE contract
import freshness_contract as fc                 # noqa: E402  grade / staleness vocabulary
import result_binding_gate as rbg               # noqa: E402  the PRIOR_DATE_SERIES_JOIN hazard

#: This file reaches nothing. Declared rather than assumed, the way the other new modules declare
#: it; test_egress_discipline asserts the flag is literally True or False wherever it is present.
ALLOW_DIRECT_HTTP = False


# =============================================================================================
# 0. THE PARALLEL MODULES.  Absent means FAILURE, and the failure names the file.
# =============================================================================================

#: Written alongside this file. Each one owns fixtures below; none of them is optional.
PARALLEL_MODULES = ("verified_snapshot", "score_collector", "board_invariants")

_MODULES = {}
_IMPORT_ERRORS = {}
for _name in PARALLEL_MODULES:
    try:
        _MODULES[_name] = importlib.import_module(_name)
    except Exception as _e:                                   # noqa: BLE001 — record, never hide
        _IMPORT_ERRORS[_name] = "%s: %s" % (type(_e).__name__, _e)


def require_module(name):
    """The imported module, or an AssertionError that names the missing file.

    Deliberately NOT a skip. pytest.importorskip and a bare `return` both turn an absent subject
    into a green run, and this repo has already paid for that once: wnba_refresh_espn's selftest
    returned True with no artifact on disk, so absence is a FAILURE here by precedent.
    """
    mod = _MODULES.get(name)
    if mod is None:
        raise AssertionError(
            "MISSING_SUBJECT harness/%s.py is not importable (%s). The fixture that raised this "
            "asserts behaviour owned by that module, so it FAILS rather than skipping: a skipped "
            "regression fixture and a passing one produce the same healthcheck exit code."
            % (name, _IMPORT_ERRORS.get(name, "no import error recorded")))
    return mod


# =============================================================================================
# 1. THE INCIDENT CLOCK.  Every instant below is the real one, in UTC, never sliced.
# =============================================================================================

NOW_1330ET = "2026-08-30T17:30:00Z"    # the moment the three finals arrived
START_1335ET = "2026-08-30T17:35:00Z"  # BOS@NYY and COL@ATL first pitch — FIVE MINUTES LATER
START_1215ET = "2026-08-30T16:15:00Z"  # MIA@WSH first pitch — 75 minutes earlier
EVENING = "2026-08-31T02:00:00Z"       # 22:00 ET on 08-30 — past every window used below, and
                                       # itself an ET-crossing instant: this is the EVENING of
                                       # 08-30, not 08-31. Slicing the UTC string is what
                                       # corrupted a cohort twice.
NEXT_DAY = "2026-08-31T17:10:00Z"      # the postponed game's makeup slot

PRIOR_DAY_START = "2026-08-29T16:15:00Z"   # the SAME matchup, one day earlier

#: The frozen board carrying the convergence defect. Read, never rewritten (R3, R6).
CANONICAL_BOARD_PATH = os.path.join(REPO, "cards", "2026-08-30_pregame_board_v6_canonical.json")
MIN_ATL_EVENT_ID = "wnba_min_atl_2026-08-30"

#: The injury report the 2026-08-30 search actually returned for Atlanta: late July, 32 days old.
ATL_INJURY_OBSERVED_AT = "2026-07-29T12:00:00Z"
ATL_INJURY_SUBJECT = "wnba:ATL:availability:2026-08-30"


def _rec(event_id, away, home, start, status, away_score=None, home_score=None,
         league="MLB", source="mlb_statsapi", fetched=None, **extra):
    """One normalized record. terminal_verified and the content hash are GENERATED, never typed.

    Built here rather than imported from score_admission._rec on purpose: a fixture that shares
    its subject's private constructor cannot catch that constructor drifting. The field names
    come from sa.RECORD_FIELDS and are asserted against it in test_meta.
    """
    r = {"event_id": event_id, "league": league, "away_team_id": away, "home_team_id": home,
         "scheduled_start_utc": start, "status": status,
         "away_score": away_score, "home_score": home_score,
         "terminal_verified": sa.terminal_verified_for(status),
         "source": source, "source_fetched_at_utc": fetched or NOW_1330ET,
         "raw_response_sha256": hashlib.sha256(
             ("%s|%s|%s|%s|%s|%s" % (event_id, start, status, away_score, home_score, source)
              ).encode()).hexdigest()}
    r.update(extra)
    return r


def _entry(event_id, away, home, start, league="MLB", **extra):
    e = {"event_id": event_id, "league": league, "away_team_id": away, "home_team_id": home,
         "scheduled_start_utc": start}
    e.update(extra)
    return e


def _codes(verdict):
    return set(verdict.reason_codes)


def _load_min_atl_game():
    """The MIN @ ATL game object, read out of the FROZEN artifact rather than retyped.

    Retyping it would let the fixture and the artifact drift apart, and the artifact is the thing
    under test. R3/R6: this file only ever reads those bytes.
    """
    if not os.path.isfile(CANONICAL_BOARD_PATH):
        raise AssertionError(
            "MISSING_SUBJECT %s is not on disk. The board fixtures assert against the FROZEN "
            "artifact that carries the defect; without it there is nothing to assert against."
            % CANONICAL_BOARD_PATH)
    with open(CANONICAL_BOARD_PATH) as fh:
        board = json.load(fh)
    for game in board.get("games") or []:
        if game.get("event_id") == MIN_ATL_EVENT_ID:
            return game
    raise AssertionError(
        "MISSING_SUBJECT %r is not in %s. The published defect row has moved or been renamed; "
        "these fixtures must be re-pointed at it deliberately, not silently."
        % (MIN_ATL_EVENT_ID, CANONICAL_BOARD_PATH))


def _min_atl_row(market):
    for row in _load_min_atl_game()["markets"]:
        if row.get("market") == market:
            return row
    raise AssertionError("MISSING_SUBJECT the MIN@ATL %s row is not in the frozen board" % market)


def implied_margin(probability, sigma):
    """The projected margin a win/cover probability implies under the board's own normal model.

    The board states its sigma in prose and nowhere else: the MIN@ATL SPREAD_RL note reads
    "cover p = Phi(5.1/13.97)". This is the inverse of that, so the two arms of one game can be
    compared in POINTS instead of in percents, which is the only way the contradiction is visible.
    """
    return statistics.NormalDist().inv_cdf(probability) * sigma


def cover_probability(margin, line, sigma):
    """P(margin + line > 0) — the board's own formula, forward. Phi((mu + line) / sigma)."""
    return 0.5 * (1.0 + math.erf(((margin + line) / sigma) / math.sqrt(2.0)))


# =============================================================================================
# 2. THE TEN FIXTURES.  One function per named failure.
# =============================================================================================

def test_future_game_with_confident_search_final():
    """FIXTURE 1. A final for a game that has not started.

    BOS@NYY, first pitch 2026-08-30T17:35Z. At 17:30Z — five minutes BEFORE first pitch — a web
    search returned "Yankees 1, Red Sox 0" as a final. COL@ATL, same first pitch, same shape,
    "Braves 6, Rockies 4".

    The disposition must be REJECT_PRESTART_OR_UNBOUND on the reason PRESTART_FINAL_IMPOSSIBLE,
    and it must be that on EVERY lane and with or without a canonical schedule, because a final
    before first pitch is not improbable, it is impossible. A CANONICAL provider asserting one is
    either buggy or pointed at the wrong game, and both of those must refuse.
    """
    schedule = sa.incident_schedule_0830()

    claims = [
        ("BOS@NYY 'Yankees 1, Red Sox 0'", sa.EID_BOSNYY, "SYNTH_BOS", "SYNTH_NYY", 0, 1),
        ("COL@ATL 'Braves 6, Rockies 4'", sa.EID_COLATL, "SYNTH_COL", "SYNTH_ATL", 4, 6),
    ]
    for label, eid, away, home, away_score, home_score in claims:
        for lane in (sa.LANE_SEARCH, sa.LANE_CANONICAL):
            for sched in (schedule, None):
                record = _rec(eid, away, home, START_1335ET, sa.CLOSED, away_score, home_score,
                              source="web_search" if lane == sa.LANE_SEARCH else "mlb_statsapi")
                v = sa.admit(record, now_utc=NOW_1330ET, canonical_schedule=sched, lane=lane)
                where = "%s lane=%s schedule=%s" % (label, lane, sched is not None)
                assert v.disposition == sa.REJECT_PRESTART_OR_UNBOUND, \
                    "%s: %s, expected REJECT_PRESTART_OR_UNBOUND" % (where, v.disposition)
                assert sa.REASON_PRESTART_FINAL_IMPOSSIBLE in _codes(v), \
                    "%s: reason codes %r do not name PRESTART_FINAL_IMPOSSIBLE" \
                    % (where, v.reason_codes)
                assert not v.admitted and not v.settleable, "%s: a pre-start final admitted" % where
                assert v.admissible_as is None, \
                    "%s: a pre-start final was given an admissible_as of %r" \
                    % (where, v.admissible_as)
                assert sa.sink_for(v) == sa.SINK_QUARANTINE, \
                    "%s: routed to %s, not quarantine" % (where, sa.sink_for(v))

    # The refusal states HOW EARLY it was, because "five minutes before first pitch" is the fact
    # that made this obvious to a human and invisible to the code.
    v = sa.admit(_rec(sa.EID_BOSNYY, "SYNTH_BOS", "SYNTH_NYY", START_1335ET, sa.CLOSED, 0, 1,
                      source="web_search"),
                 now_utc=NOW_1330ET, canonical_schedule=schedule, lane=sa.LANE_SEARCH)
    assert v.detail.get("minutes_before_start") == 5.0, \
        "the verdict does not record how far before first pitch the claim arrived: %r" \
        % (v.detail.get("minutes_before_start"),)

    # Owner rule 5, and the 2026-08-27 shape: a summary carries prose, not an identifier. With no
    # event id there is nothing to bind and the refusal must say THAT, not "pre-start" — the two
    # are different repairs.
    unbound = _rec(None, "SYNTH_BOS", "SYNTH_NYY", START_1335ET, sa.CLOSED, 0, 1,
                   source="web_search")
    v = sa.admit(unbound, now_utc=EVENING, canonical_schedule=schedule, lane=sa.LANE_SEARCH)
    assert v.disposition == sa.REJECT_PRESTART_OR_UNBOUND, \
        "a claim with no event id gave %s" % v.disposition
    assert sa.REASON_NO_EVENT_ID in _codes(v), \
        "the refusal does not say the claim carried no provider event id: %r" % (v.reason_codes,)
    for placeholder in ("", "TBD", "0", "DH1"):
        pv = sa.admit(_rec("mlb:2026:%s" % placeholder, "SYNTH_BOS", "SYNTH_NYY", START_1335ET,
                           sa.CLOSED, 0, 1, source="web_search"),
                      now_utc=EVENING, canonical_schedule=schedule, lane=sa.LANE_SEARCH)
        assert pv.disposition == sa.REJECT_PRESTART_OR_UNBOUND, \
            "placeholder id %r admitted as %s" % (placeholder, pv.disposition)
        assert {sa.REASON_EVENT_ID_PLACEHOLDER, sa.REASON_EVENT_ID_MALFORMED} & _codes(pv), \
            "placeholder id %r was refused without naming it a placeholder: %r" \
            % (placeholder, pv.reason_codes)

    # A pre-start claim with NO score and no terminal status is not a final and must not be
    # refused as one — otherwise the rule would reject the ordinary pre-game slate row.
    v = sa.admit(_rec(sa.EID_BOSNYY, "SYNTH_BOS", "SYNTH_NYY", START_1335ET, sa.SCHEDULED),
                 now_utc=NOW_1330ET, canonical_schedule=schedule, lane=sa.LANE_CANONICAL)
    assert v.disposition == sa.UNVERIFIED, \
        "a scheduled pre-game row with no score was refused as a pre-start FINAL: %s" % v.disposition
    assert sa.REASON_PRESTART_FINAL_IMPOSSIBLE not in _codes(v), \
        "the pre-start rule fired on a row that claimed nothing"


def test_live_game_incorrectly_labeled_final():
    """FIXTURE 2. A game 75 minutes into a ~170 minute game, reported as a final.

    MIA@WSH, first pitch 2026-08-30T16:15Z. At 17:30Z the search result said "Nationals 9,
    Marlins 2" — final. The game was IN_PROGRESS.

    Three separate guards have to hold, and this fixture asserts all three, because each one is
    load-bearing on its own:
      * with the canonical slate in hand, a search claim of terminal against a schedule entry that
        says IN_PROGRESS is REJECT_SCHEDULE_CONFLICT / CANONICAL_STATUS_CONTRADICTS_CLAIM;
      * with NO schedule (the 8/30 reality, both secondary sites EGRESS_BLOCKED), the temporal
        kill-switch holds it at UNVERIFIED_TOO_SOON and search can never clear it;
      * the canonical record for the same game admits as a SNAPSHOT, never as a final.
    ADMIT_FINAL must not appear anywhere in this fixture.
    """
    schedule = sa.incident_schedule_0830()
    search_claim = _rec(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", START_1215ET, sa.CLOSED,
                        2, 9, source="web_search")

    v = sa.admit(search_claim, now_utc=NOW_1330ET, canonical_schedule=schedule,
                 lane=sa.LANE_SEARCH)
    assert v.disposition == sa.REJECT_SCHEDULE_CONFLICT, \
        "a terminal search claim against an IN_PROGRESS slate gave %s" % v.disposition
    assert sa.REASON_CANONICAL_STATUS_CONTRADICTS_CLAIM in _codes(v), \
        "reason codes %r do not name the contradiction" % (v.reason_codes,)
    assert v.disposition != sa.ADMIT_FINAL and not v.admitted

    v_nosched = sa.admit(search_claim, now_utc=NOW_1330ET, canonical_schedule=None,
                         lane=sa.LANE_SEARCH)
    assert v_nosched.disposition == sa.UNVERIFIED_TOO_SOON, \
        "with no schedule the clock must still hold the claim: got %s" % v_nosched.disposition
    assert {sa.REASON_MIN_DURATION_NOT_ELAPSED,
            sa.REASON_SEARCH_CANNOT_CLEAR_MIN_DURATION,
            sa.REASON_SEARCH_LANE_CANNOT_MINT_FINAL} <= _codes(v_nosched), \
        "reason codes %r do not name the soft clock rule and the search ceiling" \
        % (v_nosched.reason_codes,)
    assert sa.REASON_SCHEDULE_NOT_SUPPLIED in _codes(v_nosched), \
        "the absence of the canonical cross-check is not recorded in the verdict"

    # 75 minutes in, against MLB's 150-minute minimum: the arithmetic, not a feeling.
    earliest = sa.earliest_possible_final(START_1215ET, "MLB")
    assert earliest == sa.parse_utc("2026-08-30T18:45:00Z"), \
        "earliest_possible_final drifted: %r" % (earliest,)
    assert sa.parse_utc(NOW_1330ET) < earliest

    live = _rec(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", START_1215ET, sa.IN_PROGRESS, 2, 1)
    v_live = sa.admit(live, now_utc=NOW_1330ET, canonical_schedule=schedule,
                      lane=sa.LANE_CANONICAL)
    assert v_live.disposition == sa.ADMIT_IN_PROGRESS, \
        "a live canonical record gave %s" % v_live.disposition
    assert v_live.admissible_as == sa.ADMISSIBLE_IN_PROGRESS
    assert v_live.admitted and not v_live.settleable, \
        "an in-progress snapshot must be readable and never settleable"
    assert sa.REASON_GAME_IN_PROGRESS in _codes(v_live)
    assert sa.sink_for(v_live) == sa.SINK_BOARD, \
        "a live snapshot reached %s" % sa.sink_for(v_live)

    # Owner rule 8: in-progress is non-final however many outlets agree. Two independent wires
    # corroborating the 9-2 claim raises the grade and never the disposition.
    other = dict(search_claim, source="other_outlet", wire_service="second_wire")
    n = sa.corroboration_count(search_claim, [other])
    assert n == 2, "two independent sources counted as %d" % n
    v_corr = sa.admit(search_claim, now_utc=EVENING, canonical_schedule=None,
                      lane=sa.LANE_SEARCH, corroborations=n)
    assert v_corr.disposition == sa.UNVERIFIED, \
        "corroborated search gave %s" % v_corr.disposition
    assert v_corr.admissible_as == sa.ADMISSIBLE_CORROBORATED, \
        "the search ceiling moved off IDENTIFIED_UNCONFIRMED_CORROBORATED: %r" % v_corr.admissible_as
    assert v_corr.disposition != sa.ADMIT_FINAL and not v_corr.admitted, \
        "SEARCH minted a final on consensus — two outlets on one wire are one source"

    # Same claim, one wire, two mastheads: NOT two sources.
    same_wire = dict(search_claim, source="third_outlet", wire_service="second_wire")
    assert sa.corroboration_count(other, [same_wire]) == 1, \
        "two mastheads sharing one wire counted as independent witnesses"


def test_historical_same_team_matchup_returned_for_today():
    """FIXTURE 3. Yesterday's game, returned for today's query, with the same two clubs on it.

    This is result_binding_gate's PRIOR_DATE_SERIES_JOIN in event-id form, and it is not
    hypothetical here: the 2026-08-30 MLB slate was SET-IDENTICAL to the fifteen matchups on the
    2026-08-28 board. A three-game series repeats team names by construction, so team names cannot
    identify a baseball game and a matchup join binds the wrong day silently.

    Two shapes, both refused, and refused DIFFERENTLY because they are different mistakes:
      * a prior-day EVENT ID against today's slate -> REJECT_PRESTART_OR_UNBOUND /
        EVENT_NOT_IN_CANONICAL_SCHEDULE. Not "unmatched id": the id is real, it is just not on
        this slate.
      * today's event id carrying yesterday's dates -> REJECT_SCHEDULE_CONFLICT on the date and
        the start, i.e. caught by the cross-check rather than by the id.
    """
    schedule = sa.incident_schedule_0830()

    stale = _rec(sa.EID_MIAWSH_PRIOR, "SYNTH_MIA", "SYNTH_WSH", PRIOR_DAY_START, sa.CLOSED,
                 9, 2, source="web_search")
    v = sa.admit(stale, now_utc=NOW_1330ET, canonical_schedule=schedule, lane=sa.LANE_SEARCH)
    assert v.disposition == sa.REJECT_PRESTART_OR_UNBOUND, \
        "a prior-day event id bound to today's slate: %s" % v.disposition
    assert sa.REASON_EVENT_NOT_IN_SCHEDULE in _codes(v), \
        "the refusal does not name the failure mode: %r" % (v.reason_codes,)
    assert not v.admitted

    # THE POINT. A name-keyed binder WOULD have bound this stale record, because the matchup
    # resolves cleanly to exactly one game on today's slate. The id is the only thing that
    # refuses it.
    siblings = sa.schedule_entries_for_matchup(schedule, "MLB", "SYNTH_MIA", "SYNTH_WSH")
    assert siblings == [sa.EID_MIAWSH], \
        "the matchup does not resolve to today's game, so this fixture is not the hazard it " \
        "claims to be: %r" % (siblings,)
    assert stale["event_id"] != siblings[0], \
        "the stale record and today's game share an event id; the fixture proves nothing"

    # The hazard already has a name on the other side of the repo. Bind to the constant so a
    # rename over there is a failure here, not a silent vocabulary fork.
    assert rbg.PRIOR_DATE_SERIES_JOIN == "PRIOR_DATE_SERIES_JOIN", \
        "result_binding_gate's name for this hazard changed: %r" % rbg.PRIOR_DATE_SERIES_JOIN
    assert "result_date" in rbg.REQUIRED_FIELDS, \
        "the row contract on the binding side stopped requiring result_date (bypass B1)"

    # Right id, yesterday's clock: caught by the schedule cross-check, on the date AND the start.
    misdated = _rec(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", PRIOR_DAY_START, sa.CLOSED,
                    9, 2, source="web_search")
    v2 = sa.admit(misdated, now_utc=NOW_1330ET, canonical_schedule=schedule, lane=sa.LANE_SEARCH)
    assert v2.disposition == sa.REJECT_SCHEDULE_CONFLICT, \
        "a record carrying yesterday's dates under today's id gave %s" % v2.disposition
    assert {sa.REASON_SCHEDULE_DATE_DISAGREE, sa.REASON_SCHEDULE_START_DISAGREE} <= _codes(v2), \
        "reason codes %r do not name the date and start disagreement" % (v2.reason_codes,)

    # The ET date is DERIVED, never sliced. A 2026-08-31T00:30Z tip is the ET evening of 08-30,
    # and slicing that UTC string is what corrupted a cohort twice.
    late = _entry(sa.EID_DH_G2, "SYNTH_KC", "SYNTH_TOR", "2026-08-31T00:30:00Z")
    assert sa.scheduled_date_of(late) == "2026-08-30", \
        "the ET date of a 00:30Z tip came out as %r — that is a sliced UTC string" \
        % sa.scheduled_date_of(late)


def test_doubleheader_is_ambiguous_by_team_names():
    """FIXTURE 4. Two games, one matchup, one date. Both must survive as distinct records.

    A matchup-keyed dedupe collapses a doubleheader into one game and silently discards a result.
    This repo has never held a doubleheader payload at all — every observed StatsAPI gameNumber is
    1 — so the halves are constructed, and the collector's `records.append(record)` being
    unconditional is the guard under test.

    The fixture asserts, in order: the payload yields TWO records with TWO distinct event ids and
    TWO admissions; the matchup lookup returns BOTH, which is the proof that names cannot choose;
    and a record whose id is not on the slate is refused with MATCHUP_AMBIGUOUS_USE_EVENT_ID
    rather than being quietly attached to whichever half sorts first.
    """
    sc = require_module("score_collector")

    payload = sc.doubleheader_payload()
    result = sc.collect_mlb("2026-08-30", now_utc=EVENING,
                            get=sc._stub_get(json.dumps(payload)))
    assert not result.lane_down, "the doubleheader fixture could not reach its stub fetcher"
    assert result.counters["RECORDS_NORMALIZED"] == 2, \
        "the doubleheader collapsed: %d records normalized from a 2-game payload" \
        % result.counters["RECORDS_NORMALIZED"]
    assert result.counters["DISTINCT_IDENTITIES"] == 2, \
        "two halves of a doubleheader share one identity: %r" % (result.counters,)

    event_ids = [e["record"]["event_id"] for e in result.admitted]
    assert sorted(event_ids) == sorted([sa.EID_DH_G1, sa.EID_DH_G2]), \
        "the admitted halves are %r, not both halves" % (event_ids,)
    assert len(set(event_ids)) == 2, "two admitted records under one event id"
    assert result.counters["ADMITTED"] == 2, \
        "a doubleheader half was dropped or refused: %r" % (result.counters,)

    # The scores are DIFFERENT, so a collapse cannot hide behind identical content.
    scores = {e["record"]["event_id"]: (e["record"]["away_score"], e["record"]["home_score"])
              for e in result.admitted}
    assert len(set(scores.values())) == 2, \
        "both halves carry the same score, so a dedupe would be invisible: %r" % (scores,)

    # Names cannot choose between them. This function exists to be called and found ambiguous.
    schedule = sc.schedule_entries_from_records([e["record"] for e in result.admitted])
    siblings = sa.schedule_entries_for_matchup(schedule, "MLB", "SYNTH_KC", "SYNTH_TOR")
    assert len(siblings) == 2, \
        "the matchup lookup found %d entries for a doubleheader — names should be ambiguous here" \
        % len(siblings)

    unknown_half = _rec("mlb:2026:SYNTHETIC-UNVERIFIED-KCTOR-G3", "SYNTH_KC", "SYNTH_TOR",
                        "2026-08-30T17:07:00Z", sa.CLOSED, 3, 1, source="web_search")
    v = sa.admit(unknown_half, now_utc=EVENING, canonical_schedule=schedule, lane=sa.LANE_SEARCH)
    assert v.disposition == sa.REJECT_PRESTART_OR_UNBOUND, \
        "an unbound doubleheader claim gave %s" % v.disposition
    assert {sa.REASON_EVENT_NOT_IN_SCHEDULE,
            sa.REASON_MATCHUP_AMBIGUOUS_USE_EVENT_ID} <= _codes(v), \
        "reason codes %r do not say the matchup is ambiguous and the id is required" \
        % (v.reason_codes,)
    assert sorted(v.detail.get("matchup_siblings") or []) == sorted(siblings), \
        "the refusal does not list the candidate halves it could not choose between"


def test_postponed_game_with_an_old_event_id():
    """FIXTURE 5. A postponed game's OLD id, carrying a score, after the makeup was scheduled.

    Modelled on the only postponement this repo evidences: PIT@CLE 2026-07-17, statusCode "DD",
    codedGameState "D", status.reason "Air Quality", officialDate already advanced to the makeup
    date (data/mlb/schedule/2026-07-17_espn_verify.json). Note what that evidence shows and what
    it does not: StatsAPI RETAINED gamePk 824414 for the makeup, and nothing in this repo reads
    rescheduledFrom, rescheduleDate or status.reason at all.

    No score is admitted on the old id, and the refusal must say REBIND, not merely "conflict":
    the correct repair is to bind the successor event, and a generic refusal would invite someone
    to relax the date check instead.
    """
    after_makeup = "2026-09-01T02:00:00Z"     # both slots are in the past by here
    schedule = sa.index_schedule([
        _entry(sa.EID_PPD_OLD, "SYNTH_PIT", "SYNTH_CLE", NEXT_DAY, status=sa.POSTPONED,
               rescheduled_to_event_id=sa.EID_PPD_NEW),
        _entry(sa.EID_PPD_NEW, "SYNTH_PIT", "SYNTH_CLE", NEXT_DAY, status=sa.SCHEDULED),
    ])

    stale_final = _rec(sa.EID_PPD_OLD, "SYNTH_PIT", "SYNTH_CLE", NEXT_DAY, sa.CLOSED, 3, 1)
    v = sa.admit(stale_final, now_utc=after_makeup, canonical_schedule=schedule,
                 lane=sa.LANE_CANONICAL)
    assert v.disposition == sa.REJECT_SCHEDULE_CONFLICT, \
        "a final on a postponed game's old id gave %s" % v.disposition
    assert {sa.REASON_POSTPONED_REBIND_REQUIRED, sa.REASON_GAME_POSTPONED} <= _codes(v), \
        "reason codes %r do not require a rebind" % (v.reason_codes,)
    assert v.detail.get("rebind_to") == sa.EID_PPD_NEW, \
        "the refusal does not name the successor event id: %r" % v.detail.get("rebind_to")
    assert not v.admitted and sa.sink_for(v) == sa.SINK_QUARANTINE

    # The successor id, same teams, same clock, admits normally — the rebind is a real repair and
    # not a dead end.
    rebound = _rec(sa.EID_PPD_NEW, "SYNTH_PIT", "SYNTH_CLE", NEXT_DAY, sa.CLOSED, 3, 1)
    v2 = sa.admit(rebound, now_utc=after_makeup, canonical_schedule=schedule,
                  lane=sa.LANE_CANONICAL)
    assert v2.disposition == sa.ADMIT_FINAL and v2.settleable, \
        "the rebound successor event did not admit: %s / %r" % (v2.disposition, v2.reason_codes)

    # A POSTPONED status is non-final on its own terms (owner rule 8), and a score riding on one
    # is named rather than ignored. The record keeps its ORIGINAL slot, which is what a postponed
    # game's schedule row carries until the makeup is published.
    ppd = _rec(sa.EID_PPD_OLD, "SYNTH_PIT", "SYNTH_CLE", "2026-08-30T17:10:00Z", sa.POSTPONED,
               0, 0)
    v3 = sa.admit(ppd, now_utc=EVENING, canonical_schedule=None, lane=sa.LANE_CANONICAL)
    assert v3.disposition == sa.UNVERIFIED, "a postponed game gave %s" % v3.disposition
    assert {sa.REASON_GAME_POSTPONED, sa.REASON_STATUS_NOT_TERMINAL,
            sa.REASON_SCORE_WITHOUT_TERMINAL_STATUS} <= _codes(v3), \
        "reason codes %r do not name the postponement and the orphan score" % (v3.reason_codes,)
    assert not v3.admitted

    # The canonical lane drops the 0-0 the payload carries rather than normalizing it into a
    # record: a postponed game has no score, and 0-0 is the most dangerous shape of a wrong one.
    sc = require_module("score_collector")
    result = sc.collect_mlb("2026-08-30", now_utc=EVENING,
                            get=sc._stub_get(json.dumps(sc.postponed_payload())))
    assert result.counters["ADMITTED"] == 0, \
        "a postponed slate admitted %d records" % result.counters["ADMITTED"]
    dropped = [p for r in result.normalized for p in (r.get("collector_problems") or [])
               if p.get("code") == sc.COLLECT_SCORE_DROPPED_NOT_PLAYED]
    assert dropped, \
        "the collector kept a score on a game that was not played; problems were %r" \
        % [p.get("code") for r in result.normalized for p in (r.get("collector_problems") or [])]
    assert all(r.get("away_score") is None and r.get("home_score") is None
               for r in result.normalized), \
        "a postponed record still carries a score"


def test_status_complete_but_not_closed():
    """FIXTURE 6. "complete" is over. "closed" is validated. Only the second one settles.

    Sportradar distinguishes the two; MLB StatsAPI's "O" (Game Over) and "F" (Final) are the same
    distinction under different letters. A COMPLETE record is readable and NOT settleable, and
    terminal_verified stays False while the status is already terminal — that gap is the whole
    reason terminal_verified exists as a separate field.
    """
    complete = _rec(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", START_1215ET, sa.COMPLETE, 2, 9,
                    fetched=EVENING)
    v = sa.admit(complete, now_utc=EVENING, canonical_schedule=None, lane=sa.LANE_CANONICAL)
    assert v.disposition == sa.ADMIT_FINAL, "a complete game gave %s" % v.disposition
    assert v.admissible_as == sa.ADMISSIBLE_FINAL_UNVALIDATED, \
        "'complete' admitted as %r" % v.admissible_as
    assert v.admitted, "a complete game must be readable"
    assert not v.settleable, "'complete' is settleable — complete and closed have been merged"
    assert not v.terminal_verified, "terminal_verified is True on an unvalidated terminal status"
    assert sa.REASON_STATUS_TERMINAL_NOT_VALIDATED in _codes(v), \
        "reason codes %r do not name the missing validation" % (v.reason_codes,)
    assert sa.sink_for(v) == sa.SINK_BOARD, \
        "an unvalidated final reached %s; only a validated one may reach the result ledger" \
        % sa.sink_for(v)

    closed = _rec(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", START_1215ET, sa.CLOSED, 2, 9,
                  fetched=EVENING)
    v2 = sa.admit(closed, now_utc=EVENING, canonical_schedule=None, lane=sa.LANE_CANONICAL)
    assert v2.disposition == sa.ADMIT_FINAL and v2.admissible_as == sa.ADMISSIBLE_FINAL
    assert v2.settleable and v2.terminal_verified, \
        "a validated final is not settleable: %r" % (v2.reason_codes,)
    assert sa.REASON_STATUS_VALIDATED in _codes(v2)
    assert sa.sink_for(v2) == sa.SINK_RESULT_LEDGER

    # The two states are different states, in the vocabulary and in the provider maps.
    assert sa.COMPLETE in sa.TERMINAL_STATES and sa.COMPLETE not in sa.VALIDATED_STATES, \
        "COMPLETE has entered VALIDATED_STATES"
    assert sa.terminal_verified_for(sa.COMPLETE) is False
    assert sa.terminal_verified_for(sa.CLOSED) is True
    assert sa.normalize_status("complete", sa.PROVIDER_SPORTRADAR) == sa.COMPLETE
    assert sa.normalize_status("closed", sa.PROVIDER_SPORTRADAR) == sa.CLOSED
    assert sa.normalize_status("O", sa.PROVIDER_MLB_STATSAPI) == sa.COMPLETE, \
        "StatsAPI 'O' must take the WEAKER state: this repo holds zero payloads carrying it, " \
        "only a comment in feed_mlb_statsapi.FINAL_STATUS_CODES"
    assert sa.normalize_status("F", sa.PROVIDER_MLB_STATSAPI) == sa.CLOSED
    assert sa.normalize_status("STATUS_FINAL", sa.PROVIDER_ESPN_SCOREBOARD) == sa.COMPLETE, \
        "an ESPN final was promoted to CLOSED; that API exposes no validation state anywhere " \
        "in this repo"

    # A record whose terminal_verified was TYPED rather than generated is refused. Counters are
    # generated by code, never typed by hand — and this field is a counter.
    forged = dict(complete, terminal_verified=True)
    ok, problems = sa.validate_record(forged)
    assert not ok and any(p["code"] == sa.REASON_TERMINAL_VERIFIED_INCONSISTENT for p in problems), \
        "a hand-set terminal_verified passed validation: %r" % (problems,)

    # End to end through the canonical lane: statusCode "O" arrives as COMPLETE, not settled.
    sc = require_module("score_collector")
    result = sc.collect_mlb("2026-08-30", now_utc=EVENING,
                            get=sc._stub_get(json.dumps(sc.complete_not_closed_payload())))
    assert result.counters["ADMITTED"] == 1, "the 'O' slate admitted %r" % (result.counters,)
    entry = result.admitted[0]
    assert entry["record"]["status"] == sa.COMPLETE
    assert entry["record"]["terminal_verified"] is False
    assert entry["verdict"].admissible_as == sa.ADMISSIBLE_FINAL_UNVALIDATED
    assert entry["sink"] == sa.SINK_BOARD, \
        "an unvalidated final was routed to %s" % entry["sink"]


def test_mutable_archive_changes_under_the_same_filename():
    """FIXTURE 7. The same filename, different bytes. Owner rule 7 exists for this.

    A hash that nothing ever recomputes is a decoration. This fixture writes a snapshot, verifies
    it clean, rewrites ONE raw payload file in place without touching its name, and requires
    verify_snapshot to report drift naming the payload bytes — not to repair it, not to raise, and
    not to report a generic failure.

    It also asserts the store REFUSES to rewrite the id (R6, append-only), and that the
    record-level shape of the same defect — one content hash covering two different score sets —
    is caught by the contract's own content_hash_conflict.
    """
    vs = require_module("verified_snapshot")

    raw_text = json.dumps({"dates": [{"date": "2026-08-30", "games": [
        {"gamePk": sa.parse_event_id(sa.EID_MIAWSH)[2], "status": {"statusCode": "F"}}]}]},
        sort_keys=True)
    record = _rec(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", START_1215ET, sa.CLOSED, 2, 9,
                  fetched=EVENING)
    record["raw_response_sha256"] = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    verdict = sa.admit(record, now_utc=EVENING, canonical_schedule=None, lane=sa.LANE_CANONICAL)
    assert verdict.settleable, "the fixture's own record did not admit: %r" % (verdict.reason_codes,)

    payloads = [{"payload_id": "mlb_statsapi_schedule.json", "raw_text": raw_text,
                 "fetched_at_utc": EVENING, "source": sa.PROVIDER_MLB_STATSAPI}]
    root = tempfile.mkdtemp(prefix="test_score_admission_")
    try:
        snapshot_id = vs.write_snapshot([vs.admission_envelope(record, verdict)],
                                        league="MLB", date_et="2026-08-30",
                                        source=sa.PROVIDER_MLB_STATSAPI,
                                        raw_payloads=payloads, now_utc=EVENING, out_root=root)
        clean = vs.verify_snapshot(snapshot_id, root=root)
        assert clean["ok"], "a freshly written snapshot already reports drift: %r" % clean["drift"]
        assert clean["checked"]["payloads"] == 1, \
            "verify_snapshot did not actually re-hash the payload: %r" % (clean["checked"],)

        served = vs.get_verified_score(sa.EID_MIAWSH, root=root)
        assert served and served["home_score"] == 9, \
            "the clean snapshot does not serve its own record: %r" % (served,)

        # THE ARCHIVE MUTATES. Same filename, different bytes — the exact 8/30 shape, where two
        # historical daily files were rewritten under unchanged names and nothing noticed.
        path = os.path.join(root, vs.SNAPSHOTS_DIR, snapshot_id, vs.RAW_DIR,
                            "mlb_statsapi_schedule.json")
        assert os.path.isfile(path), "the raw payload was never retained at %s" % path
        with open(path, "w") as fh:
            fh.write(raw_text.replace('"statusCode": "F"', '"statusCode": "DD"'))

        drifted = vs.verify_snapshot(snapshot_id, root=root)
        codes = [d["code"] for d in drifted["drift"]]
        assert not drifted["ok"], "the archive changed under one filename and verify said OK"
        assert vs.DRIFT_PAYLOAD_BYTES in codes, \
            "drift was reported as %r, which does not name the changed bytes" % (codes,)
        assert vs.DRIFT_ID_NOT_CONTENT in codes, \
            "the content-addressed id no longer matches its content and nothing said so: %r" \
            % (codes,)
        assert os.path.isfile(path), "verify_snapshot repaired or removed the drifted payload"
        with open(path) as fh:
            assert '"DD"' in fh.read(), \
                "verify_snapshot rewrote the drifted bytes — repairing erases the evidence that " \
                "the store drifted, which is the thing worth knowing"

        # R6: the id is the hash of the content, so a rewrite under the same id must refuse.
        try:
            vs.write_snapshot([vs.admission_envelope(record, verdict)],
                              league="MLB", date_et="2026-08-30",
                              source=sa.PROVIDER_MLB_STATSAPI,
                              raw_payloads=payloads, now_utc=EVENING, out_root=root)
            raise AssertionError("a committed snapshot was rewritten in place (R6 violated)")
        except vs.SnapshotImmutabilityViolation:
            pass
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # The same defect one level down: one sha256 standing over two different score sets.
    a = _rec(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", START_1215ET, sa.CLOSED, 2, 9,
             fetched=EVENING)
    b = dict(a, away_score=9, home_score=2)
    conflict, problem = sa.content_hash_conflict(a, b)
    assert conflict and problem["code"] == sa.REASON_SNAPSHOT_HASH_MATCHES_CONTENT_DIFFERS, \
        "one hash over two different score sets was not caught: %r" % (problem,)

    # And the other shape: same key, same fetch instant, different bytes.
    c = dict(a, raw_response_sha256=hashlib.sha256(b"different").hexdigest())
    conflict2, problem2 = sa.content_hash_conflict(a, c)
    assert conflict2 and problem2["code"] == sa.REASON_SNAPSHOT_CONTENT_CHANGED, \
        "a changed hash under one key was not caught: %r" % (problem2,)


def test_missing_market_price_with_a_calculated_edge():
    """FIXTURE 8. The board's only LEAN, priced against a market price that was never captured.

    cards/2026-08-30_pregame_board_v6_canonical.json, MIN @ ATL, SPREAD_RL "ATL +2.5":
        entry.price_american   null          price_available  false
        market_no_vig_cover_pct 50.0         edge_pp          14.3
        usable_edge_pp          6.9          decision         LEAN

    A no-vig probability is the normalisation of two captured implied probabilities. Zero were
    captured here — there is no field in this schema for the opposite side's price at all — so
    50.0 is the assumption "a spread is a coin flip at the number", typed in, and it is the entire
    denominator of the 14.3. usable_edge_pp then discounts that by DQ 0.65 x Unc 0.75, which
    launders a wrong base into something that reads as conservatively derived.

    Required: decision PASS (never LEAN), reason MISSING_MARKET_PRICE, and the edge SUPPRESSED —
    not recomputed, not discounted, absent. Prices enter only the action/EV overlay; an edge
    computed against an assumed price is not a smaller edge, it is not an edge.
    """
    bi = _board()
    game = _load_min_atl_game()
    row = _min_atl_row("SPREAD_RL")

    # The frozen artifact still carries the defect. If this ever stops being true the artifact has
    # been rewritten, which R3 forbids, and these fixtures are pointed at the wrong bytes.
    assert row["entry"]["price_american"] is None, "the frozen row now has a price"
    assert row["price_available"] is False
    assert row["probabilities"]["edge_pp"] == 14.3
    assert row["probabilities"]["usable_edge_pp"] == 6.9
    assert row["probabilities"]["market_no_vig_cover_pct"] == 50.0
    assert row["decision"] == "LEAN" and row["signal_decision"] == "LEAN"

    # Judged on its own, so this fixture reads the PRICE invariant and not the convergence one.
    # A game object carrying only this row makes the convergence question not arise at all.
    solo = {"event_id": game["event_id"], "game": game["game"], "sport": game["sport"],
            "markets": [row]}
    rv = bi.check_row(row, game=solo)
    codes = set(rv.reason_codes)

    assert rv.decision_in == sa.DECISION_LEAN and rv.decision == sa.DECISION_PASS, \
        "the board's only LEAN survived a row with no captured price: %s -> %s" \
        % (rv.decision_in, rv.decision)
    assert rv.signal_decision == sa.DECISION_PASS, \
        "signal_decision stayed %r" % rv.signal_decision
    assert rv.suppressed, "the row was not suppressed: %r" % (rv.reason_codes,)
    assert rv.posture == sa.DECISION_PASS_DATA_QUALITY, \
        "the posture on a null-price row is %r, not PASS_DATA_QUALITY" % rv.posture
    assert sa.BOARD_REASON_MISSING_MARKET_PRICE in codes, \
        "reason codes %r do not name the missing market price" % (rv.reason_codes,)

    # The assumed 50.0 is named as an assumption rather than carried as a measurement. This is the
    # second half of the defect: the edge's entire denominator was typed in.
    assert sa.BOARD_REASON_ASSUMED_NO_VIG in codes, \
        "the assumed no-vig 50.0 was not flagged: %r" % (rv.reason_codes,)
    assert rv.detail["no_vig_pct"] == 50.0 and rv.detail["no_vig_is_round"] is True

    # PROHIBIT EDGE CALCULATION, not merely "prohibit LEAN". The invariant must fire on the
    # EXISTENCE of the edge, so the same row with its decision already PASS is still refused —
    # otherwise a future card could keep the 14.3 and simply not act on it, which is how the
    # laundered number survives to be read by something else.
    quiet = json.loads(json.dumps(row))
    quiet["decision"] = "PASS"
    quiet["signal_decision"] = "PASS"
    rv_quiet = bi.check_row(quiet, game=dict(solo, markets=[quiet]))
    assert sa.BOARD_REASON_MISSING_MARKET_PRICE in rv_quiet.reason_codes, \
        "an unpriced edge sitting quietly on a PASS row was not refused: %r" \
        % (rv_quiet.reason_codes,)

    # And the check is not a constant: 39 rows on this board have no price, and a row that makes
    # no priced claim is not a defect. The TOTALS row is exactly that.
    totals = _min_atl_row("TOTALS")
    assert totals["entry"]["price_american"] is None and totals["probabilities"]["edge_pp"] is None
    rv_totals = bi.check_row(totals, game=dict(solo, markets=[totals]))
    assert sa.BOARD_REASON_MISSING_MARKET_PRICE not in rv_totals.reason_codes, \
        "the price invariant fired on a NO_LINE row that claims nothing: %r" \
        % (rv_totals.reason_codes,)
    assert rv_totals.decision == "NO_LINE", \
        "suppression overwrote a more specific non-action label: %r" % rv_totals.decision

    # The published arithmetic does not even reproduce itself: 64.2 - 50.0 is 14.2, the field says
    # 14.3, and the row's own usable_edge_pp agrees with 14.2 (14.2 x 0.65 x 0.75 = 6.92 -> 6.9;
    # 14.3 x 0.65 x 0.75 = 6.97 -> 7.0). Counters are generated by code, never typed by hand.
    stated = row["probabilities"]["edge_pp"]
    recomputed = round(row["probabilities"]["model_cover_pct"]
                       - row["probabilities"]["market_no_vig_cover_pct"], 1)
    assert (recomputed, stated) == (14.2, 14.3), \
        "the published arithmetic drifted: recomputed %r vs stated %r" % (recomputed, stated)
    assert rv.detail["edge_pp_recomputed"] == 14.2, \
        "the module recomputed the edge as %r" % rv.detail.get("edge_pp_recomputed")
    assert bi.REASON_EDGE_NOT_REPRODUCIBLE in rv.warnings, \
        "the hand-typed edge_pp was not reported: %r" % (rv.warnings,)

    # Through enforce(): the frozen input is not touched (R3, proved by hash) and the enforced
    # COPY carries the refusal on the row, so the 14.3 can never again stand unqualified.
    frozen_before = json.dumps(game, sort_keys=True)
    enforced = bi.enforce(CANONICAL_BOARD_PATH)
    assert enforced["counters"]["INPUT_UNCHANGED"] is True, "enforce() mutated its input (R3)"
    assert json.dumps(_load_min_atl_game(), sort_keys=True) == frozen_before, \
        "the frozen artifact changed on disk (R3/R6)"
    changed = [c for c in enforced["changes"]
               if c["event_id"] == MIN_ATL_EVENT_ID and c["market"] == "SPREAD_RL"
               and c["field"] == "decision"]
    assert changed and changed[0]["from"] == "LEAN" and changed[0]["to"] == sa.DECISION_PASS, \
        "the enforced copy did not turn the LEAN into a PASS: %r" % (changed,)


def test_ml_and_spread_rows_from_incompatible_margins():
    """FIXTURE 9. One game, one model, two arms, opposite signs.

    MIN @ ATL on the frozen board, using the board's own sigma — stated only in the SPREAD_RL
    note, "cover p = Phi(5.1/13.97)", so sigma = 13.97:

        SPREAD_RL  model_cover_pct 64.2 on ATL +2.5  =>  mu(ATL) = +2.60   ATL wins by 2.6
        ML         model_win_pct   39.7              =>  mu(ATL) = -3.65   ATL loses by 3.6

    6.25 points apart, opposite signs, same row group. The board HAS a CONVERGENCE_FAIL posture
    and uses it exactly once in the file — on HOU@NYM, not here. The ML row's own note says "ML
    edge negative; divergence from spread recorded", so the divergence was RECORDED and the
    contradicting spread row was promoted to the board's only LEAN anyway. Recording is not a
    control.

    Required: MODEL_CONVERGENCE_FAIL and no LEAN.
    """
    bi = _board()
    game = _load_min_atl_game()
    ml = _min_atl_row("ML")
    spread = _min_atl_row("SPREAD_RL")

    # THE ARITHMETIC, computed here and not read from the module, so the fixture cannot be
    # satisfied by a checker that merely agrees with itself.
    sigma = 13.97
    line = spread["line"]
    assert (line, spread["selection"]) == (2.5, "ATL +2.5")
    assert "Phi(5.1/13.97)" in spread["note"], \
        "the board's stated sigma is no longer in the row note; this fixture's sigma is a guess"

    cover_p = spread["probabilities"]["model_cover_pct"] / 100.0
    win_p = ml["probabilities"]["model_win_pct"] / 100.0
    assert (round(cover_p * 100, 1), round(win_p * 100, 1)) == (64.2, 39.7)

    mu_from_spread = implied_margin(cover_p, sigma) - line
    mu_from_ml = implied_margin(win_p, sigma)
    assert round(mu_from_spread, 2) == 2.58, \
        "the spread arm implies %r, not +2.58" % round(mu_from_spread, 2)
    assert round(mu_from_ml, 2) == -3.65, \
        "the moneyline arm implies %r, not -3.65" % round(mu_from_ml, 2)
    assert mu_from_spread * mu_from_ml < 0, "the two arms no longer have opposite signs"
    assert round(mu_from_spread - mu_from_ml, 2) == 6.23, \
        "the divergence is %r points, not 6.23" % round(mu_from_spread - mu_from_ml, 2)

    # The note's own numerator says the same thing to within the published rounding: 5.1 - 2.5 is
    # +2.60, and inverting the PUBLISHED 64.2 gives +2.58. The 0.02 is the rounding of 64.2, not a
    # disagreement — recorded here so a future reader does not "fix" one number to match the other.
    assert abs((5.1 - line) - mu_from_spread) <= 0.02
    assert round(cover_probability(5.1 - line, line, sigma) * 100, 1) == 64.2, \
        "the note's own Phi(5.1/13.97) no longer reproduces the published 64.2"

    # Forced consistency, both directions, so the fixture states what the right answer WOULD be
    # rather than only that the published one is wrong.
    assert round(cover_probability(mu_from_ml, line, sigma) * 100, 1) == 46.7, \
        "with mu = -3.65 the cover probability must be 46.7, not 64.2"
    assert round(cover_probability(mu_from_spread, 0.0, sigma) * 100, 1) == 57.3, \
        "with mu = +2.58 the moneyline probability must be 57.3, not 39.7"

    # The module reaches the same two margins independently. Two implementations agreeing is the
    # cross-check; one implementation agreeing with itself is not.
    conv = bi.check_convergence(game)
    assert conv is not None, "the convergence question did not arise on the game that is the case"
    assert bi.REASON_MODEL_CONVERGENCE_FAIL in conv["codes"], \
        "convergence codes are %r" % (conv["codes"],)
    assert conv["detail"]["opposite_signs"] is True
    assert conv["detail"]["sigma"] == sigma
    assert abs(conv["detail"]["implied_margin_ml"] - mu_from_ml) < 0.001, \
        "the module's ML margin %r disagrees with this fixture's %r" \
        % (conv["detail"]["implied_margin_ml"], mu_from_ml)
    assert abs(conv["detail"]["implied_margin_spread"] - mu_from_spread) < 0.001, \
        "the module's spread margin %r disagrees with this fixture's %r" \
        % (conv["detail"]["implied_margin_spread"], mu_from_spread)
    assert abs(conv["detail"]["gap_points"] - abs(mu_from_spread - mu_from_ml)) < 0.001

    gv = bi.check_game(game)
    codes = set(gv.reason_codes)
    assert sa.BOARD_REASON_MODEL_CONVERGENCE_FAIL in codes, \
        "two arms of one game imply opposite outcomes and the reason codes are %r" \
        % (gv.reason_codes,)
    assert gv.decision_in == "LEAN" and gv.decision != sa.DECISION_LEAN, \
        "the LEAN survived a convergence failure: %s -> %s" % (gv.decision_in, gv.decision)
    assert gv.posture == sa.DECISION_CONVERGENCE_FAIL, \
        "the posture is %r, not CONVERGENCE_FAIL" % gv.posture

    # The finding attaches to BOTH arms. The ML row is half of the contradiction, not the
    # innocent party that happened to say PASS.
    by_market = {r.market: r for r in gv.rows}
    for market in ("ML", "SPREAD_RL"):
        assert sa.BOARD_REASON_MODEL_CONVERGENCE_FAIL in by_market[market].reason_codes, \
            "the %s arm does not carry the convergence failure: %r" \
            % (market, by_market[market].reason_codes)

    # The whole game must come out exactly as the owner specified. Compared against the contract's
    # own object, not a retyped list, so the two modules cannot fork on the wording.
    assert gv.decision == sa.MIN_ATL_REQUIRED_ROW["decision"], \
        "MIN@ATL decision is %r, required %r" % (gv.decision, sa.MIN_ATL_REQUIRED_ROW["decision"])
    assert set(sa.MIN_ATL_REQUIRED_ROW["reason_codes"]) <= codes, \
        "MIN@ATL reason codes %r do not cover the required %r" \
        % (gv.reason_codes, sa.MIN_ATL_REQUIRED_ROW["reason_codes"])
    assert gv.reason_codes[:3] == list(sa.MIN_ATL_REQUIRED_ROW["reason_codes"]), \
        "the required codes are present but not in the order the owner wrote them: %r" \
        % (gv.reason_codes,)

    # A game whose arms AGREE must not be failed — otherwise the check is a constant, and this
    # board gives it exactly one live case to fire on.
    coherent = json.loads(json.dumps(game))
    for r in coherent["markets"]:
        if r["market"] == "ML":
            r["probabilities"]["model_win_pct"] = round(
                cover_probability(mu_from_spread, 0.0, sigma) * 100, 1)
            r["probabilities"]["model_loss_pct"] = round(
                100.0 - r["probabilities"]["model_win_pct"], 1)
    conv2 = bi.check_convergence(coherent)
    assert conv2 is not None and bi.REASON_MODEL_CONVERGENCE_FAIL not in conv2["codes"], \
        "a game whose two arms agree was still failed for convergence: %r" % (conv2["codes"],)
    assert conv2["detail"]["opposite_signs"] is False


def test_stale_injury_report_beyond_the_freshness_deadline():
    """FIXTURE 10. A 32-day-old injury report standing in for today's availability.

    On 2026-08-30 the only Atlanta availability report a search returned was from late July. The
    frozen game note reads "Brionna Jones out (pre-open); ATL possible B2B - model blind", i.e. the
    board knew it was blind and leaned anyway.

    freshness_contract's limit for a WNBA starter input is 2 days. 32 is not a degraded input, it
    is a different month. Required: availability_state UNKNOWN and every play depending on it
    suppressed.
    """
    bi = _board()

    stamp = fc.Stamp(observed_at=ATL_INJURY_OBSERVED_AT, effective_at=ATL_INJURY_OBSERVED_AT,
                     source="web_search", grade=fc.IDENTIFIED_UNCONFIRMED,
                     subject=ATL_INJURY_SUBJECT)
    now = sa.parse_utc(NOW_1330ET)
    d = fc.resolve_input(ATL_INJURY_SUBJECT, "wnba", "starter", stamp, now=now)

    assert fc.MAX_AGE_DAYS[("wnba", "starter")] == 2, \
        "the WNBA starter freshness limit moved: %r" % fc.MAX_AGE_DAYS[("wnba", "starter")]
    assert 32 <= d.age_days < 33, "the report is %r days old, not 32" % d.age_days
    assert d.disposition == fc.DEGRADED, \
        "a 32-day-old report resolved as %r" % d.disposition
    assert not d.actionable and not d.bettable, \
        "a 32-day-old availability input is actionable"
    assert d.grade != fc.CONFIRMED

    # An ABSENT stamp must reach the same place. "We never looked" and "we looked in July" are
    # both UNKNOWN, and the second is the more dangerous because it has a number attached.
    absent = fc.Stamp.absent(ATL_INJURY_SUBJECT, "no ATL availability source reachable 8/30")
    d_absent = fc.resolve_input(ATL_INJURY_SUBJECT, "wnba", "starter", absent, now=now)
    assert not d_absent.actionable and d_absent.grade == fc.ABSENT

    game = _load_min_atl_game()
    assert "model blind" in (game.get("note") or ""), \
        "the frozen game note no longer records that the model was blind on availability"

    # The report as the board would have carried it: a state, and the July instant it was observed.
    july_report = {"state": "AVAILABLE", "as_of_utc": ATL_INJURY_OBSERVED_AT,
                   "now_utc": NOW_1330ET}
    state, why = bi.resolve_availability(july_report)
    assert (state, why) == (sa.AVAILABILITY_UNKNOWN, bi.AVAILABILITY_STALE), \
        "a 32-day-old 'AVAILABLE' resolved as %r/%r" % (state, why)

    # The 8/30 card carried NO availability record at all, and silence is UNKNOWN, never
    # AVAILABLE. Both roads reach the same place, and the July one is the more dangerous because
    # it has a number attached.
    assert bi.resolve_availability(None) == (sa.AVAILABILITY_UNKNOWN, bi.AVAILABILITY_NOT_SUPPLIED)

    gv = bi.check_game(game, availability_state=july_report)
    codes = set(gv.reason_codes)
    assert sa.BOARD_REASON_AVAILABILITY_UNKNOWN in codes, \
        "a 32-day-old availability input did not raise AVAILABILITY_UNKNOWN: %r" \
        % (gv.reason_codes,)
    assert gv.detail["availability_state"] == sa.AVAILABILITY_UNKNOWN, \
        "availability_state is %r, not UNKNOWN" % gv.detail["availability_state"]
    assert gv.detail["availability_reason"] == bi.AVAILABILITY_STALE
    assert gv.decision != sa.DECISION_LEAN, \
        "a play depending on unknown availability was not suppressed: %s -> %s" \
        % (gv.decision_in, gv.decision)

    # Only the play-bearing rows are touched. A NO_LINE row does not depend on availability and
    # must not be relabelled by it.
    by_market = {r.market: r for r in gv.rows}
    assert sa.BOARD_REASON_AVAILABILITY_UNKNOWN in by_market["SPREAD_RL"].reason_codes
    assert sa.BOARD_REASON_AVAILABILITY_UNKNOWN not in by_market["TOTALS"].reason_codes, \
        "the availability rule fired on a row that carries no play: %r" \
        % (by_market["TOTALS"].reason_codes,)

    # And it can NOT fire: a report observed half an hour before the decision resolves, so the
    # check is not a constant that condemns every game.
    fresh = {"state": "AVAILABLE", "as_of_utc": "2026-08-30T17:00:00Z", "now_utc": NOW_1330ET}
    assert bi.resolve_availability(fresh) == ("AVAILABLE", bi.AVAILABILITY_RESOLVED)
    gv_fresh = bi.check_game(game, availability_state=fresh)
    assert sa.BOARD_REASON_AVAILABILITY_UNKNOWN not in gv_fresh.reason_codes, \
        "a report observed 30 minutes earlier was still called UNKNOWN: %r" \
        % (gv_fresh.reason_codes,)


# =============================================================================================
# 3. THE BOARD SUBJECT.  Bound by name, and a rename is a NAMED failure rather than a skip.
# =============================================================================================

#: Every board_invariants name the three board fixtures call. Checked once, up front, so a rename
#: over there arrives here as "this suite calls check_row and it is gone" rather than as an
#: AttributeError halfway through an assertion — or, far worse, as a skip.
BOARD_SURFACE = ("check_row", "check_game", "check_convergence", "resolve_availability",
                 "enforce", "REASON_MISSING_MARKET_PRICE", "REASON_AVAILABILITY_UNKNOWN",
                 "REASON_MODEL_CONVERGENCE_FAIL", "REASON_ASSUMED_NO_VIG",
                 "REASON_EDGE_NOT_REPRODUCIBLE", "AVAILABILITY_STALE",
                 "AVAILABILITY_NOT_SUPPLIED", "AVAILABILITY_RESOLVED")


def _board():
    """harness/board_invariants.py, with its surface checked. Absent or renamed is a FAILURE."""
    mod = require_module("board_invariants")
    missing = [n for n in BOARD_SURFACE if not hasattr(mod, n)]
    assert not missing, \
        "BOARD_SURFACE_MOVED harness/board_invariants.py no longer exposes %r. These fixtures " \
        "call it by name; re-point them deliberately rather than letting the call vanish." \
        % (missing,)
    # The board module must speak the CONTRACT's vocabulary, not a private copy of the strings.
    # Two modules with two spellings of MISSING_MARKET_PRICE is how a vocabulary forks.
    for local, shared in (("REASON_MISSING_MARKET_PRICE", sa.BOARD_REASON_MISSING_MARKET_PRICE),
                          ("REASON_AVAILABILITY_UNKNOWN", sa.BOARD_REASON_AVAILABILITY_UNKNOWN),
                          ("REASON_MODEL_CONVERGENCE_FAIL",
                           sa.BOARD_REASON_MODEL_CONVERGENCE_FAIL),
                          ("REASON_ASSUMED_NO_VIG", sa.BOARD_REASON_ASSUMED_NO_VIG)):
        assert getattr(mod, local) == shared, \
            "board_invariants.%s is %r; score_admission says %r — the vocabulary has forked" \
            % (local, getattr(mod, local), shared)
    return mod


# =============================================================================================
# 4. THE META-TEST.  A fixture that passes with its guard removed is testing nothing.
# =============================================================================================

#: The ten, named and hard-coded rather than derived from globals(). Deriving the list would make
#: the suite agree with whatever it happens to contain, which is the self-referential-fixture
#: defect result_binding_gate's selftest documents when it hard-codes its own field names instead
#: of looping over REQUIRED_FIELDS. A fixture deleted from this file must break this tuple.
TEN_FIXTURES = (
    "test_future_game_with_confident_search_final",
    "test_live_game_incorrectly_labeled_final",
    "test_historical_same_team_matchup_returned_for_today",
    "test_doubleheader_is_ambiguous_by_team_names",
    "test_postponed_game_with_an_old_event_id",
    "test_status_complete_but_not_closed",
    "test_mutable_archive_changes_under_the_same_filename",
    "test_missing_market_price_with_a_calculated_edge",
    "test_ml_and_spread_rows_from_incompatible_margins",
    "test_stale_injury_report_beyond_the_freshness_deadline",
)

#: fixture name -> (subject module, what the removal restores, old source, new source).
#: Each `old` is an EXACT substring of the subject's source, matched before the subject's own
#: MUTANTS list so a pattern cannot edit its own definition and report a clean apply.
GUARDS = {
    "test_future_game_with_confident_search_final": (
        "score_admission",
        "a final before first pitch is admitted again (8/30 BOS@NYY, COL@ATL)",
        "    if start_utc is not None and now < start_utc and (claims_score or claims_terminal):",
        "    if False:"),

    "test_live_game_incorrectly_labeled_final": (
        "score_admission",
        "a canonical IN_PROGRESS status stops contradicting a terminal search claim (MIA@WSH)",
        "LIVE_UNDERWAY_STATES = frozenset({IN_PROGRESS, DELAYED, SUSPENDED})",
        "LIVE_UNDERWAY_STATES = frozenset()"),

    "test_historical_same_team_matchup_returned_for_today": (
        "score_admission",
        "binding falls back to a matchup join when the event id misses (PRIOR_DATE_SERIES_JOIN)",
        '        entry = idx.get(record["event_id"])',
        '        entry = idx.get(record["event_id"]) or next('
        '(idx[_e] for _e in schedule_entries_for_matchup('
        'idx, record.get("league"), record.get("away_team_id"), '
        'record.get("home_team_id"))), None)'),

    "test_doubleheader_is_ambiguous_by_team_names": (
        "score_collector",
        "the collector dedupes by matchup, collapsing a doubleheader into one game",
        "        records.append(record)",
        "        if not any((_x.get(\"league\"), _x.get(\"away_team_id\"), _x.get(\"home_team_id\"),"
        " _x.get(\"date_et\")) == (record.get(\"league\"), record.get(\"away_team_id\"),"
        " record.get(\"home_team_id\"), record.get(\"date_et\")) for _x in records):"
        " records.append(record)"),

    "test_postponed_game_with_an_old_event_id": (
        "score_admission",
        "a postponed game's old event id no longer requires a rebind",
        '        if successor and successor != record["event_id"]:',
        "        if False:"),

    "test_status_complete_but_not_closed": (
        "score_admission",
        "'complete' counts as validated, so an unvalidated final becomes settleable",
        "VALIDATED_STATES = frozenset({CLOSED})",
        "VALIDATED_STATES = frozenset({CLOSED, COMPLETE})"),

    "test_mutable_archive_changes_under_the_same_filename": (
        "verified_snapshot",
        "the stored raw payload is never re-hashed, so bytes may change under one filename",
        '        if actual != declared.get("sha256"):',
        "        if False:"),

    "test_missing_market_price_with_a_calculated_edge": (
        "board_invariants",
        "a null entry.price_american stops refusing the edge computed against an assumed no-vig",
        "        codes.append(REASON_MISSING_MARKET_PRICE)",
        "        pass  # guard removed"),

    "test_ml_and_spread_rows_from_incompatible_margins": (
        "board_invariants",
        "two arms implying opposite projected margins stop failing convergence (MIN@ATL)",
        "    if opposite or gap > CONVERGENCE_MARGIN_TOLERANCE_POINTS:",
        "    if False:"),

    "test_stale_injury_report_beyond_the_freshness_deadline": (
        "board_invariants",
        "stale or unresolved availability stops suppressing the play that depends on it",
        "    if state == AVAILABILITY_UNKNOWN and play_bearing:",
        "    if False:"),
}


def _mutant_module(module_name, old, new):
    """Exec `module_name`'s source with `old` replaced by `new`, into a throwaway module.

    Source-level mutation rather than a globals() patch, because the guards under test are inline
    conditions inside admit(), normalize_statsapi and verify_snapshot — there is no name to
    rebind. The real module on disk is never touched, so reverting is free.

    The `body` slice reproduces the SELF_TARGETED guard the repo's Style A suites carry: a pattern
    that occurs only inside the subject's own MUTANTS list would edit that list, apply cleanly,
    change no behaviour and report a survivor.
    """
    path = os.path.join(HERE, module_name + ".py")
    with open(path) as fh:
        src = fh.read()
    body = src[:src.index("MUTANTS = [")] if "MUTANTS = [" in src else src
    if old not in src:
        raise AssertionError(
            "GUARD_NOT_FOUND harness/%s.py no longer contains the guard this suite claims to "
            "exercise: %r. Either the guard moved (re-point GUARDS) or it is gone (which is the "
            "defect)." % (module_name, old[:120]))
    if old not in body:
        raise AssertionError(
            "GUARD_SELF_TARGETED the pattern for harness/%s.py occurs only inside that module's "
            "own MUTANTS list, so mutating it would change no behaviour: %r"
            % (module_name, old[:120]))
    mutant = types.ModuleType(module_name + "__mutant")
    mutant.__dict__["__file__"] = path
    exec(compile(src.replace(old, new, 1), "<mutant:%s>" % module_name, "exec"), mutant.__dict__)
    return mutant


def _install_mutant(module_name, mutant):
    """Point this suite's own references at the mutant. Returns a zero-argument restore."""
    g = globals()
    if module_name == "score_admission":
        original = g["sa"]
        g["sa"] = mutant
        return lambda: g.__setitem__("sa", original)
    original = _MODULES.get(module_name)
    _MODULES[module_name] = mutant
    def restore():
        if original is None:
            _MODULES.pop(module_name, None)
        else:
            _MODULES[module_name] = original
    return restore


#: How a fixture ended. ASSERTION is the only legitimate way for a fixture to fail: it means a
#: stated expectation was checked and was wrong. Anything else is the subject crashing, which is
#: a different fact and must not be counted as a kill.
KIND_PASS = "PASS"
KIND_ASSERTION = "ASSERTION"


def _run_fixture(name):
    """(passed, kind, message). A fixture 'passes' only by returning without an assertion."""
    fn = globals().get(name)
    if not callable(fn):
        return False, "NO_SUCH_FIXTURE", "this file does not define %s" % name
    try:
        fn()
        return True, KIND_PASS, ""
    except AssertionError as e:
        return False, KIND_ASSERTION, (str(e).splitlines()[0][:220] if str(e) else "bare assert")
    except Exception as e:                                    # noqa: BLE001 — name it, don't hide
        return False, type(e).__name__, (str(e).splitlines()[0][:200] if str(e) else "")


def guard_report(verbose=False):
    """Remove each fixture's guard and require THAT fixture to fail. Returns (results, problems).

    results is a list of (fixture, guard description, killed: bool, note).

    A kill must be an ASSERTION. A mutant that dies of an AttributeError or a TypeError has not
    been caught by the fixture, it has crashed the subject, and the two are not the same fact.
    score_admission's first mutation run reported 12/12 KILLED while every mutant was dying at
    import — the suite proved nothing and looked perfect doing it. That is checked here.
    """
    results, problems = [], []
    missing = [n for n in TEN_FIXTURES if GUARDS.get(n) is None]
    for name in missing:
        problems.append(
            "NO_GUARD_DECLARED %s has no entry in GUARDS, so nothing proves it exercises the "
            "code path it claims. An undeclared guard is the wnba_refresh_espn shape: the "
            "fixture may already be passing for free." % name)
    for name in TEN_FIXTURES:
        guard = GUARDS.get(name)
        if guard is None:
            results.append((name, "(no guard declared)", False, "NO_GUARD_DECLARED"))
            continue
        module_name, description, old, new = guard
        if module_name in PARALLEL_MODULES and _MODULES.get(module_name) is None:
            problems.append(
                "MISSING_SUBJECT %s guards harness/%s.py, which is not importable (%s). The "
                "guard cannot be removed from a module that is not there."
                % (name, module_name, _IMPORT_ERRORS.get(module_name, "unknown")))
            results.append((name, description, False, "MISSING_SUBJECT " + module_name))
            continue
        try:
            mutant = _mutant_module(module_name, old, new)
        except AssertionError as e:
            problems.append("%s: %s" % (name, e))
            results.append((name, description, False, str(e).split()[0]))
            continue
        except Exception as e:                                # noqa: BLE001
            problems.append("%s: the mutated source of %s did not import: %s: %s"
                            % (name, module_name, type(e).__name__, e))
            results.append((name, description, False, "MUTANT_DID_NOT_IMPORT"))
            continue
        restore = _install_mutant(module_name, mutant)
        try:
            passed, kind, message = _run_fixture(name)
        finally:
            restore()
        killed = (not passed) and kind == KIND_ASSERTION
        results.append((name, description, killed, message if not passed else ""))
        if passed:
            problems.append(
                "GUARD_SURVIVED %s still passes with this guard removed from harness/%s.py — "
                "'%s'. The fixture is not exercising the code path it claims."
                % (name, module_name, description))
        elif kind != KIND_ASSERTION:
            problems.append(
                "GUARD_CRASHED %s did not CATCH the removal of '%s' in harness/%s.py; the "
                "subject raised %s (%s). A crash is not a caught defect, and a suite that counts "
                "one is the 12/12-killed-at-import failure score_admission recorded."
                % (name, description, module_name, kind, message))
        if verbose:
            mark = "  KILLED    " if killed else ("  SURVIVED  " if passed else "  CRASHED   ")
            print(mark + name + "  <- " + description)
            if killed:
                print("             caught by: " + message)
    return results, problems


def test_meta_every_fixture_exercises_its_guard():
    """META. Break each guard on purpose; the fixture that names it must fail.

    A counter that cannot fail is not a check, and a fixture that cannot fail is not a test. Ten
    fixtures, ten guards, ten required kills. This also asserts the suite's own bookkeeping: the
    ten names exist, the vocabulary they assert against is the contract's and not a retyped copy,
    and nothing has been quietly removed.
    """
    for name in TEN_FIXTURES:
        assert callable(globals().get(name)), \
            "TEN_FIXTURES names %s and this file does not define it" % name
    declared = {n for n in globals() if n.startswith("test_")} - {META_TEST}
    assert set(TEN_FIXTURES) == declared, \
        "the fixture set and TEN_FIXTURES have drifted: only in file %r, only in tuple %r" \
        % (sorted(declared - set(TEN_FIXTURES)), sorted(set(TEN_FIXTURES) - declared))

    # The record shape asserted by the fixtures is the contract's shape, not a local copy.
    sample = _rec(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", START_1215ET, sa.CLOSED, 2, 9)
    assert set(sa.RECORD_FIELDS) <= set(sample), \
        "the fixture record is missing contract fields %r" \
        % sorted(set(sa.RECORD_FIELDS) - set(sample))
    ok, problems = sa.validate_record(sample)
    assert ok, "the fixtures' own record constructor builds an invalid record: %r" % (problems,)

    # No SEARCH-lane verdict anywhere in this suite may be admitted or routed off quarantine.
    for lane_record in (_rec(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", START_1215ET, sa.CLOSED,
                             2, 9, source="web_search", fetched=EVENING),):
        v = sa.admit(lane_record, now_utc=EVENING, canonical_schedule=None,
                     lane=sa.LANE_SEARCH, corroborations=9)
        assert not v.admitted, "nine corroborating search sources admitted a final"
        assert sa.sink_for(v) == sa.SINK_QUARANTINE

    # BASELINE FIRST. A fixture that is already failing makes its mutant look killed, so a broken
    # suite would report a perfect score — module_manifest printed 11/11 on 2026-08-25 while its
    # own selftest was failing. Checked here too, so the guarantee holds under pytest, where the
    # mutation suite's own baseline gate never runs.
    broken = []
    for name in TEN_FIXTURES:
        passed, kind, message = _run_fixture(name)
        if not passed:
            broken.append("%s (%s): %s" % (name, kind, message))
    assert not broken, \
        "BASELINE_FAILING every 'kill' below would be meaningless until these pass:\n  " \
        + "\n  ".join(broken)

    results, problems = guard_report()
    assert not problems, "META FAILURES:\n  " + "\n  ".join(problems)
    killed = [r for r in results if r[2]]
    assert len(killed) == len(TEN_FIXTURES), \
        "%d of %d guards were killed; survivors mean decorative fixtures: %r" \
        % (len(killed), len(TEN_FIXTURES), [r[0] for r in results if not r[2]])


# =============================================================================================
# 5. SELFTEST / MUTATION SUITE / GATE
# =============================================================================================

META_TEST = "test_meta_every_fixture_exercises_its_guard"

#: Every callable this file runs, in a fixed order. The meta-test runs LAST so its mutants cannot
#: leave a module swapped for the fixtures that follow.
ALL_TESTS = TEN_FIXTURES + (META_TEST,)


def selftest():
    """Run the ten fixtures and the meta-test. Returns True on pass (the stated repo convention).

    Detail lines are printed BEFORE the banner on purpose: healthcheck reads the LAST line
    containing "selftest:" and requires this module's id to be in it, so nothing may follow the
    banner that could carry that substring.
    """
    f = []

    # ASSERTIONS ENABLED. Every fixture in this file is a bare `assert`, so under `python3 -O`
    # all ten would pass by doing nothing at all — a whole suite silently converted into the
    # wnba_refresh_espn failure mode by one interpreter flag. Proved, not assumed.
    _asserts_live = False
    try:
        assert False
    except AssertionError:
        _asserts_live = True
    if not _asserts_live:
        f.append("ASSERTIONS_DISABLED this interpreter was started with -O, so every fixture "
                 "below passes without checking anything")

    if MODULE_ID != os.path.basename(__file__)[:-3]:
        f.append("MODULE_ID %r does not name this file" % MODULE_ID)
    for name in PARALLEL_MODULES:
        if _MODULES.get(name) is None:
            f.append("MISSING_SUBJECT harness/%s.py is not importable (%s) — the fixtures that "
                     "depend on it FAIL rather than skip" % (name, _IMPORT_ERRORS.get(name)))

    for name in ALL_TESTS:
        passed, kind, message = _run_fixture(name)
        if not passed:
            f.append("%s [%s]: %s" % (name, kind, message))

    for line in f:
        print("  FAIL:", line)
    print("%s selftest: %s" % (MODULE_ID, "OK" if not f else "FAIL"))
    return not f


def mutation_suite():
    """The meta-test, printed. Each guard removed; each fixture must then fail.

    Baseline first: a failing fixture makes every mutant look killed, so a broken suite would
    report a perfect score. That guard is on file — module_manifest printed 11/11 on 2026-08-25
    while its own selftest was failing.
    """
    baseline = []
    for name in TEN_FIXTURES:
        passed, kind, message = _run_fixture(name)
        if not passed:
            baseline.append("%s [%s]: %s" % (name, kind, message))
    if baseline:
        print("  BASELINE_FAILING  the unmutated fixtures do not pass; every 'kill' below would "
              "be meaningless until they do")
        for line in baseline:
            print("   -", line)
        return False

    results, problems = guard_report(verbose=True)
    killed = sum(1 for r in results if r[2])
    for line in problems:
        print("   -", line)
    print("%s mutation suite: %d/%d killed%s"
          % (MODULE_ID, killed, len(TEN_FIXTURES),
             "" if killed == len(TEN_FIXTURES) else "  — SURVIVORS MEAN DECORATIVE FIXTURES"))
    return killed == len(TEN_FIXTURES) and not problems


def gate():
    """Healthcheck entry point: the ten fixtures hold AND every guard is provably load-bearing."""
    import io as _io
    import contextlib as _cl
    buf = _io.StringIO()
    with _cl.redirect_stdout(buf):
        ok_self = selftest()
        ok_mut = mutation_suite()
    print("score admission regression gate: %s (fixtures %s, guards %s)"
          % ("PASS" if (ok_self and ok_mut) else "FAIL",
             "OK" if ok_self else "FAIL", "OK" if ok_mut else "FAIL"))
    if not (ok_self and ok_mut):
        print(buf.getvalue().strip())
    return 0 if (ok_self and ok_mut) else 1


if __name__ == "__main__":
    if "--mutants" in sys.argv:
        sys.exit(0 if mutation_suite() else 1)
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    if "--gate" in sys.argv:
        sys.exit(gate())
    print(__doc__)
