#!/usr/bin/env python3
"""VERIFIED SNAPSHOT — the immutable store, and the only tool surface analysis may call.

WHAT SITS WHERE. The owner's architecture is four boxes:

    approved source API -> game binding + status validator -> IMMUTABLE VERIFIED SNAPSHOT
                        -> Claude analysis / card generation

harness/score_admission.py is box two: it decides. This file is box three: it REMEMBERS, and it
is the wall box four reads through. It judges nothing — every record arriving here must already
carry the Verdict that score_admission.admit() produced, because a store that re-judges is a
second judge, and two judges is how a vocabulary forks. A record with no verdict is REFUSED
(NO_ADMISSION_VERDICT), never stored with a disposition this module invented (R1).

THE INCIDENTS THIS FILE ANSWERS, each mapped to the rule it produced.

1. 2026-08-27. Five fabricated MLB finals were PUBLISHED from a summary of web search results.
   Nothing separated what a feed said from what a sentence said, because there was one place to
   put both. Here there are two: records.json (admitted) and quarantine.json (everything else),
   in the same snapshot, behind two DIFFERENT accessors. get_verified_score() cannot reach
   quarantine at all; get_quarantine() has a name a reviewer cannot mistake for a result.
   Routing is not decided here — it is score_admission.sink_for(verdict), read off the verdict's
   own recorded lane, so a caller cannot re-lane a record at write time.

2. 2026-08-30 13:30 ET. Three confident finals arrived for games that had not started or were
   75 minutes into a 170-minute game. They were refused by hand. The refusal is now storable:
   the actual snippet, "Nationals 9, Marlins 2", is a fixture in this module's selftest and it
   lands in quarantine as a bare STRING. Quarantine must be able to hold the thing that was
   refused — including prose that is not a record at all — or the refusal leaves no evidence.

3. 2026-08-30, same day. The admitted pitch archive REWROTE TWO HISTORICAL DAILY FILES UNDER
   UNCHANGED FILENAMES (docs/SCORE_ADMISSION_CONTRACT.md, "Standing hazards"). A sha recorded
   once is an observation at a moment, not a permanent fact. So: every raw payload's bytes are
   stored here beside the records they produced, the manifest carries each payload's sha256 and
   the instant it was fetched (owner rule 7), every admitted record's raw_response_sha256 must
   match one of those payloads (RECORD_HASH_NOT_IN_SNAPSHOT — otherwise the manifest's hashes
   are decoration), and verify_snapshot() RE-HASHES WHAT IS ON DISK instead of believing the
   manifest. The snapshot id is itself the hash of the content, so a drifted byte anywhere makes
   the directory name stop being true, and verify_snapshot says so.

4. The overwrite precedent. harness/grade_slate.py:299 records the 2026-08-21 v2 headline
   .230621 being overwritten with .292681 by a re-settlement that graded one late game; the
   cohort statistic then had to be rebuilt from the ledger. R6 exists because of that class of
   day. Here: identical content re-written is a NO-OP returning the same id; content that does
   not match what is already on disk under that id RAISES SnapshotImmutabilityViolation and
   CHANGES NOTHING — it does not repair the drift either, because repairing is a rewrite and a
   rewrite erases the evidence that a mutation happened.

5. 2026-08-30, the adversarial review of this layer (data/audit/2026-08-30_isolation_layer_-
   review.json). Thirty-five HIGH findings; five of them landed here, and every one of them was
   in the READ path — the half that had fixtures for what the store REFUSES and almost none for
   what it SERVES.

   C (five independent lenses, the strongest signal in the run). _resolve ordered observations by
     written_at_utc — the STORE ACTION — while its own docstring said observation. A stale
     IN_PROGRESS written after a validated CLOSED superseded the final, so get_verified_score
     returned a non-final for a settled game. Ordering is now _observation_order(), keyed on
     source_fetched_at_utc; and, because a final does not change, a TERMINAL observation is never
     superseded by a non-terminal one no matter which instant it carries.
   D. verify_snapshot() had ZERO read-path callers: its only production call site was inside the
     WRITE path. records.json edited in place on disk was therefore served as truth by all three
     analysis tools — this module's founding hazard, unguarded, in the module written against it.
     This is the third guard in this repo that existed and was never called (after aggregate_guard
     and ALLOW_DIRECT_HTTP). The getters now re-derive BEFORE serving: the entry files are
     re-hashed on every read (they are being read anyway, so the hash is nearly free) and the
     content id is recomputed from the bytes on disk; only the payload-bytes re-hash is cached,
     keyed on each file's size and mtime_ns. The cache is a speed shortcut over a signal the
     filesystem supplies, so it is named as a residual and not as a proof.
   E. A stored verdict was never bound to the record it judged. A genuine CANONICAL verdict copied
     onto a different record admitted that record — source "web_search" and all — as FINAL. No
     forgery was required. Now: every field the verdict RECORDED about what it judged (event_id,
     status, terminal_verified, scheduled_start_utc) must match the record beside it, what the
     admissible_as IMPLIES about that record must hold, and each entry carries record_sha256, a
     binding generated here and re-checked on every read.
   F. Two records both claiming a TERMINAL status for one event id with DIFFERENT scores were
     silently resolved by picking the writer-supplied later one; content_hash_conflict only
     catches same-key/same-sha shapes and is evaded by moving source_fetched_at_utc one second.
     A final does not change: two disagreeing terminals are a CONTRADICTION and the store serves
     NEITHER, loudly, rather than picking.
   A-DOWNSTREAM. score_admission.admit(canonical_schedule=None) leaves owner rules 1, 2 and 6
     unenforced and stamps REASON_SCHEDULE_NOT_SUPPLIED on the verdict. That ceiling is one edit
     away from being lowered again, so this store refuses such a verdict on the verified side at
     BOTH ends — write and read. NOTE FOR THE SIBLING MODULES: this makes a schedule-less
     admission unstorable as a result. harness/test_score_admission.py's FIXTURE 7 currently
     admits with canonical_schedule=None and then reads the record back; that fixture must supply
     a schedule. score_collector's own handoff already passes one.

WHY THE ID EXCLUDES now_utc AND INCLUDES fetched_at_utc. The id is content-addressed. A payload's
fetched_at is a property of the OBSERVATION (the same bytes seen at two instants are two
observations, and both are kept). now_utc is a property of the STORE ACTION (a retry of the same
write an hour later is the same content, and must dedup rather than fork). Putting now_utc in the
digest would make "write the same content twice" impossible to satisfy.

WHAT THIS MODULE DOES NOT DO. No network of any kind (ALLOW_DIRECT_HTTP is declared False and
selftest S0 scans this file's own source for call sites). No clock: every timestamp is supplied
by the caller and recorded, never read from the machine — S0 scans for that too, because a store
that stamps its own time can date an artifact later than the fetch it describes. No writes
outside out_root. No mutation of any existing snapshot, ever.

THE SURFACE.

    write_snapshot(records, *, league, date_et, source, raw_payloads, now_utc, out_root)
        the only writer. `records` are admission envelopes, not bare records.
    get_verified_score(event_id)      \\
    get_verified_scores(date, league)  > the analysis layer's three tools, and its only three.
    get_source_manifest(snapshot_id)  /   Each calls score_admission.assert_tool_allowed.
    verify_snapshot(snapshot_id)      re-hash what is on disk; report drift, repair nothing.
                                      Called by the getters now, not only by the writer (D).
    get_quarantine(date, league)      deliberately NOT an analysis tool. Reading the refused
                                      side is an audit act and has to look like one.

Two exceptions a reader may see from the READ path, both added by the 8/30 review:
    SnapshotImmutabilityViolation     the bytes under out_root are not what they were (D).
    SnapshotAdmissibilityViolation    what is stored on the verified side does not satisfy the
                                      ceiling the getters enforce: an unbound verdict, a verdict
                                      that judged some other record, or a record whose stored
                                      binding no longer covers it (E, A-DOWNSTREAM).
    SnapshotContentConflict           two stored observations of one event contradict (F).

Usage: python3 harness/verified_snapshot.py [--selftest] [--mutants] [--gate]
"""
from __future__ import annotations

MODULE_ID = "verified_snapshot"

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import score_admission as sa                 # noqa: E402  lanes, statuses, dispositions, Verdict
from feed_espn import parse_utc              # noqa: E402  instant parsing lives in ONE place

#: This module reaches nothing. Declared so the posture is stated rather than assumed; S0 proves
#: the declaration by scanning this file, so it is a check and not a comment.
ALLOW_DIRECT_HTTP = False

UTC = dt.timezone.utc


# ---------------------------------------------------------------------------------------------
# 1. LAYOUT.  Where bytes live, and the names a reader can rely on.
# ---------------------------------------------------------------------------------------------

DEFAULT_ROOT = "data/verified"

SNAPSHOTS_DIR = "snapshots"       # <root>/snapshots/<snapshot_id>/
INCOMING_DIR = ".incoming"        # <root>/.incoming/  — staged writes, renamed into place
RAW_DIR = "raw"                   # <snapshot>/raw/<payload_id>
MANIFEST_NAME = "manifest.json"
VERIFIED_NAME = "records.json"
QUARANTINE_NAME = "quarantine.json"
WRITE_LOG_NAME = "write_log.jsonl"

SCHEMA_MANIFEST = "ops.verified_snapshot.manifest.v1"
SCHEMA_ENTRIES = "ops.verified_snapshot.entries.v1"
SCHEMA_CONTENT = "ops.verified_snapshot.content.v1"
SCHEMA_WRITE_LOG = "ops.verified_snapshot.write_log.v1"
SCHEMA_VERIFICATION = "ops.verified_snapshot.verification.v1"

#: The id is GENERATED from the content (counters are generated by code, never typed by hand).
#: prefix + the sha256 of the canonical content object.
SNAPSHOT_ID_PREFIX = "vsnap1_"
_SNAPSHOT_ID_RE = re.compile(r"^vsnap1_[0-9a-f]{64}$")

#: A payload id becomes a filename. Anything that could climb out of the store is refused before
#: it is joined to a path; _assert_within is the second line, not the first.
_PAYLOAD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

_DATE_ET_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

#: The two sinks whose contents are READABLE AS RESULTS. Everything else in a snapshot is
#: quarantine. This set is the whole of the getters' admission rule, so it is stated once.
VERIFIED_SINKS = frozenset({sa.SINK_BOARD, sa.SINK_RESULT_LEDGER})

#: The three tools the analysis layer may call, bound to score_admission's tuple rather than
#: retyped. Each getter below calls sa.assert_tool_allowed with its own name, so the surface is
#: ENFORCED at call time and not merely documented (the "documented, implemented, unexecuted"
#: failure mode this repo has hit twice).
ANALYSIS_TOOL_SURFACE = sa.ANALYSIS_TOOL_SURFACE


# ---------------------------------------------------------------------------------------------
# 2. REFUSALS AND DRIFT.  Every code carries a meaning, and selftest asserts every code fires.
# ---------------------------------------------------------------------------------------------

REFUSE_NO_RECORDS = "SNAPSHOT_HAS_NO_RECORDS"
REFUSE_NOT_AN_ENVELOPE = "RECORD_IS_NOT_AN_ADMISSION_ENVELOPE"
REFUSE_NO_VERDICT = "NO_ADMISSION_VERDICT"
REFUSE_BAD_VERDICT = "ADMISSION_VERDICT_MALFORMED"
REFUSE_SEARCH_ADMISSION = "SEARCH_LANE_ADMISSION_FORGED"
REFUSE_ADMITTED_INVALID = "ADMITTED_RECORD_FAILS_VALIDATION"
REFUSE_HASH_NOT_IN_SNAPSHOT = "RECORD_HASH_NOT_IN_SNAPSHOT"
REFUSE_LEAGUE_MISMATCH = "RECORD_LEAGUE_NOT_SNAPSHOT_LEAGUE"
REFUSE_DATE_MISMATCH = "RECORD_ET_DATE_NOT_SNAPSHOT_DATE"
REFUSE_DUPLICATE_EVENT_ID = "DUPLICATE_EVENT_ID_IN_SNAPSHOT"
REFUSE_NOT_SERIALIZABLE = "ENTRY_NOT_JSON_SERIALIZABLE"
REFUSE_NO_PAYLOAD = "NO_RAW_PAYLOAD_RETAINED"
REFUSE_PAYLOAD_SHAPE = "RAW_PAYLOAD_SHAPE_UNUSABLE"
REFUSE_PAYLOAD_ID = "RAW_PAYLOAD_ID_UNSAFE"
REFUSE_PAYLOAD_FETCHED_AT = "RAW_PAYLOAD_FETCHED_AT_MISSING"
REFUSE_PAYLOAD_SHA_MISMATCH = "RAW_PAYLOAD_SHA256_MISMATCH"
REFUSE_DUPLICATE_PAYLOAD_ID = "DUPLICATE_RAW_PAYLOAD_ID"
REFUSE_VERDICT_NOT_BOUND = "VERDICT_DID_NOT_JUDGE_THIS_RECORD"
REFUSE_UNBOUND_NO_SCHEDULE = "ADMITTED_WITHOUT_A_CANONICAL_SCHEDULE"
REFUSE_BAD_DATE_ET = "SNAPSHOT_DATE_ET_MALFORMED"
REFUSE_BAD_SOURCE = "SNAPSHOT_SOURCE_MISSING"
REFUSE_BAD_SNAPSHOT_ID = "SNAPSHOT_ID_MALFORMED"
REFUSE_WRITE_OUTSIDE_ROOT = "PATH_ESCAPES_OUT_ROOT"
#: Bound to score_admission's spellings, not retyped: the same failure must have one name.
REFUSE_BAD_LEAGUE = sa.REASON_UNSUPPORTED_LEAGUE
REFUSE_BAD_NOW = sa.REASON_UNPARSEABLE_TIMESTAMP

REFUSAL_MEANING = {
    REFUSE_NO_RECORDS: "an empty snapshot. A down lane and an empty slate look identical on "
                       "disk, and on 2026-08-30 that ambiguity is what invited a search "
                       "backfill; an absence is declared with score_admission.lane_down()",
    REFUSE_NOT_AN_ENVELOPE: "not {'record': ..., 'verdict': ...}; this store never re-judges, so "
                            "it cannot accept a record that arrives without its judgement",
    REFUSE_NO_VERDICT: "no admission verdict — call score_admission.admit() first. A disposition "
                       "this module invented would be a number nobody generated (R1)",
    REFUSE_BAD_VERDICT: "the verdict is not score_admission's vocabulary: unknown disposition, "
                        "empty or undocumented reason codes, or an unknown admissible_as",
    REFUSE_SEARCH_ADMISSION: "a SEARCH-lane verdict claiming an admitting disposition. Search "
                             "never admits; a verdict saying it does was forged or mutated",
    REFUSE_ADMITTED_INVALID: "a record routed to the verified side fails "
                             "score_admission.validate_record — the judge and the store disagree",
    REFUSE_HASH_NOT_IN_SNAPSHOT: "an admitted record's raw_response_sha256 matches none of this "
                                 "snapshot's payloads, so nothing on disk supports it (owner "
                                 "rule 7). Without this the manifest's hashes are decoration",
    REFUSE_LEAGUE_MISMATCH: "an admitted record's league is not the snapshot's league; "
                            "get_verified_scores selects by the snapshot's league",
    REFUSE_DATE_MISMATCH: "an admitted record's ET date is not the snapshot's date_et. Derived "
                          "with zoneinfo, never sliced: a 2026-08-31T00:30Z tip is the ET "
                          "EVENING of 08-30, and slicing corrupted a cohort twice",
    REFUSE_DUPLICATE_EVENT_ID: "two admitted records for one event id in one snapshot; the "
                               "getters would have to pick, and picking is not a store's job",
    REFUSE_NOT_SERIALIZABLE: "the entry cannot be written as JSON, so it could not be re-read",
    REFUSE_NO_PAYLOAD: "no raw payload. Owner rule 7: preserve the raw response and its hash, so "
                       "a later reader can re-derive rather than trust",
    REFUSE_PAYLOAD_SHAPE: "a payload is not a mapping carrying raw_text or raw_bytes",
    REFUSE_PAYLOAD_ID: "the payload id is empty, over-long, or contains path syntax",
    REFUSE_PAYLOAD_FETCHED_AT: "a payload with no fetched_at_utc. Half of owner rule 7 is WHEN "
                               "the bytes were seen; a hash with no instant cannot date drift",
    REFUSE_PAYLOAD_SHA_MISMATCH: "the caller supplied a sha256 that is not the sha256 of the "
                                 "bytes supplied with it — a typed hash, not a generated one",
    REFUSE_DUPLICATE_PAYLOAD_ID: "two payloads share one id; the second would overwrite the first",
    REFUSE_VERDICT_NOT_BOUND: "the verdict beside this record judged something else: a field it "
                              "RECORDED about what it judged disagrees with the record, or the "
                              "record does not satisfy what its admissible_as implies. Copying a "
                              "genuine CANONICAL verdict onto a fabricated record needed no "
                              "forgery at all before this check (2026-08-30 review, cluster E)",
    REFUSE_UNBOUND_NO_SCHEDULE: "a verdict carrying CANONICAL_SCHEDULE_NOT_SUPPLIED on the "
                                "verified side. Owner rules 1, 2 and 6 live inside admit()'s "
                                "`if idx is not None`, so a schedule-less admission checked the "
                                "record only against ITSELF; the store will not keep that as a "
                                "result. Defence in depth: the ceiling in admit() is one edit "
                                "away from being lowered again (2026-08-30 review, cluster A)",
    REFUSE_BAD_DATE_ET: "date_et is not a real YYYY-MM-DD ET calendar date",
    REFUSE_BAD_SOURCE: "source is empty; a snapshot with no named source cannot be lane-checked",
    REFUSE_BAD_SNAPSHOT_ID: "not a '" + SNAPSHOT_ID_PREFIX + "<64 hex>' id generated by this store",
    REFUSE_WRITE_OUTSIDE_ROOT: "a path resolved outside out_root; this module writes nowhere else",
    REFUSE_BAD_LEAGUE: "league is not one of score_admission.LEAGUES",
    REFUSE_BAD_NOW: "now_utc could not be parsed as an instant",
}

