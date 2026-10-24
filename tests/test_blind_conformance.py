"""Independent conformance experiments, authored without reading builder tests.

All data, signing keys, populations and claims here are synthetic. Test signing
keys confer no real validation authority. Five lifecycle symmetry cases are the
verifier's operational interpretation, not a quotation of unavailable user text.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pipelines.cards.research_selection import (
    seal_forecast, seal_quality_receipt, select_research, selector_config_artifact,
    selector_config_id, target_id, verify_selection_record,
)
from research.procedure_lineage import ProcedureLineage, FrozenWalkForwardPlan, create_procedure
from research.selection_evaluation import EvaluationError, evaluate_decisions, holm_adjust, paired_block_comparison, power_curve
from research.validation_registry import ArtifactStore, Ed25519Verifier, RegistryError, TrialLog, canonical_bytes, content_id


AT = "2026-10-20T18:00:00Z"
CONFIG = {"schema": "research-selector-config-v1", "objective": "unconditional_win",
          "threshold": .6, "require_quality_receipt": True}
FAMILY = {"league": "nfl", "product": "spread", "period": "full_game",
          "settlement_rules_id": "synthetic.standard.fullgame.v1"}


class SignedFixture:
    """Construct a positive control from public interfaces, not shipped fixtures."""
    def __init__(self, root):
        self.store = ArtifactStore(root)
        self.keys = {name: Ed25519PrivateKey.from_private_bytes(bytes([i])*32)
                     for i, name in enumerate(("fixture-author", "fixture-witness", "fixture-reviewer"), 11)}
        self.verifier = Ed25519Verifier({name: key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw) for name, key in self.keys.items()})
        self.candidate = create_procedure(self.store, parent_ids=[], owner="fixture-author",
            created_utc="2026-08-01T00:00:00Z", change_hypothesis="A frozen synthetic feature definition changes paired loss.",
            definition={"model_id": "synthetic.v1", "model_state_id": "1"*64,
                        "feature_semantics_id": "2"*64, "calibration_id": "3"*64})
        self.control = create_procedure(self.store, parent_ids=[], owner="fixture-author",
            created_utc="2026-07-01T00:00:00Z", change_hypothesis="Preserved synthetic control.",
            definition={"model_id": "synthetic.control.v1", "model_state_id": "4"*64})
        self.config_id = self.store.put(selector_config_artifact(CONFIG))
        self.population = self.store.put({"schema": "synthetic-population.v1", "event_ids": [str(i) for i in range(8)],
                                         "population_rule": "All eight preregistered events, including blocked opportunities."})
        basis = self.store.put({"schema": "validation-design-basis-v1", "purpose": "Synthetic conformance only",
                               "assumptions": "Independent generated blocks; no real model approval."})
        self.protocol = {"schema": "validation-protocol-v2", "author_id": "fixture-author",
            "candidate_id": self.candidate, "control_id": self.control, "population_id": self.population,
            "selector_config_id": self.config_id, "target": FAMILY, "objective": "unconditional_win",
            "primary_metric": "brier", "development_end_utc": "2026-08-30T00:00:00Z",
            "evaluation_start_utc": "2026-09-01T00:00:00Z", "evaluation_end_utc": "2026-09-30T00:00:00Z",
            "valid_for_days": 30, "criteria": {"minimum_events": 4, "minimum_slates": 2, "minimum_selected": 2,
                "minimum_total_coverage": .25, "maximum_total_coverage": .75,
                "maximum_primary_delta_ci_upper": 0, "minimum_power": .8},
            "criteria_justification": {k: {"rationale": "Synthetic fixture checks protocol-specific admission, not inference.",
                "basis_artifact_id": basis} for k in ("minimum_events", "minimum_slates", "minimum_selected", "minimum_total_coverage", "minimum_power")},
            "inspection_budget": 1,
            "power_assumptions": {"minimum_useful_improvement": .04, "paired_loss_sd": .03,
                "design_effect": 1.2, "alpha": .05, "total_trials": 1, "target_power": .8,
                "dependence": "Independent synthetic blocks"}}
        self.dataset = self.store.put({"schema": "synthetic-paired-dataset.v1", "evidence_scope": "CONFIRMATION"})
        self.evidence = {"candidate_id": self.candidate, "control_id": self.control,
            "population_id": self.population, "selector_config_id": self.config_id,
            "target": FAMILY, "objective": "unconditional_win", "primary_metric": "brier",
            "evaluation_start_utc": self.protocol["evaluation_start_utc"],
            "evaluation_end_utc": self.protocol["evaluation_end_utc"], "computed_at_utc": "2026-10-01T00:00:00Z",
            "n_events": 8, "n_slates": 4, "n_selected": 4, "total_coverage": .5,
            "primary_delta_ci_upper": -.01, "power_at_declared_effect": .9, "paired_dataset_id": self.dataset,
            "inspected_configurations": 1}
        self.seal()

    def receipt(self, artifact_id, purpose, when, signer):
        payload = {"artifact_id": artifact_id, "purpose": purpose, "witnessed_at_utc": when, "signer_id": signer}
        return self.store.put({"payload": payload, "signature_b64": base64.b64encode(
            self.keys[signer].sign(canonical_bytes(payload))).decode()})

    def seal(self):
        from research.validation_registry import ValidationRegistry, LifecycleLog
        protocol_id = self.store.put(self.protocol)
        evidence_id = self.store.put({**self.evidence, "protocol_id": protocol_id})
        review = self.store.put({"protocol_id": protocol_id, "evidence_id": evidence_id,
            "authorship_receipt_id": self.receipt(protocol_id, "protocol_authorship", "2026-08-30T01:00:00Z", "fixture-author"),
            "registration_receipt_id": self.receipt(protocol_id, "preregistration", "2026-08-30T02:00:00Z", "fixture-witness")})
        self.review_receipt = self.receipt(review, "validation_review", "2026-10-02T00:00:00Z", "fixture-reviewer")
        self.record_id = self.store.put({"review_payload_id": review, "review_receipt_id": self.review_receipt})
        self.trial_log = TrialLog(self.store.root / (protocol_id+".trials.jsonl"),
                                 clock=lambda: datetime(2026, 9, 1, tzinfo=timezone.utc))
        tip = self.trial_log.append({"kind": "INSPECTED", "trial_id": protocol_id,
            "family_id": "synthetic-family", "procedure_id": self.protocol["candidate_id"], "configuration_id": self.config_id})
        self.lifecycle = LifecycleLog(self.store, self.store.root / (protocol_id+".lifecycle.jsonl"), self.verifier,
                                     clock=lambda: datetime(2026, 10, 2, 2, tzinfo=timezone.utc))
        event = self.store.put({"schema": "procedure-lifecycle-event-v1", "action": "QUALIFY",
            "procedure_id": self.protocol["candidate_id"], "selector_config_id": self.config_id, "target": FAMILY,
            "created_utc": "2026-10-02T00:30:00Z", "reason": "Synthetic positive lifecycle fixture", "record_id": self.record_id})
        self.lifecycle_receipt = self.receipt(event, "procedure_lifecycle", "2026-10-02T01:00:00Z", "fixture-reviewer")
        lifecycle_tip = self.lifecycle.append(event, self.lifecycle_receipt)
        self.registry_args = {"trial_log": self.trial_log, "trial_tip": tip["record_id"],
                              "lifecycle_log": self.lifecycle, "lifecycle_tip": lifecycle_tip["record_id"]}
        self.registry = ValidationRegistry(self.store, [self.record_id], self.verifier, **self.registry_args)

    def forecast(self, probability=.62, *, procedure=None):
        return seal_forecast({"schema": "research-forecast-v1", "procedure_id": procedure or self.candidate,
            "input_snapshot_sha256": "5"*64,
            "target": {**FAMILY, "event_id": "synthetic:test", "side": "home", "line": -3,
                       "starts_at_utc": "2026-10-20T20:00:00Z"},
            "probabilities": {"win": probability, "loss": 1-probability-.12, "push": .08, "void": .04},
            "forecast_cutoff_utc": "2026-10-20T17:00:00Z", "forecast_created_at_utc": "2026-10-20T17:01:00Z"})

    def decide(self, forecast=None, **kwargs):
        forecast = forecast or self.forecast()
        quality = seal_quality_receipt({"forecast_id": forecast["forecast_id"],
            "input_snapshot_sha256": forecast["input_snapshot_sha256"], "created_at_utc": "2026-10-20T17:02:00Z",
            "blocking_reasons": [], "review_notes": []})
        return select_research(forecast, CONFIG, decision_at_utc=AT, registry=kwargs.pop("registry", self.registry),
                               quality_receipt=quality, **kwargs)


@pytest.fixture
def signed(tmp_path):
    return SignedFixture(tmp_path / "artifacts")


def test_positive_twin_and_invalid_exact_identity(signed):
    valid = signed.decide()
    assert valid["decision_class"] == "SHADOW_SELECTED"
    assert valid["selection_probability"] == .62
    invalid_id = signed.store.put({**signed.store.read(signed.candidate),
                                  "definition": {"model_id": "synthetic.changed-feature-or-fit"}})
    invalid = signed.decide(signed.forecast(procedure=invalid_id))
    assert invalid["decision_class"] == "BLOCKED"
    assert invalid["raw_probability"] == .62 and invalid["selection_probability"] is None
    assert valid["publication_allowed"] is False and valid["wagering_status"] == "OFF"


@pytest.mark.parametrize("key,value", [("league", "nhl"), ("product", "winner"),
    ("period", "first_half"), ("settlement_rules_id", "different-refund-rule")])
def test_target_specific_validation_cannot_cross_families(signed, key, value):
    family = {**FAMILY, key: value}
    verdict = signed.registry.assess(signed.candidate, family, AT, signed.config_id)
    assert verdict.eligible is False


def test_missing_validation_keeps_raw_artifact_and_no_pick(signed):
    frozen = signed.forecast()
    before = canonical_bytes(frozen)
    decision = signed.decide(frozen, registry=None)
    assert canonical_bytes(frozen) == before
    assert decision["raw_probability"] == .62
    assert decision["selection_probability"] is None
    assert decision["selection_decision"] == "NO_PICK" and decision["decision_class"] == "BLOCKED"


def test_revoked_qualification_blocks_but_preserves_replay_and_raw(signed):
    from research.validation_registry import ValidationRegistry
    frozen, old_decision = signed.forecast(), signed.decide()
    before = canonical_bytes(frozen), canonical_bytes(old_decision)
    payload = signed.store.put({"record_id": signed.record_id, "reason": "Synthetic retraction"})
    revocation = signed.store.put({"revocation_payload_id": payload, "revocation_receipt_id": signed.receipt(
        payload, "validation_revocation", "2026-10-19T00:00:00Z", "fixture-reviewer")})
    registry = ValidationRegistry(signed.store, [signed.record_id], signed.verifier, revocation_ids=[revocation], **signed.registry_args)
    result = signed.decide(frozen, registry=registry)
    assert result["decision_class"] == "BLOCKED" and "VALIDATION_REVOKED" in result["blocking_reasons"]
    assert result["raw_probability"] == .62 and result["selection_probability"] is None
    assert (canonical_bytes(frozen), canonical_bytes(old_decision)) == before
    verify_selection_record(old_decision)
    assert registry.assess(signed.candidate, FAMILY, "2026-10-18T00:00:00Z", signed.config_id).eligible


def test_expired_and_unexpired_symmetry(signed):
    assert signed.registry.assess(signed.candidate, FAMILY, "2026-10-31T23:59:59Z", signed.config_id).eligible
    result = signed.registry.assess(signed.candidate, FAMILY, "2026-11-01T00:00:01Z", signed.config_id)
    assert not result.eligible and "VALIDATION_EXPIRED" in result.reasons


def test_child_inherits_defects_but_not_qualification(signed, tmp_path):
    defect = signed.store.put({"schema": "procedure-defect-v1", "owner": "fixture-author",
        "created_utc": "2026-07-01T00:00:00Z", "description": "Synthetic ancestral bug"})
    parent = create_procedure(signed.store, parent_ids=[], owner="fixture-author", created_utc="2026-08-01T00:00:00Z",
        change_hypothesis="Attach known defect", definition={"model_id": "parent"}, defect_ids=[defect])
    child = create_procedure(signed.store, parent_ids=[signed.candidate, parent], owner="fixture-author",
        created_utc="2026-10-10T00:00:00Z", change_hypothesis="Synthetic descendant", definition={"model_id": "child"})
    lineage = ProcedureLineage(signed.store).resolve(child)
    assert {parent, signed.candidate, child} <= set(lineage.ancestor_ids)
    assert defect in lineage.defect_ids
    assert signed.decide(signed.forecast(procedure=child))["decision_class"] == "BLOCKED"
    journal = TrialLog(tmp_path / "trials.jsonl")
    journal.append({"kind": "INSPECTED", "trial_id": "parent", "family_id": parent, "configuration_id": signed.config_id})
    journal.append({"kind": "INSPECTED", "trial_id": "child", "family_id": child, "configuration_id": signed.config_id})
    assert journal.inspected_count() == 2


def test_bad_signature_fails_without_erasing_frozen_replay(signed):
    from research.validation_registry import ValidationRegistry
    original = signed.decide()
    receipt = signed.store.read(signed.review_receipt)
    receipt["signature_b64"] = base64.b64encode(bytes(64)).decode()
    bad = signed.store.put(receipt)
    record = signed.store.read(signed.record_id)
    record["review_receipt_id"] = bad
    registry = ValidationRegistry(signed.store, [signed.store.put(record)], signed.verifier, **signed.registry_args)
    result = signed.decide(registry=registry)
    assert result["decision_class"] == "BLOCKED" and result["raw_probability"] == .62
    assert "INVALID_ATTESTATION_SIGNATURE" in result["blocking_reasons"]
    verify_selection_record(original)


@pytest.mark.parametrize("field", ["owner", "created_utc", "change_hypothesis", "parent_ids"])
def test_registry_rejects_unattributed_or_unresolved_procedure(signed, field):
    node = signed.store.read(signed.candidate)
    del node[field]
    malformed = signed.store.put(node)
    signed.protocol["candidate_id"] = signed.evidence["candidate_id"] = malformed
    try:
        signed.seal()
    except RegistryError:
        return  # Malformed lineage is rejected before a lifecycle can be signed.
    result = signed.registry.assess(malformed, FAMILY, AT, signed.config_id)
    assert not result.eligible, f"Registry qualified a procedure lacking {field}"


@pytest.mark.parametrize("field", ["criteria_justification", "power_assumptions"])
def test_registry_demands_protocol_justification_and_declared_power(signed, field):
    del signed.protocol[field]
    signed.seal()
    result = signed.registry.assess(signed.candidate, FAMILY, AT, signed.config_id)
    assert not result.eligible, f"Registry accepted absent {field}"


@pytest.mark.parametrize("field", ["model_id", "model_state_id", "feature_semantics_id", "calibration_id"])
def test_registry_requires_exact_model_feature_and_calibration_identity(signed, field):
    node = signed.store.read(signed.candidate)
    del node["definition"][field]
    incomplete = signed.store.put(node)
    signed.protocol["candidate_id"] = signed.evidence["candidate_id"] = incomplete
    try:
        signed.seal()
    except RegistryError:
        return
    result = signed.registry.assess(incomplete, FAMILY, AT, signed.config_id)
    assert not result.eligible, f"Candidate qualified without exact {field}"


def test_three_classes_threshold_tie_and_prices_diagnostic_only(signed):
    above, equal, below = [signed.decide(signed.forecast(p)) for p in (.61, .60, .59)]
    assert [r["decision_class"] for r in (above, equal, below)] == ["SHADOW_SELECTED", "SHADOW_SELECTED", "ELIGIBLE_NOT_SELECTED"]
    forecast = signed.forecast()
    outcomes = []
    for odds in (1.5, 2.0, 4.0):
        outcomes.append(signed.decide(forecast, price={"target_id": target_id(forecast["target"]),
            "decimal_odds": odds, "quoted_at_utc": "2026-10-20T17:59:00Z"}))
    assert len({r["decision_id"] for r in outcomes}) == 1
    assert [r["estimated_value"] for r in outcomes] == pytest.approx([.05, .36, 1.6])
    assert outcomes[0]["price_break_even"]["probability_basis"] == "conditional_decisive"


def evaluation_rows(outcomes=("WIN", "LOSS", "PUSH", "VOID", "LIVE", "MISSING")):
    rows = [{"event_id": f"e{i}", "target_id": f"t{i}", "slate_id": f"s{i//2}",
        "procedure_id": "1"*64, "selector_config_id": "2"*64, "control_procedure_id": "3"*64,
        "target_family_id": "4"*64, "decision_class": "SHADOW_SELECTED", "outcome": outcome,
        "raw_probability": .6, "control_probability": .5, "control_target_id": f"t{i}",
        "control_predicted_outcome": "WIN"} for i, outcome in enumerate(outcomes)]
    population = [{key: row[key] for key in ("event_id", "target_id", "slate_id")} for row in rows]
    return rows, population


def test_unconditional_and_decisive_denominators_reconcile():
    rows, population = evaluation_rows()
    report = evaluate_decisions(rows, population=population, evidence_scope="SHADOW", bootstrap_samples=40)
    settlement = report["selected_settlement"]
    expected = {"wins": 1, "losses": 1, "pushes": 1, "voids": 1, "n_settled": 4,
        "unconditional_win_accuracy": .25, "non_win_risk": .75, "decisive_only_accuracy_diagnostic": .5}
    assert {key: settlement[key] for key in expected} == expected
    assert report["selected_unsettled"] == 2
    assert report["selected_forecast_scores"]["n"] == 4
    assert report["selected_forecast_scores"]["brier"] == pytest.approx((.16+3*.36)/4)
    assert report["selected_same_event_control"]["n"] == 4


def test_empty_selection_risk_is_undefined_and_abstentions_are_not_wins():
    rows, population = evaluation_rows(("WIN", "WIN", "VOID"))
    for row in rows:
        row["decision_class"] = "ELIGIBLE_NOT_SELECTED"
    rows[0]["decision_class"] = "BLOCKED"
    report = evaluate_decisions(rows, population=population, evidence_scope="SHADOW", bootstrap_samples=20)
    assert report["n_events"] == 3 and report["n_blocked"] == 1 and report["total_coverage"] == 0
    assert report["selected_settlement"]["wins"] == 0
    assert report["selected_settlement"]["non_win_risk"] is None
    assert report["full_slate_raw_forecast_scores"]["n"] == 3


def test_population_omission_and_wrong_control_target_rejected():
    rows, population = evaluation_rows()
    with pytest.raises(EvaluationError, match="missing population"):
        evaluate_decisions(rows[:-1], population=population, evidence_scope="SHADOW")
    rows[0]["control_target_id"] = "unpaired-event-target"
    with pytest.raises(EvaluationError, match="control target mismatch"):
        evaluate_decisions(rows, population=population, evidence_scope="SHADOW")


def test_curve_includes_entire_ties_and_is_monotone_in_coverage():
    rows, population = evaluation_rows(("WIN", "LOSS", "VOID", "WIN"))
    for row, probability in zip(rows, (.9, .7, .7, .55)):
        row["raw_probability"] = probability
    curve = evaluate_decisions(rows, population=population, evidence_scope="SHADOW", bootstrap_samples=20)["risk_coverage_diagnostic_only"]
    assert [r["threshold"] for r in curve] == [.9, .7, .55]
    assert [r["n_selected"] for r in curve] == [1, 3, 4]
    assert [r["total_coverage"] for r in curve] == [.25, .75, 1]


def test_paired_blocks_multiplicity_and_power_contracts():
    one = [{"event_id": str(i), "block_id": "same-night", "candidate_loss": .1, "control_loss": .2} for i in range(6)]
    report = paired_block_comparison(one, samples=20)
    assert report["status"] == "INSUFFICIENT_BLOCKS" and report["ci_upper"] is None
    with pytest.raises(EvaluationError, match="explicit inspected"):
        holm_adjust({"shown": .01})
    assert holm_adjust({"shown": .01}, total_trials=40)["tests"]["shown"]["adjusted_p_value"] == .4
    power = power_curve([10, 100], minimum_useful_improvement=.02, paired_loss_sd=.1,
                        design_effect=2, alpha=.05, total_trials=10, target_power=.8)
    assert power["curve"][1]["power"] > power["curve"][0]["power"]
    assert power["planning_alpha"] == .005 and power["curve"][0]["effective_sample_size"] == 5


def test_frozen_walk_forward_plan_admits_changing_states_only_when_bound(signed):
    rows, population = evaluation_rows(("WIN", "LOSS", "WIN", "VOID"))
    for i, row in enumerate(rows):
        row.update(procedure_id=content_id({"procedure": i}), fitted_state_id=content_id({"fit": i}),
            control_fitted_state_id="6"*64, training_data_cutoff_utc="2026-09-01T00:00:00Z",
            forecast_created_at_utc="2026-10-19T15:00:00Z", decision_at_utc="2026-10-20T15:00:00Z",
            starts_at_utc="2026-10-20T20:00:00Z", control_training_data_cutoff_utc="2026-09-01T00:00:00Z",
            control_forecast_created_at_utc="2026-10-19T15:00:00Z")
    with pytest.raises(EvaluationError, match="mixed"):
        evaluate_decisions(rows, population=population, evidence_scope="CONFIRMATION")
    fields = ("event_id", "procedure_id", "selector_config_id", "fitted_state_id", "control_procedure_id", "control_fitted_state_id")
    plan_id = signed.store.put({"schema": "walk-forward-plan-v1", "owner": "fixture-author",
        "change_hypothesis": "Explicit ex-ante assignment permits different fitted states.",
        "created_utc": "2026-10-01T00:00:00Z", "evaluation_start_utc": "2026-10-10T00:00:00Z",
        "evaluation_end_utc": "2026-10-31T00:00:00Z", "target_family_id": "4"*64,
        "population_id": content_id(population), "assignments": [{k: row[k] for k in fields} for row in rows]})
    receipt = signed.receipt(plan_id, "walk_forward_registration", "2026-10-02T00:00:00Z", "fixture-witness")
    plan = FrozenWalkForwardPlan(signed.store, plan_id, receipt, signed.verifier)
    report = evaluate_decisions(rows, population=population, evidence_scope="CONFIRMATION", bootstrap_samples=20, walk_forward_plan=plan)
    assert report["n_events"] == 4 and report["procedure_id"] is None
    assert report["walk_forward_plan"]["plan_id"] == plan_id
    bad = copy.deepcopy(rows)
    bad[0]["fitted_state_id"] = "f"*64
    with pytest.raises(EvaluationError, match="WALK_FORWARD_IDENTITY_MISMATCH"):
        evaluate_decisions(bad, population=population, evidence_scope="CONFIRMATION", walk_forward_plan=plan)


def later_refit_fixture(signed, mutation=None):
    """Freeze a recipe first, then compute and witness two different simple fits.

    Synthetic fold 1 uses observations [1,3] (mean 2); fold 2 adds [5,7]
    (mean 4). The control recipe always returns zero. This computes actual tiny
    fitted states after plan construction; it is not sports-accuracy evidence.
    """
    rows, population = evaluation_rows(("WIN", "LOSS", "WIN", "VOID"))
    recipes = {}
    for role in ("candidate", "control"):
        material = {key: signed.store.put({"kind": key, "role": role, "declaration": declaration})
            for key, declaration in {"code_id": "mean(values)" if role == "candidate" else "0",
                "hyperparameters_id": {}, "feature_definition_id": "synthetic_values",
                "calibration_id": "untransformed", "training_rule_id": "expanding_history_until_fold_end"}.items()}
        recipes[role] = {**material, "id": signed.store.put({"schema": "frozen-fit-recipe-v1", **material})}
    folds = [{"fold_id": f"fold{i}", "train_start_utc": "2026-09-01T00:00:00Z",
        "train_end_utc": f"2026-10-{9+2*i:02d}T00:00:00Z", "evaluation_start_utc": f"2026-10-{10+2*i:02d}T00:00:00Z",
        "evaluation_end_utc": f"2026-10-{11+2*i:02d}T00:00:00Z", "event_ids": [f"e{2*i}", f"e{2*i+1}"]} for i in range(2)]
    plan_id = signed.store.put({"schema": "walk-forward-refit-policy-v2", "owner": "fixture-author",
        "change_hypothesis": "Later expanding means under one predeclared recipe", "created_utc": "2026-10-01T00:00:00Z",
        "evaluation_start_utc": "2026-10-10T00:00:00Z", "evaluation_end_utc": "2026-10-14T00:00:00Z",
        "population_id": content_id(population), "target_family_id": "4"*64, "selector_config_id": signed.config_id,
        "recipe_id": recipes["candidate"]["id"], "control_recipe_id": recipes["control"]["id"],
        "fit_authority_id": "fixture-reviewer", "folds": folds})
    registration = signed.receipt(plan_id, "walk_forward_registration", "2026-10-02T00:00:00Z", "fixture-witness")
    envelopes, realized_states = [], []
    for i, fold in enumerate(folds):
        day = 9+2*i
        values = [1, 3] if i == 0 else [1, 3, 5, 7]
        for role in ("candidate", "control"):
            recipe = recipes[role]
            created, witnessed = f"2026-10-{day:02d}T12:00:00Z", f"2026-10-{day:02d}T13:00:00Z"
            availability = f"2026-10-{day:02d}T01:00:00Z" if mutation == "future_data" and i == 0 and role == "candidate" else fold["train_end_utc"]
            dataset = signed.store.put({"schema": "training-dataset-receipt-v1", "data_sha256": content_id(values), "values": values,
                "window_start_utc": fold["train_start_utc"], "window_end_utc": fold["train_end_utc"],
                "max_available_at_utc": availability, "max_event_end_utc": fold["train_end_utc"],
                "created_utc": f"2026-10-{day:02d}T02:00:00Z"})
            coefficients = {"intercept": float(np.mean(values)) if role == "candidate" else 0.}
            state = signed.store.put({"schema": "fitted-model-state-v1", "state_sha256": content_id(coefficients),
                "coefficients": coefficients, "recipe_id": recipe["id"], "training_dataset_id": dataset, "created_utc": created})
            procedure = create_procedure(signed.store, parent_ids=[signed.candidate], owner="fixture-author", created_utc=created,
                change_hypothesis="Execute the previously frozen recipe for this fold", definition={"model_id": "synthetic.mean."+role,
                    "model_state_id": state, "feature_semantics_id": recipe["feature_definition_id"], "calibration_id": recipe["calibration_id"],
                    "recipe_id": recipe["id"], "fitted_state_id": state, "training_dataset_id": dataset})
            declared_recipe = recipes["control"]["id"] if mutation == "wrong_recipe" and i == 0 and role == "candidate" else recipe["id"]
            fit = signed.store.put({"schema": "walk-forward-fit-v1", "plan_id": plan_id, "role": role, "fold_id": fold["fold_id"],
                "recipe_id": declared_recipe, "created_utc": created, "training_dataset_id": dataset,
                "fitted_state_id": state, "procedure_id": procedure})
            envelopes.append(signed.store.put({"fit_payload_id": fit,
                "fit_receipt_id": signed.receipt(fit, "walk_forward_fit", witnessed, "fixture-reviewer")}))
            if role == "candidate":
                realized_states.append(state)
            for row in rows[2*i:2*i+2]:
                prefix = "" if role == "candidate" else "control_"
                row.update({prefix+"procedure_id": procedure, prefix+"fitted_state_id": state,
                            prefix+"forecast_created_at_utc": f"2026-10-{day+1:02d}T09:00:00Z",
                            prefix+"training_data_cutoff_utc": fold["train_end_utc"]})
                row.update(selector_config_id=signed.config_id, decision_at_utc=f"2026-10-{day+1:02d}T10:00:00Z",
                           starts_at_utc=f"2026-10-{day+1:02d}T20:00:00Z")
    plan = FrozenWalkForwardPlan(signed.store, plan_id, registration, signed.verifier, realized_fit_receipt_ids=envelopes)
    return rows, population, plan, realized_states


def test_prefrozen_recipe_allows_realized_fits_created_after_registration(signed):
    rows, population, plan, states = later_refit_fixture(signed)
    assert len(set(states)) == 2
    assert [signed.store.read(state)["coefficients"]["intercept"] for state in states] == [2, 4]
    report = evaluate_decisions(rows, population=population, evidence_scope="CONFIRMATION", bootstrap_samples=20, walk_forward_plan=plan)
    assert report["walk_forward_plan"]["schema"] == "walk-forward-refit-policy-v2"
    assert report["walk_forward_plan"]["n_folds"] == 2 and report["n_events"] == 4
    assert report["procedure_id"] is None and len(report["identity_bindings"]) == 2
    assert report["walk_forward_plan"]["fit_execution_independently_verified"] is False


@pytest.mark.parametrize("mutation,error", [("wrong_recipe", "REFIT_WRONG_FROZEN_RECIPE"), ("future_data", "REFIT_TRAINING_DATA_LEAKAGE")])
def test_refit_policy_rejects_wrong_recipe_or_future_availability(signed, mutation, error):
    rows, population, plan, _ = later_refit_fixture(signed, mutation)
    with pytest.raises(EvaluationError, match=error):
        evaluate_decisions(rows, population=population, evidence_scope="CONFIRMATION", walk_forward_plan=plan)


def rest_inputs(previous_home, previous_away):
    event = {"event_id": "NHL:oracle", "home_id": "H", "away_id": "A", "neutral_site": False,
             "start_time_utc": "2026-10-24T01:00:00Z"}
    state = {"H": {"n": 10, "for": 5, "against": 3, "last": {"must_not": "be read"}},
             "A": {"n": 30, "for": 2, "against": 4, "last": {"must_not": "be read"}}}
    capture = "2026-10-23T23:00:00Z"
    records = [{"event_id": "prior-"+team, "home_id": "other-"+team, "away_id": team,
        "start_time_utc": previous, "status": "final", "observed_at_utc": capture, "source_sha256": "a"*64}
        for team, previous in (("H", previous_home), ("A", previous_away))]
    coverage = [{"team_id": team, "from_utc": "2026-09-01T00:00:00Z", "through_utc": capture,
        "observed_at_utc": capture, "source_sha256": "a"*64, "complete": True, "population": "ALL_PLAYED_GAMES"}
        for team in ("H", "A")]
    return state, event, records, coverage


@pytest.mark.parametrize("adapter_name", ["training", "serving"])
@pytest.mark.parametrize("home,away,expected", [
    ("2026-10-22T23:00:00Z", "2026-10-20T01:00:00Z", (13/12, 4)),
    ("2026-10-01T01:00:00Z", "2026-10-17T01:00:00Z", (14, 7)),
    ("2026-10-21T19:00:00-07:00", "2026-10-20T23:00:00+09:00", (47/24, 83/24)),
])
def test_each_rest_adapter_against_hand_computed_golden_vectors(adapter_name, home, away, expected):
    from models.current.freshness import serving_candidate_features, REST_SEMANTICS
    from scripts.prepare_initial_baselines import operational_rest_training_example
    adapter = {"training": operational_rest_training_example, "serving": serving_candidate_features}[adapter_name]
    state, event, records, coverage = rest_inputs(home, away)
    result = adapter(state, event, 3, records, cutoff_utc="2026-10-24T00:00:00Z", coverage=coverage)
    assert result["candidate_ready"] and result["feature_semantics_id"] == REST_SEMANTICS
    # n/(n+10) shrinkage: H weight 1/2; A weight 3/4. Exact independent oracle.
    assert result["features"] == pytest.approx({"home_for": 4, "home_against": 3, "away_for": 2.25,
        "away_against": 3.75, "home_rest": expected[0], "away_rest": expected[1],
        "home_cold": 0, "away_cold": 0, "neutral": 0})
    assert result["proxy_columns_used"] == [] and result["action_authority"] is False


@pytest.mark.parametrize("adapter_name", ["training", "serving"])
def test_each_rest_adapter_responds_to_actual_schedule_perturbation(adapter_name):
    from models.current.freshness import serving_candidate_features
    from scripts.prepare_initial_baselines import operational_rest_training_example
    adapter = {"training": operational_rest_training_example, "serving": serving_candidate_features}[adapter_name]
    state, event, records, coverage = rest_inputs("2026-10-20T01:00:00Z", "2026-10-17T01:00:00Z")
    old = adapter(state, event, 3, records, cutoff_utc="2026-10-24T00:00:00Z", coverage=coverage)
    records.append({**records[0], "event_id": "closer-home", "start_time_utc": "2026-10-23T00:00:00Z"})
    new = adapter(state, event, 3, records, cutoff_utc="2026-10-24T00:00:00Z", coverage=coverage)
    assert old["features"]["home_rest"] == 4
    assert new["features"]["home_rest"] == pytest.approx(25/24)
    assert new["rest_receipt"]["per_side"]["home"]["previous_event_id"] == "closer-home"
    assert {k: v for k, v in old["features"].items() if k != "home_rest"} == {k: v for k, v in new["features"].items() if k != "home_rest"}


def test_rest_challenger_does_not_redefine_legacy_feature_or_mutate_state():
    from models.current.baseline import feature
    from models.current.freshness import rebuild_candidate_features
    state, event, records, coverage = rest_inputs("2026-10-22T23:00:00Z", "2026-10-20T01:00:00Z")
    for value in state.values():
        value["last"] = "2026-10-01T01:00:00Z"
    original = canonical_bytes(state)
    legacy = feature(state, event, 3)
    rebuilt = rebuild_candidate_features(state, event, 3, records, cutoff_utc="2026-10-24T00:00:00Z", coverage=coverage)
    assert legacy["home_rest"] == legacy["away_rest"] == 14
    assert rebuilt["legacy_features"] == legacy
    assert rebuilt["candidate_features"]["home_rest"] == pytest.approx(13/12)
    assert rebuilt["candidate_features"]["away_rest"] == 4
    assert rebuilt["adoption_status"] == "REFIT_AND_CHRONOLOGICAL_EVALUATION_REQUIRED"
    assert canonical_bytes(state) == original and "prediction" not in rebuilt


def synthetic_nba_package(league="nba"):
    from models.current.baseline import FEATURES
    event = {"event_id": league.upper()+":numeric-oracle", "home_id": "H", "away_id": "A", "home_team": "Home", "away_team": "Away",
        "neutral_site": False, "start_time_utc": "2026-10-24T01:00:00Z", "slate_date": "2026-10-23"}
    state = {team: {"n": 10, "for": 100, "against": 95, "last": "2026-10-20T00:00:00Z"} for team in ("H", "A")}
    def head(kind, intercept):
        return {"kind": kind, "impute": [0]*9, "mean": [0]*9, "scale": [1]*9,
                "coefficient": [.001]*9, "intercept": intercept}
    fitted = {"winner": head("logistic", -.3), "margin": head("linear", 3), "total": head("linear", 190)}
    if league == "mls":
        fitted = {"home_goals": head("poisson", .4), "away_goals": head("poisson", .1)}
    package = {"schema": "sports.current_research_package.v1", "league": league, "model_id": league+".initial_causal_score.research.v1",
        "events": [event], "team_state": state, "fitted_model": fitted, "prior": 100, "feature_names": FEATURES,
        "source_fetches": [{"fetched_at_utc": "2026-10-23T22:00:00Z"}], "captured_at_utc": "2026-10-23T22:00:00Z",
        "training_cutoff_utc": "2026-10-01T00:00:00Z", "data_grade": "SYNTHETIC", "limitations": [], "model_lineage": [],
        "action_authority": False}
    package["model_sha256"] = content_id({"model": fitted, "state": state, "prior": 100})
    return event, package


@pytest.mark.parametrize("league", ["nba", "nhl", "mls"])
def test_real_initial_adapters_v2_price_perturbation_and_legacy_replay(tmp_path, monkeypatch, league):
    import importlib
    adapter = importlib.import_module("pipelines.cards.adapters."+league)
    from pipelines.cards.semantic_identity import forecast_with_identity, SEMANTIC, LEGACY
    event, package = synthetic_nba_package(league)
    monkeypatch.setenv("SPORTS_INITIAL_BASELINES", "1")
    outputs = []
    for i, odds in enumerate((1.2, 8.0, 1.2)):
        p = copy.deepcopy(package)
        e = p["events"][0]
        e["market_moneyline_home"] = odds
        p["presentation_metadata"] = {"odds": odds, "label": str(i)}
        context = {"package": p, "package_sha256": content_id(p), "cutoff": "2026-10-23T23:00:00Z"}
        monkeypatch.setenv("SPORTS_RESEARCH_DRAW_OUTPUT", str(tmp_path / f"run-{i}"))
        outputs.append(forecast_with_identity(adapter, e, context, 257, semantics=SEMANTIC))
    assert len({r["numerical_identity"]["identity_sha256"] for r in outputs}) == 1
    assert len({content_id(r["simulation"]["draw_sha256"]) for r in outputs}) == 1
    assert len({r["model_p"] for r in outputs}) == len({r["sim_p"] for r in outputs}) == 1
    assert len({r["diagnostics"]["identity_provenance"]["legacy_package_sha256"] for r in outputs}) == 3
    context = {"package": package, "package_sha256": content_id(package), "cutoff": "2026-10-23T23:00:00Z"}
    monkeypatch.setenv("SPORTS_RESEARCH_DRAW_OUTPUT", str(tmp_path / "legacy-a"))
    direct = adapter.forecast_event(event, context, 257)
    monkeypatch.setenv("SPORTS_RESEARCH_DRAW_OUTPUT", str(tmp_path / "legacy-b"))
    replay = forecast_with_identity(adapter, event, context, 257, semantics=LEGACY)
    assert direct["model_p"] == replay["model_p"] and direct["sim_p"] == replay["sim_p"]
    for member in Path(direct["simulation"]["draw_directory"]).glob("*.npy"):
        assert np.array_equal(np.load(member), np.load(Path(replay["simulation"]["draw_directory"])/member.name))


@pytest.mark.parametrize("league", ["cfb", "wnba", "mlb"])
def test_remaining_current_adapters_numeric_price_firewall(tmp_path, monkeypatch, league):
    import importlib
    from pipelines.cards.semantic_identity import forecast_with_identity, SEMANTIC
    event, package = synthetic_nba_package()
    event["event_id"] = league.upper()+":independent-numeric-oracle"
    package["league"] = league
    if league == "cfb":
        from models.current.cfb import feature_row
        event.update(season=2026, week=8, division_scope="FBS_VS_FBS", conference_game=True)
        state = {"elo": {"Home": 1560, "Away": 1490}, "last_season": {"Home": 2026, "Away": 2026},
                 "last": {"Home": "2026-10-17T01:00:00Z", "Away": "2026-10-16T01:00:00Z"},
                 "ewpf": {"Home": 29, "Away": 24}, "ewpa": {"Home": 22, "Away": 28}, "ewm": {"Home": 7, "Away": -4}}
        parameters = {"regress": .75, "hfa": 55}
        names = list(feature_row(state, event, parameters))
        fitted = {kind: {"kind": "logistic" if kind == "winner" else "linear", "impute": [0]*len(names),
            "mean": [0]*len(names), "scale": [1]*len(names), "coefficient": [.001]*len(names), "intercept": .2}
            for kind in ("winner", "margin")}
        package.update(model_id="cfb.fbs.elo_form_logit_ridge.v1_0.shadow", team_state=state,
                       feature_names=names, parameters=parameters, fitted_model=fitted)
        package["model_sha256"] = content_id({"model": fitted, "state": state, "parameters": parameters})
    elif league == "wnba":
        event.update(season=2026, season_type=2)
        values = {"g": 20, "pts": 1600, "opts": 1500, "fgm": 600, "fga": 1400, "fg3m": 200,
                  "fta": 250, "oreb": 180, "tov": 240, "ofga": 1400, "ooreb": 180, "otov": 240,
                  "ofta": 250, "last": "2026-10-20"}
        state = [{"season": 2026, "team": name, "values": copy.deepcopy(values)} for name in ("Home", "Away")]
        fitted = {"mu": [0]*6, "sd": [1]*6, "blog": [.2]+[.01]*7, "bmar": [3]+[.1]*7,
                  "tmu": [0]*3, "tsd": [1]*3, "btot": [145]+[.1]*3}
        package.update(model_id="wnba.rs.ff7_logit_ridge.v1_0.shadow", team_state=state,
                       fitted_model=fitted, league_state=[16000, 100, 8000], consumed_game_ids=[])
        package["model_sha256"] = content_id({"model": fitted, "state": state, "league": package["league_state"]})
    else:
        event.update(home_pitcher_id="10", away_pitcher_id="11", park_factor=1.05)
        state = {"Home": {"rf": 4.6, "ra": 4.1}, "Away": {"rf": 4.1, "ra": 4.5}}
        starters = {"10": {"era": 3.6, "gs": 25, "k": 24, "bb": 8}, "11": {"era": 4.2, "gs": 23, "k": 20, "bb": 9}}
        package.update(model_id="mlb.v13.current_input.research.v1", team_state=state, starter_state=starters)
        package["model_sha256"] = content_id({"teams": state, "starters": starters})
    adapter = importlib.import_module("pipelines.cards.adapters."+league)
    children = []
    for i, price in enumerate((1.1, 10.0)):
        p = copy.deepcopy(package)
        e = p["events"][0]
        e["decimal_odds"] = price
        p["market_metadata"] = {"price": price, "book": "synthetic-market"}
        context = {"package": p, "package_sha256": content_id(p), "cutoff": "2026-10-23T23:00:00Z"}
        monkeypatch.setenv("SPORTS_RESEARCH_DRAW_OUTPUT", str(tmp_path/f"{league}-{i}"))
        children.append(forecast_with_identity(adapter, e, context, 257, semantics=SEMANTIC))
    assert children[0]["numerical_identity"] == children[1]["numerical_identity"]
    assert children[0]["model_p"] == children[1]["model_p"]
    assert children[0]["sim_p"] == children[1]["sim_p"]
    assert children[0]["simulation"]["draw_sha256"] == children[1]["simulation"]["draw_sha256"]


def test_nfl_numeric_reidentifier_runs_and_preserves_legacy_objects():
    from pipelines.cards.semantic_identity import reidentify_nfl_run, SEMANTIC, LEGACY
    from models.nfl.contextual.recovered_inference import predict, digest, bernoulli_simulation
    head = {"impute": [0], "center": [0], "scale": [1], "coefficient": [1], "intercept": 0}
    artifact = {"arms": {"qb": {"model_id": "synthetic.nfl.qb", "feature_names": ["x"],
        "heads": {key: copy.deepcopy(head) for key in ("home_win", "home_margin", "total_points")}}}}
    event = {"event_id": "NFL:oracle", "start_time_utc": "2026-10-24T01:00:00Z"}
    parent = {"mode": "research_pregame", "market_input": False, "selected_arm": "qb", "model_id": "synthetic.nfl.qb",
              "features": {"x": .3}, "prediction": predict(artifact["arms"]["qb"], {"x": .3})["prediction"],
              "score_simulation": None, "identity": "a"*64, "model_artifact_sha256": digest(artifact),
              "event": event, "cutoff_utc": AT}
    old_draws, summary = bernoulli_simulation(parent["prediction"]["home_win"], parent["identity"], 40)
    parent["winner_simulation"] = summary
    legacy = reidentify_nfl_run(artifact, event, AT, parent, old_draws, None, semantics=LEGACY)
    assert legacy[0] is parent and legacy[1] is old_draws
    child, draws, scores = reidentify_nfl_run(artifact, event, AT, parent, old_draws, None, semantics=SEMANTIC)
    assert child["prediction"] == parent["prediction"] and scores is None and len(draws) == 40
    assert child["identity"] != parent["identity"] and child["identity_semantics"] == SEMANTIC


def test_archive_is_unique_by_attempt_and_requires_byte_readback(tmp_path):
    from scripts.ci_evidence_archive import build_bundle, archive_to_drive, ArchiveError, verify_bundle
    source = tmp_path / "independent-evidence.txt"
    source.write_text("Independent synthetic retained bytes\n")
    identity = {"repository": "test/repo", "workflow": "synthetic-ci", "run_id": "123", "run_attempt": "1",
                "checkout_sha": "a"*40, "event_name": "workflow_dispatch"}
    first = build_bundle(tmp_path/"attempt1", identity, [f"evidence.txt={source}"], [])
    second = build_bundle(tmp_path/"attempt2", {**identity, "run_attempt": "2"}, [f"evidence.txt={source}"], [])
    assert first["archive_name"] != second["archive_name"]
    manifest = verify_bundle(first["archive_path"])
    assert manifest["files"][0]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    class Adapter:
        destination = "synthetic-only"
        corrupt = False
        def capabilities(self, required):
            assert required == {"put_immutable", "download"}
        def call(self, operation, payload):
            if operation == "put_immutable":
                self.uploaded = Path(payload["local_path"]).read_bytes()
                return {"object_id": "synthetic-object", "name": payload["name"], "destination_id": self.destination}
            Path(payload["local_path"]).write_bytes(b"corrupted" if self.corrupt else self.uploaded)
            return {}
    adapter = Adapter()
    assert archive_to_drive(first, adapter)["durable_archive_verified"] is True
    adapter.corrupt = True
    with pytest.raises(ArchiveError, match="READBACK_SHA256"):
        archive_to_drive(first, adapter)


def test_lineage_cycle_guard_and_unknown_parent_fail(signed):
    class CyclicStore(ArtifactStore):
        def read(self, artifact_id):
            return {"schema": "research-procedure-v1", "owner": "test", "change_hypothesis": "Cycle fixture",
                    "created_utc": "2026-01-01T00:00:00Z", "definition": {}, "parent_ids": [artifact_id], "defect_ids": []}
    # The synthetic store isolates the graph traversal; real content addressing
    # additionally makes constructing a self-referential hash computationally hard.
    with pytest.raises(RegistryError, match="LINEAGE_CYCLE"):
        ProcedureLineage(CyclicStore(signed.store.root)).resolve("f"*64)
    with pytest.raises(RegistryError, match="MISSING_OR_INVALID_PARENT"):
        create_procedure(signed.store, parent_ids=["f"*64], owner="test", created_utc=AT,
                         change_hypothesis="Unknown ancestry", definition={})


def test_signed_lifecycle_demotion_and_tampered_journal_fail_closed(signed):
    from research.validation_registry import ValidationRegistry
    original = signed.decide()
    assert original["decision_class"] == "SHADOW_SELECTED"
    signed.lifecycle.journal.clock = lambda: datetime(2026, 10, 19, 2, tzinfo=timezone.utc)
    event = signed.store.put({"schema": "procedure-lifecycle-event-v1", "action": "REVOKE",
        "procedure_id": signed.candidate, "selector_config_id": signed.config_id, "target": FAMILY,
        "created_utc": "2026-10-19T00:00:00Z", "reason": "Synthetic demotion", "record_id": signed.record_id})
    receipt = signed.receipt(event, "procedure_lifecycle", "2026-10-19T01:00:00Z", "fixture-reviewer")
    tip = signed.lifecycle.append(event, receipt, expected_tip=signed.registry_args["lifecycle_tip"])
    arguments = {**signed.registry_args, "lifecycle_tip": tip["record_id"]}
    demoted = ValidationRegistry(signed.store, [signed.record_id], signed.verifier, **arguments)
    result = signed.decide(registry=demoted)
    assert result["decision_class"] == "BLOCKED" and result["raw_probability"] == .62
    assert "LIFECYCLE_NOT_QUALIFIED:REVOKE" in result["blocking_reasons"]
    path = signed.lifecycle.journal.path
    path.write_text(path.read_text().replace('"signed-lifecycle"', '"tampered-lifecycle"'))
    result = signed.decide(registry=demoted)
    assert result["decision_class"] == "BLOCKED" and result["raw_probability"] == .62
    assert "TRIAL_CHAIN_CORRUPT" in result["blocking_reasons"]
    verify_selection_record(original)


def test_ancestry_trial_exposure_cannot_be_reset_by_new_family_labels(signed, tmp_path):
    child = create_procedure(signed.store, parent_ids=[signed.candidate], owner="fixture-author", created_utc=AT,
                             change_hypothesis="Renamed family", definition={"model_id": "child"})
    journal = TrialLog(tmp_path/"renamed-trials.jsonl")
    journal.append({"kind": "INSPECTED", "trial_id": "ancestor", "family_id": "old-label", "procedure_id": signed.candidate,
                    "configuration_id": signed.config_id})
    tip = journal.append({"kind": "INSPECTED", "trial_id": "descendant", "family_id": "new-label", "procedure_id": child,
                          "configuration_id": signed.config_id})
    exposure = journal.lineage_exposure(signed.store, child, expected_tip=tip["record_id"])
    assert exposure["inspected_configurations"] == 2 and exposure["performance_inherited"] is False


def test_storage_crossings_are_persistent_and_repeated_below_is_suppressed():
    from scripts.ci_storage_monitor import inventory, transition, persist_transition, content_id as storage_id, METRIC_SCOPE
    from scripts.ci_evidence_archive import ArchiveError
    policy = {"schema": "ci-storage-monitor-v1", "repository": "test/repo", "metric_scope": METRIC_SCOPE,
              "threshold_bytes": 100, "initial_below_policy": "baseline_only", "state_key": "fixture-only"}
    def measurement(value):
        return inventory([{"total_count": 2, "artifacts": [
            {"id": 1, "size_in_bytes": value, "expired": False},
            {"id": 2, "size_in_bytes": 1234, "expired": True}]}], "test/repo")
    class StatefulAdapter:
        destination, state, revision, corrupt = "synthetic", None, None, False
        def capabilities(self, required):
            assert required == {"state_get", "state_compare_and_swap"}
        def call(self, operation, payload):
            if operation == "state_get":
                return {"state": self.state, "revision": self.revision if not self.corrupt else "unexpected-revision"}
            assert operation == "state_compare_and_swap" and payload["expected_revision"] == self.revision
            self.state = payload["state"]
            self.revision = str(int(self.revision or "0")+1)
            return {"revision": self.revision, "state_sha256": storage_id(self.state)}
    adapter = StatefulAdapter()
    results = [persist_transition(adapter, policy, measurement(value), f"2026-10-23T00:00:0{i}Z")
               for i, value in enumerate((110, 100, 99, 80, 120, 90), 1)]
    assert [r["transition_event"]["kind"] if r["transition_event"] else None for r in results] == [None, None, "CROSSED_BELOW", None, None, "CROSSED_BELOW"]
    assert results[-1]["pending_event_count"] == 2
    assert all(not e["notification_sent"] for e in adapter.state["pending_events"])
    assert measurement(99)["value_bytes"] == 99 and measurement(99)["account_quota_status"] == "UNKNOWN_NOT_MEASURED"
    baseline, event = transition(policy, None, measurement(50), AT)
    assert event is None and baseline["pending_events"] == []
    initial, event = transition({**policy, "initial_below_policy": "record_event"}, None, measurement(50), AT)
    assert event["kind"] == "INITIAL_BELOW" and event["notification_sent"] is False
    with pytest.raises(ArchiveError, match="NONINCREASING"):
        transition(policy, baseline, measurement(40), AT)


def finding_fixture(root):
    from research.finding_evidence import FIELDS
    (root/"implementation.py").write_text("value = 1\n")
    (root/"acceptance.log").write_text("synthetic fixture receipt, not an actual execution claim\n")
    def ref(name):
        return {"path": name, "sha256": hashlib.sha256((root/name).read_bytes()).hexdigest()}
    receipt = {"schema": "acceptance-execution-v1", "exit_code": 0, "command": "synthetic-test-command",
               "executed_at_utc": AT, "sources": [ref("implementation.py")], "log": ref("acceptance.log")}
    (root/"receipt.json").write_text(json.dumps(receipt))
    packet = {key: "Synthetic fixture "+key for key in FIELDS}
    packet.update(schema="finding-evidence-v1", status="verified_implementation", classification="implementation_bug",
        owner="independent-fixture", evidence=[ref("implementation.py")],
        acceptance_test={"command": receipt["command"], "execution_receipt": ref("receipt.json")},
        delivery={"stage": "Tested"})
    return packet


def test_finding_verified_stage_requires_actual_bound_delivery_receipt(tmp_path):
    from research.finding_evidence import validate_packet
    packet = finding_fixture(tmp_path)
    assert validate_packet(packet, root=tmp_path)["packet_valid"] is True
    packet["delivery"] = {"stage": "Verified", "merge_commit": "not-a-commit", "configuration_ref": "missing-config.json",
                          "run_url": "not-a-run-url", "verification_receipt": "missing-receipt.json"}
    with pytest.raises(ValueError):
        validate_packet(packet, root=tmp_path)


def test_finding_verified_delivery_positive_twin_and_failed_run_negative(tmp_path):
    from research.finding_evidence import validate_packet
    packet = finding_fixture(tmp_path)
    def write_ref(name, value):
        (tmp_path/name).write_text(json.dumps(value))
        return {"path": name, "sha256": hashlib.sha256((tmp_path/name).read_bytes()).hexdigest()}
    commit = "a"*40
    url = "https://github.com/synthetic/repo/actions/runs/123/attempts/1"
    merge = write_ref("merge.json", {"merged": True, "sha": commit})
    configuration = write_ref("configuration.json", {"enabled": True, "synthetic": True})
    run = {"html_url": url, "head_sha": commit, "status": "completed", "conclusion": "success"}
    run_ref = write_ref("run.json", run)
    verification = {"schema": "delivery-verification-v1", "merge_commit": commit, "run_receipt": run_ref,
                    "configuration_ref": configuration, "verified": True, "verified_at_utc": AT}
    packet["delivery"] = {"stage": "Verified", "merge_commit": commit, "merge_receipt": merge,
        "configuration_ref": configuration, "run_url": url, "run_receipt": run_ref,
        "verification_receipt": write_ref("verification.json", verification)}
    assert validate_packet(packet, root=tmp_path)["delivery_stage"] == "Verified"
    run_ref = write_ref("run_failed.json", {**run, "conclusion": "failure"})
    packet["delivery"]["run_receipt"] = run_ref
    packet["delivery"]["verification_receipt"] = write_ref("verification_failed.json", {**verification, "run_receipt": run_ref})
    with pytest.raises(ValueError, match="DELIVERY_VERIFICATION"):
        validate_packet(packet, root=tmp_path)


def source_card_fixture(league="MLS"):
    return {"league": league, "as_of_utc": "2026-10-20T17:00:00Z", "generated_at_utc": "2026-10-20T17:01:00Z",
        "forecasts": [{"event_id": league+":one", "home_team": "H", "away_team": "A",
            "start_time_utc": "2026-10-20T20:00:00Z", "forecast_status": "FORECAST_GENERATED",
            "model_id": league.lower()+".initial_causal_score.research.v1", "model_winner": "H", "model_p": .55,
            "diagnostics": {"outcome_order": ["away", "draw", "home"], "analytic_probabilities": [.25, .2, .55]},
            "coverage_label": "REGULATION_1X2_INITIAL_RESEARCH", "input_snapshot_hash": "a"*64,
            "model_state_config_hash": "b"*64}]}


def test_mls_bridge_never_declares_refund_contract_and_erases_draw_mass():
    from pipelines.cards.selection_integration import build_card_selection
    card = source_card_fixture()
    report = build_card_selection(card, source_sha256=content_id(card), source_ref="synthetic-only", evaluated_at_utc=AT)
    forecast = report["forecasts"][0]
    if forecast["target"]["settlement_rules_id"] == "full_game_winner_tie_push_v1":
        assert forecast["probabilities"]["push"] == .2, "Draw mass cannot become loss under a tie-refund target."
    else:
        assert "regulation" in forecast["target"]["settlement_rules_id"].lower()


@pytest.mark.parametrize("winner,probability,side,tied_result", [("H", .55, "home", "LOSS"),
    ("A", .25, "away", "LOSS"), ("Draw", .2, "draw", "WIN")])
def test_mls_1x2_exact_target_settlement(winner, probability, side, tied_result):
    from pipelines.cards.selection_integration import build_card_selection, settle_target
    card = source_card_fixture()
    card["forecasts"][0].update(model_winner=winner, model_p=probability)
    report = build_card_selection(card, source_sha256=content_id(card), source_ref="synthetic-only", evaluated_at_utc=AT)
    forecast = report["forecasts"][0]
    assert forecast["target"]["period"] == "regulation_90" and forecast["target"]["side"] == side
    assert forecast["probabilities"] == pytest.approx({"win": probability, "loss": 1-probability, "push": 0, "void": 0})
    assert settle_target(forecast["target"], 1, 1, score_period="REGULATION_90") == tied_result
    with pytest.raises(ValueError, match="REGULATION"):
        settle_target(forecast["target"], 1, 1)
    with pytest.raises(ValueError, match="REGULATION"):
        settle_target(forecast["target"], 1, 1, score_period="FULL_GAME")


def test_source_population_retains_failed_forecast_opportunity():
    from pipelines.cards.selection_integration import build_card_selection
    card = source_card_fixture("NBA")
    card["forecasts"].append({"event_id": "NBA:failed", "forecast_status": "FORECAST_FAILED",
        "home_team": "H2", "away_team": "A2", "start_time_utc": "2026-10-20T20:00:00Z"})
    report = build_card_selection(card, source_sha256=content_id(card), source_ref="synthetic-only", evaluated_at_utc=AT)
    assert {row["event_id"] for row in report["population"]} == {"NBA:one", "NBA:failed"}


def test_source_card_retrospective_replay_is_labeled_and_immutable(tmp_path):
    from pipelines.cards.selection_integration import write_card_selection, verify_sidecar
    path = tmp_path/"retained_source_card.json"
    path.write_text(json.dumps(source_card_fixture("NBA")))
    before = path.read_bytes()
    report = write_card_selection(path, tmp_path/"decisions", retrospective=True, evaluated_at_utc="2026-10-23T18:00:00Z")
    assert path.read_bytes() == before
    assert report["execution_mode"] == "RETROSPECTIVE_DIAGNOSTIC" and report["evidence_scope"] == "DISCOVERY"
    assert all(d["execution_mode"] == "RETROSPECTIVE_DIAGNOSTIC" for d in report["decisions"])
    verify_sidecar(report, source_card_sha256=hashlib.sha256(before).hexdigest())
    receipt = json.loads((tmp_path/"decisions/execution_receipt.json").read_text())
    assert receipt["original_source_unchanged"] and receipt["decisions_sha256"] == hashlib.sha256((tmp_path/"decisions/decisions.json").read_bytes()).hexdigest()


def test_shared_card_cli_emits_bound_decisions_while_publication_is_blocked(tmp_path):
    import os
    import subprocess
    import sys
    from pipelines.cards.selection_integration import verify_sidecar
    event, package = synthetic_nba_package()
    now = datetime.now(timezone.utc)-timedelta(minutes=1)
    future = now+timedelta(days=1)
    event.update(start_time_utc=future.isoformat(), slate_date=future.date().isoformat())
    package.update(captured_at_utc=now.isoformat(), source_fetches=[{"fetched_at_utc": now.isoformat()}],
                   covered_dates=[future.date().isoformat()], code_pins={})
    package_root = tmp_path/"packages/nba"
    package_root.mkdir(parents=True)
    (package_root/"package.json").write_text(json.dumps(package))
    output = tmp_path/"shared-card-run"
    env = {**os.environ, "SPORTS_RESEARCH_PACKAGE_DIR": str(package_root.parent)}
    command = [sys.executable, "scripts/generate_card_force.py", "--date", future.date().isoformat(), "--league", "nba",
               "--initial-research-baselines", "--simulations", "257", "--output-dir", str(output)]
    completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, completed.stdout[-2000:]+completed.stderr[-2000:]
    card_bytes = (output/"diagnostic_card.json").read_bytes()
    card = json.loads(card_bytes)
    assert card["forecast_count"] == 1 and card["actionable"] is False
    assert card["forecasts"][0]["identity_semantics"] == "market_blind_numeric.v2"
    report = json.loads((output/"research_selection/decisions.json").read_text())
    verify_sidecar(report, source_card_sha256=hashlib.sha256(card_bytes).hexdigest())
    assert report["decisions"][0]["decision_class"] == "BLOCKED"
    assert report["decisions"][0]["raw_probability"] == card["forecasts"][0]["model_p"]
    assert report["decisions"][0]["selection_probability"] is None


def test_nfl_actual_cli_emits_bound_decisions_with_real_inference(tmp_path):
    """Exercise the actual CLI with an explicitly synthetic future event package.

    The fitted coefficients are retained repository artifacts. Future schedule,
    inputs and receipts are synthetic test data, never live forecasting evidence.
    """
    import os
    import subprocess
    import sys
    from models.nfl.contextual.model import load_artifact
    from models.nfl.contextual.recovered_inference import digest
    from pipelines.cards.selection_integration import verify_sidecar
    root = Path(__file__).resolve().parents[1]
    data = root/"data/nfl/contextual_v1"
    artifact_path = data/"model_packed.json"
    artifact = load_artifact(artifact_path)
    event = json.loads((data/"mnf_event.json").read_text())
    base = json.loads((data/"mnf_base_row.json").read_text())[0]
    context = json.loads((data/"mnf_context_integrated.json").read_text())
    now = datetime.now(timezone.utc)-timedelta(minutes=2)
    future = now+timedelta(days=1)
    event.update(event_id="2026_01_DEN_KC_SYNTHETIC_BLIND_TEST", start_time_utc=future.isoformat(), gameday=future.date().isoformat(),
                 gametime="20:15", event_scope="SYNTHETIC_CONFORMANCE_ONLY", source="synthetic fixture")
    base.update(game_id=event["event_id"], gameday=event["gameday"], week=1)
    for value in context.values():
        value.update(event_id=event["event_id"], source="synthetic fixture", source_sha256="f"*64,
                     retrieved_at_utc=now.isoformat(), available_by_utc=now.isoformat(), published_at_utc=now.isoformat())
    context["weather"].update(valid_from_utc=(future-timedelta(hours=1)).isoformat(), valid_to_utc=(future+timedelta(hours=1)).isoformat())
    context["personnel"]["state"]["injury_observations"] = []
    context["personnel"]["state"]["reserve_absences"] = []
    package = {"schema": "nfl.integrated_event_package.v1", "captured_at_utc": now.isoformat(),
        "scope": "SYNTHETIC_CONFORMANCE_ONLY", "covered_dates": [event["gameday"]], "events": [event],
        "model_path": str(artifact_path), "model_digest": digest(artifact),
        "recovered_parameters_path": str(data/"recovered_parameters.json"),
        "event_inputs": {event["event_id"]: {"base": base, "context": context}},
        "source_fetches": [{"source": "synthetic fixture", "fetched_at_utc": now.isoformat()}]}
    package_path = tmp_path/"synthetic_nfl_package.json"
    package_path.write_text(json.dumps(package))
    # Real NFL inference followed by v2 reidentification at the SAME cutoff:
    # price-bearing event metadata must affect neither numeric identity nor draws.
    from models.nfl.contextual.runtime import run
    from pipelines.cards.semantic_identity import reidentify_nfl_run, SEMANTIC
    recovered = json.loads((data/"recovered_parameters.json").read_text())
    children = []
    for odds in (1.1, 15.0):
        annotated = {**event, "market_decimal_odds": odds}
        parent, winner, scores = run(artifact, recovered, base, context, annotated, now.isoformat(), 257,
                                    model_id="nfl.integrated_context.qb.v1.research")
        children.append(reidentify_nfl_run(artifact, annotated, now.isoformat(), parent, winner, scores, semantics=SEMANTIC))
    assert children[0][0]["numerical_identity"] == children[1][0]["numerical_identity"]
    assert children[0][0]["prediction"] == children[1][0]["prediction"]
    assert np.array_equal(children[0][1], children[1][1])
    output = tmp_path/"nfl-cli-run"
    command = [sys.executable, "scripts/run_nfl_integrated.py", "--date", event["gameday"], "--output", str(output),
               "--simulations", "257", "--model-id", "nfl.integrated_context.qb.v1.research"]
    completed = subprocess.run(command, cwd=root, env={**os.environ, "NFL_CONTEXT_PACKAGE": str(package_path)},
                               capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, completed.stdout[-2000:]+completed.stderr[-3000:]
    folder = output/event["event_id"]
    raw = json.loads((folder/"forecast.json").read_text())
    assert raw["identity_semantics"] == "market_blind_numeric.v2"
    report = json.loads((folder/"research_selection/decisions.json").read_text())
    source = (folder/"selection_source_card.json").read_bytes()
    verify_sidecar(report, source_card_sha256=hashlib.sha256(source).hexdigest())
    assert report["decisions"][0]["decision_class"] == "BLOCKED"
    assert report["decisions"][0]["raw_probability"] == max(raw["prediction"]["home_win"], 1-raw["prediction"]["home_win"])
    assert report["decisions"][0]["raw_probability_basis"] == "conditional_decisive"
    assert report["decisions"][0]["selection_probability"] is None
