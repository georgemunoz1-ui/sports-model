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
      It reads BOTH CLOCKS, exactly as (a) does — see ROUND TWO below.

ROUND TWO, 2026-08-30 re-attack. Round one found untouched defects. Round two found INCOMPLETE
FIXES, and every item below is one: a guard repaired on one rule and not the neighbouring one, a
clock bounded below and not above, a field carried by both sides and compared by neither.

  cluster M, part (b)   The hard pre-start rule was repaired to read both the judging and the
                        OBSERVATION clock. The soft duration hold was left reading `now` alone,
                        so the 8/30 MIA@WSH snippet — observed 75 minutes into a 150-minute game
                        — lost MIN_DURATION_NOT_ELAPSED entirely by being judged that evening.
                        Same bytes, same fetch, later look, weaker verdict. Both clocks now, with
                        the SOFT semantics unchanged: a canonical terminal status still clears it.
  the upper bound       Nothing compared source_fetched_at_utc against now_utc, so a record
                        claiming to have been fetched in 2027 admitted and settled in 2026. A
                        stamp a guard READS is a stamp the guard must BOUND.
                        Disposition: REJECT_PRESTART_OR_UNBOUND, OBSERVED_AFTER_THE_JUDGEMENT_
                        INSTANT.
  the schedule key      index_schedule() returned dict(schedule) for a dict input and never asked
                        whether a key equalled its entry's own event_id, and _schedule_conflicts
                        never compared them. An entry filed under another game's id bound the
                        wrong game. Owner rule 1 binds by the PROVIDER's id, not by a caller's
                        dict key; the entry's own id is now the index key, and the comparison
                        exists as well.
  game_number           Declared in OPTIONAL_RECORD_FIELDS and in CANONICAL_SCHEDULE_OPTIONAL_
                        FIELDS and compared nowhere, so a record claiming doubleheader half 2
                        bound cleanly to an entry declaring half 1 — owner regression fixture 4
                        landing inside the binder.
  the self-schedule     Cluster A made a canonical schedule MANDATORY without making it
                        INDEPENDENT, so admit(record, canonical_schedule=record) reached
                        ADMIT_FINAL / settleable / result_ledger: "a record checked only against
                        itself", which is the phrase cluster A's own docstring used for the
                        defect it closed.
  the status field      `record['status']` was an ungrounded caller assertion in exactly the way
                        `lane` was before cluster B. Nothing checked a status was REACHABLE from
                        its own source's PROVIDER_STATUS_MAPS, so source='espn_scoreboard_api'
                        with status='CLOSED' settled — against this file's own docstring, which
                        says ESPN exposes no statistics-validation state anywhere in this repo.

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
import json
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

#: THE SOURCE ALLOWLIST.  CLUSTER B, 2026-08-30 review: `lane` arrived as an UNVERIFIED CALLER
#: ASSERTION. Nothing compared record["source"] against it, so a web_search record carrying
#: lane=CANONICAL reached ADMIT_FINAL, settleable, result_ledger — the 8/27 publication path with
#: a different label on the envelope. The three PROVIDER_* constants existed and were never used
#: as an allowlist; they are one now.
#:
#: Only these three sources may ride the canonical lane. The list is short because the repo
#: evidences exactly three provider vocabularies (PROVIDER_STATUS_MAPS); adding a fourth here
#: without a status map would be describing a feed from memory (R1).
CANONICAL_SOURCES = frozenset({PROVIDER_MLB_STATSAPI, PROVIDER_ESPN_SCOREBOARD,
                               PROVIDER_SPORTRADAR})

#: Trust ordering, so "take the lower of the two" is arithmetic rather than a chain of ifs.
LANE_TRUST_RANK = {LANE_SEARCH: 0, LANE_MARKET: 1, LANE_CANONICAL: 2}


def lane_for_source(source):
    """The lane a source EARNS, independent of the lane its caller declares.

    Unknown sources default to SEARCH, never CANONICAL: an unrecognised name is an unapproved
    one. This function never returns MARKET — a price source is declared by the caller and is
    refused as a score source before this is consulted.
    """
    if source is None:
        return LANE_SEARCH
    return LANE_CANONICAL if str(source).strip().lower() in CANONICAL_SOURCES else LANE_SEARCH


def effective_lane(declared_lane, source):
    """(lane, demoted). The LOWER-trust of what the caller claims and what the source earns.

    Never an upgrade: a canonical feed handed in on the search lane stays on the search lane,
    because the caller may know something about that fetch that this module does not.
    """
    if declared_lane != LANE_CANONICAL:
        # MARKET is refused as a score source before this is reached, and SEARCH is already the
        # floor. Only the CANONICAL claim is worth checking, and it is the only one worth forging.
        return declared_lane, False
    earned = lane_for_source(source)
    if LANE_TRUST_RANK[earned] < LANE_TRUST_RANK[LANE_CANONICAL]:
        return earned, True
    return declared_lane, False


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


def reachable_statuses_for_source(source):
    """Every state `source`'s provider map can actually produce, or None when it has no map.

    None means "this module holds no vocabulary for that source", which is a DIFFERENT fact from
    "that source can produce nothing" and must not be collapsed into one: a search outlet has no
    map and is already refused by the lane rules, so inventing a state list for it would add a
    second, weaker refusal in front of the real one.
    """
    if source is None:
        return None
    table = PROVIDER_STATUS_MAPS.get(str(source).strip().lower())
    return None if table is None else frozenset(table.values()) | {UNKNOWN}


def terminal_status_unreachable_from_source(source, status):
    """(unreachable, detail|None) — the record asserts a TERMINAL state its own source cannot emit.

    ROUND-TWO FINDING, 2026-08-30 re-attack. `record['status']` was an ungrounded caller
    assertion in exactly the way `lane` was before cluster B: nothing compared it against the
    source's own vocabulary. So source='espn_scoreboard_api' with status='CLOSED' reached
    ADMIT_FINAL / FINAL / settleable, contradicting this module's own docstring, which says of
    ESPN: "STATUS_FINAL -> COMPLETE, NOT CLOSED: the scoreboard API exposes no
    statistics-validation state anywhere in this repo." normalize_status() is a helper a caller
    may simply not call; this is the check that does not depend on the caller calling it.

    SCOPED TO TERMINAL STATES, deliberately, and this is the whole design decision. The provider
    maps are PARTIAL BY CONSTRUCTION (R1: only what this repo has witnessed is mapped — F, O, DD
    and S for MLB StatsAPI, three constants for ESPN). MLB StatsAPI plainly has in-progress
    states; this repo has never captured one, so IN_PROGRESS is unreachable from the map while
    being entirely real. Requiring reachability for EVERY status would therefore false-reject
    genuine live records for a gap in OUR OWN evidence table — the blanket-refusal degeneration
    the owner warned about on the duration rule, relocated here. A TERMINAL claim is different:
    it is the claim that mints a final and settles a wager, and refusing an unreachable one
    cannot false-reject any of the three mapped providers, each of which reaches at least one
    terminal state (MLB and Sportradar both, ESPN COMPLETE and never CLOSED).
    """
    if status not in TERMINAL_STATES:
        return False, None
    reachable = reachable_statuses_for_source(source)
    if reachable is None or status in reachable:
        return False, None
    return True, {"code": REASON_STATUS_UNREACHABLE_FROM_SOURCE, "field": "status",
                  "status": status, "source": source,
                  "reachable_terminal_states": sorted(reachable & TERMINAL_STATES),
                  "detail": "no key of this provider's PROVIDER_STATUS_MAPS entry maps to %r; "
                            "the state is the caller's assertion, not the provider's" % (status,)}


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
REASON_SOURCE_NOT_APPROVED_FOR_LANE = "SOURCE_NOT_APPROVED_FOR_DECLARED_LANE"

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
REASON_SCHEDULE_EVENT_ID_DISAGREE = "SCHEDULE_ENTRY_EVENT_ID_DISAGREES_WITH_RECORD"
REASON_SCHEDULE_GAME_NUMBER_DISAGREE = "SCHEDULE_GAME_NUMBER_DISAGREE"
REASON_SCHEDULE_IS_THE_RECORD = "CANONICAL_SCHEDULE_IS_THE_RECORD"

REASON_SCHEDULE_CEILING_UNVERIFIED = "NO_SCHEDULE_ADMISSION_CEILING_UNVERIFIED"
REASON_SCHEDULED_DATE_OVERRIDE = "CARRIED_SCHEDULED_DATE_DISAGREES_WITH_DERIVATION"

REASON_PRESTART_FINAL_IMPOSSIBLE = "PRESTART_FINAL_IMPOSSIBLE"
REASON_PRESTART_OBSERVATION_IMPOSSIBLE = "PRESTART_OBSERVED_BEFORE_FIRST_PITCH"
REASON_OBSERVATION_AFTER_JUDGEMENT = "OBSERVED_AFTER_THE_JUDGEMENT_INSTANT"
REASON_MIN_DURATION_NOT_ELAPSED = "MIN_DURATION_NOT_ELAPSED"
REASON_MIN_DURATION_CLEARED = "MIN_DURATION_CLEARED_BY_CANONICAL_TERMINAL"
REASON_SEARCH_CANNOT_CLEAR_MIN_DURATION = "SEARCH_LANE_CANNOT_CLEAR_MIN_DURATION"