DRIFT_MANIFEST_MISSING = "SNAPSHOT_MANIFEST_MISSING"
DRIFT_FILE_MISSING = "SNAPSHOT_FILE_MISSING"
DRIFT_PAYLOAD_BYTES = "RAW_PAYLOAD_BYTES_DRIFTED"
DRIFT_ENTRY_FILE_BYTES = "SNAPSHOT_ENTRY_FILE_DRIFTED"
DRIFT_ID_NOT_CONTENT = "SNAPSHOT_ID_NO_LONGER_MATCHES_CONTENT"
DRIFT_RECORD_HASH_UNCOVERED = "RECORD_HASH_NO_LONGER_COVERED_BY_A_PAYLOAD"

DRIFT_MEANING = {
    DRIFT_MANIFEST_MISSING: "the snapshot directory exists with no manifest: a partial write or "
                            "a deletion. The getters refuse to serve around it",
    DRIFT_FILE_MISSING: "a file the manifest names is gone",
    DRIFT_PAYLOAD_BYTES: "a stored raw payload's bytes no longer hash to the recorded sha256 — "
                         "the 2026-08-30 mutable-archive shape, caught inside our own store",
    DRIFT_ENTRY_FILE_BYTES: "records.json or quarantine.json no longer hashes to the recorded "
                            "sha256: a score was edited after the fact",
    DRIFT_ID_NOT_CONTENT: "the content on disk no longer hashes to the snapshot id. The id IS "
                          "the hash, so this is the anchor check: it survives a manifest that "
                          "was updated to match the tampered bytes",
    DRIFT_RECORD_HASH_UNCOVERED: "an admitted record's source hash matches none of the payloads "
                                 "as they now stand on disk",
}

#: READ-TIME contradictions and unservable stores. Separate from REFUSE_ (a write that was
#: stopped) and from DRIFT_ (bytes that changed under out_root): these are things the store HOLDS
#: that cannot be turned into one answer. Every one of them exists because of the 8/30 review.
CONFLICT_TERMINAL_DISAGREEMENT = "TERMINAL_RECORDS_DISAGREE_FOR_ONE_EVENT"
CONFLICT_VERDICT_NOT_BOUND = "STORED_VERDICT_DID_NOT_JUDGE_THE_RECORD_BESIDE_IT"
CONFLICT_RECORD_BINDING = "STORED_RECORD_DOES_NOT_MATCH_ITS_RECORDED_BINDING"
CONFLICT_UNBOUND_ADMISSION = "STORED_ADMISSION_HAD_NO_CANONICAL_SCHEDULE"
CONFLICT_VERDICT_UNREADABLE = "STORED_VERDICT_IS_NOT_SCORE_ADMISSION_VOCABULARY"

CONFLICT_MEANING = {
    CONFLICT_TERMINAL_DISAGREEMENT: "two stored records both claim a TERMINAL status for one "
                                    "event id and their scores differ. A final does not change, "
                                    "so this is a contradiction and not a race: the store serves "
                                    "NEITHER and says why. Picking a winner by a "
                                    "writer-supplied timestamp is what it used to do, and moving "
                                    "source_fetched_at_utc by one second evaded "
                                    "content_hash_conflict entirely (cluster F)",
    CONFLICT_VERDICT_NOT_BOUND: "a stored verdict does not describe the record it sits beside. "
                                "Checked at write AND at read, because the write check only "
                                "covers records this build wrote (cluster E)",
    CONFLICT_RECORD_BINDING: "the record's bytes no longer hash to the record_sha256 stored in "
                             "its own entry. The entry-file hash catches this too; this catches "
                             "it when the manifest and the id were rebuilt to cover the edit",
    CONFLICT_UNBOUND_ADMISSION: "a stored verdict on the verified side carries "
                                "CANONICAL_SCHEDULE_NOT_SUPPLIED: it was never checked against a "
                                "canonical schedule, so it is an unbound claim and not a result "
                                "(cluster A, defence in depth downstream of admit())",
    CONFLICT_VERDICT_UNREADABLE: "a stored verdict is not score_admission's vocabulary. It was "
                                 "checked at write time, so on read it means the entry was "
                                 "edited after the fact",
}


class SnapshotRefused(ValueError):
    """A read or write was refused BEFORE anything was written. Carries .problems."""

    def __init__(self, problems):
        self.problems = list(problems)
        codes = [p.get("code") for p in self.problems]
        ValueError.__init__(self, "verified_snapshot refused: %s :: %s"
                            % (codes, json.dumps(self.problems, default=str, sort_keys=True)))


class SnapshotImmutabilityViolation(RuntimeError):
    """R6. Something under out_root is not what it was, or a write would change what is there."""

    def __init__(self, message, detail=None):
        self.detail = dict(detail or {})
        RuntimeError.__init__(self, "%s :: %s" % (message, json.dumps(self.detail, default=str,
                                                                      sort_keys=True)))


class SnapshotContentConflict(RuntimeError):
    """Two stored records claim to be the same observation and are not. Read-time, loud."""

    def __init__(self, problem):
        self.problem = dict(problem)
        RuntimeError.__init__(self, "verified_snapshot content conflict: %s"
                              % json.dumps(self.problem, default=str, sort_keys=True))


class SnapshotAdmissibilityViolation(RuntimeError):
    """READ-TIME. What is stored on the verified side does not satisfy the ceiling the getters
    enforce, so there is nothing here that may be served as a result.

    Loud rather than skipped, on the store's standing precedent: a record dropped quietly makes a
    slate read like a quiet night, and that ambiguity is what invited the 8/30 search backfill.
    Carries .problems, the same shape SnapshotRefused carries at the other end.
    """

    def __init__(self, problems):
        self.problems = list(problems)
        codes = [p.get("code") for p in self.problems]
        RuntimeError.__init__(self, "verified_snapshot will not serve this: %s :: %s"
                              % (codes, json.dumps(self.problems, default=str, sort_keys=True)))


class SnapshotNotFound(KeyError):
    """A snapshot id was named and the store does not hold it."""


def _refuse(problems):
    raise SnapshotRefused(problems)


# ---------------------------------------------------------------------------------------------
# 3. SMALL HELPERS.  No clock, no network, no path leaves the root.
# ---------------------------------------------------------------------------------------------

def _canonical(obj):
    """The one byte-form of a JSON object this module hashes and writes. Deterministic."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _sha256_text(text):
    return _sha256_bytes(text.encode("utf-8"))


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


def _valid_date_et(date_et):
    """A real ET calendar date, spelled YYYY-MM-DD. '2026-02-30' is refused, not rounded."""
    if not isinstance(date_et, str) or not _DATE_ET_RE.match(date_et):
        return False
    return _utc(date_et) is not None


def _assert_within(root, path):
    """Second line of defence: nothing this module writes resolves outside out_root."""
    r = os.path.realpath(root)
    p = os.path.realpath(path)
    if p != r and not p.startswith(r + os.sep):
        _refuse([{"code": REFUSE_WRITE_OUTSIDE_ROOT, "root": r, "path": p}])
    return p


def _snapshot_dir(root, snapshot_id):
    if not isinstance(snapshot_id, str) or not _SNAPSHOT_ID_RE.match(snapshot_id):
        _refuse([{"code": REFUSE_BAD_SNAPSHOT_ID, "snapshot_id": snapshot_id}])
    d = os.path.join(root, SNAPSHOTS_DIR, snapshot_id)
    _assert_within(root, d)
    return d


def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _read_json(path):
    with open(path, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def _write_new_file(root, path, data):
    """Write bytes to a path that must not already exist. Never opens an existing file to write."""
    _assert_within(root, path)
    if os.path.exists(path):
        raise SnapshotImmutabilityViolation(
            "a file already exists where this snapshot would be written; nothing is overwritten",
            {"path": path})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


# ---------------------------------------------------------------------------------------------
# 4. THE ADMISSION ENVELOPE.  What a caller hands this store.
# ---------------------------------------------------------------------------------------------

def admission_envelope(record, verdict):
    """Pair a record with the Verdict that judged it. The constructor exists so the two key
    names cannot fork between the module that admits and the module that stores."""
    return {"record": record, "verdict": verdict}


def _verdict_of(raw):
    """(Verdict, None) or (None, reason). The store re-checks the verdict's vocabulary because a
    forged verdict is the only way a refused record could reach the verified side."""
    if isinstance(raw, sa.Verdict):
        return raw, None
    if not isinstance(raw, dict):
        return None, ("verdict is %s, not a mapping or a score_admission.Verdict"
                      % type(raw).__name__)
    disposition = raw.get("disposition")
    if disposition not in sa.DISPOSITIONS:
        return None, "disposition %r is not in score_admission.DISPOSITIONS" % (disposition,)
    codes = raw.get("reason_codes")
    if not isinstance(codes, list) or not codes:
        return None, "reason_codes must be a non-empty list; a verdict that cannot be audited is "\
                     "the 8/27 review"
    unknown = [c for c in codes if c not in sa.REASON_MEANING]
    if unknown:
        return None, "undocumented reason codes %s" % unknown
    admissible = raw.get("admissible_as")
    if admissible is not None and admissible not in sa.ADMISSIBLE_AS_VALUES:
        return None, "admissible_as %r is not in ADMISSIBLE_AS_VALUES" % (admissible,)
    detail = raw.get("detail")
    if detail is None:
        detail = {}
    if not isinstance(detail, dict):
        return None, "verdict detail is not a mapping"
    return sa.Verdict(disposition, codes, admissible, detail), None


# ---------------------------------------------------------------------------------------------
# 5. NORMALISATION.  Everything is checked before one byte is written; every problem is
#    collected, not short-circuited, so a caller's fix pass converges in one iteration.
# ---------------------------------------------------------------------------------------------

def _normalize_payloads(raw_payloads):
    """(payloads, problems). Each payload: id, bytes, GENERATED sha256, and its fetched instant."""
    problems = []
    if isinstance(raw_payloads, dict):
        items = []
        for pid, value in raw_payloads.items():
            if isinstance(value, dict):
                v = dict(value)
                v.setdefault("payload_id", pid)
                items.append(v)
            else:
                # A bare id -> text mapping cannot carry fetched_at_utc, and dropping the instant
                # is dropping half of owner rule 7. Refused rather than defaulted.
                problems.append({"code": REFUSE_PAYLOAD_SHAPE, "payload_id": pid,
                                 "detail": "a payload must be a mapping carrying raw_text or "
                                           "raw_bytes plus fetched_at_utc"})
        raw_payloads = items
    if raw_payloads is None or (isinstance(raw_payloads, (list, tuple)) and not raw_payloads):
        problems.append({"code": REFUSE_NO_PAYLOAD,
                         "detail": "owner rule 7: the raw response and its hash are preserved"})
        return [], problems
    if not isinstance(raw_payloads, (list, tuple)):
        problems.append({"code": REFUSE_PAYLOAD_SHAPE, "type": type(raw_payloads).__name__})
        return [], problems

    payloads, seen = [], {}
    for i, item in enumerate(raw_payloads):
        if not isinstance(item, dict):
            problems.append({"code": REFUSE_PAYLOAD_SHAPE, "index": i,
                             "type": type(item).__name__})
            continue
        pid = item.get("payload_id")
        if not isinstance(pid, str) or not _PAYLOAD_ID_RE.match(pid) or ".." in pid:
            problems.append({"code": REFUSE_PAYLOAD_ID, "index": i, "payload_id": pid})
            continue
        if pid in seen:
            problems.append({"code": REFUSE_DUPLICATE_PAYLOAD_ID, "payload_id": pid,
                             "indexes": [seen[pid], i]})
            continue
        body = item.get("raw_bytes")
        if body is None:
            text = item.get("raw_text")
            if not isinstance(text, str):
                problems.append({"code": REFUSE_PAYLOAD_SHAPE, "index": i, "payload_id": pid,
                                 "detail": "neither raw_bytes nor a raw_text string"})
                continue
            body = text.encode("utf-8")
        if not isinstance(body, (bytes, bytearray)):
            problems.append({"code": REFUSE_PAYLOAD_SHAPE, "index": i, "payload_id": pid,
                             "detail": "raw_bytes is not bytes"})
            continue
        body = bytes(body)
        fetched = _iso(item.get("fetched_at_utc"))
        if fetched is None:
            problems.append({"code": REFUSE_PAYLOAD_FETCHED_AT, "payload_id": pid,
                             "value": item.get("fetched_at_utc")})
            continue
        sha = _sha256_bytes(body)
        declared = item.get("sha256")
        if declared is not None and str(declared).strip().lower() != sha:
            # A hash the caller typed is not a hash of anything. Generated wins; the write stops.
            problems.append({"code": REFUSE_PAYLOAD_SHA_MISMATCH, "payload_id": pid,
                             "declared": declared, "computed": sha})
            continue
        seen[pid] = i
        payloads.append({"payload_id": pid, "sha256": sha, "n_bytes": len(body),
                         "fetched_at_utc": fetched, "source": item.get("source"),
                         "url": item.get("url"), "_body": body})
    payloads.sort(key=lambda p: p["payload_id"])
    return payloads, problems


def _payload_descriptor(payload):
    """The payload's identity as the content digest and the manifest see it — bytes excluded,
    because the sha256 stands for the bytes and the bytes are on disk beside it."""
    return {"payload_id": payload["payload_id"], "sha256": payload["sha256"],
            "n_bytes": payload["n_bytes"], "fetched_at_utc": payload["fetched_at_utc"],
            "source": payload.get("source"), "url": payload.get("url")}


def _normalize_entries(records, league, date_et, payload_shas):
    """(entries, problems). An entry is {record, verdict, sink}; the SINK is score_admission's."""
    problems, entries = [], []
    if not isinstance(records, (list, tuple)) or not records:
        problems.append({"code": REFUSE_NO_RECORDS, "n": (0 if not records else len(records))})
        return entries, problems

    seen_event_ids = {}
    for i, env in enumerate(records):
        if not isinstance(env, dict) or "record" not in env:
            problems.append({"code": REFUSE_NOT_AN_ENVELOPE, "index": i,
                             "type": type(env).__name__})
            continue
        if env.get("verdict") is None:
            problems.append({"code": REFUSE_NO_VERDICT, "index": i,
                             "detail": "score_admission.admit() produces it; this store never "
                                       "invents one"})
            continue
        verdict, why = _verdict_of(env.get("verdict"))
        if verdict is None:
            problems.append({"code": REFUSE_BAD_VERDICT, "index": i, "detail": why})
            continue

        lane = verdict.detail.get("lane")
        if lane == sa.LANE_SEARCH and verdict.disposition in sa.ADMITTING_DISPOSITIONS:
            problems.append({"code": REFUSE_SEARCH_ADMISSION, "index": i,
                             "disposition": verdict.disposition, "lane": lane})
            continue

        sink = sa.sink_for(verdict)
        # The lane table is consulted at write time rather than assumed. It cannot refuse
        # anything sink_for returns TODAY, because sink_for is total and lane-consistent — but it
        # is not decoration: mutation M07 replaces sink_for's answer with a constant, and this
        # line is what refuses the resulting SEARCH -> result_ledger write.
        if lane in sa.LANES:
            sa.assert_write_allowed(lane, sink)

        record = env["record"]
        if sink in VERIFIED_SINKS:
            bad = _verified_record_problems(record, i, league, date_et, payload_shas,
                                            seen_event_ids)
            bad.extend(_verdict_binding_problems(record, verdict, i))
            if bad:
                problems.extend(bad)
                continue
        try:
            binding = _record_binding(record)
        except (TypeError, ValueError) as e:
            problems.append({"code": REFUSE_NOT_SERIALIZABLE, "index": i, "detail": str(e)})
            continue
        entry = {"record": record, "verdict": verdict.to_dict(), "sink": sink,
                 "record_sha256": binding}
        try:
            _canonical(entry)
        except (TypeError, ValueError) as e:
            problems.append({"code": REFUSE_NOT_SERIALIZABLE, "index": i, "detail": str(e)})
            continue
        entries.append(entry)
    return entries, problems


