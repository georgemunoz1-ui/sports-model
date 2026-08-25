"""SYSTEM_NOT_DECISION_READY — section 7's product-level gate.

THE CHANGE THIS MAKES. Until now, a missing uncertainty estimator produced a page full of blocked
rows that still looked like a decision board: a header, twelve games, EV numbers, a watchlist. The
standard says that is the wrong shape of output entirely. A missing estimator is a BOARD-READINESS
failure, so the product does not publish a decision board at all — it publishes
SYSTEM_NOT_DECISION_READY and says which part of the infrastructure is missing.

The distinction matters because the two failures have different owners and different remedies. A
blocked game is a question for the analyst. An unready product is a question for whoever maintains
the pipeline, and it is answered before the slate rather than during it.

ELEVEN REQUIRED PARTS. Section 7 lists what a frozen estimator must specify. Every one is required,
because each absent one is a different way for the estimator to be unfalsifiable:
absent estimand -> nothing to check; absent population -> in-sample leakage invisible; absent
cluster definition -> dependence uncounted; absent minimum cluster count -> k=2 passes; absent
pooling rules -> subgroups silently merged; absent coverage validation -> intervals never tested
against outcomes; absent identity or hashes -> irreproducible; absent conversion method -> the
number never reaches a decision; absent refusal behaviour -> extrapolation without notice.
"""

import sys

REQUIRED_ESTIMATOR_PARTS = (
    "exact_estimand",
    "training_and_calibration_population",
    "cluster_definition",
    "minimum_admissible_cluster_count",
    "subgroup_pooling_rules",
    "coverage_validation",
    "versioned_model_identity",
    "input_and_evidence_hashes",
    "conservative_ev_conversion_method",
    "refusal_behavior_outside_validated_support",
    "frozen_at_utc",
)

#: quantities that may NEVER be the estimator, however convenient their units
FORBIDDEN_SUBSTITUTES = (
    "CROSS_GAME_P_SD", "BERNOULLI_OUTCOME_SD", "MONTE_CARLO_SD", "MC_SD_PRIMARY_30K",
    "MC_SD_DIAGNOSTIC_100K", "MC_SD_DIFFERENCE", "PRIOR_PARAMETER_SD",
)

READY = "SYSTEM_DECISION_READY"
NOT_READY = "SYSTEM_NOT_DECISION_READY"
FORBIDDEN = "FORBIDDEN_SUBSTITUTE_USED_AS_UNCERTAINTY_ESTIMATOR"
MAY_NOT_PUBLISH = "MUST_NOT_PUBLISH_A_PAGE_THAT_APPEARS_DECISION_READY"


def estimator_complete(spec):
    """(ok, missing, problems) for one uncertainty estimator specification."""
    spec = spec or {}
    missing = [p for p in REQUIRED_ESTIMATOR_PARTS
               if spec.get(p) in (None, "", [], {})]
    problems = []
    est = str(spec.get("exact_estimand") or "")
    if est in FORBIDDEN_SUBSTITUTES:
        problems.append({"code": FORBIDDEN, "estimand": est,
                         "note": "dispersion, outcome variance, simulation error and prior-parameter "
                                 "SD are not model forecast uncertainty"})
    k = spec.get("minimum_admissible_cluster_count")
    if isinstance(k, int) and k < 6:
        problems.append({"code": "MINIMUM_CLUSTER_COUNT_BELOW_FLOOR", "value": k, "floor": 6,
                         "note": "ceil(log2(2/0.05)) = 6; below this the exact sign-flip test "
                                 "cannot reach p <= 0.05 at any effect size"})
    return (not missing and not problems), missing, problems


def readiness(estimator_spec, admissible_clusters=None, prior_pool_provisional=None):
    """The product-level gate. Anything short of ready refuses to publish a decision board."""
    ok, missing, problems = estimator_complete(estimator_spec)
    reasons = []
    if missing:
        reasons.append({"code": "ESTIMATOR_SPEC_INCOMPLETE", "missing_parts": missing})
    reasons.extend(problems)
    need = (estimator_spec or {}).get("minimum_admissible_cluster_count")
    if admissible_clusters is not None and isinstance(need, int) and admissible_clusters < need:
        reasons.append({"code": "INSUFFICIENT_ADMISSIBLE_CLUSTERS",
                        "admissible": admissible_clusters, "required": need})
    if prior_pool_provisional:
        reasons.append({"code": "PRIOR_INPUT_POOL_PROVISIONAL",
                        "note": "training evidence that cannot be traced to a retained artifact "
                                "cannot certify an estimator built on it"})
    ready = not reasons
    return {
        "status": READY if ready else NOT_READY,
        "may_publish_decision_board": ready,
        "publication_rule": None if ready else MAY_NOT_PUBLISH,
        "reasons": reasons,
        "required_parts": list(REQUIRED_ESTIMATOR_PARTS),
        "note": None if ready else
                "a missing estimator is a BOARD-READINESS failure with a pipeline owner, not a "
                "per-game explanation with an analyst owner. The product publishes "
                f"{NOT_READY} and names the missing infrastructure; it does not publish a page "
                "that looks like a decision board and is full of blocked rows.",
    }


