"""Synthetic versioned study policies: refuse absent inputs without inventing scores."""
from copy import deepcopy

import pytest

from pipelines.cards.missingness import seal_audit
from research import missingness_review as review
from research.validation_registry import RegistryError, _time
from test_validation_registry import make_registry_fixture


def make_refusal_study(tmp_path, *, overrides=None, all_complete=False, all_supported=False):
    fixture = make_registry_fixture(tmp_path / "objects")
    store = fixture["store"]
    policy = store.read(fixture["protocol"]["missingness_policy_id"])
    result = store.read(fixture["evidence"]["missingness_evaluation_id"])
    key = next(iter(policy["strata"]))
    data = store.read(result["strata"][key])
    contract = policy["strata"][key]
    groups = ["complete", "partial", "missing"] if all_supported else ["complete"]
    contract.update(
        prediction_groups=groups,
        prediction_source_states={source: list(review.OBSERVATION_STATES) if all_supported else
                                  ["VERIFIED_OBSERVATION", "VERIFIED_ABSENCE"]
                                  for source in contract["source_ids"]},
        minimum_predictions_by_group=dict.fromkeys(groups, 1),
        minimum_refusals=0 if all_complete or all_supported else 2,
        max_refusal_rate=0.0 if all_complete or all_supported else 2 / 3,
    )
    contract.update(overrides or {})
    policy["schema"] = "sports.missingness_policy.v2"
    policy_id = store.put(policy)
    for index, row in enumerate(data["events"]):
        old = store.read(row["receipt_id"])
        measure = old["details"]["monitored_strata"][key]
        measure["policy_id"] = policy_id
        if all_complete:
            measure["source_states"] = dict.fromkeys(contract["source_ids"], "VERIFIED_OBSERVATION")
            row.update(report_group="complete", missing_rate=0.0)
        refused = index > 0 and not all_complete and not all_supported
        row["disposition"] = "REFUSED" if refused else "FORECAST"
        forecast = store.read(row["forecast_id"])
        products = [contract["head"]]
        if refused:
            reasons = ["REPORT_GROUP_UNSUPPORTED:" + row["report_group"]] + [
                "SOURCE_STATE_UNSUPPORTED:test-source-" + str(j) + ":ACQUISITION_FAILURE"
                for j in range(index)
            ]
            row.update(reason_codes=reasons, model_loss=None, head_shift=None)
            forecast = {"status": "REFUSED", "reason_codes": reasons}
            measure.pop("head_after")
            measure.pop("same_fit_reporting_control_head")
            products = ["coverage"]
        row["forecast_id"] = store.put(forecast)
        row["receipt_id"] = store.put(seal_audit(
            league=policy["target"]["league"], event_id=row["event_id"], model_id=policy["model_id"],
            products=products, forecast=forecast,
            details={"source": "TEST_ONLY synthetic", "monitored_strata": {key: measure}},
        ))
        resign(fixture, row)
    data["policy_id"] = policy_id
    checks = store.read(result["engineering_evidence_id"])
    checks["policy_id"] = policy_id
    result.update(schema="sports.missingness_evaluation.v2", policy_id=policy_id,
                  engineering_evidence_id=store.put(checks), strata={key: store.put(data)})
    return fixture, policy_id, result, key, data


def resign(fixture, row):
    store = fixture["store"]
    record = {"event_id": row["event_id"], "procedure_id": fixture["procedure_id"],
              "target": fixture["target"], **{k: row[k] for k in (
                  "forecast_id", "receipt_id", "start_utc", "incumbent_forecast_id",
                  "independent_forecast_id", "disposition")}}
    row["registration_id"] = store.put(record)
    row["registration_witness_id"] = fixture["sign"](
        row["registration_id"], "missingness_pregame_registration", "TEST_ONLY_witness", row["registered_at_utc"])


def validate(case):
    fixture, policy_id, result, key, data = case
    store = fixture["store"]
    result["strata"][key] = store.put(data)
    return review.validate_study(
        store, policy_id, store.put(result), fixture["procedure_id"], fixture["target"],
        _time(fixture["protocol"]["evaluation_start_utc"]),
        _time(fixture["protocol"]["evaluation_end_utc"]), verifier=fixture["verifier"],
    )


def test_mandatory_missing_inputs_are_retained_as_refusals_not_numeric_forecasts(tmp_path):
    case = make_refusal_study(tmp_path)
    policy = validate(case)
    assert policy["schema"] == "sports.missingness_policy.v2"
    rows = case[-1]["events"]
    assert [r["disposition"] for r in rows] == ["FORECAST", "REFUSED", "REFUSED"]
    assert rows[0]["model_loss"] == pytest.approx((.53 - 1) ** 2)
    assert all(r["model_loss"] is None and r["head_shift"] is None for r in rows[1:])


def test_complete_only_confirmation_can_only_support_declared_complete_scope(tmp_path):
    case = make_refusal_study(tmp_path, all_complete=True)
    policy = validate(case)
    contract = policy["strata"][case[3]]
    measure = {"policy_id": case[1], "head": contract["head"], "unit": contract["unit"],
               "source_states": dict.fromkeys(contract["source_ids"], "ACQUISITION_FAILURE"),
               "head_after": .53, "same_fit_reporting_control_head": .53}
    with pytest.raises(RegistryError, match="CURRENT_SOURCE_SCOPE_UNSUPPORTED"):
        review.monitored(measure, case[1], contract, {contract["head"]: .53})