def _record_binding(record):
    """The content hash of one record, as this store binds it. Generated, never supplied.

    Written into the entry beside the verdict and re-derived on every read, so the pair
    (record, verdict) cannot be shuffled, edited or re-paired after the fact. Raises TypeError or
    ValueError for anything JSON cannot carry, which the caller reports as ENTRY_NOT_JSON_-
    SERIALIZABLE — quarantine may hold prose, but it may not hold bytes we could not read back.
    """
    return _sha256_text(_canonical(record))


#: What an admissible_as CLAIMS about the record it was attached to. score_admission decides these
#: (admit(): VALIDATED_STATES -> FINAL, TERMINAL_STATES -> FINAL_UNVALIDATED, IN_PROGRESS ->
#: IN_PROGRESS_SNAPSHOT); the store only checks that the record beside the verdict still satisfies
#: them, which is why the sets are score_admission's own and are not retyped here.
_ADMISSIBLE_IMPLIES = {
    sa.ADMISSIBLE_FINAL: (sa.VALIDATED_STATES, True),
    sa.ADMISSIBLE_FINAL_UNVALIDATED: (sa.TERMINAL_STATES, True),
    sa.ADMISSIBLE_IN_PROGRESS: (frozenset({sa.IN_PROGRESS}), False),
}

#: Fields admit() RECORDS in the verdict's own detail about the record it judged. A verdict lifted
#: onto some other record disagrees with it here. Each pair is (detail key, how to read the record).
_VERDICT_DETAIL_BINDINGS = (
    ("event_id", lambda r: r.get("event_id")),
    ("status", lambda r: r.get("status")),
    ("terminal_verified", lambda r: bool(r.get("terminal_verified"))),
    ("scheduled_start_utc", lambda r: _iso(r.get("scheduled_start_utc"))),
)


def _verdict_binding_problems(record, verdict, index):
    """Every way the verdict beside a record can fail to BE A JUDGEMENT OF THAT RECORD.

    Cluster E, 2026-08-30 review: a stored Verdict was never checked against the record it sat
    next to, so a genuine CANONICAL verdict copied onto a fabricated record — source "web_search",
    scores invented — put a FINAL through get_verified_score with no forgery of any kind. Selftest
    S2 asserted that was impossible; it was not.

    The check is not a re-judgement (this store never re-judges: two judges is how a vocabulary
    forks). It compares the verdict against ITS OWN RECORD of what it judged, plus what its
    admissible_as necessarily implies about the record beside it.

    RESIDUAL, stated because a half-check that reads as a whole one is worse than none: admit()
    does not put the scores it saw into the verdict's detail, so a record re-fabricated to match
    the verdict on event id, status, terminal_verified and start — and re-bound with a recomputed
    record_sha256 — still passes. Closing that needs a record digest inside the Verdict, which is
    score_admission's to add. What this closes is the copy: transferring a verdict now requires
    rebuilding the record around it rather than just moving one dict.
    """
    if not isinstance(record, dict):
        return [{"code": REFUSE_VERDICT_NOT_BOUND, "index": index,
                 "detail": "a record on the verified side is not a mapping"}]
    problems = []
    for field, read in _VERDICT_DETAIL_BINDINGS:
        if field not in verdict.detail:
            continue
        judged, stored = verdict.detail.get(field), read(record)
        if judged != stored:
            problems.append({"code": REFUSE_VERDICT_NOT_BOUND, "index": index, "field": field,
                             "verdict_judged": judged, "record_says": stored})
    implied = _ADMISSIBLE_IMPLIES.get(verdict.admissible_as)
    if implied is not None:
        states, needs_scores = implied
        if record.get("status") not in states:
            problems.append({"code": REFUSE_VERDICT_NOT_BOUND, "index": index,
                             "field": "admissible_as", "admissible_as": verdict.admissible_as,
                             "implies_status_in": sorted(states),
                             "record_says": record.get("status")})
        if needs_scores and (record.get("away_score") is None
                             or record.get("home_score") is None):
            problems.append({"code": REFUSE_VERDICT_NOT_BOUND, "index": index,
                             "field": "admissible_as", "admissible_as": verdict.admissible_as,
                             "detail": "a final with no scores beside it"})
    if sa.REASON_SCHEDULE_NOT_SUPPLIED in verdict.reason_codes:
        problems.append({"code": REFUSE_UNBOUND_NO_SCHEDULE, "index": index,
                         "event_id": record.get("event_id"),
                         "reason_codes": list(verdict.reason_codes)})
    return problems


def _verified_record_problems(record, index, league, date_et, payload_shas, seen_event_ids):
    """Everything a record must satisfy to be READABLE AS A RESULT. Quarantine is exempt from all
    of it on purpose: quarantine has to be able to hold the prose that was refused."""
    problems = []
    if not isinstance(record, dict):
        return [{"code": REFUSE_ADMITTED_INVALID, "index": index,
                 "detail": "an admitted record is not a mapping"}]
    ok, record_problems = sa.validate_record(record)
    if not ok:
        problems.append({"code": REFUSE_ADMITTED_INVALID, "index": index,
                         "record_problems": record_problems})
    if sa.normalize_league(record.get("league")) != league:
        problems.append({"code": REFUSE_LEAGUE_MISMATCH, "index": index,
                         "record": record.get("league"), "snapshot": league})
    row_date = sa.scheduled_date_of(record)
    if row_date != date_et:
        problems.append({"code": REFUSE_DATE_MISMATCH, "index": index, "record": row_date,
                         "snapshot": date_et,
                         "detail": "ET date derived from the UTC instant, never sliced"})
    sha = str(record.get("raw_response_sha256") or "").strip().lower()
    if sha not in payload_shas:
        problems.append({"code": REFUSE_HASH_NOT_IN_SNAPSHOT, "index": index,
                         "raw_response_sha256": record.get("raw_response_sha256"),
                         "payload_sha256": sorted(payload_shas)})
    event_id = record.get("event_id")
    if event_id in seen_event_ids:
        problems.append({"code": REFUSE_DUPLICATE_EVENT_ID, "event_id": event_id,
                         "indexes": [seen_event_ids[event_id], index]})
    elif not problems:
        seen_event_ids[event_id] = index
    return problems


# ---------------------------------------------------------------------------------------------
# 6. CONTENT ADDRESSING.  The id is generated from the content and from nothing else.
# ---------------------------------------------------------------------------------------------

def _content_object(league, date_et, source, entries, payload_descriptors):
    """The object the snapshot id hashes. now_utc is deliberately absent — see the docstring."""
    return {"schema": SCHEMA_CONTENT,
            "league": league,
            "date_et": date_et,
            "source": source,
            "entries": sorted(entries, key=_canonical),
            "payloads": sorted(payload_descriptors, key=lambda p: p["payload_id"])}


def _content_digest(content):
    return _sha256_text(_canonical(content))


def _entries_document(snapshot_id, kind, entries):
    return {"schema": SCHEMA_ENTRIES, "snapshot_id": snapshot_id, "kind": kind,
            "n": len(entries), "entries": entries}


# ---------------------------------------------------------------------------------------------
# 7. WRITE.
# ---------------------------------------------------------------------------------------------

def write_snapshot(records, *, league, date_et, source, raw_payloads, now_utc,
                   out_root=DEFAULT_ROOT):
    """Store one immutable, content-addressed snapshot. Returns its snapshot_id.

    records       a sequence of admission envelopes, {"record": ..., "verdict": ...}, where the
                  verdict is what score_admission.admit() returned (a Verdict or its to_dict()).
                  A bare record is REFUSED: this store does not judge.
    league        one of score_admission.LEAGUES (aliases resolved)
    date_et       the ET slate date, YYYY-MM-DD, derived with zoneinfo and never sliced
    source        the provider these records came from
    raw_payloads  the raw responses to preserve: a sequence of mappings (or a mapping of
                  payload_id -> mapping) carrying raw_text or raw_bytes plus fetched_at_utc.
                  Each sha256 is GENERATED here; a caller-supplied one is checked, never trusted.
    now_utc       the instant of the WRITE. Recorded in the manifest and the write log; absent
                  from the content digest, so re-writing identical content later is a no-op.
    out_root      the only directory this module writes to.

    Idempotence and R6:
      * identical content -> the same id, nothing rewritten, one dedup line in the write log
      * an id whose stored content differs from what is being written -> RAISES
        SnapshotImmutabilityViolation, writes nothing, and REPAIRS NOTHING. A rewrite would
        erase the evidence that the store drifted, which is the thing worth knowing.
    """
    problems = []
    normalized_league = sa.normalize_league(league)
    if normalized_league is None:
        problems.append({"code": REFUSE_BAD_LEAGUE, "value": league,
                         "known": list(sa.LEAGUES)})
    if not _valid_date_et(date_et):
        problems.append({"code": REFUSE_BAD_DATE_ET, "value": date_et})
    if not isinstance(source, str) or not source.strip():
        problems.append({"code": REFUSE_BAD_SOURCE, "value": source})
    written_at = _iso(now_utc)
    if written_at is None:
        problems.append({"code": REFUSE_BAD_NOW, "field": "now_utc", "value": str(now_utc)})

    payloads, payload_problems = _normalize_payloads(raw_payloads)
    problems.extend(payload_problems)
    entries, entry_problems = _normalize_entries(
        records, normalized_league, date_et, {p["sha256"] for p in payloads})
    problems.extend(entry_problems)
    if problems:
        _refuse(problems)

    descriptors = [_payload_descriptor(p) for p in payloads]
    content = _content_object(normalized_league, date_et, source, entries, descriptors)
    digest = _content_digest(content)
    snapshot_id = SNAPSHOT_ID_PREFIX + digest

    root = os.path.abspath(out_root)
    verified = [e for e in content["entries"] if e["sink"] in VERIFIED_SINKS]
    quarantined = [e for e in content["entries"] if e["sink"] not in VERIFIED_SINKS]

    if _existing_snapshot_blocks_write(root, snapshot_id, digest):
        _append_write_log(root, snapshot_id, normalized_league, date_et, source, written_at,
                          content, verified, quarantined, descriptors, deduplicated=True)
        return snapshot_id

    _commit(root, snapshot_id, digest, normalized_league, date_et, source, written_at,
            verified, quarantined, payloads, descriptors)
    _append_write_log(root, snapshot_id, normalized_league, date_et, source, written_at,
                      content, verified, quarantined, descriptors, deduplicated=False)
    return snapshot_id


def _existing_snapshot_blocks_write(root, snapshot_id, digest):
    """True when the snapshot is already stored with EXACTLY this content (a no-op write).

    Raises when something is there and it is not this content. The comparison is made against
    what is ON DISK, re-hashed, not against the manifest's own claims — the manifest is part of
    what can drift.
    """
    directory = _snapshot_dir(root, snapshot_id)
    if not os.path.isdir(directory):
        return False
    report = verify_snapshot(snapshot_id, root=root)
    identical = bool(report["ok"]) and report.get("content_sha256") == digest
    if not identical:
        raise SnapshotImmutabilityViolation(
            "R6: a snapshot already exists at this id and its stored content is not the content "
            "being written. Nothing was written and nothing was repaired — repairing would erase "
            "the evidence that the store drifted",
            {"snapshot_id": snapshot_id, "expected_content_sha256": digest,
             "on_disk_content_sha256": report.get("content_sha256"), "drift": report["drift"]})
    return True


def _commit(root, snapshot_id, digest, league, date_et, source, written_at,
            verified, quarantined, payloads, descriptors):
    """Stage the whole snapshot beside the store, then rename it into place in one step."""
    staging = os.path.join(root, INCOMING_DIR, "%s_%d" % (snapshot_id[:20], os.getpid()))
    _assert_within(root, staging)
    if os.path.exists(staging):
        shutil.rmtree(staging)
    destination = _snapshot_dir(root, snapshot_id)
    try:
        os.makedirs(staging)
        files = {}
        for name, kind, entries in ((VERIFIED_NAME, "verified", verified),
                                    (QUARANTINE_NAME, "quarantine", quarantined)):
            body = _canonical(_entries_document(snapshot_id, kind, entries)).encode("utf-8")
            _write_new_file(root, os.path.join(staging, name), body)
            files[name] = {"sha256": _sha256_bytes(body), "n_bytes": len(body)}
        for payload in payloads:
            _write_new_file(root, os.path.join(staging, RAW_DIR, payload["payload_id"]),
                            payload["_body"])
        manifest = {
            "schema": SCHEMA_MANIFEST,
            "snapshot_id": snapshot_id,
            "content_sha256": digest,
            "league": league,
            "date_et": date_et,
            "source": source,
            "written_at_utc": written_at,
            "n_entries": len(verified) + len(quarantined),
            "n_verified": len(verified),
            "n_quarantined": len(quarantined),
            "dispositions": _disposition_counts(verified + quarantined),
            "verified_event_ids": sorted(
                str(e["record"].get("event_id")) for e in verified
                if isinstance(e["record"], dict)),
            "files": files,
            "payloads": [dict(d, path="%s/%s" % (RAW_DIR, d["payload_id"])) for d in descriptors],
            "rule": "the snapshot id is the sha256 of this snapshot's content (entries plus "
                    "payload descriptors). verify_snapshot() re-hashes the bytes on disk rather "
                    "than believing this manifest; a sha recorded once is an observation at a "
                    "moment, not a permanent fact (2026-08-30, the archive that rewrote two "
                    "historical daily files under unchanged filenames)",
        }
        _write_new_file(root, os.path.join(staging, MANIFEST_NAME),
                        _canonical(manifest).encode("utf-8"))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        try:
            os.rename(staging, destination)
        except OSError as e:
            raise SnapshotImmutabilityViolation(
                "the snapshot directory appeared between the immutability check and the commit; "
                "nothing was overwritten",
                {"snapshot_id": snapshot_id, "error": str(e)})
    finally:
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)


def _disposition_counts(entries):
    counts = {}
    for e in entries:
        d = e["verdict"].get("disposition")
        counts[d] = counts.get(d, 0) + 1
    return counts


def _append_write_log(root, snapshot_id, league, date_et, source, written_at, content,
                      verified, quarantined, descriptors, deduplicated):
    """Append-only journal of every write ATTEMPT, deduplicated ones included.

    The journal is not the index: the getters read the snapshot directories, because an index is
    a second copy of the truth and a second copy is a thing that can disagree. This exists so a
    reviewer can see that a rewrite was attempted and refused-as-a-no-op.
    """
    path = os.path.join(root, WRITE_LOG_NAME)
    _assert_within(root, path)
    os.makedirs(root, exist_ok=True)
    line = {"schema": SCHEMA_WRITE_LOG, "snapshot_id": snapshot_id, "league": league,
            "date_et": date_et, "source": source, "written_at_utc": written_at,
            "n_verified": len(verified), "n_quarantined": len(quarantined),
            "payload_sha256": [d["sha256"] for d in descriptors],
            "deduplicated": bool(deduplicated)}
    with open(path, "a") as fh:
        fh.write(_canonical(line) + "\n")


# ---------------------------------------------------------------------------------------------
# 8. VERIFY.  Re-derive; do not trust.
# ---------------------------------------------------------------------------------------------

