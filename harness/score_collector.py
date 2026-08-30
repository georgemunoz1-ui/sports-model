#!/usr/bin/env python3
"""SCORE COLLECTOR — stages 1 and 2 of the owner's four-stage architecture.

    approved source API  ->  game binding + status validation  ->  immutable verified snapshot
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^      ->  Claude analysis / card
    this module                                                         (verified_snapshot.py)

THE INCIDENT. 2026-08-30 13:30 ET a web search returned three confident MLB finals:

    "Nationals 9, Marlins 2"   MIA@WSH first pitch 12:15 ET -> 75 minutes into a ~170 minute game
    "Yankees 1, Red Sox 0"     BOS@NYY first pitch 13:35 ET -> HAD NOT STARTED
    "Braves 6, Rockies 4"      COL@ATL first pitch 13:35 ET -> HAD NOT STARTED

All three were refused by hand. On 2026-08-27 the same class of summary WAS published, as five
fabricated finals. Nothing in code prevented either, because nothing in code was between the
sentence and the card. This module is one half of what is now between them: it is the only path
by which a score enters from an approved feed, and it hands every record to
score_admission.admit() rather than judging any of them itself.

WHAT THIS MODULE DOES NOT DO, on purpose:

  - It does not decide admissibility. Every normalized record goes through
    score_admission.admit(); the collector only ROUTES the verdict. The routing line is mutant M9
    below, precisely because "the collector quietly decided" is the failure mode that ends with a
    fabricated final on a board.
  - It does not fetch by default. DEFAULT_GET is feed_mlb_statsapi._default_get, which REFUSES
    with AcquisitionDisabled. Injecting `get=` is the only way to acquire. When nothing is
    injected the canonical lane is DOWN and the answer is an explicit NO_DATA_LANE_DOWN verdict —
    never an empty list, because an empty list reads as "no games today" and on 8/30 that
    ambiguity is exactly what invited a search backfill.
  - It does not write. snapshot_payload() builds the body; verified_snapshot.write_snapshot owns
    the writing, and this module does not own that signature.
  - It does not define a fourth AcquisitionDisabled. feed_mlb_statsapi's class is re-exported.
    Three unrelated classes of that name already exist (acquisition_adapters, feed_espn,
    feed_mlb_statsapi) and test_egress_discipline only survives that by comparing type NAMES.

FOUR DECISIONS THAT NEEDED EVIDENCE, AND WHAT THE EVIDENCE SAID.

1. TEAM IDS. The owner's normalized record names away_team_id / home_team_id, not abbreviations.
   StatsAPI carries teams.<side>.team.id. The only live StatsAPI payload in this repo
   (data/feeds/fixtures/2026-08-28/mlb_statsapi_schedule_LIVE_capture.json, 15 games) was trimmed
   to the fields feed_mlb_statsapi.parse_schedule reads, and parse_schedule reads NAMES — so that
   capture has no team ids at all. When the id is absent this collector emits the record with
   away_team_id None and keeps the team NAME as evidence in collector_problems. It does not fall
   back to the name (R1: a name identifies, it never binds — that is the whole 8/27
   PRIOR_DATE_SERIES_JOIN lesson in one line). Consequence, asserted in the selftest: all 15 games
   of the live capture are REFUSED. That is the correct answer for a payload with no identities,
   and it is why the capture is exercised here rather than admired.

2. DOUBLEHEADERS. gameNumber IS evidenced (feed_mlb_statsapi.parse_schedule reads it; 20 payload
   occurrences in data/, every one of them the value 1). doubleHeader is NOT evidenced: its only
   appearance repo-wide is inside a quoted external-auditor claim string in
   docs/audits/2026-08-14_v19_audit_intake.json. So identity keys on gamePk ALONE
   (_identity_key), game_number is carried as the contract's optional field, and doubleheader_flag
   is read defensively with .get() and is None on every payload this repo has ever seen. Two games
   sharing (away, home) on one date is EXPECTED and must not collapse; mutant M1 restores the
   collapse and the doubleheader fixture kills it.

3. RESCHEDULES. The repo evidences rescheduleDate, rescheduleGameDate, rescheduledFrom and
   rescheduledFromDate (data/mlb/schedule/2026-07-17_espn_verify.json, PIT@CLE gamePk 824414,
   statusCode DD, reason "Air Quality"). It evidences NO successor-id key: `rescheduledTo` has
   zero hits repo-wide, and that same record shows StatsAPI RETAINING gamePk 824414 for the
   makeup. So this collector never synthesises a successor event id from a reschedule DATE — that
   would be minting an identifier out of a timestamp. A postponed game emits REBIND_REQUIRED and
   carries the reschedule dates as data. When the supplied canonical schedule names a successor
   (score_admission's rescheduled_to_event_id), the rebinding is recorded as data instead
   (REBIND_TARGET_RECORDED) and admit() refuses the old id with POSTPONED_REBIND_REQUIRED.

4. A KNOWN GAP, stated rather than papered over. score_admission maps exactly the four MLB
   statusCodes this repo has witnessed — F(20 observations), DD(1), S(1) — plus "O", which is
   declared in feed_mlb_statsapi.FINAL_STATUS_CODES and observed nowhere. There is therefore NO
   evidenced in-progress statusCode, so a genuinely live StatsAPI game normalizes to UNKNOWN and
   is refused as non-final. This collector CANNOT currently produce ADMIT_IN_PROGRESS from
   StatsAPI. The remedy is to capture a live in-progress payload and extend
   score_admission.MLB_STATUSCODE_TO_STATUS there — not to guess a code here, and not to add a
   second status map in this file, which is how a vocabulary forks.

ABSENT STATUS vs UNKNOWN STATUS. These are different facts and are kept apart. A game whose
payload carries no statusCode gets status None, so admit() answers SOURCE_STATUS_MISSING — owner
rule 3, and the exact shape of the five 8/27 finals, which were prose and had no status field at
all. A game whose statusCode is present but unmapped gets UNKNOWN. Collapsing the two would hide
rule 3's own case behind rule 8's.

DETERMINISM. No wall clock is read anywhere in this module: now_utc and fetched_utc are supplied
by the caller. feed_mlb_statsapi.fetch_schedule is deliberately NOT used even though it wraps the
same URL and fetcher — it stamps fetched_utc off the wall clock and discards the team ids the
owner's record requires. selftest S0 scans this file's own source for wall-clock and network call
sites, with the needles built by concatenation so the check cannot match itself.

EGRESS REGISTRATION. This module is deliberately NOT added to test_egress_discipline.GUARDED. It
owns no fetcher: DEFAULT_GET *is* feed_mlb_statsapi._default_get, which is already registered
there. Registering this module too would put a fetcher behind two flags, and GUARDED's mutant
(flip ALLOW_DIRECT_HTTP to True and require the refusal to stop) would report MUTANT SURVIVED
because feed_mlb_statsapi's own flag would still be refusing. ALLOW_DIRECT_HTTP is declared here
anyway so the posture is stated, and S0 asserts BOTH flags are False and that DEFAULT_GET is
still the refusing function and not something swapped in later.

REMAINING WIRING, none of which is in this file, all of which is required before this gate is
anything more than a file that passes when you run it by hand:
  * data/registry/module_manifest.json — add `"harness/score_collector.py": "score_collector",` in
    sorted position with one-space indent. Until then module_manifest.py --audit reports
    MODULE_NOT_IN_MANIFEST and healthcheck 6c fails. (verified_snapshot.py is in the same state.)
  * harness/healthcheck.py:237-289 — add "score_collector" to the selftest tuple with a dated
    comment, and a numbered --gate/--mutants block; this module answers all three flags and exits
    0 today. Unwired, it is exactly the wnba_refresh_espn shape: documented, implemented, and
    never executed. A rule this gate does not run is a rule that has stopped running.

Usage: python3 harness/score_collector.py [--selftest] [--mutants] [--gate]
"""
from __future__ import annotations

MODULE_ID = "score_collector"

import datetime as dt
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import score_admission as sa                      # noqa: E402  THE contract; nothing retyped
import feed_mlb_statsapi                          # noqa: E402  schedule_url + the refusing get
from feed_espn import et_date_of, parse_utc       # noqa: E402  ET derivation lives in ONE place

#: feed_mlb_statsapi's class, re-exported. NOT a fourth class of the same name (see docstring).
from feed_mlb_statsapi import AcquisitionDisabled  # noqa: E402,F401

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Declared so the posture is stated. The flag that GATES the fetch is feed_mlb_statsapi's, since
#: that module owns the only fetcher on this path. S0 asserts both are False.
ALLOW_DIRECT_HTTP = False

#: THE REFUSING DEFAULT. Not a copy, not a wrapper: the same function object
#: test_egress_discipline.GUARDED already covers. Mutant M4 replaces it with something that
#: returns bytes, i.e. "the default became a live call", and the lane-down fixture kills it.
DEFAULT_GET = feed_mlb_statsapi._default_get

#: "mlb_statsapi" — bound to the contract's provider constant, never retyped as a literal.
SOURCE = sa.PROVIDER_MLB_STATSAPI
LEAGUE = "MLB"

#: The event-id space for this collector: "mlb:<season>:<gamePk>" (the owner's example is
#: mlb:2026:824643). This is NOT result_binding_gate's two-part "MLB_GAMEPK:824643". They are
#: different id spaces; never join across them and never strip a prefix to a bare int.
ID_SPACE = "mlb"

#: Sources this deployment could not reach on 2026-08-30. StatsAPI itself answered — the LIVE
#: capture's own note records ESPN returning HTTP 403 from this egress while StatsAPI worked — so
#: this list is carried as lane DETAIL, never as the canonical lane's reason.
KNOWN_EGRESS_BLOCKED = ("espn.com", "covers.com")


# ---------------------------------------------------------------------------------------------
# 1. LANE STATE VOCABULARY.  Small, and total over score_admission.LANES.
# ---------------------------------------------------------------------------------------------

LANE_STATE_UP = "UP"
LANE_STATE_DOWN = "DOWN"
LANE_STATE_QUARANTINE_ONLY = "UP_QUARANTINE_ONLY"
LANE_STATE_NOT_A_SCORE_SOURCE = "NOT_A_SCORE_SOURCE"
LANE_STATES = (LANE_STATE_UP, LANE_STATE_DOWN, LANE_STATE_QUARANTINE_ONLY,
               LANE_STATE_NOT_A_SCORE_SOURCE)


# ---------------------------------------------------------------------------------------------
# 2. COLLECTOR REASON CODES.
#
#    These are PAYLOAD-level findings, not verdicts. A verdict is score_admission's word and only
#    admit() may say it. Every code here is registered in COLLECT_REASON_MEANING and every one is
#    produced by a fixture in selftest(); there is no exemption list, because a code nothing can
#    fire is a code nobody has ever watched fire.
# ---------------------------------------------------------------------------------------------

COLLECT_GAME_NOT_A_MAPPING = "PAYLOAD_GAME_NOT_A_MAPPING"
COLLECT_TEAM_ID_ABSENT = "PROVIDER_TEAM_ID_ABSENT_IN_PAYLOAD"
COLLECT_EVENT_ID_UNCONSTRUCTIBLE = "EVENT_ID_UNCONSTRUCTIBLE"
COLLECT_DUPLICATE_EVENT_ID = "DUPLICATE_EVENT_ID_IN_PAYLOAD"
COLLECT_STATUS_CODE_ABSENT = "PROVIDER_STATUS_CODE_ABSENT"
COLLECT_STATUS_CODE_UNMAPPED = "PROVIDER_STATUS_CODE_UNMAPPED"
COLLECT_START_UNPARSEABLE = "GAME_DATE_UNPARSEABLE"
COLLECT_SEASON_DERIVED = "SEASON_DERIVED_FROM_ET_CALENDAR_YEAR"
COLLECT_SEASON_DISAGREES = "SEASON_DISAGREES_WITH_ET_CALENDAR_YEAR"
COLLECT_OFFICIAL_DATE_DISAGREES = "OFFICIAL_DATE_DISAGREES_WITH_ET_DATE"
COLLECT_SCORE_DROPPED_NOT_PLAYED = "SCORE_DROPPED_GAME_NOT_PLAYED"
COLLECT_REBIND_REQUIRED = "REBIND_REQUIRED"
COLLECT_REBIND_TARGET_RECORDED = "REBIND_TARGET_RECORDED"
COLLECT_CLOCK_SKEW = "FETCHED_AT_IS_AFTER_NOW"
COLLECT_HASH_DOES_NOT_COVER_RAW = "CONTENT_HASH_DOES_NOT_COVER_RAW_RESPONSE"