def test_policy_can_require_actual_predictions_in_all_three_groups(tmp_path):
    validate(make_refusal_study(tmp_path, all_supported=True))


@pytest.mark.parametrize("overrides,reason", [
    ({"max_refusal_rate": .5}, "REFUSAL_COVERAGE_OUT_OF_BOUNDS"),
    ({"minimum_refusals": 3}, "REFUSAL_COVERAGE_OUT_OF_BOUNDS"),
    ({"minimum_predictions_by_group": {"complete": 2}}, "INSUFFICIENT_GROUP_PREDICTIONS"),
    ({"prediction_groups": []}, "PREDICTION_GROUP_SCOPE"),
    ({"prediction_groups": ["complete", "complete"]}, "PREDICTION_GROUP_SCOPE"),
    ({"minimum_predictions_by_group": {"complete": True}}, "PREDICTION_GROUP_COUNTS"),
    ({"prediction_source_states": {}}, "PREDICTION_SOURCE_SCOPE"),
    ({"max_refusal_rate": True}, "NONFINITE_MEASUREMENT"),
])
def test_predeclared_coverage_limits_cannot_be_skipped(tmp_path, overrides, reason):
    with pytest.raises(RegistryError, match=reason):
        validate(make_refusal_study(tmp_path, overrides=overrides))


def test_refusal_cannot_be_dropped_from_witnessed_population(tmp_path):
    case = make_refusal_study(tmp_path)
    case[-1]["events"].pop()
    with pytest.raises(RegistryError, match="MONITORING_POPULATION_MISMATCH"):
        validate(case)


@pytest.mark.parametrize("change", ["numeric_loss", "numeric_shift", "wrong_reasons", "hidden_head"])
def test_refusal_never_becomes_scored_prediction_or_unexplained_omission(tmp_path, change):
    case = make_refusal_study(tmp_path)
    fixture, policy_id, result, key, data = case
    row = data["events"][1]
    if change == "numeric_loss":
        row["model_loss"] = 0
    elif change == "numeric_shift":
        row["head_shift"] = 0
    elif change == "wrong_reasons":
        row["reason_codes"] = ["COLLECTOR_WORKED"]
    else:
        store = fixture["store"]
        receipt = store.read(row["receipt_id"])
        receipt["details"]["monitored_strata"][key]["head_after"] = .53
        row["receipt_id"] = store.put(seal_audit(
            league=receipt["league"], event_id=receipt["event_id"], model_id=receipt["model_id"],
            products=["coverage"], forecast=store.read(row["forecast_id"]), details=receipt["details"]))
        resign(fixture, row)
    with pytest.raises(RegistryError, match="REFUSAL_"):
        validate(case)


def test_disposition_is_bound_by_pregame_registration(tmp_path):
    case = make_refusal_study(tmp_path)
    fixture, *_, data = case
    row = data["events"][0]
    record = fixture["store"].read(row["registration_id"])
    record["disposition"] = "REFUSED"
    row["registration_id"] = fixture["store"].put(record)
    row["registration_witness_id"] = fixture["sign"](
        row["registration_id"], "missingness_pregame_registration", "TEST_ONLY_witness", row["registered_at_utc"])
    with pytest.raises(RegistryError, match="REGISTRATION_BINDING"):
        validate(case)


def test_existing_v1_policy_cannot_silently_adopt_new_refusal_semantics(tmp_path):
    case = make_refusal_study(tmp_path)
    fixture, _, result, key, data = case
    policy = fixture["store"].read(case[1])
    policy["schema"] = "sports.missingness_policy.v1"
    policy_id = fixture["store"].put(policy)
    result.update(schema="sports.missingness_evaluation.v1", policy_id=policy_id)
    with pytest.raises(RegistryError, match="REFUSAL_POLICY_REQUIRES_V2"):
        validate((fixture, policy_id, result, key, data))


@pytest.mark.parametrize("name", ["incumbent", "independent"])
def test_witnessed_comparator_may_also_refuse_an_unscored_opportunity(tmp_path, name):
    case = make_refusal_study(tmp_path)
    fixture, *_, data = case
    store = fixture["store"]
    for row in data["events"][1:]:
        comparator = store.read(row[name + "_forecast_id"])
        comparator.pop("point")
        comparator.update(disposition="REFUSED", reason_codes=["MANDATORY_INPUT_UNAVAILABLE"])
        row[name + "_forecast_id"] = store.put(comparator)
        row[name + "_loss"] = None
        resign(fixture, row)
    validate(case)


@pytest.mark.parametrize("change", ["scored_candidate", "invented_loss", "invented_point", "no_reason"])
def test_comparator_refusal_cannot_supply_a_numeric_comparison(tmp_path, change):
    case = make_refusal_study(tmp_path)
    fixture, *_, data = case
    store = fixture["store"]
    row = data["events"][0 if change == "scored_candidate" else 1]
    comparator = store.read(row["incumbent_forecast_id"])
    comparator.pop("point")
    comparator.update(disposition="REFUSED", reason_codes=["MANDATORY_INPUT_UNAVAILABLE"])
    row["incumbent_loss"] = 0.0 if change == "invented_loss" else None
    if change == "invented_point":
        comparator["point"] = .5
    if change == "no_reason":
        comparator["reason_codes"] = []
    row["incumbent_forecast_id"] = store.put(comparator)
    resign(fixture, row)
    with pytest.raises(RegistryError, match="COMPARATOR_REFUSAL_INVALID"):
        validate(case)
