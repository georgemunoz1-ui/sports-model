"""Acceptance of a model/product missingness study. Approval is external to the study."""
import base64
import json
import math
from pathlib import Path

from pipelines.cards.missingness import OBSERVATION_STATES, REQUIRED_TESTS, content_digest, verify_audit
from research.validation_registry import ArtifactStore, Ed25519Verifier, RegistryError, _time

REVIEW_DIR = Path(__file__).resolve().parents[1] / "data/model_selection/missingness"
PERFORMANCE_GROUPS = {"complete", "partial", "missing"}


def require(ok, reason):
    if not ok:
        raise RegistryError("MISSINGNESS_" + reason)


def number(value):
    require(type(value) in (float, int) and math.isfinite(value), "NONFINITE_MEASUREMENT")
    return value


def monitored(measure, policy_id, contract, forecast):
    require(measure["policy_id"] == policy_id and measure["head"] == contract["head"] and
            measure["unit"] == contract["unit"], "CURRENT_STRATUM_SCOPE")
    states = measure["source_states"]
    require(isinstance(states, dict) and bool(states) and set(states) == set(contract["source_ids"]) and
            set(states.values()) <= set(OBSERVATION_STATES),
            "CURRENT_OBSERVATION_STATES")
    missing = sum(s not in ("VERIFIED_OBSERVATION", "VERIFIED_ABSENCE") for s in states.values())
    rate = missing / len(states)
    group = "complete" if missing == 0 else "missing" if missing == len(states) else "partial"
    after = number(forecast[contract["head"]])
    require(number(measure["head_after"]) == after, "CURRENT_HEAD_BINDING")
    shift = after - number(measure["same_fit_reporting_control_head"])
    require(abs(shift) <= number(contract["max_abs_shift"]) and
            0 <= number(contract["missing_rate_min"]) <= rate <= number(contract["missing_rate_max"]) <= 1,
            "CURRENT_STRATUM_OUT_OF_BOUNDS")
    return group, rate, shift, after


def loss(metric, prediction, actual):
    p, y = number(prediction), number(actual)
    if metric == "mae":
        return abs(p-y)
    if metric == "squared_error":
        return (p-y)**2
    require(metric in ("brier", "log_loss") and y in (0, 1) and 0 <= p <= 1, "INVALID_SCORING_INPUT")
    if metric == "brier":
        return (p-y)**2
    probability = p if y else 1-p
    require(probability > 0, "INFINITE_LOG_LOSS")
    return -math.log(probability)