COLLECT_REASON_MEANING = {
    COLLECT_GAME_NOT_A_MAPPING:
        "a games[] entry is not a dict. It is still normalized into a refusable record rather "
        "than skipped: a dropped game is invisible, and invisible is how a slate silently shrinks",
    COLLECT_TEAM_ID_ABSENT:
        "the payload carries no teams.<side>.team.id. The team NAME is retained as evidence and "
        "is NOT used as an identity — a name identifies, it never binds (owner rule 1)",
    COLLECT_EVENT_ID_UNCONSTRUCTIBLE:
        "no gamePk, a placeholder gamePk, or no season to compose one with, so no event id "
        "exists. The record is emitted with event_id None and admit() refuses it as unbound",
    COLLECT_DUPLICATE_EVENT_ID:
        "two games in ONE payload claim the same event id. Neither is deduplicated away; both are "
        "kept and the collision is reported, because picking one would be picking blind",
    COLLECT_STATUS_CODE_ABSENT:
        "status.statusCode is absent, so the record's status is None (not UNKNOWN) and admit() "
        "answers SOURCE_STATUS_MISSING — owner rule 3, the shape of the five 8/27 finals",
    COLLECT_STATUS_CODE_UNMAPPED:
        "statusCode is present but score_admission maps it to UNKNOWN, because this repo has "
        "witnessed only F, DD and S in payloads. UNKNOWN is non-final (owner rule 8)",
    COLLECT_START_UNPARSEABLE:
        "gameDate could not be parsed as an instant, so there is no start, no ET date and no "
        "season; nothing is defaulted",
    COLLECT_SEASON_DERIVED:
        "the payload carried no season, so the event id's season is the year of the ET CALENDAR "
        "date (derived by feed_espn.et_date_of, never sliced off a UTC string). Valid for MLB, "
        "whose season does not cross a calendar year; this collector is MLB-only",
    COLLECT_SEASON_DISAGREES:
        "the payload's season and the ET calendar year disagree. The PAYLOAD wins, because the "
        "provider owns its own id space, and the disagreement is surfaced rather than resolved "
        "silently (the feed_sweep precedent)",
    COLLECT_OFFICIAL_DATE_DISAGREES:
        "officialDate differs from the ET date derived from gameDate. feed_mlb_statsapi's "
        "docstring promised this conflict would be surfaced and nothing ever read the field; the "
        "one real postponement in this repo (PIT@CLE 2026-07-17) is exactly this shape",
    COLLECT_SCORE_DROPPED_NOT_PLAYED:
        "a postponed game arrived carrying a score. The score is removed from the record and the "
        "dropped values are kept here as evidence: a game that was not played has no score",
    COLLECT_REBIND_REQUIRED:
        "a postponed game whose successor event id is not evidenced anywhere — not in the payload "
        "(no such key exists in this repo) and not in the supplied schedule. Re-collect the date "
        "the game moved to and bind to the id the provider publishes then. Nothing is guessed",
    COLLECT_REBIND_TARGET_RECORDED:
        "the supplied canonical schedule names rescheduled_to_event_id for this event, so the "
        "rebinding is recorded as data; admit() refuses the old id with POSTPONED_REBIND_REQUIRED",
    COLLECT_CLOCK_SKEW:
        "the fetch instant is later than the judgement instant. One of the two stamps is not what "
        "it says it is, and a snapshot's age cannot be trusted until that is resolved",
    COLLECT_HASH_DOES_NOT_COVER_RAW:
        "raw_response_sha256 does not equal the sha256 of the retained raw response. Owner rule 7 "
        "is 'preserve the raw response AND content hash'; a hash that covers other bytes preserves "
        "nothing",
}

COLLECT_REASON_CODES = tuple(sorted(COLLECT_REASON_MEANING))

#: Keys this collector adds to score_admission's normalized record. ADDITIONS only — never a
#: rename of a contract field, and score_admission reads none of them. S0 asserts the set is
#: exactly this and that it is disjoint from RECORD_FIELDS.
COLLECTOR_EXTRA_FIELDS = ("date_et", "official_date", "provider_status_code",
                          "provider_status_detailed", "doubleheader_flag", "raw_hash_basis",
                          "source_url", "collector_problems")

#: Where the content hash came from.
HASH_BASIS_RAW_BYTES = "RAW_RESPONSE_BYTES"
HASH_BASIS_CANONICAL_JSON = "CANONICAL_JSON_REBUILD"


# ---------------------------------------------------------------------------------------------
# 3. SMALL HELPERS.
# ---------------------------------------------------------------------------------------------

def _instant(value):
    """Any instant -> tz-aware UTC datetime, or None when unparseable. Never a guess.

    Mirrors score_admission._utc so the two modules cannot disagree about what an instant is.
    Strings go through feed_espn.parse_utc; ET derivation and instant parsing both live there.
    """
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    try:
        return parse_utc(value)
    except Exception:
        return None


def _iso(value):
    """Any instant -> 'YYYY-MM-DDTHH:MM:SSZ', or None. Mirrors score_admission's rendering."""
    d = _instant(value)
    return None if d is None else d.isoformat().replace("+00:00", "Z")


def _sha256_of(blob):
    """sha256 of bytes, or of a str's utf-8 encoding. GENERATED; never typed."""
    if isinstance(blob, bytes):
        return hashlib.sha256(blob).hexdigest()
    return hashlib.sha256(str(blob).encode("utf-8")).hexdigest()


