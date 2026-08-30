#!/usr/bin/env python3
"""SCORE ADMISSION — the one place that decides whether a score may be believed.

THE TWO INCIDENTS THIS MODULE ANSWERS.

2026-08-27. Five fabricated MLB finals were PUBLISHED. They came from a summary of web search
results. No feed was consulted, no game id was bound, no status field was read. Nothing in code
refused them, because nothing in code was asked.

2026-08-30 13:30 ET. A web search returned three confident MLB finals:

    "Nationals 9, Marlins 2"    MIA@WSH first pitch 12:15 ET -> 75 minutes into a ~170 minute game
    "Yankees 1, Red Sox 0"      BOS@NYY first pitch 13:35 ET -> HAD NOT STARTED
    "Braves 6, Rockies 4"       COL@ATL first pitch 13:35 ET -> HAD NOT STARTED

Two of the three were finals for games that had not begun. All three were refused BY HAND. A
refusal that depends on a human noticing the clock is not a control; it is luck with a good
reputation. This module is the control.

WHAT EACH RULE WOULD HAVE STOPPED, named:

  pre-start hard invariant      BOS@NYY 1-0 and COL@ATL 6-4 on 8/30. now < first pitch, so a
                                final is not merely unlikely, it is IMPOSSIBLE.
  provider status required      the five 8/27 finals. A summary carries prose, not a status field;
                                with no status there is nothing to be terminal, so nothing admits.
  terminal-status gate          MIA@WSH on 8/30. The game was IN_PROGRESS; in-progress is never
                                final, however confident the sentence reads.
  event-id binding              the 8/27 "same matchup, wrong day" class (see
                                result_binding_gate.py, PRIOR_DATE_SERIES_JOIN). Team names do not
                                identify a baseball game; a three-game series repeats them.
  lane separation               all eight fabricated/near-fabricated scores. Search may write to
                                quarantine and to nothing else, ever.
  content hash retained         a mutable archive that changes bytes under one filename cannot be
                                caught without one.

THE SPLIT CLOCK RULE, and why it is split. The owner sent two messages that disagree. Message 1
made provider status the PRIMARY gate and the clock SECONDARY, reasoning that a legitimately short
game (rain-shortened, called, forfeit) would be false-rejected by a minimum-duration rule.
Message 2 time-gated EVERYTHING as a hard reject. The lead resolved it by splitting the clock into
two rules that behave differently, because they are not the same claim:

  (a) PRE-START is HARD and unconditional. now < scheduled_start means a final is IMPOSSIBLE, not
      improbable. No provider status may override it — a provider asserting a final before first
      pitch is either a provider bug or a MIS-BOUND GAME (the id points at yesterday's game, or at
      the other half of a doubleheader), and both of those must refuse. This rule cannot
      false-reject a short game, because no game ends before it begins.
      Disposition: REJECT_PRESTART_OR_UNBOUND.

  (b) MINIMUM-DURATION is SOFT. It is the rule that CAN false-reject the rain-shortened game, so on
      its own it yields UNVERIFIED_TOO_SOON — a hold, not a refusal — which a TERMINAL PROVIDER
      STATUS FROM THE CANONICAL LANE clears. A SEARCH snippet can never clear it. That keeps
      message 1's correct instinct (status is primary) without giving up message 2's protection
      (the 8/30 snippets were all inside the window and all had no canonical status to clear it).

Also decided by the lead, and encoded here: consensus between two SEARCH sources raises the grade
at most to IDENTIFIED_UNCONFIRMED_CORROBORATED. Search NEVER mints FINAL, corroborated or not,
because two outlets running one wire feed are ONE source wearing two names. corroboration_count()
therefore de-duplicates by wire_service before it counts.

COMPLETE vs CLOSED. Some providers distinguish "complete" (the game is over) from "closed" (the
statistics have been validated). Only the validated state is settled. That distinction is carried
by two SEPARATE sets — TERMINAL_STATES and VALIDATED_STATES — and by terminal_verified, which is
True only for a validated state. A COMPLETE record admits as FINAL_UNVALIDATED: readable, not
settleable. Merging the two sets is mutant M2 of the suite below, and it must be caught.

NO NETWORK. This module performs no I/O of any kind. ALLOW_DIRECT_HTTP is declared False so the
posture is stated rather than assumed, and selftest S0 scans this file's own source for network
call sites so the declaration cannot quietly stop being true. There is no fetch entry point here,
so this module is deliberately NOT registered in test_egress_discipline.GUARDED; if a fetcher is
ever added, register it in the same commit.

WHAT THIS MODULE IS NOT. It does not fetch, does not build snapshots, does not render a board and
does not enforce the pre-publication board invariants. It is the SHARED VOCABULARY those modules
import: lanes, statuses, dispositions, reason codes, the normalized record, and admit(). The
board-side reason codes at the bottom are defined here for one reason only — three modules were
being built in parallel and a retyped string literal is how a vocabulary forks.

Usage: python3 harness/score_admission.py [--selftest] [--mutants] [--gate]
"""
from __future__ import annotations

MODULE_ID = "score_admission"

import datetime as dt
import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import freshness_contract as fc            # noqa: E402  grade vocabulary, bound not retyped
from feed_espn import et_date_of, parse_utc  # noqa: E402  ET derivation lives in ONE place

UTC = dt.timezone.utc

#: This module reaches nothing. The flag exists so the posture is DECLARED (test_egress_discipline
#: asserts the flag is literally True or False on every fetching module); S0 below proves the
#: declaration by scanning this file for call sites, so it is a check and not a decoration.
ALLOW_DIRECT_HTTP = False


# ---------------------------------------------------------------------------------------------
# 1. LANES.  Who may write WHERE. This is data, not prose, so a checker can enforce it.
# ---------------------------------------------------------------------------------------------

LANE_CANONICAL = "CANONICAL"
LANE_SEARCH = "SEARCH"
LANE_MARKET = "MARKET"
LANES = (LANE_CANONICAL, LANE_SEARCH, LANE_MARKET)

LANE_TRUST = {LANE_CANONICAL: "HIGH", LANE_SEARCH: "LOW", LANE_MARKET: "MEDIUM"}

#: Write targets. A sink is a place bytes land; the point of naming them is that "the board" and
#: "quarantine" must be different nouns before a rule can keep them apart.
SINK_BOARD = "board"
SINK_RESULT_LEDGER = "result_ledger"
SINK_QUARANTINE = "quarantine"
SINK_PRICE_ROWS = "price_rows"
SINKS = (SINK_BOARD, SINK_RESULT_LEDGER, SINK_QUARANTINE, SINK_PRICE_ROWS)

#: THE LANE TABLE. SEARCH holds exactly one sink, and it is quarantine. On 2026-08-27 a search
#: summary reached the published card; there was no table to consult, so there was nothing to
#: violate. Now there is.
LANE_WRITE_TARGETS = {
    LANE_CANONICAL: frozenset({SINK_BOARD, SINK_RESULT_LEDGER, SINK_QUARANTINE}),
    LANE_SEARCH: frozenset({SINK_QUARANTINE}),
    LANE_MARKET: frozenset({SINK_PRICE_ROWS}),
}

#: The analysis layer (Claude, card generation) may call these and nothing else. Named here so the
#: snapshot module and the card module cannot drift on the spelling.
ANALYSIS_TOOL_SURFACE = ("get_verified_score", "get_verified_scores", "get_source_manifest")

#: ...and may never mutate these directly, whatever it learns.
FORBIDDEN_DIRECT_MUTATIONS = ("raw_feed", "result_ledger", "settled_game_table")


class LaneViolation(RuntimeError):
    """A lane tried to write to a sink its row of LANE_WRITE_TARGETS does not contain."""


def may_write(lane, sink):
    """May `lane` write to `sink`? Unknown lane or unknown sink is False, never a shrug."""
    return sink in LANE_WRITE_TARGETS.get(lane, frozenset())


def assert_write_allowed(lane, sink):
    """Raise LaneViolation unless the table permits it. Returns True so it can be asserted."""
    if not may_write(lane, sink):
        raise LaneViolation(
            "%s: lane=%r sink=%r permitted=%s" %
            (REASON_LANE_FORBIDDEN_SINK, lane, sink,
             sorted(LANE_WRITE_TARGETS.get(lane, frozenset()))))
    return True


def assert_tool_allowed(name):
    """Raise LaneViolation unless `name` is one of the three read-only analysis tools."""
    if name not in ANALYSIS_TOOL_SURFACE:
        raise LaneViolation(
            "TOOL_NOT_ON_ANALYSIS_SURFACE: %r; permitted=%s" % (name, list(ANALYSIS_TOOL_SURFACE)))
    return True


# ---------------------------------------------------------------------------------------------
# 2. STATUS.  One vocabulary, and the provider mappings that reach it.
# ---------------------------------------------------------------------------------------------

SCHEDULED = "SCHEDULED"
PRE_GAME = "PRE_GAME"
IN_PROGRESS = "IN_PROGRESS"
DELAYED = "DELAYED"
POSTPONED = "POSTPONED"
SUSPENDED = "SUSPENDED"
COMPLETE = "COMPLETE"
CLOSED = "CLOSED"
UNKNOWN = "UNKNOWN"

STATUSES = (SCHEDULED, PRE_GAME, IN_PROGRESS, DELAYED, POSTPONED, SUSPENDED,
            COMPLETE, CLOSED, UNKNOWN)

#: TERMINAL: the game is over. VALIDATED: the statistics are validated as well. They are separate
#: sets on purpose — see the COMPLETE vs CLOSED paragraph of the module docstring. COMPLETE is in
#: the first and NOT in the second, and mutant M2 exists to prove that stays true.
TERMINAL_STATES = frozenset({COMPLETE, CLOSED})
VALIDATED_STATES = frozenset({CLOSED})

#: Everything that is not terminal is non-final, INCLUDING unknown, delayed, postponed and
#: in-progress (owner rule 8). Stated as a set so the partition can be asserted, not assumed.
NON_FINAL_STATES = frozenset({SCHEDULED, PRE_GAME, IN_PROGRESS, DELAYED, POSTPONED,
                              SUSPENDED, UNKNOWN})

#: The game is known to be underway and not over. A claimed FINAL against one of these from the
#: canonical schedule is a contradiction, not a scoop — this is the MIA@WSH shape of 8/30.
LIVE_UNDERWAY_STATES = frozenset({IN_PROGRESS, DELAYED, SUSPENDED})

#: States in which the game has provably not started. Used only for reporting; the pre-start rule
#: is decided by the CLOCK, not by this set, because a stale status field is exactly what fails.
PRE_START_STATES = frozenset({SCHEDULED, PRE_GAME})

PROVIDER_MLB_STATSAPI = "mlb_statsapi"          # feed_mlb_statsapi record["source"]
PROVIDER_ESPN_SCOREBOARD = "espn_scoreboard_api"  # feed_espn record["source"]
PROVIDER_SPORTRADAR = "sportradar"

#: MLB StatsAPI statusCode -> this vocabulary. ONLY what this repo evidences is mapped:
#:   "F"  detailedState "Final", observed 20x across data/ (the 8/28 LIVE capture and fixtures)
#:        and listed in feed_mlb_statsapi.FINAL_STATUS_CODES as "Final". -> CLOSED.
#:   "O"  listed in feed_mlb_statsapi.FINAL_STATUS_CODES with the comment "Game Over" and NEVER
#:        OBSERVED in any payload in this repo. The repo evidences that it is a SECOND, distinct
#:        state from "Final", so it maps to the weaker of the two — COMPLETE, terminal but not
#:        validated. Mapping an unobserved code to the stronger state would be inventing.
#:   "DD" detailedState "Postponed", codedGameState "D", observed once
#:        (data/mlb/schedule/2026-07-17_espn_verify.json, PIT@CLE, reason "Air Quality").
#:   "S"  detailedState "Scheduled", observed twice.
#: EVERY OTHER statusCode -> UNKNOWN. The repo has witnessed exactly F(20), DD(1), S(1) in data/
#: plus the O declaration in code. Writing a mapping for "I", "PW", "IR", "UR", "CR", "MA" or any
#: other code would be me describing the API from memory, which is R1's definition of inventing.
#: UNKNOWN is non-final, so an unmapped code refuses rather than admits.
MLB_STATUSCODE_TO_STATUS = {
    "F": CLOSED,
    "O": COMPLETE,
    "DD": POSTPONED,
    "S": SCHEDULED,
}

#: ESPN status.type.name -> this vocabulary. feed_espn declares exactly three constants
#: (STATUS_FINAL, STATUS_SCHEDULED, STATUS_POSTPONED); those three are mapped and nothing else is.
#: STATUS_FINAL -> COMPLETE, NOT CLOSED: the scoreboard API exposes no statistics-validation state
#: anywhere in this repo, so an ESPN final is over-but-unvalidated. It reads; it does not settle.
ESPN_STATUS_TO_STATUS = {
    "STATUS_FINAL": COMPLETE,
    "STATUS_SCHEDULED": SCHEDULED,
    "STATUS_POSTPONED": POSTPONED,
}

#: Sportradar. The owner directive names exactly two states, "complete" and "closed", and that
#: naming is the entire reason TERMINAL_STATES and VALIDATED_STATES are separate sets. Only those
#: two are mapped: the repo holds no Sportradar payload of any kind.
SPORTRADAR_STATUS_TO_STATUS = {
    "complete": COMPLETE,
    "closed": CLOSED,
}