def validate_study(store, policy_id, results_id, procedure_id, target, start, end, *, verifier=None):
    """Read hash-bound inputs. The enclosing protocol and review authorize these IDs."""
    require(isinstance(verifier, Ed25519Verifier), "TRUSTED_WITNESS_REQUIRED")
    policy, results = store.read(policy_id), store.read(results_id)
    require(policy.get("schema") == "sports.missingness_policy.v1" and
            results.get("schema") == "sports.missingness_evaluation.v1", "STUDY_SCHEMA")
    require(policy["procedure_id"] == procedure_id and policy["target"] == target and
            results["policy_id"] == policy_id, "STUDY_SCOPE_MISMATCH")
    require(_time(policy["calibration_end_utc"]) < start < end, "CALIBRATION_OVERLAP")
    # Every stratum binds a source, season, feature contract, and native head/unit.
    contracts, observations = policy["strata"], results["strata"]
    require(isinstance(contracts, dict) and contracts and contracts.keys() == observations.keys(),
            "SOURCE_SEASON_COVERAGE")
    population = store.read(policy["monitoring_population_id"])
    require(population["procedure_id"] == procedure_id and population["target"] == target and
            _time(population["frozen_utc"]) <= _time(policy["calibration_end_utc"]) and
            set(population["events_by_stratum"]) == set(contracts), "MONITORING_POPULATION_BINDING")
    for key, c in contracts.items():
        require(all(isinstance(c[k], str) and c[k].strip() for k in
                    ("source", "season", "head", "unit", "definition", "freshness", "missing_representation",
                     "imputation", "indicator", "fallback")), "FEATURE_CONTRACT")
        require(set(c["operational_states"]) == set(OBSERVATION_STATES), "OBSERVATION_SCOPE")
        baseline = store.read(c["calibration_data_id"])
        require(baseline["scope"] == "CALIBRATION" and baseline["stratum"] == key and
                baseline["procedure_id"] == procedure_id and baseline["target"] == target and
                _time(baseline["last_outcome_utc"]) <= _time(policy["calibration_end_utc"]),
                "CALIBRATION_SOURCE_BINDING")
        historical = baseline["events"]
        source_ids = c["source_ids"]
        require(isinstance(source_ids, list) and bool(source_ids) and all(type(x) is str and x for x in source_ids)
                and len(source_ids) == len(set(source_ids)), "SOURCE_KEYS")
        require(isinstance(historical, list) and historical and
                len({r["event_id"] for r in historical}) == len(historical), "CALIBRATION_ROWS")
        rates, shifts = [], []
        for r in historical:
            states = r["source_states"]
            require(r["event_id"] and set(states) == set(source_ids) and
                    set(states.values()) <= set(OBSERVATION_STATES) and
                    _time(r["available_utc"]) <= _time(baseline["last_outcome_utc"]), "CALIBRATION_ROW_BINDING")
            rates.append(sum(s not in ("VERIFIED_OBSERVATION", "VERIFIED_ABSENCE") for s in states.values())/len(states))
            shifts.append(abs(number(r["same_fit_head_shift"])))
        require(c["limit_method"] == "WITHIN_EMPIRICAL_CALIBRATION_SUPPORT"
                and 0 <= number(c["max_abs_shift"]) <= max(shifts)
                and min(rates) <= number(c["missing_rate_min"]) <= number(c["missing_rate_max"]) <= max(rates),
                "LIMIT_OUTSIDE_CALIBRATION_BASIS")
        data = store.read(observations[key])
        ids = set()
        groups = set()
        for row in data["events"]:
            eid = row["event_id"]
            require(isinstance(eid, str) and eid and eid not in ids, "DUPLICATE_OR_MISSING_EVENT")
            ids.add(eid)
            require(start <= _time(row["registered_at_utc"]) < _time(row["start_utc"])
                    <= _time(row["result_available_utc"]) <= end, "FORWARD_CHRONOLOGY")
            receipt = store.read(row["receipt_id"])
            require(receipt.get("schema") == "sports.missingness_audit.v1" and
                    receipt.get("event_id") == eid and receipt.get("league") == target["league"] and
                    receipt.get("model_id") == policy["model_id"] and c["head"] in receipt["products"],
                    "MONITORING_RECEIPT_SCOPE")
            forecast = store.read(row["forecast_id"])
            require(verify_audit(receipt, league=target["league"], event_id=eid, model_id=policy["model_id"],
                                 products=receipt["products"], forecast=forecast), "MONITORING_RECEIPT_BINDING")
            group, rate, shift, prediction = monitored(receipt["details"]["monitored_strata"][key],
                                                        policy_id, c, forecast)
            require(row["report_group"] == group and number(row["missing_rate"]) == rate and
                    math.isclose(number(row["head_shift"]), shift, abs_tol=1e-12, rel_tol=0),
                    "OBSERVATION_MEASUREMENT_MISMATCH")
            groups.add(group)
            settlement = store.read(row["result_id"])
            require(settlement["event_id"] == eid and settlement["target"] == target and
                    settlement["status"] == "RECONCILED" and settlement["start_utc"] == row["start_utc"] and
                    settlement["available_utc"] == row["result_available_utc"], "SETTLEMENT_BINDING")
            record = {"event_id": eid, "procedure_id": procedure_id, "target": target, "forecast_id": row["forecast_id"],
                      "receipt_id": row["receipt_id"], "start_utc": row["start_utc"]}
            require(store.read(row["registration_id"]) == record, "REGISTRATION_BINDING")
            for subject, purpose, stamp, ref in (
                (row["registration_id"], "missingness_pregame_registration", row["registered_at_utc"], row["registration_witness_id"]),
                (row["result_id"], "missingness_result_reconciliation", row["result_available_utc"], row["result_witness_id"]),
            ):
                attestation = verifier.verify(store.read(ref), artifact_id=subject, purpose=purpose)
                require(attestation["signer_id"] == policy["witnesses"][purpose] and
                        _time(attestation["witnessed_at_utc"]) == _time(stamp), "WITNESS_BINDING")
            actual = settlement["actual"]
            forecasts = {"model": prediction}
            for name in ("incumbent", "independent"):
                ref = store.read(row[name + "_forecast_id"])
                comparator_key = "incumbent_id" if name == "incumbent" else "independent_comparator_id"
                require(ref["procedure_id"] == policy[comparator_key]
                        and ref["event_id"] == eid and ref["target"] == target
                        and _time(ref["frozen_utc"]) < _time(row["start_utc"]), "COMPARATOR_BINDING")
                forecasts[name] = ref["point"]
            for name, estimate in forecasts.items():
                score = number(row[name + "_loss"])
                require(score >= 0 and math.isclose(score, loss(c["metric"], estimate, actual),
                                                    abs_tol=1e-12, rel_tol=0), "LOSS_RECOMPUTATION_FAILED")
        expected = population["events_by_stratum"][key]
        require(isinstance(expected, list) and expected and set(expected) == ids and len(expected) == len(ids),
                "MONITORING_POPULATION_MISMATCH")
        require(groups == PERFORMANCE_GROUPS and type(c["minimum_events"]) is int and
                len(ids) >= c["minimum_events"] > 0, "INSUFFICIENT_FORWARD_COVERAGE")
        require(data["stratum"] == key and data["policy_id"] == policy_id, "FORWARD_STRATUM_BINDING")
        # Compare paired loss by report group with independently identified benchmarks.
        for group in PERFORMANCE_GROUPS:
            records = [r for r in data["events"] if r["report_group"] == group]
            for comparator in ("incumbent", "independent"):
                limit = number(c["max_mean_loss_delta"][comparator])
                delta = sum(number(r["model_loss"]) - number(r[comparator + "_loss"]) for r in records)/len(records)
                require(delta <= limit, "GROUP_PERFORMANCE_OUT_OF_BOUNDS")
    require(policy["independent_comparator_id"] not in (procedure_id, policy["incumbent_id"]),
            "INDEPENDENT_COMPARATOR_REQUIRED")
    for ref in ("independent_comparator_id", "incumbent_id"):
        store.read(policy[ref])
    checks = store.read(results["engineering_evidence_id"])
    require(checks["procedure_id"] == procedure_id and checks["policy_id"] == policy_id and
            set(checks["tests"]) == set(REQUIRED_TESTS), "TEST_COVERAGE")
    for name, ref in checks["tests"].items():
        evidence = store.read(ref)
        require(evidence["test"] == name and evidence["procedure_id"] == procedure_id and
                evidence["passed"] is True and type(evidence["cases"]) is int and evidence["cases"] > 0,
                "TEST_FAILED")
    return policy