def _canonical_json(payload):
    """A stable re-serialisation, used ONLY when no raw response was retained.

    The resulting hash is labelled HASH_BASIS_CANONICAL_JSON so nobody later reads it as a hash of
    the provider's bytes. It is not the same claim and it is not labelled as if it were.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _identity_key(record):
    """THE identity of a game: its provider event id, and nothing else.

    Team names are not an identity. A doubleheader repeats them within one day and a three-game
    series repeats them across three; the 8/27 contamination was a matchup join wearing an id's
    clothes (result_binding_gate.PRIOR_DATE_SERIES_JOIN). Mutant M1 restores the matchup key and
    the doubleheader fixture kills it.
    """
    return record.get("event_id")


def _team_id_and_name(side):
    """(team id, team name) from a StatsAPI teams.<side> object. Absence is None, never the name."""
    team = ((side or {}).get("team") or {}) if isinstance(side, dict) else {}
    return team.get("id"), team.get("name")


# ---------------------------------------------------------------------------------------------
# 4. NORMALIZATION.  StatsAPI payload -> the owner's normalized record.
# ---------------------------------------------------------------------------------------------

def _normalize_game(g, *, fetched_utc, now_utc, raw_sha256, raw_hash_basis, source_url):
    """One StatsAPI schedule game -> one normalized record. Never raises, never drops, never fills.

    Every field the payload does not supply is None with a collector_problems entry saying so.
    R1 in one function: an absence is declared, not papered over.
    """
    problems = []
    if not isinstance(g, dict):
        problems.append({"code": COLLECT_GAME_NOT_A_MAPPING, "type": type(g).__name__,
                         "value": repr(g)[:120]})
        g = {}

    # ---- status. ABSENT (None) and UNMAPPED (UNKNOWN) are different facts; see the docstring.
    status_obj = g.get("status")
    if not isinstance(status_obj, dict):
        status_obj = {}
    code = status_obj.get("statusCode")
    detailed = status_obj.get("detailedState")
    if code in (None, ""):
        problems.append({"code": COLLECT_STATUS_CODE_ABSENT, "detailed_state": detailed,
                         "detail": "status None, not UNKNOWN: the provider said nothing"})
        status = None
    else:
        status = sa.normalize_status(code, sa.PROVIDER_MLB_STATSAPI)
        if status == sa.UNKNOWN:
            problems.append({"code": COLLECT_STATUS_CODE_UNMAPPED, "status_code": code,
                             "detailed_state": detailed,
                             "detail": "score_admission maps only the codes this repo has "
                                       "witnessed; an unmapped code is non-final"})

    # ---- the instant, and the ET calendar date derived from it (never sliced off the UTC string)
    start = _instant(g.get("gameDate"))
    if g.get("gameDate") is not None and start is None:
        problems.append({"code": COLLECT_START_UNPARSEABLE, "game_date": g.get("gameDate")})
    date_et = et_date_of(start) if start is not None else None
    official_date = g.get("officialDate")
    if official_date and date_et and str(official_date) != date_et:
        problems.append({"code": COLLECT_OFFICIAL_DATE_DISAGREES, "official_date": official_date,
                         "date_et": date_et,
                         "detail": "surfaced, not resolved: neither field is overwritten"})

    # ---- season, and the event id composed from it
    payload_season = str(g.get("season") or "").strip() or None
    # The YEAR OF THE ET CALENDAR DATE. date_et is already ET (feed_espn.et_date_of); taking its
    # first four characters is reading a field, not slicing a UTC instant.
    et_year = date_et[:4] if date_et else None
    if payload_season and et_year and payload_season != et_year:
        problems.append({"code": COLLECT_SEASON_DISAGREES, "payload_season": payload_season,
                         "et_calendar_year": et_year, "used": payload_season})
    season = payload_season or et_year
    if not payload_season and season:
        problems.append({"code": COLLECT_SEASON_DERIVED, "season": season, "date_et": date_et})

    game_pk = g.get("gamePk")
    event_id = None
    if game_pk is None or season is None:
        problems.append({"code": COLLECT_EVENT_ID_UNCONSTRUCTIBLE, "game_pk": game_pk,
                         "season": season,
                         "detail": "no gamePk and/or no season: nothing to compose an id from"})
    else:
        try:
            event_id = sa.event_id_for(ID_SPACE, season, game_pk)
        except ValueError as e:
            problems.append({"code": COLLECT_EVENT_ID_UNCONSTRUCTIBLE, "game_pk": game_pk,
                             "season": season, "detail": str(e)})

    # ---- teams. The id or nothing; the name is evidence, never an identity.
    teams = g.get("teams") if isinstance(g.get("teams"), dict) else {}
    away_side, home_side = teams.get("away"), teams.get("home")
    away_id, away_name = _team_id_and_name(away_side)
    home_id, home_name = _team_id_and_name(home_side)
    for side, tid, name in (("away", away_id, away_name), ("home", home_id, home_name)):
        if tid is None:
            problems.append({"code": COLLECT_TEAM_ID_ABSENT, "side": side, "team_name": name,
                             "detail": "name retained as evidence; it is not used to bind"})

    away_score = (away_side or {}).get("score") if isinstance(away_side, dict) else None
    home_score = (home_side or {}).get("score") if isinstance(home_side, dict) else None
    # No int() coercion. ESPN returns scores as STRINGS and the normalized record does not;
    # coercing here would erase the tell that score_admission.validate_record exists to catch.

    # ---- a game that was not played has no score.
    if status == sa.POSTPONED and (away_score is not None or home_score is not None):
        problems.append({"code": COLLECT_SCORE_DROPPED_NOT_PLAYED, "status": status,
                         "dropped_away_score": away_score, "dropped_home_score": home_score})
        away_score = home_score = None
    # NOTE the deliberate asymmetry: a score under SCHEDULED or UNKNOWN is NOT dropped. That is a
    # provider contradiction and admit() must see it, as SCORE_WITHOUT_TERMINAL_STATUS.

    if status == sa.POSTPONED:
        problems.append({"code": COLLECT_REBIND_REQUIRED, "event_id": event_id,
                         "reschedule_date": g.get("rescheduleDate"),
                         "reschedule_game_date": g.get("rescheduleGameDate"),
                         "rescheduled_from": g.get("rescheduledFrom"),
                         "reason": status_obj.get("reason"),
                         "detail": "no successor-id key exists in any payload this repo has seen; "
                                   "a date is not an identifier and is not turned into one"})

    record = {
        # ---- the owner's fields, exactly ----
        "event_id": event_id,
        "league": LEAGUE,
        "away_team_id": away_id,
        "home_team_id": home_id,
        "scheduled_start_utc": _iso(start),
        "status": status,
        "away_score": away_score,
        "home_score": home_score,
        # GENERATED from the status, never typed. Mutant M6 types it and the "O" fixture kills it.
        "terminal_verified": sa.terminal_verified_for(status),
        "source": SOURCE,
        "source_fetched_at_utc": _iso(fetched_utc),
        "raw_response_sha256": raw_sha256,
        # ---- contract-optional ----
        "game_number": g.get("gameNumber"),
        # ---- collector additions (COLLECTOR_EXTRA_FIELDS) ----
        "date_et": date_et,
        "official_date": official_date,
        "provider_status_code": code,
        "provider_status_detailed": detailed,
        # Read defensively: the repo evidences no doubleHeader key in any payload, only a quoted
        # auditor claim. Identity does not depend on it and never will.
        "doubleheader_flag": g.get("doubleHeader"),
        "raw_hash_basis": raw_hash_basis,
        "source_url": source_url,
        "collector_problems": problems,
    }

    fetched_at, now_at = _instant(fetched_utc), _instant(now_utc)
    if fetched_at is not None and now_at is not None and fetched_at > now_at:
        problems.append({"code": COLLECT_CLOCK_SKEW, "fetched_at": _iso(fetched_at),
                         "now": _iso(now_at)})
    return record


def normalize_statsapi(payload, *, fetched_utc, now_utc, raw_sha256=None, raw_hash_basis=None,
                       source_url=None):
    """StatsAPI schedule payload -> a list of normalized records, in payload order.

    One record per games[] entry, ALWAYS: nothing is dropped and nothing is deduplicated. Two
    games sharing a matchup is a doubleheader, which is expected; two games sharing an event id is
    a defect, which is reported (COLLECT_DUPLICATE_EVENT_ID) and still not deduplicated, because
    choosing between two records that claim one identity is choosing blind.

    raw_sha256 should be the sha256 of the bytes the provider actually returned (owner rule 7).
    When it is not supplied, a hash of a canonical re-serialisation is generated and LABELLED
    HASH_BASIS_CANONICAL_JSON, so it is never read as a hash of the provider's bytes.
    """
    if raw_sha256 is None:
        raw_sha256 = _sha256_of(_canonical_json(payload if isinstance(payload, dict) else {}))
        raw_hash_basis = raw_hash_basis or HASH_BASIS_CANONICAL_JSON
    raw_hash_basis = raw_hash_basis or HASH_BASIS_RAW_BYTES

    games = []
    if isinstance(payload, dict):
        for day in payload.get("dates") or []:
            if isinstance(day, dict):
                games.extend(day.get("games") or [])

    records = []
    for g in games:
        record = _normalize_game(g, fetched_utc=fetched_utc, now_utc=now_utc,
                                 raw_sha256=raw_sha256, raw_hash_basis=raw_hash_basis,
                                 source_url=source_url)
        # NEVER conditional. A game the collector cannot normalize is refused downstream by the
        # contract, not made to disappear here. Mutant M12 restores the silent drop.
        records.append(record)

    seen = {}
    for r in records:
        key = _identity_key(r)
        if key is None:
            continue
        seen.setdefault(key, []).append(r)
    for key, group in seen.items():
        if len(group) > 1:
            for r in group:
                r["collector_problems"].append(
                    {"code": COLLECT_DUPLICATE_EVENT_ID, "identity": key, "n": len(group),
                     "detail": "kept, not deduplicated"})
            # When the colliding records also DISAGREE, the contract already owns a name for it:
            # one content hash covering two different score sets is regression fixture 7 in
            # payload form. Borrowed, not retyped, so the two modules cannot fork on the wording.
            for other in group[1:]:
                conflict, prob = sa.content_hash_conflict(group[0], other)
                if conflict:
                    other["collector_problems"].append(
                        dict(prob, detail="two games in one payload claim one event id and "
                                          "disagree on content"))
    return records


def schedule_entries_from_records(records):
    """Normalized records -> canonical schedule entries for score_admission.admit().

    FOR A LATER COLLECTION, NOT THIS ONE. Binding tonight's finals against a schedule built from
    tonight's own payload proves nothing: a record always agrees with itself. The honest use is
    the morning slate snapshot binding the evening results snapshot, which is what the selftest
    does. collect_mlb never calls this on its own output.
    """
    entries = []
    for r in records:
        if not r.get("event_id"):
            continue
        entries.append({"event_id": r["event_id"], "league": r.get("league"),
                        "away_team_id": r.get("away_team_id"),
                        "home_team_id": r.get("home_team_id"),
                        "scheduled_start_utc": r.get("scheduled_start_utc"),
                        "status": r.get("status"), "game_number": r.get("game_number")})
    return sa.index_schedule(entries)


# ---------------------------------------------------------------------------------------------
# 5. LANE STATUS.
# ---------------------------------------------------------------------------------------------

def lane_status(league, *, get=None):
    """Which lanes are up, which are down, and WHY — as data, not as a shrug.

    The canonical lane is DOWN whenever no fetcher is injected, because the default refuses. A
    caller that reads this and still calls collect_mlb receives NO_DATA_LANE_DOWN rather than an
    empty list: on 2026-08-30 "no rows came back" and "the feed is unreachable" looked identical
    from the outside, and that ambiguity is what a search backfill was offered to fill.
    """
    lg = sa.normalize_league(league)
    if lg is None:
        raise ValueError("UNSUPPORTED_LEAGUE: %r (known: %s)" % (league, list(sa.LEAGUES)))

    canonical_up = get is not None
    lanes = {
        sa.LANE_CANONICAL: {
            "lane": sa.LANE_CANONICAL,
            "trust": sa.LANE_TRUST[sa.LANE_CANONICAL],
            "state": LANE_STATE_UP if canonical_up else LANE_STATE_DOWN,
            "reason": None if canonical_up else "NO_ADAPTER_INJECTED",
            "sinks": sorted(sa.LANE_WRITE_TARGETS[sa.LANE_CANONICAL]),
            "detail": {
                "source": SOURCE,
                "fetcher": "injected" if canonical_up else "DEFAULT_GET (refuses)",
                "allow_direct_http": ALLOW_DIRECT_HTTP,
                "known_egress_blocked": list(KNOWN_EGRESS_BLOCKED),
                "note": "espn.com and covers.com were EGRESS_BLOCKED for this deployment on "
                        "2026-08-30; statsapi.mlb.com answered, per the LIVE capture's own note. "
                        "Blocked sources are detail, not this lane's reason.",
            },
        },
        sa.LANE_SEARCH: {
            "lane": sa.LANE_SEARCH,
            "trust": sa.LANE_TRUST[sa.LANE_SEARCH],
            "state": LANE_STATE_QUARANTINE_ONLY,
            "reason": "SEARCH_WRITES_QUARANTINE_ONLY",
            "sinks": sorted(sa.LANE_WRITE_TARGETS[sa.LANE_SEARCH]),
            "detail": {"note": "reachable is not the same as usable: a search claim can never "
                               "mint a FINAL, with or without consensus"},
        },
        sa.LANE_MARKET: {
            "lane": sa.LANE_MARKET,
            "trust": sa.LANE_TRUST[sa.LANE_MARKET],
            "state": LANE_STATE_NOT_A_SCORE_SOURCE,
            "reason": sa.REASON_MARKET_LANE_NOT_A_SCORE_SOURCE,
            "sinks": sorted(sa.LANE_WRITE_TARGETS[sa.LANE_MARKET]),
            "detail": {"note": "prices are never predictive features and never results"},
        },
    }
    return {"schema": "ops.score_collector.lane_status.v1", "league": lg,
            "canonical_up": canonical_up, "lanes": lanes,
            "rule": "a down canonical lane yields NO_DATA_LANE_DOWN, never a search backfill and "
                    "never a silent empty slate"}


# ---------------------------------------------------------------------------------------------
# 6. THE RESULT.
# ---------------------------------------------------------------------------------------------

class CollectResult:
    """What collect_mlb returns.

    admitted and quarantined are SEPARATE lists and there is no combined view, so a caller cannot
    mix them by accident. The object is deliberately not iterable: `for x in result` raises,
    because the choice of which list you are reading has to be visible in the caller's own source.

    A plain class, not a dataclass. With `from __future__ import annotations` a dataclass resolves
    its annotations through sys.modules[cls.__module__], which does not exist when this file is
    exec'd into a throwaway namespace — which is exactly what mutation_suite() does. That defect
    made score_admission's first mutation run report 12/12 killed while every mutant was dying at
    import; it is not being repeated here.
    """

    __slots__ = ("date_et", "league", "lane", "now_utc", "source", "source_url", "raw_text",
                 "raw_sha256", "raw_hash_basis", "fetched_utc", "normalized", "admitted",
                 "quarantined", "lanes", "no_data", "problems", "counters")

    def __init__(self, *, date_et, league, now_utc, lanes, source_url=None, raw_text=None,
                 raw_sha256=None, raw_hash_basis=None, fetched_utc=None, normalized=None,
                 admitted=None, quarantined=None, no_data=None, problems=None):
        self.date_et = date_et
        self.league = league
        self.lane = sa.LANE_CANONICAL
        self.now_utc = _iso(now_utc)
        self.source = SOURCE
        self.source_url = source_url
        self.raw_text = raw_text
        self.raw_sha256 = raw_sha256
        self.raw_hash_basis = raw_hash_basis
        self.fetched_utc = _iso(fetched_utc)
        #: The pre-verdict normalization, retained as evidence. A caller reading scores from here
        #: has walked around the gate; read .admitted.
        self.normalized = list(normalized or [])
        self.admitted = list(admitted or [])
        self.quarantined = list(quarantined or [])
        self.lanes = lanes
        self.no_data = no_data
        self.problems = list(problems or [])

        # Owner rule 7, checked rather than asserted: the hash must cover the bytes it names.
        if self.raw_text is not None and self.raw_sha256 is not None \
                and self.raw_hash_basis == HASH_BASIS_RAW_BYTES:
            if _sha256_of(self.raw_text) != self.raw_sha256:
                self.problems.append({"code": COLLECT_HASH_DOES_NOT_COVER_RAW,
                                      "declared": self.raw_sha256,
                                      "recomputed": _sha256_of(self.raw_text)})

        # COUNTERS ARE GENERATED HERE, never typed by a caller.
        dispositions = {}
        for entry in self.admitted + self.quarantined:
            d = entry["verdict"].disposition
            dispositions[d] = dispositions.get(d, 0) + 1
        self.counters = {
            "GAMES_IN_PAYLOAD": len(self.normalized),
            "RECORDS_NORMALIZED": len(self.normalized),
            "DISTINCT_IDENTITIES": len({_identity_key(r) for r in self.normalized
                                        if _identity_key(r) is not None}),
            "ADMITTED": len(self.admitted),
            "QUARANTINED": len(self.quarantined),
            "COLLECTOR_PROBLEMS": len(self.problems) + sum(
                len(r.get("collector_problems") or []) for r in self.normalized),
            "DISPOSITIONS": dict(sorted(dispositions.items())),
        }

    def __iter__(self):
        raise TypeError(
            "a CollectResult is not iterable on purpose: iterate .admitted or .quarantined "
            "explicitly, so which one you read is visible in your own source")

    def __repr__(self):
        return "CollectResult(%s %s admitted=%d quarantined=%d no_data=%s)" % (
            self.league, self.date_et, len(self.admitted), len(self.quarantined),
            self.no_data.disposition if self.no_data else None)

    @property
    def lane_down(self):
        return self.no_data is not None

    def to_dict(self):
        return {
            "schema": "ops.score_collector.result.v1",
            "league": self.league, "date_et": self.date_et, "lane": self.lane,
            "now_utc": self.now_utc, "source": self.source, "source_url": self.source_url,
            "source_fetched_at_utc": self.fetched_utc,
            "raw_response_sha256": self.raw_sha256, "raw_hash_basis": self.raw_hash_basis,
            "counters": dict(self.counters),
            "lane_status": self.lanes,
            "no_data": self.no_data.to_dict() if self.no_data else None,
            "admitted": [{"record": e["record"], "verdict": e["verdict"].to_dict(),
                          "sink": e["sink"]} for e in self.admitted],
            "quarantined": [{"record": e["record"], "verdict": e["verdict"].to_dict(),
                             "sink": e["sink"]} for e in self.quarantined],
            "problems": list(self.problems),
        }


# ---------------------------------------------------------------------------------------------
# 7. THE CANONICAL LANE.
# ---------------------------------------------------------------------------------------------

def collect_mlb(date_et, *, now_utc, get=None, canonical_schedule=None):
    """Acquire one MLB slate, normalize it, and hand every record to score_admission.admit().

    get   an approved fetcher, called as get(url) — the feed layer's calling convention
          (feed_espn / feed_mlb_statsapi pass one positional; acquisition_adapters passes a
          timeout keyword, so a fetcher shared across both layers needs `def f(url, timeout=None)`).
          Omitting it does not fall back to the network: the canonical lane reports DOWN and the
          answer is NO_DATA_LANE_DOWN.

    canonical_schedule  a schedule acquired EARLIER and independently (see
          schedule_entries_from_records). None is permitted and every verdict then carries
          CANONICAL_SCHEDULE_NOT_SUPPLIED, so the absence of the cross-check is visible in the
          artifact rather than assumed away.
    """
    lanes = lane_status(LEAGUE, get=get)
    url = feed_mlb_statsapi.schedule_url(date_et)

    if not lanes["canonical_up"]:
        # PROVE the refusal instead of asserting it: call the default and record what it did. A
        # deployment where this stops raising has a live default, which is the defect
        # test_egress_discipline exists for.
        try:
            DEFAULT_GET(url)
            refusal = "NONE"
        except Exception as e:                                    # noqa: BLE001 — name, not type
            refusal = type(e).__name__
        v = sa.lane_down(LEAGUE, sa.LANE_CANONICAL,
                         reason=lanes["lanes"][sa.LANE_CANONICAL]["reason"],
                         blocked_sources=KNOWN_EGRESS_BLOCKED, date_et=date_et,
                         detail={"source": SOURCE, "source_url": url,
                                 "default_fetcher_refusal": refusal})
        return CollectResult(date_et=date_et, league=LEAGUE, now_utc=now_utc, lanes=lanes,
                             source_url=url, no_data=v)

    try:
        raw = get(url)
    except Exception as e:                                        # noqa: BLE001 — name, not type
        # Three unrelated AcquisitionDisabled classes exist in this repo; test_egress_discipline
        # compares by NAME for the same reason.
        name = type(e).__name__
        reason = "NO_ADAPTER_INJECTED" if name == "AcquisitionDisabled" else "PROVIDER_ERROR"
        v = sa.lane_down(LEAGUE, sa.LANE_CANONICAL, reason=reason,
                         blocked_sources=KNOWN_EGRESS_BLOCKED, date_et=date_et,
                         detail={"source": SOURCE, "source_url": url,
                                 "exception": name, "message": str(e)[:300]})
        return CollectResult(date_et=date_et, league=LEAGUE, now_utc=now_utc, lanes=lanes,
                             source_url=url, no_data=v)

    raw_text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    raw_sha256 = _sha256_of(raw)
    try:
        payload = json.loads(raw_text)
    except Exception as e:                                        # noqa: BLE001
        v = sa.lane_down(LEAGUE, sa.LANE_CANONICAL, reason="PROVIDER_ERROR",
                         blocked_sources=KNOWN_EGRESS_BLOCKED, date_et=date_et,
                         detail={"source": SOURCE, "source_url": url,
                                 "exception": type(e).__name__, "message": str(e)[:300],
                                 "raw_response_sha256": raw_sha256,
                                 "note": "the bytes were retained and hashed; they are not JSON"})
        return CollectResult(date_et=date_et, league=LEAGUE, now_utc=now_utc, lanes=lanes,
                             source_url=url, raw_text=raw_text, raw_sha256=raw_sha256,
                             raw_hash_basis=HASH_BASIS_RAW_BYTES, no_data=v)

    # The fetch instant is the caller's instant. This module reads no clock (see DETERMINISM).
    fetched_utc = now_utc
    records = normalize_statsapi(payload, fetched_utc=fetched_utc, now_utc=now_utc,
                                 raw_sha256=raw_sha256, raw_hash_basis=HASH_BASIS_RAW_BYTES,
                                 source_url=url)

    # IDENTITY COLLISIONS ARE REPORTED, NOT RESOLVED, AND NOT ALLOWED TO CHANGE A VERDICT.
    # admit() is the only thing in this repo permitted to say whether a score may be believed, so
    # two payload games claiming one event id still each get their own verdict. The collision is
    # raised to result level (and therefore into snapshot_payload) because the place where "one
    # key holds one record" is actually enforceable is the append-only snapshot store, not here.
    collisions = {}
    for r in records:
        for p in r["collector_problems"]:
            if p["code"] == COLLECT_DUPLICATE_EVENT_ID:
                collisions[p["identity"]] = p["n"]
    problems = [{"code": COLLECT_DUPLICATE_EVENT_ID, "identity": k, "n": n,
                 "detail": "one payload, %d games claiming this identity. Neither was dropped; "
                           "the snapshot store must refuse to hold two records under one key" % n}
                for k, n in sorted(collisions.items())]

    schedule_index = sa.index_schedule(canonical_schedule)
    admitted, quarantined = [], []
    for record in records:
        if record.get("status") == sa.POSTPONED and schedule_index:
            entry = schedule_index.get(record.get("event_id")) or {}
            successor = entry.get("rescheduled_to_event_id")
            if successor:
                record["collector_problems"].append(
                    {"code": COLLECT_REBIND_TARGET_RECORDED, "rebind_to": successor,
                     "from_event_id": record.get("event_id")})

        # THE CONTRACT DECIDES. The collector's only job on this line is to ask.
        verdict = sa.admit(record, now_utc=now_utc, canonical_schedule=canonical_schedule,
                           lane=sa.LANE_CANONICAL)
        sink = sa.sink_for(verdict)
        entry = {"record": record, "verdict": verdict, "sink": sink}
        if verdict.admitted:
            admitted.append(entry)
        else:
            quarantined.append(entry)

    return CollectResult(date_et=date_et, league=LEAGUE, now_utc=now_utc, lanes=lanes,
                         source_url=url, raw_text=raw_text, raw_sha256=raw_sha256,
                         raw_hash_basis=HASH_BASIS_RAW_BYTES, fetched_utc=fetched_utc,
                         normalized=records, admitted=admitted, quarantined=quarantined,
                         problems=problems)


# ---------------------------------------------------------------------------------------------
# 8. THE SEARCH LANE.  Structurally incapable of admitting.
# ---------------------------------------------------------------------------------------------

#: Hard-coded, and deliberately NOT a parameter of quarantine_search_claim: there is no code path
#: by which a caller can tell that function it is canonical. Mutant M3 rewrites this constant, and
#: the post-filter below turns the rewrite into a LaneViolation rather than a published final.
_SEARCH_LANE = sa.LANE_SEARCH


def _quarantine_only(verdict):
    """The ONLY exit quarantine_search_claim has.

    Two things must both hold or nothing is returned: the verdict does not admit, and it routes to
    quarantine. A search claim that got past either of those did not come from the search lane,
    whatever the caller believes, and the right answer is to raise rather than to hand back
    something that looks like a result.
    """
    if verdict.admitted or sa.sink_for(verdict) != sa.SINK_QUARANTINE:
        raise sa.LaneViolation(
            "%s: the search lane produced %s/%s routing to %r. Search snippets IDENTIFY and never "
            "BIND; this exit exists so that a lane mix-up is an exception, not a published score."
            % (sa.REASON_SEARCH_LANE_CANNOT_MINT_FINAL, verdict.disposition,
               verdict.admissible_as, sa.sink_for(verdict)))
    return verdict


#: What a search claim may carry. Anything else is ignored; nothing is invented to fill a gap.
SEARCH_CLAIM_FIELDS = ("event_id", "league", "away_team_id", "home_team_id",
                       "scheduled_start_utc", "status", "provider", "provider_status",
                       "away_score", "home_score", "source", "wire_service",
                       "result_timestamp_utc", "raw_text", "raw_response_sha256",
                       "source_fetched_at_utc")


def _search_record(claim, *, now_utc):
    """A search claim -> the normalized record shape, with nothing filled in that was not given.

    In particular: no event id is invented from team names, and no content hash is invented. A
    snippet with no retained bytes has no raw_response_sha256, so admit() refuses it on owner
    rule 7 — which is the correct answer, because an unretained page cannot be re-checked.
    """
    if not isinstance(claim, dict):
        return claim                      # admit() answers RECORD_NOT_A_MAPPING; that is the 8/30
                                          # snippet in its actual shape: a sentence.
    status = claim.get("status")
    if status is None and claim.get("provider_status") is not None:
        status = sa.normalize_status(claim.get("provider_status"), claim.get("provider"))
    sha = claim.get("raw_response_sha256")
    if sha is None and claim.get("raw_text") is not None:
        sha = _sha256_of(claim["raw_text"])          # generated from bytes we actually hold
    record = {
        "event_id": claim.get("event_id"),
        "league": claim.get("league"),
        "away_team_id": claim.get("away_team_id"),
        "home_team_id": claim.get("home_team_id"),
        "scheduled_start_utc": claim.get("scheduled_start_utc"),
        "status": status,
        "away_score": claim.get("away_score"),
        "home_score": claim.get("home_score"),
        "terminal_verified": sa.terminal_verified_for(status) if status in sa.STATUSES else False,
        "source": claim.get("source") or "web_search",
        "source_fetched_at_utc": claim.get("source_fetched_at_utc") or _iso(now_utc),
        "raw_response_sha256": sha,
    }
    for optional in ("result_timestamp_utc", "wire_service"):
        if claim.get(optional) is not None:
            record[optional] = claim[optional]
    return record


def quarantine_search_claim(claim, *, now_utc, canonical_schedule, corroborations=0):
    """The SEARCH lane. Returns a Verdict that can never be ADMIT_FINAL.

    Not "can never" by an if-statement in this function: the lane is a module constant rather than
    a parameter, so nothing a caller passes can make this canonical; score_admission's own
    _search_lane_may_not_mint_final caps a corroborated search claim at
    IDENTIFIED_UNCONFIRMED_CORROBORATED; and _quarantine_only is the single return path, refusing
    anything that admits or that routes off quarantine. Two outlets running one wire are ONE
    source, so consensus raises the grade and never the disposition.
    """
    record = _search_record(claim, now_utc=now_utc)
    verdict = sa.admit(record, now_utc=now_utc, canonical_schedule=canonical_schedule,
                       lane=_SEARCH_LANE, corroborations=corroborations)
    return _quarantine_only(verdict)


# ---------------------------------------------------------------------------------------------
# 9. THE SNAPSHOT BODY.  Built here, written by verified_snapshot.
# ---------------------------------------------------------------------------------------------

def payload_id_for(result):
    """The raw payload's id inside a snapshot. One slate, one provider, one id: deterministic, so
    re-collecting the same slate lands on the same id instead of accumulating near-duplicates."""
    return "%s_schedule_%s" % (result.source, result.date_et)


def admission_envelopes(result):
    """(record, verdict) pairs for verified_snapshot.write_snapshot, admitted AND quarantined.

    Both sides are handed over deliberately: the store keeps the refused records too, and a
    refusal nobody kept is a refusal nobody can audit. The store sorts them by their own verdicts,
    which is why the verdict travels WITH the record and is never re-derived downstream.

    The two key names are not invented here — verified_snapshot.admission_envelope() constructs
    the same pair, and the selftest asserts the two agree so the shape cannot fork.
    """
    return [{"record": e["record"], "verdict": e["verdict"]}
            for e in result.admitted + result.quarantined]


def snapshot_payload(result):
    """The immutable snapshot body, JSON-clean, for verified_snapshot.write_snapshot.

    This module does not write it. R6 (append-only, never rewrite a committed artifact) and the
    snapshot's identity are that module's rules and its signature is its own; the call is

        verified_snapshot.write_snapshot(
            admission_envelopes(result), league=result.league, date_et=result.date_et,
            source=result.source, raw_payloads=snapshot_payload(result)["raw_payloads"],
            now_utc=<the write instant>)
    """
    body = result.to_dict()
    body["schema"] = "ops.score_collector.snapshot.v1"
    # Owner rule 7: the bytes, retained, with the instant they were fetched. The sha is not
    # supplied as a claim — the store generates its own and a caller-typed one is only ever
    # checked against it.
    body["raw_payloads"] = [{"payload_id": payload_id_for(result), "raw_text": result.raw_text,
                             "fetched_at_utc": result.fetched_utc, "source": result.source,
                             "url": result.source_url}] if result.raw_text is not None else []
    body["tool_surface"] = list(sa.ANALYSIS_TOOL_SURFACE)
    body["rule"] = ("the analysis layer reads this through get_verified_score / "
                    "get_verified_scores / get_source_manifest and mutates nothing")
    return body


# ---------------------------------------------------------------------------------------------
# 10. verified_snapshot — imported if it exists, and NAMED as skipped if it does not.
#     Another module is being built against the same contract in parallel. A selftest that quietly
#     passes when its subject is absent is itself a defect (precedent: wnba_refresh_espn returned
#     True with no artifact), so absence is printed, not swallowed.
# ---------------------------------------------------------------------------------------------

VERIFIED_SNAPSHOT_NAMES = ("write_snapshot", "get_verified_score", "get_verified_scores",
                           "get_source_manifest")

try:
    import verified_snapshot as vs                 # noqa: E402
    VERIFIED_SNAPSHOT_ABSENCE = None
except Exception as _e:                            # noqa: BLE001 — any import failure, named below
    vs = None
    VERIFIED_SNAPSHOT_ABSENCE = "%s: %s" % (type(_e).__name__, _e)


# =============================================================================== fixtures

_NOW_1330ET = "2026-08-30T17:30:00Z"     # the instant of the incident, 13:30 ET
_START_1335ET = "2026-08-30T17:35:00Z"   # BOS@NYY and COL@ATL first pitch
_START_1215ET = "2026-08-30T16:15:00Z"   # MIA@WSH first pitch
_EVENING = "2026-08-31T02:00:00Z"        # 22:00 ET on 8/30: past every window used below

LIVE_CAPTURE_PATH = os.path.join(
    REPO_ROOT, "data", "feeds", "fixtures", "2026-08-28",
    "mlb_statsapi_schedule_LIVE_capture.json")

#: gamePks used by the fixtures below. None of them is a plausible-looking integer, because no
#: gamePk was captured for any of the 8/30 games before the claims were refused, and inventing one
#: is the exact defect this module exists to stop (R1). The three incident ids are score_admission's
#: own EID_* constants, taken apart rather than retyped, so the two modules test one fixture.
PK_BOSNYY = sa.parse_event_id(sa.EID_BOSNYY)[2]
PK_COLATL = sa.parse_event_id(sa.EID_COLATL)[2]
PK_MIAWSH = sa.parse_event_id(sa.EID_MIAWSH)[2]
PK_DH_G1 = sa.parse_event_id(sa.EID_DH_G1)[2]
PK_DH_G2 = sa.parse_event_id(sa.EID_DH_G2)[2]
PK_PPD = sa.parse_event_id(sa.EID_PPD_OLD)[2]
PK_NO_STATUS = "SYNTHETIC-UNVERIFIED-NOSTATUS"
PK_UNMAPPED = "SYNTHETIC-UNVERIFIED-UNMAPPEDCODE"
PK_SEASON_DRIFT = "SYNTHETIC-UNVERIFIED-SEASONDRIFT"
PK_BAD_DATE = "SYNTHETIC-UNVERIFIED-BADGAMEDATE"

FIXTURE_PROVENANCE = {
    PK_BOSNYY: "SYNTHETIC_UNVERIFIED — BOS@NYY 2026-08-30 13:35 ET. Reuses score_admission's "
               "EID_BOSNYY provider id so both modules bind one fixture. No real gamePk was ever "
               "captured for this game: the claim was refused before acquisition.",
    PK_COLATL: "SYNTHETIC_UNVERIFIED — COL@ATL 2026-08-30 13:35 ET, same refusal, same absence.",
    PK_MIAWSH: "SYNTHETIC_UNVERIFIED — MIA@WSH 2026-08-30 12:15 ET, the 75-minutes-in claim.",
    PK_DH_G1: "SYNTHETIC_UNVERIFIED — doubleheader half 1. The repo holds NO doubleheader payload "
              "(every observed gameNumber is 1), so both halves are constructed.",
    PK_DH_G2: "SYNTHETIC_UNVERIFIED — doubleheader half 2: the half team names cannot select.",
    PK_PPD: "SYNTHETIC_UNVERIFIED — a postponement modelled field-for-field on the only one this "
            "repo evidences (PIT@CLE 2026-07-17, statusCode DD, codedGameState D, reason 'Air "
            "Quality', officialDate already advanced to the makeup date, rescheduleDate and "
            "rescheduleGameDate present, NO successor id anywhere).",
    PK_NO_STATUS: "SYNTHETIC_UNVERIFIED — a game with no status object at all: owner rule 3, and "
                  "the shape of the five 8/27 finals, which were prose.",
    PK_UNMAPPED: "SYNTHETIC_UNVERIFIED — statusCode 'I'. This repo has witnessed only F, DD and S "
                 "in payloads, so 'I' maps to UNKNOWN and refuses. This is the KNOWN GAP named in "
                 "the module docstring, exercised rather than described.",
    PK_SEASON_DRIFT: "SYNTHETIC_UNVERIFIED — a payload season that disagrees with the ET calendar "
                     "year. No repo payload carries a season key at all.",
    PK_BAD_DATE: "SYNTHETIC_UNVERIFIED — an unparseable gameDate.",
}


def _game(pk, away_id, home_id, game_date, status_code=None, away_score=None, home_score=None,
          away_name=None, home_name=None, **extra):
    """A StatsAPI-SHAPED schedule game. Shaped from the LIVE capture's own key set."""
    g = {"gameDate": game_date,
         "teams": {"away": {"team": {"id": away_id, "name": away_name}, "score": away_score},
                   "home": {"team": {"id": home_id, "name": home_name}, "score": home_score}},
         "gameNumber": 1}
    if pk is not None:
        g["gamePk"] = pk
    if status_code is not None:
        g["status"] = {"statusCode": status_code,
                       "detailedState": {"F": "Final", "O": "Game Over", "DD": "Postponed",
                                         "S": "Scheduled", "I": "In Progress"}.get(status_code,
                                                                                   "Unknown")}
    g.update(extra)
    return g


