#!/usr/bin/env python3
"""Executes the acquisition ladder. The piece that was missing.

WHY THIS EXISTS. On 2026-08-30 I searched twice for Atlanta Dream availability, got a report
32 days stale, rejected it correctly, and then TERMINATED with AVAILABILITY_UNKNOWN. One more
query on the SAME rail returned the current information immediately. The stale artifact was
evidence that ONE artifact was unusable; it said nothing about whether current information
existed.

route_ladder_v1 already stated the rule -- a blocked rail advances the ladder, and acquisition
cannot terminate while an authorized route remains untried. But route_ladder_v1.attempt() takes an
ALREADY-COLLECTED set of attempts and judges whether they were sufficient. It can say "you stopped
too soon". It cannot make anything continue. The repo had a control plane and no execution plane,
and the agent behaved like the old system: search, stale result, abstain.

THE CONSTRAINT THAT SHAPES THIS MODULE, stated plainly because it changes the owner's design.
The only working egress in this deployment is WebFetch/WebSearch, and those are TOOLS IN THE AGENT
LOOP, not Python callables. No Python function can invoke them. So "the session bootstrap creates
the approved get= implementation automatically" is not implementable here: there is nothing to
bind a get= to. feed_espn and acquisition_adapters will keep refusing by default and that is
correct -- the fetch has to round-trip through the agent.

What IS implementable, and is what this module does, is to make the ladder DRIVE that loop:

    plan = open_plan(subject, field, date_et)
    while True:
        action = next_action(plan)          # the next UNTRIED authorized rung, as an instruction
        if action is None: break            # exhausted, and only then
        # the agent executes action with its own tools and comes back
        record_attempt(plan, action.rung, outcome, artifact)

Every non-OBTAINED outcome ADVANCES. BLOCKED advances. NOT_FOUND advances. STALE_REJECTED
advances -- that is the specific transition the incident turned on. CONTAMINATED advances.

And disposition() REFUSES to return a terminal answer while any authorized rung is UNTRIED. It
returns ACQUISITION_INCOMPLETE instead, naming the rungs still owed. That is the enforcement:
the system cannot say UNKNOWN while it still has somewhere to look.

assert_no_premature_termination() is the healthcheck gate. If any record on disk claims UNKNOWN,
BLOCKED or NO_FORECAST while its ledger holds an authorized UNTRIED rung, CI fails. That check --
not a better heuristic -- is what would have caught 2026-08-30 the moment it happened.
"""
from __future__ import annotations

MODULE_ID = "acquisition_orchestrator"

import datetime as dt
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

UTC = dt.timezone.utc

# ------------------------------------------------------------------ the ladder

#: Seven rungs, strongest first. Mirrors route_ladder_v1.RUNGS; imported below when available so
#: the two cannot drift, with this tuple as the declared fallback rather than a silent second copy.
RUNGS = (
    "OFFICIAL_API",
    "OFFICIAL_LEAGUE_PAGE",
    "OFFICIAL_TEAM_STATUS",
    "SPORTSBOOK",
    "NAMED_AGGREGATOR",
    "OPEN_WEB_SEARCH",
    "OWNER_RELAY",
)

try:
    import route_ladder_v1 as _rl
    _declared = tuple(r[0] if isinstance(r, (tuple, list)) else r for r in _rl.RUNGS)
    if len(_declared) != len(RUNGS):
        # Drift is disclosed, never silently reconciled. R1: do not guess which list is right.
        LADDER_DRIFT = (f"route_ladder_v1 declares {len(_declared)} rungs, this module {len(RUNGS)}"
                        f" — {_declared} vs {RUNGS}")
    else:
        LADDER_DRIFT = None
except Exception as _e:                                   # pragma: no cover - import-shape only
    LADDER_DRIFT = f"route_ladder_v1 not importable ({type(_e).__name__}); using the local ladder"

#: Outcomes. EVERY one of these except OBTAINED advances the ladder.
OBTAINED = "OBTAINED"
BLOCKED = "BLOCKED"                    # egress denial, 403, proxy refusal
NOT_FOUND = "NOT_FOUND"                # host does not resolve, 404, empty response
STALE_REJECTED = "STALE_REJECTED"      # content returned but too old to use
CONTAMINATED = "CONTAMINATED"          # content returned but about the wrong game/date/entity
TITLES_ONLY = "TITLES_ONLY"            # links with no usable content
INELIGIBLE = "INELIGIBLE"              # this rung cannot answer this field at all
ERROR = "ERROR"                        # anything else

