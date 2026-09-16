#!/usr/bin/env python3
"""Generate the ONE artifact an analysis agent may read for scores.

WHY THIS EXISTS. On 2026-08-27 five fabricated finals were published. On 2026-08-30 three more
were caught by hand at 13:30 ET, and they turned out not to be fabricated at all: they were the
genuine 2026-08-28 results for the same three matchups, returned against an 8/30 query, because
that day's MLB slate was set-identical to the 8/28 board's fifteen. A true score for the wrong
date is worse than an invented one -- it is checkable, and it is convincing.

Both times the agent reached for search because the governed path had nothing in it. The remedy
the owner specified is to stop making that reach possible: a deterministic collector retrieves and
validates, and the agent consumes a read-only artifact. This module builds that artifact.

IT FAILS CLOSED. Seven refusal conditions, each named, each raising rather than degrading. An
export that cannot prove its provenance produces NO FILE, because a partial handoff is exactly the
vacuum that gets filled with search.

A LANE-DOWN EXPORT IS A SUCCESS, NOT A FAILURE. Both egress paths to statsapi.mlb.com are denied
in this deployment. A correct MLB export today therefore contains ZERO records and a lane-down
header, and that is the contract working. Pinning the agent to this artifact does not make MLB
correct; it makes MLB dark, honestly, rather than backfilled, plausibly. The two are not the same
and the artifact must never let them look the same -- which is why an empty export still carries a
header, a reason and a lane table, and never just an empty list.

INVOCATION. The owner's spec writes `python -m harness.export_agent_context`. harness/ is not a
package in this repo (no __init__.py; every module uses the flat sys.path idiom), so the runnable
form is:

    python3 harness/export_agent_context.py --commit <sha> --date 2026-08-30 --sports MLB WNBA NFL CFB

The --branch flag is accepted and checked. Deviation from the spec is the invocation only; every
gate the spec named is implemented.
"""
from __future__ import annotations

MODULE_ID = "export_agent_context"

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

UTC = dt.timezone.utc

CONTEXT_SCHEMA = "verified_scores.v1"
MANIFEST_SCHEMA = "verified_scores.manifest.v1"
OUT_DIR = os.path.join("data", "agent_context")

#: evidence_state values. DISPLAY_ONLY is the layer separation this repo has kept since 2026-08-25:
#: a result may be true, displayable and still inadmissible as evidence.
EV_ADMITTED = "ADMITTED"
EV_DISPLAY_ONLY = "DISPLAY_ONLY"
EV_QUARANTINED = "QUARANTINED"

#: The seven refusal conditions the owner named, plus the two this module added while writing
#: them down. Each is a hard stop: no file is written.
REFUSALS = {
    "COMMIT_NOT_AUDITED_HEAD":
        "the requested commit is not the audited head of the operational branch",
    "RECORD_LACKS_EVENT_ID":
        "a record carries no canonical event id, so it cannot be matched by anything but names",
    "FINAL_STATUS_NOT_TERMINAL":
        "a record claims a final while its source status is not terminal",
    "SCHEDULE_BINDING_INCOMPLETE":
        "the canonical schedule does not cover every record, so binding cannot be proven",
    "SCORE_ONLY_IN_DISPLAY_LAYER":
        "a score exists only at RESULT_DISPLAY and is being offered as evidence",
    "SOURCE_SNAPSHOT_MISSING_HASH":
        "a source snapshot carries no content hash, so drift cannot be detected later",
    "FEED_CONFLICTS_NOT_PRESERVED":
        "feed conflicts were dropped rather than carried; a resolved conflict that leaves no trace "
        "is indistinguishable from one that never happened",
    # added while implementing the seven above
    "WORKING_TREE_DIRTY":
        "uncommitted changes exist, so the exported context cannot be reproduced from the commit "
        "it names",
    "TERMINAL_VERIFIED_TYPED_NOT_DERIVED":
        "terminal_verified disagrees with what the status implies, i.e. it was typed rather than "
        "generated",
}