PROVIDER_STATUS_MAPS = {
    PROVIDER_MLB_STATSAPI: MLB_STATUSCODE_TO_STATUS,
    PROVIDER_ESPN_SCOREBOARD: ESPN_STATUS_TO_STATUS,
    PROVIDER_SPORTRADAR: SPORTRADAR_STATUS_TO_STATUS,
}


def normalize_status(raw_status, provider):
    """Provider status string -> this vocabulary. Anything unmapped is UNKNOWN, never guessed.

    UNKNOWN is a non-final state, so an unrecognised code degrades to a refusal rather than
    falling through to whatever the caller hoped it meant.
    """
    table = PROVIDER_STATUS_MAPS.get(provider)
    if table is None:
        return UNKNOWN
    if raw_status is None:
        return UNKNOWN
    return table.get(str(raw_status), UNKNOWN)


def is_terminal(status):
    """The game is over (may or may not be validated)."""
    return status in TERMINAL_STATES


def is_validated(status):
    """The statistics are validated: this is the only state that may settle a wager."""
    return status in VALIDATED_STATES


def terminal_verified_for(status):
    """THE generator of record["terminal_verified"]. Never type that field by hand."""
    return status in VALIDATED_STATES


# ---------------------------------------------------------------------------------------------
# 3. DISPOSITIONS.
# ---------------------------------------------------------------------------------------------

ADMIT_FINAL = "ADMIT_FINAL"
ADMIT_IN_PROGRESS = "ADMIT_IN_PROGRESS"
UNVERIFIED = "UNVERIFIED"
UNVERIFIED_TOO_SOON = "UNVERIFIED_TOO_SOON"
REJECT_PRESTART_OR_UNBOUND = "REJECT_PRESTART_OR_UNBOUND"
REJECT_SCHEDULE_CONFLICT = "REJECT_SCHEDULE_CONFLICT"
REJECT_LANE_FORBIDDEN = "REJECT_LANE_FORBIDDEN"
NO_CONSENSUS = "NO_CONSENSUS"
NO_DATA_LANE_DOWN = "NO_DATA_LANE_DOWN"

DISPOSITIONS = (ADMIT_FINAL, ADMIT_IN_PROGRESS, UNVERIFIED, UNVERIFIED_TOO_SOON,
                REJECT_PRESTART_OR_UNBOUND, REJECT_SCHEDULE_CONFLICT, REJECT_LANE_FORBIDDEN,
                NO_CONSENSUS, NO_DATA_LANE_DOWN)

DISPOSITION_MEANING = {
    ADMIT_FINAL: "the score may be read as the result of this game; settleable only when "
                 "admissible_as == FINAL (a validated status), not merely FINAL_UNVALIDATED",
    ADMIT_IN_PROGRESS: "a live snapshot of a game that is underway; never a result, never graded",
    UNVERIFIED: "identified but not verified: it may be stored and shown as unverified, and it "
                "may not become a result",
    UNVERIFIED_TOO_SOON: "the soft minimum-duration hold: too early for this to be over, and no "
                         "canonical terminal status has cleared it",
    REJECT_PRESTART_OR_UNBOUND: "impossible or unbound — a score before first pitch, or a record "
                                "that names no event in the canonical schedule",
    REJECT_SCHEDULE_CONFLICT: "the record disagrees with the canonical schedule on teams, league, "
                              "date or start, or is bound to a superseded event id",
    REJECT_LANE_FORBIDDEN: "this lane may not produce a score at all",
    NO_CONSENSUS: "a search-derived claim with fewer than two INDEPENDENT sources agreeing on "
                  "score, status and result timestamp",
    NO_DATA_LANE_DOWN: "the lane is down; this is an explicit absence of data and must never be "
                       "read as 'no games' or backfilled from search",
}

#: Dispositions that let a score reach an analysis layer at all.
ADMITTING_DISPOSITIONS = (ADMIT_FINAL, ADMIT_IN_PROGRESS)

#: admissible_as — WHAT the caller is allowed to treat the record as. The first two are the
#: complete/closed split; the last two are bound to freshness_contract's grades rather than
#: retyped, so the two modules cannot drift.
ADMISSIBLE_FINAL = "FINAL"
ADMISSIBLE_FINAL_UNVALIDATED = "FINAL_UNVALIDATED"
ADMISSIBLE_IN_PROGRESS = "IN_PROGRESS_SNAPSHOT"
ADMISSIBLE_IDENTIFIED_UNCONFIRMED = fc.IDENTIFIED_UNCONFIRMED
ADMISSIBLE_CORROBORATED = fc.IDENTIFIED_UNCONFIRMED + "_CORROBORATED"
ADMISSIBLE_AS_VALUES = (ADMISSIBLE_FINAL, ADMISSIBLE_FINAL_UNVALIDATED, ADMISSIBLE_IN_PROGRESS,
                        ADMISSIBLE_IDENTIFIED_UNCONFIRMED, ADMISSIBLE_CORROBORATED)


# ---------------------------------------------------------------------------------------------
# 4. THE TEMPORAL KILL-SWITCH.
# ---------------------------------------------------------------------------------------------

#: Owner's minimums, verbatim. A game cannot plausibly be over before start + this many minutes.
MIN_DURATION_MINUTES = {"MLB": 150, "NBA": 120, "WNBA": 120, "NFL": 165, "CFB": 180}

LEAGUES = tuple(sorted(MIN_DURATION_MINUTES))

#: feed_espn keys CFB as "college-football" while freshness_contract keys it "cfb". Crossing those
#: two silently is a known hazard; this is the explicit map, and it is the only alias table.
LEAGUE_ALIASES = {"COLLEGE-FOOTBALL": "CFB", "COLLEGE_FOOTBALL": "CFB", "NCAAF": "CFB"}


def normalize_league(value):
    """League string -> one of LEAGUES, or None. Case-insensitive; aliases via LEAGUE_ALIASES."""
    if value is None:
        return None
    key = str(value).strip().upper()
    key = LEAGUE_ALIASES.get(key, key)
    return key if key in MIN_DURATION_MINUTES else None


def earliest_possible_final(scheduled_start_utc, league):
    """start + the sport's minimum plausible duration, as a tz-aware UTC datetime.

    R1: an unknown league raises rather than defaulting to some minutes number nobody chose.
    """
    start = _utc(scheduled_start_utc)
    if start is None:
        raise ValueError("UNPARSEABLE_TIMESTAMP: %r" % (scheduled_start_utc,))
    lg = normalize_league(league)
    if lg is None:
        raise ValueError("UNSUPPORTED_LEAGUE: %r (known: %s)" % (league, list(LEAGUES)))
    return start + dt.timedelta(minutes=MIN_DURATION_MINUTES[lg])


# ---------------------------------------------------------------------------------------------
# 5. REASON CODES.  A verdict is never a bare bool and never a bare string: it carries the codes
#    that produced it. REASON_MEANING is the registry, and S0 asserts every REASON_* constant is
#    in it, so a builder cannot add a code with no meaning attached.
# ---------------------------------------------------------------------------------------------

REASON_LANE_UNKNOWN = "LANE_UNKNOWN"
REASON_MARKET_LANE_NOT_A_SCORE_SOURCE = "MARKET_LANE_NOT_A_SCORE_SOURCE"
REASON_LANE_FORBIDDEN_SINK = "LANE_MAY_NOT_WRITE_THIS_SINK"

REASON_NO_EVENT_ID = "NO_PROVIDER_EVENT_ID"
REASON_EVENT_ID_MALFORMED = "EVENT_ID_MALFORMED"
REASON_EVENT_ID_PLACEHOLDER = "EVENT_ID_IS_A_PLACEHOLDER"

REASON_EVENT_NOT_IN_SCHEDULE = "EVENT_NOT_IN_CANONICAL_SCHEDULE"
REASON_SCHEDULE_TEAMS_DISAGREE = "SCHEDULE_TEAMS_DISAGREE"
REASON_SCHEDULE_TEAMS_REVERSED = "SCHEDULE_TEAMS_REVERSED"
REASON_SCHEDULE_LEAGUE_DISAGREE = "SCHEDULE_LEAGUE_DISAGREE"
REASON_SCHEDULE_DATE_DISAGREE = "SCHEDULE_DATE_DISAGREE"
REASON_SCHEDULE_START_DISAGREE = "SCHEDULE_START_DISAGREE"
REASON_POSTPONED_REBIND_REQUIRED = "POSTPONED_REBIND_REQUIRED"
REASON_CANONICAL_STATUS_CONTRADICTS_CLAIM = "CANONICAL_STATUS_CONTRADICTS_CLAIM"
REASON_MATCHUP_AMBIGUOUS_USE_EVENT_ID = "MATCHUP_AMBIGUOUS_USE_EVENT_ID"
REASON_SCHEDULE_NOT_SUPPLIED = "CANONICAL_SCHEDULE_NOT_SUPPLIED"

REASON_PRESTART_FINAL_IMPOSSIBLE = "PRESTART_FINAL_IMPOSSIBLE"
REASON_MIN_DURATION_NOT_ELAPSED = "MIN_DURATION_NOT_ELAPSED"
REASON_MIN_DURATION_CLEARED = "MIN_DURATION_CLEARED_BY_CANONICAL_TERMINAL"
REASON_SEARCH_CANNOT_CLEAR_MIN_DURATION = "SEARCH_LANE_CANNOT_CLEAR_MIN_DURATION"

REASON_STATUS_MISSING = "SOURCE_STATUS_MISSING"
REASON_STATUS_NOT_IN_VOCABULARY = "SOURCE_STATUS_NOT_IN_VOCABULARY"
REASON_STATUS_UNKNOWN = "SOURCE_STATUS_UNKNOWN"
REASON_STATUS_NOT_TERMINAL = "STATUS_NOT_TERMINAL"
REASON_STATUS_TERMINAL_NOT_VALIDATED = "STATUS_TERMINAL_NOT_VALIDATED"
REASON_STATUS_VALIDATED = "STATUS_VALIDATED"
REASON_GAME_IN_PROGRESS = "GAME_IN_PROGRESS"
REASON_GAME_POSTPONED = "GAME_POSTPONED"
REASON_GAME_SUSPENDED = "GAME_SUSPENDED"
REASON_TERMINAL_WITHOUT_SCORES = "TERMINAL_STATUS_WITHOUT_SCORES"
REASON_SCORE_WITHOUT_TERMINAL_STATUS = "SCORE_WITHOUT_TERMINAL_STATUS"
REASON_TERMINAL_VERIFIED_INCONSISTENT = "TERMINAL_VERIFIED_INCONSISTENT_WITH_STATUS"

REASON_SEARCH_LANE_CANNOT_MINT_FINAL = "SEARCH_LANE_CANNOT_MINT_FINAL"
REASON_SEARCH_CORROBORATED = "SEARCH_CORROBORATED_BY_INDEPENDENT_SOURCES"
REASON_NO_CONSENSUS_SINGLE_SOURCE = "NO_CONSENSUS_FEWER_THAN_TWO_INDEPENDENT_SOURCES"

REASON_RECORD_NOT_A_MAPPING = "RECORD_NOT_A_MAPPING"
REASON_MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
REASON_UNSUPPORTED_LEAGUE = "UNSUPPORTED_LEAGUE"
REASON_UNPARSEABLE_TIMESTAMP = "UNPARSEABLE_TIMESTAMP"
REASON_NON_NUMERIC_SCORE = "NON_NUMERIC_SCORE"
REASON_NEGATIVE_SCORE = "NEGATIVE_SCORE"
REASON_PARTIAL_SCORE = "PARTIAL_SCORE_ONE_SIDE_ONLY"
REASON_SAME_TEAM_BOTH_SIDES = "SAME_TEAM_BOTH_SIDES"
REASON_BAD_CONTENT_HASH = "RAW_RESPONSE_SHA256_NOT_A_SHA256"
REASON_SNAPSHOT_CONTENT_CHANGED = "SNAPSHOT_CONTENT_CHANGED_UNDER_SAME_KEY"
REASON_SNAPSHOT_HASH_MATCHES_CONTENT_DIFFERS = "SNAPSHOT_HASH_MATCHES_BUT_CONTENT_DIFFERS"

REASON_LANE_DOWN = "LANE_DOWN"

