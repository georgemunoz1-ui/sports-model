#!/usr/bin/env python3
"""PROSPECTIVITY EVIDENCE — who stamped the timestamp that proves a forecast came first.

OWNER DIRECTIVE 2026-08-24: "Verify prospectivity using a remotely observed timestamp."

WHAT I HAD BEEN DOING, AND WHY IT DOES NOT PROVE ANYTHING. The 8/23 cohort's prospectivity rested on
a git commit date: 2026-08-23T10:22:21Z, 7h12m39s before first pitch. A git commit date is a field
INSIDE the commit object, written by the machine that made the commit — mine. I can set it to any
value I like with one environment variable. As evidence that a forecast existed before a game, it is
a statement by the party who benefits from it being true.

AND FETCHING IT FROM GITHUB DOES NOT FIX IT. Asking the GitHub API for that commit returns
author.date and committer.date — the same author-written fields, echoed back. It LOOKS like remote
corroboration and is not: GitHub is repeating my claim, not making an observation. That distinction
is the whole point of this module, and it is easy to miss precisely because the round trip feels
like verification.

THE THREE GRADES:

  SELF_ASSERTED_LOCAL      a git author/committer date. Written by me. No corroboration.
  REMOTE_ECHOED            the same field, read back from a remote service. Still written by me.
                           The most dangerous grade, because it wears the costume of the third.
  REMOTE_OBSERVED          an instant the remote service GENERATED: a workflow run's created_at, a
                           check run, a release's published_at, a push event, an issue or comment
                           creation time. The service had no reason to lie and no way to be told.

FINDING FOR 2026-08-23: NO REMOTE_OBSERVED TIMESTAMP EXISTS. The repository has zero workflow runs,
so no CI stamp was ever created for that commit, and no release or tag was cut. The cohort's
prospectivity is therefore SELF_ASSERTED, corroborated by nothing. It is very likely true — the
commit is deeply consistent with a long chain of prior work, and the owner watched the card go out —
but "likely true" is the state, and this module refuses to print "proven".

WHAT PRODUCES A REMOTE OBSERVATION GOING FORWARD, cheapest first: push the card, then cause the
remote to stamp something that references the pushed SHA — a CI workflow on push is the cleanest,
a release/tag is next, and an issue comment naming the SHA works with nothing but the API. Any of
them binds "this SHA existed by this instant" to a clock that is not mine. None of them can be
back-dated onto 8/23; prospectivity evidence must be created BEFORE the event it protects, which is
the one property that makes it worth anything.

API
  grade(kind)                       -> which of the three a timestamp source is
  verify(claim)                     -> (status, detail) for one prospectivity claim
  binding_lead(instants, event_utc) -> the lead time from the LATEST pregame instant, in seconds
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

SELF_ASSERTED = "SELF_ASSERTED_LOCAL"
REMOTE_ECHOED = "REMOTE_ECHOED_SELF_ASSERTED"
REMOTE_OBSERVED = "REMOTE_OBSERVED"
UNKNOWN_KIND = "UNKNOWN_TIMESTAMP_SOURCE"

#: How each known timestamp source is graded. The middle row is the one that matters.
SOURCE_GRADE = {
    "git_author_date": SELF_ASSERTED,
    "git_committer_date": SELF_ASSERTED,
    "local_clock": SELF_ASSERTED,
    "file_mtime": SELF_ASSERTED,
    "github_api_commit_author_date": REMOTE_ECHOED,
    "github_api_commit_committer_date": REMOTE_ECHOED,
    "github_workflow_run_created_at": REMOTE_OBSERVED,
    "github_check_run_started_at": REMOTE_OBSERVED,
    "github_release_published_at": REMOTE_OBSERVED,
    "github_push_event_created_at": REMOTE_OBSERVED,
    "github_issue_comment_created_at": REMOTE_OBSERVED,
    "artifact_service_published_at": REMOTE_OBSERVED,
}

PROVEN = "PROSPECTIVITY_REMOTELY_OBSERVED"
NOT_CORROBORATED = "PROSPECTIVITY_SELF_ASSERTED_NOT_REMOTELY_CORROBORATED"
REFUTED = "PROSPECTIVITY_REFUTED_TIMESTAMP_AT_OR_AFTER_EVENT"
NO_EVIDENCE = "PROSPECTIVITY_NO_TIMESTAMP_SUPPLIED"

WHY_NOT_PROVEN = (
    "every supplied instant is a value I wrote, including any read back from a remote API — an "
    "echoed author date is my claim repeated, not an observation. A remote observation is an "
    "instant the service GENERATED.")


def grade(kind):
    return SOURCE_GRADE.get(kind, UNKNOWN_KIND)


def _parse(t):
    if not t or "T" not in str(t):
        return None
    try:
        return dt.datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def binding_lead(instants, event_utc):
    """Lead time from the LATEST supplied pregame instant — prospectivity is only as strong as its
    weakest link, so the binding number is the last thing that had to exist, not the first."""
    ev = _parse(event_utc)
    parsed = [(k, _parse(v)) for k, v in (instants or {}).items()]
    parsed = [(k, t) for k, t in parsed if t is not None]
    if ev is None or not parsed:
        return None, None, None
    k, latest = max(parsed, key=lambda kv: kv[1])
    return int((ev - latest).total_seconds()), k, latest.strftime("%Y-%m-%dT%H:%M:%SZ")


def verify(claim):
    """`claim`: {"event_utc", "instants": {source_kind: instant, ...}}

    Returns the strongest grade among instants that actually precede the event, and refuses to call
    a claim proven on anything weaker than a remote observation.
    """
    ev = _parse(claim.get("event_utc"))
    instants = claim.get("instants") or {}
    if ev is None:
        return NO_EVIDENCE, {"reason": f"event_utc {claim.get('event_utc')!r} is not an instant"}
    graded, unknown = [], []
    for kind, val in sorted(instants.items()):
        t = _parse(val)
        g = grade(kind)
        if g == UNKNOWN_KIND:
            unknown.append(kind)
            continue
        if t is None:
            continue
        graded.append({"kind": kind, "instant": val, "grade": g, "precedes_event": t < ev})
    if not graded:
        return NO_EVIDENCE, {"reason": "no parseable timestamp of a known kind", "unknown": unknown}
    if not any(g["precedes_event"] for g in graded):
        return REFUTED, {"graded": graded, "unknown": unknown}
    observed = [g for g in graded if g["grade"] == REMOTE_OBSERVED and g["precedes_event"]]
    lead, src, inst = binding_lead(
        {g["kind"]: g["instant"] for g in graded if g["precedes_event"]}, claim.get("event_utc"))
    detail = {"graded": graded, "unknown": unknown,
              "binding_lead_seconds": lead, "binding_source": src, "binding_instant": inst,
              "n_remote_observed": len(observed)}
    if observed:
        return PROVEN, detail
    detail["why_not_proven"] = WHY_NOT_PROVEN
    return NOT_CORROBORATED, detail


# =================================================================================================
def selftest():
    f = []
    FP = "2026-08-23T17:35:00Z"

    # --- the grades, and the one that wears a costume ---------------------------------------------
    if grade("git_committer_date") != SELF_ASSERTED:
        f.append("a git committer date is self-asserted")
    if grade("github_api_commit_author_date") != REMOTE_ECHOED:
        f.append("an author date read back from GitHub is ECHOED, not observed")
    if grade("github_api_commit_author_date") == REMOTE_OBSERVED:
        f.append("an echoed author date must never grade as a remote observation")
    if grade("github_workflow_run_created_at") != REMOTE_OBSERVED:
        f.append("a workflow run's created_at is remotely observed")
    if grade("something_new") != UNKNOWN_KIND:
        f.append("an unregistered source is unknown, not assumed good")

    # --- the actual 2026-08-23 claim --------------------------------------------------------------
    real = {"event_utc": FP,
            "instants": {"git_committer_date": "2026-08-23T10:22:21Z",
                         "github_api_commit_committer_date": "2026-08-23T10:22:21Z",
                         "local_clock": "2026-08-23T10:04:27Z"}}
    st, d = verify(real)
    if st != NOT_CORROBORATED:
        f.append(f"the 8/23 claim has no remote observation and must not be proven, got {st}")
    if d["n_remote_observed"] != 0:
        f.append("no remote observation exists for 8/23")
    if d["binding_lead_seconds"] != 7 * 3600 + 12 * 60 + 39:
        f.append(f"binding lead must be 7h12m39s, got {d['binding_lead_seconds']}s")
    if d["binding_source"] not in ("git_committer_date", "github_api_commit_committer_date"):
        f.append(f"the binding source must be the LATEST instant, got {d['binding_source']}")
    if not d.get("why_not_proven"):
        f.append("an uncorroborated claim must say why it is not proven, not carry an empty field")
    if "echoed" not in d.get("why_not_proven", "").lower():
        f.append("the explanation must name the echoed-timestamp trap specifically")

    # --- with a real remote observation it does become proven -------------------------------------
    with_ci = {"event_utc": FP,
               "instants": dict(real["instants"],
                                github_workflow_run_created_at="2026-08-23T10:23:05Z")}
    st2, d2 = verify(with_ci)
    if st2 != PROVEN or d2["n_remote_observed"] != 1:
        f.append(f"a workflow stamp before the event proves prospectivity, got {st2}")
    if d2["binding_lead_seconds"] != 7 * 3600 + 11 * 60 + 55:
        f.append(f"the binding lead must move to the LATER remote stamp, got {d2['binding_lead_seconds']}")

    # --- a remote observation AFTER the event proves nothing about before it ----------------------
    late = {"event_utc": FP,
            "instants": {"github_workflow_run_created_at": "2026-08-23T18:00:00Z",
                         "git_committer_date": "2026-08-23T10:22:21Z"}}
    st3, d3 = verify(late)
    if st3 != NOT_CORROBORATED:
        f.append(f"a post-event remote stamp does not corroborate prospectivity, got {st3}")
    if d3["binding_lead_seconds"] != 7 * 3600 + 12 * 60 + 39:
        f.append("a post-event instant must not enter the binding lead")

    # --- everything after the event is refuted ----------------------------------------------------
    after = {"event_utc": FP, "instants": {"git_committer_date": "2026-08-23T19:00:00Z"}}
    if verify(after)[0] != REFUTED:
        f.append("a claim whose every instant follows the event is refuted")
    # exactly AT the event is not before it
    at = {"event_utc": FP, "instants": {"git_committer_date": FP}}
    if verify(at)[0] != REFUTED:
        f.append("an instant exactly at first pitch is not prospective")

    # --- nothing supplied, and unparseable input --------------------------------------------------
    if verify({"event_utc": FP, "instants": {}})[0] != NO_EVIDENCE:
        f.append("no instants means no evidence")
    if verify({"event_utc": "2026-08-23", "instants": {"local_clock": "2026-08-23T10:00:00Z"}})[0] != NO_EVIDENCE:
        f.append("a calendar-date event is not an instant")
    unk = verify({"event_utc": FP, "instants": {"vibes": "2026-08-23T10:00:00Z"}})
    if unk[0] != NO_EVIDENCE or "vibes" not in unk[1]["unknown"]:
        f.append("an unknown source must be reported, not silently counted")

    for x in f:
        print("FAIL:", x)
    if not f:
        print("prospectivity_evidence selftest: OK")
    return f


MUTANTS = [
    ("an echoed author date is promoted to a remote observation",
     '    "github_api_commit_author_date": REMOTE_ECHOED,\n    "github_api_commit_committer_date": REMOTE_ECHOED,',
     '    "github_api_commit_author_date": REMOTE_OBSERVED,\n    "github_api_commit_committer_date": REMOTE_OBSERVED,'),
    ("a git committer date counts as remote",
     '    "git_committer_date": SELF_ASSERTED,', '    "git_committer_date": REMOTE_OBSERVED,'),
    ("a self-asserted claim is reported as proven",
     '    if observed:\n        return PROVEN, detail', "    if True:\n        return PROVEN, detail"),
    ("an unknown source is assumed to be a remote observation",
     "    return SOURCE_GRADE.get(kind, UNKNOWN_KIND)", "    return SOURCE_GRADE.get(kind, REMOTE_OBSERVED)"),
    ("a post-event remote stamp counts as corroboration",
     '    observed = [g for g in graded if g["grade"] == REMOTE_OBSERVED and g["precedes_event"]]',
     '    observed = [g for g in graded if g["grade"] == REMOTE_OBSERVED]'),
    ("the binding lead takes the EARLIEST instant instead of the latest",
     "    k, latest = max(parsed, key=lambda kv: kv[1])", "    k, latest = min(parsed, key=lambda kv: kv[1])"),
    ("post-event instants are folded into the binding lead",
     '        {g["kind"]: g["instant"] for g in graded if g["precedes_event"]}, claim.get("event_utc"))',
     '        {g["kind"]: g["instant"] for g in graded}, claim.get("event_utc"))'),
    ("an instant exactly at the event counts as preceding it",
     '        graded.append({"kind": kind, "instant": val, "grade": g, "precedes_event": t < ev})',
     '        graded.append({"kind": kind, "instant": val, "grade": g, "precedes_event": t <= ev})'),
    ("a claim with every instant after the event is not refuted",
     '    if not any(g["precedes_event"] for g in graded):', "    if False:"),
    ("the uncorroborated verdict stops explaining itself",
     'WHY_NOT_PROVEN = (', 'WHY_NOT_PROVEN = "" and ('),
    ("a calendar date passes as an instant",
     '    if not t or "T" not in str(t):\n        return None', "    if not t:\n        return None"),
    ("unknown sources are dropped instead of reported",
     "        if g == UNKNOWN_KIND:\n            unknown.append(kind)\n            continue",
     "        if g == UNKNOWN_KIND:\n            continue"),
]


def mutation_suite(verbose=True):
    import subprocess as _sp, tempfile as _tf
    src = open(os.path.abspath(__file__)).read()
    i = src.index("MUTANTS = [")
    j = src.index("\ndef mutation_suite", i)
    head, block, tail = src[:i], src[i:j], src[j:]
    surv, unapp = [], []
    for name, old, new in MUTANTS:
        where = "head" if old in head else ("tail" if old in tail else None)
        if where is None:
            unapp.append(f"{name}: pattern not found"); continue
        mut = (head.replace(old, new, 1) + block + tail) if where == "head" \
            else (head + block + tail.replace(old, new, 1))
        if mut == src:
            unapp.append(f"{name}: no-op"); continue
        with _tf.NamedTemporaryFile("w", suffix="_mutant.py", delete=False,
                                    dir=os.path.dirname(os.path.abspath(__file__))) as fh:
            fh.write(mut); path = fh.name
        try:
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True, timeout=120)
            killed = pr.returncode != 0
        except _sp.TimeoutExpired:
            killed = True
        finally:
            os.unlink(path)
        if verbose:
            print(f"  {'KILLED  ' if killed else 'SURVIVED'}  {name}")
        if not killed:
            surv.append(name)
    for u in unapp:
        print(f"  UNAPPLIED  {u}")
    print(f"mutation suite: {len(MUTANTS)-len(surv)-len(unapp)}/{len(MUTANTS)} killed"
          f"{'' if not (surv or unapp) else '  — SURVIVORS MEAN DECORATIVE FIXTURES'}")
    return surv + unapp


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    if "--mutants" in sys.argv:
        sys.exit(1 if mutation_suite() else 0)
    print(__doc__)
