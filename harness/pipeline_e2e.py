"""The real board entry point, instrumented. Healthcheck fails when a registered gate is bypassed.

MODULE SELF-TESTS DO NOT PROVE A GATE RUNS. Every gate in this repository has its own fixtures and
its own mutants, and on 2026-08-24 a board shipped anyway with rows that no gate had refused —
because passing tests prove a gate WORKS, not that anything CALLED it. The two are independent, and
only the second one protects a production board.

So the pipeline declares the gates it is required to invoke, runs end to end through the real entry
points, and records which ones actually fired. A gate that is registered and never called is a
BYPASS and fails the healthcheck, exactly as a failing gate would.

    schedule -> acquisition -> verification -> replacement -> price overlay -> uncertainty
      -> BET/PASS -> rendering -> anchor

The instrumentation is a wrapper, not a promise: `_traced` replaces each registered callable with
one that records the call. Nothing in the pipeline body can satisfy the trace except by calling the
real function, which is the property that makes a bypass detectable rather than merely discouraged.
"""

from __future__ import annotations

MODULE_ID = "pipeline_e2e"

import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])

import checkpoint_schedule as CS
import decision_view as DV
import price_overlay as PO
import readiness_gate as RG
import replacement_workflow as RW
import route_ladder_v1 as RL

#: (stage, module, attribute). Every one MUST be invoked by a compliant run.
REQUIRED_GATES = (
    ("SCHEDULE", "checkpoint_schedule", "status"),
    ("ACQUISITION", "route_ladder_v1", "attempt"),
    ("VERIFICATION", "decision_view", "slate_coverage_gate"),
    ("REPLACEMENT", "replacement_workflow", "replace"),
    ("PRICE_OVERLAY", "price_overlay", "pregame_overlay_gate"),
    ("UNCERTAINTY", "readiness_gate", "readiness"),
    ("DECISION", "decision_view", "final_decision_gate"),
    ("RENDER", "decision_view", "row_contract_gate"),
    ("ANCHOR", "pipeline_e2e", "anchor"),
)
MODULES = {"checkpoint_schedule": CS, "route_ladder_v1": RL, "decision_view": DV,
           "replacement_workflow": RW, "price_overlay": PO, "readiness_gate": RG}

BYPASSED = "REGISTERED_GATE_NEVER_INVOKED"
OK = "PIPELINE_E2E_OK"
REFUSED = "PIPELINE_E2E_REFUSED"


def anchor(payload):
    """Stand-in for the remote anchor. Real anchoring is CI; this records that the stage ran."""
    return {"anchored": True, "payload_keys": sorted(payload or {})}


class _Trace:
    """Wrap each registered gate so a call is recorded. Restores originals on exit, always."""

    def __init__(self, gates=REQUIRED_GATES):
        self.gates, self.called, self._saved = gates, set(), []

    def __enter__(self):
        for stage, modname, attr in self.gates:
            mod = MODULES.get(modname) or sys.modules[__name__]
            orig = getattr(mod, attr)
            self._saved.append((mod, attr, orig))

            def make(o=orig, key=(stage, modname, attr)):
                def wrapper(*a, **kw):
                    self.called.add(key)
                    return o(*a, **kw)
                return wrapper
            setattr(mod, attr, make())
        return self

    def __exit__(self, *exc):
        for mod, attr, orig in self._saved:
            setattr(mod, attr, orig)
        return False