def _payload(games, date="2026-08-30"):
    return {"dates": [{"date": date, "games": games}]}


def incident_payload_0830():
    """The 8/30 claims as a StatsAPI-SHAPED payload.

    SYNTHETIC and labelled: no such payload was ever captured. It exists to answer a question the
    incident raised — what if the CANONICAL feed had made the same claim? — and the answer must be
    that a final before first pitch still refuses, because a provider asserting one is either
    buggy or pointed at the wrong game, and both of those must refuse.
    """
    return _payload([
        _game(PK_BOSNYY, "SYNTH_BOS", "SYNTH_NYY", _START_1335ET, "F", 0, 1,
              "Boston Red Sox", "New York Yankees"),
        _game(PK_COLATL, "SYNTH_COL", "SYNTH_ATL", _START_1335ET, "F", 4, 6,
              "Colorado Rockies", "Atlanta Braves"),
        _game(PK_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, "F", 2, 9,
              "Miami Marlins", "Washington Nationals"),
    ])


def doubleheader_payload():
    """Two gamePks, one matchup, one date. Expected, and it must not collapse."""
    return _payload([
        dict(_game(PK_DH_G1, "SYNTH_KC", "SYNTH_TOR", "2026-08-30T17:07:00Z", "F", 3, 1,
                   "Kansas City Royals", "Toronto Blue Jays"), gameNumber=1),
        dict(_game(PK_DH_G2, "SYNTH_KC", "SYNTH_TOR", "2026-08-30T20:07:00Z", "F", 13, 2,
                   "Kansas City Royals", "Toronto Blue Jays"), gameNumber=2),
    ])