REASON_MEANING = {
    REASON_LANE_UNKNOWN: "the lane argument is not one of LANES",
    REASON_MARKET_LANE_NOT_A_SCORE_SOURCE: "the market lane carries prices; a price is never a "
                                           "score and never a predictive feature",
    REASON_LANE_FORBIDDEN_SINK: "this lane may not write to that sink (LANE_WRITE_TARGETS)",
    REASON_NO_EVENT_ID: "no provider event id at all — team names do not identify a game "
                        "(owner rule 1, and the 8/27 prior-date series join)",
    REASON_EVENT_ID_MALFORMED: "event_id is not '<space>:<season>:<provider_id>' shaped",
    REASON_EVENT_ID_PLACEHOLDER: "the provider id is a placeholder ('TBD', 'DH1', '0'), which is "
                                 "an absence wearing an identifier's clothes",
    REASON_EVENT_NOT_IN_SCHEDULE: "the canonical schedule holds no such event id (the unbound "
                                  "half of REJECT_PRESTART_OR_UNBOUND)",
    REASON_SCHEDULE_TEAMS_DISAGREE: "team ids differ from the canonical schedule entry",
    REASON_SCHEDULE_TEAMS_REVERSED: "home and away are swapped relative to the schedule",
    REASON_SCHEDULE_LEAGUE_DISAGREE: "league differs from the canonical schedule entry",
    REASON_SCHEDULE_DATE_DISAGREE: "ET scheduled date differs from the canonical schedule entry",
    REASON_SCHEDULE_START_DISAGREE: "scheduled start instant differs from the schedule entry",
    REASON_POSTPONED_REBIND_REQUIRED: "the schedule says this event was superseded; rebind to the "
                                      "new event id rather than scoring the old one",
    REASON_CANONICAL_STATUS_CONTRADICTS_CLAIM: "the canonical schedule says the game is underway "
                                               "while this record claims it is over",
    REASON_MATCHUP_AMBIGUOUS_USE_EVENT_ID: "more than one scheduled event shares this matchup "
                                           "(doubleheader); names cannot choose between them",
    REASON_SCHEDULE_NOT_SUPPLIED: "no canonical schedule was supplied, so the binding cross-check "
                                  "did not run — recorded so its absence is visible in the proof",
    REASON_PRESTART_FINAL_IMPOSSIBLE: "now precedes first pitch: a final is impossible, not "
                                      "improbable. Hard invariant; no status overrides it",
    REASON_MIN_DURATION_NOT_ELAPSED: "now precedes start + the sport's minimum duration",
    REASON_MIN_DURATION_CLEARED: "the soft duration hold was cleared by a terminal status from "
                                 "the canonical lane (rain-shortened and called games survive)",
    REASON_SEARCH_CANNOT_CLEAR_MIN_DURATION: "a search snippet can never clear the duration hold",
    REASON_STATUS_MISSING: "no source status field: with nothing to be terminal, nothing admits "
                           "(owner rule 3; the 8/27 summaries had no status at all)",
    REASON_STATUS_NOT_IN_VOCABULARY: "status is not one of STATUSES — normalize_status() first",
    REASON_STATUS_UNKNOWN: "the provider status did not map to a known state; UNKNOWN is treated "
                           "as non-final (owner rule 8)",
    REASON_STATUS_NOT_TERMINAL: "the status is not a terminal state, so no final may be read",
    REASON_STATUS_TERMINAL_NOT_VALIDATED: "terminal but unvalidated (complete, not closed): "
                                          "readable as a final, NOT settleable",
    REASON_STATUS_VALIDATED: "the provider reports statistics-validated: settleable",
    REASON_GAME_IN_PROGRESS: "the game is underway; in-progress is never final (MIA@WSH, 8/30)",
    REASON_GAME_POSTPONED: "postponed games are non-final and must be rebound when rescheduled",
    REASON_GAME_SUSPENDED: "a suspended game's partial score is not a result",
    REASON_TERMINAL_WITHOUT_SCORES: "terminal status with no scores — nothing to admit",
    REASON_SCORE_WITHOUT_TERMINAL_STATUS: "a score is asserted under a non-terminal status",
    REASON_TERMINAL_VERIFIED_INCONSISTENT: "terminal_verified does not equal "
                                           "terminal_verified_for(status); it was typed, not "
                                           "generated",
    REASON_SEARCH_LANE_CANNOT_MINT_FINAL: "the search lane never mints FINAL, corroborated or not",
    REASON_SEARCH_CORROBORATED: "two or more INDEPENDENT sources agree on score, status and "
                                "result timestamp; grade rises to IDENTIFIED_UNCONFIRMED_"
                                "CORROBORATED and no further",
    REASON_NO_CONSENSUS_SINGLE_SOURCE: "fewer than two independent sources; outlets sharing one "
                                       "wire feed count once",
    REASON_RECORD_NOT_A_MAPPING: "the record is not a dict",
    REASON_MISSING_REQUIRED_FIELD: "a required field is missing, None, empty or 'TBD'",
    REASON_UNSUPPORTED_LEAGUE: "league is not one of LEAGUES, so no minimum duration exists",
    REASON_UNPARSEABLE_TIMESTAMP: "a timestamp field could not be parsed as an instant",
    REASON_NON_NUMERIC_SCORE: "a score is not an int (ESPN returns scores as STRINGS; the "
                              "normalized record does not)",
    REASON_NEGATIVE_SCORE: "a score is negative",
    REASON_PARTIAL_SCORE: "one side has a score and the other does not",
    REASON_SAME_TEAM_BOTH_SIDES: "away_team_id equals home_team_id",
    REASON_BAD_CONTENT_HASH: "raw_response_sha256 is not 64 hex characters (owner rule 7)",
    REASON_SNAPSHOT_CONTENT_CHANGED: "two records share event_id + source + fetched instant but "
                                     "carry different content hashes: the archive mutated under "
                                     "one key",
    REASON_SNAPSHOT_HASH_MATCHES_CONTENT_DIFFERS: "identical content hash, different parsed "
                                                  "scores: the hash is not covering the bytes it "
                                                  "claims to cover",
    REASON_LANE_DOWN: "the lane could not be reached at all (e.g. EGRESS_BLOCKED)",
}

REASON_CODES = tuple(sorted(REASON_MEANING))

#: Named reasons a lane goes down. EGRESS_BLOCKED is the live one: on 2026-08-30 espn.com and
#: covers.com both refused this deployment's egress.
LANE_DOWN_REASONS = ("EGRESS_BLOCKED", "PROVIDER_ERROR", "NO_ADAPTER_INJECTED", "RATE_LIMITED")


# ---------------------------------------------------------------------------------------------
# 6. THE NORMALIZED RECORD.
# ---------------------------------------------------------------------------------------------

#: The owner's field names, exactly. Not a superset, not a rename.
RECORD_FIELDS = ("event_id", "league", "away_team_id", "home_team_id", "scheduled_start_utc",
                 "status", "away_score", "home_score", "terminal_verified", "source",
                 "source_fetched_at_utc", "raw_response_sha256")

#: Fields that may never be missing. Scores are absent before a game ends, so they are not here;
#: they are type-checked when present and required by the terminal path in admit().
REQUIRED_RECORD_FIELDS = ("event_id", "league", "away_team_id", "home_team_id",
                          "scheduled_start_utc", "status", "terminal_verified", "source",
                          "source_fetched_at_utc", "raw_response_sha256")

#: Optional fields admit() and corroboration_count() read when present.
#:   result_timestamp_utc  when the source says the result was determined (consensus field)
#:   wire_service          the wire the outlet ran; two outlets on one wire are ONE source
OPTIONAL_RECORD_FIELDS = ("result_timestamp_utc", "wire_service", "game_number")

#: "<space>:<season>:<provider_id>" — mlb:2026:824643. THREE parts; a two-part namespaced id
#: ("MLB_GAMEPK:824643", result_binding_gate's form) is a DIFFERENT id space and is refused here
#: rather than silently coerced. Never strip a prefix to a bare int, never join across spaces.
_EVENT_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*:[0-9]{4}:[A-Za-z0-9_.-]+$")

