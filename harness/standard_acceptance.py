"""Section 12: the eleven proofs. The standard is implemented only when these pass.

EACH TEST IS AN END-TO-END CLAIM, not a unit test of one function. The modules already carry their
own mutation suites; what this file proves is that the STANDARD holds when they are composed — that
a blocked rail really does advance all the way through the ladder into a decision, that a live price
really cannot reach a pregame overlay from any direction, that a board with no uncertainty really
cannot call itself ready.

A test here that cannot fail is worse than no test, so each one asserts BOTH directions: the
compliant case passes AND the violating case is refused. A one-directional acceptance test is how a
standard becomes decoration.
"""

MODULE_ID = "standard_acceptance"

import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])

import route_ladder_v1 as AL
import checkpoint_schedule as CS
import decision_view as DV
import price_overlay as PO
import readiness_gate as RG
import replacement_workflow as RW
import module_manifest as MM
import pipeline_e2e as PE
import recovery_jobs as RJ
import uncertainty_estimand as UE

RESULTS = []


def _check(name, passed, detail=""):
    RESULTS.append({"test": name, "passed": bool(passed), "detail": detail})
    return bool(passed)


# --- 1 --------------------------------------------------------------------------------------------
def t1_every_game_gets_a_row():
    games = ["mlb:A@B", "mlb:C@D", "wnba:E@F"]
    rows = [{"game": g, "final_decision": DV.PASS, "primary_reason": "negative EV"} for g in games]
    complete = (DV.slate_coverage_gate(games, rows)["status"] == DV.OK
                and DV.final_decision_gate(rows)["status"] == DV.OK)
    # a board that silently drops a game must be REFUSED, not merely different. Checked against the
    # schedule, because rows checked against themselves always cover their own universe.
    dropped = all(DV.slate_coverage_gate(games, [r for r in rows if r["game"] != g])["status"]
                  == DV.REFUSED for g in games)
    phantom = DV.slate_coverage_gate(games, rows + [{"game": "mlb:NOT@SCHEDULED"}])["status"] \
        == DV.REFUSED
    return _check("every scheduled game receives a final decision row",
                  complete and dropped and phantom,
                  "3 scheduled -> 3 rows passes; dropping any one refuses; a phantom game refuses")


# --- 2 & 3 ----------------------------------------------------------------------------------------
def t2_routes_attempted_in_order():
    good = AL.attempt("starter", [{"rung": r, "result": "EGRESS_BLOCKED", "value": None}
                                  for r in AL.RUNG_NAMES])
    bad = AL.attempt("starter", [{"rung": "WEB_SEARCH_OPEN", "result": "EGRESS_BLOCKED",
                                  "value": None},
                                 {"rung": "OFFICIAL_API", "result": "EGRESS_BLOCKED",
                                  "value": None}])
    return _check("every required acquisition route is attempted in order",
                  good["status"] == AL.EXHAUSTED and bad["status"] == AL.OUT_OF_ORDER,
                  "in-order exhaustion accepted; out-of-order refused")


def t3_blocked_rail_advances():
    one = AL.attempt("starter", [{"rung": "OFFICIAL_API", "result": "EGRESS_BLOCKED",
                                  "value": None}])
    advanced = one["status"] == AL.INCOMPLETE and len(one["routes_untried"]) == 6
    two = AL.attempt("starter", [{"rung": "OFFICIAL_API", "result": "EGRESS_BLOCKED", "value": None},
                                 {"rung": "OFFICIAL_LEAGUE_PAGE", "result": "OK",
                                  "value": "Wheeler", "artifact_sha256": "abc"}])
    resolved = two["status"] == AL.ACQUIRED and two["rung"] == "OFFICIAL_LEAGUE_PAGE"
    return _check("a blocked direct rail automatically advances to the next route",
                  advanced and resolved,
                  "rung 1 blocked leaves 6 untried; rung 2 then resolves the field")