def reviewed_policy(scope, at_utc, *, league=None):
    """Only protected-repository review pins are trusted. Indeterminate evidence fails closed."""
    if not isinstance(scope, dict):
        raise RegistryError("MISSINGNESS_REVIEW_REQUIRED")
    target = scope["target"]
    require(league is None or target["league"] == league, "RELEASE_LEAGUE_MISMATCH")
    anchors = json.loads((REVIEW_DIR / "approved.json").read_bytes())
    trusted = anchors["approved_review_ids"]
    require(scope["review_id"] in trusted, "NO_APPROVED_SCOPE_REVIEW")
    store = ArtifactStore(REVIEW_DIR / "objects")
    r = store.read(scope["review_id"])
    require(r["procedure_id"] == scope["procedure_id"] and r["target"] == target, "RELEASE_SCOPE_MISMATCH")
    require(r["author"] and r["reviewer"] and r["author"] != r["reviewer"], "INDEPENDENT_REVIEW_REQUIRED")
    require(_time(r["policy_frozen_utc"]) < _time(r["confirmation_start_utc"]) <
            _time(r["confirmation_end_utc"]) <= _time(r["reviewed_utc"]) <= _time(at_utc) <
            _time(r["expires_utc"]), "RELEASE_CHRONOLOGY")
    p = validate_study(store, r["policy_id"], r["results_id"], scope["procedure_id"], target,
                       _time(r["confirmation_start_utc"]), _time(r["confirmation_end_utc"]),
                       verifier=Ed25519Verifier({k: base64.b64decode(v, validate=True)
                                                for k,v in anchors["witness_keys"].items()}))
    require(p["model_id"] == scope["model_id"] and _time(p["calibration_end_utc"]) <= _time(r["policy_frozen_utc"]),
            "RELEASE_MODEL_OR_CUTOFF_MISMATCH")
    return p