def verify_snapshot(snapshot_id, *, root=DEFAULT_ROOT):
    """Re-hash what is on disk and REPORT drift. Never repairs, never raises on drift.

    Returns {"schema", "snapshot_id", "ok", "drift" [ {code, ...} ], "content_sha256" (as
    RE-DERIVED from disk, None when it could not be derived), "checked" {counts}}.

    Written because owner rule 7's hash is only worth having if something ever recomputes it.
    On 2026-08-30 an admitted archive rewrote two historical daily files under unchanged
    filenames; nothing noticed, because nothing looked.
    """
    directory = _snapshot_dir(os.path.abspath(root), snapshot_id)
    drift = []
    checked = {"payloads": 0, "entry_files": 0, "verified_records": 0}
    report = {"schema": SCHEMA_VERIFICATION, "snapshot_id": snapshot_id, "ok": False,
              "drift": drift, "content_sha256": None, "checked": checked,
              "path": directory}

    manifest_path = os.path.join(directory, MANIFEST_NAME)
    if not os.path.isfile(manifest_path):
        drift.append({"code": DRIFT_MANIFEST_MISSING, "path": manifest_path})
        return report
    try:
        manifest = _read_json(manifest_path)
    except Exception as e:
        drift.append({"code": DRIFT_MANIFEST_MISSING, "path": manifest_path, "detail": str(e)})
        return report

    documents = {}
    for name in (VERIFIED_NAME, QUARANTINE_NAME):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            drift.append({"code": DRIFT_FILE_MISSING, "file": name, "path": path})
            continue
        body = _read_bytes(path)
        checked["entry_files"] += 1
        declared = (manifest.get("files") or {}).get(name) or {}
        actual = _sha256_bytes(body)
        if declared.get("sha256") != actual:
            drift.append({"code": DRIFT_ENTRY_FILE_BYTES, "file": name,
                          "declared": declared.get("sha256"), "actual": actual})
        try:
            documents[name] = json.loads(body.decode("utf-8"))
        except Exception as e:
            drift.append({"code": DRIFT_ENTRY_FILE_BYTES, "file": name, "detail": str(e)})

    actual_payloads, actual_shas = [], set()
    for declared in manifest.get("payloads") or []:
        payload_id = declared.get("payload_id")
        path = os.path.join(directory, RAW_DIR, str(payload_id))
        if not os.path.isfile(path):
            drift.append({"code": DRIFT_FILE_MISSING, "payload_id": payload_id, "path": path})
            continue
        body = _read_bytes(path)
        checked["payloads"] += 1
        actual = _sha256_bytes(body)
        if actual != declared.get("sha256"):
            drift.append({"code": DRIFT_PAYLOAD_BYTES, "payload_id": payload_id,
                          "declared": declared.get("sha256"), "actual": actual,
                          "detail": "the bytes changed under an unchanged filename"})
        actual_shas.add(actual)
        actual_payloads.append({"payload_id": payload_id, "sha256": actual,
                                "n_bytes": len(body),
                                "fetched_at_utc": declared.get("fetched_at_utc"),
                                "source": declared.get("source"), "url": declared.get("url")})

    entries = []
    for name in (VERIFIED_NAME, QUARANTINE_NAME):
        entries.extend((documents.get(name) or {}).get("entries") or [])
    if documents:
        content = _content_object(manifest.get("league"), manifest.get("date_et"),
                                  manifest.get("source"), entries, actual_payloads)
        report["content_sha256"] = _content_digest(content)
        if SNAPSHOT_ID_PREFIX + report["content_sha256"] != snapshot_id:
            drift.append({"code": DRIFT_ID_NOT_CONTENT, "snapshot_id": snapshot_id,
                          "recomputed": SNAPSHOT_ID_PREFIX + report["content_sha256"],
                          "detail": "the id is the hash of the content, so the directory name "
                                    "has stopped being true"})

    for entry in (documents.get(VERIFIED_NAME) or {}).get("entries") or []:
        record = entry.get("record")
        if not isinstance(record, dict):
            continue
        checked["verified_records"] += 1
        sha = str(record.get("raw_response_sha256") or "").strip().lower()
        if sha not in actual_shas:
            drift.append({"code": DRIFT_RECORD_HASH_UNCOVERED,
                          "event_id": record.get("event_id"), "raw_response_sha256": sha})

    report["ok"] = not drift
    return report


# ---------------------------------------------------------------------------------------------
# 8b. THE READ PATH RE-DERIVES.  Cluster D of the 2026-08-30 review: verify_snapshot() had zero
#     read-path callers, so every hash in section 8 was decoration from the analysis layer's side
#     and records.json edited in place was served as truth. Nothing below trusts the manifest.
# ---------------------------------------------------------------------------------------------

#: Payload bytes are the expensive half of a verification, so they are re-hashed only when the
#: filesystem says a file changed. The key is (path -> size, mtime_ns) for every file in the
#: snapshot. RESIDUAL, named rather than implied: an edit that preserves both size and mtime is
#: not seen by this cache. The entry files are re-hashed on EVERY read regardless (below), because
#: they are being read to be served anyway, so the record bytes never depend on this shortcut.
_PAYLOAD_INTEGRITY_CACHE = {}


def _fs_signature(directory):
    """Every file under a snapshot, with its size and mtime_ns. Not a clock read: this is what the
    filesystem already recorded about bytes that are already there."""
    signature = []
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames.sort()
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            try:
                st = os.stat(path)
            except OSError:
                signature.append((os.path.relpath(path, directory), None, None))
                continue
            signature.append((os.path.relpath(path, directory), st.st_size, st.st_mtime_ns))
    return tuple(signature)


def _payload_drift(manifest, directory):
    """Re-hash every stored raw payload against the sha256 the manifest recorded for it."""
    drift = []
    for declared in manifest.get("payloads") or []:
        payload_id = declared.get("payload_id")
        path = os.path.join(directory, RAW_DIR, str(payload_id))
        if not os.path.isfile(path):
            drift.append({"code": DRIFT_FILE_MISSING, "payload_id": payload_id, "path": path})
            continue
        # Deliberately not spelled the way verify_snapshot spells the same comparison: the
        # mutation suite edits ONE occurrence of a pattern, so two identically worded checks
        # would leave whichever one it did not reach untested and looking tested.
        rehashed = _sha256_bytes(_read_bytes(path))
        if rehashed != declared.get("sha256"):
            drift.append({"code": DRIFT_PAYLOAD_BYTES, "payload_id": payload_id,
                          "declared": declared.get("sha256"), "actual": rehashed,
                          "detail": "the bytes changed under an unchanged filename"})
    return drift


def _cached_payload_drift(manifest, directory):
    key = os.path.realpath(directory)
    signature = _fs_signature(directory)
    hit = _PAYLOAD_INTEGRITY_CACHE.get(key)
    if hit is not None and hit[0] == signature:
        return list(hit[1])
    drift = _payload_drift(manifest, directory)
    _PAYLOAD_INTEGRITY_CACHE[key] = (signature, list(drift))
    return drift


def _read_integrity(manifest, root):
    """The drift list a getter must clear BEFORE it serves anything out of this snapshot.

    The entry files are re-hashed here on every call, uncached, and the content id is recomputed
    from the bytes that were just read — so a manifest rewritten to cover an edited records.json
    still fails, because the id is the hash of the content and the directory name stops being
    true. Only the payload half consults the size/mtime cache.
    """
    snapshot_id = manifest.get("snapshot_id")
    directory = _snapshot_dir(os.path.abspath(root), snapshot_id)
    drift, entries = [], []
    for name in (VERIFIED_NAME, QUARANTINE_NAME):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            drift.append({"code": DRIFT_FILE_MISSING, "file": name, "path": path})
            continue
        body = _read_bytes(path)
        declared = (manifest.get("files") or {}).get(name) or {}
        seen = _sha256_bytes(body)                       # named apart from verify_snapshot's
        if declared.get("sha256") != seen:               # `actual`, for the same reason as above
            drift.append({"code": DRIFT_ENTRY_FILE_BYTES, "file": name,
                          "declared": declared.get("sha256"), "actual": seen,
                          "detail": "a stored record was edited after the fact"})
        try:
            entries.extend((json.loads(body.decode("utf-8")) or {}).get("entries") or [])
        except Exception as e:                                  # noqa: BLE001 — reported, not hidden
            drift.append({"code": DRIFT_ENTRY_FILE_BYTES, "file": name, "detail": str(e)})
    descriptors = [{k: d.get(k) for k in ("payload_id", "sha256", "n_bytes", "fetched_at_utc",
                                          "source", "url")}
                   for d in manifest.get("payloads") or []]
    recomputed = _content_digest(_content_object(manifest.get("league"), manifest.get("date_et"),
                                                 manifest.get("source"), entries, descriptors))
    if SNAPSHOT_ID_PREFIX + recomputed != snapshot_id:
        drift.append({"code": DRIFT_ID_NOT_CONTENT, "snapshot_id": snapshot_id,
                      "recomputed": SNAPSHOT_ID_PREFIX + recomputed,
                      "detail": "the id is the hash of the content, so the directory name has "
                                "stopped being true"})
    drift.extend(_cached_payload_drift(manifest, directory))
    return drift


def _assert_readable(manifest, root):
    """Nothing is served out of a snapshot whose bytes are not what they were (cluster D)."""
    drift = _read_integrity(manifest, root)
    if drift:
        raise SnapshotImmutabilityViolation(
            "this snapshot's bytes are not what they were, so nothing in it may be served as a "
            "result. verify_snapshot() reports the same drift and repairs none of it",
            {"snapshot_id": manifest.get("snapshot_id"), "drift": drift})


def _assert_servable(entry, snapshot_id):
    """The ceiling the getters enforce on one stored VERIFIED entry, re-checked on every read.

    Clusters E and A of the 8/30 review. The write path checks the same two things, and that is
    not redundancy: the write check only ever covers records this build wrote, and the whole
    premise of this module is that what is on disk is an observation at a moment rather than a
    permanent fact.
    """
    problems = []
    record = entry.get("record")
    verdict, why = _verdict_of(entry.get("verdict"))
    if verdict is None:
        problems.append({"code": CONFLICT_VERDICT_UNREADABLE, "snapshot_id": snapshot_id,
                         "detail": why})
    else:
        for p in _verdict_binding_problems(record, verdict, None):
            code = (CONFLICT_UNBOUND_ADMISSION if p["code"] == REFUSE_UNBOUND_NO_SCHEDULE
                    else CONFLICT_VERDICT_NOT_BOUND)
            problems.append(dict(p, code=code, snapshot_id=snapshot_id))
    try:
        binding = _record_binding(record)
    except (TypeError, ValueError) as e:
        binding, problems = None, problems + [{"code": CONFLICT_RECORD_BINDING,
                                               "snapshot_id": snapshot_id, "detail": str(e)}]
    if binding is not None and entry.get("record_sha256") != binding:
        problems.append({"code": CONFLICT_RECORD_BINDING, "snapshot_id": snapshot_id,
                         "event_id": record.get("event_id") if isinstance(record, dict) else None,
                         "stored": entry.get("record_sha256"), "recomputed": binding})
    if problems:
        raise SnapshotAdmissibilityViolation(problems)


# ---------------------------------------------------------------------------------------------
# 9. READ.  The store's directories are the truth; nothing here consults an index.
# ---------------------------------------------------------------------------------------------

def list_snapshots(root=DEFAULT_ROOT):
    """Every stored manifest, oldest write first. Raises on a snapshot with no manifest: a
    partial write must not be served around silently, because 'fewer games' reads like 'a quiet
    night' and that is the shape of the 8/30 absence that invited a backfill."""
    base = os.path.join(os.path.abspath(root), SNAPSHOTS_DIR)
    if not os.path.isdir(base):
        return []
    manifests = []
    for name in sorted(os.listdir(base)):
        directory = os.path.join(base, name)
        if not os.path.isdir(directory) or name.startswith("."):
            continue
        if not _SNAPSHOT_ID_RE.match(name):
            raise SnapshotImmutabilityViolation(
                "a directory in the snapshot store is not a snapshot id generated by this store",
                {"name": name, "path": directory})
        manifest_path = os.path.join(directory, MANIFEST_NAME)
        if not os.path.isfile(manifest_path):
            raise SnapshotImmutabilityViolation(
                "a snapshot directory has no manifest: a partial write or a deletion. The store "
                "refuses to serve around it",
                {"snapshot_id": name, "code": DRIFT_MANIFEST_MISSING})
        manifests.append(_read_json(manifest_path))
    manifests.sort(key=lambda m: (str(m.get("written_at_utc")), str(m.get("snapshot_id"))))
    return manifests


def get_source_manifest(snapshot_id, *, root=DEFAULT_ROOT):
    """The snapshot's manifest: per-payload sha256, byte count and fetched instant (owner rule 7),
    the files' hashes, and the content hash the id is made of.

    ANALYSIS TOOL SURFACE. Read-only, like the other two. The manifest is re-derived against the
    bytes on disk before it is handed over: a manifest is a claim about a snapshot, and cluster D
    is precisely the case of a claim nobody ever recomputed.
    """
    sa.assert_tool_allowed("get_source_manifest")
    directory = _snapshot_dir(os.path.abspath(root), snapshot_id)
    path = os.path.join(directory, MANIFEST_NAME)
    if not os.path.isfile(path):
        raise SnapshotNotFound(snapshot_id)
    manifest = _read_json(path)
    _assert_readable(manifest, root)
    return manifest


def _entries_of(manifest, kind, root):
    """One snapshot's entries, AFTER the snapshot has been re-derived from its own bytes.

    This is the single choke point every getter reads through, which is why the read-path
    verification hangs here: cluster D was not a missing check but a check with no caller.
    """
    directory = _snapshot_dir(os.path.abspath(root), manifest["snapshot_id"])
    name = VERIFIED_NAME if kind == "verified" else QUARANTINE_NAME
    path = os.path.join(directory, name)
    if not os.path.isfile(path):
        raise SnapshotImmutabilityViolation(
            "a snapshot is missing an entry file the manifest names",
            {"snapshot_id": manifest["snapshot_id"], "file": name, "code": DRIFT_FILE_MISSING})
    _assert_readable(manifest, root)
    return (_read_json(path) or {}).get("entries") or []


#: Sorts strictly before any real instant, for a candidate whose observation instant will not
#: parse. validate_record makes that unreachable on the verified side; it is here so the sort
#: cannot raise instead of ordering.
_UNDATED = dt.datetime(1, 1, 1, tzinfo=UTC)


def _observation_order(candidate):
    """The instant the OBSERVATION was made, then the write instant, then the id.

    Cluster C, and the finding five separate review lenses reached independently: this used to be
    written_at_utc — the STORE ACTION — while the docstring beside it said observation. A stale
    IN_PROGRESS re-written after a validated CLOSED then superseded the final, and
    get_verified_score returned a non-final for a settled game. source_fetched_at_utc is when the
    provider was actually seen; written_at_utc is only when someone got round to storing it.

    Compared as datetimes, never as ISO strings: '…:00.5Z' is a LATER instant than '…:00Z' and a
    SMALLER string. The write instant and the id are tiebreakers only, so the order is total.
    """
    return (_utc(candidate["record"].get("source_fetched_at_utc")) or _UNDATED,
            str(candidate.get("written_at_utc")), str(candidate.get("snapshot_id")))


def _verified_candidates(root, event_id=None, date_et=None, league=None):
    """Every stored VERIFIED entry matching the filter, latest OBSERVATION last.

    Each entry clears _assert_servable first: a stored verdict that did not judge the record
    beside it, or one that was never checked against a canonical schedule, is not a result no
    matter which file it is filed in.
    """
    normalized = sa.normalize_league(league) if league is not None else None
    out = []
    for manifest in list_snapshots(root):
        if date_et is not None and manifest.get("date_et") != date_et:
            continue
        if normalized is not None and sa.normalize_league(manifest.get("league")) != normalized:
            continue
        for entry in _entries_of(manifest, "verified", root):
            record = entry.get("record")
            if not isinstance(record, dict):
                continue
            if event_id is not None and record.get("event_id") != event_id:
                continue
            _assert_servable(entry, manifest["snapshot_id"])
            out.append({"record": record, "verdict": entry.get("verdict"),
                        "snapshot_id": manifest["snapshot_id"],
                        "observed_at_utc": _iso(record.get("source_fetched_at_utc")),
                        "written_at_utc": manifest.get("written_at_utc")})
    out.sort(key=_observation_order)
    return out