# --- 4 & 5 ----------------------------------------------------------------------------------------
def t4_material_change_generates_replacement():
    orig = {"identity": "mlb.winner.CHAMPION_V13", "p_home": 0.5340}
    got, err = RW.replace(orig, "CONFIRMED_STARTER_REPLACING_OFFICIAL_TBD",
                          "CWS starter: TBD -> Urquidy", "OFFICIAL_TEAM_PAGE_OR_STATUS",
                          "mlb.replacement.CONFIRMED_LINEUP", 0.5121,
                          "2026-08-24T23:00:00Z", "2026-08-24T23:40:00Z", "2026-08-24T23:10:00Z")
    made = not err and got["replacement"]["identity"] != orig["identity"]
    _, err2 = RW.replace(orig, "CONFIRMED_STARTER_REPLACING_OFFICIAL_TBD", "x", "y",
                         "mlb.replacement.IMPROVISED", 0.5,
                         "2026-08-24T23:00:00Z", "2026-08-24T23:40:00Z", "2026-08-24T23:10:00Z")
    return _check("material changes generate replacement identities",
                  made and bool(err2),
                  "registered identity accepted; improvised identity refused")


def t5_originals_immutable():
    orig = {"identity": "mlb.winner.CHAMPION_V13", "p_home": 0.5340}
    before = dict(orig)
    got, err = RW.replace(orig, "PITCHER_SCRATCH", "scratch", "OFFICIAL_TEAM_PAGE_OR_STATUS",
                          "mlb.replacement.CONFIRMED_LINEUP", 0.4900,
                          "2026-08-24T23:00:00Z", "2026-08-24T23:40:00Z", "2026-08-24T23:10:00Z")
    unchanged = (not err) and orig == before and got["original"] == before
    distinct = got["replacement"]["forecast_sha256"] != got["replacement"]["original_forecast_sha256"]
    return _check("original forecasts remain immutable",
                  unchanged and distinct,
                  "original byte-identical after replacement; hashes differ")


# --- 6, 7, 8 --------------------------------------------------------------------------------------
def t6_live_price_cannot_enter_pregame():
    START = "2026-08-24T23:40:00Z"
    q = {"game": "mlb:TEX@CWS", "actual_start_utc": START, "books": ["DRAFTKINGS"]}
    ok = PO.pregame_overlay_gate([dict(q, captured_at_utc="2026-08-24T16:41:27Z",
                                       declared_phase="PRE_GAME")])["status"] == PO.ELIGIBLE
    by_clock = PO.pregame_overlay_gate([dict(q, captured_at_utc="2026-08-25T01:58:16Z")])
    by_decl = PO.pregame_overlay_gate([dict(q, captured_at_utc="2026-08-24T16:41:27Z",
                                            declared_phase="LIVE")])
    return _check("live prices cannot enter pregame overlays",
                  ok and by_clock["status"] != PO.ELIGIBLE and by_decl["status"] != PO.ELIGIBLE,
                  "refused by the clock AND by a declared phase; pregame quote still passes")


def t7_cross_book_cannot_pass_same_book_hold():
    START = "2026-08-24T23:40:00Z"
    q = {"game": "mlb:A@B", "captured_at_utc": "2026-08-24T16:41:27Z", "actual_start_utc": START}
    one = PO.pregame_overlay_gate([dict(q, books=["DRAFTKINGS"])])["status"] == PO.ELIGIBLE
    two = PO.pregame_overlay_gate([dict(q, books=["DRAFTKINGS", "FANDUEL"])])
    caught = any(p["code"] == PO.CROSS_BOOK_HOLD for p in two["problems"])
    return _check("cross-book prices cannot pass same-book hold validation",
                  one and caught, "one book eligible; two books refused")