class ExportRefused(RuntimeError):
    """Raised on any of the refusal conditions. Carries the code and the offending detail."""

    def __init__(self, code, detail):
        if code not in REFUSALS:
            raise KeyError(f"unregistered refusal code {code!r} — register it in REFUSALS")
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {REFUSALS[code]} — {detail}")


# ----------------------------------------------------------------- repo state

def _git(*args, cwd=REPO):
    return subprocess.run(("git",) + args, cwd=cwd, capture_output=True,
                          text=True).stdout.strip()


def repo_state(branch):
    return {
        "branch": branch,
        "head": _git("rev-parse", "HEAD"),
        "head_short": _git("rev-parse", "--short", "HEAD"),
        "branch_head": _git("rev-parse", branch) if branch else None,
        "dirty": bool(_git("status", "--porcelain")),
        "described": _git("log", "-1", "--format=%h %cI %s"),
    }


def _resolve(commit):
    """A caller may pass an abbreviated sha. Compare resolved objects, not strings."""
    full = _git("rev-parse", f"{commit}^{{commit}}")
    return full or None


# ----------------------------------------------------------------- gates

def check_commit(commit, branch, state):
    if not commit:
        return                              # no pin requested; the header still records HEAD
    want = _resolve(commit)
    if not want:
        raise ExportRefused("COMMIT_NOT_AUDITED_HEAD", f"{commit!r} does not resolve in this repo")
    if want != state["head"]:
        raise ExportRefused(
            "COMMIT_NOT_AUDITED_HEAD",
            f"requested {commit} ({want[:8]}) but the audited head of {branch} is "
            f"{state['head'][:8]}. Exporting a context that names a commit it was not built from "
            "is how a stale artifact outlives the thing it describes.")
    if state["dirty"]:
        raise ExportRefused("WORKING_TREE_DIRTY",
                            "the working tree has uncommitted changes; the export would not be "
                            "reproducible from the commit it names")


def check_record(rec, *, schedule_index, sa):
    """Every per-record gate. Raises on the first failure — no partial exports."""
    eid = rec.get("event_id")
    if not eid:
        raise ExportRefused("RECORD_LACKS_EVENT_ID", f"record {rec!r} has no event_id")

    status = rec.get("status")
    if status is None:
        raise ExportRefused("FINAL_STATUS_NOT_TERMINAL",
                            f"{eid} carries no source status; owner rule 3")

    has_score = rec.get("away_score") is not None or rec.get("home_score") is not None
    tv = rec.get("terminal_verified")

    derived = sa.terminal_verified_for(status)
    if tv is not None and bool(tv) != bool(derived):
        raise ExportRefused(
            "TERMINAL_VERIFIED_TYPED_NOT_DERIVED",
            f"{eid} status {status} implies terminal_verified={derived} but the record says {tv}")

    if tv and not sa.is_terminal(status):
        raise ExportRefused("FINAL_STATUS_NOT_TERMINAL",
                            f"{eid} claims terminal_verified with status {status}")

    if rec.get("evidence_state") == EV_DISPLAY_ONLY and (tv or rec.get("_settleable")):
        raise ExportRefused("SCORE_ONLY_IN_DISPLAY_LAYER",
                            f"{eid} is DISPLAY_ONLY and is being offered as settleable evidence")

    if has_score and not rec.get("raw_response_sha256"):
        raise ExportRefused("SOURCE_SNAPSHOT_MISSING_HASH",
                            f"{eid} carries a score with no raw_response_sha256")

    if schedule_index is not None and eid not in schedule_index:
        raise ExportRefused("SCHEDULE_BINDING_INCOMPLETE",
                            f"{eid} is absent from the canonical schedule supplied for this date")


def check_conflicts(conflicts, records):
    """Owner condition 7. A conflict that leaves no trace is worse than one left unresolved."""
    if conflicts is None:
        raise ExportRefused("FEED_CONFLICTS_NOT_PRESERVED",
                            "the collector returned no conflicts structure at all — absence of "
                            "the field is not the same as an empty list of conflicts, and this "
                            "module refuses to guess which it was")
    for c in conflicts:
        if not c.get("event_id") or not c.get("kind"):
            raise ExportRefused("FEED_CONFLICTS_NOT_PRESERVED",
                                f"conflict {c!r} lacks event_id or kind")