def postponed_payload():
    """The 2026-07-17 PIT@CLE shape, transposed to 8/30. Carries a score, which must be dropped."""
    return _payload([
        _game(PK_PPD, "SYNTH_PIT", "SYNTH_CLE", "2026-08-30T17:10:00Z", "DD", 0, 0,
              "Pittsburgh Pirates", "Cleveland Guardians",
              officialDate="2026-08-31",
              rescheduleDate="2026-08-31T17:10:00Z", rescheduleGameDate="2026-08-31"),
    ])


def complete_not_closed_payload():
    """statusCode 'O'. Declared in feed_mlb_statsapi.FINAL_STATUS_CODES, observed in no payload."""
    return _payload([
        _game(PK_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, "O", 2, 9,
              "Miami Marlins", "Washington Nationals"),
    ])


def malformed_payload():
    """Every way a game can fail to identify itself, in one slate."""
    return _payload([
        _game(PK_NO_STATUS, "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, None, 9, 2,
              "Miami Marlins", "Washington Nationals"),
        _game(PK_UNMAPPED, "SYNTH_COL", "SYNTH_ATL", _START_1335ET, "I", 1, 0,
              "Colorado Rockies", "Atlanta Braves"),
        _game(None, "SYNTH_BOS", "SYNTH_NYY", _START_1335ET, "F", 0, 1,
              "Boston Red Sox", "New York Yankees"),
        _game(0, "SYNTH_SEA", "SYNTH_TOR", _START_1335ET, "F", 1, 2,
              "Seattle Mariners", "Toronto Blue Jays"),
        _game(PK_BAD_DATE, "SYNTH_TEX", "SYNTH_MIL", "not-a-date", "F", 1, 2,
              "Texas Rangers", "Milwaukee Brewers"),
        _game(PK_SEASON_DRIFT, "SYNTH_PIT", "SYNTH_STL", "2026-08-30T23:15:00Z", "F", 1, 2,
              "Pittsburgh Pirates", "St. Louis Cardinals", season="2025"),
        _game(PK_DH_G1, "SYNTH_KC", "SYNTH_TOR", "2026-08-30T17:07:00Z", "F", 3, 1,
              "Kansas City Royals", "Toronto Blue Jays"),
        _game(PK_DH_G1, "SYNTH_KC", "SYNTH_TOR", "2026-08-30T17:07:00Z", "F", 4, 1,
              "Kansas City Royals", "Toronto Blue Jays"),
        "Nationals 9, Marlins 2",
    ])


def _stub_get(text, seen=None):
    """An injected fetcher, called the way the feed layer calls one: get(url)."""
    def _get(url, timeout=None):
        if seen is not None:
            seen.append(url)
        return text
    return _get


# =============================================================================== selftest