def t8_stale_quote_cannot_authorize():
    START = "2026-08-24T23:40:00Z"
    stale = PO.market_phase("2026-08-25T01:58:16Z", START)[1]
    row = {"game": "mlb:A@B", "final_decision": DV.BET, "primary_reason": "edge",
           "conservative_ev_per_100": 5.0}
    # a BET is only publishable when its quote is pregame; the phase gate is the upstream stop
    return _check("stale quotes cannot authorize execution",
                  (not stale) and DV.final_decision_gate([row])["status"] == DV.OK,
                  "post-start quote inadmissible upstream; a pregame BET still publishable")


# --- 9 --------------------------------------------------------------------------------------------
def t9_missing_uncertainty_blocks_readiness():
    COMPLETE = {p: "specified" for p in RG.REQUIRED_ESTIMATOR_PARTS}
    COMPLETE["exact_estimand"] = "SD_OF_BLOCK_MEAN_SIGNED_CALIBRATION_RESIDUAL"
    COMPLETE["minimum_admissible_cluster_count"] = 6
    ready = RG.readiness(COMPLETE, admissible_clusters=8, prior_pool_provisional=False)
    absent = RG.readiness({}, admissible_clusters=2, prior_pool_provisional=True)
    return _check("missing uncertainty prevents the board from claiming decision readiness",
                  ready["may_publish_decision_board"] and
                  not absent["may_publish_decision_board"] and
                  absent["status"] == RG.NOT_READY,
                  "complete estimator publishes; absent estimator is SYSTEM_NOT_DECISION_READY")


# --- 10 -------------------------------------------------------------------------------------------
def t10_no_blocked_row_labelled_a_selection():
    ALLG = {g: True for g in DV.GATE_NAMES}
    NONE_ = {g: False for g in DV.GATE_NAMES}
    blocked = DV.row("mlb:COL@WSH", "WSH", 0.5666, "COL", 169, 16.58, 3, 3, "Over 8", NONE_,
                     "2026-08-24T16:41:27Z", blocker_detail="MODEL_UNCERTAINTY")
    bet = DV.row("mlb:A@B", "B", 0.55, "A", 120, 5.0, 3, 3, "Over 8", ALLG, "2026-08-24T16:41:27Z")
    refused = DV.render_gate([blocked], rendered_selections=[blocked])
    caught = any(p["code"] == DV.BLOCKED_AS_SELECTION for p in refused["problems"])
    allowed = DV.render_gate([bet], rendered_selections=[bet])["status"] == DV.OK
    empty = DV.selections([blocked]) == []
    return _check("no blocked opportunity is labelled a selection",
                  caught and allowed and empty,
                  "a blocked row in the selections section is refused; a BET is not")


# --- 11 -------------------------------------------------------------------------------------------
def t11_wager_carries_quote_risk_stake_boundary():
    full = {k: "x" for k in DV.ROW_CONTRACT_V1}
    full.update(game="mlb:A@B", final_decision=DV.BET, recommended_units=1.0,
                recommended_dollars=100.0, playable_price_boundary="-115",
                quote_timestamp_utc="2026-08-24T16:41:27Z", quote_age_seconds=60)
    ok = DV.row_contract_gate([full])["status"] == DV.OK
    bad = all(DV.row_contract_gate([dict(full, **{k: v})])["status"] == DV.REFUSED
              for k, v in (("playable_price_boundary", None), ("recommended_units", None),
                           ("recommended_dollars", 50.0)))
    return _check("every authorized wager carries a fresh quote, risk, stake and playable-price "
                  "boundary", ok and bad,
                  "complete wager row passes; each missing element refuses")