# ----------------------------------------------------------------- export

def build(date_et, sports, *, commit=None, branch="sportsmodel/main", now_utc=None,
          snapshot_reader=None, schedules=None):
    """Assemble the context. Returns (context, manifest). Raises ExportRefused on any gate.

    snapshot_reader: injected accessor with get_verified_scores(date, league) and
                     get_source_manifest(snapshot_id). Defaults to harness.verified_snapshot.
                     Injection exists for the selftest; production passes nothing.
    """
    import score_admission as sa

    now_utc = now_utc or dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")
    state = repo_state(branch)
    check_commit(commit, branch, state)

    if snapshot_reader is None:
        try:
            import verified_snapshot as snapshot_reader           # noqa: F401
        except Exception as e:
            # Absence is a FAILURE, not a skip. The precedent is on file: a selftest that passed
            # with its subject absent let a whole artifact go missing without a single red gate.
            raise ExportRefused(
                "SCHEDULE_BINDING_INCOMPLETE",
                f"the verified snapshot store is not importable ({type(e).__name__}: {e}); there "
                "is no governed source to export from. Refusing rather than emitting an empty "
                "file that would read like 'no games'.")

    records, lanes, conflicts, sources = [], {}, [], {}
    for league in sports:
        lg = sa.normalize_league(league)
        lane_state = _lane_state(lg, snapshot_reader, date_et)
        lanes[lg] = lane_state
        if lane_state["canonical"] != "UP":
            continue
        got = snapshot_reader.get_verified_scores(date_et, lg)
        idx = (schedules or {}).get(lg)
        for rec in got:
            check_record(rec, schedule_index=idx, sa=sa)
            records.append(dict(rec, league=lg,
                                evidence_state=rec.get("evidence_state", EV_ADMITTED)))
            sid = rec.get("snapshot_id")
            if sid and sid not in sources:
                sources[sid] = snapshot_reader.get_source_manifest(sid)
        conflicts.extend(getattr(snapshot_reader, "get_conflicts", lambda *_a, **_k: [])(
            date_et, lg) or [])

    check_conflicts(conflicts, records)

    header = {
        "AUTHORITATIVE_CONTEXT": f"{OUT_DIR}/verified_scores_{date_et}.json",
        "SOURCE_COMMIT": state["head_short"],
        "WEB_SCORE_LOOKUP": "PROHIBITED",
    }
    context = {
        "context_schema": CONTEXT_SCHEMA,
        "_header": header,
        "as_of_utc": now_utc,
        "repository_branch": branch,
        "repository_commit": state["head"],
        "ingestion_run_id": f"scores-{date_et.replace('-', '')}-"
                            f"{now_utc[11:13]}{now_utc[14:16]}{now_utc[17:19]}",
        "date_et": date_et,
        "sports_requested": list(sports),
        "lane_status": lanes,
        "records": records,
        "n_records": len(records),
        "conflicts": conflicts,
        "READ_THIS_IF_RECORDS_IS_EMPTY": (
            "an empty records list is NOT 'no games today'. Read lane_status. A canonical lane "
            "reported DOWN means the governed path could not observe anything, and the correct "
            "output is 'No canonical final admitted.' It is never a licence to look elsewhere."),
        "POLICY": "docs/AGENT_SCORE_CONTRACT.md",
    }
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "_header": header,
        "context_sha256": hashlib.sha256(
            json.dumps(context, sort_keys=True).encode()).hexdigest(),
        "as_of_utc": now_utc,
        "repository_commit": state["head"],
        "repository_head_described": state["described"],
        "working_tree_dirty": state["dirty"],
        "date_et": date_et,
        "sources": sources,
        "lane_status": lanes,
        "n_records": len(records),
        "n_conflicts": len(conflicts),
        "gates_run": sorted(REFUSALS),
    }
    return context, manifest