# =================================================================================================
def selftest():
    f = []
    COMPLETE = {p: "specified" for p in REQUIRED_ESTIMATOR_PARTS}
    COMPLETE["exact_estimand"] = "SD_OF_BLOCK_MEAN_SIGNED_CALIBRATION_RESIDUAL"
    COMPLETE["minimum_admissible_cluster_count"] = 6

    if len(REQUIRED_ESTIMATOR_PARTS) != 11:
        f.append("section 7 lists eleven required parts")

    ok, missing, probs = estimator_complete(COMPLETE)
    if not ok:
        f.append(f"a complete spec must pass, missing={missing} problems={probs}")
    r = readiness(COMPLETE, admissible_clusters=8, prior_pool_provisional=False)
    if r["status"] != READY or not r["may_publish_decision_board"]:
        f.append(f"a complete, well-supplied estimator is READY, got {r}")

    # EVERY part is individually required — a spec missing any one is not ready
    for part in REQUIRED_ESTIMATOR_PARTS:
        spec = dict(COMPLETE); spec.pop(part)
        okp, miss, _ = estimator_complete(spec)
        if okp:
            f.append(f"a spec missing {part} must not be complete")
        if part not in miss:
            f.append(f"the missing part {part} must be named")
        rr = readiness(spec)
        if rr["may_publish_decision_board"]:
            f.append(f"a spec missing {part} must not publish a decision board")
        if rr["publication_rule"] != MAY_NOT_PUBLISH:
            f.append(f"the publication rule must fire when {part} is missing")

    # the forbidden substitutes are refused BY NAME, each of them
    for bad in ("CROSS_GAME_P_SD", "BERNOULLI_OUTCOME_SD", "MONTE_CARLO_SD", "MC_SD_DIFFERENCE",
                "PRIOR_PARAMETER_SD"):
        spec = dict(COMPLETE, exact_estimand=bad)
        okb, _, pb = estimator_complete(spec)
        if okb or not any(p["code"] == FORBIDDEN for p in pb):
            f.append(f"{bad} must be refused as an estimator")
        if readiness(spec)["may_publish_decision_board"]:
            f.append(f"{bad} as the estimand must block publication")

    # the cluster floor is enforced inside the spec itself, not only at run time
    lowk = dict(COMPLETE, minimum_admissible_cluster_count=2)
    okl, _, pl = estimator_complete(lowk)
    if okl or not any(p["code"] == "MINIMUM_CLUSTER_COUNT_BELOW_FLOOR" for p in pl):
        f.append("a spec declaring a floor below 6 must be refused")

    # THIS REPOSITORY'S ACTUAL STATE must come back NOT READY, for the right three reasons
    actual = readiness(COMPLETE, admissible_clusters=2, prior_pool_provisional=True)
    if actual["status"] != NOT_READY:
        f.append("k=2 with a provisional pool is not decision ready")
    codes = {x["code"] for x in actual["reasons"]}
    if "INSUFFICIENT_ADMISSIBLE_CLUSTERS" not in codes:
        f.append("k=2 against a floor of 6 must be reported")
    if "PRIOR_INPUT_POOL_PROVISIONAL" not in codes:
        f.append("a provisional training pool must be reported")
    if actual["may_publish_decision_board"]:
        f.append("a not-ready system may not publish a decision board")
    if "BOARD-READINESS failure" not in (actual["note"] or ""):
        f.append("the note must say this is a board-readiness failure, not a per-game explanation")
    # and a ready system must NOT carry the refusal furniture
    if r["publication_rule"] is not None or r["reasons"]:
        f.append("a ready system carries no refusal reason")

    print("readiness_gate selftest:", "OK" if not f else "FAIL")
    for x in f:
        print("   -", x)
    return not f


MUTANTS = [
    ("an incomplete estimator spec may still publish a board",
     "    if missing:\n        reasons.append", "    if False:\n        reasons.append"),
    ("Monte Carlo error is accepted as the estimator",
     '    if est in FORBIDDEN_SUBSTITUTES:', "    if False:"),
    ("cross-game dispersion drops off the forbidden list",
     '    "CROSS_GAME_P_SD", "BERNOULLI_OUTCOME_SD", "MONTE_CARLO_SD", "MC_SD_PRIMARY_30K",',
     '    "BERNOULLI_OUTCOME_SD", "MONTE_CARLO_SD", "MC_SD_PRIMARY_30K",'),
    ("the cluster shortfall stops blocking publication",
     "    if admissible_clusters is not None and isinstance(need, int) and admissible_clusters < need:",
     "    if False:"),
    ("a provisional prior pool stops blocking publication",
     "    if prior_pool_provisional:", "    if False:"),
    ("the declared cluster floor may drop below six",
     "    if isinstance(k, int) and k < 6:", "    if False:"),
    ("a required part is quietly dropped from the contract",
     '    "coverage_validation",\n', ""),
    ("the conversion method stops being required",
     '    "conservative_ev_conversion_method",\n', ""),
    ("refusal behaviour outside support stops being required",
     '    "refusal_behavior_outside_validated_support",\n', ""),
    ("a not-ready system is allowed to publish anyway",
     '        "may_publish_decision_board": ready,', '        "may_publish_decision_board": True,'),
    ("the note stops naming this a board-readiness failure",
     '"a missing estimator is a BOARD-READINESS failure with a pipeline owner, not a "',
     '"uncertainty is unavailable. "'),
]


def mutation_suite():
    src = open(__file__).read()
    killed = 0
    for name, old, new in MUTANTS:
        if old not in src:
            print("  UNAPPLIED ", name + ": pattern not found")
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
    print(__doc__)