ADVANCING_OUTCOMES = frozenset({BLOCKED, NOT_FOUND, STALE_REJECTED, CONTAMINATED,
                                TITLES_ONLY, INELIGIBLE, ERROR})
OUTCOMES = frozenset(ADVANCING_OUTCOMES | {OBTAINED})

#: Terminal claims a caller might want to make, and which this module gates.
TERMINAL_CLAIMS = frozenset({"UNKNOWN", "BLOCKED", "NO_FORECAST", "AVAILABILITY_UNKNOWN",
                             "NO_DATA", "ABSENT"})

INCOMPLETE = "ACQUISITION_INCOMPLETE"
EXHAUSTED = "ACQUISITION_EXHAUSTED"
ACQUIRED = "ACQUIRED"

#: Which rungs can answer which field. An INELIGIBLE rung is not an untried rung -- but it must be
#: declared here rather than skipped by a caller's judgement, or "ineligible" becomes a way to
#: shrink the ladder to whatever was convenient.
FIELD_ELIGIBILITY = {
    "availability": ("OFFICIAL_API", "OFFICIAL_LEAGUE_PAGE", "OFFICIAL_TEAM_STATUS",
                     "NAMED_AGGREGATOR", "OPEN_WEB_SEARCH", "OWNER_RELAY"),
    "result": ("OFFICIAL_API", "OFFICIAL_LEAGUE_PAGE", "NAMED_AGGREGATOR",
               "OPEN_WEB_SEARCH", "OWNER_RELAY"),
    "schedule": ("OFFICIAL_API", "OFFICIAL_LEAGUE_PAGE", "NAMED_AGGREGATOR",
                 "OPEN_WEB_SEARCH", "OWNER_RELAY"),
    "starter": ("OFFICIAL_API", "OFFICIAL_LEAGUE_PAGE", "OFFICIAL_TEAM_STATUS",
                "NAMED_AGGREGATOR", "OPEN_WEB_SEARCH", "OWNER_RELAY"),
    "price": ("SPORTSBOOK", "NAMED_AGGREGATOR", "OWNER_RELAY"),
}


class PrematureTermination(RuntimeError):
    """Raised when a terminal claim is made while an authorized rung is still UNTRIED."""


class Action:
    """One instruction for the agent loop. Not a fetch — a thing for the agent to go do."""

    __slots__ = ("rung", "field", "subject", "date_et", "hint", "index", "of")

    def __init__(self, rung, field, subject, date_et, hint, index, of):
        self.rung, self.field, self.subject = rung, field, subject
        self.date_et, self.hint = date_et, hint
        self.index, self.of = index, of

    def to_dict(self):
        return {"rung": self.rung, "field": self.field, "subject": self.subject,
                "date_et": self.date_et, "hint": self.hint,
                "position": f"{self.index}/{self.of}"}

    def __repr__(self):
        return f"<Action {self.index}/{self.of} {self.rung} {self.field} {self.subject}>"


def _hint(rung, field, subject, date_et):
    """What to actually do on this rung. Concrete beats abstract when the agent is the executor."""
    s = subject
    if rung == "OFFICIAL_API":
        return f"the league's own API for {field} of {s} on {date_et}"
    if rung == "OFFICIAL_LEAGUE_PAGE":
        return f"the league's own site page for {s} on {date_et}"
    if rung == "OFFICIAL_TEAM_STATUS":
        return f"the club's own site / status page for {s}"
    if rung == "SPORTSBOOK":
        return f"a sportsbook board carrying {s} on {date_et}"
    if rung == "NAMED_AGGREGATOR":
        return f"a NAMED aggregator page for {s} on {date_et} — fetch the page, not a search for it"
    if rung == "OPEN_WEB_SEARCH":
        return (f"open search for {field} of {s} on {date_et}. Make the query SPECIFIC: include "
                f"the date, both sides, and the field. One generic query is not an acquisition "
                f"strategy — that is exactly what returned a 32-day-old article on 2026-08-30.")
    if rung == "OWNER_RELAY":
        return f"ask the owner to relay {field} for {s} on {date_et}"
    return f"{rung} for {field} of {s}"


# ------------------------------------------------------------------ the plan

def open_plan(subject, field, date_et, *, authorized=None, now_utc=None):
    if field not in FIELD_ELIGIBILITY:
        raise KeyError(f"unknown field {field!r}; known: {sorted(FIELD_ELIGIBILITY)}")
    eligible = tuple(r for r in RUNGS if r in FIELD_ELIGIBILITY[field])
    auth = tuple(r for r in eligible if authorized is None or r in authorized)
    return {
        "schema": "ops.acquisition_plan.v1",
        "subject": subject, "field": field, "date_et": date_et,
        "opened_utc": now_utc or dt.datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "eligible_rungs": list(eligible),
        "authorized_rungs": list(auth),
        "ineligible_rungs": [r for r in RUNGS if r not in eligible],
        "attempts": [],
        "artifacts": [],
        "ladder_drift": LADDER_DRIFT,
    }