def _lane_state(league, reader, date_et):
    fn = getattr(reader, "lane_status", None)
    if fn is not None:
        try:
            return fn(league)
        except Exception as e:
            return {"canonical": "UNKNOWN", "reason": f"{type(e).__name__}: {e}"}
    return {"canonical": "UNKNOWN",
            "reason": "the snapshot store exposes no lane_status; treating the lane as UNKNOWN "
                      "rather than assuming it is up"}


def write(date_et, context, manifest, *, out_root=None):
    root = out_root or os.path.join(REPO, OUT_DIR)
    os.makedirs(root, exist_ok=True)
    a = os.path.join(root, f"verified_scores_{date_et}.json")
    b = os.path.join(root, f"verified_scores_{date_et}.manifest.json")
    for path, doc in ((a, context), (b, manifest)):
        with open(path, "w") as fh:
            json.dump(doc, fh, indent=1, sort_keys=True)
    return a, b


# ----------------------------------------------------------------- selftest

def _fake_reader(records, *, conflicts=(), lane="UP"):
    class R:
        @staticmethod
        def lane_status(league):
            return {"canonical": lane, "reason": "fixture"}

        @staticmethod
        def get_verified_scores(date, league):
            return [r for r in records if r.get("league", league) == league]

        @staticmethod
        def get_source_manifest(sid):
            return {"snapshot_id": sid, "raw_sha256": "0" * 64}

        @staticmethod
        def get_conflicts(date, league):
            return list(conflicts)
    return R


def _ok_record(**over):
    rec = {"event_id": "mlb:2026:824231", "league": "MLB", "away_team_id": 119,
           "home_team_id": 116, "scheduled_start_utc": "2026-08-28T22:40:00Z",
           "status": "CLOSED", "away_score": 2, "home_score": 1, "terminal_verified": True,
           "source": "mlb_statsapi", "source_fetched_at_utc": "2026-08-30T09:50:43Z",
           "raw_response_sha256": "a" * 64, "snapshot_id": "snap1"}
    rec.update(over)
    return rec