REASON_STATUS_MISSING = "SOURCE_STATUS_MISSING"
REASON_STATUS_NOT_IN_VOCABULARY = "SOURCE_STATUS_NOT_IN_VOCABULARY"
REASON_STATUS_UNKNOWN = "SOURCE_STATUS_UNKNOWN"
REASON_STATUS_UNREACHABLE_FROM_SOURCE = "STATUS_UNREACHABLE_FROM_ITS_OWN_SOURCE"
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
REASON_NAIVE_TIMESTAMP = "TIMESTAMP_HAS_NO_UTC_OFFSET"
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
    REASON_SOURCE_NOT_APPROVED_FOR_LANE: "record['source'] is not on CANONICAL_SOURCES, so the "
                                         "caller's CANONICAL declaration is overruled and the "
                                         "record is judged on the SEARCH lane (cluster B)",
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
    REASON_SCHEDULE_EVENT_ID_DISAGREE: "the schedule entry the record bound to declares a "
                                       "DIFFERENT event_id than the record: the entry was filed "
                                       "under a key that is not its own identifier, so the "
                                       "binding was to a caller-chosen key rather than to the "
                                       "authority's own id (owner rule 1)",
    REASON_SCHEDULE_GAME_NUMBER_DISAGREE: "record and schedule entry declare different "
                                          "doubleheader halves under one event id; a field "
                                          "carried by both sides and compared by neither reads "
                                          "in an audit as a check that ran",
    REASON_SCHEDULE_IS_THE_RECORD: "the 'canonical schedule' is the record itself, or a dict "
                                   "carrying the record's own observation fields: a record "
                                   "checked only against itself agrees with itself, which is "
                                   "the defect cluster A closed and not the fix for it",
    REASON_SCHEDULE_CEILING_UNVERIFIED: "no canonical schedule was supplied, so nothing bound "
                                        "this record to a real game: the disposition is capped at "
                                        "UNVERIFIED and the record can never settle (cluster A)",
    REASON_SCHEDULED_DATE_OVERRIDE: "the record or entry carries a scheduled_date that disagrees "
                                    "with the ET date derived from its own UTC instant: a "
                                    "conflict to report, never a value to prefer (cluster N, "
                                    "commit 0bf9399)",
    REASON_PRESTART_FINAL_IMPOSSIBLE: "now precedes first pitch: a final is impossible, not "
                                      "improbable. Hard invariant; no status overrides it",
    REASON_PRESTART_OBSERVATION_IMPOSSIBLE: "the OBSERVATION precedes first pitch: whatever the "
                                            "source saw, it was not the end of this game. Waiting "
                                            "until later to judge it changes nothing (cluster M)",
    REASON_OBSERVATION_AFTER_JUDGEMENT: "source_fetched_at_utc is LATER than now_utc: the record "
                                        "claims to have been observed after the instant it is "
                                        "being judged at. That is as impossible as a final "
                                        "before first pitch, and the module refused one while "
                                        "tolerating the other",
    REASON_MIN_DURATION_NOT_ELAPSED: "the judging clock, the OBSERVATION clock, or both precede "
                                     "start + the sport's minimum duration",
    REASON_MIN_DURATION_CLEARED: "the soft duration hold was cleared by a terminal status from "
                                 "the canonical lane (rain-shortened and called games survive)",
    REASON_SEARCH_CANNOT_CLEAR_MIN_DURATION: "a search snippet can never clear the duration hold",
    REASON_STATUS_MISSING: "no source status field: with nothing to be terminal, nothing admits "
                           "(owner rule 3; the 8/27 summaries had no status at all)",
    REASON_STATUS_NOT_IN_VOCABULARY: "status is not one of STATUSES — normalize_status() first",
    REASON_STATUS_UNKNOWN: "the provider status did not map to a known state; UNKNOWN is treated "
                           "as non-final (owner rule 8)",
    REASON_STATUS_UNREACHABLE_FROM_SOURCE: "the record asserts a TERMINAL status its own source "
                                           "cannot produce: no key of that provider's map in "
                                           "PROVIDER_STATUS_MAPS reaches it. An ESPN scoreboard "
                                           "record claiming CLOSED is the shape — ESPN exposes "
                                           "no statistics-validation state at all, so the claim "
                                           "is the caller's assertion, not the provider's",
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
    REASON_NAIVE_TIMESTAMP: "a timestamp that gates a decision carries no UTC offset; a naive ET "
                            "wall clock read as UTC moves first pitch 4-5 hours earlier (R1: a "
                            "missing offset is missing information, not an assumed zero)",
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

#: The fields that carry an INSTANT. Every one of them gates a decision — the start gates the
#: pre-start invariant, the fetch instant gates the observation clock (cluster M), the result
#: instant gates consensus — so every one of them is refused when it carries no UTC offset.
TIMESTAMP_RECORD_FIELDS = ("scheduled_start_utc", "source_fetched_at_utc", "result_timestamp_utc")

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


def _naive_instant(value):
    """True when `value` states a wall clock and NO offset. R1: that is missing information.

    CLUSTER L, 2026-08-30 review. The first version of _utc() did what feed_espn.parse_utc still
    does — `p if p.tzinfo else p.replace(tzinfo=UTC)` — which reads a naive string as UTC. An ET
    first pitch written "2026-08-30T13:35:00" then becomes 13:35Z, FOUR HOURS EARLY, and both
    halves of the split clock rule are satisfied by a game that has not begun: the record admits
    AND settles before first pitch, with a canonical schedule supplied. A missing offset is not a
    zero offset. It is an unanswered question, and this module answers unanswered questions with a
    refusal.

    parse_utc is still imported and still used, because the ET derivation must live in ONE place;
    this predicate is the gate in front of it, not a second parser.
    """
    if isinstance(value, dt.datetime):
        return value.tzinfo is None or value.tzinfo.utcoffset(value) is None
    if value is None:
        return False
    try:
        parsed = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except Exception:
        return False        # unparseable is a DIFFERENT failure and carries a different code
    return parsed.tzinfo is None


def _utc(value):
    """Any instant -> tz-aware UTC datetime, or None when unparseable. Never a guess.

    A timezone-NAIVE value returns None (cluster L). Callers that need to tell "naive" from
    "gibberish" apart call _instant_problem(); everything else only needs to know it has no
    instant it may compute on.
    """
    if value is None:
        return None
    if _naive_instant(value):
        return None
    if isinstance(value, dt.datetime):
        return value.astimezone(UTC)
    try:
        return parse_utc(value)
    except Exception:
        return None


def _instant_problem(field, value):
    """None when `value` is an offset-bearing instant; otherwise the problem dict that says why.

    Absent (None) is not this function's business — REQUIRED_RECORD_FIELDS handles absence.
    """
    if value is None:
        return None
    if _naive_instant(value):
        return {"code": REASON_NAIVE_TIMESTAMP, "field": field, "value": value,
                "detail": "no UTC offset: an ET wall clock read as UTC moves first pitch 4-5 "
                          "hours earlier (cluster L)"}
    if _utc(value) is None:
        return {"code": REASON_UNPARSEABLE_TIMESTAMP, "field": field, "value": value}
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

    for f in TIMESTAMP_RECORD_FIELDS:
        p = _instant_problem(f, record.get(f))
        if p is not None:
            problems.append(p)

    # CLUSTER N. A carried scheduled_date is a CLAIM to be checked, never a value to prefer.
    conflict, date_problem = carried_scheduled_date_conflict(record)
    if conflict:
        problems.append(date_problem)

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


#: Fields only an OBSERVATION carries. A canonical schedule states what is SCHEDULED; it does not
#: carry a fetch stamp, a content hash, a validation flag or a score. This tuple is what lets
#: "the schedule is the record" be detected by SHAPE rather than by object identity, so a copy is
#: caught as well as the object itself.
RECORD_ONLY_OBSERVATION_FIELDS = ("source", "source_fetched_at_utc", "raw_response_sha256",
                                  "terminal_verified", "away_score", "home_score")


def index_schedule(schedule):
    """Accept a dict keyed by event_id, a single entry, or a sequence of entries -> dict.

    ROUND-TWO FINDING, 2026-08-30 re-attack: THIS FUNCTION TRUSTED THE DICT KEY. For a sequence
    it keyed entries by `e["event_id"]`, but for a dict it returned `dict(schedule)` and never
    asked whether each key equalled the entry's own event_id. A single mis-filed entry —
    {"mlb:2026:BOSNYY": <the COL@ATL entry>} — therefore bound a BOS@NYY record to a schedule
    entry describing a different game, and _schedule_conflicts never compared the two ids either,
    so the record admitted as a settleable FINAL against someone else's game. Owner rule 1 says
    bind by the PROVIDER's event id; a caller-chosen dict key is not the provider's event id.

    The authority now wins over the key: an entry that declares its own event_id is indexed under
    THAT id, so a mis-keyed slate no longer answers a lookup for the key it was filed under. The
    record is then refused as EVENT_NOT_IN_CANONICAL_SCHEDULE rather than mis-bound. An entry
    that declares no id at all keeps the caller's key and is caught one layer down, by the
    event-id comparison in _schedule_conflicts.
    """
    if schedule is None:
        return None
    if isinstance(schedule, dict):
        if "event_id" in schedule and "games" not in schedule:
            return {schedule["event_id"]: schedule}
        out = {}
        for key, entry in schedule.items():
            own = entry.get("event_id") if isinstance(entry, dict) else None
            out[own if own not in (None, "") else key] = entry
        return out
    return {e["event_id"]: e for e in schedule}