def tried(plan):
    return {a["rung"] for a in plan["attempts"]}


def untried(plan):
    """Authorized rungs with no attempt recorded. This is the list that blocks termination."""
    return [r for r in plan["authorized_rungs"] if r not in tried(plan)]


def _succeeded(attempt):
    """An attempt stops the ladder only if it did NOT advance it.

    2026-08-30, found while writing this module's own mutation suite: ADVANCING_OUTCOMES was
    computed, stored on every attempt as `advances`, and then consulted by nothing — next_action
    and disposition both tested `outcome == OBTAINED` directly. That is the compute-then-discard
    shape this repo has now found six times, in code written to fix an instance of it. The set is
    load-bearing here, so a mutant that empties it changes behaviour and can be caught.
    """
    return attempt["outcome"] not in ADVANCING_OUTCOMES


def next_action(plan):
    """The next UNTRIED authorized rung, as an instruction. None only when the ladder is spent."""
    if any(_succeeded(a) for a in plan["attempts"]):
        return None
    rest = untried(plan)
    if not rest:
        return None
    r = rest[0]
    total = len(plan["authorized_rungs"])
    idx = total - len(rest) + 1
    return Action(r, plan["field"], plan["subject"], plan["date_et"],
                  _hint(r, plan["field"], plan["subject"], plan["date_et"]), idx, total)


def record_attempt(plan, rung, outcome, *, detail=None, artifact=None, now_utc=None):
    """Record one rung's result. Every outcome but OBTAINED advances the ladder."""
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}; known: {sorted(OUTCOMES)}")
    if rung not in RUNGS:
        raise ValueError(f"unknown rung {rung!r}")
    stamp = now_utc or dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")
    rec = {"rung": rung, "outcome": outcome, "at_utc": stamp, "detail": detail,
           "advances": outcome in ADVANCING_OUTCOMES}
    if artifact is not None:
        blob = json.dumps(artifact, sort_keys=True, default=str)
        rec["artifact_sha256"] = hashlib.sha256(blob.encode()).hexdigest()
        plan["artifacts"].append({"rung": rung, "at_utc": stamp, "artifact": artifact,
                                  "sha256": rec["artifact_sha256"]})
    plan["attempts"].append(rec)
    return plan


def disposition(plan):
    """ACQUIRED, EXHAUSTED, or INCOMPLETE. Never a terminal answer while a rung is untried."""
    got = [a for a in plan["attempts"] if _succeeded(a)]
    if got:
        return {"state": ACQUIRED, "on_rung": got[0]["rung"],
                "rungs_tried": len(plan["attempts"]),
                "untried_authorized": untried(plan),
                "note": "stronger rungs above this one failed; the artifact carries the grade of "
                        "the rung that produced it, not of the rungs that did not"}
    rest = untried(plan)
    if rest:
        return {"state": INCOMPLETE, "untried_authorized": rest,
                "rungs_tried": len(plan["attempts"]),
                "refusal": "a terminal claim is not available while an authorized route is "
                           "untried. This is ACQUISITION_INCOMPLETE, not UNKNOWN."}
    return {"state": EXHAUSTED, "untried_authorized": [],
            "rungs_tried": len(plan["attempts"]),
            "outcomes": [a["outcome"] for a in plan["attempts"]],
            "note": "every authorized rung was attempted and none produced usable content. NOW a "
                    "terminal claim is honest, and it is honest because the ledger shows the work."}


def assert_terminal_allowed(plan, claim):
    """Gate every terminal claim. This is the call that would have caught 2026-08-30."""
    if claim not in TERMINAL_CLAIMS:
        return
    d = disposition(plan)
    if d["state"] == INCOMPLETE:
        raise PrematureTermination(
            f"{claim!r} refused for {plan['field']} of {plan['subject']} on {plan['date_et']}: "
            f"{len(d['untried_authorized'])} authorized rung(s) still UNTRIED "
            f"({', '.join(d['untried_authorized'])}). Rejecting a stale artifact ADVANCES the "
            "ladder; it does not end it.")


# ------------------------------------------------------------------ CI gate