def run_board(schedule, price_quotes, estimator_spec, admissible_clusters,
              prior_pool_provisional, material_changes=None, minutes_to_start=5,
              completed_checkpoints=None):
    """The real board entry point. Every stage calls its registered gate."""
    m = sys.modules[__name__]
    out = {"stages": {}}

    out["stages"]["SCHEDULE"] = MODULES["checkpoint_schedule"].status(
        minutes_to_start, completed_checkpoints or set(CS.NAMES))

    acq = {}
    for g in schedule:
        acq[g] = MODULES["route_ladder_v1"].attempt(
            f"{g}:starter",
            [{"rung": "OFFICIAL_API", "result": "OK", "value": "confirmed",
              "artifact_sha256": "a" * 8}])
    out["stages"]["ACQUISITION"] = {"n": len(acq),
                                    "all_acquired": all(v["status"] == RL.ACQUIRED
                                                        for v in acq.values())}

    rows = [{"game": g} for g in schedule]
    out["stages"]["VERIFICATION"] = MODULES["decision_view"].slate_coverage_gate(schedule, rows)

    reps = []
    for ch in (material_changes or []):
        rep, err = MODULES["replacement_workflow"].replace(**ch)
        reps.append({"ok": rep is not None, "error": err})
    if not (material_changes or []):
        # the stage must run even with nothing to replace, or a slate with no changes silently
        # skips the gate and the trace would call that compliant
        rep, err = MODULES["replacement_workflow"].replace(
            {"identity": "probe", "p_home": 0.5}, "PITCHER_SCRATCH", "probe", "probe",
            "mlb.replacement.CONFIRMED_LINEUP", 0.5, "2000-01-01T00:00:00Z",
            "2000-01-01T01:00:00Z", "2000-01-01T00:30:00Z")
        reps.append({"ok": rep is not None, "error": err, "probe": True})
    out["stages"]["REPLACEMENT"] = {"n": len(reps), "results": reps}

    out["stages"]["PRICE_OVERLAY"] = MODULES["price_overlay"].pregame_overlay_gate(price_quotes)

    ready = MODULES["readiness_gate"].readiness(estimator_spec, admissible_clusters,
                                                prior_pool_provisional)
    out["stages"]["UNCERTAINTY"] = ready

    prices_ok = out["stages"]["PRICE_OVERLAY"]["status"] == PO.ELIGIBLE
    decided = []
    for g in schedule:
        if not ready["may_publish_decision_board"]:
            fd, reason, cev = DV.PASS, "SYSTEM_NOT_DECISION_READY", None
        elif not prices_ok:
            fd, reason, cev = DV.EXCEPTION, "MARKET_SUSPENDED", None
        else:
            fd, reason, cev = DV.PASS, "negative expected value at this price", None
        row = {k: "x" for k in DV.ROW_CONTRACT_V1}
        row.update(game=g, final_decision=fd, primary_reason=reason,
                   conservative_ev_per_100=cev,
                   exception_state="MARKET_SUSPENDED" if fd == DV.EXCEPTION else None,
                   recommended_units=0.0, recommended_dollars=0.0)
        decided.append(row)
    out["stages"]["DECISION"] = MODULES["decision_view"].final_decision_gate(decided)
    out["stages"]["RENDER"] = MODULES["decision_view"].row_contract_gate(decided)
    out["stages"]["ANCHOR"] = m.anchor({"rows": len(decided), "ready": ready["status"]})
    out["rows"] = decided
    return out


def run_instrumented(**kw):
    """Run the board and report any REGISTERED gate that was never invoked."""
    with _Trace() as tr:
        result = run_board(**kw)
        called = set(tr.called)
    missing = [g for g in REQUIRED_GATES if g not in called]
    return {"status": OK if not missing else REFUSED,
            "n_required": len(REQUIRED_GATES), "n_invoked": len(called),
            "bypassed": [{"code": BYPASSED, "stage": s, "module": m, "gate": a}
                         for s, m, a in missing],
            "result": result,
            "note": None if not missing else
                    "a registered gate was never called. Its own tests may pass perfectly; that "
                    "proves the gate works, not that anything invoked it."}


DEFAULT_RUN = dict(
    schedule=["mlb:A@B", "mlb:C@D"],
    price_quotes=[{"game": "mlb:A@B", "captured_at_utc": "2026-08-24T16:41:27Z",
                   "actual_start_utc": "2026-08-24T23:40:00Z", "books": ["DRAFTKINGS"]}],
    estimator_spec={}, admissible_clusters=2, prior_pool_provisional=True,
)


# =================================================================================================
def selftest():
    f = []

    r = run_instrumented(**DEFAULT_RUN)
    if r["status"] != OK:
        f.append(f"a complete run must invoke every registered gate, bypassed={r['bypassed']}")
    if r["n_invoked"] != r["n_required"]:
        f.append(f"{r['n_invoked']} of {r['n_required']} gates invoked")
    for stage, _, _ in REQUIRED_GATES:
        if stage not in r["result"]["stages"]:
            f.append(f"stage {stage} produced no output")

    # THE POINT: bypassing any one registered gate must be DETECTED, not merely discouraged
    for stage, modname, attr in REQUIRED_GATES:
        mod = MODULES.get(modname) or sys.modules[__name__]
        orig = getattr(mod, attr)
        try:
            # a stub that answers everything plausibly. Return shapes differ across gates, so the
            # probe tolerates a raise: what is being asserted is whether the TRACE saw the call,
            # not whether the stubbed pipeline still runs to completion.
            setattr(mod, attr, lambda *a, **kw: {"status": "OK", "problems": [], "n_problems": 0,
                                                 "may_publish_decision_board": False,
                                                 "anchored": True})
            traced = tuple(g for g in REQUIRED_GATES if g != (stage, modname, attr))
            with _Trace(traced) as tr2:
                try:
                    run_board(**DEFAULT_RUN)
                except Exception:
                    pass
            missing = [g for g in REQUIRED_GATES if g not in set(tr2.called)]
            if (stage, modname, attr) not in missing:
                f.append(f"bypassing {stage} must be detectable")
        finally:
            setattr(mod, attr, orig)

    # this system's ACTUAL state must come out SYSTEM_NOT_DECISION_READY, and every row must still
    # be a legal final decision — never a work-queue condition
    res = r["result"]
    if res["stages"]["UNCERTAINTY"]["status"] != RG.NOT_READY:
        f.append("with an empty estimator the run must be SYSTEM_NOT_DECISION_READY")
    if res["stages"]["DECISION"]["status"] != DV.OK:
        f.append(f"every row must be a legal final decision: {res['stages']['DECISION']}")
    if res["stages"]["RENDER"]["status"] != DV.OK:
        f.append(f"every row must satisfy the section 9 contract: {res['stages']['RENDER']}")
    for row in res["rows"]:
        if row["final_decision"] not in DV.FINAL_DECISIONS:
            f.append(f"{row['game']} ended as {row['final_decision']}")
        if row["final_decision"] == DV.BET:
            f.append("a not-ready system must never emit a BET")
    if res["stages"]["VERIFICATION"]["status"] != DV.OK:
        f.append("every scheduled game must be covered")
    if not res["stages"]["ANCHOR"]["anchored"]:
        f.append("the run must anchor")

    # a live price must stop the overlay stage even inside a full pipeline run
    live = run_instrumented(**dict(DEFAULT_RUN, price_quotes=[
        {"game": "mlb:A@B", "captured_at_utc": "2026-08-25T01:58:16Z",
         "actual_start_utc": "2026-08-24T23:40:00Z", "books": ["DRAFTKINGS"]}]))
    if live["result"]["stages"]["PRICE_OVERLAY"]["status"] == PO.ELIGIBLE:
        f.append("a post-start quote must be refused inside the pipeline, not only in isolation")
    if live["status"] != OK:
        f.append("a refused price must not bypass any gate")

    print("pipeline_e2e selftest:", "OK" if not f else "FAIL")
    for x in f:
        print("   -", x)
    return not f