def _resolve(candidates):
    """The record a caller should read, from several observations of one event.

    A later OBSERVATION supersedes an earlier one — IN_PROGRESS fetched at 18:45 then CLOSED
    fetched at 20:30 is two honest observations and both are kept on disk. Three rules, each one
    an incident:

    1. Two records claiming the SAME source and the SAME fetched instant with DIFFERENT content
       hashes are not two observations; that is an archive that changed under one key, and it
       RAISES rather than picking a winner (owner rule 7, 2026-08-30).
    2. A FINAL DOES NOT CHANGE. Two records both claiming a terminal status for one event with
       different scores are a CONTRADICTION, and the store serves NEITHER — picking between them
       by any timestamp is how a fabricated final would win. content_hash_conflict does not catch
       this shape: move source_fetched_at_utc by one second and the keys stop matching
       (cluster F).
    3. A terminal observation is never superseded by a non-terminal one. A canonical feed that
       regresses a CLOSED game to IN_PROGRESS is a provider bug, and the contract is explicit
       that elapsed time never converts one status into another (cluster C, and owner rule 8 read
       in the direction nobody had tested).
    """
    if not candidates:
        return None
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            conflict, problem = sa.content_hash_conflict(candidates[i]["record"],
                                                         candidates[j]["record"])
            if conflict:
                raise SnapshotContentConflict(dict(
                    problem, snapshot_ids=[candidates[i]["snapshot_id"],
                                           candidates[j]["snapshot_id"]],
                    event_id=candidates[i]["record"].get("event_id")))
    terminals = [c for c in candidates if c["record"].get("status") in sa.TERMINAL_STATES]
    scores = sorted({(c["record"].get("away_score"), c["record"].get("home_score"))
                     for c in terminals})
    if len(scores) > 1:
        raise SnapshotContentConflict({
            "code": CONFLICT_TERMINAL_DISAGREEMENT,
            "event_id": candidates[0]["record"].get("event_id"),
            "scores": [list(s) for s in scores],
            "snapshot_ids": [c["snapshot_id"] for c in terminals],
            "observed_at_utc": [c.get("observed_at_utc") for c in terminals],
            "detail": "a final does not change. Two terminal records for one event disagree, so "
                      "this store serves neither and names both",
        })
    if terminals:
        candidates = terminals
    return sorted(candidates, key=_observation_order)[-1]["record"]


def get_verified_score(event_id, *, root=DEFAULT_ROOT):
    """The verified record for one event, or None when the store holds none.

    ANALYSIS TOOL SURFACE. Returns ONLY records whose stored verdict routed them to the board or
    the result ledger. A quarantined record is not reachable from here at any cost — that is the
    whole separation, and get_quarantine() is the deliberate act that reads the other side.

    A malformed event id RAISES rather than returning None: 'no such id' and 'that is not an id'
    are different facts, and letting the second read as the first is how an unbound claim becomes
    a quiet absence.
    """
    sa.assert_tool_allowed("get_verified_score")
    ok, problems = sa.validate_event_id(event_id)
    if not ok:
        _refuse(problems)
    return _resolve(_verified_candidates(root, event_id=event_id))


def get_verified_scores(date, league, *, root=DEFAULT_ROOT):
    """Every verified record for one ET date and league, sorted by event id.

    ANALYSIS TOOL SURFACE. An empty list means the store holds nothing for that slate; it does
    NOT mean there were no games. A down lane says so with score_admission.lane_down(), and this
    module cannot manufacture that statement on the caller's behalf.
    """
    sa.assert_tool_allowed("get_verified_scores")
    problems = []
    if not _valid_date_et(date):
        problems.append({"code": REFUSE_BAD_DATE_ET, "value": date})
    if sa.normalize_league(league) is None:
        problems.append({"code": REFUSE_BAD_LEAGUE, "value": league, "known": list(sa.LEAGUES)})
    if problems:
        _refuse(problems)
    grouped = {}
    for candidate in _verified_candidates(root, date_et=date, league=league):
        grouped.setdefault(candidate["record"].get("event_id"), []).append(candidate)
    return [_resolve(grouped[eid]) for eid in sorted(grouped, key=str)]


def get_quarantine(date, league, *, root=DEFAULT_ROOT):
    """Everything the store REFUSED for one ET date and league, with the verdict that refused it.

    NOT on the analysis tool surface, deliberately: reading quarantine is an audit act, not an
    analysis one, and score_admission.assert_tool_allowed('get_quarantine') raises by design.

    Returns envelopes, never bare records — a refused claim without the reason it was refused is
    exactly the artifact that got published on 2026-08-27. The 'record' may be anything that was
    handed in, including the bare sentence a search returned; quarantine must be able to hold the
    thing that was refused.
    """
    problems = []
    if not _valid_date_et(date):
        problems.append({"code": REFUSE_BAD_DATE_ET, "value": date})
    if sa.normalize_league(league) is None:
        problems.append({"code": REFUSE_BAD_LEAGUE, "value": league, "known": list(sa.LEAGUES)})
    if problems:
        _refuse(problems)
    normalized = sa.normalize_league(league)
    out = []
    for manifest in list_snapshots(root):
        if manifest.get("date_et") != date:
            continue
        if sa.normalize_league(manifest.get("league")) != normalized:
            continue
        for entry in _entries_of(manifest, "quarantine", root):
            out.append({"record": entry.get("record"), "verdict": entry.get("verdict"),
                        "sink": entry.get("sink"), "snapshot_id": manifest["snapshot_id"],
                        "written_at_utc": manifest.get("written_at_utc")})
    return out


# ---------------------------------------------------------------------------------------------
# 10. FIXTURES.  Every event id declares provenance, the way result_binding_gate.PK_PROVENANCE
#     does: a gate fixture carrying an undeclared identifier is a contamination vector itself.
#     The ids themselves are score_admission's, so the two modules cannot fork on them.
# ---------------------------------------------------------------------------------------------

#: The 8/30 clock, mirroring score_admission's incident constants.
_START_1215ET = "2026-08-30T16:15:00Z"    # MIA@WSH first pitch
_START_1335ET = "2026-08-30T17:35:00Z"    # BOS@NYY and COL@ATL first pitch
_NOW_1330ET = "2026-08-30T17:30:00Z"      # the instant the three finals arrived
_EVENING = "2026-08-30T23:00:00Z"         # 19:00 ET, past every window used below
_LATE = "2026-08-31T00:30:00Z"            # 20:30 ET on 08-30. THE ET-crossing instant.

#: Ids are imported, not minted. FIXTURE_PROVENANCE lives in score_admission and is asserted
#: below to still cover every id this module's fixtures touch.
_FIXTURE_EVENT_IDS = (sa.EID_MIAWSH, sa.EID_BOSNYY, sa.EID_COLATL, sa.EID_WNBA)


class _FixtureAborted(Exception):
    """A fixture the selftest cannot continue past. The NAMED failure is already recorded, so the
    outer handler must not re-report it as an unclassified explosion — the mutation suite counts
    "died on a named assertion" and "blew up somewhere" as different outcomes (cluster O)."""


def _rebuild_snapshot_on_disk(root, snapshot_id, mutate):
    """FIXTURE MACHINERY. Rewrite a stored snapshot's verified entries and then rebuild the
    manifest and the directory name AROUND the edit, so the store is self-consistent on disk.

    This is the adversary the read-path checks exist for: anyone who can edit records.json can
    edit the manifest beside it, and the 2026-08-30 mutable archive did exactly that under
    unchanged filenames. A fixture that only edits the bytes proves the file hash and nothing
    else. Returns the snapshot's new id.
    """
    directory = os.path.join(root, SNAPSHOTS_DIR, snapshot_id)
    manifest = _read_json(os.path.join(directory, MANIFEST_NAME))
    documents = {name: _read_json(os.path.join(directory, name))
                 for name in (VERIFIED_NAME, QUARANTINE_NAME)}
    documents[VERIFIED_NAME]["entries"] = [mutate(dict(e)) for e in
                                           documents[VERIFIED_NAME].get("entries") or []]
    entries = []
    for name in (VERIFIED_NAME, QUARANTINE_NAME):
        entries.extend(documents[name].get("entries") or [])
    descriptors = [{k: d.get(k) for k in ("payload_id", "sha256", "n_bytes", "fetched_at_utc",
                                          "source", "url")}
                   for d in manifest.get("payloads") or []]
    digest = _content_digest(_content_object(manifest.get("league"), manifest.get("date_et"),
                                             manifest.get("source"), entries, descriptors))
    new_id = SNAPSHOT_ID_PREFIX + digest
    files = {}
    for name in (VERIFIED_NAME, QUARANTINE_NAME):
        documents[name]["snapshot_id"] = new_id
        body = _canonical(documents[name]).encode("utf-8")
        with open(os.path.join(directory, name), "wb") as fh:
            fh.write(body)
        files[name] = {"sha256": _sha256_bytes(body), "n_bytes": len(body)}
    manifest.update({"snapshot_id": new_id, "content_sha256": digest, "files": files})
    with open(os.path.join(directory, MANIFEST_NAME), "wb") as fh:
        fh.write(_canonical(manifest).encode("utf-8"))
    os.rename(directory, os.path.join(root, SNAPSHOTS_DIR, new_id))
    return new_id


def _payload(payload_id, text, fetched_at_utc, source=sa.PROVIDER_MLB_STATSAPI):
    return {"payload_id": payload_id, "raw_text": text, "fetched_at_utc": fetched_at_utc,
            "source": source, "url": "statsapi:/api/v1/schedule?sportId=1&date=2026-08-30"}


def _record(event_id, away, home, start, status, away_score=None, home_score=None,
            *, sha, league="MLB", source=sa.PROVIDER_MLB_STATSAPI, fetched=_EVENING):
    """A normalized record. terminal_verified is GENERATED; the content hash is the payload's."""
    return {"event_id": event_id, "league": league, "away_team_id": away, "home_team_id": home,
            "scheduled_start_utc": start, "status": status,
            "away_score": away_score, "home_score": home_score,
            "terminal_verified": sa.terminal_verified_for(status),
            "source": source, "source_fetched_at_utc": fetched, "raw_response_sha256": sha}


def _admit(record, *, now_utc, lane, schedule, corroborations=0):
    return admission_envelope(record, sa.admit(record, now_utc=now_utc, lane=lane,
                                               canonical_schedule=schedule,
                                               corroborations=corroborations))


# ---------------------------------------------------------------------------------------------
# 11. SELFTEST.
# ---------------------------------------------------------------------------------------------