def selftest():
    """Fixtures named for the incident they answer, not for a test number."""
    f = []
    skipped = []
    codes_seen = set()

    def SEARCH(claim, **kw):
        """Every search-lane call in this selftest goes through here.

        A mutant that points quarantine_search_claim at the canonical lane makes _quarantine_only
        raise, and an exception aborts the run before any fixture can name what went wrong.
        score_admission's own first mutation run reported 12/12 killed while every mutant was
        dying at import; a kill that names nothing is not evidence.
        """
        try:
            return quarantine_search_claim(claim, **kw)
        except sa.LaneViolation as e:
            f.append("SEARCH: quarantine_search_claim raised LaneViolation — the lane it used "
                     "is not SEARCH (%s)" % e)
            return sa.Verdict(sa.UNVERIFIED, [sa.REASON_LANE_UNKNOWN], None,
                              {"lane": sa.LANE_SEARCH})

    def note(records_or_result):
        """Collect every collector code any fixture produced, for the coverage check."""
        if isinstance(records_or_result, CollectResult):
            for p in records_or_result.problems:
                codes_seen.add(p["code"])
            recs = records_or_result.normalized
        else:
            recs = records_or_result
        for r in recs:
            if isinstance(r, dict):
                for p in r.get("collector_problems") or []:
                    codes_seen.add(p["code"])

    # ---- S0. POSTURE, VOCABULARY, AND THE CLAIMS THIS FILE MAKES ABOUT ITSELF ---------------
    if MODULE_ID != os.path.basename(__file__)[:-3]:
        f.append("S0: MODULE_ID %r does not name this file" % MODULE_ID)
    if ALLOW_DIRECT_HTTP is not False or feed_mlb_statsapi.ALLOW_DIRECT_HTTP is not False:
        f.append("S0: a direct-HTTP flag is not False (this=%r, feed=%r)"
                 % (ALLOW_DIRECT_HTTP, feed_mlb_statsapi.ALLOW_DIRECT_HTTP))
    if DEFAULT_GET is not feed_mlb_statsapi._default_get:
        f.append("S0: DEFAULT_GET is no longer feed_mlb_statsapi's refusing fetcher — a live "
                 "default could now be sitting behind a flag that says False")
    try:
        DEFAULT_GET("https://example.invalid/schedule")
        f.append("S0: the default fetcher returned instead of refusing")
    except Exception as e:                                        # noqa: BLE001
        if type(e).__name__ != "AcquisitionDisabled":
            f.append("S0: the default fetcher raised %s, not AcquisitionDisabled — a network "
                     "error is not a refusal" % type(e).__name__)
    # The no-I/O and no-wall-clock claims, checked rather than asserted. Needles are built by
    # concatenation so this scan cannot match itself.
    needles = ["requests" + ".get", "url" + "open", "http" + ".client", "socket" + ".socket",
               "urllib" + ".request", "datetime" + ".now", "time" + ".time", "utcnow" + "("]
    own = open(__file__).read()
    hits = [n for n in needles if n in own]
    if hits:
        f.append("S0: this module claims no I/O and no wall clock, but its source contains %s"
                 % hits)
    missing_meaning = sorted(v for k, v in sorted(globals().items())
                             if k.startswith("COLLECT_") and isinstance(v, str)
                             and v not in COLLECT_REASON_MEANING)
    if missing_meaning:
        f.append("S0: collector codes with no COLLECT_REASON_MEANING entry: %s" % missing_meaning)
    if set(COLLECTOR_EXTRA_FIELDS) & set(sa.RECORD_FIELDS):
        f.append("S0: a collector extra field shadows a contract field: %s"
                 % sorted(set(COLLECTOR_EXTRA_FIELDS) & set(sa.RECORD_FIELDS)))
    if ID_SPACE + ":" in "MLB_GAMEPK:" or ID_SPACE.upper() == "MLB_GAMEPK":
        f.append("S0: the event-id space collided with result_binding_gate's MLB_GAMEPK space")
    if "write_snapshot" in sa.ANALYSIS_TOOL_SURFACE:
        f.append("S0: a WRITE appeared on the read-only analysis tool surface")
    for name in ("get_verified_score", "get_verified_scores", "get_source_manifest"):
        if name not in sa.ANALYSIS_TOOL_SURFACE:
            f.append("S0: %s is missing from ANALYSIS_TOOL_SURFACE" % name)
    for bad in sa.FORBIDDEN_DIRECT_MUTATIONS:
        try:
            sa.assert_tool_allowed(bad)
            f.append("S0: %r was accepted as an analysis tool" % bad)
        except sa.LaneViolation:
            pass

    # ---- LANE STATUS. A DOWN LANE IS NOT AN EMPTY SLATE -------------------------------------
    ls = lane_status("mlb")
    if set(ls["lanes"]) != set(sa.LANES):
        f.append("LANES: lane_status is not total over score_admission.LANES")
    if ls["canonical_up"] or ls["lanes"][sa.LANE_CANONICAL]["state"] != LANE_STATE_DOWN \
            or ls["lanes"][sa.LANE_CANONICAL]["reason"] != "NO_ADAPTER_INJECTED":
        f.append("LANES: with no fetcher injected the canonical lane reported %r/%r"
                 % (ls["lanes"][sa.LANE_CANONICAL]["state"],
                    ls["lanes"][sa.LANE_CANONICAL]["reason"]))
    if ls["lanes"][sa.LANE_SEARCH]["sinks"] != [sa.SINK_QUARANTINE]:
        f.append("LANES: the search lane advertises a sink other than quarantine: %s"
                 % ls["lanes"][sa.LANE_SEARCH]["sinks"])
    if ls["lanes"][sa.LANE_MARKET]["state"] != LANE_STATE_NOT_A_SCORE_SOURCE:
        f.append("LANES: the market lane was offered as a score source")
    if not lane_status("MLB", get=_stub_get("{}"))["canonical_up"]:
        f.append("LANES: an injected fetcher did not bring the canonical lane up")
    try:
        lane_status("KBO")
        f.append("LANES: an unsupported league was given a lane status instead of a refusal")
    except ValueError:
        pass

    # collect_mlb with nothing injected: NO_DATA, and the refusal is PROVEN, not asserted.
    down = collect_mlb("2026-08-30", now_utc=_NOW_1330ET)
    if not down.lane_down or down.no_data.disposition != sa.NO_DATA_LANE_DOWN:
        f.append("LANE_DOWN: an uninjected collect produced %r instead of NO_DATA_LANE_DOWN"
                 % (down.no_data.disposition if down.no_data else None))
    if down.admitted or down.quarantined or down.normalized:
        f.append("LANE_DOWN: a down lane produced records (%d admitted, %d quarantined)"
                 % (len(down.admitted), len(down.quarantined)))
    if down.no_data.detail.get("default_fetcher_refusal") != "AcquisitionDisabled":
        f.append("LANE_DOWN: the default fetcher did not refuse (%r) — the default is live"
                 % down.no_data.detail.get("default_fetcher_refusal"))
    if down.no_data.detail.get("search_backfill_permitted") is not False:
        f.append("LANE_DOWN: the no-data verdict did not refuse a search backfill")
    if down.source_url != feed_mlb_statsapi.schedule_url("2026-08-30"):
        f.append("LANE_DOWN: the url did not come from feed_mlb_statsapi.schedule_url")

    # a fetcher that raises something that is NOT a refusal is a provider error, not a refusal
    def _boom(url, timeout=None):
        raise RuntimeError("connection reset")
    err = collect_mlb("2026-08-30", now_utc=_NOW_1330ET, get=_boom)
    if not err.lane_down or err.no_data.detail.get("reason") != "PROVIDER_ERROR":
        f.append("LANE_DOWN: a transport failure was not reported as PROVIDER_ERROR")
    junk = collect_mlb("2026-08-30", now_utc=_NOW_1330ET, get=_stub_get("<html>403</html>"))
    if not junk.lane_down or junk.raw_sha256 is None:
        f.append("LANE_DOWN: non-JSON bytes were not retained and hashed before refusing")

    # An EMPTY slate that was actually fetched is NOT a down lane. The two must be distinguishable.
    empty = collect_mlb("2026-08-30", now_utc=_NOW_1330ET,
                        get=_stub_get(json.dumps({"dates": []})))
    if empty.lane_down or empty.counters["GAMES_IN_PAYLOAD"] != 0:
        f.append("EMPTY: a fetched empty slate was confused with a down lane")

    # ---- FIXTURE 1. A FINAL FOR A GAME THAT HAS NOT STARTED ---------------------------------
    seen_urls = []
    sched = sa.incident_schedule_0830()
    inc = collect_mlb("2026-08-30", now_utc=_NOW_1330ET, canonical_schedule=sched,
                      get=_stub_get(json.dumps(incident_payload_0830()), seen_urls))
    note(inc)
    if seen_urls != [feed_mlb_statsapi.schedule_url("2026-08-30")]:
        f.append("F1: the collector did not fetch feed_mlb_statsapi.schedule_url (%s)" % seen_urls)
    by_id = {e["record"]["event_id"]: e for e in inc.admitted + inc.quarantined}
    for label, eid in (("BOS@NYY", sa.EID_BOSNYY), ("COL@ATL", sa.EID_COLATL)):
        e = by_id.get(eid)
        if e is None:
            f.append("F1 %s: the game vanished from the result entirely" % label)
        elif e["verdict"].disposition != sa.REJECT_PRESTART_OR_UNBOUND or \
                sa.REASON_PRESTART_FINAL_IMPOSSIBLE not in e["verdict"].reason_codes:
            f.append("F1 %s: a final before first pitch produced %s %s"
                     % (label, e["verdict"].disposition, e["verdict"].reason_codes))
        elif e["sink"] != sa.SINK_QUARANTINE:
            f.append("F1 %s: a pre-start final routed to %r" % (label, e["sink"]))
    if any(e["record"]["event_id"] in (sa.EID_BOSNYY, sa.EID_COLATL) for e in inc.admitted):
        f.append("F1: a pre-start final reached the admitted list")

    # ---- FIXTURE 2. A LIVE GAME LABELLED FINAL ----------------------------------------------
    # MIA@WSH, 75 minutes into a game that needs ~170. THE SPLIT CLOCK RULE IS VISIBLE HERE, and
    # the asymmetry is the decision, not an accident: a CANONICAL terminal status clears the SOFT
    # minimum-duration hold (else every rain-shortened game is false-rejected — owner message 1's
    # warning), while the SEARCH lane can never clear it. The 8/30 claim was a SEARCH claim.
    mia = by_id.get(sa.EID_MIAWSH)
    if mia is None or mia["verdict"].disposition != sa.ADMIT_FINAL or \
            sa.REASON_MIN_DURATION_CLEARED not in mia["verdict"].reason_codes:
        f.append("F2 canonical: a canonical terminal status inside the duration window did not "
                 "clear the SOFT hold (%s)" % (mia["verdict"].reason_codes if mia else None))
    search_mia = SEARCH(
        {"event_id": sa.EID_MIAWSH, "league": "MLB", "away_team_id": "SYNTH_MIA",
         "home_team_id": "SYNTH_WSH", "scheduled_start_utc": _START_1215ET,
         "status": sa.CLOSED, "away_score": 2, "home_score": 9, "source": "web_search",
         "raw_text": "Nationals 9, Marlins 2"},
        now_utc=_NOW_1330ET, canonical_schedule=None)
    if search_mia.disposition != sa.UNVERIFIED_TOO_SOON or \
            sa.REASON_SEARCH_CANNOT_CLEAR_MIN_DURATION not in search_mia.reason_codes:
        f.append("F2 search: the 75-minutes-in search claim produced %s %s"
                 % (search_mia.disposition, search_mia.reason_codes))
    bound_mia = SEARCH(
        {"event_id": sa.EID_MIAWSH, "league": "MLB", "away_team_id": "SYNTH_MIA",
         "home_team_id": "SYNTH_WSH", "scheduled_start_utc": _START_1215ET,
         "status": sa.CLOSED, "away_score": 2, "home_score": 9, "source": "web_search",
         "raw_text": "Nationals 9, Marlins 2"},
        now_utc=_NOW_1330ET, canonical_schedule=sched)
    if bound_mia.disposition != sa.REJECT_SCHEDULE_CONFLICT or \
            sa.REASON_CANONICAL_STATUS_CONTRADICTS_CLAIM not in bound_mia.reason_codes:
        f.append("F2 bound: a search final against an IN_PROGRESS canonical status produced %s %s"
                 % (bound_mia.disposition, bound_mia.reason_codes))
    for label, eid, start in (("BOS@NYY", sa.EID_BOSNYY, _START_1335ET),
                              ("COL@ATL", sa.EID_COLATL, _START_1335ET)):
        v = SEARCH(
            {"event_id": eid, "league": "MLB",
             "away_team_id": "SYNTH_" + label[:3], "home_team_id": "SYNTH_" + label[-3:],
             "scheduled_start_utc": start, "status": sa.CLOSED, "away_score": 1,
             "home_score": 0, "source": "web_search", "raw_text": label + " final"},
            now_utc=_NOW_1330ET, canonical_schedule=sched)
        if v.disposition != sa.REJECT_PRESTART_OR_UNBOUND:
            f.append("F1/SEARCH %s: a pre-start search final produced %s" % (label, v.disposition))

    # ---- FIXTURE 3. YESTERDAY'S GAME OF THE SAME MATCHUP ------------------------------------
    v = SEARCH(
        {"event_id": sa.EID_MIAWSH_PRIOR, "league": "MLB", "away_team_id": "SYNTH_MIA",
         "home_team_id": "SYNTH_WSH", "scheduled_start_utc": "2026-08-29T16:15:00Z",
         "status": sa.CLOSED, "away_score": 3, "home_score": 4, "raw_text": "prior day"},
        now_utc=_EVENING, canonical_schedule=sched)
    if v.disposition != sa.REJECT_PRESTART_OR_UNBOUND or \
            sa.REASON_EVENT_NOT_IN_SCHEDULE not in v.reason_codes:
        f.append("F3: a prior-day event id bound against today's slate (%s %s)"
                 % (v.disposition, v.reason_codes))

    # ---- FIXTURE 4. A DOUBLEHEADER ----------------------------------------------------------
    dh_records = normalize_statsapi(doubleheader_payload(), fetched_utc=_EVENING,
                                    now_utc=_EVENING)
    note(dh_records)
    if len(dh_records) != 2:
        f.append("F4: a doubleheader normalized to %d records" % len(dh_records))
    if len({r["event_id"] for r in dh_records}) != 2:
        f.append("F4: the two halves collapsed to one identity — team names chose the game")
    dup = [p for r in dh_records for p in r["collector_problems"]
           if p["code"] == COLLECT_DUPLICATE_EVENT_ID]
    if dup:
        f.append("F4: a legitimate doubleheader was reported as a duplicate identity — identity "
                 "is keyed on the matchup, not on the gamePk")
    if [r["game_number"] for r in dh_records] != [1, 2]:
        f.append("F4: gameNumber was lost (%s)" % [r["game_number"] for r in dh_records])
    dh_sched = sa.index_schedule([
        {"event_id": sa.EID_DH_G1, "league": "MLB", "away_team_id": "SYNTH_KC",
         "home_team_id": "SYNTH_TOR", "scheduled_start_utc": "2026-08-30T17:07:00Z",
         "game_number": 1},
        {"event_id": sa.EID_DH_G2, "league": "MLB", "away_team_id": "SYNTH_KC",
         "home_team_id": "SYNTH_TOR", "scheduled_start_utc": "2026-08-30T20:07:00Z",
         "game_number": 2},
    ])
    dh = collect_mlb("2026-08-30", now_utc=_EVENING, canonical_schedule=dh_sched,
                     get=_stub_get(json.dumps(doubleheader_payload())))
    note(dh)
    if dh.counters["DISTINCT_IDENTITIES"] != 2 or dh.counters["ADMITTED"] != 2:
        f.append("F4 collect: %d distinct identities, %d admitted — a doubleheader is two games"
                 % (dh.counters["DISTINCT_IDENTITIES"], dh.counters["ADMITTED"]))
    if {e["record"]["event_id"] for e in dh.admitted} != {sa.EID_DH_G1, sa.EID_DH_G2}:
        f.append("F4 collect: the admitted halves are %s"
                 % sorted(e["record"]["event_id"] for e in dh.admitted))
    if len(sa.schedule_entries_for_matchup(dh_sched, "MLB", "SYNTH_KC", "SYNTH_TOR")) != 2:
        f.append("F4: the fixture is not actually ambiguous by name, so it proves nothing")
    # the morning slate binding the evening results: the ONLY honest use of a derived schedule
    derived = schedule_entries_from_records(dh_records)
    if set(derived) != {sa.EID_DH_G1, sa.EID_DH_G2}:
        f.append("F4: schedule_entries_from_records lost a half (%s)" % sorted(derived))

    # ---- FIXTURE 5. A POSTPONED GAME --------------------------------------------------------
    ppd = collect_mlb("2026-08-30", now_utc=_EVENING,
                      get=_stub_get(json.dumps(postponed_payload())))
    note(ppd)
    rec = ppd.normalized[0]
    if rec["status"] != sa.POSTPONED:
        f.append("F5: statusCode DD did not normalize to POSTPONED (%r)" % rec["status"])
    if rec["away_score"] is not None or rec["home_score"] is not None:
        f.append("F5: a postponed game carried a score forward (%s-%s)"
                 % (rec["away_score"], rec["home_score"]))
    dropped = [p for p in rec["collector_problems"]
               if p["code"] == COLLECT_SCORE_DROPPED_NOT_PLAYED]
    if not dropped or dropped[0]["dropped_home_score"] != 0:
        f.append("F5: the dropped score was not retained as evidence")
    reb = [p for p in rec["collector_problems"] if p["code"] == COLLECT_REBIND_REQUIRED]
    if not reb or reb[0]["reschedule_game_date"] != "2026-08-31":
        f.append("F5: REBIND_REQUIRED did not carry the reschedule evidence (%s)" % reb)
    if not any(p["code"] == COLLECT_OFFICIAL_DATE_DISAGREES for p in rec["collector_problems"]):
        f.append("F5: officialDate 2026-08-31 against ET date 2026-08-30 was not surfaced — the "
                 "conflict feed_mlb_statsapi's docstring promised and nothing ever implemented")
    if ppd.admitted or not ppd.quarantined:
        f.append("F5: a postponed game was admitted (%d admitted, %d quarantined)"
                 % (len(ppd.admitted), len(ppd.quarantined)))
    elif sa.REASON_GAME_POSTPONED not in ppd.quarantined[0]["verdict"].reason_codes:
        f.append("F5: the postponed verdict did not name the postponement (%s)"
                 % ppd.quarantined[0]["verdict"].reason_codes)
    # the same game, with a schedule that names the successor: the rebinding is DATA, not a guess
    ppd_sched = sa.index_schedule([
        {"event_id": sa.EID_PPD_OLD, "league": "MLB", "away_team_id": "SYNTH_PIT",
         "home_team_id": "SYNTH_CLE", "scheduled_start_utc": "2026-08-30T17:10:00Z",
         "status": sa.POSTPONED, "rescheduled_to_event_id": sa.EID_PPD_NEW},
    ])
    ppd2 = collect_mlb("2026-08-30", now_utc=_EVENING, canonical_schedule=ppd_sched,
                       get=_stub_get(json.dumps(postponed_payload())))
    note(ppd2)
    rec2 = ppd2.normalized[0]
    target = [p for p in rec2["collector_problems"] if p["code"] == COLLECT_REBIND_TARGET_RECORDED]
    if not target or target[0]["rebind_to"] != sa.EID_PPD_NEW:
        f.append("F5 rebind: a known successor id was not recorded as data (%s)" % target)
    if not ppd2.quarantined:
        f.append("F5 rebind: a superseded event id was admitted instead of refused")
    else:
        v2 = ppd2.quarantined[0]["verdict"]
        if v2.disposition != sa.REJECT_SCHEDULE_CONFLICT or \
                sa.REASON_POSTPONED_REBIND_REQUIRED not in v2.reason_codes or \
                v2.detail.get("rebind_to") != sa.EID_PPD_NEW:
            f.append("F5 rebind: the superseded id was scored instead of rebound (%s %s)"
                     % (v2.disposition, v2.reason_codes))

    # ---- FIXTURE 6. COMPLETE BUT NOT CLOSED -------------------------------------------------
    cnc = collect_mlb("2026-08-30", now_utc=_EVENING, canonical_schedule=sched,
                      get=_stub_get(json.dumps(complete_not_closed_payload())))
    note(cnc)
    if len(cnc.admitted) != 1:
        f.append("F6: statusCode 'O' produced %d admitted records" % len(cnc.admitted))
    else:
        e = cnc.admitted[0]
        if e["verdict"].admissible_as != sa.ADMISSIBLE_FINAL_UNVALIDATED or e["verdict"].settleable:
            f.append("F6: an unvalidated 'complete' admitted as %s (settleable=%s) — only a "
                     "validated state settles" % (e["verdict"].admissible_as,
                                                  e["verdict"].settleable))
        if e["record"]["terminal_verified"] is not False:
            f.append("F6: terminal_verified was True for a COMPLETE (not CLOSED) status")
        if e["sink"] != sa.SINK_BOARD:
            f.append("F6: an unvalidated final routed to %r; it is readable, not settled"
                     % e["sink"])
    closed = collect_mlb("2026-08-30", now_utc=_EVENING, canonical_schedule=sched,
                         get=_stub_get(json.dumps(_payload([
                             _game(PK_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, "F", 2, 9,
                                   "Miami Marlins", "Washington Nationals")]))))
    note(closed)
    if not closed.admitted or closed.admitted[0]["sink"] != sa.SINK_RESULT_LEDGER:
        f.append("F6 closed: a validated final did not route to the result ledger")
    elif not closed.admitted[0]["record"]["terminal_verified"]:
        f.append("F6 closed: terminal_verified was not generated True for a validated status")

    # ---- FIXTURE 7. THE MUTABLE ARCHIVE, AND THE HASH THAT MUST COVER THE BYTES -------------
    if closed.raw_sha256 != _sha256_of(closed.raw_text):
        f.append("F7: the content hash does not cover the retained raw response")
    if any(p["code"] == COLLECT_HASH_DOES_NOT_COVER_RAW for p in closed.problems):
        f.append("F7: an honest fetch was reported as a hash mismatch")
    forged = CollectResult(date_et="2026-08-30", league=LEAGUE, now_utc=_EVENING, lanes=ls,
                           raw_text="{}", raw_sha256="0" * 64,
                           raw_hash_basis=HASH_BASIS_RAW_BYTES)
    note(forged)
    if not any(p["code"] == COLLECT_HASH_DOES_NOT_COVER_RAW for p in forged.problems):
        f.append("F7: a hash that covers different bytes was accepted")
    a, b = closed.normalized[0], dict(closed.normalized[0], away_score=3,
                                      raw_response_sha256="1" * 64)
    conflict, prob = sa.content_hash_conflict(a, b)
    if not conflict or prob["code"] != sa.REASON_SNAPSHOT_CONTENT_CHANGED:
        f.append("F7: two snapshots under one key with different hashes were not flagged")

    # ---- THE LIVE CAPTURE. ABSENCE IS A FAILURE, NOT A PASS ---------------------------------
    # The one live StatsAPI payload in this repo was trimmed to the fields parse_schedule reads,
    # and parse_schedule reads NAMES. So all 15 games arrive with no team id, and all 15 must be
    # refused. A collector that "handles" them by falling back to the name is the 8/27 bug.
    if not os.path.exists(LIVE_CAPTURE_PATH):
        f.append("LIVE: %s is missing — the only live payload in this repo is not being "
                 "exercised, and a selftest that passes without its subject is a defect"
                 % LIVE_CAPTURE_PATH)
    else:
        live_text = open(LIVE_CAPTURE_PATH).read()
        live = collect_mlb("2026-08-28", now_utc="2026-08-29T12:00:00Z",
                           get=_stub_get(live_text))
        note(live)
        if live.counters["GAMES_IN_PAYLOAD"] != 15:
            f.append("LIVE: %d games parsed from the live capture, expected 15"
                     % live.counters["GAMES_IN_PAYLOAD"])
        if live.admitted:
            f.append("LIVE: %d records with NO team id were admitted — a team name was used as "
                     "an identity" % len(live.admitted))
        missing_ids = sum(1 for r in live.normalized
                          for p in r["collector_problems"] if p["code"] == COLLECT_TEAM_ID_ABSENT)
        if missing_ids != 30:
            f.append("LIVE: %d absent team ids reported across 15 games, expected 30"
                     % missing_ids)
        names_kept = [p.get("team_name") for r in live.normalized
                      for p in r["collector_problems"] if p["code"] == COLLECT_TEAM_ID_ABSENT]
        if "Cincinnati Reds" not in names_kept:
            f.append("LIVE: the team name was not retained as evidence of what was refused")
        et_dates = {r["date_et"] for r in live.normalized}
        if et_dates != {"2026-08-28"}:
            f.append("LIVE: ET derivation drifted (%s). Five of these games tip after UTC "
                     "midnight and are still the ET evening of 08-28" % sorted(et_dates))
        if live.raw_sha256 != _sha256_of(live_text):
            f.append("LIVE: the retained hash does not cover the captured bytes")

    # ---- MALFORMED PAYLOADS: NOTHING IS DROPPED, NOTHING IS FILLED IN -----------------------
    mal_payload = malformed_payload()
    mal = collect_mlb("2026-08-30", now_utc=_EVENING, get=_stub_get(json.dumps(mal_payload)))
    note(mal)
    n_games = len(mal_payload["dates"][0]["games"])
    if mal.counters["GAMES_IN_PAYLOAD"] != n_games:
        f.append("MALFORMED: %d of %d games survived normalization — a game was dropped"
                 % (mal.counters["GAMES_IN_PAYLOAD"], n_games))
    if mal.counters["ADMITTED"] + mal.counters["QUARANTINED"] != n_games:
        f.append("MALFORMED: the two lists do not account for every game")
    # WHAT MUST REFUSE: no status, an unmapped status, no gamePk, a placeholder gamePk, an
    # unparseable gameDate, and a games[] entry that is a sentence. Six of the nine.
    refused_ids = {e["record"].get("event_id") for e in mal.quarantined}
    if len(mal.quarantined) != 6:
        f.append("MALFORMED: %d of 9 games refused, expected 6 (%s)"
                 % (len(mal.quarantined), sorted(str(i) for i in refused_ids)))
    # WHAT MUST NOT: a surfaced season disagreement is a CONFLICT REPORT, not a refusal, and a
    # duplicated identity is reported without a verdict being overridden — admit() owns that word.
    drift = [e for e in mal.admitted if (e["record"].get("event_id") or "").endswith(
        PK_SEASON_DRIFT)]
    if len(drift) != 1 or drift[0]["record"]["event_id"] != "mlb:2025:" + PK_SEASON_DRIFT:
        f.append("MALFORMED: the season disagreement was resolved into a refusal instead of "
                 "being surfaced (%s)" % [e["record"]["event_id"] for e in mal.admitted])
    if not any(p["code"] == COLLECT_DUPLICATE_EVENT_ID for p in mal.problems):
        f.append("MALFORMED: an identity collision was not raised to result level, so the "
                 "snapshot store would never see it")
    if not any(p["code"] == sa.REASON_SNAPSHOT_HASH_MATCHES_CONTENT_DIFFERS
               for r in mal.normalized for p in r["collector_problems"]):
        f.append("MALFORMED: two records under one identity disagreed on the score and the "
                 "contract's own name for that was not used")
    no_status_rec = [r for r in mal.normalized if r["event_id"]
                     and r["event_id"].endswith(PK_NO_STATUS)]
    if not no_status_rec or no_status_rec[0]["status"] is not None:
        f.append("MALFORMED: an absent status field became a value instead of None")
    else:
        codes = {c for e in mal.quarantined if e["record"] is no_status_rec[0]
                 for c in e["verdict"].reason_codes}
        if sa.REASON_STATUS_MISSING not in codes:
            f.append("MALFORMED: a missing status did not produce SOURCE_STATUS_MISSING (%s)"
                     % codes)
    unmapped = [r for r in mal.normalized if r.get("provider_status_code") == "I"]
    if not unmapped or unmapped[0]["status"] != sa.UNKNOWN:
        f.append("MALFORMED: an unevidenced statusCode was mapped to something other than UNKNOWN")
    dupes = [p for r in mal.normalized for p in r["collector_problems"]
             if p["code"] == COLLECT_DUPLICATE_EVENT_ID]
    if len(dupes) != 2:
        f.append("MALFORMED: two games sharing one event id produced %d duplicate reports"
                 % len(dupes))
    # ---- CLOCK SKEW, and the canonical-json hash basis ---------------------------------------
    skew = normalize_statsapi(doubleheader_payload(), fetched_utc=_EVENING, now_utc=_NOW_1330ET)
    note(skew)
    if not any(p["code"] == COLLECT_CLOCK_SKEW for r in skew for p in r["collector_problems"]):
        f.append("SKEW: a fetch stamped after the judgement instant was not reported")
    if skew[0]["raw_hash_basis"] != HASH_BASIS_CANONICAL_JSON:
        f.append("SKEW: a hash with no raw bytes behind it was labelled as covering raw bytes")

    # ---- THE SEARCH LANE CANNOT ADMIT, BY CONSTRUCTION ---------------------------------------
    if _SEARCH_LANE != sa.LANE_SEARCH:
        f.append("SEARCH: quarantine_search_claim's lane constant is not the SEARCH lane")
    try:
        _quarantine_only(sa.Verdict(sa.ADMIT_FINAL, [sa.REASON_STATUS_VALIDATED],
                                    sa.ADMISSIBLE_FINAL, {"lane": sa.LANE_CANONICAL}))
        f.append("SEARCH: the quarantine post-filter returned an ADMIT_FINAL verdict")
    except sa.LaneViolation:
        pass
    search_verdicts = []
    claim = {"event_id": sa.EID_MIAWSH, "league": "MLB", "away_team_id": "SYNTH_MIA",
             "home_team_id": "SYNTH_WSH", "scheduled_start_utc": _START_1215ET,
             "status": sa.CLOSED, "away_score": 2, "home_score": 9, "source": "outlet_a",
             "wire_service": "wire_x", "result_timestamp_utc": _EVENING,
             "raw_text": "Nationals 9, Marlins 2"}
    for n in (0, 1, 2, 3, 99):
        v = SEARCH(claim, now_utc=_EVENING, canonical_schedule=None, corroborations=n)
        search_verdicts.append(v)
        if v.admitted or v.disposition == sa.ADMIT_FINAL:
            f.append("SEARCH: %d corroborations minted a final from the search lane" % n)
        if v.admissible_as in (sa.ADMISSIBLE_FINAL, sa.ADMISSIBLE_FINAL_UNVALIDATED):
            f.append("SEARCH: %d corroborations produced admissible_as=%r" % (n, v.admissible_as))
        if sa.sink_for(v) != sa.SINK_QUARANTINE:
            f.append("SEARCH: a search verdict routed to %r" % sa.sink_for(v))
    if search_verdicts and search_verdicts[0].disposition != sa.NO_CONSENSUS:
        f.append("SEARCH: a single-source search final produced %s"
                 % search_verdicts[0].disposition)
    if len(search_verdicts) > 2 and (
            search_verdicts[2].disposition != sa.UNVERIFIED
            or search_verdicts[2].admissible_as != sa.ADMISSIBLE_CORROBORATED):
        f.append("SEARCH: two independent sources produced %s/%s, not UNVERIFIED/%s"
                 % (search_verdicts[2].disposition, search_verdicts[2].admissible_as,
                    sa.ADMISSIBLE_CORROBORATED))
    # a snippet with no retained bytes has no hash, and owner rule 7 refuses it
    no_bytes = SEARCH(dict(claim, raw_text=None), now_utc=_EVENING, canonical_schedule=None)
    if no_bytes.disposition != sa.UNVERIFIED or \
            sa.REASON_MISSING_REQUIRED_FIELD not in no_bytes.reason_codes:
        f.append("SEARCH: a claim with no retained response was not refused on rule 7 (%s %s)"
                 % (no_bytes.disposition, no_bytes.reason_codes))
    # the 8/30 snippet in its actual shape: a sentence
    prose = SEARCH("Nationals 9, Marlins 2", now_utc=_NOW_1330ET, canonical_schedule=sched)
    if prose.disposition != sa.UNVERIFIED or \
            sa.REASON_RECORD_NOT_A_MAPPING not in prose.reason_codes:
        f.append("SEARCH: a bare sentence produced %s %s" % (prose.disposition,
                                                             prose.reason_codes))
    named = SEARCH(dict(claim, event_id=None), now_utc=_EVENING, canonical_schedule=sched)
    if named.disposition != sa.REJECT_PRESTART_OR_UNBOUND or \
            sa.REASON_NO_EVENT_ID not in named.reason_codes:
        f.append("SEARCH: a claim identified only by team names produced %s %s"
                 % (named.disposition, named.reason_codes))

    # ---- EVERY RECORD AND EVERY VERDICT THIS SELFTEST PRODUCED MUST BE WELL FORMED -----------
    results = [inc, dh, ppd, ppd2, cnc, closed, mal, empty]
    if os.path.exists(LIVE_CAPTURE_PATH):
        results.append(live)
    contract_fields = set(sa.RECORD_FIELDS) | set(sa.OPTIONAL_RECORD_FIELDS)
    for res in results:
        if {id(e) for e in res.admitted} & {id(e) for e in res.quarantined}:
            f.append("RESULT: an entry appears in both the admitted and quarantined lists")
        if res.counters["ADMITTED"] + res.counters["QUARANTINED"] != \
                res.counters["RECORDS_NORMALIZED"]:
            f.append("RESULT: counters do not balance (%s)" % res.counters)
        try:
            list(res)
            f.append("RESULT: a CollectResult was iterable, so a caller can mix the two lists")
        except TypeError:
            pass
        json.dumps(res.to_dict(), default=str)
        json.dumps(snapshot_payload(res), default=str)
        for r in res.normalized:
            extras = set(r) - contract_fields
            if extras != set(COLLECTOR_EXTRA_FIELDS):
                f.append("RECORD: undeclared extra fields %s" % sorted(extras ^
                                                                       set(COLLECTOR_EXTRA_FIELDS)))
            if r["source"] != sa.PROVIDER_MLB_STATSAPI:
                f.append("RECORD: source %r is not the contract's provider name" % r["source"])
            if r["status"] is not None and r["status"] not in sa.STATUSES:
                f.append("RECORD: status %r is outside the shared vocabulary" % r["status"])
            if r["terminal_verified"] != sa.terminal_verified_for(r["status"]):
                f.append("RECORD: terminal_verified was typed, not generated (%r for %r)"
                         % (r["terminal_verified"], r["status"]))
            if r["date_et"] and sa.scheduled_date_of(r) != r["date_et"]:
                f.append("RECORD: date_et %r disagrees with the contract's own derivation %r"
                         % (r["date_et"], sa.scheduled_date_of(r)))
            if r["event_id"] is not None:
                ok_id, probs = sa.validate_event_id(r["event_id"])
                if not ok_id:
                    f.append("RECORD: emitted an id the contract refuses: %s"
                             % [p["code"] for p in probs])
        for e in res.admitted:
            if not e["verdict"].admitted:
                f.append("ROUTING: a non-admitting verdict is in the admitted list")
            if e["sink"] not in (sa.SINK_BOARD, sa.SINK_RESULT_LEDGER):
                f.append("ROUTING: an admitted record routed to %r" % e["sink"])
        for e in res.admitted + res.quarantined:
            if e["verdict"].detail.get("lane") != sa.LANE_CANONICAL:
                f.append("ROUTING: a collector verdict carries lane %r"
                         % e["verdict"].detail.get("lane"))
            sa.assert_write_allowed(sa.LANE_CANONICAL, e["sink"])
    for v in search_verdicts + [search_mia, bound_mia, prose, named, no_bytes]:
        if v.detail.get("lane") != sa.LANE_SEARCH:
            f.append("SEARCH: a quarantine verdict carries lane %r" % v.detail.get("lane"))
        if v.admitted:
            f.append("SEARCH: a search verdict reported itself admitted")

    # ---- VOCABULARY COVERAGE. A code no fixture can fire is a code nobody has watched -------
    uncovered = [c for c in COLLECT_REASON_CODES if c not in codes_seen]
    if uncovered:
        f.append("COVERAGE: collector codes this selftest never produces: %s" % uncovered)

    # ---- verified_snapshot: integrate if it exists, SAY SO if it does not --------------------
    if vs is None:
        skipped.append("verified_snapshot is not importable (%s) — the write_snapshot / "
                       "get_verified_score / get_verified_scores / get_source_manifest "
                       "integration is NOT exercised by this run" % VERIFIED_SNAPSHOT_ABSENCE)
    else:
        for name in VERIFIED_SNAPSHOT_NAMES:
            fn = getattr(vs, name, None)
            if fn is None:
                f.append("SNAPSHOT: verified_snapshot has no %s — the documented name this "
                         "collector was built against" % name)
            elif not callable(fn):
                f.append("SNAPSHOT: verified_snapshot.%s is not callable" % name)
        if hasattr(vs, "admission_envelope"):
            mine = admission_envelopes(inc)[0]
            theirs = vs.admission_envelope(mine["record"], mine["verdict"])
            if set(mine) != set(theirs):
                f.append("SNAPSHOT: the admission envelope forked between the module that admits "
                         "and the module that stores (%s vs %s)"
                         % (sorted(mine), sorted(theirs)))
        # THE HANDOFF, EXERCISED. Stage 2 -> stage 3, into a throwaway root so no repo artifact is
        # touched (R6 belongs to the store, and a selftest must not append to it). The check that
        # matters is the LAST one: a record this collector refused must not be reachable through
        # the read-only analysis surface. That is the whole lane separation, end to end.
        import shutil, tempfile
        root = tempfile.mkdtemp(prefix="score_collector_selftest_")
        try:
            body = snapshot_payload(inc)
            sid = vs.write_snapshot(admission_envelopes(inc), league=inc.league,
                                    date_et=inc.date_et, source=inc.source,
                                    raw_payloads=body["raw_payloads"], now_utc=_EVENING,
                                    out_root=root)
            got = vs.get_verified_score(sa.EID_MIAWSH, root=root)
            if not got or got.get("home_score") != 9 or got.get("away_score") != 2:
                f.append("SNAPSHOT: the admitted record did not survive the round trip (%s)"
                         % got)
            for refused in (sa.EID_BOSNYY, sa.EID_COLATL):
                leaked = vs.get_verified_score(refused, root=root)
                if leaked is not None:
                    f.append("SNAPSHOT: %s was REFUSED by admit() and is still readable through "
                             "get_verified_score — the quarantine boundary leaks" % refused)
            slate = vs.get_verified_scores(inc.date_et, "MLB", root=root)
            if len(slate) != len(inc.admitted):
                f.append("SNAPSHOT: the slate read back %d records for %d admitted"
                         % (len(slate), len(inc.admitted)))
            manifest = vs.get_source_manifest(sid, root=root)
            if inc.raw_sha256 not in json.dumps(manifest, default=str):
                f.append("SNAPSHOT: the manifest does not carry the raw response hash this "
                         "collector retained (owner rule 7 broken across the handoff)")
        except TypeError as e:
            # A signature this module does not own changed. That is not this collector's defect,
            # and it is not silence either.
            skipped.append("verified_snapshot's signature does not match what this collector "
                           "calls (%s) — the write/read round trip was NOT exercised" % e)
        except Exception as e:                                    # noqa: BLE001
            f.append("SNAPSHOT: verified_snapshot refused what this collector produced (%s: %s)"
                     % (type(e).__name__, str(e)[:400]))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    for s in skipped:
        print("  SKIPPED:", s)
    print(f"{MODULE_ID} selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("  FAIL:", x)
    return not f


# =============================================================================== mutation suite

MUTANTS = [
    ("M1 identity becomes the matchup, so a doubleheader reads as one game reported twice",
     '    return record.get("event_id")',
     '    return (record.get("away_team_id"), record.get("home_team_id"))'),

    ("M2 the search lane's only exit stops refusing a verdict that admits",
     "    if verdict.admitted or sa.sink_for(verdict) != sa.SINK_QUARANTINE:",
     "    if False:"),

    ("M3 a search claim is submitted as if it came from the canonical lane",
     "_SEARCH_LANE = sa.LANE_SEARCH",
     "_SEARCH_LANE = sa.LANE_CANONICAL"),

    ("M4 the default fetcher becomes a live call instead of a refusal",
     "DEFAULT_GET = feed_mlb_statsapi._default_get",
     'DEFAULT_GET = lambda url, timeout=None: json.dumps(incident_payload_0830())'),

    ("M5 a postponed game carries its score forward",
     "        away_score = home_score = None",
     "        pass"),

    ("M6 terminal_verified is typed from the terminal set instead of generated from the "
     "validated set, so 'complete' becomes settleable",
     '        "terminal_verified": sa.terminal_verified_for(status),',
     '        "terminal_verified": status in sa.TERMINAL_STATES,'),

    ("M7 the content hash stops covering the bytes it names",
     "    raw_sha256 = _sha256_of(raw)",
     '    raw_sha256 = "a" * 64'),

    ("M8 the provider status is decoded locally instead of through the shared mapping, and the "
     "unobserved 'O' code is promoted to validated",
     "        status = sa.normalize_status(code, sa.PROVIDER_MLB_STATSAPI)",
     '        status = sa.CLOSED if code in ("F", "O") else sa.UNKNOWN'),

    ("M9 the collector decides admissibility itself instead of routing the contract's verdict",
     "        if verdict.admitted:",
     "        if True:"),

    ("M10 an absent team id falls back to the team name, so a name becomes an identity",
     "    return team.get(\"id\"), team.get(\"name\")",
     "    return team.get(\"id\") or team.get(\"name\"), team.get(\"name\")"),

    ("M11 the canonical lane reports UP with no fetcher injected, so a down feed reads as an "
     "empty slate",
     "    canonical_up = get is not None",
     "    canonical_up = True"),

    ("M12 a game the collector cannot identify is silently dropped instead of refused",
     "        records.append(record)",
     "        if record.get(\"event_id\"): records.append(record)"),

    ("M13 an absent status field is defaulted to UNKNOWN, hiding owner rule 3 behind rule 8",
     "        status = None",
     "        status = sa.UNKNOWN"),
]


def mutation_suite():
    src = open(__file__).read()
    # BASELINE FIRST. A failing selftest makes every mutant look killed, so a broken fixture
    # reports a perfect score. (module_manifest printed 11/11 that way on 2026-08-25.)
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
            with _cl.redirect_stdout(_io.StringIO()):
                ok = ns["selftest"]()
        except Exception:
            ok = False
        print(("  KILLED    " if not ok else "  SURVIVED  ") + name)
        killed += not ok
    print(f"score_collector mutation suite: {killed}/{len(MUTANTS)} killed"
          + ("" if killed == len(MUTANTS) else "  — SURVIVORS MEAN DECORATIVE FIXTURES"))
    return killed == len(MUTANTS)


def gate():
    """Healthcheck entry point: the fixtures hold AND the mutants die."""
    import io as _io, contextlib as _cl
    _b = _io.StringIO()
    with _cl.redirect_stdout(_b):
        ok_self = selftest()
        ok_mut = mutation_suite()
    print("score collector gate: %s (selftest %s, mutants %s)"
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