def release_reason(scope, at_utc, *, league=None, receipt=None, forecast=None):
    try:
        policy = reviewed_policy(scope, at_utc, league=league)
        if receipt is not None:
            require(receipt["model_id"] == policy["model_id"] and
                    receipt["league"] == policy["target"]["league"], "CURRENT_MODEL_BINDING")
            measured = receipt["details"].get("monitored_strata")
            require(isinstance(measured, dict) and set(measured) == set(policy["strata"]),
                    "CURRENT_STRATA_UNMEASURED")
            for key, limit in policy["strata"].items():
                row = measured[key]
                monitored(row, scope_policy_id(scope), limit, forecast)
        return None
    except (OSError, TypeError, ValueError, KeyError, OverflowError) as exc:
        return str(exc) if isinstance(exc, RegistryError) else "MISSINGNESS_REVIEW_INVALID"



def scope_policy_id(scope):
    return ArtifactStore(REVIEW_DIR / "objects").read(scope["review_id"])["policy_id"]


def release_inventory(block, league, decision_utc):
    """Reconcile complete and refused rows against a separately witnessed schedule / model inventory."""
    try:
        data = ArtifactStore(REVIEW_DIR / "objects")
        witness = block["inventory_witness_id"]
        record_id = block["inventory_id"]
        inventory = data.read(record_id)
        anchors = json.loads((REVIEW_DIR / "approved.json").read_bytes())
        verifier = Ed25519Verifier({k: base64.b64decode(v, validate=True) for k,v in anchors["witness_keys"].items()})
        claim = verifier.verify(data.read(witness), artifact_id=record_id, purpose="missingness_release_inventory")
        require(claim["signer_id"] in anchors["inventory_witnesses"], "INVENTORY_ISSUER")
        require(inventory["league"] == league and inventory["state"] in ("VERIFIED_ABSENCE", "VERIFIED_OBSERVATION")
                and _time(inventory["cutoff_utc"]) <= _time(claim["witnessed_at_utc"]) <= _time(decision_utc)
                < _time(inventory["expires_utc"]), "INVENTORY_SCOPE_OR_CHRONOLOGY")
        expected = inventory["event_products"]
        actual = block["events"]
        require(isinstance(expected, dict) and isinstance(actual, list) and
                set(expected) == {e["event_key"] for e in actual} and len(expected) == len(actual) and
                (inventory["state"] == "VERIFIED_ABSENCE") == (not expected), "INVENTORY_EVENTS")
        for e in actual:
            if e["disposition"] == "COMPLETE":
                rows = e.get("model_outputs", [])
                wanted = expected[e["event_key"]]
                require(isinstance(wanted, list) and wanted and len(wanted) == len(rows) and
                        sorted(json.dumps(r, sort_keys=True) for r in wanted) ==
                        sorted(json.dumps({**{k: r[k] for k in ("model_id", "procedure_id", "target", "start_utc")},
                                           "forecast_sha256": content_digest(r["forecast"]),
                                           "receipt_sha256": r["missingness_audit"]["receipt_sha256"]},
                                          sort_keys=True) for r in rows), "INVENTORY_OUTPUTS")
                require(len({(r["procedure_id"], json.dumps(r["target"],sort_keys=True)) for r in wanted}) == len(wanted)
                        and all(_time(decision_utc) < _time(r["start_utc"]) for r in wanted),
                        "DUPLICATE_OR_POST_START_RELEASE")
            else:
                require(not e.get("model_outputs") and e.get("disposition") in
                        ("EXPLICITLY_BLOCKED","NOT_APPLICABLE","CANCELLED","POSTPONED","SOURCE_CONFLICT"),
                        "UNVERIFIED_EVENT_OUTPUT")
        return None
    except (OSError, TypeError, ValueError, KeyError, AttributeError, OverflowError) as exc:
        return str(exc) if isinstance(exc, RegistryError) else "MISSINGNESS_VERIFIED_INVENTORY_REQUIRED"