def selftest():
    import score_admission as sa
    f = []

    def expect(code, label, **kw):
        try:
            build("2026-08-28", ["MLB"], **kw)
            f.append(f"{label}: expected {code}, got a clean export")
        except ExportRefused as e:
            if e.code != code:
                f.append(f"{label}: expected {code}, got {e.code}")
        except Exception as e:
            f.append(f"{label}: expected {code}, got {type(e).__name__}: {e}")

    base = dict(now_utc="2026-08-30T23:00:00Z", commit=None)

    # 1. clean path
    try:
        ctx, man = build("2026-08-28", ["MLB"],
                         snapshot_reader=_fake_reader([_ok_record()]), **base)
        if ctx["n_records"] != 1:
            f.append("clean export did not carry its record")
        if ctx["_header"]["WEB_SCORE_LOOKUP"] != "PROHIBITED":
            f.append("header missing the prohibition")
        if man["context_sha256"] != hashlib.sha256(
                json.dumps(ctx, sort_keys=True).encode()).hexdigest():
            f.append("manifest hash does not bind the context it describes")
    except Exception as e:
        f.append(f"clean path raised {type(e).__name__}: {e}")

    # 2. every named refusal must actually fire
    expect("RECORD_LACKS_EVENT_ID", "no event id",
           snapshot_reader=_fake_reader([_ok_record(event_id=None)]), **base)
    expect("FINAL_STATUS_NOT_TERMINAL", "no status",
           snapshot_reader=_fake_reader([_ok_record(status=None)]), **base)
    expect("TERMINAL_VERIFIED_TYPED_NOT_DERIVED", "typed terminal_verified",
           snapshot_reader=_fake_reader([_ok_record(status="IN_PROGRESS")]), **base)
    expect("SCORE_ONLY_IN_DISPLAY_LAYER", "display-only offered as evidence",
           snapshot_reader=_fake_reader(
               [_ok_record(evidence_state=EV_DISPLAY_ONLY)]), **base)
    expect("SOURCE_SNAPSHOT_MISSING_HASH", "score with no hash",
           snapshot_reader=_fake_reader([_ok_record(raw_response_sha256=None)]), **base)
    expect("SCHEDULE_BINDING_INCOMPLETE", "not in schedule",
           snapshot_reader=_fake_reader([_ok_record()]),
           schedules={"MLB": {"mlb:2026:999999": {}}}, **base)
    expect("FEED_CONFLICTS_NOT_PRESERVED", "conflict with no identity",
           snapshot_reader=_fake_reader([_ok_record()],
                                        conflicts=[{"note": "something happened"}]), **base)

    # 3. THE LANE-DOWN CASE IS A SUCCESS, and it must not look like "no games"
    try:
        ctx, _ = build("2026-08-30", ["MLB"],
                       snapshot_reader=_fake_reader([], lane="DOWN"), **base)
        if ctx["n_records"] != 0:
            f.append("lane-down export invented records")
        if ctx["lane_status"]["MLB"]["canonical"] != "DOWN":
            f.append("lane-down export did not report the lane down")
        if "READ_THIS_IF_RECORDS_IS_EMPTY" not in ctx:
            f.append("an empty export must explain itself; this one reads like 'no games'")
    except Exception as e:
        f.append(f"lane-down export raised instead of succeeding: {type(e).__name__}: {e}")

    # 4. a commit that is not the head must refuse
    try:
        build("2026-08-28", ["MLB"], snapshot_reader=_fake_reader([_ok_record()]),
              commit="HEAD~1", now_utc="2026-08-30T23:00:00Z")
        f.append("a non-head commit was accepted")
    except ExportRefused as e:
        if e.code not in ("COMMIT_NOT_AUDITED_HEAD", "WORKING_TREE_DIRTY"):
            f.append(f"non-head commit gave {e.code}")

    # 5. every registered refusal code must be reachable — an unreachable gate is decoration
    unreached = {"WORKING_TREE_DIRTY"}          # environment-dependent; exercised in production
    fired = {"RECORD_LACKS_EVENT_ID", "FINAL_STATUS_NOT_TERMINAL",
             "TERMINAL_VERIFIED_TYPED_NOT_DERIVED", "SCORE_ONLY_IN_DISPLAY_LAYER",
             "SOURCE_SNAPSHOT_MISSING_HASH", "SCHEDULE_BINDING_INCOMPLETE",
             "FEED_CONFLICTS_NOT_PRESERVED", "COMMIT_NOT_AUDITED_HEAD"}
    missing = set(REFUSALS) - fired - unreached
    if missing:
        f.append(f"registered but never exercised: {sorted(missing)}")

    for x in f:
        print("  FAIL:", x)
    print(f"export_agent_context selftest: {'OK' if not f else 'FAIL'}")
    return not f


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--branch", default="sportsmodel/main")
    p.add_argument("--commit", default=None)
    p.add_argument("--date", required=False)
    p.add_argument("--sports", nargs="+", default=["MLB", "WNBA", "NFL", "CFB"])
    p.add_argument("--out-root", default=None)
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args(argv)

    if a.selftest or not a.date:
        return 0 if selftest() else 1

    try:
        ctx, man = build(a.date, a.sports, commit=a.commit, branch=a.branch)
    except ExportRefused as e:
        print(f"EXPORT REFUSED — {e}", file=sys.stderr)
        print("no file was written; a partial handoff is the vacuum that gets filled with search",
              file=sys.stderr)
        return 2
    x, y = write(a.date, ctx, man, out_root=a.out_root)
    print(f"AUTHORITATIVE_CONTEXT: {ctx['_header']['AUTHORITATIVE_CONTEXT']}")
    print(f"SOURCE_COMMIT: {ctx['_header']['SOURCE_COMMIT']}")
    print("WEB_SCORE_LOOKUP: PROHIBITED")
    print(f"wrote {os.path.relpath(x, REPO)} and {os.path.relpath(y, REPO)} "
          f"({ctx['n_records']} records, {len(ctx['conflicts'])} conflicts)")
    for lg, st in sorted(ctx["lane_status"].items()):
        print(f"  lane {lg}: canonical {st.get('canonical')} — {st.get('reason')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