def assert_no_premature_termination(records):
    """Healthcheck gate. records: [{claim, plan}] — any UNKNOWN over an unfinished ladder fails."""
    bad = []
    for r in records:
        claim, plan = r.get("claim"), r.get("plan")
        if claim not in TERMINAL_CLAIMS or not plan:
            continue
        d = disposition(plan)
        if d["state"] == INCOMPLETE:
            bad.append({"subject": plan["subject"], "field": plan["field"],
                        "date_et": plan["date_et"], "claim": claim,
                        "untried": d["untried_authorized"]})
    return bad


def ledger(plan):
    return {"schema": "ops.acquisition_ledger.v1",
            "subject": plan["subject"], "field": plan["field"], "date_et": plan["date_et"],
            "authorized_rungs": plan["authorized_rungs"],
            "attempts": plan["attempts"],
            "disposition": disposition(plan),
            "artifact_hashes": [a["sha256"] for a in plan["artifacts"]]}


# ------------------------------------------------------------------ selftest

def _incident_plan():
    """The 2026-08-30 Atlanta case, replayed."""
    p = open_plan("MIN@ATL Atlanta Dream", "availability", "2026-08-30")
    record_attempt(p, "OFFICIAL_API", BLOCKED, detail="site.api.espn.com EGRESS_BLOCKED",
                   now_utc="2026-08-30T22:20:00Z")
    record_attempt(p, "OFFICIAL_LEAGUE_PAGE", BLOCKED, detail="www.wnba.com EGRESS_BLOCKED",
                   now_utc="2026-08-30T22:21:00Z")
    record_attempt(p, "OFFICIAL_TEAM_STATUS", NOT_FOUND, detail="atlantadream.wnba.com ENOTFOUND",
                   now_utc="2026-08-30T22:22:00Z")
    return p


def selftest():
    f = []

    # 1. THE INCIDENT. A stale rejection must not end the ladder.
    p = _incident_plan()
    record_attempt(p, "NAMED_AGGREGATOR", STALE_REJECTED,
                   detail="late-July report, 32 days stale", now_utc="2026-08-30T22:25:00Z")
    if disposition(p)["state"] != INCOMPLETE:
        f.append("a stale rejection ended the ladder — this is the 2026-08-30 defect")
    try:
        assert_terminal_allowed(p, "AVAILABILITY_UNKNOWN")
        f.append("AVAILABILITY_UNKNOWN was permitted with OPEN_WEB_SEARCH and OWNER_RELAY untried")
    except PrematureTermination:
        pass
    a = next_action(p)
    if a is None or a.rung != "OPEN_WEB_SEARCH":
        f.append(f"after a stale rejection the next action should be OPEN_WEB_SEARCH, got {a}")

    # 2. and continuing finds it
    record_attempt(p, "OPEN_WEB_SEARCH", OBTAINED,
                   detail="specific query returned the current report",
                   artifact={"out": ["Brionna Jones"], "date": "2026-08-30"},
                   now_utc="2026-08-30T22:30:00Z")
    d = disposition(p)
    if d["state"] != ACQUIRED or d["on_rung"] != "OPEN_WEB_SEARCH":
        f.append(f"acquisition not recorded: {d}")
    if next_action(p) is not None:
        f.append("the ladder kept going after OBTAINED")
    if not p["artifacts"] or "sha256" not in p["artifacts"][0]:
        f.append("the acquired artifact was not hashed")

    # 3. genuine exhaustion IS allowed to terminate
    q = open_plan("X", "availability", "2026-08-30")
    for r in q["authorized_rungs"]:
        record_attempt(q, r, BLOCKED, now_utc="2026-08-30T22:00:00Z")
    if disposition(q)["state"] != EXHAUSTED:
        f.append("a fully-attempted ladder did not reach EXHAUSTED")
    try:
        assert_terminal_allowed(q, "AVAILABILITY_UNKNOWN")
    except PrematureTermination:
        f.append("UNKNOWN refused after every rung was attempted — over-refusal")

    # 4. every advancing outcome really advances
    for oc in sorted(ADVANCING_OUTCOMES):
        z = open_plan("Y", "availability", "2026-08-30")
        record_attempt(z, "OFFICIAL_API", oc, now_utc="2026-08-30T22:00:00Z")
        if next_action(z) is None:
            f.append(f"outcome {oc} did not advance the ladder")

    # 5. the CI gate catches it in a batch
    bad = assert_no_premature_termination([{"claim": "AVAILABILITY_UNKNOWN",
                                            "plan": _incident_plan()}])
    if len(bad) != 1:
        f.append(f"the CI gate missed a premature termination: {bad}")

    # 6. ineligible rungs are declared, not silently dropped
    pr = open_plan("Z", "price", "2026-08-30")
    if "OFFICIAL_API" in pr["authorized_rungs"]:
        f.append("price should not authorize OFFICIAL_API")
    if "OFFICIAL_API" not in pr["ineligible_rungs"]:
        f.append("an ineligible rung must be recorded as ineligible, not omitted")

    for x in f:
        print("  FAIL:", x)
    print(f"acquisition_orchestrator selftest: {'OK' if not f else 'FAIL'}")
    return not f