# --- the section 1 rule, which is the whole point --------------------------------------------------
def t12_work_queue_is_not_a_decision():
    ok = DV.final_decision_gate([{"game": "mlb:A@B", "final_decision": DV.PASS,
                                  "primary_reason": "negative expected value at this price",
                                  "conservative_ev_per_100": None}])["status"] == DV.OK
    bad = all(DV.final_decision_gate([{"game": "mlb:A@B", "final_decision": DV.PASS,
                                       "primary_reason": wq,
                                       "conservative_ev_per_100": None}])["status"] == DV.REFUSED
              for wq in ("UNCERTAINTY_PIPELINE_DEFECT", "PERSONNEL_UNVERIFIED", "PRICE_MISSING",
                         "STARTER_UNCONFIRMED", "BLOCKED_INFORMATION_UNAVAILABLE"))
    late = CS.status(4, set(CS.NAMES) - {"T_MINUS_45M"})["status"] == CS.SYSTEM_FAILURE
    return _check("an internal work queue may not end a game, and an overdue checkpoint at the "
                  "freeze is a SYSTEM_FAILURE", ok and bad and late,
                  "a genuine economic PASS publishes; a work-queue reason does not")


# --- v1.0 conditional-acceptance requirements ------------------------------------------------------
def t13_computable_is_not_decision_grade():
    if UE.MIN_COMPUTABLE_CLUSTERS != 6 or UE.DECISION_GRADE_EFFECTIVE_CLUSTERS != 20.0:
        return _check("computable and decision-grade cluster thresholds are separate", False)
    after_restore = UE.grade(7, cluster_sizes=[15] * 7,
                             block_residuals={f"d{i}": 0.01 * i for i in range(7)}, coverage=95.0)
    good = UE.grade(24, cluster_sizes=[15] * 24,
                    block_residuals={f"d{i}": (0.005 if i % 2 else -0.005) for i in range(24)},
                    coverage=95.0)
    # each of the four requirements alone must be able to stop decision grade
    stops = [
        UE.grade(24, cluster_sizes=[500] + [5] * 23,
                 block_residuals={f"d{i}": (0.005 if i % 2 else -0.005) for i in range(24)},
                 coverage=95.0)["grade"],
        UE.grade(24, cluster_sizes=[15] * 24,
                 block_residuals=dict({f"d{i}": 0.001 for i in range(23)}, d23=0.9),
                 coverage=95.0)["grade"],
        UE.grade(24, cluster_sizes=[15] * 24,
                 block_residuals={f"d{i}": (0.005 if i % 2 else -0.005) for i in range(24)},
                 coverage=None)["grade"],
        UE.grade(24, cluster_sizes=[15] * 24, block_residuals=None, coverage=95.0)["grade"],
    ]
    return _check("six or seven clusters is computable, not decision-grade",
                  after_restore["grade"] == UE.GRADE_COMPUTABLE
                  and good["grade"] == UE.GRADE_DECISION
                  and all(g != UE.GRADE_DECISION for g in stops),
                  "k=7 computable; 24 effective + stable LOO + validated coverage passes; "
                  "imbalance, influence, missing coverage and no-LOO each block alone")


def t14_pipeline_bypass_is_detected():
    ok = PE.run_instrumented(**PE.DEFAULT_RUN)
    bypassed = []
    for gate in PE.REQUIRED_GATES:
        with PE._Trace(tuple(g for g in PE.REQUIRED_GATES if g != gate)) as tr:
            try:
                PE.run_board(**PE.DEFAULT_RUN)
            except Exception:
                pass
        bypassed.append(gate not in set(tr.called))
    return _check("healthcheck fails when a registered gate is bypassed",
                  ok["status"] == PE.OK and ok["n_invoked"] == ok["n_required"]
                  and all(bypassed),
                  f"{ok['n_invoked']}/{ok['n_required']} invoked on a compliant run; each of the "
                  f"{len(PE.REQUIRED_GATES)} gates is individually detectable when skipped")