#: Placeholders that are an absence wearing an identifier's clothes. The first six are
#: result_binding_gate's set; DH1/DH2 are added because the 2026-08-17 cards carried them as
#: gamePks and that gate's placeholder list does not catch them (a known hole, documented here so
#: it is not re-opened on this side).
_PLACEHOLDER_IDS = ("", "NONE", "TBD", "NULL", "0", "PENDING", "DH1", "DH2")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _utc(value):
    """Any instant -> tz-aware UTC datetime, or None when unparseable. Never a guess."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        return parse_utc(value)
    except Exception:
        return None


def _iso(value):
    d = _utc(value)
    return None if d is None else d.isoformat().replace("+00:00", "Z")


def event_id_for(space, season, provider_id):
    """Compose an event id. Raises ValueError rather than emitting a malformed or placeholder id."""
    eid = "%s:%s:%s" % (space, season, provider_id)
    ok, problems = validate_event_id(eid)
    if not ok:
        raise ValueError("%s: %r" % (problems[0]["code"], eid))
    return eid


def parse_event_id(event_id):
    """'mlb:2026:824643' -> ('mlb', '2026', '824643'). Raises ValueError on anything else."""
    ok, problems = validate_event_id(event_id)
    if not ok:
        raise ValueError("%s: %r" % (problems[0]["code"], event_id))
    space, season, provider_id = str(event_id).split(":", 2)
    return space, season, provider_id


def validate_event_id(event_id):
    """(ok, problems). Owner rules 1 and 5 begin here: no id, no binding, no admission."""
    problems = []
    if event_id in (None, "") or not isinstance(event_id, str):
        problems.append({"code": REASON_NO_EVENT_ID, "field": "event_id", "value": event_id})
        return False, problems
    parts = event_id.split(":", 2)
    if not _EVENT_ID_RE.match(event_id) or len(parts) != 3:
        problems.append({"code": REASON_EVENT_ID_MALFORMED, "field": "event_id",
                         "value": event_id,
                         "detail": "expected '<space>:<season>:<provider_id>'"})
        return False, problems
    provider_id = parts[2]
    if provider_id.strip().upper() in _PLACEHOLDER_IDS:
        problems.append({"code": REASON_EVENT_ID_PLACEHOLDER, "field": "event_id",
                         "value": event_id, "provider_id": provider_id})
        return False, problems
    return True, []


def validate_record(record):
    """(ok, problems) for one normalized record. A clean record returns (True, []).

    NOTE the deliberate difference from result_binding_gate.bind_row, which returns
    [{"code": "BOUND"}] on its SUCCESS path: here an empty list means clean. Test `ok`, never the
    list, on either side.
    """
    if not isinstance(record, dict):
        return False, [{"code": REASON_RECORD_NOT_A_MAPPING, "type": type(record).__name__}]

    problems = []
    for f in REQUIRED_RECORD_FIELDS:
        v = record.get(f)
        if v is None or (isinstance(v, str) and v.strip() in ("", "TBD")):
            # Owner rule 3 carries its own code. "MISSING_REQUIRED_FIELD" would invite a future
            # maintainer to "fix" it by defaulting the status, which is exactly the bug.
            code = REASON_STATUS_MISSING if f == "status" else REASON_MISSING_REQUIRED_FIELD
            problems.append({"code": code, "field": f})

    ok_id, id_problems = validate_event_id(record.get("event_id"))
    if not ok_id and record.get("event_id") is not None:
        problems.extend(id_problems)

    if record.get("league") is not None and normalize_league(record.get("league")) is None:
        problems.append({"code": REASON_UNSUPPORTED_LEAGUE, "field": "league",
                         "value": record.get("league")})

    for f in ("scheduled_start_utc", "source_fetched_at_utc", "result_timestamp_utc"):
        if record.get(f) is not None and _utc(record.get(f)) is None:
            problems.append({"code": REASON_UNPARSEABLE_TIMESTAMP, "field": f,
                             "value": record.get(f)})

    status = record.get("status")
    if status is not None and status not in STATUSES:
        problems.append({"code": REASON_STATUS_NOT_IN_VOCABULARY, "field": "status",
                         "value": status,
                         "detail": "call normalize_status(raw, provider) before building a record"})

    # Scores. bool is an int subclass, and True would otherwise sail through as 1.
    scores = {}
    for f in ("away_score", "home_score"):
        v = record.get(f)
        scores[f] = v
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, int):
            problems.append({"code": REASON_NON_NUMERIC_SCORE, "field": f, "value": v,
                             "type": type(v).__name__})
        elif v < 0:
            problems.append({"code": REASON_NEGATIVE_SCORE, "field": f, "value": v})
    if (scores["away_score"] is None) != (scores["home_score"] is None):
        problems.append({"code": REASON_PARTIAL_SCORE, "away_score": scores["away_score"],
                         "home_score": scores["home_score"]})

    a, h = record.get("away_team_id"), record.get("home_team_id")
    if a is not None and h is not None and str(a) == str(h):
        problems.append({"code": REASON_SAME_TEAM_BOTH_SIDES, "team_id": a})

    tv = record.get("terminal_verified")
    if not isinstance(tv, bool):
        problems.append({"code": REASON_MISSING_REQUIRED_FIELD, "field": "terminal_verified",
                         "detail": "must be a bool generated by terminal_verified_for(status)"})
    elif status in STATUSES and tv != terminal_verified_for(status):
        problems.append({"code": REASON_TERMINAL_VERIFIED_INCONSISTENT, "status": status,
                         "terminal_verified": tv, "expected": terminal_verified_for(status)})

    sha = record.get("raw_response_sha256")
    if sha is not None and not _SHA256_RE.match(str(sha).strip().lower()):
        problems.append({"code": REASON_BAD_CONTENT_HASH, "field": "raw_response_sha256",
                         "value": sha})

    return (not problems), problems


def content_hash_conflict(a, b):
    """(conflict, problem|None) for two records that claim to be the same snapshot.

    Owner rule 7 and regression fixture 7 — the mutable archive whose bytes change under one
    filename. Two shapes are caught:
      - same (event_id, source, source_fetched_at_utc), different raw_response_sha256
      - same raw_response_sha256, different parsed scores  (the hash covers nothing)
    """
    key_a = (a.get("event_id"), a.get("source"), _iso(a.get("source_fetched_at_utc")))
    key_b = (b.get("event_id"), b.get("source"), _iso(b.get("source_fetched_at_utc")))
    sha_a = str(a.get("raw_response_sha256") or "").lower()
    sha_b = str(b.get("raw_response_sha256") or "").lower()
    if key_a == key_b and sha_a != sha_b:
        return True, {"code": REASON_SNAPSHOT_CONTENT_CHANGED, "key": list(key_a),
                      "sha256": [sha_a, sha_b]}
    scores_a = (a.get("away_score"), a.get("home_score"))
    scores_b = (b.get("away_score"), b.get("home_score"))
    if sha_a and sha_a == sha_b and scores_a != scores_b:
        return True, {"code": REASON_SNAPSHOT_HASH_MATCHES_CONTENT_DIFFERS, "sha256": sha_a,
                      "scores": [list(scores_a), list(scores_b)]}
    return False, None


# ---------------------------------------------------------------------------------------------
# 7. THE CANONICAL SCHEDULE.  What a record is bound AGAINST.
# ---------------------------------------------------------------------------------------------

CANONICAL_SCHEDULE_ENTRY_FIELDS = ("event_id", "league", "away_team_id", "home_team_id",
                                   "scheduled_start_utc")
#: Optional entry fields: "status" (the canonical live state), "rescheduled_to_event_id" (the
#: successor after a postponement), "scheduled_date" (explicit ET date), "game_number" (DH half).
CANONICAL_SCHEDULE_OPTIONAL_FIELDS = ("status", "rescheduled_to_event_id", "scheduled_date",
                                      "game_number")


def index_schedule(schedule):
    """Accept a dict keyed by event_id, a single entry, or a sequence of entries -> dict."""
    if schedule is None:
        return None
    if isinstance(schedule, dict):
        if "event_id" in schedule and "games" not in schedule:
            return {schedule["event_id"]: schedule}
        return dict(schedule)
    return {e["event_id"]: e for e in schedule}


def scheduled_date_of(obj):
    """The ET calendar date of a record or schedule entry. Derived via feed_espn.et_date_of.

    NEVER sliced from the UTC string: a 2026-08-31T00:30Z tip is the ET EVENING of 08-30, and
    slicing is what corrupted a cohort twice.
    """
    explicit = obj.get("scheduled_date")
    if explicit:
        return str(explicit)
    start = _utc(obj.get("scheduled_start_utc"))
    return None if start is None else et_date_of(start)


def schedule_entries_for_matchup(schedule, league, away_team_id, home_team_id, scheduled_date=None):
    """Every event id whose matchup matches. Two hits means a doubleheader: names cannot choose.

    This exists to be CALLED and found ambiguous, not to be used for binding. Binding is by
    event id (owner rule 1); this function's only job is to prove that names are not enough.
    """
    idx = index_schedule(schedule) or {}
    out = []
    for eid, entry in idx.items():
        if normalize_league(entry.get("league")) != normalize_league(league):
            continue
        if str(entry.get("away_team_id")) != str(away_team_id):
            continue
        if str(entry.get("home_team_id")) != str(home_team_id):
            continue
        if scheduled_date and scheduled_date_of(entry) != scheduled_date:
            continue
        out.append(eid)
    return sorted(out)


def _schedule_conflicts(record, entry, lane):
    """Every way the record disagrees with the canonical schedule entry. Owner rules 2 and 6."""
    conflicts = []
    if normalize_league(record.get("league")) != normalize_league(entry.get("league")):
        conflicts.append({"code": REASON_SCHEDULE_LEAGUE_DISAGREE,
                          "record": record.get("league"), "schedule": entry.get("league")})
    r_away, r_home = str(record.get("away_team_id")), str(record.get("home_team_id"))
    e_away, e_home = str(entry.get("away_team_id")), str(entry.get("home_team_id"))
    if (r_away, r_home) != (e_away, e_home):
        code = (REASON_SCHEDULE_TEAMS_REVERSED if (r_away, r_home) == (e_home, e_away)
                else REASON_SCHEDULE_TEAMS_DISAGREE)
        conflicts.append({"code": code, "record": "%s@%s" % (r_away, r_home),
                          "schedule": "%s@%s" % (e_away, e_home)})
    r_date, e_date = scheduled_date_of(record), scheduled_date_of(entry)
    if r_date != e_date:
        conflicts.append({"code": REASON_SCHEDULE_DATE_DISAGREE, "record": r_date,
                          "schedule": e_date})
    r_start, e_start = _utc(record.get("scheduled_start_utc")), _utc(entry.get("scheduled_start_utc"))
    if r_start is not None and e_start is not None and r_start != e_start:
        conflicts.append({"code": REASON_SCHEDULE_START_DISAGREE, "record": _iso(r_start),
                          "schedule": _iso(e_start)})
    # The MIA@WSH shape of 8/30: the canonical schedule says the game is underway and a low-trust
    # record claims it is over. Scoped to the SEARCH lane on purpose — a CANONICAL record is a
    # LATER observation from the same provider and legitimately supersedes the slate snapshot,
    # so applying this to canonical would false-reject every genuine final of the night.
    if lane == LANE_SEARCH and entry.get("status") in LIVE_UNDERWAY_STATES \
            and record.get("status") in TERMINAL_STATES:
        conflicts.append({"code": REASON_CANONICAL_STATUS_CONTRADICTS_CLAIM,
                          "record": record.get("status"), "schedule": entry.get("status")})
    return conflicts


# ---------------------------------------------------------------------------------------------
# 8. CONSENSUS.  Counted by code, never typed by hand.
# ---------------------------------------------------------------------------------------------

CONSENSUS_MIN_SOURCES = 2

#: All three must agree, not just the score. An outlet that agrees on 9-2 but places the result an
#: hour earlier is describing a different game or a different moment.
CONSENSUS_FIELDS = ("away_score", "home_score", "status", "result_timestamp_utc")


def _independence_key(record):
    """Two outlets sharing one wire feed are ONE source. The wire is the identity, if declared."""
    return record.get("wire_service") or record.get("source")


def corroboration_count(record, others):
    """How many INDEPENDENT sources agree with `record` on every CONSENSUS_FIELD.

    Counts `record` itself as one. Deduplicated by wire service, so five outlets running one wire
    count once — which is the whole reason search consensus can never mint a final.
    """
    def sig(r):
        return tuple((r.get(f) if f != "result_timestamp_utc" else _iso(r.get(f)))
                     for f in CONSENSUS_FIELDS)
    target = sig(record)
    keys = {_independence_key(record)}
    for other in others or []:
        if other is record:
            continue
        if other.get("event_id") != record.get("event_id"):
            continue
        if sig(other) == target:
            keys.add(_independence_key(other))
    return len({k for k in keys if k})


# ---------------------------------------------------------------------------------------------
# 9. THE VERDICT.
# ---------------------------------------------------------------------------------------------

class Verdict:
    """What admit() returns. Four fields, always all four.

    reason_codes is a LIST and is never empty, including on the admit paths: a verdict that says
    only "yes" cannot be audited later, and the 8/27 review had nothing to audit.

    NOT a dataclass, deliberately. With `from __future__ import annotations` a dataclass resolves
    its own annotations through sys.modules[cls.__module__], which does not exist when this file
    is exec'd into a throwaway namespace — which is exactly what mutation_suite() does. The first
    run of that suite reported 12/12 KILLED while every mutant was dying of an AttributeError at
    import, i.e. the suite proved nothing at all. A plain class removes the failure mode.
    """

    __slots__ = ("disposition", "reason_codes", "admissible_as", "detail")

    def __init__(self, disposition, reason_codes, admissible_as=None, detail=None):
        seen, ordered = set(), []
        for c in (reason_codes or []):
            if c not in seen:
                seen.add(c)
                ordered.append(c)
        self.disposition = disposition
        self.reason_codes = ordered
        self.admissible_as = admissible_as
        self.detail = dict(detail or {})

    def __repr__(self):
        return "Verdict(%s, %s, admissible_as=%r)" % (self.disposition, self.reason_codes,
                                                      self.admissible_as)

    def __eq__(self, other):
        if not isinstance(other, Verdict):
            return NotImplemented
        return (self.disposition, self.reason_codes, self.admissible_as, self.detail) == \
               (other.disposition, other.reason_codes, other.admissible_as, other.detail)

    @property
    def admitted(self):
        """The score may reach an analysis layer at all."""
        return self.disposition in ADMITTING_DISPOSITIONS

    @property
    def settleable(self):
        """A wager may be settled on it: a validated terminal status and nothing less."""
        return self.disposition == ADMIT_FINAL and self.admissible_as == ADMISSIBLE_FINAL

    @property
    def terminal_verified(self):
        return bool(self.detail.get("terminal_verified", False))

    def to_dict(self):
        return {"schema": "ops.score_admission.verdict.v1",
                "disposition": self.disposition,
                "reason_codes": list(self.reason_codes),
                "admissible_as": self.admissible_as,
                "admitted": self.admitted,
                "settleable": self.settleable,
                "detail": dict(self.detail)}


def _search_lane_may_not_mint_final(lane):
    """SEARCH never mints FINAL. Not with two sources, not with ten. Search snippets IDENTIFY."""
    return lane == LANE_SEARCH


def _search_terminal_verdict(corroborations, reasons, detail):
    """The ceiling for a search-lane terminal claim: corroborated identification, never a final."""
    reasons = list(reasons) + [REASON_SEARCH_LANE_CANNOT_MINT_FINAL]
    if corroborations >= CONSENSUS_MIN_SOURCES:
        reasons.append(REASON_SEARCH_CORROBORATED)
        return Verdict(UNVERIFIED, reasons, ADMISSIBLE_CORROBORATED, detail)
    reasons.append(REASON_NO_CONSENSUS_SINGLE_SOURCE)
    return Verdict(NO_CONSENSUS, reasons, None, detail)


def admit(record, *, now_utc, canonical_schedule=None, lane, corroborations=0):
    """THE admission gate. All eight owner rules plus the lead's split clock rule.

    record             a normalized record (see RECORD_FIELDS)
    now_utc            the instant the judgement is made; str or datetime
    canonical_schedule dict keyed by event_id, a sequence of entries, or None
    lane               one of LANES; keyword-only and REQUIRED, because a caller that forgets to
                       say where the data came from is the 8/27 defect in miniature
    corroborations     independent-source count from corroboration_count(); search lane only

    Returns a Verdict. Never a bool, never a bare string.
    """
    now = _utc(now_utc)
    detail = {"lane": lane, "now_utc": _iso(now), "corroborations": int(corroborations or 0),
              "event_id": record.get("event_id") if isinstance(record, dict) else None,
              "schedule_supplied": canonical_schedule is not None}

    # ---- rule: lanes ---------------------------------------------------------------------
    if lane not in LANES:
        return Verdict(REJECT_LANE_FORBIDDEN, [REASON_LANE_UNKNOWN], None,
                       dict(detail, known_lanes=list(LANES)))
    if lane == LANE_MARKET:
        # Prices are never predictive features and never results; the market lane writes price
        # rows and nothing else (LANE_WRITE_TARGETS).
        return Verdict(REJECT_LANE_FORBIDDEN, [REASON_MARKET_LANE_NOT_A_SCORE_SOURCE], None,
                       dict(detail, permitted_sinks=sorted(LANE_WRITE_TARGETS[LANE_MARKET])))
    if not isinstance(record, dict):
        return Verdict(UNVERIFIED, [REASON_RECORD_NOT_A_MAPPING], None, detail)
    if now is None:
        return Verdict(UNVERIFIED, [REASON_UNPARSEABLE_TIMESTAMP], None,
                       dict(detail, field="now_utc", value=str(now_utc)))

    # ---- owner rules 1 and 5: bind by provider event id, never by names ------------------
    ok_id, id_problems = validate_event_id(record.get("event_id"))
    if not ok_id:
        return Verdict(REJECT_PRESTART_OR_UNBOUND, [p["code"] for p in id_problems], None,
                       dict(detail, record_problems=id_problems))

    # ---- owner rules 2 and 6: agree with the canonical schedule --------------------------
    entry = None
    idx = index_schedule(canonical_schedule)
    if idx is not None:
        entry = idx.get(record["event_id"])
        if entry is None:
            siblings = schedule_entries_for_matchup(
                idx, record.get("league"), record.get("away_team_id"), record.get("home_team_id"))
            reasons = [REASON_EVENT_NOT_IN_SCHEDULE]
            if len(siblings) > 1:
                reasons.append(REASON_MATCHUP_AMBIGUOUS_USE_EVENT_ID)
            return Verdict(REJECT_PRESTART_OR_UNBOUND, reasons, None,
                           dict(detail, matchup_siblings=siblings,
                                n_schedule_events=len(idx)))
        successor = entry.get("rescheduled_to_event_id")
        if successor and successor != record["event_id"]:
            return Verdict(REJECT_SCHEDULE_CONFLICT,
                           [REASON_POSTPONED_REBIND_REQUIRED, REASON_GAME_POSTPONED], None,
                           dict(detail, rebind_to=successor))
        conflicts = _schedule_conflicts(record, entry, lane)
        if conflicts:
            return Verdict(REJECT_SCHEDULE_CONFLICT, [c["code"] for c in conflicts], None,
                           dict(detail, conflicts=conflicts))

    # ---- the lead's split clock rule, part (a): PRE-START IS HARD ------------------------
    # The canonical schedule's start wins when there is one, so a record cannot evade this by
    # claiming an earlier first pitch. Nothing below can overturn it; nothing above it admits.
    start_utc = (_utc((entry or {}).get("scheduled_start_utc"))
                 or _utc(record.get("scheduled_start_utc")))
    claims_score = record.get("away_score") is not None or record.get("home_score") is not None
    claims_terminal = record.get("status") in TERMINAL_STATES
    detail["scheduled_start_utc"] = _iso(start_utc)
    if start_utc is not None and now < start_utc and (claims_score or claims_terminal):
        return Verdict(REJECT_PRESTART_OR_UNBOUND,
                       [REASON_PRESTART_FINAL_IMPOSSIBLE], None,
                       dict(detail, claims_score=claims_score, claims_terminal=claims_terminal,
                            minutes_before_start=round((start_utc - now).total_seconds() / 60.0, 1),
                            rule="now < scheduled_start: a final is impossible. No provider "
                                 "status overrides this (8/30 BOS@NYY, COL@ATL)"))

    # ---- owner rules 3 and 7: a source status field, and a retained content hash ----------
    ok_rec, problems = validate_record(record)
    if not ok_rec:
        codes = [p["code"] for p in problems]
        return Verdict(UNVERIFIED, codes, None, dict(detail, record_problems=problems))

    status = record["status"]
    detail["status"] = status
    detail["terminal_verified"] = terminal_verified_for(status)
    base = [] if idx is not None else [REASON_SCHEDULE_NOT_SUPPLIED]

    # ---- owner rules 4 and 8: only a terminal status may carry a final --------------------
    if status not in TERMINAL_STATES:
        if status == IN_PROGRESS:
            if lane == LANE_SEARCH:
                return Verdict(UNVERIFIED,
                               base + [REASON_GAME_IN_PROGRESS,
                                       REASON_SEARCH_LANE_CANNOT_MINT_FINAL],
                               ADMISSIBLE_IDENTIFIED_UNCONFIRMED, detail)
            return Verdict(ADMIT_IN_PROGRESS,
                           base + [REASON_GAME_IN_PROGRESS, REASON_STATUS_NOT_TERMINAL],
                           ADMISSIBLE_IN_PROGRESS, detail)
        reasons = base + [REASON_STATUS_NOT_TERMINAL]
        if status == UNKNOWN:
            reasons.append(REASON_STATUS_UNKNOWN)
        elif status == POSTPONED:
            reasons.append(REASON_GAME_POSTPONED)
        elif status == SUSPENDED:
            reasons.append(REASON_GAME_SUSPENDED)
        if claims_score:
            reasons.append(REASON_SCORE_WITHOUT_TERMINAL_STATUS)
        return Verdict(UNVERIFIED, reasons, None, detail)

    # ---- the lead's split clock rule, part (b): MINIMUM DURATION IS SOFT ------------------
    earliest = earliest_possible_final(start_utc, record["league"]) if start_utc else None
    detail["earliest_possible_final"] = _iso(earliest)
    too_soon = earliest is not None and now < earliest
    cleared = too_soon and lane == LANE_CANONICAL and status in TERMINAL_STATES
    reasons = list(base)
    if too_soon:
        reasons.append(REASON_MIN_DURATION_NOT_ELAPSED)
    if too_soon and not cleared:
        if lane == LANE_SEARCH:
            reasons.append(REASON_SEARCH_CANNOT_CLEAR_MIN_DURATION)
            reasons.append(REASON_SEARCH_LANE_CANNOT_MINT_FINAL)
        return Verdict(UNVERIFIED_TOO_SOON, reasons, None, detail)
    if cleared:
        # A rain-shortened or called game is legitimately short. The canonical provider saying
        # the game is over is the evidence that survives the clock; a snippet is not.
        reasons.append(REASON_MIN_DURATION_CLEARED)

    if _search_lane_may_not_mint_final(lane):
        return _search_terminal_verdict(corroborations, reasons, detail)

    if not claims_score:
        return Verdict(UNVERIFIED, reasons + [REASON_TERMINAL_WITHOUT_SCORES], None, detail)

    if status in VALIDATED_STATES:
        return Verdict(ADMIT_FINAL, reasons + [REASON_STATUS_VALIDATED], ADMISSIBLE_FINAL,
                       dict(detail, terminal_verified=True))
    # COMPLETE: over, but the statistics are not validated. Readable, not settleable.
    return Verdict(ADMIT_FINAL, reasons + [REASON_STATUS_TERMINAL_NOT_VALIDATED],
                   ADMISSIBLE_FINAL_UNVALIDATED, dict(detail, terminal_verified=False))


def sink_for(verdict):
    """Where this verdict's record may be written. Never guesses: anything else -> quarantine.

    The lane is read from the verdict's own detail, so a caller cannot route a search verdict to
    the board by passing a different lane at write time than it passed at admit time.
    """
    lane = verdict.detail.get("lane")
    if lane == LANE_CANONICAL and verdict.admitted:
        # Only a VALIDATED final reaches the result ledger. An unvalidated final and a live
        # snapshot are board-readable and nothing more; a wager settles on neither.
        sink = SINK_RESULT_LEDGER if verdict.settleable else SINK_BOARD
        return sink if may_write(LANE_CANONICAL, sink) else SINK_QUARANTINE
    if lane == LANE_MARKET and may_write(LANE_MARKET, SINK_PRICE_ROWS):
        return SINK_PRICE_ROWS
    return SINK_QUARANTINE


def lane_down(league, lane, *, reason="EGRESS_BLOCKED", blocked_sources=(), date_et=None,
              detail=None):
    """The explicit NO_DATA a down lane must produce.

    An empty result set and a down feed look identical from the outside, and on 2026-08-30 that
    ambiguity is what invited a search backfill. This makes the absence say so, and states in the
    artifact itself that backfilling from search is not licensed by it.
    """
    d = {"league": normalize_league(league) or league, "lane": lane, "reason": reason,
         "blocked_sources": list(blocked_sources), "date_et": date_et,
         "search_backfill_permitted": False,
         "rule": "a down canonical lane yields NO_DATA_LANE_DOWN, never a search backfill and "
                 "never a silent empty slate"}
    d.update(detail or {})
    return Verdict(NO_DATA_LANE_DOWN, [REASON_LANE_DOWN], None, d)


# ---------------------------------------------------------------------------------------------
# 10. BOARD-SIDE VOCABULARY.  Defined here, enforced elsewhere.
#
# The pre-publication board invariants live in the board module, NOT in this file. These constants
# are here only because three modules were built in parallel against this contract and a retyped
# literal is how a vocabulary forks. The 2026-08-30 MIN@ATL row
# (cards/2026-08-30_pregame_board_v6_canonical.json) must come out as
#   {"decision": "PASS", "reason_codes": ["MISSING_MARKET_PRICE", "AVAILABILITY_UNKNOWN",
#                                         "MODEL_CONVERGENCE_FAIL"]}
# It currently comes out LEAN on a 14.3pp edge computed against an ASSUMED 50.0 no-vig, because
# entry.price_american was never captured.
# ---------------------------------------------------------------------------------------------

DECISION_PASS = "PASS"
DECISION_LEAN = "LEAN"
DECISION_PASS_DATA_QUALITY = "PASS_DATA_QUALITY"
DECISION_CONVERGENCE_FAIL = "CONVERGENCE_FAIL"

BOARD_REASON_MISSING_MARKET_PRICE = "MISSING_MARKET_PRICE"
BOARD_REASON_AVAILABILITY_UNKNOWN = "AVAILABILITY_UNKNOWN"
BOARD_REASON_MODEL_CONVERGENCE_FAIL = "MODEL_CONVERGENCE_FAIL"
BOARD_REASON_ASSUMED_NO_VIG = "MARKET_NO_VIG_ASSUMED_NOT_CAPTURED"

AVAILABILITY_UNKNOWN = "UNKNOWN"

#: The exact row the board module must produce for MIN@ATL. Kept as data so the two modules test
#: against one object rather than two copies of a list of strings.
MIN_ATL_REQUIRED_ROW = {
    "decision": DECISION_PASS,
    "reason_codes": [BOARD_REASON_MISSING_MARKET_PRICE,
                     BOARD_REASON_AVAILABILITY_UNKNOWN,
                     BOARD_REASON_MODEL_CONVERGENCE_FAIL],
}


# ---------------------------------------------------------------------------------------------
# 11. FIXTURES.  Every id declares its provenance, the way result_binding_gate.PK_PROVENANCE does:
#     a gate fixture carrying an undeclared number is a contamination vector itself.
# ---------------------------------------------------------------------------------------------

EID_OWNER = "mlb:2026:824643"
EID_BOSNYY = "mlb:2026:SYNTHETIC-UNVERIFIED-BOSNYY-0830"
EID_COLATL = "mlb:2026:SYNTHETIC-UNVERIFIED-COLATL-0830"
EID_MIAWSH = "mlb:2026:SYNTHETIC-UNVERIFIED-MIAWSH-0830"
EID_MIAWSH_PRIOR = "mlb:2026:SYNTHETIC-UNVERIFIED-MIAWSH-0829"
EID_DH_G1 = "mlb:2026:SYNTHETIC-UNVERIFIED-KCTOR-G1"
EID_DH_G2 = "mlb:2026:SYNTHETIC-UNVERIFIED-KCTOR-G2"
EID_PPD_OLD = "mlb:2026:SYNTHETIC-UNVERIFIED-PITCLE-PPD"
EID_PPD_NEW = "mlb:2026:SYNTHETIC-UNVERIFIED-PITCLE-MAKEUP"
EID_WNBA = "wnba:2026:SYNTHETIC-UNVERIFIED-MINATL-0830"

FIXTURE_PROVENANCE = {
    EID_OWNER: "CAPTURED — the owner's own normalized-record example in the 2026-08-30 directive, "
               "reproduced verbatim so the shape this module accepts is the shape that was asked "
               "for.",
    EID_BOSNYY: "SYNTHETIC_UNVERIFIED — BOS@NYY, 2026-08-30 13:35 ET. The search result claiming "
                "'Yankees 1, Red Sox 0' was refused before any id was captured. Inventing a "
                "plausible gamePk here would be the exact defect this module exists to stop (R1).",
    EID_COLATL: "SYNTHETIC_UNVERIFIED — COL@ATL, 2026-08-30 13:35 ET, 'Braves 6, Rockies 4'. "
                "Same refusal, same absence of a captured id.",
    EID_MIAWSH: "SYNTHETIC_UNVERIFIED — MIA@WSH, 2026-08-30 12:15 ET, 'Nationals 9, Marlins 2' "
                "asserted 75 minutes into a game needing about 170.",
    EID_MIAWSH_PRIOR: "SYNTHETIC_UNVERIFIED — the SAME matchup on the prior day, which is the "
                      "8/27 PRIOR_DATE_SERIES_JOIN shape in event-id form.",
    EID_DH_G1: "SYNTHETIC_UNVERIFIED — doubleheader half 1. The repo holds no doubleheader "
               "payload at all (every observed gameNumber is 1), so this half is constructed.",
    EID_DH_G2: "SYNTHETIC_UNVERIFIED — doubleheader half 2, the half team names cannot select.",
    EID_PPD_OLD: "SYNTHETIC_UNVERIFIED — a postponed game. Modelled on the one real postponement "
                 "this repo evidences (PIT@CLE 2026-07-17, statusCode DD, reason 'Air Quality', "
                 "data/mlb/schedule/2026-07-17_espn_verify.json). NOTE what that evidence shows: "
                 "StatsAPI RETAINED gamePk 824414 for the makeup and moved gameDate, so the "
                 "same-id case is exercised too, by start/date disagreement.",
    EID_PPD_NEW: "SYNTHETIC_UNVERIFIED — the successor event id a provider that does reissue ids "
                 "would emit; the schedule entry's rescheduled_to_event_id points here.",
    EID_WNBA: "SYNTHETIC_UNVERIFIED — MIN@ATL 2026-08-30, the game whose board row carries the "
              "convergence defect. Used here only to prove the league table is not MLB-only.",
}

_NOW_1330ET = "2026-08-30T17:30:00Z"   # the instant of the 8/30 incident, 13:30 ET
_START_1335ET = "2026-08-30T17:35:00Z"  # BOS@NYY and COL@ATL first pitch
_START_1215ET = "2026-08-30T16:15:00Z"  # MIA@WSH first pitch
_EVENING = "2026-08-30T23:00:00Z"       # 19:00 ET, past every window used below


def _rec(event_id, league, away, home, start, status, away_score=None, home_score=None,
         source=PROVIDER_MLB_STATSAPI, fetched=_NOW_1330ET, **extra):
    """Build a normalized record. terminal_verified and the content hash are GENERATED here."""
    r = {"event_id": event_id, "league": league, "away_team_id": away, "home_team_id": home,
         "scheduled_start_utc": start, "status": status,
         "away_score": away_score, "home_score": home_score,
         "terminal_verified": terminal_verified_for(status),
         "source": source, "source_fetched_at_utc": fetched,
         "raw_response_sha256": hashlib.sha256(
             ("%s|%s|%s|%s|%s" % (event_id, start, status, away_score, home_score)
              ).encode()).hexdigest()}
    r.update(extra)
    return r


def _entry(event_id, away, home, start, league="MLB", **extra):
    e = {"event_id": event_id, "league": league, "away_team_id": away, "home_team_id": home,
         "scheduled_start_utc": start}
    e.update(extra)
    return e


def incident_schedule_0830():
    """The canonical slate as it stood at 2026-08-30 13:30 ET, when the three finals arrived."""
    return index_schedule([
        _entry(EID_BOSNYY, "SYNTH_BOS", "SYNTH_NYY", _START_1335ET, status=SCHEDULED),
        _entry(EID_COLATL, "SYNTH_COL", "SYNTH_ATL", _START_1335ET, status=SCHEDULED),
        _entry(EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, status=IN_PROGRESS),
    ])


def selftest():
    """Every fixture below is one of the ten regression cases the owner named, or a vocabulary
    invariant another module depends on. Fixture names are the incident, not a test number."""
    f = []
    verdicts = []
    seen_codes = set()

    def A(**kw):
        v = admit(**kw)
        verdicts.append(v)
        seen_codes.update(v.reason_codes)
        return v

    # ---- S0. VOCABULARY INTEGRITY ---------------------------------------------------------
    if MODULE_ID != os.path.basename(__file__)[:-3]:
        f.append("S0: MODULE_ID %r does not name this file" % MODULE_ID)
    if set(LANE_WRITE_TARGETS) != set(LANES):
        f.append("S0: LANE_WRITE_TARGETS is not total over LANES")
    if LANE_WRITE_TARGETS[LANE_SEARCH] != frozenset({SINK_QUARANTINE}):
        f.append("S0: the SEARCH lane may write somewhere other than quarantine — that is the "
                 "8/27 publication path, reopened")
    if may_write(LANE_SEARCH, SINK_BOARD) or may_write(LANE_MARKET, SINK_BOARD):
        f.append("S0: a low/medium-trust lane may write to the board")
    if not may_write(LANE_CANONICAL, SINK_BOARD):
        f.append("S0: the canonical lane cannot write to the board, which leaves no lane that can")
    try:
        assert_write_allowed(LANE_SEARCH, SINK_BOARD)
        f.append("S0: assert_write_allowed permitted SEARCH -> board")
    except LaneViolation as e:
        if REASON_LANE_FORBIDDEN_SINK not in str(e):
            f.append("S0: the lane refusal does not name its own reason code")
        seen_codes.add(REASON_LANE_FORBIDDEN_SINK)
    try:
        assert_tool_allowed("write_result_ledger")
        f.append("S0: assert_tool_allowed permitted a tool outside ANALYSIS_TOOL_SURFACE")
    except LaneViolation:
        pass
    if TERMINAL_STATES | NON_FINAL_STATES != set(STATUSES) or (TERMINAL_STATES & NON_FINAL_STATES):
        f.append("S0: TERMINAL_STATES and NON_FINAL_STATES do not partition STATUSES")
    if not VALIDATED_STATES <= TERMINAL_STATES:
        f.append("S0: a validated state that is not terminal")
    if COMPLETE not in TERMINAL_STATES or COMPLETE in VALIDATED_STATES:
        f.append("S0: COMPLETE must be terminal and NOT validated (complete != closed)")
    if CLOSED not in VALIDATED_STATES or CLOSED not in TERMINAL_STATES:
        f.append("S0: CLOSED must be both terminal and validated")
    if terminal_verified_for(COMPLETE) or not terminal_verified_for(CLOSED):
        f.append("S0: terminal_verified does not track VALIDATED_STATES")
    if (MLB_STATUSCODE_TO_STATUS.get("F"), MLB_STATUSCODE_TO_STATUS.get("O"),
            MLB_STATUSCODE_TO_STATUS.get("DD"), MLB_STATUSCODE_TO_STATUS.get("S")) != \
            (CLOSED, COMPLETE, POSTPONED, SCHEDULED):
        f.append("S0: the MLB statusCode map drifted from what the repo evidences")
    if normalize_status("I", PROVIDER_MLB_STATSAPI) != UNKNOWN:
        f.append("S0: an unevidenced statusCode mapped to something other than UNKNOWN (R1)")
    if normalize_status("STATUS_FINAL", PROVIDER_ESPN_SCOREBOARD) != COMPLETE:
        f.append("S0: an ESPN final must be COMPLETE, never CLOSED — the scoreboard API exposes "
                 "no validation state anywhere in this repo")
    if normalize_status(None, PROVIDER_MLB_STATSAPI) != UNKNOWN:
        f.append("S0: a missing status did not map to UNKNOWN")
    expected_minutes = {"MLB": 150, "NBA": 120, "WNBA": 120, "NFL": 165, "CFB": 180}
    if MIN_DURATION_MINUTES != expected_minutes:
        f.append("S0: MIN_DURATION_MINUTES drifted from the owner's table: %r"
                 % (MIN_DURATION_MINUTES,))
    if normalize_league("college-football") != "CFB" or normalize_league("mlb") != "MLB":
        f.append("S0: league normalisation lost the feed_espn 'college-football' alias")
    if normalize_league("KBO") is not None:
        f.append("S0: an unknown league normalised to something instead of None")
    if _iso(earliest_possible_final(_START_1335ET, "MLB")) != "2026-08-30T20:05:00Z":
        f.append("S0: earliest_possible_final is not start + 150 minutes for MLB")
    try:
        earliest_possible_final(_START_1335ET, "KBO")
        f.append("S0: earliest_possible_final invented a minimum for an unknown league")
    except ValueError:
        pass
    if set(DISPOSITION_MEANING) != set(DISPOSITIONS):
        f.append("S0: DISPOSITION_MEANING is not total over DISPOSITIONS")
    for d in DISPOSITIONS:
        if not isinstance(d, str) or not d.isupper():
            f.append("S0: disposition %r is not a bare upper-case string" % (d,))
    missing_meaning = sorted(v for k, v in sorted(globals().items())
                             if k.startswith("REASON_") and isinstance(v, str)
                             and v not in REASON_MEANING)
    if missing_meaning:
        f.append("S0: reason codes with no entry in REASON_MEANING: %s" % missing_meaning)
    if ADMISSIBLE_IDENTIFIED_UNCONFIRMED != fc.IDENTIFIED_UNCONFIRMED:
        f.append("S0: the identified-unconfirmed grade forked from freshness_contract")
    if ALLOW_DIRECT_HTTP is not False:
        f.append("S0: ALLOW_DIRECT_HTTP is not False")
    # The no-network claim, checked rather than asserted. Needles are built by concatenation so
    # this check cannot match itself.
    needles = ["requests" + ".get", "url" + "open", "http" + ".client", "socket" + ".socket",
               "urllib" + ".request"]
    own_source = open(__file__).read()
    hits = [n for n in needles if n in own_source]
    if hits:
        f.append("S0: this module claims no network I/O but its source contains %s" % hits)
    bad_prov = [e for e, p in FIXTURE_PROVENANCE.items()
                if not p.startswith(("CAPTURED", "ARCHIVE_VERIFIED", "SYNTHETIC_UNVERIFIED"))]
    if bad_prov:
        f.append("S0: fixture ids with undeclared provenance: %s" % bad_prov)
    declared_ids = {v for k, v in globals().items() if k.startswith("EID_")}
    if declared_ids != set(FIXTURE_PROVENANCE):
        f.append("S0: fixture event ids without a provenance entry: %s"
                 % sorted(declared_ids ^ set(FIXTURE_PROVENANCE)))
    for eid in FIXTURE_PROVENANCE:
        try:
            parse_event_id(eid)
        except ValueError as e:
            f.append("S0: fixture id %r does not satisfy this module's own id shape (%s)" % (eid, e))

    # ---- S1. THE NORMALIZED RECORD --------------------------------------------------------
    owner_example = {"event_id": EID_OWNER, "league": "MLB", "away_team_id": 138,
                     "home_team_id": 112, "scheduled_start_utc": "2026-08-30T17:35:00Z",
                     "status": IN_PROGRESS, "away_score": 2, "home_score": 1,
                     "terminal_verified": False, "source": "mlb_statsapi",
                     "source_fetched_at_utc": "2026-08-30T18:45:00Z",
                     "raw_response_sha256": hashlib.sha256(b"owner-example").hexdigest()}
    ok, problems = validate_record(owner_example)
    if not ok:
        f.append("S1: the owner's own example record was refused: %s"
                 % [p["code"] for p in problems])
    good = _rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9)
    ok, problems = validate_record(good)
    if not ok:
        f.append("S1: a clean record was refused: %s" % [p["code"] for p in problems])

    def refuses(label, mutate, code):
        r = _rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9)
        mutate(r)
        ok2, probs = validate_record(r)
        codes = [p["code"] for p in probs]
        seen_codes.update(codes)
        if ok2 or code not in codes:
            f.append("S1 %s: expected %s, got %s" % (label, code, codes or "ACCEPTED"))

    refuses("status absent (owner rule 3)", lambda r: r.__setitem__("status", None),
            REASON_STATUS_MISSING)
    refuses("score as a string (ESPN returns strings)",
            lambda r: r.__setitem__("away_score", "2"), REASON_NON_NUMERIC_SCORE)
    refuses("score as a bool", lambda r: r.__setitem__("home_score", True),
            REASON_NON_NUMERIC_SCORE)
    refuses("one-sided score", lambda r: r.__setitem__("home_score", None), REASON_PARTIAL_SCORE)
    refuses("bare provider id", lambda r: r.__setitem__("event_id", "824643"),
            REASON_EVENT_ID_MALFORMED)
    refuses("two-part namespaced id from the other id space",
            lambda r: r.__setitem__("event_id", "MLB_GAMEPK:824643"), REASON_EVENT_ID_MALFORMED)
    refuses("short season", lambda r: r.__setitem__("event_id", "mlb:26:824643"),
            REASON_EVENT_ID_MALFORMED)
    refuses("placeholder provider id", lambda r: r.__setitem__("event_id", "mlb:2026:TBD"),
            REASON_EVENT_ID_PLACEHOLDER)
    refuses("DH placeholder (the 2026-08-17 cards' 'DH1' gamePk)",
            lambda r: r.__setitem__("event_id", "mlb:2026:DH1"), REASON_EVENT_ID_PLACEHOLDER)
    refuses("content hash absent", lambda r: r.__setitem__("raw_response_sha256", None),
            REASON_MISSING_REQUIRED_FIELD)
    refuses("content hash not a sha256",
            lambda r: r.__setitem__("raw_response_sha256", "deadbeef"), REASON_BAD_CONTENT_HASH)
    refuses("terminal_verified typed rather than generated",
            lambda r: r.update({"status": COMPLETE, "terminal_verified": True}),
            REASON_TERMINAL_VERIFIED_INCONSISTENT)
    refuses("same team both sides", lambda r: r.__setitem__("home_team_id", "SYNTH_MIA"),
            REASON_SAME_TEAM_BOTH_SIDES)
    refuses("league with no minimum duration", lambda r: r.__setitem__("league", "KBO"),
            REASON_UNSUPPORTED_LEAGUE)
    refuses("status outside the vocabulary",
            lambda r: r.update({"status": "Final", "terminal_verified": False}),
            REASON_STATUS_NOT_IN_VOCABULARY)
    refuses("unparseable start", lambda r: r.__setitem__("scheduled_start_utc", "yesterday"),
            REASON_UNPARSEABLE_TIMESTAMP)

    sched = incident_schedule_0830()

    # ---- FIXTURE 1. A FUTURE GAME WITH A CONFIDENT, INCORRECT SEARCH FINAL ------------------
    # 2026-08-30 13:30 ET. "Yankees 1, Red Sox 0" and "Braves 6, Rockies 4", five minutes before
    # first pitch. This is the hard pre-start invariant and nothing may overturn it.
    for eid, away, home, a_s, h_s, label in (
            (EID_BOSNYY, "SYNTH_BOS", "SYNTH_NYY", 0, 1, "BOS@NYY 1-0"),
            (EID_COLATL, "SYNTH_COL", "SYNTH_ATL", 4, 6, "COL@ATL 6-4")):
        v = A(record=_rec(eid, "MLB", away, home, _START_1335ET, CLOSED, a_s, h_s,
                          source="web_search"),
              now_utc=_NOW_1330ET, canonical_schedule=sched, lane=LANE_SEARCH)
        if v.disposition != REJECT_PRESTART_OR_UNBOUND or \
                REASON_PRESTART_FINAL_IMPOSSIBLE not in v.reason_codes:
            f.append("F1 %s: a final five minutes BEFORE first pitch produced %s %s"
                     % (label, v.disposition, v.reason_codes))
    # ...and the same claim wearing a canonical badge is refused identically. A provider asserting
    # a final before first pitch is a provider bug or a mis-bound game; both must refuse.
    v = A(record=_rec(EID_BOSNYY, "MLB", "SYNTH_BOS", "SYNTH_NYY", _START_1335ET, CLOSED, 0, 1),
          now_utc=_NOW_1330ET, canonical_schedule=sched, lane=LANE_CANONICAL)
    if v.disposition != REJECT_PRESTART_OR_UNBOUND:
        f.append("F1 canonical: a CANONICAL terminal status overrode the pre-start invariant "
                 "(%s) — the one rule that has no exception" % v.disposition)
    # with no schedule at all, the record's own start still refuses it
    v = A(record=_rec(EID_COLATL, "MLB", "SYNTH_COL", "SYNTH_ATL", _START_1335ET, COMPLETE, 4, 6),
          now_utc=_NOW_1330ET, lane=LANE_CANONICAL)
    if v.disposition != REJECT_PRESTART_OR_UNBOUND:
        f.append("F1 unbound: pre-start stopped being checked when no schedule was supplied (%s)"
                 % v.disposition)

    # ---- FIXTURE 2. A LIVE GAME LABELLED FINAL ---------------------------------------------
    # MIA@WSH, 75 minutes into a game that needs about 170. "Nationals 9, Marlins 2".
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9,
                      source="web_search"),
          now_utc=_NOW_1330ET, canonical_schedule=sched, lane=LANE_SEARCH)
    if v.disposition != REJECT_SCHEDULE_CONFLICT or \
            REASON_CANONICAL_STATUS_CONTRADICTS_CLAIM not in v.reason_codes:
        f.append("F2 MIA@WSH: a search final against an IN_PROGRESS canonical status produced "
                 "%s %s" % (v.disposition, v.reason_codes))
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9,
                      source="web_search"),
          now_utc=_NOW_1330ET, lane=LANE_SEARCH)
    if v.disposition != UNVERIFIED_TOO_SOON or \
            REASON_SEARCH_CANNOT_CLEAR_MIN_DURATION not in v.reason_codes:
        f.append("F2 MIA@WSH unbound: 75 minutes into a 150-minute minimum produced %s %s"
                 % (v.disposition, v.reason_codes))
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, IN_PROGRESS,
                      2, 1),
          now_utc=_NOW_1330ET, canonical_schedule=sched, lane=LANE_CANONICAL)
    if v.disposition != ADMIT_IN_PROGRESS or v.admissible_as != ADMISSIBLE_IN_PROGRESS \
            or v.settleable:
        f.append("F2 live snapshot: a canonical in-progress record produced %s/%s (settleable=%s)"
                 % (v.disposition, v.admissible_as, v.settleable))

    # ---- FIXTURE 3. YESTERDAY'S GAME OF THE SAME MATCHUP -----------------------------------
    # The 8/27 contamination in event-id form: same teams, wrong day.
    v = A(record=_rec(EID_MIAWSH_PRIOR, "MLB", "SYNTH_MIA", "SYNTH_WSH",
                      "2026-08-29T16:15:00Z", CLOSED, 3, 4),
          now_utc=_EVENING, canonical_schedule=sched, lane=LANE_CANONICAL)
    if v.disposition != REJECT_PRESTART_OR_UNBOUND or \
            REASON_EVENT_NOT_IN_SCHEDULE not in v.reason_codes:
        f.append("F3 prior-day: yesterday's event id bound anyway (%s %s)"
                 % (v.disposition, v.reason_codes))
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH",
                      "2026-08-29T16:15:00Z", CLOSED, 3, 4),
          now_utc=_EVENING, canonical_schedule=sched, lane=LANE_CANONICAL)
    if v.disposition != REJECT_SCHEDULE_CONFLICT or \
            REASON_SCHEDULE_DATE_DISAGREE not in v.reason_codes:
        f.append("F3 date drift: today's event id carrying yesterday's date produced %s %s"
                 % (v.disposition, v.reason_codes))

    # ---- FIXTURE 4. A DOUBLEHEADER, WHERE TEAM NAMES ARE AMBIGUOUS -------------------------
    dh = index_schedule([
        _entry(EID_DH_G1, "SYNTH_KC", "SYNTH_TOR", "2026-08-30T17:07:00Z", game_number=1),
        _entry(EID_DH_G2, "SYNTH_KC", "SYNTH_TOR", "2026-08-30T20:07:00Z", game_number=2),
    ])
    if schedule_entries_for_matchup(dh, "MLB", "SYNTH_KC", "SYNTH_TOR") != [EID_DH_G1, EID_DH_G2]:
        f.append("F4: the matchup did not resolve to TWO events — the fixture is not a "
                 "doubleheader and proves nothing")
    v = A(record=_rec(EID_DH_G2, "MLB", "SYNTH_KC", "SYNTH_TOR", "2026-08-30T20:07:00Z",
                      CLOSED, 13, 2),
          now_utc=_EVENING, canonical_schedule=dh, lane=LANE_CANONICAL)
    if v.disposition != ADMIT_FINAL:
        f.append("F4 G2: the correct half of a doubleheader was refused (%s %s)"
                 % (v.disposition, v.reason_codes))
    v = A(record=_rec(EID_DH_G2, "MLB", "SYNTH_KC", "SYNTH_TOR", "2026-08-30T17:07:00Z",
                      CLOSED, 13, 2),
          now_utc=_EVENING, canonical_schedule=dh, lane=LANE_CANONICAL)
    if v.disposition != REJECT_SCHEDULE_CONFLICT or \
            REASON_SCHEDULE_START_DISAGREE not in v.reason_codes:
        f.append("F4 crossed halves: G2's id carrying G1's start produced %s %s"
                 % (v.disposition, v.reason_codes))
    v = A(record=_rec(EID_PPD_OLD, "MLB", "SYNTH_KC", "SYNTH_TOR", "2026-08-30T20:07:00Z",
                      CLOSED, 13, 2),
          now_utc=_EVENING, canonical_schedule=dh, lane=LANE_CANONICAL)
    if REASON_MATCHUP_AMBIGUOUS_USE_EVENT_ID not in v.reason_codes:
        f.append("F4 ambiguity: an unbound record on a doubleheader matchup did not report that "
                 "names cannot choose between the halves (%s)" % v.reason_codes)

    # ---- FIXTURE 5. A POSTPONED GAME WITH AN OLD EVENT ID ----------------------------------
    ppd = index_schedule([
        _entry(EID_PPD_OLD, "SYNTH_PIT", "SYNTH_CLE", "2026-08-30T17:10:00Z", status=POSTPONED,
               rescheduled_to_event_id=EID_PPD_NEW),
    ])
    v = A(record=_rec(EID_PPD_OLD, "MLB", "SYNTH_PIT", "SYNTH_CLE", "2026-08-30T17:10:00Z",
                      CLOSED, 5, 4),
          now_utc=_EVENING, canonical_schedule=ppd, lane=LANE_CANONICAL)
    if v.disposition != REJECT_SCHEDULE_CONFLICT or \
            REASON_POSTPONED_REBIND_REQUIRED not in v.reason_codes or \
            v.detail.get("rebind_to") != EID_PPD_NEW:
        f.append("F5 rebind: a superseded event id was scored instead of rebound (%s %s %s)"
                 % (v.disposition, v.reason_codes, v.detail.get("rebind_to")))
    # The one real postponement this repo evidences RETAINED its gamePk (824414) and moved the
    # date. That shape must refuse too, via the date/start comparison rather than a successor id.
    ppd_same_id = index_schedule([
        _entry(EID_PPD_OLD, "SYNTH_PIT", "SYNTH_CLE", "2026-08-31T17:10:00Z", status=SCHEDULED),
    ])
    v = A(record=_rec(EID_PPD_OLD, "MLB", "SYNTH_PIT", "SYNTH_CLE", "2026-08-30T17:10:00Z",
                      CLOSED, 5, 4),
          now_utc=_EVENING, canonical_schedule=ppd_same_id, lane=LANE_CANONICAL)
    if v.disposition != REJECT_SCHEDULE_CONFLICT:
        f.append("F5 same-id makeup: a game that moved to the next day was scored on its old "
                 "date (%s %s)" % (v.disposition, v.reason_codes))
    v = A(record=_rec(EID_PPD_OLD, "MLB", "SYNTH_PIT", "SYNTH_CLE", "2026-08-30T17:10:00Z",
                      POSTPONED),
          now_utc=_EVENING, lane=LANE_CANONICAL)
    if v.disposition != UNVERIFIED or REASON_GAME_POSTPONED not in v.reason_codes:
        f.append("F5 status: a postponed record was not held as non-final (%s %s)"
                 % (v.disposition, v.reason_codes))

    # ---- A FINAL SCORE WITH NO STATUS FIELD IS UNVERIFIED, NOT FINAL (owner rule 3) ---------
    # The five published 8/27 finals came from prose. Prose has no status field, so there is
    # nothing that can be terminal, so nothing admits.
    no_status = _rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9)
    no_status["status"] = None
    no_status["terminal_verified"] = False
    v = A(record=no_status, now_utc=_EVENING, canonical_schedule=sched, lane=LANE_SEARCH)
    if v.disposition != UNVERIFIED or REASON_STATUS_MISSING not in v.reason_codes:
        f.append("RULE3: a score carrying no source status produced %s %s"
                 % (v.disposition, v.reason_codes))

    # ---- FIXTURE 6. COMPLETE BUT NOT CLOSED ------------------------------------------------
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, COMPLETE, 2, 9),
          now_utc=_EVENING, canonical_schedule=sched, lane=LANE_CANONICAL)
    if v.disposition != ADMIT_FINAL or v.admissible_as != ADMISSIBLE_FINAL_UNVALIDATED \
            or v.settleable or v.terminal_verified:
        f.append("F6 complete: an unvalidated 'complete' admitted as %s/%s (settleable=%s, "
                 "terminal_verified=%s) — only a validated state settles"
                 % (v.disposition, v.admissible_as, v.settleable, v.terminal_verified))
    if sink_for(v) != SINK_BOARD:
        f.append("F6 routing: an unvalidated final routed to %r; it is readable, not settled"
                 % sink_for(v))
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9),
          now_utc=_EVENING, canonical_schedule=sched, lane=LANE_CANONICAL)
    if v.disposition != ADMIT_FINAL or v.admissible_as != ADMISSIBLE_FINAL or not v.settleable \
            or not v.terminal_verified:
        f.append("F6 closed: a validated final did not settle (%s/%s)"
                 % (v.disposition, v.admissible_as))
    if sink_for(v) != SINK_RESULT_LEDGER:
        f.append("F6 routing: a validated final did not route to the result ledger (%r)"
                 % sink_for(v))
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED),
          now_utc=_EVENING, canonical_schedule=sched, lane=LANE_CANONICAL)
    if v.disposition != UNVERIFIED or REASON_TERMINAL_WITHOUT_SCORES not in v.reason_codes:
        f.append("F6 empty final: a terminal status with no scores admitted (%s)" % v.disposition)

    # ---- FIXTURE 7. A MUTABLE ARCHIVE UNDER ONE FILENAME ------------------------------------
    a = _rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9)
    b = _rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 3, 9)
    b["source_fetched_at_utc"] = a["source_fetched_at_utc"]
    conflict, prob = content_hash_conflict(a, b)
    seen_codes.add(prob["code"] if prob else None)
    if not conflict or prob["code"] != REASON_SNAPSHOT_CONTENT_CHANGED:
        f.append("F7 mutation: bytes changed under one snapshot key and nothing noticed")
    c = dict(b, raw_response_sha256=a["raw_response_sha256"])
    conflict, prob = content_hash_conflict(a, c)
    seen_codes.add(prob["code"] if prob else None)
    if not conflict or prob["code"] != REASON_SNAPSHOT_HASH_MATCHES_CONTENT_DIFFERS:
        f.append("F7 hash coverage: one hash covered two different score sets")
    later = _rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9,
                 fetched=_EVENING)
    conflict, _ = content_hash_conflict(a, later)
    if conflict:
        f.append("F7 false positive: two honest fetches at different instants were called a "
                 "mutation")

    # ---- THE SPLIT CLOCK, PART (b): A RAIN-SHORTENED GAME MUST SURVIVE ----------------------
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9),
          now_utc="2026-08-30T17:50:00Z", canonical_schedule=sched, lane=LANE_CANONICAL)
    if v.disposition != ADMIT_FINAL or REASON_MIN_DURATION_CLEARED not in v.reason_codes \
            or REASON_MIN_DURATION_NOT_ELAPSED not in v.reason_codes:
        f.append("CLOCK(b): a canonical terminal status 95 minutes in did not clear the SOFT "
                 "duration hold (%s %s) — this is the false-reject owner message 1 warned about"
                 % (v.disposition, v.reason_codes))

    # ---- SEARCH CONSENSUS: TWO OUTLETS ON ONE WIRE ARE ONE SOURCE ---------------------------
    s1 = _rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9,
              source="outlet_a", wire_service="wire_x", result_timestamp_utc=_EVENING)
    s2 = dict(s1, source="outlet_b")
    s3 = dict(s1, source="outlet_c", wire_service="wire_y")
    s4 = dict(s3, source="outlet_d", wire_service="wire_z", result_timestamp_utc=_NOW_1330ET)
    if corroboration_count(s1, [s2]) != 1:
        f.append("CONSENSUS: two outlets running one wire counted as two independent sources")
    if corroboration_count(s1, [s2, s3]) != 2:
        f.append("CONSENSUS: a genuinely independent second source was not counted")
    if corroboration_count(s1, [s4]) != 1:
        f.append("CONSENSUS: a source disagreeing on the RESULT TIMESTAMP was counted as agreeing")
    v = A(record=s1, now_utc=_EVENING, lane=LANE_SEARCH, corroborations=1)
    if v.disposition != NO_CONSENSUS:
        f.append("CONSENSUS: a single-source search final produced %s" % v.disposition)
    v = A(record=s1, now_utc=_EVENING, lane=LANE_SEARCH, corroborations=2)
    if v.disposition != UNVERIFIED or v.admissible_as != ADMISSIBLE_CORROBORATED:
        f.append("CONSENSUS: corroborated search produced %s/%s, not UNVERIFIED/%s"
                 % (v.disposition, v.admissible_as, ADMISSIBLE_CORROBORATED))
    for n in (2, 3, 99):
        v = A(record=s1, now_utc=_EVENING, lane=LANE_SEARCH, corroborations=n)
        if v.disposition == ADMIT_FINAL or v.admissible_as in (ADMISSIBLE_FINAL,
                                                               ADMISSIBLE_FINAL_UNVALIDATED):
            f.append("CONSENSUS: %d corroborations minted a FINAL from the SEARCH lane; two "
                     "outlets sharing a wire are not two witnesses" % n)

    # ---- LANES ------------------------------------------------------------------------------
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9),
          now_utc=_EVENING, canonical_schedule=sched, lane=LANE_MARKET)
    if v.disposition != REJECT_LANE_FORBIDDEN or \
            REASON_MARKET_LANE_NOT_A_SCORE_SOURCE not in v.reason_codes:
        f.append("LANE: the market lane produced a score (%s)" % v.disposition)
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9),
          now_utc=_EVENING, canonical_schedule=sched, lane="GUT_FEEL")
    if v.disposition != REJECT_LANE_FORBIDDEN or REASON_LANE_UNKNOWN not in v.reason_codes:
        f.append("LANE: an unknown lane was tolerated (%s)" % v.disposition)

    # ---- A DOWN LANE IS NO_DATA, NOT AN EMPTY SLATE -----------------------------------------
    v = lane_down("MLB", LANE_CANONICAL, reason="EGRESS_BLOCKED",
                  blocked_sources=["espn.com", "covers.com"], date_et="2026-08-30")
    verdicts.append(v)
    if v.disposition != NO_DATA_LANE_DOWN or v.admitted or \
            v.detail.get("search_backfill_permitted") is not False:
        f.append("LANE_DOWN: a blocked canonical lane did not produce an explicit NO_DATA that "
                 "refuses a search backfill")

    # ---- WNBA: the league table is not MLB-only, and 120 is not 150 -------------------------
    if _iso(earliest_possible_final("2026-08-30T23:00:00Z", "WNBA")) != "2026-08-31T01:00:00Z":
        f.append("WNBA: the 120-minute minimum is not being applied")
    # start + 130 minutes: past the WNBA window, inside an MLB one. A search claim there is
    # refused for lack of consensus, NOT held as too soon.
    v = A(record=_rec(EID_WNBA, "WNBA", "SYNTH_MIN", "SYNTH_ATL", "2026-08-30T23:00:00Z", CLOSED,
                      81, 78, source="web_search"),
          now_utc="2026-08-31T01:10:00Z", lane=LANE_SEARCH)
    if v.disposition != NO_CONSENSUS:
        f.append("WNBA: 130 minutes after a WNBA tip is past the 120-minute minimum; got %s %s"
                 % (v.disposition, v.reason_codes))

    # ---- FIXTURES 8, 9, 10 ARE BOARD INVARIANTS AND LIVE IN THE BOARD MODULE ----------------
    # This module owns only their VOCABULARY, so the two cannot fork. If these strings change,
    # the board module's reason codes change with them or this fails.
    if MIN_ATL_REQUIRED_ROW != {"decision": "PASS",
                                "reason_codes": ["MISSING_MARKET_PRICE", "AVAILABILITY_UNKNOWN",
                                                 "MODEL_CONVERGENCE_FAIL"]}:
        f.append("F8/F9/F10: the required MIN@ATL row drifted from the owner's directive")
    if (DECISION_PASS_DATA_QUALITY, DECISION_CONVERGENCE_FAIL, AVAILABILITY_UNKNOWN) != \
            ("PASS_DATA_QUALITY", "CONVERGENCE_FAIL", "UNKNOWN"):
        f.append("F8/F9/F10: a board decision constant drifted")

    # ---- THE 8/30 SNIPPET IN ITS ACTUAL SHAPE: A SENTENCE, WITH NO ID AND NO STATUS ---------
    # This is what the search actually returned. Not a record with a bad field — prose.
    v = A(record="Nationals 9, Marlins 2", now_utc=_NOW_1330ET, canonical_schedule=sched,
          lane=LANE_SEARCH)
    if v.disposition != UNVERIFIED or REASON_RECORD_NOT_A_MAPPING not in v.reason_codes:
        f.append("SNIPPET: a bare sentence produced %s %s" % (v.disposition, v.reason_codes))
    no_id = _rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9)
    no_id["event_id"] = None
    v = A(record=no_id, now_utc=_EVENING, canonical_schedule=sched, lane=LANE_SEARCH)
    if v.disposition != REJECT_PRESTART_OR_UNBOUND or REASON_NO_EVENT_ID not in v.reason_codes:
        f.append("SNIPPET: a score with no provider event id produced %s %s"
                 % (v.disposition, v.reason_codes))

    # ---- THE REMAINING NON-FINAL STATES, AND SCORES ASSERTED UNDER THEM ---------------------
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, SUSPENDED,
                      2, 1),
          now_utc=_EVENING, canonical_schedule=sched, lane=LANE_CANONICAL)
    if v.disposition != UNVERIFIED or REASON_GAME_SUSPENDED not in v.reason_codes:
        f.append("SUSPENDED: a suspended game's partial score was treated as a result (%s %s)"
                 % (v.disposition, v.reason_codes))
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, UNKNOWN, 2, 9),
          now_utc=_EVENING, canonical_schedule=sched, lane=LANE_CANONICAL)
    if v.disposition != UNVERIFIED or REASON_STATUS_UNKNOWN not in v.reason_codes:
        f.append("UNKNOWN: an unmapped provider status was not treated as non-final (%s %s)"
                 % (v.disposition, v.reason_codes))
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, SCHEDULED,
                      2, 9),
          now_utc=_EVENING, canonical_schedule=sched, lane=LANE_CANONICAL)
    if REASON_SCORE_WITHOUT_TERMINAL_STATUS not in v.reason_codes:
        f.append("SCORE/STATUS: a score under a SCHEDULED status was not flagged (%s)"
                 % v.reason_codes)

    # ---- THE OTHER THREE WAYS A RECORD CAN DISAGREE WITH THE SCHEDULE -----------------------
    for label, mutate, code in (
            ("teams", lambda r: r.__setitem__("home_team_id", "SYNTH_NYM"),
             REASON_SCHEDULE_TEAMS_DISAGREE),
            ("teams reversed", lambda r: r.update({"away_team_id": "SYNTH_WSH",
                                                   "home_team_id": "SYNTH_MIA"}),
             REASON_SCHEDULE_TEAMS_REVERSED),
            ("league", lambda r: r.__setitem__("league", "WNBA"),
             REASON_SCHEDULE_LEAGUE_DISAGREE)):
        r = _rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9)
        mutate(r)
        v = A(record=r, now_utc=_EVENING, canonical_schedule=sched, lane=LANE_CANONICAL)
        if v.disposition != REJECT_SCHEDULE_CONFLICT or code not in v.reason_codes:
            f.append("CONFLICT %s: expected %s, got %s %s"
                     % (label, code, v.disposition, v.reason_codes))

    refuses("negative score", lambda r: r.__setitem__("away_score", -1), REASON_NEGATIVE_SCORE)

    # ---- EVERY VERDICT THIS SELFTEST PRODUCED MUST BE WELL FORMED ---------------------------
    for v in verdicts:
        seen_codes.update(v.reason_codes)
        if v.disposition not in DISPOSITIONS:
            f.append("VERDICT: disposition %r is not in DISPOSITIONS" % (v.disposition,))
        if not v.reason_codes:
            f.append("VERDICT: %s carried no reason codes — a verdict that cannot be audited is "
                     "the 8/27 review" % v.disposition)
        unknown = [c for c in v.reason_codes if c not in REASON_MEANING]
        if unknown:
            f.append("VERDICT: undocumented reason codes %s" % unknown)
        if v.admissible_as is not None and v.admissible_as not in ADMISSIBLE_AS_VALUES:
            f.append("VERDICT: admissible_as %r is not in ADMISSIBLE_AS_VALUES" % v.admissible_as)
        if v.settleable and v.disposition != ADMIT_FINAL:
            f.append("VERDICT: %s reported itself settleable" % v.disposition)
        v.to_dict()
        # The lane invariant, asserted over EVERY verdict this selftest produced rather than on
        # the one fixture that was thinking about it: search never admits, and never routes
        # anywhere but quarantine.
        lane = v.detail.get("lane")
        sink = sink_for(v)
        if lane == LANE_SEARCH and v.admitted:
            f.append("VERDICT: a SEARCH verdict was ADMITTED (%s/%s)"
                     % (v.disposition, v.admissible_as))
        if lane == LANE_SEARCH and sink != SINK_QUARANTINE:
            f.append("VERDICT: a SEARCH verdict routed to %r" % sink)
        if lane in LANES:
            try:
                assert_write_allowed(lane, sink)
            except LaneViolation as e:
                f.append("VERDICT: routing violates the lane table (%s)" % e)

    # ---- VOCABULARY COVERAGE ----------------------------------------------------------------
    # A reason code with no fixture is a code nobody has ever watched fire. There is no exemption
    # list on purpose: a code that cannot be produced should be deleted, not excused.
    uncovered = [c for c in REASON_CODES if c not in seen_codes]
    if uncovered:
        f.append("COVERAGE: reason codes this selftest never produces: %s" % uncovered)

    print(f"{MODULE_ID} selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("  FAIL:", x)
    return not f


# ---------------------------------------------------------------------------------------------
# 12. MUTATION SUITE.  A counter that cannot fail is not a check.
#     Each entry names the DEFECT RESTORED, not a test. Every one must be KILLED by selftest().
# ---------------------------------------------------------------------------------------------

MUTANTS = [
    ("a final before first pitch is admitted again (8/30 BOS@NYY, COL@ATL)",
     "    if start_utc is not None and now < start_utc and (claims_score or claims_terminal):",
     "    if False:"),
    ("'complete' counts as validated, so an unvalidated final becomes settleable",
     "VALIDATED_STATES = frozenset({CLOSED})",
     "VALIDATED_STATES = frozenset({CLOSED, COMPLETE})"),
    ("the SEARCH lane may mint a FINAL",
     "    return lane == LANE_SEARCH",
     "    return False"),
    ("two corroborating search sources promote the claim to FINAL",
     "        return Verdict(UNVERIFIED, reasons, ADMISSIBLE_CORROBORATED, detail)",
     "        return Verdict(ADMIT_FINAL, reasons, ADMISSIBLE_FINAL, detail)"),
    ("the record is never compared against the canonical schedule",
     "    conflicts = _schedule_conflicts(record, entry, lane)",
     "    conflicts = []"),
    ("the SOFT duration check becomes hard: a canonical terminal status can no longer clear it, "
     "and the rain-shortened game is false-rejected (owner message 1's warning, restored)",
     "    cleared = too_soon and lane == LANE_CANONICAL and status in TERMINAL_STATES",
     "    cleared = False"),
    ("the SEARCH lane may write to the board again (the 8/27 publication path)",
     "    LANE_SEARCH: frozenset({SINK_QUARANTINE}),",
     "    LANE_SEARCH: frozenset({SINK_QUARANTINE, SINK_BOARD}),"),
    ("any string is accepted as an event id",
     '_EVENT_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*:[0-9]{4}:[A-Za-z0-9_.-]+$")',
     '_EVENT_ID_RE = re.compile(r"^.+$")'),
    ("the temporal kill-switch is disarmed (every minimum set to zero)",
     'MIN_DURATION_MINUTES = {"MLB": 150, "NBA": 120, "WNBA": 120, "NFL": 165, "CFB": 180}',
     'MIN_DURATION_MINUTES = {"MLB": 0, "NBA": 0, "WNBA": 0, "NFL": 0, "CFB": 0}'),
    ("outlets sharing one wire feed count as independent witnesses",
     '    return record.get("wire_service") or record.get("source")',
     '    return record.get("source")'),
    ("admit stops validating the record, so a score with no status field flows through",
     "    ok_rec, problems = validate_record(record)",
     "    ok_rec, problems = True, []"),
    ("the market lane may produce a score",
     "    if lane == LANE_MARKET:",
     "    if False:"),
]


def mutation_suite():
    src = open(__file__).read()
    # BASELINE FIRST. A failing selftest makes every mutant look killed, so a broken fixture
    # reports a perfect score.
    import io as _io, contextlib as _cl
    _b = _io.StringIO()
    with _cl.redirect_stdout(_b):
        _base = selftest()
    if not _base:
        print("  BASELINE_FAILING  the unmutated selftest does not pass; every 'kill' below is "
              "meaningless until it does")
        print(_b.getvalue().strip())
        return False
    # a mutant whose pattern occurs only inside the MUTANTS literal edits its OWN definition,
    # applies cleanly, changes no behaviour and reports SURVIVED.
    body = src[:src.index("MUTANTS = [")]
    killed = 0
    for name, old, new in MUTANTS:
        if old not in src:
            print("  UNAPPLIED ", name + ": pattern not found")
            continue
        if old not in body:
            print("  SELF_TARGETED ", name + ": pattern occurs only inside the MUTANTS list")
            continue
        ns = {"__file__": __file__, "__name__": "mutant"}
        try:
            exec(compile(src.replace(old, new, 1), "<mutant>", "exec"), ns)
            ok = ns["selftest"]()
        except Exception:
            ok = False
        print(("  KILLED    " if not ok else "  SURVIVED  ") + name)
        killed += not ok
    print(f"score_admission mutation suite: {killed}/{len(MUTANTS)} killed"
          + ("" if killed == len(MUTANTS) else "  — SURVIVORS MEAN DECORATIVE FIXTURES"))
    return killed == len(MUTANTS)


def gate():
    """Healthcheck entry point: the fixtures hold AND the mutants die."""
    import io as _io, contextlib as _cl
    _b = _io.StringIO()
    with _cl.redirect_stdout(_b):
        ok_self = selftest()
        ok_mut = mutation_suite()
    print("score admission gate: %s (selftest %s, mutants %s)"
          % ("PASS" if (ok_self and ok_mut) else "FAIL",
             "OK" if ok_self else "FAIL", "OK" if ok_mut else "FAIL"))
    if not (ok_self and ok_mut):
        print(_b.getvalue().strip())
    return 0 if (ok_self and ok_mut) else 1


if __name__ == "__main__":
    if "--mutants" in sys.argv:
        sys.exit(0 if mutation_suite() else 1)
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    if "--gate" in sys.argv:
        sys.exit(gate())
    print(__doc__)