def _mutant(label, apply_mutant, verify):
    """KILLED = with the mutant applied, `verify` FAILS, i.e. the guard notices the breakage.

    A crash is an ERROR, not a kill. Counting an exception as a kill is exactly the defect the
    contract module's docstring records for its own suite, and it inflates every tally that does
    it.
    """
    undo = None
    try:
        undo = apply_mutant()
        try:
            held = verify()
        except PrematureTermination:
            held = True                       # the guard fired: it noticed
        return (label, "SURVIVED" if held else "KILLED")
    except Exception as e:
        return (label, f"ERROR {type(e).__name__}: {e}")
    finally:
        if callable(undo):
            undo()


def mutation_suite(verbose=True):
    """Each mutant BREAKS a guard; the suite is only meaningful if behaviour then changes."""
    out = []

    def m_drop_stale_from_advancing():
        saved = globals()["ADVANCING_OUTCOMES"]
        globals()["ADVANCING_OUTCOMES"] = frozenset(saved - {STALE_REJECTED})
        return lambda: globals().__setitem__("ADVANCING_OUTCOMES", saved)

    def v_stale_still_advances():
        p = _incident_plan()
        record_attempt(p, "NAMED_AGGREGATOR", STALE_REJECTED, now_utc="2026-08-30T22:25:00Z")
        # the guard: a stale rejection must leave the ladder INCOMPLETE with rungs to go
        return disposition(p)["state"] == INCOMPLETE and next_action(p) is not None

    def m_untried_returns_nothing():
        saved = globals()["untried"]
        globals()["untried"] = lambda plan: []
        return lambda: globals().__setitem__("untried", saved)

    def v_terminal_is_gated():
        p = _incident_plan()
        assert_terminal_allowed(p, "AVAILABILITY_UNKNOWN")
        return False                          # no refusal raised: the gate did not fire

    def m_ci_gate_ignores_claim_set():
        saved = globals()["TERMINAL_CLAIMS"]
        globals()["TERMINAL_CLAIMS"] = frozenset()
        return lambda: globals().__setitem__("TERMINAL_CLAIMS", saved)

    def v_ci_gate_sees_it():
        return len(assert_no_premature_termination(
            [{"claim": "NO_FORECAST", "plan": _incident_plan()}])) == 1

    def m_eligibility_opens_everything():
        saved = globals()["FIELD_ELIGIBILITY"]
        globals()["FIELD_ELIGIBILITY"] = {k: RUNGS for k in saved}
        return lambda: globals().__setitem__("FIELD_ELIGIBILITY", saved)

    def v_price_excludes_official_api():
        return "OFFICIAL_API" not in open_plan("Z", "price", "2026-08-30")["authorized_rungs"]

    for label, m, v in (
            ("STALE_REJECTED must advance the ladder", m_drop_stale_from_advancing,
             v_stale_still_advances),
            ("terminal claims must be gated on untried rungs", m_untried_returns_nothing,
             v_terminal_is_gated),
            ("the CI gate must recognise every terminal claim", m_ci_gate_ignores_claim_set,
             v_ci_gate_sees_it),
            ("field eligibility must actually restrict rungs", m_eligibility_opens_everything,
             v_price_excludes_official_api)):
        out.append(_mutant(label, m, v))

    killed = sum(1 for _, s in out if s == "KILLED")
    errored = sum(1 for _, s in out if s.startswith("ERROR"))
    survived = len(out) - killed - errored
    if verbose:
        for label, s in out:
            print(f"  {s:22s} {label}")
        print(f"acquisition_orchestrator mutation suite: {killed} killed, "
              f"{errored} errored, {survived} survived")
    return killed == len(out)


def gate():
    ok = selftest()
    ok = mutation_suite() and ok
    print(f"acquisition orchestrator gate: {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    if "--mutants" in sys.argv:
        sys.exit(0 if mutation_suite() else 1)
    if "--gate" in sys.argv:
        sys.exit(0 if gate() else 1)
    sys.exit(0 if selftest() else 1)