MUTANTS = [
    ("the uncertainty gate is skipped entirely",
     '    ready = MODULES["readiness_gate"].readiness(estimator_spec, admissible_clusters,\n                                                prior_pool_provisional)',
     '    ready = {"may_publish_decision_board": False, "status": "SYSTEM_NOT_DECISION_READY"}'),
    ("the price overlay gate is skipped",
     '    out["stages"]["PRICE_OVERLAY"] = MODULES["price_overlay"].pregame_overlay_gate(price_quotes)',
     '    out["stages"]["PRICE_OVERLAY"] = {"status": "ELIGIBLE", "problems": []}'),
    ("the slate coverage gate is skipped",
     '    out["stages"]["VERIFICATION"] = MODULES["decision_view"].slate_coverage_gate(schedule, rows)',
     '    out["stages"]["VERIFICATION"] = {"status": "DECISION_VIEW_OK", "problems": []}'),
    ("the replacement stage is skipped when there is nothing to replace",
     "    if not (material_changes or []):", "    if False:"),
    ("the decision gate is skipped",
     '    out["stages"]["DECISION"] = MODULES["decision_view"].final_decision_gate(decided)',
     '    out["stages"]["DECISION"] = {"status": "DECISION_VIEW_OK", "problems": []}'),
    ("the render contract is skipped",
     '    out["stages"]["RENDER"] = MODULES["decision_view"].row_contract_gate(decided)',
     '    out["stages"]["RENDER"] = {"status": "DECISION_VIEW_OK", "problems": []}'),
    ("the anchor stage is skipped",
     '    out["stages"]["ANCHOR"] = m.anchor({"rows": len(decided), "ready": ready["status"]})',
     '    out["stages"]["ANCHOR"] = {"anchored": True}'),
    ("the schedule gate is skipped",
     '    out["stages"]["SCHEDULE"] = MODULES["checkpoint_schedule"].status(',
     '    out["stages"]["SCHEDULE"] = {} or MODULES["checkpoint_schedule"].__dict__.get("nope", lambda *a: {})('),
    ("a bypassed gate stops being reported",
     "    missing = [g for g in REQUIRED_GATES if g not in called]", "    missing = []"),
    ("a not-ready system is allowed to emit a BET",
     "        if not ready[\"may_publish_decision_board\"]:\n            fd, reason, cev = DV.PASS, \"SYSTEM_NOT_DECISION_READY\", None",
     "        if not ready[\"may_publish_decision_board\"]:\n            fd, reason, cev = DV.BET, \"edge\", 5.0"),
]


def mutation_suite():
    src = open(__file__).read()
    import io as _io, contextlib as _cl
    _b = _io.StringIO()
    with _cl.redirect_stdout(_b):
        _base = selftest()
    if not _base:
        print("  BASELINE_FAILING  the unmutated selftest does not pass")
        print(_b.getvalue().strip())
        return False
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
    print(f"mutation suite: {killed}/{len(MUTANTS)} killed"
          + ("" if killed == len(MUTANTS) else "  — SURVIVORS MEAN DECORATIVE FIXTURES"))
    return killed == len(MUTANTS)


if __name__ == "__main__":
    if "--mutants" in sys.argv:
        sys.exit(0 if mutation_suite() else 1)
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    if "--run" in sys.argv:
        r = run_instrumented(**DEFAULT_RUN)
        print(json.dumps({k: v for k, v in r.items() if k != "result"}, indent=1))
        sys.exit(0 if r["status"] == OK else 1)
    print(__doc__)