def t15_open_defects_are_owned_by_jobs():
    jobs = RJ.load() or RJ.default_jobs()
    rep = RJ.status_report(jobs, "2026-08-25T03:00:00Z")
    owned = all(b in rep["open_blockers"] for b in
                ("PRIOR_INPUT_POOL_PROVISIONAL", "UNCERTAINTY_PIPELINE_DEFECT"))
    fields = all(all(k in j for k in RJ.REQUIRED_FIELDS) for j in jobs.values())
    # a job cannot lie about its own progress. Use an explicitly INCOMPLETE copy: borrowing the
    # live first job broke this proof the day RJ-001 legitimately reached 123/123 — closing a
    # complete job with a valid disposition is allowed, and the proof was testing live state.
    j = dict(list(jobs.values())[0], units_done=0)
    refuses = all(RJ.advance(j, "2026-08-25T03:00:00Z", **kw)[0] is None for kw in (
        {"units_done": -1}, {"status": RJ.COMPLETE, "disposition": "RESTORED"},
        {"units_done": j["units_total"], "status": RJ.COMPLETE},
        {"units_done": j["units_total"], "status": RJ.COMPLETE,
         "disposition": "WE_STOPPED_LOOKING"}))
    late = RJ.status_report(jobs, "2027-01-01T00:00:00Z")["n_overdue"] > 0
    return _check("open defects are executable jobs with id, next run, progress, deadline and "
                  "terminal disposition", owned and fields and refuses and late,
                  "every open blocker names its job; backwards progress, premature closure and an "
                  "unrecognised disposition all refuse; a passed deadline reports OVERDUE")


def t16_clobber_protection():
    M = {"harness/a.py": "alpha"}
    occupied = MM.check_write("harness/a.py", "beta", MM.CREATE, M)
    replace_ok = MM.check_write("harness/a.py", "beta", MM.REPLACE, M, replaces="alpha",
                                reason="superseded")
    replace_bad = [MM.check_write("harness/a.py", "beta", MM.REPLACE, M, **kw)[0]
                   for kw in ({"replaces": None, "reason": "x"},
                              {"replaces": "wrong", "reason": "x"},
                              {"replaces": "alpha", "reason": None})]
    dup = MM.check_write("harness/z.py", "alpha", MM.CREATE, M)
    live = MM.audit()
    return _check("a unique (path, module_id) manifest refuses creation over an occupied path and "
                  "duplicate identities",
                  (not occupied[0]) and occupied[1]["code"] == MM.OCCUPIED
                  and replace_ok[0] and not any(replace_bad)
                  and (not dup[0]) and dup[1]["code"] == MM.DUPLICATE
                  and live["status"] == MM.OK,
                  f"CREATE over an occupied path refused; explicit REPLACE naming what it displaces "
                  f"and why accepted; duplicate id refused; live manifest {live['n_modules']} "
                  f"modules, {live['n_problems']} problems")


TESTS = (t1_every_game_gets_a_row, t2_routes_attempted_in_order, t3_blocked_rail_advances,
         t4_material_change_generates_replacement, t5_originals_immutable,
         t6_live_price_cannot_enter_pregame, t7_cross_book_cannot_pass_same_book_hold,
         t8_stale_quote_cannot_authorize, t9_missing_uncertainty_blocks_readiness,
         t10_no_blocked_row_labelled_a_selection, t11_wager_carries_quote_risk_stake_boundary,
         t12_work_queue_is_not_a_decision, t13_computable_is_not_decision_grade,
         t14_pipeline_bypass_is_detected, t15_open_defects_are_owned_by_jobs,
         t16_clobber_protection)


def run():
    RESULTS.clear()
    for t in TESTS:
        t()
    passed = sum(1 for r in RESULTS if r["passed"])
    for r in RESULTS:
        print(("  PASS  " if r["passed"] else "  FAIL  ") + r["test"])
        if r["detail"]:
            print("          " + r["detail"])
    print(f"standard acceptance: {passed}/{len(RESULTS)} passed"
          + ("" if passed == len(RESULTS) else "  — STANDARD NOT IMPLEMENTED"))
    return passed == len(RESULTS)


def selftest():
    ok = run()
    print("standard_acceptance selftest:", "OK" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
