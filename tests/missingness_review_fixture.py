"""Synthetic, signed-registry fixture only. The limits below are never installed."""
from datetime import timedelta
from pipelines.cards.missingness import OBSERVATION_STATES, REQUIRED_TESTS, seal_audit
from research.validation_registry import _time


def make_study(store, protocol, sign, witness):
    pid, target = protocol["candidate_id"], protocol["target"]
    model = store.read(pid)["definition"]["model_id"]
    key = "fixture-report-season"
    bounds = {"procedure_id": pid, "target": target, "scope": "CALIBRATION", "stratum": key,
              "last_outcome_utc": protocol["development_end_utc"]}
    bounds["events"] = [{"event_id": f"calibration-{i}", "available_utc": protocol["development_end_utc"],
                         "source_states": {f"test-source-{j}": "VERIFIED_OBSERVATION" if i else "NOT_YET_PUBLISHED"
                                           for j in range(2)}, "same_fit_head_shift": .2} for i in range(2)]
    spec = {"limit_method": "WITHIN_EMPIRICAL_CALIBRATION_SUPPORT", "source": "test-feed", "source_ids": ["test-source-0","test-source-1"], "season": "test-season", "head": target["product"], "unit": "probability", "metric": "brier",
            "definition": "report indicator", "freshness": "same cutoff", "missing_representation": "null",
            "imputation": "fixture-training median", "indicator": "report pending", "fallback": "research hold",
            "operational_states": list(OBSERVATION_STATES), "calibration_data_id": store.put(bounds),
            "max_abs_shift": 0.2, "missing_rate_min": 0., "missing_rate_max": 1.,
            "minimum_events": 3, "max_mean_loss_delta": {"incumbent": 0., "independent": 0.}}
    policy = {"schema": "sports.missingness_policy.v1", "procedure_id": pid, "target": target,
              "model_id": model, "witnesses": {purpose: witness for purpose in ("missingness_pregame_registration", "missingness_result_reconciliation")}, "calibration_end_utc": protocol["development_end_utc"], "strata": {key: spec},
              "incumbent_id": protocol["control_id"], "independent_comparator_id": store.put({"fixture": "market"})}
    policy["monitoring_population_id"] = store.put({"procedure_id": pid, "target": target,
        "frozen_utc": protocol["development_end_utc"], "events_by_stratum": {key: [f"fixture-{i}" for i in range(3)]}})
    policy_id=store.put(policy)
    rows = []
    start = _time(protocol["evaluation_start_utc"])
    for i, group in enumerate(("complete", "partial", "missing")):
        eid = f"fixture-{i}"
        f = {target["product"]: .53}
        states = {f"test-source-{j}": "ACQUISITION_FAILURE" if j<i else "VERIFIED_OBSERVATION" for j in range(2)}
        measure = {"policy_id": policy_id, "unit": "probability", "head": target["product"], "head_after": .53,
                   "same_fit_reporting_control_head": .5, "source_states": states}
        receipt = seal_audit(league=target["league"], event_id=eid, model_id=model, products=[target["product"]],
                             forecast=f, details={"source": "synthetic", "monitored_strata": {key: measure}})
        rows.append({"event_id": eid, "registered_at_utc": start.isoformat(),
                     "start_utc": (start+timedelta(minutes=5)).isoformat(),
                     "result_available_utc": (start+timedelta(hours=2)).isoformat(),
                     "report_group": group, "receipt_id": store.put(receipt), "forecast_id": store.put(f),
                     "head_shift": 0.03, "missing_rate": i/2, "model_loss": (.53-1)**2,
                     "incumbent_loss": .25, "independent_loss": .25,
                     "result_id": store.put({"event_id": eid, "target": target, "status": "RECONCILED",
                             "actual": 1, "start_utc": (start+timedelta(minutes=5)).isoformat(),
                             "available_utc": (start+timedelta(hours=2)).isoformat()}),
                     **{name+"_forecast_id": store.put({"event_id": eid, "target": target, "point": .5,
                            "procedure_id": ref, "frozen_utc": start.isoformat()}) for name,ref in
                            (("incumbent", protocol["control_id"]),("independent",policy["independent_comparator_id"]))}})
    for row in rows:
        record = {"event_id": row["event_id"], "procedure_id": pid, "target": target,
                  "forecast_id":row["forecast_id"], "receipt_id":row["receipt_id"], "start_utc":row["start_utc"],
                  "incumbent_forecast_id":row["incumbent_forecast_id"],
                  "independent_forecast_id":row["independent_forecast_id"]}
        row["registration_id"] = store.put(record)
        row["registration_witness_id"] = sign(row["registration_id"], "missingness_pregame_registration", row["registered_at_utc"])
        row["result_witness_id"] = sign(row["result_id"], "missingness_result_reconciliation", row["result_available_utc"])
    observed = store.put({"events": rows, "stratum": key, "policy_id": policy_id})
    checks = {name: store.put({"test": name, "passed": True, "cases": 1, "procedure_id": pid}) for name in REQUIRED_TESTS}
    test_id = store.put({"procedure_id": pid, "policy_id": policy_id, "tests": checks})
    return policy_id, store.put({"schema": "sports.missingness_evaluation.v1", "policy_id": policy_id,
                                "strata": {key: observed}, "engineering_evidence_id": test_id})
