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
    get_quarantine(date, league)      deliberately NOT an analysis tool. Reading the refused
                                      side is an audit act and has to look like one.

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
            if bad:
                problems.extend(bad)
                continue
        entry = {"record": record, "verdict": verdict.to_dict(), "sink": sink}
        try:
            _canonical(entry)
        except (TypeError, ValueError) as e:
            problems.append({"code": REFUSE_NOT_SERIALIZABLE, "index": i, "detail": str(e)})
            continue
        entries.append(entry)
    return entries, problems


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

    ANALYSIS TOOL SURFACE. Read-only, like the other two."""
    sa.assert_tool_allowed("get_source_manifest")
    directory = _snapshot_dir(os.path.abspath(root), snapshot_id)
    path = os.path.join(directory, MANIFEST_NAME)
    if not os.path.isfile(path):
        raise SnapshotNotFound(snapshot_id)
    return _read_json(path)


def _entries_of(manifest, kind, root):
    directory = _snapshot_dir(os.path.abspath(root), manifest["snapshot_id"])
    name = VERIFIED_NAME if kind == "verified" else QUARANTINE_NAME
    path = os.path.join(directory, name)
    if not os.path.isfile(path):
        raise SnapshotImmutabilityViolation(
            "a snapshot is missing an entry file the manifest names",
            {"snapshot_id": manifest["snapshot_id"], "file": name, "code": DRIFT_FILE_MISSING})
    return (_read_json(path) or {}).get("entries") or []


def _verified_candidates(root, event_id=None, date_et=None, league=None):
    """Every stored VERIFIED entry matching the filter, newest write last."""
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
            out.append({"record": record, "verdict": entry.get("verdict"),
                        "snapshot_id": manifest["snapshot_id"],
                        "written_at_utc": manifest.get("written_at_utc")})
    out.sort(key=lambda c: (str(c["written_at_utc"]), c["snapshot_id"]))
    return out


def _resolve(candidates):
    """The record a caller should read, from several observations of one event.

    A later observation supersedes an earlier one — IN_PROGRESS at 18:45 then CLOSED at 20:30 is
    two honest observations and both are kept on disk. But two records claiming the SAME source
    and the SAME fetched instant with DIFFERENT content hashes are not two observations; that is
    an archive that changed under one key, and it RAISES rather than picking a winner.
    """
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            conflict, problem = sa.content_hash_conflict(candidates[i]["record"],
                                                         candidates[j]["record"])
            if conflict:
                raise SnapshotContentConflict(dict(
                    problem, snapshot_ids=[candidates[i]["snapshot_id"],
                                           candidates[j]["snapshot_id"]],
                    event_id=candidates[i]["record"].get("event_id")))
    return candidates[-1]["record"] if candidates else None


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

        sid = write_snapshot(envelopes + [snippet, search_env], league="MLB",
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
        if get_verified_score(sa.EID_WNBA, root=wnba_root) is not None:
            f.append("S2: an event stored only in quarantine was returned as a verified score")
        if get_verified_scores("2026-08-30", "WNBA", root=wnba_root) != []:
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
        expect_refusal("R: a record from another league",
                       w(**{"league": "WNBA"}), REFUSE_LEAGUE_MISMATCH)
        # THE UTC-SLICE BUG, in its exact shape: a 2026-08-31T00:30Z start is the ET EVENING of
        # 08-30, so filing it under 08-31 must refuse.
        late = _record(sa.EID_WNBA, "SYNTH_MIN", "SYNTH_ATL", _LATE, sa.CLOSED, 81, 78,
                       sha=sha, league="WNBA")
        late_env = _admit(late, now_utc="2026-08-31T04:00:00Z", lane=sa.LANE_CANONICAL,
                          schedule=None)
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
#     Each entry names the DEFECT RESTORED, not a test. Every one must be KILLED by selftest().
# ---------------------------------------------------------------------------------------------

MUTANTS = [
    ("an existing snapshot whose bytes have changed is silently accepted as a no-op (R6)",
     "    if not identical:",
     "    if False:"),
    ("a quarantined entry is checked, and therefore filed, as if it were verified",
     "        if sink in VERIFIED_SINKS:",
     "        if True:"),
    ("a quarantined record leaks out through the READ path — get_verified_score reaches the "
     "other side of the store (the 8/27 publication path, in getter form)",
     "        for entry in _entries_of(manifest, \"verified\", root):",
     "        for entry in _entries_of(manifest, \"verified\", root) + "
     "_entries_of(manifest, \"quarantine\", root):"),
    ("verify_snapshot stops comparing a stored payload's bytes to its recorded hash",
     "        if actual != declared.get(\"sha256\"):",
     "        if False:"),
    ("the snapshot id stops covering the payload hashes, so drifted bytes leave the id true",
     "            \"payloads\": sorted(payload_descriptors, key=lambda p: p[\"payload_id\"])}",
     "            \"payloads\": []}"),
    ("the snapshot id stops covering the records, so different content collides on one id",
     "            \"entries\": sorted(entries, key=_canonical),",
     "            \"entries\": [],"),
    ("verify_snapshot stops comparing records.json and quarantine.json to their hashes",
     "        if declared.get(\"sha256\") != actual:",
     "        if False:"),
    ("routing is decided by the store instead of by the verdict's own recorded lane",
     "        sink = sa.sink_for(verdict)",
     "        sink = sa.SINK_RESULT_LEDGER"),
    ("an admitted record no longer has to validate",
     "    ok, record_problems = sa.validate_record(record)",
     "    ok, record_problems = True, []"),
    ("an admitted record's source hash no longer has to be covered by a stored payload "
     "(owner rule 7 becomes decorative)",
     "    if sha not in payload_shas:",
     "    if False:"),
    ("the ET date of an admitted record is no longer checked against the slate (the UTC-slice "
     "bug, restored)",
     "    if row_date != date_et:",
     "    if False:"),
    ("a snapshot may be written with no raw payload at all (owner rule 7 unenforced)",
     "    if raw_payloads is None or (isinstance(raw_payloads, (list, tuple)) "
     "and not raw_payloads):",
     "    if False:"),
    ("an empty snapshot is accepted, so a down lane and an empty slate look identical on disk",
     "    if not isinstance(records, (list, tuple)) or not records:",
     "    if not isinstance(records, (list, tuple)):"),
    ("two admitted records for one event id are accepted",
     "    if event_id in seen_event_ids:",
     "    if False:"),
    ("a caller-supplied sha256 is trusted instead of the sha256 of the bytes",
     "        if declared is not None and str(declared).strip().lower() != sha:",
     "        if False:"),
    ("get_verified_score returns the FIRST observation instead of the latest",
     "    return candidates[-1][\"record\"] if candidates else None",
     "    return candidates[0][\"record\"] if candidates else None"),
    ("the mutable-archive conflict is resolved silently instead of raised",
     "            if conflict:",
     "            if False:"),
    ("a partial snapshot with no manifest is served around, so 'fewer games' reads as "
     "'a quiet night'",
     "        if not os.path.isfile(manifest_path):",
     "        if False:"),
]


def mutation_suite():
    """Break one protection at a time; every mutant must be caught by selftest().

    Sixteen of the eighteen die on a NAMED assertion. Two (the quarantine entry checked as
    verified, and the store overriding score_admission's routing) die when a fixture write is
    refused mid-run; the selftest catches that and prints it as UNEXPECTED with the refusing
    rule's own message, so the output still says which protection was removed rather than only
    that something broke.
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
    print(f"verified_snapshot mutation suite: {killed}/{len(MUTANTS)} killed"
          + ("" if killed == len(MUTANTS) else "  — SURVIVORS MEAN DECORATIVE FIXTURES"))
    return killed == len(MUTANTS)


def gate():
    """Healthcheck entry point: the fixtures hold AND the mutants die."""
    import io as _io, contextlib as _cl
    _b = _io.StringIO()
    with _cl.redirect_stdout(_b):
        ok_self = selftest()
        ok_mutants = mutation_suite()
    print("verified snapshot gate: %s (selftest %s, mutants %s)"
          % ("PASS" if (ok_self and ok_mutants) else "FAIL",
             "OK" if ok_self else "FAIL", "OK" if ok_mutants else "FAIL"))
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