def schedule_digest(indexed_schedule):
    """A stable sha256 of an indexed canonical schedule, or None when there is none.

    Recorded in every verdict so a stored ADMIT_FINAL says WHAT it was bound against. Two
    verdicts carrying the same digest were bound against the same slate; a one-entry digest and a
    fifteen-game digest are visibly different objects, which "schedule_supplied: true" was not.
    """
    if indexed_schedule is None:
        return None
    return hashlib.sha256(
        json.dumps(indexed_schedule, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def schedule_entry_is_the_record(entry, record):
    """(is_self, problem|None) — the 'canonical schedule' entry IS the record it must check.

    ROUND-TWO FINDING, 2026-08-30 re-attack, and a hole left inside the CLUSTER A fix. That fix
    made a canonical schedule MANDATORY (absence is a ceiling) but never made it INDEPENDENT, so
    `admit(record, canonical_schedule=record)` reached ADMIT_FINAL / FINAL / settleable=True /
    sink=result_ledger. index_schedule() accepts a single entry, so passing the record produces a
    one-entry index in which the record is its own schedule entry: every comparison in
    _schedule_conflicts compares a dict with itself, and the start instant the split clock rule
    measures against is the record's own claim. That is "a record checked only against itself" —
    the exact sentence cluster A's own docstring uses for the defect it closed — rebuilt out of a
    supplied argument instead of an omitted one.

    Detected by SHAPE, not only by identity, so a copy does not evade it: a schedule entry that
    carries a fetch stamp, a content hash, a validation flag or a score is an observation wearing
    a schedule's name. score_collector.schedule_entries_from_records() already strips exactly
    these fields, which is why an honest morning-slate-binds-evening-results schedule passes.
    """
    if not isinstance(entry, dict) or not isinstance(record, dict):
        return False, None
    if entry is record:
        return True, {"code": REASON_SCHEDULE_IS_THE_RECORD, "how": "the schedule entry IS the "
                      "record object", "event_id": record.get("event_id")}
    if entry == record:
        return True, {"code": REASON_SCHEDULE_IS_THE_RECORD, "how": "the schedule entry is a "
                      "copy of the record, field for field", "event_id": record.get("event_id")}
    carried = [f for f in RECORD_ONLY_OBSERVATION_FIELDS if f in entry]
    if carried:
        return True, {"code": REASON_SCHEDULE_IS_THE_RECORD,
                      "how": "the schedule entry carries observation fields a schedule never has",
                      "observation_fields": carried, "event_id": record.get("event_id")}
    return False, None


def scheduled_date_of(obj):
    """The ET calendar date of a record or schedule entry. ALWAYS DERIVED via feed_espn.et_date_of.

    NEVER sliced from the UTC string: a 2026-08-31T00:30Z tip is the ET EVENING of 08-30, and
    slicing is what corrupted a cohort twice.

    CLUSTER N, 2026-08-30 review. The first version preferred a caller-supplied `scheduled_date`
    string over this derivation, and verified_snapshot uses this function for its slate check. An
    8/28 final carrying scheduled_date "2026-08-30" was therefore filed and served as an 8/30
    result — commit 0bf9399, exactly. The field name also collides with a REQUIRED field in
    result_binding_gate, so the two contracts were one typo apart from agreeing on a lie.

    The instant is the fact. A carried date is a CLAIM about that fact, checked by
    carried_scheduled_date_conflict() and reported, never preferred.
    """
    start = _utc(obj.get("scheduled_start_utc"))
    return None if start is None else et_date_of(start)


def carried_scheduled_date_conflict(obj):
    """(conflict, problem|None) when a carried `scheduled_date` disagrees with the derivation.

    Silence on absence: most records carry no scheduled_date at all, and that is the healthy case.
    Silence when the instant is unusable too — an unparseable or naive start is a different code
    reported by its own check, and stacking two verdicts on one defect reads as two defects.
    """
    if not isinstance(obj, dict):
        return False, None
    carried = obj.get("scheduled_date")
    if carried in (None, ""):
        return False, None
    derived = scheduled_date_of(obj)
    if derived is None or str(carried).strip() == derived:
        return False, None
    return True, {"code": REASON_SCHEDULED_DATE_OVERRIDE, "field": "scheduled_date",
                  "carried": str(carried).strip(), "derived": derived,
                  "detail": "the UTC instant is the fact; the carried date is a claim about it"}


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
    # ROUND TWO. The binding is proved against the ENTRY'S OWN IDENTIFIER, never against the key
    # it happens to sit under. index_schedule now re-keys a dict by the entry's own event_id, so
    # this fires for the case it cannot re-key: an entry that declares no event_id at all, which
    # is an entry that names no event and therefore binds nothing.
    r_eid, e_eid = record.get("event_id"), entry.get("event_id")
    if e_eid in (None, "") or str(e_eid) != str(r_eid):
        conflicts.append({"code": REASON_SCHEDULE_EVENT_ID_DISAGREE,
                          "record": r_eid, "schedule": e_eid})
    # ROUND TWO. game_number was declared in OPTIONAL_RECORD_FIELDS and in
    # CANONICAL_SCHEDULE_OPTIONAL_FIELDS and compared NOWHERE, so a record claiming doubleheader
    # half 2 bound cleanly to an entry declaring half 1. Event-id binding is the real gate and
    # nothing was mis-admitted by this alone, but a field carried by both sides and checked by
    # neither reads in an audit as a check that ran. It is checked now, and only when BOTH sides
    # declare one: a record that makes no doubleheader claim is not making a false one.
    r_gn, e_gn = record.get("game_number"), entry.get("game_number")
    if r_gn is not None and e_gn is not None and str(r_gn) != str(e_gn):
        conflicts.append({"code": REASON_SCHEDULE_GAME_NUMBER_DISAGREE,
                          "record": r_gn, "schedule": e_gn})
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
    # CLUSTER N: check the CARRIED date on both sides before comparing the derived ones, so a
    # record and an entry that both carry the same wrong string cannot agree their way past the
    # comparison below.
    for side, obj in (("record", record), ("schedule", entry)):
        carried_conflict, carried_problem = carried_scheduled_date_conflict(obj)
        if carried_conflict:
            conflicts.append(dict(carried_problem, side=side))
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


def _ceiling_unverified(verdict, code):
    """Cap a verdict at UNVERIFIED, keeping every reason it already carries and adding `code`.

    A ceiling is not a refusal: the record may still be stored, shown and audited as unverified.
    It may not be believed, and it may not settle. Verdict.settleable reads ADMIT_FINAL, so the
    demotion closes the settlement path as a consequence of the disposition rather than by a
    second flag that could disagree with it.
    """
    reasons = list(verdict.reason_codes) + [code]
    if verdict.disposition not in ADMITTING_DISPOSITIONS:
        return Verdict(verdict.disposition, reasons, verdict.admissible_as, verdict.detail)
    # REASON_SCHEDULE_CEILING_UNVERIFIED fires ONLY here, on a verdict that would otherwise have
    # admitted. It is the auditable trace of an admission that was taken back, which the code
    # naming the missing input cannot express on its own.
    return Verdict(UNVERIFIED, reasons + [REASON_SCHEDULE_CEILING_UNVERIFIED],
                   ADMISSIBLE_IDENTIFIED_UNCONFIRMED,
                   dict(verdict.detail, admission_ceiling=code, terminal_verified=False,
                        ceiling_replaced=verdict.disposition))


def admit(record, *, now_utc, canonical_schedule=None, lane, corroborations=0):
    """THE admission gate. All eight owner rules plus the lead's split clock rule.

    record             a normalized record (see RECORD_FIELDS)
    now_utc            the instant the judgement is made; str or datetime
    canonical_schedule dict keyed by event_id, a sequence of entries, or None. SUPPLY IT. The
                       parameter keeps its default only because three sibling modules already
                       call this function; the default is now a CEILING, not a shortcut — see
                       below.
    lane               one of LANES; keyword-only and REQUIRED, because a caller that forgets to
                       say where the data came from is the 8/27 defect in miniature
    corroborations     independent-source count from corroboration_count(); search lane only

    Returns a Verdict. Never a bool, never a bare string.

    CLUSTER A, 2026-08-30 review — the most important finding in that pass, reached independently
    by four lenses. Owner rules 1, 2 and 6 (bind by provider event id, require exact teams /
    league / date, reject schedule conflicts) all live inside `if idx is not None`, so with
    canonical_schedule left at its default the record was checked ONLY AGAINST ITSELF, and a
    fabricated final reached ADMIT_FINAL / settleable=True / sink=result_ledger. No forged
    verdict was needed; an omitted argument was enough. The owner's spec was OPT-IN.

    It is not opt-in now. Absence of a schedule is NON-ADMITTING: whatever the rest of the
    reasoning concludes, a record that was never bound to a real game is capped at UNVERIFIED
    with CANONICAL_SCHEDULE_NOT_SUPPLIED, and can never be settleable. Binding to nothing is not
    binding, and a record checked only against itself is a record that agrees with itself.
    """
    verdict = _admit(record, now_utc=now_utc, canonical_schedule=canonical_schedule, lane=lane,
                     corroborations=corroborations)
    # THE CEILING. Applied to whatever _admit concluded, so no branch inside it can leak an
    # admission past a missing schedule — including branches added later by someone who never
    # read this docstring.
    if index_schedule(canonical_schedule) is None:
        verdict = _ceiling_unverified(verdict, REASON_SCHEDULE_NOT_SUPPLIED)
    if verdict.detail.get("source_lane_demoted"):
        verdict = Verdict(verdict.disposition,
                          list(verdict.reason_codes) + [REASON_SOURCE_NOT_APPROVED_FOR_LANE],
                          verdict.admissible_as, verdict.detail)
    return verdict


def _admit(record, *, now_utc, canonical_schedule=None, lane, corroborations=0):
    """The reasoning admit() puts a ceiling on. Call admit(), never this."""
    now = _utc(now_utc)
    idx = index_schedule(canonical_schedule)
    # ROUND TWO. The verdict records the SHAPE of what the record was bound against, on EVERY
    # branch. Before this, n_schedule_events appeared only on the event-not-found branch, so an
    # auditor reading a stored ADMIT_FINAL could not tell a fifteen-game slate from a one-entry
    # schedule that was the record itself. "schedule_supplied: true" was the whole proof.
    detail = {"lane": lane, "now_utc": _iso(now), "corroborations": int(corroborations or 0),
              "event_id": record.get("event_id") if isinstance(record, dict) else None,
              "schedule_supplied": idx is not None,
              "n_schedule_events": None if idx is None else len(idx),
              "canonical_schedule_sha256": schedule_digest(idx)}

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

    # ---- CLUSTER B: the lane is the CALLER's claim; the source is the EVIDENCE -------------
    # A declared lane was believed on sight, so a web_search record relabelled CANONICAL admitted
    # as a settleable FINAL. The declaration may now only LOWER trust, never raise it.
    declared_lane = lane
    lane, source_lane_demoted = effective_lane(declared_lane, record.get("source"))
    detail.update({"lane": lane, "declared_lane": declared_lane,
                   "source": record.get("source"),
                   "source_lane": lane_for_source(record.get("source")),
                   "source_lane_demoted": source_lane_demoted,
                   "approved_canonical_sources": sorted(CANONICAL_SOURCES)})

    if now is None:
        problem = _instant_problem("now_utc", now_utc) or {"code": REASON_MISSING_REQUIRED_FIELD}
        return Verdict(UNVERIFIED, [problem["code"]], None,
                       dict(detail, field="now_utc", value=str(now_utc)))

    # ---- owner rules 1 and 5: bind by provider event id, never by names ------------------
    ok_id, id_problems = validate_event_id(record.get("event_id"))
    if not ok_id:
        return Verdict(REJECT_PRESTART_OR_UNBOUND, [p["code"] for p in id_problems], None,
                       dict(detail, record_problems=id_problems))

    # ---- CLUSTER L: every instant that gates a decision must carry its offset -------------
    # Checked HERE, before binding, because a naive start compared against an aware schedule
    # entry produces SCHEDULE_START_DISAGREE — a true refusal for the wrong reason, which reads
    # in the audit as "the schedule caught it" when nothing caught the missing offset.
    stamp_problems = [p for p in (_instant_problem(f, record.get(f))
                                  for f in TIMESTAMP_RECORD_FIELDS) if p is not None]
    if stamp_problems:
        return Verdict(UNVERIFIED, [p["code"] for p in stamp_problems], None,
                       dict(detail, record_problems=stamp_problems))

    # ---- owner rules 2 and 6: agree with the canonical schedule --------------------------
    entry = None
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
        # ROUND TWO. The schedule must be INDEPENDENT of the record, not merely SUPPLIED. Checked
        # BEFORE every comparison below, because each of those comparisons is a comparison of a
        # dict with itself when this fires, and a self-comparison that passes reads in the audit
        # as a binding that was proved.
        is_self, self_problem = schedule_entry_is_the_record(entry, record)
        if is_self:
            return Verdict(REJECT_PRESTART_OR_UNBOUND, [REASON_SCHEDULE_IS_THE_RECORD], None,
                           dict(detail, schedule_problems=[self_problem],
                                rule="a record checked only against itself agrees with itself; "
                                     "supplying the record as its own schedule is binding to "
                                     "nothing with an argument filled in"))
        entry_stamp = _instant_problem("schedule.scheduled_start_utc",
                                       entry.get("scheduled_start_utc"))
        if entry_stamp is not None:
            # CLUSTER L on the other side of the comparison. A naive entry start is the more
            # dangerous half: the schedule is the authority the record is measured against, so a
            # schedule four hours early moves every game of the slate.
            return Verdict(UNVERIFIED, [entry_stamp["code"]], None,
                           dict(detail, schedule_problems=[entry_stamp]))
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

    # ---- part (a) again, on the OBSERVATION clock. CLUSTER M ------------------------------
    # The check above asks when the JUDGE looked. That is the wrong clock on its own, and the
    # review named this the single most damning finding for this module's stated purpose: the
    # exact 8/30 records — "Yankees 1, Red Sox 0" fetched at 13:30 ET for a 13:35 ET first pitch
    # — became ADMIT_FINAL, settleable, result_ledger simply by being judged a few hours later.
    # WAITING DEFEATED THE ONE RULE THE DOCSTRING CALLS UNCONDITIONAL.
    #
    # It cannot now. The observation governs: a source that had not yet seen first pitch did not
    # see the end of the game, and no later judging instant adds information to a fetch that
    # already happened. Both clocks must pass; neither substitutes for the other.
    fetched_utc = _utc(record.get("source_fetched_at_utc"))
    detail["source_fetched_at_utc"] = _iso(fetched_utc)

    # ---- THE OBSERVATION CLOCK'S UPPER BOUND. ROUND TWO ------------------------------------
    # Cluster M put the observation clock in front of the pre-start rule and gave it no ceiling.
    # Nothing compared source_fetched_at_utc against now_utc, so a record stamped 2027-01-01 —
    # months after the instant it was being judged at — reached ADMIT_FINAL, settleable=True,
    # sink=result_ledger, with no reason code and no detail field recording that the observation
    # postdated the judgement. `fetched > now` is as impossible as a final before first pitch,
    # and this module refused one while tolerating the other. A stamp the guard READS is a stamp
    # the guard must BOUND: an unbounded stamp is a knob, and cluster M's whole point is that a
    # clock a caller can set freely is not a clock.
    if fetched_utc is not None and fetched_utc > now:
        return Verdict(REJECT_PRESTART_OR_UNBOUND, [REASON_OBSERVATION_AFTER_JUDGEMENT], None,
                       dict(detail,
                            minutes_after_now=round((fetched_utc - now).total_seconds() / 60.0, 1),
                            rule="source_fetched_at_utc > now_utc: the record claims an "
                                 "observation from after the moment it is being judged at. No "
                                 "fetch has happened yet at that instant"))

    if start_utc is not None and fetched_utc is not None and fetched_utc < start_utc \
            and (claims_score or claims_terminal):
        return Verdict(REJECT_PRESTART_OR_UNBOUND,
                       [REASON_PRESTART_OBSERVATION_IMPOSSIBLE], None,
                       dict(detail, claims_score=claims_score, claims_terminal=claims_terminal,
                            minutes_before_start=round(
                                (start_utc - fetched_utc).total_seconds() / 60.0, 1),
                            rule="source_fetched_at_utc < scheduled_start: the source observed "
                                 "this game before it began, so whatever it reported is not a "
                                 "result. Judging it later does not make it one"))

    # ---- owner rules 3 and 7: a source status field, and a retained content hash ----------
    ok_rec, problems = validate_record(record)
    if not ok_rec:
        codes = [p["code"] for p in problems]
        return Verdict(UNVERIFIED, codes, None, dict(detail, record_problems=problems))

    status = record["status"]
    detail["status"] = status
    detail["terminal_verified"] = terminal_verified_for(status)
    base = [] if idx is not None else [REASON_SCHEDULE_NOT_SUPPLIED]

    # ---- ROUND TWO: A STATUS IS EVIDENCE ONLY IF ITS OWN SOURCE CAN PRODUCE IT -------------
    # `status` was an ungrounded caller assertion in exactly the way `lane` was before cluster B.
    # validate_record checks only that the string is in STATUSES; normalize_status() is a helper
    # a caller may simply not call. So source='espn_scoreboard_api' with status='CLOSED' admitted
    # as a settleable FINAL although the ESPN map reaches no validated state at all — the module
    # contradicting its own docstring, in the same shape as the lane forgery.
    unreachable, unreachable_problem = terminal_status_unreachable_from_source(
        record.get("source"), status)
    if unreachable:
        detail["reachable_statuses"] = sorted(reachable_statuses_for_source(record.get("source")))
        return Verdict(UNVERIFIED, base + [REASON_STATUS_UNREACHABLE_FROM_SOURCE], None,
                       dict(detail, record_problems=[unreachable_problem]))

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
    #
    # ROUND TWO — CLUSTER M, FINISHED. The hard rule above was repaired to read BOTH clocks and
    # this one was left reading the judging clock alone: `too_soon = now < earliest`. So a
    # terminal record OBSERVED 75 minutes into a 150-minute game lost MIN_DURATION_NOT_ELAPSED
    # entirely by being judged that evening — the 8/30 MIA@WSH snippet, same bytes, same fetch
    # instant, judged at 23:00Z instead of 17:30Z, came back UNVERIFIED with the duration codes
    # gone. No disposition flipped to a final that would not otherwise be one (canonical clears
    # the hold by spec, search still cannot mint), but the search hold evaporated by waiting and
    # the audit trail stopped recording that the observation was made inside the impossible
    # window. That is the same sentence cluster M was written against: WAITING IS NOT EVIDENCE.
    #
    # BOTH clocks now, exactly as the hard rule does. The SOFT semantics are untouched: a
    # canonical terminal status still clears it, so the rain-shortened and called games owner
    # message 1 protected are not false-rejected — CLOCK(b) below is the fixture that proves the
    # rule has not degenerated into a blanket refusal, and it must keep passing.
    earliest = earliest_possible_final(start_utc, record["league"]) if start_utc else None
    detail["earliest_possible_final"] = _iso(earliest)
    judged_too_soon = earliest is not None and now < earliest
    observed_too_soon = earliest is not None and fetched_utc is not None and fetched_utc < earliest
    too_soon = judged_too_soon or observed_too_soon
    if too_soon:
        detail["min_duration_too_soon_on"] = ([c for c, hit in (("judging", judged_too_soon),
                                                                ("observation", observed_too_soon))
                                               if hit])
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


def selftest_failures():
    """The list of NAMED failures, empty when the module holds. selftest() prints it and returns
    a bool; the mutation suite reads the list itself.

    CLUSTER O. The suite used to treat ANY exception as a kill, so a mutant that died at import
    without running a single fixture counted the same as a mutant a fixture caught. This function
    exists so "killed" can mean what it says: a named expectation was checked and was wrong. An
    exception is a different fact and is reported as an ERROR, never added to the tally.

    Every fixture below is one of the ten regression cases the owner named, or a vocabulary
    invariant another module depends on. Fixture names are the incident, not a test number.
    """
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
    # fetched AFTER the second game's 20:07Z first pitch: an observation of a game in progress or
    # over. The default fetch instant in _rec is 17:30Z, which precedes it, and cluster M's
    # observation clock refuses that correctly — so this fixture states its own fetch time rather
    # than admitting a final that was observed three hours before the game began.
    v = A(record=_rec(EID_DH_G2, "MLB", "SYNTH_KC", "SYNTH_TOR", "2026-08-30T20:07:00Z",
                      CLOSED, 13, 2, fetched=_EVENING),
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

    # ---- CLUSTER A. A MISSING SCHEDULE IS NON-ADMITTING ------------------------------------
    # The review's most important finding: owner rules 1, 2 and 6 lived inside `if idx is not
    # None`, so omitting one argument turned the whole spec off and a fabricated final reached
    # ADMIT_FINAL / settleable / result_ledger. The SAME record is used bound and unbound, so
    # this fixture measures the schedule's absence and nothing else.
    bindable = _rec(EID_DH_G2, "MLB", "SYNTH_KC", "SYNTH_TOR", "2026-08-30T20:07:00Z",
                    CLOSED, 13, 2, fetched=_EVENING)
    v = A(record=bindable, now_utc=_EVENING, canonical_schedule=dh, lane=LANE_CANONICAL)
    if v.disposition != ADMIT_FINAL or not v.settleable:
        f.append("A control: the bound half of the pair stopped admitting, so the unbound half "
                 "below proves nothing (%s %s)" % (v.disposition, v.reason_codes))
    v = A(record=bindable, now_utc=_EVENING, lane=LANE_CANONICAL)
    if v.disposition != UNVERIFIED or v.admitted or v.settleable \
            or REASON_SCHEDULE_NOT_SUPPLIED not in v.reason_codes \
            or REASON_SCHEDULE_CEILING_UNVERIFIED not in v.reason_codes:
        f.append("A ceiling: a record with NO canonical schedule to bind against produced "
                 "%s/%s (admitted=%s, settleable=%s) %s — absence of a schedule must cap the "
                 "disposition at UNVERIFIED"
                 % (v.disposition, v.admissible_as, v.admitted, v.settleable, v.reason_codes))
    if sink_for(v) != SINK_QUARANTINE:
        f.append("A routing: an unbound final routed to %r instead of quarantine" % sink_for(v))
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, IN_PROGRESS,
                      2, 1),
          now_utc=_EVENING, lane=LANE_CANONICAL)
    if v.admitted or REASON_SCHEDULE_NOT_SUPPLIED not in v.reason_codes:
        f.append("A ceiling (live): an unbound in-progress snapshot was ADMITTED (%s/%s) — a "
                 "snapshot of WHICH game? Nothing bound it to one" % (v.disposition, v.admitted))

    # ---- CLUSTER B. THE LANE IS THE CALLER'S CLAIM; THE SOURCE IS THE EVIDENCE --------------
    if lane_for_source("web_search") != LANE_SEARCH or \
            lane_for_source(PROVIDER_MLB_STATSAPI) != LANE_CANONICAL or \
            lane_for_source(None) != LANE_SEARCH or lane_for_source("Sportradar") != \
            LANE_CANONICAL:
        f.append("B allowlist: lane_for_source does not map the three approved providers to "
                 "CANONICAL and everything else to SEARCH")
    mislabelled = _rec(EID_DH_G2, "MLB", "SYNTH_KC", "SYNTH_TOR", "2026-08-30T20:07:00Z",
                       CLOSED, 13, 2, source="web_search", fetched=_EVENING)
    v = A(record=mislabelled, now_utc=_EVENING, canonical_schedule=dh, lane=LANE_CANONICAL)
    if v.admitted or v.settleable or REASON_SOURCE_NOT_APPROVED_FOR_LANE not in v.reason_codes \
            or v.detail.get("lane") != LANE_SEARCH:
        f.append("B relabelled: a web_search record declared CANONICAL produced %s/%s "
                 "(settleable=%s, effective lane %r) — the caller's word is not evidence"
                 % (v.disposition, v.admissible_as, v.settleable, v.detail.get("lane")))
    if sink_for(v) != SINK_QUARANTINE:
        f.append("B routing: a relabelled search record routed to %r" % sink_for(v))
    # ...and never an upgrade. A canonical source handed in on the search lane stays there.
    v = A(record=_rec(EID_DH_G2, "MLB", "SYNTH_KC", "SYNTH_TOR", "2026-08-30T20:07:00Z",
                      CLOSED, 13, 2, fetched=_EVENING),
          now_utc=_EVENING, canonical_schedule=dh, lane=LANE_SEARCH)
    if v.admitted or v.detail.get("lane") != LANE_SEARCH:
        f.append("B upgrade: an approved source was PROMOTED to the canonical lane by its own "
                 "name (%s/%s)" % (v.disposition, v.detail.get("lane")))

    # ---- CLUSTER L. A NAIVE INSTANT IS MISSING INFORMATION, NOT AN ASSUMED ZERO -------------
    # "2026-08-30T13:35:00" is the BOS@NYY first pitch written in ET with the offset dropped.
    # Read as UTC it lands four hours early, and the schedule that should have caught it is
    # written the same way — so at 16:30Z, an hour before the real first pitch, the record
    # cleared both the pre-start invariant and the 150-minute minimum and settled.
    naive_sched = index_schedule([
        _entry(EID_BOSNYY, "SYNTH_BOS", "SYNTH_NYY", "2026-08-30T13:35:00", status=SCHEDULED)])
    naive_rec = _rec(EID_BOSNYY, "MLB", "SYNTH_BOS", "SYNTH_NYY", "2026-08-30T13:35:00",
                     CLOSED, 0, 1, fetched="2026-08-30T16:20:00Z")
    v = A(record=naive_rec, now_utc="2026-08-30T16:30:00Z", canonical_schedule=naive_sched,
          lane=LANE_CANONICAL)
    if v.admitted or REASON_NAIVE_TIMESTAMP not in v.reason_codes:
        f.append("L naive record: an ET wall clock with no offset produced %s %s — read as UTC "
                 "it admits and settles a game that has not started"
                 % (v.disposition, v.reason_codes))
    v = A(record=_rec(EID_BOSNYY, "MLB", "SYNTH_BOS", "SYNTH_NYY", _START_1335ET, CLOSED, 0, 1,
                      fetched="2026-08-30T20:10:00Z"),
          now_utc=_EVENING, canonical_schedule=naive_sched, lane=LANE_CANONICAL)
    if v.admitted or REASON_NAIVE_TIMESTAMP not in v.reason_codes:
        f.append("L naive schedule: an offset-bearing record measured against a NAIVE schedule "
                 "entry produced %s %s — the schedule is the authority and it was four hours "
                 "wrong" % (v.disposition, v.reason_codes))
    if _utc("2026-08-30T13:35:00") is not None or _utc(dt.datetime(2026, 8, 30, 13, 35)) is not None:
        f.append("L _utc: a naive value was still coerced to UTC")
    if _iso(_utc("2026-08-30T13:35:00-04:00")) != "2026-08-30T17:35:00Z":
        f.append("L _utc: an offset-BEARING instant was not converted to UTC correctly")

    # ---- CLUSTER M. THE OBSERVATION CLOCK, NOT THE JUDGING CLOCK ----------------------------
    # The single most damning finding for this module's stated purpose. "Yankees 1, Red Sox 0"
    # was fetched at 17:30Z for a 17:35Z first pitch. Judged at 17:30Z it was refused; judged at
    # 23:00Z — same bytes, same fetch, later look — it became a settleable FINAL in the result
    # ledger. Waiting is not evidence.
    v = A(record=_rec(EID_BOSNYY, "MLB", "SYNTH_BOS", "SYNTH_NYY", _START_1335ET, CLOSED, 0, 1,
                      fetched=_NOW_1330ET),
          now_utc=_EVENING, canonical_schedule=sched, lane=LANE_CANONICAL)
    if v.disposition != REJECT_PRESTART_OR_UNBOUND or v.admitted or \
            REASON_PRESTART_OBSERVATION_IMPOSSIBLE not in v.reason_codes:
        f.append("M observation clock: a final OBSERVED five minutes before first pitch and "
                 "judged five hours later produced %s %s — waiting defeated the one rule this "
                 "module calls unconditional" % (v.disposition, v.reason_codes))
    # The same game, the same judging instant, an observation taken AFTER first pitch: admits.
    # Without this half the rule above could be a blanket refusal of BOS@NYY.
    v = A(record=_rec(EID_BOSNYY, "MLB", "SYNTH_BOS", "SYNTH_NYY", _START_1335ET, CLOSED, 0, 1,
                      fetched="2026-08-30T20:10:00Z"),
          now_utc=_EVENING, canonical_schedule=sched, lane=LANE_CANONICAL)
    if v.disposition != ADMIT_FINAL or not v.settleable:
        f.append("M control: a final observed AFTER first pitch and past the minimum duration "
                 "was refused (%s %s)" % (v.disposition, v.reason_codes))

    # ---- CLUSTER M, PART (b). THE *SOFT* HOLD READS THE OBSERVATION CLOCK TOO ---------------
    # The round-two re-attack: part (a) was repaired on both clocks and part (b) was left on the
    # judging clock alone, so the 8/30 MIA@WSH snippet — OBSERVED 75 minutes into a 150-minute
    # game — lost MIN_DURATION_NOT_ELAPSED entirely by being judged that evening. Same bytes,
    # same fetch instant, later look, weaker verdict.
    observed_inside_window = _rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET,
                                  CLOSED, 2, 9, source="web_search", fetched=_NOW_1330ET)
    v = A(record=observed_inside_window, now_utc=_EVENING, lane=LANE_SEARCH, corroborations=2)
    if v.disposition != UNVERIFIED_TOO_SOON or \
            REASON_MIN_DURATION_NOT_ELAPSED not in v.reason_codes or \
            REASON_SEARCH_CANNOT_CLEAR_MIN_DURATION not in v.reason_codes:
        f.append("M(b) soft clock: a terminal claim OBSERVED 75 minutes into a 150-minute game "
                 "and judged five and a half hours later produced %s %s — the hold evaporated "
                 "by waiting, which is the sentence cluster M was written against"
                 % (v.disposition, v.reason_codes))
    if v.detail.get("min_duration_too_soon_on") != ["observation"]:
        f.append("M(b) audit trail: the verdict does not record WHICH clock was inside the "
                 "impossible window (%r)" % (v.detail.get("min_duration_too_soon_on"),))
    # ...and on the CANONICAL lane the SOFT semantics are unchanged: the terminal status still
    # clears the hold, and the verdict now KEEPS both codes instead of losing them to a late
    # judgement. Owner message 1's rain-shortened game survives; the audit records the window.
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9,
                      fetched=_NOW_1330ET),
          now_utc=_EVENING, canonical_schedule=sched, lane=LANE_CANONICAL)
    if v.disposition != ADMIT_FINAL or not v.settleable or \
            REASON_MIN_DURATION_NOT_ELAPSED not in v.reason_codes or \
            REASON_MIN_DURATION_CLEARED not in v.reason_codes:
        f.append("M(b) canonical clearance: a canonical terminal record observed inside the "
                 "window produced %s %s — the hold must still CLEAR (soft), and the audit must "
                 "still record that the observation was inside the window"
                 % (v.disposition, v.reason_codes))

    # ---- THE OBSERVATION CLOCK'S UPPER BOUND -----------------------------------------------
    # Nothing compared source_fetched_at_utc against now_utc, so a record stamped months after
    # the judging instant admitted and settled. Cluster M's guard read a stamp it never bounded.
    v = A(record=_rec(EID_BOSNYY, "MLB", "SYNTH_BOS", "SYNTH_NYY", _START_1335ET, CLOSED, 0, 1,
                      fetched="2027-01-01T00:00:00Z"),
          now_utc=_EVENING, canonical_schedule=sched, lane=LANE_CANONICAL)
    if v.disposition != REJECT_PRESTART_OR_UNBOUND or v.admitted or v.settleable or \
            REASON_OBSERVATION_AFTER_JUDGEMENT not in v.reason_codes:
        f.append("E3 observation after judgement: a record claiming to have been FETCHED on "
                 "2027-01-01 and judged on 2026-08-30 produced %s %s (settleable=%s) — a fetch "
                 "from after the judging instant has not happened yet"
                 % (v.disposition, v.reason_codes, v.settleable))
    # The near miss that must NOT be refused: fetched at exactly the judging instant is the
    # normal shape of a live collection, and a strict > keeps it admissible.
    v = A(record=_rec(EID_DH_G2, "MLB", "SYNTH_KC", "SYNTH_TOR", "2026-08-30T20:07:00Z",
                      CLOSED, 13, 2, fetched=_EVENING),
          now_utc=_EVENING, canonical_schedule=dh, lane=LANE_CANONICAL)
    if v.disposition != ADMIT_FINAL:
        f.append("E3 control: a record fetched at exactly the judging instant was refused (%s "
                 "%s) — the upper bound must be a bound, not a blanket refusal"
                 % (v.disposition, v.reason_codes))

    # ---- THE SCHEDULE KEY IS NOT THE AUTHORITY'S IDENTIFIER --------------------------------
    # A schedule entry filed under someone else's event id bound a record to a DIFFERENT game,
    # silently: index_schedule returned dict(schedule) for a dict input and _schedule_conflicts
    # never compared the two ids.
    mis_keyed = {EID_BOSNYY: _entry(EID_COLATL, "SYNTH_COL", "SYNTH_ATL", _START_1335ET,
                                    status=SCHEDULED)}
    v = A(record=_rec(EID_BOSNYY, "MLB", "SYNTH_BOS", "SYNTH_NYY", _START_1335ET, CLOSED, 0, 1,
                      fetched="2026-08-30T20:10:00Z"),
          now_utc=_EVENING, canonical_schedule=mis_keyed, lane=LANE_CANONICAL)
    if v.disposition != REJECT_PRESTART_OR_UNBOUND or v.admitted or \
            REASON_EVENT_NOT_IN_SCHEDULE not in v.reason_codes:
        f.append("E4 mis-keyed: a schedule entry filed under ANOTHER game's event id answered "
                 "the lookup and produced %s %s — binding must be to the authority's own "
                 "identifier, never to the key a caller chose" % (v.disposition, v.reason_codes))
    # The entry index_schedule cannot re-key: one that declares no event id at all. It keeps the
    # caller's key and is caught one layer down, by the comparison in _schedule_conflicts.
    unidentified = {EID_MIAWSH: {"league": "MLB", "away_team_id": "SYNTH_MIA",
                                 "home_team_id": "SYNTH_WSH",
                                 "scheduled_start_utc": _START_1215ET}}
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9,
                      fetched=_EVENING),
          now_utc=_EVENING, canonical_schedule=unidentified, lane=LANE_CANONICAL)
    if v.disposition != REJECT_SCHEDULE_CONFLICT or \
            REASON_SCHEDULE_EVENT_ID_DISAGREE not in v.reason_codes:
        f.append("E4 unidentified entry: a schedule entry that names no event bound a record "
                 "anyway (%s %s)" % (v.disposition, v.reason_codes))
    if index_schedule({EID_BOSNYY: _entry(EID_COLATL, "SYNTH_COL", "SYNTH_ATL",
                                          _START_1335ET)}) != index_schedule(
            [_entry(EID_COLATL, "SYNTH_COL", "SYNTH_ATL", _START_1335ET)]):
        f.append("E4 index: index_schedule kept a caller's key over the entry's own event_id")

    # ---- game_number IS CARRIED BY BOTH SIDES AND WAS COMPARED BY NEITHER -------------------
    # Owner regression fixture 4 — the doubleheader — landing inside the binder: a record
    # claiming half 2 bound cleanly to an entry declaring half 1 under one event id.
    v = A(record=_rec(EID_DH_G2, "MLB", "SYNTH_KC", "SYNTH_TOR", "2026-08-30T20:07:00Z",
                      CLOSED, 13, 2, fetched=_EVENING, game_number=1),
          now_utc=_EVENING, canonical_schedule=dh, lane=LANE_CANONICAL)
    if v.disposition != REJECT_SCHEDULE_CONFLICT or \
            REASON_SCHEDULE_GAME_NUMBER_DISAGREE not in v.reason_codes:
        f.append("E5 doubleheader half: a record declaring game_number 1 bound to the entry for "
                 "half 2 and produced %s %s" % (v.disposition, v.reason_codes))
    v = A(record=_rec(EID_DH_G2, "MLB", "SYNTH_KC", "SYNTH_TOR", "2026-08-30T20:07:00Z",
                      CLOSED, 13, 2, fetched=_EVENING, game_number=2),
          now_utc=_EVENING, canonical_schedule=dh, lane=LANE_CANONICAL)
    if v.disposition != ADMIT_FINAL:
        f.append("E5 control: a record declaring the SAME half as its entry was refused (%s %s) "
                 "— the comparison must catch a disagreement, not the field's presence"
                 % (v.disposition, v.reason_codes))

    # ---- A SCHEDULE THAT IS THE RECORD IS NOT A SCHEDULE ------------------------------------
    # Cluster A made the canonical schedule MANDATORY and never made it INDEPENDENT, so
    # admit(record, canonical_schedule=record) reached ADMIT_FINAL / settleable / result_ledger:
    # "a record checked only against itself", rebuilt out of a supplied argument.
    self_bound = _rec(EID_DH_G2, "MLB", "SYNTH_KC", "SYNTH_TOR", "2026-08-30T20:07:00Z",
                      CLOSED, 13, 2, fetched=_EVENING)
    for label, schedule_arg in (("the record itself", self_bound),
                                ("a copy of the record", dict(self_bound)),
                                ("a dict of records", {self_bound["event_id"]: dict(self_bound)})):
        v = A(record=self_bound, now_utc=_EVENING, canonical_schedule=schedule_arg,
              lane=LANE_CANONICAL)
        if v.admitted or v.settleable or REASON_SCHEDULE_IS_THE_RECORD not in v.reason_codes:
            f.append("E6 self-schedule (%s): a record checked only against ITSELF produced "
                     "%s/%s (settleable=%s) %s" % (label, v.disposition, v.admissible_as,
                                                   v.settleable, v.reason_codes))
        if sink_for(v) != SINK_QUARANTINE:
            f.append("E6 routing (%s): a self-bound record routed to %r" % (label, sink_for(v)))
    v = A(record=self_bound, now_utc=_EVENING, canonical_schedule=dh, lane=LANE_CANONICAL)
    if v.disposition != ADMIT_FINAL or not v.settleable:
        f.append("E6 control: the SAME record against an INDEPENDENT slate must admit (%s %s) — "
                 "otherwise the refusal above is a blanket one" % (v.disposition, v.reason_codes))
    if v.detail.get("n_schedule_events") != 2 or not v.detail.get("canonical_schedule_sha256"):
        f.append("E6 audit trail: the verdict does not record the SHAPE of the slate it was "
                 "bound against (%r) — 'schedule_supplied: true' cannot tell a fifteen-game "
                 "slate from a one-entry self-schedule" % (v.detail.get("n_schedule_events"),))

    # ---- A STATUS IS EVIDENCE ONLY IF ITS OWN SOURCE CAN PRODUCE IT -------------------------
    # `status` was an ungrounded caller assertion in the shape `lane` had before cluster B. ESPN
    # exposes no statistics-validation state anywhere in this repo, so ESPN can never say CLOSED.
    espn_sched = index_schedule([
        _entry(EID_WNBA, "SYNTH_MIN", "SYNTH_ATL", "2026-08-30T23:00:00Z", league="WNBA")])
    v = A(record=_rec(EID_WNBA, "WNBA", "SYNTH_MIN", "SYNTH_ATL", "2026-08-30T23:00:00Z",
                      CLOSED, 78, 81, source=PROVIDER_ESPN_SCOREBOARD,
                      fetched="2026-08-31T02:00:00Z"),
          now_utc="2026-08-31T02:00:00Z", canonical_schedule=espn_sched, lane=LANE_CANONICAL)
    if v.admitted or v.settleable or REASON_STATUS_UNREACHABLE_FROM_SOURCE not in v.reason_codes:
        f.append("E7 espn CLOSED: an ESPN-sourced record asserting a VALIDATED status produced "
                 "%s/%s (settleable=%s) %s — the ESPN map reaches no validated state at all"
                 % (v.disposition, v.admissible_as, v.settleable, v.reason_codes))
    # The state ESPN CAN reach still admits, as FINAL_UNVALIDATED: readable, never settleable.
    v = A(record=_rec(EID_WNBA, "WNBA", "SYNTH_MIN", "SYNTH_ATL", "2026-08-30T23:00:00Z",
                      COMPLETE, 78, 81, source=PROVIDER_ESPN_SCOREBOARD,
                      fetched="2026-08-31T02:00:00Z"),
          now_utc="2026-08-31T02:00:00Z", canonical_schedule=espn_sched, lane=LANE_CANONICAL)
    if v.disposition != ADMIT_FINAL or v.admissible_as != ADMISSIBLE_FINAL_UNVALIDATED \
            or v.settleable:
        f.append("E7 control: an ESPN final in the state ESPN CAN report was refused (%s/%s) — "
                 "grounding a status must not become a blanket refusal of the provider"
                 % (v.disposition, v.admissible_as))
    if reachable_statuses_for_source("web_search") is not None:
        f.append("E7 scope: a source with no provider map was given a state list it never "
                 "declared — that is inventing a vocabulary (R1)")
    if reachable_statuses_for_source(PROVIDER_ESPN_SCOREBOARD) & VALIDATED_STATES:
        f.append("E7 map: the ESPN map reaches a VALIDATED state; the docstring says it exposes "
                 "no statistics-validation state anywhere in this repo")

    # ---- CLUSTER N. THE INSTANT IS THE FACT; A CARRIED DATE IS A CLAIM ABOUT IT -------------
    # commit 0bf9399 in one line: an evening tip crosses midnight UTC, and a carried
    # scheduled_date is exactly how a prior day's final gets filed under today.
    if scheduled_date_of({"scheduled_start_utc": "2026-08-31T00:30:00Z",
                          "scheduled_date": "2026-08-31"}) != "2026-08-30":
        f.append("N derivation: scheduled_date_of preferred a carried date over the ET "
                 "derivation from the UTC instant")
    lying = _rec(EID_MIAWSH_PRIOR, "MLB", "SYNTH_MIA", "SYNTH_WSH", "2026-08-29T16:15:00Z",
                 CLOSED, 3, 4, fetched="2026-08-29T19:30:00Z", scheduled_date="2026-08-30")
    if scheduled_date_of(lying) != "2026-08-29":
        f.append("N record: yesterday's game answered today's date (%s)"
                 % scheduled_date_of(lying))
    v = A(record=lying, now_utc=_EVENING, lane=LANE_CANONICAL)
    if v.admitted or REASON_SCHEDULED_DATE_OVERRIDE not in v.reason_codes:
        f.append("N carried date: an 8/29 final carrying scheduled_date 2026-08-30 produced "
                 "%s %s — that is commit 0bf9399" % (v.disposition, v.reason_codes))
    lying_entry = index_schedule([
        _entry(EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, scheduled_date="2026-08-28")])
    v = A(record=_rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9),
          now_utc=_EVENING, canonical_schedule=lying_entry, lane=LANE_CANONICAL)
    if v.disposition != REJECT_SCHEDULE_CONFLICT or \
            REASON_SCHEDULED_DATE_OVERRIDE not in v.reason_codes:
        f.append("N carried date (schedule side): a canonical entry whose carried date "
                 "contradicts its own instant produced %s %s"
                 % (v.disposition, v.reason_codes))

    # ---- SEARCH CONSENSUS: TWO OUTLETS ON ONE WIRE ARE ONE SOURCE ---------------------------
    # OBSERVED at 23:00Z, well past the 18:45Z minimum for a 16:15Z first pitch. Stated rather
    # than defaulted because the SOFT duration rule now reads the observation clock too (round
    # two, cluster M part b): with the default 17:30Z fetch these records are held TOO_SOON, and
    # this block is testing CONSENSUS, not the clock.
    s1 = _rec(EID_MIAWSH, "MLB", "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, CLOSED, 2, 9,
              source="outlet_a", wire_service="wire_x", result_timestamp_utc=_EVENING,
              fetched=_EVENING)
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
                      81, 78, source="web_search", fetched="2026-08-31T01:10:00Z"),
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

    return f