def selftest():
    """Fixtures are named for the incident, not for a test number."""
    import tempfile

    f = []
    seen_refusals = set()
    seen_drift = set()
    seen_conflicts = set()
    roots = []

    def new_root(label):
        d = tempfile.mkdtemp(prefix="verified_snapshot_%s_" % label)
        roots.append(d)
        return d

    def expect_refusal(label, fn, code):
        try:
            fn()
            f.append("%s: expected refusal %s, the write was ACCEPTED" % (label, code))
        except SnapshotRefused as e:
            codes = [p.get("code") for p in e.problems]
            seen_refusals.update(codes)
            if code not in codes:
                f.append("%s: expected %s, got %s" % (label, code, codes))
        except Exception as e:
            f.append("%s: expected SnapshotRefused(%s), got %s: %s"
                     % (label, code, type(e).__name__, e))

    def expect_conflict(label, fn, code, exc=SnapshotContentConflict):
        """A READ that must refuse to answer. The counterpart of expect_refusal at the other end
        of the store, and the half the 8/30 review found had almost no fixtures."""
        try:
            served = fn()
            f.append("%s: expected %s, the store SERVED %r" % (label, code, served))
        except exc as e:
            got = [p.get("code") for p in getattr(e, "problems", [getattr(e, "problem", {})])]
            seen_conflicts.update(c for c in got if c)
            if code not in got:
                f.append("%s: expected %s, got %s" % (label, code, got))
        except Exception as e:
            f.append("%s: expected %s(%s), got %s: %s"
                     % (label, exc.__name__, code, type(e).__name__, e))

    def must_write(label, *args, **kwargs):
        """A fixture write that is supposed to succeed. A mutant that makes the store refuse its
        own happy path must die on a NAMED assertion, not on a bare traceback the mutation suite
        can only report as an unclassified error (cluster O)."""
        try:
            return write_snapshot(*args, **kwargs)
        except (SnapshotRefused, sa.LaneViolation) as e:
            f.append("%s: the store REFUSED or MIS-ROUTED a write it must accept: %s: %s"
                     % (label, type(e).__name__, str(e)[:400]))
            raise _FixtureAborted(label)

    try:
        # ---- S0. POSTURE AND VOCABULARY ---------------------------------------------------
        if MODULE_ID != os.path.basename(__file__)[:-3]:
            f.append("S0: MODULE_ID %r does not name this file" % MODULE_ID)
        if ALLOW_DIRECT_HTTP is not False:
            f.append("S0: ALLOW_DIRECT_HTTP is not False")
        own_source = open(__file__).read()
        # Needles are built by concatenation so these checks cannot match themselves.
        net = [n for n in ["requests" + ".get", "url" + "open", "http" + ".client",
                           "socket" + ".socket", "urllib" + ".request"] if n in own_source]
        if net:
            f.append("S0: this module claims no network I/O but its source contains %s" % net)
        clock = [n for n in ["datetime." + "now", "utc" + "now", "time." + "time",
                             "date." + "today"] if n in own_source]
        if clock:
            f.append("S0: this module claims to read no clock but its source contains %s — a "
                     "store that stamps its own time can date an artifact later than the fetch "
                     "it describes" % clock)
        if tuple(ANALYSIS_TOOL_SURFACE) != ("get_verified_score", "get_verified_scores",
                                            "get_source_manifest"):
            f.append("S0: the analysis tool surface drifted: %r" % (ANALYSIS_TOOL_SURFACE,))
        for name in ANALYSIS_TOOL_SURFACE:
            if not callable(globals().get(name)):
                f.append("S0: %s is on the analysis tool surface and is not defined here" % name)
        try:
            sa.assert_tool_allowed("get_quarantine")
            f.append("S0: get_quarantine is on the analysis tool surface — reading quarantine "
                     "must stay a deliberate audit act, not an analysis call")
        except sa.LaneViolation:
            pass
        if VERIFIED_SINKS != frozenset({sa.SINK_BOARD, sa.SINK_RESULT_LEDGER}):
            f.append("S0: VERIFIED_SINKS drifted from the two readable-as-result sinks")
        if sa.SINK_QUARANTINE in VERIFIED_SINKS:
            f.append("S0: quarantine is a verified sink — that is the 8/27 publication path")
        missing = sorted(v for k, v in sorted(globals().items())
                         if k.startswith("REFUSE_") and isinstance(v, str)
                         and v not in REFUSAL_MEANING)
        if missing:
            f.append("S0: refusal codes with no entry in REFUSAL_MEANING: %s" % missing)
        missing = sorted(v for k, v in sorted(globals().items())
                         if k.startswith("DRIFT_") and isinstance(v, str)
                         and v not in DRIFT_MEANING)
        if missing:
            f.append("S0: drift codes with no entry in DRIFT_MEANING: %s" % missing)
        missing = sorted(v for k, v in sorted(globals().items())
                         if k.startswith("CONFLICT_") and isinstance(v, str)
                         and v not in CONFLICT_MEANING)
        if missing:
            f.append("S0: conflict codes with no entry in CONFLICT_MEANING: %s" % missing)
        undeclared = [e for e in _FIXTURE_EVENT_IDS if e not in sa.FIXTURE_PROVENANCE]
        if undeclared:
            f.append("S0: fixture event ids with no declared provenance: %s" % undeclared)

        # ---- S1. THE HAPPY PATH, AND WHAT THE MANIFEST PRESERVES ---------------------------
        # One canonical StatsAPI fetch of the 8/30 slate, read in the evening. Three games: a
        # validated final, an unvalidated final, and one still in progress.
        schedule = sa.incident_schedule_0830()
        root = new_root("happy")
        raw = '{"dates":[{"date":"2026-08-30","games":[]}],"_fixture":"SYNTHETIC_UNVERIFIED"}'
        sha = _sha256_text(raw)
        payloads = [_payload("mlb_statsapi_schedule_2026-08-30.json", raw, _EVENING)]

        closed = _record(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, sa.CLOSED,
                         2, 9, sha=sha)
        complete = _record(sa.EID_BOSNYY, "SYNTH_BOS", "SYNTH_NYY", _START_1335ET, sa.COMPLETE,
                           0, 1, sha=sha)
        live = _record(sa.EID_COLATL, "SYNTH_COL", "SYNTH_ATL", _START_1335ET, sa.IN_PROGRESS,
                       4, 6, sha=sha)
        envelopes = [_admit(r, now_utc=_EVENING, lane=sa.LANE_CANONICAL, schedule=schedule)
                     for r in (closed, complete, live)]
        for env in envelopes:
            if not env["verdict"].admitted:
                f.append("S1: a canonical fixture did not admit (%s %s) — the store fixture is "
                         "testing the wrong thing" % (env["verdict"].disposition,
                                                      env["verdict"].reason_codes))

        # ...and the sentence that actually arrived at 13:30 ET, which is not a record at all.
        snippet = admission_envelope(
            "Nationals 9, Marlins 2",
            sa.admit("Nationals 9, Marlins 2", now_utc=_NOW_1330ET,
                     canonical_schedule=schedule, lane=sa.LANE_SEARCH))
        search_claim = _record(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", _START_1215ET,
                               sa.CLOSED, 2, 9, sha=sha, source="web_search",
                               fetched=_NOW_1330ET)
        search_env = _admit(search_claim, now_utc=_NOW_1330ET, lane=sa.LANE_SEARCH,
                            schedule=schedule)
        if search_env["verdict"].disposition != sa.REJECT_SCHEDULE_CONFLICT:
            f.append("S1: the MIA@WSH search claim did not refuse as a schedule conflict (%s)"
                     % search_env["verdict"].disposition)

        sid = must_write("S1", envelopes + [snippet, search_env], league="MLB",
                         date_et="2026-08-30", source=sa.PROVIDER_MLB_STATSAPI,
                         raw_payloads=payloads, now_utc=_EVENING, out_root=root)
        if not _SNAPSHOT_ID_RE.match(sid):
            f.append("S1: the snapshot id is not content-addressed in this store's shape: %r" % sid)

        manifest = get_source_manifest(sid, root=root)
        if len(manifest.get("payloads") or []) != 1:
            f.append("S1: the manifest does not carry exactly the one payload written")
        else:
            p = manifest["payloads"][0]
            if p["sha256"] != sha:
                f.append("S1: the manifest's payload sha256 is not the sha256 of the raw bytes "
                         "(owner rule 7)")
            if p.get("fetched_at_utc") != _EVENING:
                f.append("S1: the manifest lost the payload's fetched instant")
            stored = os.path.join(root, SNAPSHOTS_DIR, sid, p["path"])
            if not os.path.isfile(stored):
                f.append("S1: the raw response was not preserved under the snapshot")
            elif _sha256_bytes(_read_bytes(stored)) != sha:
                f.append("S1: the preserved raw bytes do not re-derive the recorded hash")
        if manifest.get("n_verified") != 3 or manifest.get("n_quarantined") != 2:
            f.append("S1: the manifest's counts are wrong: %s verified / %s quarantined"
                     % (manifest.get("n_verified"), manifest.get("n_quarantined")))

        got = get_verified_scores("2026-08-30", "MLB", root=root)
        if len(got) != 3:
            f.append("S1: get_verified_scores returned %d records, expected 3" % len(got))
        one = get_verified_score(sa.EID_MIAWSH, root=root)
        if one is None or one.get("away_score") != 2 or one.get("home_score") != 9:
            f.append("S1: get_verified_score did not return the stored validated final: %r" % one)
        report = verify_snapshot(sid, root=root)
        if not report["ok"]:
            f.append("S1: a snapshot did not verify immediately after being written: %s"
                     % report["drift"])
        if report["checked"]["payloads"] != 1 or report["checked"]["verified_records"] != 3:
            f.append("S1: verify_snapshot did not actually re-hash the snapshot's contents: %s"
                     % report["checked"])

        # ---- S2. QUARANTINE DOES NOT LEAK -------------------------------------------------
        # The 8/30 sentence and the refused MIA@WSH claim are both IN the store, and neither is
        # reachable from the result side. The search claim carries the SAME event id as the
        # admitted final, so a leak here would be invisible in a count and visible only in a
        # score: the quarantined claim says 2-9 for a game whose canonical row also says 2-9,
        # which is why the leak test asserts on the SOURCE, not the score.
        quarantined = get_quarantine("2026-08-30", "MLB", root=root)
        if len(quarantined) != 2:
            f.append("S2: get_quarantine returned %d envelopes, expected 2" % len(quarantined))
        if not any(q["record"] == "Nationals 9, Marlins 2" for q in quarantined):
            f.append("S2: the refused sentence was not preserved in quarantine — a refusal that "
                     "leaves no evidence is the 8/27 review")
        for q in quarantined:
            if q.get("verdict") is None or not q["verdict"].get("reason_codes"):
                f.append("S2: a quarantined envelope carries no reason codes")
            if q.get("sink") in VERIFIED_SINKS:
                f.append("S2: a quarantined entry is filed under a verified sink")
        for record in get_verified_scores("2026-08-30", "MLB", root=root):
            if record.get("source") == "web_search":
                f.append("S2: a SEARCH-lane record reached get_verified_scores")
        if (get_verified_score(sa.EID_MIAWSH, root=root) or {}).get("source") == "web_search":
            f.append("S2: get_verified_score returned the quarantined search claim")
        # an event that exists ONLY in quarantine must read as absent, not as a result
        only_quarantined = _record(sa.EID_WNBA, "SYNTH_MIN", "SYNTH_ATL", _EVENING, sa.CLOSED,
                                   81, 78, sha=sha, league="WNBA", source="web_search",
                                   fetched=_LATE)
        env = _admit(only_quarantined, now_utc="2026-08-31T02:00:00Z", lane=sa.LANE_SEARCH,
                     schedule=None)
        wnba_root = new_root("quarantine_only")
        write_snapshot([env], league="WNBA", date_et="2026-08-30", source="web_search",
                       raw_payloads=[_payload("search_snippet.txt", raw, _LATE, "web_search")],
                       now_utc="2026-08-31T02:00:00Z", out_root=wnba_root)

        leaked = object()

        def leak_check(label, fn):
            """A read of the verified surface where only quarantine exists. If the boundary is
            broken this can EXPLODE rather than return — a quarantined record does not have to
            satisfy the verified side's rules, so reaching one raises. An explosion with no name
            attached is not evidence of anything, so it is named here (cluster O)."""
            try:
                return fn()
            except Exception as e:                              # noqa: BLE001 — named, not hidden
                f.append("S2: %s raised %s, so a quarantined record reached the verified read "
                         "path at all: %s" % (label, type(e).__name__, str(e)[:200]))
                return leaked

        got = leak_check("get_verified_score on a quarantine-only slate",
                         lambda: get_verified_score(sa.EID_WNBA, root=wnba_root))
        if got is not leaked and got is not None:
            f.append("S2: an event stored only in quarantine was returned as a verified score")
        got = leak_check("get_verified_scores on a quarantine-only slate",
                         lambda: get_verified_scores("2026-08-30", "WNBA", root=wnba_root))
        if got is not leaked and got != []:
            f.append("S2: a quarantine-only slate did not read as empty")
        if len(get_quarantine("2026-08-30", "WNBA", root=wnba_root)) != 1:
            f.append("S2: the quarantine-only record is not readable through get_quarantine")

        # ---- S3. IDEMPOTENCE: THE SAME CONTENT TWICE IS A NO-OP ---------------------------
        before = _read_bytes(os.path.join(root, SNAPSHOTS_DIR, sid, VERIFIED_NAME))
        again = write_snapshot(envelopes + [snippet, search_env], league="MLB",
                               date_et="2026-08-30", source=sa.PROVIDER_MLB_STATSAPI,
                               raw_payloads=payloads, now_utc="2026-08-31T03:00:00Z",
                               out_root=root)
        if again != sid:
            f.append("S3: identical content produced a second snapshot id (%s vs %s)"
                     % (again, sid))
        if _read_bytes(os.path.join(root, SNAPSHOTS_DIR, sid, VERIFIED_NAME)) != before:
            f.append("S3: an identical re-write rewrote the stored bytes — not append-only")
        log = [json.loads(x) for x in
               open(os.path.join(root, WRITE_LOG_NAME)).read().strip().splitlines()]
        if len(log) != 2 or log[0]["deduplicated"] or not log[1]["deduplicated"]:
            f.append("S3: the write log does not record the second write as deduplicated: %s"
                     % [(x["snapshot_id"][:14], x["deduplicated"]) for x in log])
        if len([m for m in list_snapshots(root)]) != 1:
            f.append("S3: a deduplicated write created a second snapshot directory")

        # ---- S4. THE MUTABLE ARCHIVE, INSIDE OUR OWN STORE --------------------------------
        # 2026-08-30: the admitted pitch archive rewrote two historical daily files under
        # unchanged filenames. Here the same thing is done to a stored payload on purpose.
        drift_root = new_root("drift")
        drift_sid = write_snapshot(envelopes, league="MLB", date_et="2026-08-30",
                                   source=sa.PROVIDER_MLB_STATSAPI, raw_payloads=payloads,
                                   now_utc=_EVENING, out_root=drift_root)
        if not verify_snapshot(drift_sid, root=drift_root)["ok"]:
            f.append("S4: the control snapshot did not verify before it was tampered with")
        payload_path = os.path.join(drift_root, SNAPSHOTS_DIR, drift_sid, RAW_DIR,
                                    "mlb_statsapi_schedule_2026-08-30.json")
        with open(payload_path, "wb") as fh:
            fh.write(raw.replace("2026-08-30", "2026-08-28").encode("utf-8"))
        report = verify_snapshot(drift_sid, root=drift_root)
        codes = {d["code"] for d in report["drift"]}
        seen_drift.update(codes)
        if report["ok"]:
            f.append("S4: verify_snapshot passed after a stored payload's bytes were rewritten "
                     "under an unchanged filename — the check proves nothing")
        for expected in (DRIFT_PAYLOAD_BYTES, DRIFT_ID_NOT_CONTENT, DRIFT_RECORD_HASH_UNCOVERED):
            if expected not in codes:
                f.append("S4: drift went unnamed: expected %s, got %s" % (expected, sorted(codes)))
        # ...and re-writing the ORIGINAL content over a drifted snapshot must RAISE, not repair.
        tampered = _read_bytes(payload_path)
        try:
            write_snapshot(envelopes, league="MLB", date_et="2026-08-30",
                           source=sa.PROVIDER_MLB_STATSAPI, raw_payloads=payloads,
                           now_utc="2026-08-31T04:00:00Z", out_root=drift_root)
            f.append("S4: a write over a DRIFTED snapshot was accepted as a no-op (R6)")
        except SnapshotImmutabilityViolation:
            pass
        except Exception as e:
            f.append("S4: a write over a drifted snapshot raised %s, not "
                     "SnapshotImmutabilityViolation" % type(e).__name__)
        if _read_bytes(payload_path) != tampered:
            f.append("S4: the refused write REPAIRED the drifted bytes. A repair is a rewrite, "
                     "and it erases the evidence that the store mutated")

        # ---- S5. ENTRY-FILE DRIFT: A SCORE EDITED AFTER THE FACT ---------------------------
        edit_root = new_root("edited")
        edit_sid = write_snapshot(envelopes, league="MLB", date_et="2026-08-30",
                                  source=sa.PROVIDER_MLB_STATSAPI, raw_payloads=payloads,
                                  now_utc=_EVENING, out_root=edit_root)
        records_path = os.path.join(edit_root, SNAPSHOTS_DIR, edit_sid, VERIFIED_NAME)
        # Read BEFORE opening for write. Opening 'wb' first truncates the file, and an emptied
        # file trips the JSON-decode branch instead of the hash branch — the fixture would then
        # pass with the hash comparison removed, which is how this one nearly shipped decorative.
        original = _read_bytes(records_path)
        edited = original.replace(b'"home_score":9', b'"home_score":8')
        if edited == original:
            f.append("S5: the tampering fixture changed nothing; it proves nothing")
        with open(records_path, "wb") as fh:
            fh.write(edited)
        report = verify_snapshot(edit_sid, root=edit_root)
        codes = {d["code"] for d in report["drift"]}
        seen_drift.update(codes)
        if report["ok"] or DRIFT_ENTRY_FILE_BYTES not in codes:
            f.append("S5: a stored score was edited on disk and verify_snapshot did not name it "
                     "(%s)" % sorted(codes))

        # ---- S6. A PARTIAL SNAPSHOT IS NOT SERVED AROUND -----------------------------------
        partial_root = new_root("partial")
        partial_sid = write_snapshot(envelopes, league="MLB", date_et="2026-08-30",
                                     source=sa.PROVIDER_MLB_STATSAPI, raw_payloads=payloads,
                                     now_utc=_EVENING, out_root=partial_root)
        os.remove(os.path.join(partial_root, SNAPSHOTS_DIR, partial_sid, MANIFEST_NAME))
        report = verify_snapshot(partial_sid, root=partial_root)
        codes = {d["code"] for d in report["drift"]}
        seen_drift.update(codes)
        if report["ok"] or DRIFT_MANIFEST_MISSING not in codes:
            f.append("S6: a snapshot with no manifest verified clean")
        try:
            get_verified_scores("2026-08-30", "MLB", root=partial_root)
            f.append("S6: the store served around a snapshot with no manifest; 'fewer games' "
                     "reads like 'a quiet night'")
        except SnapshotImmutabilityViolation:
            pass
        except Exception as e:
            f.append("S6: a partial snapshot raised %s instead of refusing as an immutability "
                     "violation: %s" % (type(e).__name__, e))
        missing_root = new_root("missing_file")
        missing_sid = write_snapshot(envelopes, league="MLB", date_et="2026-08-30",
                                     source=sa.PROVIDER_MLB_STATSAPI, raw_payloads=payloads,
                                     now_utc=_EVENING, out_root=missing_root)
        os.remove(os.path.join(missing_root, SNAPSHOTS_DIR, missing_sid, RAW_DIR,
                               "mlb_statsapi_schedule_2026-08-30.json"))
        report = verify_snapshot(missing_sid, root=missing_root)
        codes = {d["code"] for d in report["drift"]}
        seen_drift.update(codes)
        if report["ok"] or DRIFT_FILE_MISSING not in codes:
            f.append("S6: a deleted raw payload did not read as drift (%s)" % sorted(codes))

        # ---- S7. LATER OBSERVATION WINS; A MUTATED ARCHIVE RAISES --------------------------
        series_root = new_root("series")
        live_raw = raw + "|live"
        live_sha = _sha256_text(live_raw)
        live_rec = _record(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", _START_1215ET,
                           sa.IN_PROGRESS, 1, 3, sha=live_sha, fetched="2026-08-30T18:45:00Z")
        write_snapshot([_admit(live_rec, now_utc="2026-08-30T18:46:00Z",
                               lane=sa.LANE_CANONICAL, schedule=schedule)],
                       league="MLB", date_et="2026-08-30", source=sa.PROVIDER_MLB_STATSAPI,
                       raw_payloads=[_payload("schedule_1845.json", live_raw,
                                              "2026-08-30T18:45:00Z")],
                       now_utc="2026-08-30T18:46:00Z", out_root=series_root)
        write_snapshot([_admit(closed, now_utc=_EVENING, lane=sa.LANE_CANONICAL,
                               schedule=schedule)],
                       league="MLB", date_et="2026-08-30", source=sa.PROVIDER_MLB_STATSAPI,
                       raw_payloads=payloads, now_utc=_EVENING, out_root=series_root)
        latest = get_verified_score(sa.EID_MIAWSH, root=series_root)
        if latest is None or latest.get("status") != sa.CLOSED:
            f.append("S7: the later observation did not supersede the earlier one: %r" % latest)
        if len(get_verified_scores("2026-08-30", "MLB", root=series_root)) != 1:
            f.append("S7: two observations of one game were returned as two results")

        # ...and two snapshots that share a payload but hold DIFFERENT records are two
        # snapshots. If the id stopped covering the records, the second write would look like a
        # duplicate of the first and its games would vanish into a dedup.
        distinct_root = new_root("distinct_entries")
        shared = [_payload("shared_schedule.json", raw, _EVENING)]
        ids = [write_snapshot([_admit(rec, now_utc=_EVENING, lane=sa.LANE_CANONICAL,
                                      schedule=schedule)],
                              league="MLB", date_et="2026-08-30",
                              source=sa.PROVIDER_MLB_STATSAPI, raw_payloads=shared,
                              now_utc=_EVENING, out_root=distinct_root)
               for rec in (closed, complete)]
        if ids[0] == ids[1]:
            f.append("S7: two snapshots with different records collided on one id — the id has "
                     "stopped covering the records it is supposed to address")
        if len(get_verified_scores("2026-08-30", "MLB", root=distinct_root)) != 2:
            f.append("S7: a second snapshot's records were lost to a dedup")

        conflict_root = new_root("mutated_archive")
        alt_raw = raw + "|rewritten"
        alt = _record(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, sa.CLOSED,
                      2, 8, sha=_sha256_text(alt_raw))
        for rec, payload_id, text in ((closed, "schedule_a.json", raw),
                                      (alt, "schedule_b.json", alt_raw)):
            write_snapshot([_admit(rec, now_utc=_EVENING, lane=sa.LANE_CANONICAL,
                                   schedule=schedule)],
                           league="MLB", date_et="2026-08-30",
                           source=sa.PROVIDER_MLB_STATSAPI,
                           raw_payloads=[_payload(payload_id, text, _EVENING)],
                           now_utc=_EVENING, out_root=conflict_root)
        try:
            get_verified_score(sa.EID_MIAWSH, root=conflict_root)
            f.append("S7: two records sharing event id, source and fetched instant with "
                     "different content hashes were silently resolved — that is the archive "
                     "that changed under one key")
        except SnapshotContentConflict as e:
            if e.problem.get("code") != sa.REASON_SNAPSHOT_CONTENT_CHANGED:
                f.append("S7: the conflict was raised under the wrong code: %s"
                         % e.problem.get("code"))

        # ---- S8. WRITE REFUSALS ------------------------------------------------------------
        refuse_root = new_root("refusals")

        def w(records_arg=None, **kw):
            args = {"league": "MLB", "date_et": "2026-08-30",
                    "source": sa.PROVIDER_MLB_STATSAPI, "raw_payloads": payloads,
                    "now_utc": _EVENING, "out_root": refuse_root}
            args.update(kw)
            return lambda: write_snapshot(
                envelopes if records_arg is None else records_arg, **args)

        expect_refusal("R: a bare record with no verdict",
                       w([{"record": closed}]), REFUSE_NO_VERDICT)
        expect_refusal("R: something that is not an envelope",
                       w([closed]), REFUSE_NOT_AN_ENVELOPE)
        expect_refusal("R: a forged disposition",
                       w([{"record": closed, "verdict": {"disposition": "PROBABLY_FINE",
                                                         "reason_codes": ["X"]}}]),
                       REFUSE_BAD_VERDICT)
        expect_refusal("R: a SEARCH verdict claiming to have admitted",
                       w([{"record": closed,
                           "verdict": {"disposition": sa.ADMIT_FINAL,
                                       "reason_codes": [sa.REASON_STATUS_VALIDATED],
                                       "admissible_as": sa.ADMISSIBLE_FINAL,
                                       "detail": {"lane": sa.LANE_SEARCH}}}]),
                       REFUSE_SEARCH_ADMISSION)
        bad_record = dict(closed)
        bad_record["away_score"] = "2"          # ESPN returns scores as strings; records do not
        expect_refusal("R: an admitted record that does not validate",
                       w([{"record": bad_record,
                           "verdict": envelopes[0]["verdict"].to_dict()}]),
                       REFUSE_ADMITTED_INVALID)
        expect_refusal("R: an admitted record whose source hash is in no payload",
                       w([{"record": dict(closed, raw_response_sha256=_sha256_text("elsewhere")),
                           "verdict": envelopes[0]["verdict"].to_dict()}]),
                       REFUSE_HASH_NOT_IN_SNAPSHOT)
        # CLUSTER E, at the write end. No forgery: a GENUINE canonical verdict, moved sideways
        # onto a record it never judged — source "web_search", scores invented, admitted FINAL.
        fabricated = _record(sa.EID_COLATL, "SYNTH_COL", "SYNTH_ATL", _START_1335ET, sa.CLOSED,
                             9, 2, sha=sha, source="web_search", fetched=_EVENING)
        expect_refusal("R: a genuine CANONICAL verdict copied onto a record it never judged",
                       w([{"record": fabricated,
                           "verdict": envelopes[0]["verdict"].to_dict()}]),
                       REFUSE_VERDICT_NOT_BOUND)
        # CLUSTER A, downstream. admit(canonical_schedule=None) leaves owner rules 1, 2 and 6
        # unenforced and says so in the verdict. This gate is DEFENCE IN DEPTH and the fixture is
        # built to stay honest about that: score_admission now caps a schedule-less record at
        # UNVERIFIED, so asking admit() for the dangerous verdict no longer yields one — and a
        # gate whose fixture depends on another module's ceiling stops testing itself the moment
        # that ceiling moves. So the verdict admit() RETURNED UNTIL 2026-08-30 is built by hand.
        unbound_verdict = {"disposition": sa.ADMIT_FINAL,
                           "reason_codes": [sa.REASON_SCHEDULE_NOT_SUPPLIED,
                                            sa.REASON_STATUS_VALIDATED],
                           "admissible_as": sa.ADMISSIBLE_FINAL,
                           "detail": {"lane": sa.LANE_CANONICAL, "event_id": closed["event_id"],
                                      "status": closed["status"], "terminal_verified": True,
                                      "scheduled_start_utc": closed["scheduled_start_utc"]}}
        expect_refusal("R: an admission never checked against a canonical schedule",
                       w([{"record": closed, "verdict": unbound_verdict}]),
                       REFUSE_UNBOUND_NO_SCHEDULE)
        expect_refusal("R: a record from another league",
                       w(**{"league": "WNBA"}), REFUSE_LEAGUE_MISMATCH)
        # THE UTC-SLICE BUG, in its exact shape: a 2026-08-31T00:30Z start is the ET EVENING of
        # 08-30, so filing it under 08-31 must refuse.
        late = _record(sa.EID_WNBA, "SYNTH_MIN", "SYNTH_ATL", _LATE, sa.CLOSED, 81, 78,
                       sha=sha, league="WNBA", fetched="2026-08-31T03:30:00Z")
        # Bound against a schedule of its own: an unbound admission is refused before the date is
        # ever compared (the gate two blocks up), which would make this fixture pass for the
        # wrong reason and stop watching the UTC slice.
        late_env = _admit(late, now_utc="2026-08-31T04:00:00Z", lane=sa.LANE_CANONICAL,
                          schedule={"event_id": sa.EID_WNBA, "league": "WNBA",
                                    "away_team_id": "SYNTH_MIN", "home_team_id": "SYNTH_ATL",
                                    "scheduled_start_utc": _LATE})
        expect_refusal("R: an ET date sliced from the UTC string",
                       w([late_env], league="WNBA", date_et="2026-08-31"), REFUSE_DATE_MISMATCH)
        expect_refusal("R: two admitted records for one event id",
                       w([envelopes[0], envelopes[0]]), REFUSE_DUPLICATE_EVENT_ID)
        expect_refusal("R: an empty snapshot", w([]), REFUSE_NO_RECORDS)
        expect_refusal("R: no raw payload retained (owner rule 7)",
                       w(raw_payloads=[]), REFUSE_NO_PAYLOAD)
        expect_refusal("R: a payload that is not a mapping",
                       w(raw_payloads=["just some text"]), REFUSE_PAYLOAD_SHAPE)
        expect_refusal("R: a payload id that is a path",
                       w(raw_payloads=[_payload("../escape.json", raw, _EVENING)]),
                       REFUSE_PAYLOAD_ID)
        expect_refusal("R: a payload with no fetched instant",
                       w(raw_payloads=[{"payload_id": "p.json", "raw_text": raw}]),
                       REFUSE_PAYLOAD_FETCHED_AT)
        expect_refusal("R: a typed sha256 that is not the sha256 of the bytes",
                       w(raw_payloads=[dict(_payload("p.json", raw, _EVENING),
                                            sha256=_sha256_text("something else"))]),
                       REFUSE_PAYLOAD_SHA_MISMATCH)
        expect_refusal("R: two payloads under one id",
                       w(raw_payloads=[_payload("p.json", raw, _EVENING),
                                       _payload("p.json", raw + "x", _EVENING)]),
                       REFUSE_DUPLICATE_PAYLOAD_ID)
        expect_refusal("R: a malformed slate date", w(date_et="30-08-2026"), REFUSE_BAD_DATE_ET)
        expect_refusal("R: a date that is not a date", w(date_et="2026-02-30"),
                       REFUSE_BAD_DATE_ET)
        expect_refusal("R: a league with no minimum duration", w(league="KBO"), REFUSE_BAD_LEAGUE)
        expect_refusal("R: a snapshot with no named source", w(source="  "), REFUSE_BAD_SOURCE)
        expect_refusal("R: an unparseable write instant", w(now_utc="tonight"), REFUSE_BAD_NOW)
        # Quarantine may hold anything that was refused, but it must still be WRITABLE: bytes
        # that JSON cannot carry would be stored as something other than what was handed in.
        expect_refusal("R: an entry that cannot be written as JSON",
                       w([{"record": {"event_id": sa.EID_MIAWSH, "blob": b"\x00"},
                           "verdict": search_env["verdict"].to_dict()}]),
                       REFUSE_NOT_SERIALIZABLE)
        expect_refusal("R: a malformed snapshot id on read",
                       lambda: get_source_manifest("../../etc/passwd", root=refuse_root),
                       REFUSE_BAD_SNAPSHOT_ID)
        try:
            get_source_manifest(SNAPSHOT_ID_PREFIX + "0" * 64, root=refuse_root)
            f.append("R: an id the store does not hold returned a manifest")
        except SnapshotNotFound:
            pass
        expect_refusal("R: a malformed event id on read",
                       lambda: get_verified_score("824643", root=refuse_root),
                       sa.REASON_EVENT_ID_MALFORMED)
        seen_refusals.add(sa.REASON_EVENT_ID_MALFORMED)
        # Defence in depth: the payload-id regex refuses a path first, so this is the second
        # line, exercised directly rather than left to be proven by a route that never reaches it.
        expect_refusal("R: a path that escapes out_root",
                       lambda: _assert_within(refuse_root,
                                              os.path.join(refuse_root, "..", "escaped")),
                       REFUSE_WRITE_OUTSIDE_ROOT)

        # Nothing a refused write touched may exist on disk.
        if os.path.isdir(os.path.join(refuse_root, SNAPSHOTS_DIR)):
            f.append("R: a refused write created a snapshot directory")
        if os.path.isdir(os.path.join(refuse_root, INCOMING_DIR)) and \
                os.listdir(os.path.join(refuse_root, INCOMING_DIR)):
            f.append("R: a refused write left staged files behind")

        # ---- S10. ORDERED BY THE OBSERVATION, NOT BY THE WRITE (cluster C) ------------------
        # Five separate review lenses reached this one independently. _resolve ordered by
        # written_at_utc — when somebody got round to STORING the record — while the docstring
        # beside it said observation, so a stale IN_PROGRESS written after a validated CLOSED
        # answered a settled game with a live score.
        order_root = new_root("observation_order")
        settled_raw, regressed_raw = raw + "|final2230", raw + "|live2330"
        settled = _record(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, sa.CLOSED,
                          2, 9, sha=_sha256_text(settled_raw), fetched="2026-08-30T22:30:00Z")
        # ...and the provider REGRESSING a settled game, observed an hour LATER than the final.
        # Ordering alone does not save this one: a final does not change.
        regressed = _record(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", _START_1215ET,
                            sa.IN_PROGRESS, 1, 3, sha=_sha256_text(regressed_raw),
                            fetched="2026-08-30T23:30:00Z")
        for rec, pid, text, seen in ((settled, "schedule_2230.json", settled_raw,
                                      "2026-08-30T22:30:00Z"),
                                     (regressed, "schedule_2330.json", regressed_raw,
                                      "2026-08-30T23:30:00Z")):
            must_write("S10", [_admit(rec, now_utc="2026-08-31T02:00:00Z",
                                      lane=sa.LANE_CANONICAL, schedule=schedule)],
                       league="MLB", date_et="2026-08-30", source=sa.PROVIDER_MLB_STATSAPI,
                       raw_payloads=[_payload(pid, text, seen)],
                       now_utc="2026-08-31T02:00:00Z", out_root=order_root)
        served = get_verified_score(sa.EID_MIAWSH, root=order_root)
        if (served or {}).get("status") != sa.CLOSED:
            f.append("S10: a non-terminal observation superseded a VALIDATED FINAL on a settled "
                     "game. A final does not change, and elapsed time never converts a status: "
                     "%r" % (served,))

        # ...and with no terminal record in play at all, the order is still the order the
        # OBSERVATIONS were made in, not the order someone stored them.
        order2_root = new_root("observation_order_live")
        early_raw, late_raw = raw + "|colatl1845", raw + "|colatl1930"
        early = _record(sa.EID_COLATL, "SYNTH_COL", "SYNTH_ATL", _START_1335ET, sa.IN_PROGRESS,
                        1, 0, sha=_sha256_text(early_raw), fetched="2026-08-30T18:45:00Z")
        later = _record(sa.EID_COLATL, "SYNTH_COL", "SYNTH_ATL", _START_1335ET, sa.IN_PROGRESS,
                        4, 6, sha=_sha256_text(late_raw), fetched="2026-08-30T19:30:00Z")
        # The 19:30 observation is written FIRST and the 18:45 one is written a day later.
        for rec, pid, text, seen, wrote in (
                (later, "colatl_1930.json", late_raw, "2026-08-30T19:30:00Z",
                 "2026-08-30T19:31:00Z"),
                (early, "colatl_1845.json", early_raw, "2026-08-30T18:45:00Z",
                 "2026-08-31T05:00:00Z")):
            must_write("S10", [_admit(rec, now_utc=wrote, lane=sa.LANE_CANONICAL,
                                      schedule=schedule)],
                       league="MLB", date_et="2026-08-30", source=sa.PROVIDER_MLB_STATSAPI,
                       raw_payloads=[_payload(pid, text, seen)], now_utc=wrote,
                       out_root=order2_root)
        served = get_verified_score(sa.EID_COLATL, root=order2_root)
        if (served or {}).get("away_score") != 4 or (served or {}).get("home_score") != 6:
            f.append("S10: the LAST-WRITTEN observation won instead of the LAST-OBSERVED one. "
                     "written_at_utc is the store action; source_fetched_at_utc is the "
                     "observation: %r" % (served,))
        if len(get_verified_scores("2026-08-30", "MLB", root=order2_root)) != 1:
            f.append("S10: two observations of one game read back as two results")

        # ---- S11. TWO TERMINALS THAT DISAGREE ARE A CONTRADICTION (cluster F) ---------------
        # content_hash_conflict catches same-key/same-sha shapes. Move source_fetched_at_utc by
        # ONE SECOND and the keys stop matching, and the store used to settle the disagreement
        # by picking whichever of the two a writer stamped later.
        contradiction_root = new_root("two_finals")
        a_raw, b_raw = raw + "|final_a", raw + "|final_b"
        final_a = _record(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, sa.CLOSED,
                          2, 9, sha=_sha256_text(a_raw), fetched=_EVENING)
        final_b = _record(sa.EID_MIAWSH, "SYNTH_MIA", "SYNTH_WSH", _START_1215ET, sa.CLOSED,
                          2, 8, sha=_sha256_text(b_raw), fetched="2026-08-30T23:00:01Z")
        for rec, pid, text, seen in ((final_a, "final_a.json", a_raw, _EVENING),
                                     (final_b, "final_b.json", b_raw,
                                      "2026-08-30T23:00:01Z")):
            must_write("S11", [_admit(rec, now_utc="2026-08-31T02:00:00Z",
                                      lane=sa.LANE_CANONICAL, schedule=schedule)],
                       league="MLB", date_et="2026-08-30", source=sa.PROVIDER_MLB_STATSAPI,
                       raw_payloads=[_payload(pid, text, seen)],
                       now_utc="2026-08-31T02:00:00Z", out_root=contradiction_root)
        expect_conflict("S11: two disagreeing finals for one event id",
                        lambda: get_verified_score(sa.EID_MIAWSH, root=contradiction_root),
                        CONFLICT_TERMINAL_DISAGREEMENT)
        expect_conflict("S11: the same contradiction through the slate getter",
                        lambda: get_verified_scores("2026-08-30", "MLB",
                                                    root=contradiction_root),
                        CONFLICT_TERMINAL_DISAGREEMENT)

        # ---- S12/S13. WHAT IS STORED IS RE-CHECKED ON READ (clusters E, A) -----------------
        # Every fixture below rebuilds the manifest AND the directory name around its edit, so
        # the snapshot is self-consistent on disk and the file hashes cannot catch it. That is
        # the honest adversary: whoever can edit records.json can edit the manifest beside it.
        def stored(label, record):
            r = new_root(label)
            return r, must_write(label, [_admit(record, now_utc=_EVENING,
                                                lane=sa.LANE_CANONICAL, schedule=schedule)],
                                 league="MLB", date_et="2026-08-30",
                                 source=sa.PROVIDER_MLB_STATSAPI, raw_payloads=payloads,
                                 now_utc=_EVENING, out_root=r)

        def promote(entry):
            """The 8/27 shape in one edit: a live record turned into a final underneath the
            verdict that judged it live."""
            entry["record"] = dict(entry["record"], status=sa.CLOSED, terminal_verified=True)
            entry["record_sha256"] = _record_binding(entry["record"])
            return entry

        bind_root, bind_sid = stored("verdict_binding", live)
        _rebuild_snapshot_on_disk(bind_root, bind_sid, promote)
        expect_conflict("S12: an IN_PROGRESS record promoted to CLOSED beneath its own verdict",
                        lambda: get_verified_score(sa.EID_COLATL, root=bind_root),
                        CONFLICT_VERDICT_NOT_BOUND, SnapshotAdmissibilityViolation)

        def edit_score(entry):
            """A score edited on disk, with the entry's OWN binding left as it was."""
            entry["record"] = dict(entry["record"], home_score=99)
            return entry

        stale_root, stale_sid = stored("record_binding", live)
        _rebuild_snapshot_on_disk(stale_root, stale_sid, edit_score)
        expect_conflict("S12: a score edited on disk with the manifest rebuilt around it",
                        lambda: get_verified_score(sa.EID_COLATL, root=stale_root),
                        CONFLICT_RECORD_BINDING, SnapshotAdmissibilityViolation)

        def unbind(entry):
            entry["verdict"] = dict(entry["verdict"], reason_codes=list(
                entry["verdict"]["reason_codes"]) + [sa.REASON_SCHEDULE_NOT_SUPPLIED])
            return entry

        unbound_root, unbound_sid = stored("unbound_admission", live)
        _rebuild_snapshot_on_disk(unbound_root, unbound_sid, unbind)
        expect_conflict("S13: a stored admission that was never checked against a schedule",
                        lambda: get_verified_score(sa.EID_COLATL, root=unbound_root),
                        CONFLICT_UNBOUND_ADMISSION, SnapshotAdmissibilityViolation)

        def forge(entry):
            entry["verdict"] = dict(entry["verdict"], disposition="PROBABLY_FINE")
            return entry

        forged_root, forged_sid = stored("forged_verdict", live)
        _rebuild_snapshot_on_disk(forged_root, forged_sid, forge)
        expect_conflict("S13: a stored verdict edited out of score_admission's vocabulary",
                        lambda: get_verified_score(sa.EID_COLATL, root=forged_root),
                        CONFLICT_VERDICT_UNREADABLE, SnapshotAdmissibilityViolation)

        # ---- S14. THE READ PATH RE-DERIVES BEFORE IT SERVES (cluster D) ---------------------
        # verify_snapshot() existed, was correct, and had ZERO read-path callers: its only
        # production call site was inside the WRITE path. So records.json edited in place was
        # served as truth by all three analysis tools — the mutable-archive hazard this module
        # was written against, inside the module written against it. No manifest rebuild here:
        # just the bytes, the way an archive rewrites a file under an unchanged name.
        tamper_root, tamper_sid = stored("read_rehash", closed)
        tampered_path = os.path.join(tamper_root, SNAPSHOTS_DIR, tamper_sid, VERIFIED_NAME)
        original = _read_bytes(tampered_path)
        edited = original.replace(b'"home_score":9', b'"home_score":8')
        if edited == original:
            f.append("S14: the tampering fixture changed nothing; it proves nothing")
        with open(tampered_path, "wb") as fh:
            fh.write(edited)
        for tool, call in (("get_verified_score",
                            lambda: get_verified_score(sa.EID_MIAWSH, root=tamper_root)),
                           ("get_verified_scores",
                            lambda: get_verified_scores("2026-08-30", "MLB", root=tamper_root)),
                           ("get_source_manifest",
                            lambda: get_source_manifest(tamper_sid, root=tamper_root))):
            try:
                out = call()
                f.append("S14: %s served a snapshot whose records.json was edited on disk (%r). "
                         "The guard exists; nothing on the read path called it" % (tool, out))
            except SnapshotImmutabilityViolation:
                pass
            except Exception as e:
                f.append("S14: %s raised %s instead of refusing to serve tampered bytes: %s"
                         % (tool, type(e).__name__, e))
        if _read_bytes(tampered_path) != edited:
            f.append("S14: a refused read REPAIRED the tampered bytes. Repair is a rewrite, and "
                     "it erases the evidence that the store mutated")

        # ...and the same for the RAW payload the record was derived from. This is the half the
        # read path caches on size and mtime, so the fixture also proves the cache is not a hole
        # the getters serve through.
        payload_root, payload_sid = stored("read_rehash_payload", closed)
        if get_verified_score(sa.EID_MIAWSH, root=payload_root) is None:
            f.append("S14: the control store does not serve its own record before tampering")
        with open(os.path.join(payload_root, SNAPSHOTS_DIR, payload_sid, RAW_DIR,
                               "mlb_statsapi_schedule_2026-08-30.json"), "wb") as fh:
            fh.write(raw.replace("2026-08-30", "2026-08-28").encode("utf-8"))
        try:
            out = get_verified_score(sa.EID_MIAWSH, root=payload_root)
            f.append("S14: a record was served on top of a raw payload whose bytes had been "
                     "rewritten under an unchanged filename (%r)" % (out,))
        except SnapshotImmutabilityViolation:
            pass
        except Exception as e:
            f.append("S14: a drifted payload raised %s on read instead of refusing to serve: %s"
                     % (type(e).__name__, e))

        # ---- S9. NOTHING WAS WRITTEN OUTSIDE out_root --------------------------------------
        for r in roots:
            for dirpath, _dirnames, filenames in os.walk(r):
                for name in filenames:
                    _assert_within(r, os.path.join(dirpath, name))
        if os.path.exists(DEFAULT_ROOT):
            f.append("S9: the selftest wrote to the real store at %s; every fixture root is a "
                     "temporary directory" % DEFAULT_ROOT)

        # ---- COVERAGE. A code no fixture produces is a code nobody has watched fire. --------
        uncovered = sorted(c for c in REFUSAL_MEANING if c not in seen_refusals)
        if uncovered:
            f.append("COVERAGE: refusal codes this selftest never produces: %s" % uncovered)
        uncovered = sorted(c for c in DRIFT_MEANING if c not in seen_drift)
        if uncovered:
            f.append("COVERAGE: drift codes this selftest never produces: %s" % uncovered)
        uncovered = sorted(c for c in CONFLICT_MEANING if c not in seen_conflicts)
        if uncovered:
            f.append("COVERAGE: read-time conflict codes this selftest never produces: %s"
                     % uncovered)
    except _FixtureAborted:
        pass          # the named failure is already in f; see must_write
    except Exception as e:
        # A mutant that makes a fixture EXPLODE is caught either way, but an exception with no
        # name attached reads like an infrastructure problem. Name it, so the mutation output
        # says which protection was removed rather than only that something broke.
        import traceback
        f.append("UNEXPECTED: the fixture run raised %s: %s | %s"
                 % (type(e).__name__, e, traceback.format_exc().strip().splitlines()[-3:]))
    finally:
        for r in roots:
            shutil.rmtree(r, ignore_errors=True)

    print(f"{MODULE_ID} selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("  FAIL:", x)
    return not f


# ---------------------------------------------------------------------------------------------
# 12. MUTATION SUITE.  A counter that cannot fail is not a check.
#     Each entry names the DEFECT RESTORED, not a test, and declares the MARKER of the assertion
#     that must catch it. A mutant killed by some other assertion is not evidence that the
#     fixture named below is doing anything (cluster O, 2026-08-30 review).
# ---------------------------------------------------------------------------------------------

MUTANTS = [
    ("an existing snapshot whose bytes have changed is silently accepted as a no-op (R6)",
     "    if not identical:",
     "    if False:", "S4:"),
    ("a quarantined entry is checked, and therefore filed, as if it were verified",
     "        if sink in VERIFIED_SINKS:",
     "        if True:", "S1:"),
    ("a quarantined record leaks out through the READ path — get_verified_score reaches the "
     "other side of the store (the 8/27 publication path, in getter form)",
     "        for entry in _entries_of(manifest, \"verified\", root):",
     "        for entry in _entries_of(manifest, \"verified\", root) + "
     "_entries_of(manifest, \"quarantine\", root):", "S2:"),
    ("verify_snapshot stops comparing a stored payload's bytes to its recorded hash",
     "        if actual != declared.get(\"sha256\"):",
     "        if False:", "S4:"),
    ("the snapshot id stops covering the payload hashes, so drifted bytes leave the id true",
     "            \"payloads\": sorted(payload_descriptors, key=lambda p: p[\"payload_id\"])}",
     "            \"payloads\": []}", "S4:"),
    ("the snapshot id stops covering the records, so different content collides on one id",
     "            \"entries\": sorted(entries, key=_canonical),",
     "            \"entries\": [],", "S7:"),
    ("verify_snapshot stops comparing records.json and quarantine.json to their hashes",
     "        if declared.get(\"sha256\") != actual:",
     "        if False:", "S5:"),
    ("routing is decided by the store instead of by the verdict's own recorded lane",
     "        sink = sa.sink_for(verdict)",
     "        sink = sa.SINK_RESULT_LEDGER", "S1:"),
    ("an admitted record no longer has to validate",
     "    ok, record_problems = sa.validate_record(record)",
     "    ok, record_problems = True, []", "R: an admitted record that does not validate"),
    ("an admitted record's source hash no longer has to be covered by a stored payload "
     "(owner rule 7 becomes decorative)",
     "    if sha not in payload_shas:",
     "    if False:", "R: an admitted record whose source hash is in no payload"),
    ("the ET date of an admitted record is no longer checked against the slate (the UTC-slice "
     "bug, restored)",
     "    if row_date != date_et:",
     "    if False:", "R: an ET date sliced from the UTC string"),
    ("a snapshot may be written with no raw payload at all (owner rule 7 unenforced)",
     "    if raw_payloads is None or (isinstance(raw_payloads, (list, tuple)) "
     "and not raw_payloads):",
     "    if False:", "R: no raw payload retained"),
    ("an empty snapshot is accepted, so a down lane and an empty slate look identical on disk",
     "    if not isinstance(records, (list, tuple)) or not records:",
     "    if not isinstance(records, (list, tuple)):", "R: an empty snapshot"),
    ("two admitted records for one event id are accepted",
     "    if event_id in seen_event_ids:",
     "    if False:", "R: two admitted records for one event id"),
    ("a caller-supplied sha256 is trusted instead of the sha256 of the bytes",
     "        if declared is not None and str(declared).strip().lower() != sha:",
     "        if False:", "R: a typed sha256 that is not the sha256 of the bytes"),
    ("get_verified_score returns the FIRST observation instead of the latest",
     "    return sorted(candidates, key=_observation_order)[-1][\"record\"]",
     "    return sorted(candidates, key=_observation_order)[0][\"record\"]", "S10:"),
    ("the mutable-archive conflict is resolved silently instead of raised",
     "            if conflict:",
     "            if False:", "S7:"),
    ("a partial snapshot with no manifest is served around, so 'fewer games' reads as "
     "'a quiet night'",
     "        if not os.path.isfile(manifest_path):",
     "        if False:", "S6:"),

    # ---- the 2026-08-30 adversarial review. One mutant per cluster that landed here. --------
    ("CLUSTER C: observations are ordered by written_at_utc — the store action — again, so a "
     "stale record written last wins over the one observed last",
     "    return (_utc(candidate[\"record\"].get(\"source_fetched_at_utc\")) or _UNDATED,",
     "    return (", "S10:"),
    ("CLUSTER C: a non-terminal observation may supersede a validated final again, so a "
     "provider regressing a settled game un-settles it downstream",
     "    if terminals:",
     "    if False:", "S10:"),
    ("CLUSTER D: the read path stops re-deriving, so records.json edited in place on disk is "
     "served as truth by all three analysis tools",
     "    drift = _read_integrity(manifest, root)",
     "    drift = []", "S14:"),
    ("CLUSTER D: the read path stops re-hashing the stored raw payloads, so an archive that "
     "rewrites bytes under an unchanged filename is served through the cache",
     "        if rehashed != declared.get(\"sha256\"):",
     "        if False:", "S14:"),
    ("CLUSTER E: a verdict is no longer bound to the record it judged at WRITE time, so a "
     "genuine CANONICAL verdict copied onto a fabricated record admits it",
     "            bad.extend(_verdict_binding_problems(record, verdict, i))",
     "            bad.extend([])", "R: a genuine CANONICAL verdict copied"),
    ("CLUSTER E: the binding is no longer re-checked at READ time, so a live record edited "
     "into a final on disk is served as a final",
     "        for p in _verdict_binding_problems(record, verdict, None):",
     "        for p in []:", "S12: an IN_PROGRESS record promoted"),
    ("CLUSTER E: a record's stored content binding is no longer re-derived, so an edited score "
     "with a rebuilt manifest around it is served",
     "    if binding is not None and entry.get(\"record_sha256\") != binding:",
     "    if False:", "S12: a score edited on disk"),
    ("CLUSTER F: two terminal records that disagree are silently resolved by picking one, "
     "instead of refused as the contradiction they are",
     "    if len(scores) > 1:",
     "    if False:", "S11:"),
    ("CLUSTER A downstream: a verdict that was never checked against a canonical schedule is "
     "storable, and readable, as a result",
     "    if sa.REASON_SCHEDULE_NOT_SUPPLIED in verdict.reason_codes:",
     "    if False:", "R: an admission never checked"),
]


def mutation_suite():
    """Break one protection at a time. A mutant must die on the NAMED assertion that owns it.

    WHAT COUNTS AS A KILL, rewritten 2026-08-30 (cluster O of the review). This suite used to
    count ANY exception as a kill — including a mutant that died at import before a single
    fixture ran. That overstates what is proven, and this repo has already paid for the exact
    overstatement once: score_admission's first mutation run reported 12/12 KILLED while every
    mutant was dying of an AttributeError at import, i.e. the suite proved nothing at all.

    So, three outcomes and no fourth:
      KILLED    the selftest returned False, printed at least one named FAIL, printed no
                UNEXPECTED line, and one of those failures carries this mutant's own marker.
      ERRORED   anything else that is not a pass: an exception escaping the fixtures, an
                ImportError or AttributeError at exec, a pattern that no longer matches, or a
                death on an assertion that belongs to some other protection. Reported, and NOT
                counted as a kill.
      SURVIVED  the selftest passed with the protection removed. The fixture is decorative.

    The tally is printed as "N killed, M errored, K survived"; the gate requires all killed.
    """
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
    killed, errored, survived = [], [], []
    for name, old, new, marker in MUTANTS:
        if old not in src:
            errored.append((name, "the pattern no longer occurs in this file: %r" % old))
            print("  ERRORED   " + name)
            continue
        if old not in body:
            errored.append((name, "the pattern occurs only inside the MUTANTS list, so the "
                                  "mutant edits its own definition"))
            print("  ERRORED   " + name)
            continue
        ns = {"__file__": __file__, "__name__": "mutant"}
        out = _io.StringIO()
        try:
            exec(compile(src.replace(old, new, 1), "<mutant>", "exec"), ns)
            with _cl.redirect_stdout(out):
                ok = ns["selftest"]()
        except Exception as e:
            errored.append((name, "%s before any fixture could judge it: %s"
                            % (type(e).__name__, str(e)[:200])))
            print("  ERRORED   " + name)
            continue
        failures = [line.strip()[5:].strip() for line in out.getvalue().splitlines()
                    if line.strip().startswith("FAIL:")]
        if ok:
            survived.append(name)
            print("  SURVIVED  " + name)
            continue
        unexpected = [x for x in failures if x.startswith("UNEXPECTED:")]
        if unexpected:
            errored.append((name, "died on an unclassified exception rather than an assertion: "
                            + unexpected[0][:200]))
            print("  ERRORED   " + name)
            continue
        if not failures:
            errored.append((name, "the selftest returned False and named nothing"))
            print("  ERRORED   " + name)
            continue
        if not any(marker in x for x in failures):
            errored.append((name, "died on an unrelated assertion; expected one carrying %r, "
                                  "got %s" % (marker, [x[:90] for x in failures[:3]])))
            print("  ERRORED   " + name)
            continue
        killed.append(name)
        print("  KILLED    " + name)
    print("verified_snapshot mutation suite: %d killed, %d errored, %d survived (of %d)"
          % (len(killed), len(errored), len(survived), len(MUTANTS)))
    for name, why in errored:
        print("    ERROR     %s\n              :: %s" % (name, why))
    for name in survived:
        print("    SURVIVOR  %s\n              :: the fixture that should catch this is "
              "decorative" % name)
    return not errored and not survived and len(killed) == len(MUTANTS)


def gate():
    """Healthcheck entry point: the fixtures hold AND the mutants die on their own assertions."""
    import io as _io, contextlib as _cl
    _b = _io.StringIO()
    with _cl.redirect_stdout(_b):
        ok_self = selftest()
        ok_mutants = mutation_suite()
    print("verified snapshot gate: %s (selftest %s, mutants %s)"
          % ("PASS" if (ok_self and ok_mutants) else "FAIL",
             "OK" if ok_self else "FAIL", "OK" if ok_mutants else "FAIL"))
    # The tally is carried out of the buffer even on a PASS: "mutants OK" is a claim, and the
    # counts are the evidence for it. Killed / errored / survived are three different facts.
    for line in _b.getvalue().splitlines():
        if line.startswith("verified_snapshot mutation suite:"):
            print("  " + line)
    if not (ok_self and ok_mutants):
        print(_b.getvalue().strip())
    return 0 if (ok_self and ok_mutants) else 1


if __name__ == "__main__":
    if "--mutants" in sys.argv:
        sys.exit(0 if mutation_suite() else 1)
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    if "--gate" in sys.argv:
        sys.exit(gate())
    print(__doc__)