def selftest():
    """Run every fixture, print the named failures, and return True when there are none."""
    f = selftest_failures()
    print(f"{MODULE_ID} selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("  FAIL:", x)
    return not f


# ---------------------------------------------------------------------------------------------
# 12. MUTATION SUITE.  A counter that cannot fail is not a check.
#     Each entry names the DEFECT RESTORED, not a test. Every one must be KILLED by selftest().
#
#     CLUSTER O, 2026-08-30 review. The first version of this suite counted ANY exception as a
#     kill — including a mutant that died at import before a single fixture ran. That is the
#     failure this module's own docstring already records (12/12 KILLED while every mutant died
#     of an AttributeError), rediscovered one layer up: the fix had been applied in
#     test_score_admission.guard_report and not here. A kill now requires a NAMED FAILURE from
#     selftest_failures(), and the entry's fourth element names WHICH failure must fire, so a
#     mutant cannot be credited to collateral damage in an unrelated fixture. Anything else is
#     an ERROR, reported separately and excluded from the tally.
#
#     Entry shape: (name, old_source, new_source, expectation)
#       expectation  a substring that must appear in at least one named failure, OR an exception
#                    type that the mutant must raise. None means "any named failure will do" and
#                    is deliberately not used by anything below.
# ---------------------------------------------------------------------------------------------

MUTANTS = [
    ("a final before first pitch is admitted again (8/30 BOS@NYY, COL@ATL)",
     "    if start_utc is not None and now < start_utc and (claims_score or claims_terminal):",
     "    if False:",
     "F1"),
    ("'complete' counts as validated, so an unvalidated final becomes settleable",
     "VALIDATED_STATES = frozenset({CLOSED})",
     "VALIDATED_STATES = frozenset({CLOSED, COMPLETE})",
     "F6 complete"),
    ("the SEARCH lane may mint a FINAL",
     "    return lane == LANE_SEARCH",
     "    return False",
     "CONSENSUS"),
    ("two corroborating search sources promote the claim to FINAL",
     "        return Verdict(UNVERIFIED, reasons, ADMISSIBLE_CORROBORATED, detail)",
     "        return Verdict(ADMIT_FINAL, reasons, ADMISSIBLE_FINAL, detail)",
     "CONSENSUS"),
    ("the record is never compared against the canonical schedule",
     "    conflicts = _schedule_conflicts(record, entry, lane)",
     "    conflicts = []",
     "CONFLICT"),
    ("the SOFT duration check becomes hard: a canonical terminal status can no longer clear it, "
     "and the rain-shortened game is false-rejected (owner message 1's warning, restored)",
     "    cleared = too_soon and lane == LANE_CANONICAL and status in TERMINAL_STATES",
     "    cleared = False",
     "CLOCK(b)"),
    ("the SEARCH lane may write to the board again (the 8/27 publication path)",
     "    LANE_SEARCH: frozenset({SINK_QUARANTINE}),",
     "    LANE_SEARCH: frozenset({SINK_QUARANTINE, SINK_BOARD}),",
     "S0"),
    ("any string is accepted as an event id",
     '_EVENT_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*:[0-9]{4}:[A-Za-z0-9_.-]+$")',
     '_EVENT_ID_RE = re.compile(r"^.+$")',
     "S1"),
    ("the temporal kill-switch is disarmed (every minimum set to zero)",
     'MIN_DURATION_MINUTES = {"MLB": 150, "NBA": 120, "WNBA": 120, "NFL": 165, "CFB": 180}',
     'MIN_DURATION_MINUTES = {"MLB": 0, "NBA": 0, "WNBA": 0, "NFL": 0, "CFB": 0}',
     "S0"),
    ("outlets sharing one wire feed count as independent witnesses",
     '    return record.get("wire_service") or record.get("source")',
     '    return record.get("source")',
     "CONSENSUS"),
    ("admit stops validating the record, so a score with no status field flows through",
     "    ok_rec, problems = validate_record(record)",
     "    ok_rec, problems = True, []",
     "RULE3"),
    ("the market lane may produce a score",
     "    if lane == LANE_MARKET:",
     "    if False:",
     "LANE"),

    # ---- the five 2026-08-30 review findings, each with the fixture that catches it ---------
    ("CLUSTER A: the no-schedule admission ceiling is removed, so omitting one argument turns "
     "owner rules 1, 2 and 6 off and a self-consistent fabrication settles",
     "    if index_schedule(canonical_schedule) is None:",
     "    if False:",
     "A ceiling"),
    ("CLUSTER B: the declared lane is believed again, so a web_search record relabelled "
     "CANONICAL admits as a settleable FINAL",
     "    if declared_lane != LANE_CANONICAL:",
     "    if True:",
     "B relabelled"),
    ("CLUSTER L: a naive ISO string is read as UTC again, moving an ET first pitch 4-5 hours "
     "earlier so a final admits and settles before the game begins",
     "    return parsed.tzinfo is None",
     "    return False",
     "L naive"),
    ("CLUSTER M: the pre-start invariant consults only the judging clock again, so the 8/30 "
     "records this module exists to refuse admit as soon as they are judged late enough",
     "    if start_utc is not None and fetched_utc is not None and fetched_utc < start_utc \\",
     "    if False and fetched_utc is not None and fetched_utc < start_utc \\",
     "M observation clock"),
    # ---- the round-two re-attack's findings, each with the fixture that catches it ----------
    ("CLUSTER M PART (b): the SOFT duration hold goes back to the judging clock alone, so a "
     "terminal claim OBSERVED inside the impossible window loses the hold by being judged later",
     "    too_soon = judged_too_soon or observed_too_soon",
     "    too_soon = judged_too_soon",
     "M(b) soft clock"),
    ("THE OBSERVATION CLOCK LOSES ITS UPPER BOUND: a record stamped as fetched in 2027 is "
     "judged in 2026 and settles",
     "    if fetched_utc is not None and fetched_utc > now:",
     "    if False:",
     "E3 observation after judgement"),
    ("index_schedule TRUSTS THE DICT KEY again, so an entry filed under another game's event id "
     "answers that id's lookup and the record binds to a different game",
     '            out[own if own not in (None, "") else key] = entry',
     "            out[key] = entry",
     "E4 mis-keyed"),
    ("the binding stops being proved against the schedule entry's OWN identifier, so an entry "
     "that names no event binds a record anyway",
     '    if e_eid in (None, "") or str(e_eid) != str(r_eid):',
     "    if False:",
     "E4 unidentified entry"),
    ("game_number goes back to being carried by both sides and compared by neither, so a record "
     "claiming doubleheader half 1 binds to the entry for half 2",
     "    if r_gn is not None and e_gn is not None and str(r_gn) != str(e_gn):",
     "    if False:",
     "E5 doubleheader half"),
    ("the canonical schedule may be the RECORD again: cluster A's ceiling required a schedule to "
     "be supplied and never required it to be independent",
     "        if is_self:",
     "        if False:",
     "E6 self-schedule"),
    ("record['status'] goes back to being an ungrounded caller assertion, so an ESPN-sourced "
     "record claiming CLOSED settles although the ESPN map reaches no validated state",
     "    if unreachable:",
     "    if False:",
     "E7 espn CLOSED"),

    ("CLUSTER N: a caller-supplied scheduled_date overrides the ET derivation again, so an "
     "8/29 final is filed and served as an 8/30 result (commit 0bf9399)",
     "    return None if start is None else et_date_of(start)",
     "    return str(obj.get('scheduled_date')) if obj.get('scheduled_date') else ("
     "None if start is None else et_date_of(start))",
     "N "),
]

#: CLUSTER O's own check. This mutation is not a defect and is not in MUTANTS: it is a canary
#: that must be classified ERRORED rather than KILLED. A suite that counts crashes as kills
#: reports a perfect score while proving nothing, which is exactly what happened here once
#: already, so the classifier is tested rather than trusted.
ERROR_CANARY = ("the module raises at import, before any fixture runs",
                "UTC = dt.timezone.utc",
                "UTC = dt.timezone.utc + _this_name_does_not_exist")


#: How one mutant ended. KILLED is the only outcome that PROVES anything, and it is the only one
#: that requires a named failure to have fired.
OUTCOME_KILLED = "KILLED"
OUTCOME_SURVIVED = "SURVIVED"
OUTCOME_ERRORED = "ERRORED"
OUTCOME_UNAPPLIED = "UNAPPLIED"
OUTCOME_SELF_TARGETED = "SELF_TARGETED"
OUTCOME_MISDIRECTED = "MISDIRECTED"


def run_mutant(src, body, old, new, expectation=None):
    """(outcome, note) for one source-level mutation. CLUSTER O lives here.

    KILLED requires a NAMED failure from selftest_failures() — and, when the entry declares one,
    the failure that NAMES this defect's own fixture. An exception of any kind, at import or in
    the run, is OUTCOME_ERRORED: the mutant may well be fatal, but a crash is not evidence that a
    fixture watches this guard, and counting it as one is how a suite reports 12/12 while proving
    nothing. An expectation may also be an exception TYPE, for a mutant whose correct behaviour
    IS to raise; then that exact type is a kill and every other type is still an error.
    """
    if old not in src:
        return OUTCOME_UNAPPLIED, "pattern not found in this module's source"
    if old not in body:
        return OUTCOME_SELF_TARGETED, "pattern occurs only inside the MUTANTS list"
    wants_exception = isinstance(expectation, type) and issubclass(expectation, BaseException)
    ns = {"__file__": __file__, "__name__": "mutant"}
    import io as _io, contextlib as _cl
    try:
        with _cl.redirect_stdout(_io.StringIO()):
            exec(compile(src.replace(old, new, 1), "<mutant>", "exec"), ns)
    except BaseException as e:                      # noqa: BLE001 — classification, not handling
        if wants_exception and isinstance(e, expectation):
            return OUTCOME_KILLED, "raised the expected %s at import" % expectation.__name__
        return OUTCOME_ERRORED, "died at import: %s: %s" % (type(e).__name__, e)
    if "selftest_failures" not in ns:
        return OUTCOME_ERRORED, "the mutant module exposes no selftest_failures()"
    try:
        with _cl.redirect_stdout(_io.StringIO()):
            failures = ns["selftest_failures"]()
    except BaseException as e:                      # noqa: BLE001 — classification, not handling
        if wants_exception and isinstance(e, expectation):
            return OUTCOME_KILLED, "raised the expected %s" % expectation.__name__
        return OUTCOME_ERRORED, "unexpected %s from selftest_failures: %s" % (type(e).__name__, e)
    if not isinstance(failures, list):
        return OUTCOME_ERRORED, "selftest_failures returned %s, not a list" % type(failures).__name__
    if not failures:
        return OUTCOME_SURVIVED, "every fixture still passed"
    if wants_exception:
        return OUTCOME_ERRORED, "expected %s, got %d named failures" % (expectation.__name__,
                                                                       len(failures))
    if expectation and not any(expectation in x for x in failures):
        return OUTCOME_MISDIRECTED, ("killed by %r, but no fixture naming %r fired — the guard "
                                     "this mutant removes is watched by a DIFFERENT fixture than "
                                     "the one claimed" % (failures[0][:90], expectation))
    return OUTCOME_KILLED, failures[0][:120]


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
    tally = {k: 0 for k in (OUTCOME_KILLED, OUTCOME_ERRORED, OUTCOME_SURVIVED,
                            OUTCOME_UNAPPLIED, OUTCOME_SELF_TARGETED, OUTCOME_MISDIRECTED)}
    for entry in MUTANTS:
        name, old, new = entry[0], entry[1], entry[2]
        expectation = entry[3] if len(entry) > 3 else None
        outcome, note = run_mutant(src, body, old, new, expectation)
        tally[outcome] += 1
        print("  %-14s %s" % (outcome, name))
        if outcome != OUTCOME_KILLED:
            print("                 -> %s" % note)

    # CLUSTER O's classifier, tested rather than trusted: a mutant that dies at import must be
    # reported as an ERROR and must not reach the kill tally.
    canary_name, canary_old, canary_new = ERROR_CANARY
    canary_outcome, canary_note = run_mutant(src, body, canary_old, canary_new)
    canary_ok = canary_outcome == OUTCOME_ERRORED
    print("  %-14s CANARY %s" % ("OK" if canary_ok else "BROKEN", canary_name))
    if not canary_ok:
        print("                 -> classified %s (%s); a suite that calls an import crash a KILL "
              "counts crashes as proof" % (canary_outcome, canary_note))

    n = len(MUTANTS)
    print("score_admission mutation suite: %d killed, %d errored, %d survived (of %d)"
          % (tally[OUTCOME_KILLED], tally[OUTCOME_ERRORED], tally[OUTCOME_SURVIVED], n))
    extra = {k: v for k, v in tally.items()
             if v and k in (OUTCOME_UNAPPLIED, OUTCOME_SELF_TARGETED, OUTCOME_MISDIRECTED)}
    if extra:
        print("  not applied as written: %s" % extra)
    if tally[OUTCOME_KILLED] != n:
        print("  — A MUTANT THAT IS NOT KILLED BY A NAMED FIXTURE PROVES NOTHING. An ERRORED "
              "mutant is not a kill: it crashed, which no fixture was watching for.")
    return tally[OUTCOME_KILLED] == n and canary_ok


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
