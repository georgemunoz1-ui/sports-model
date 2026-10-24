import copy
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.procedure_lineage import (FrozenWalkForwardPlan, ProcedureLineage, create_procedure, predictive_identity)
from research.selection_evaluation import EvaluationError, evaluate_decisions
from research.validation_registry import (ArtifactStore, LifecycleLog, RegistryError, TrialLog,
                                          ValidationRegistry, content_id)
from tests.test_selection_evaluation import evaluation_fixture
from tests.test_validation_registry import make_registry_fixture


class LineageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ArtifactStore(self.tmp.name)

    def node(self, name, parents=(), defects=(), created="2025-12-01T00:00:00Z"):
        return create_procedure(self.store, parent_ids=parents, owner="TEST_ONLY_owner", created_utc=created,
                                change_hypothesis="TEST_ONLY " + name, definition={"name": name}, defect_ids=defects)

    def test_full_ancestry_retains_defects_but_never_scores(self):
        defect = self.store.put({"schema": "procedure-defect-v1", "owner": "TEST_ONLY_owner",
                                 "created_utc": "2025-11-01T00:00:00Z", "description": "TEST_ONLY rest defect"})
        root = self.node("root", defects=[defect])
        left, right = self.node("left", [root]), self.node("right", [root])
        child = self.node("renamed-family merge", [left, right])
        result = ProcedureLineage(self.store).resolve(child)
        self.assertEqual(set(result.ancestor_ids), {root, left, right, child})
        self.assertEqual(result.root_ids, (root,))
        self.assertEqual(result.defect_ids, (defect,))
        self.assertFalse(hasattr(result, "performance"))
        self.assertFalse(hasattr(result, "eligible"))

    def test_missing_parent_bad_metadata_and_future_parent_fail(self):
        with self.assertRaises(RegistryError):
            self.node("missing", ["a" * 64])
        valid = self.node("valid")
        raw = self.store.read(valid)
        for key in ("parent_ids", "owner", "created_utc", "change_hypothesis"):
            bad = dict(raw)
            bad.pop(key)
            with self.subTest(key=key), self.assertRaises(RegistryError):
                ProcedureLineage(self.store).resolve(self.store.put(bad))
        future = self.node("future", created="2026-01-01T00:00:00Z")
        with self.assertRaisesRegex(RegistryError, "PARENT_CREATED_AFTER_CHILD"):
            self.node("past-child", [future])

    def test_cycle_guard_even_if_storage_backend_is_corrupt(self):
        # Real content-addressed cycles require a hash fixed point; exercise the
        # traversal's explicit guard using a deliberately corrupt test backend.
        a, b = "a" * 64, "b" * 64
        prototype = {"schema": "research-procedure-v1", "owner": "test", "created_utc": "2025-01-01T00:00:00Z",
                     "change_hypothesis": "cycle test", "definition": {}, "defect_ids": []}
        class BrokenStore(ArtifactStore):
            def read(self, key):
                return dict(prototype, parent_ids=[b if key == a else a])
        with self.assertRaisesRegex(RegistryError, "LINEAGE_CYCLE"):
            ProcedureLineage(BrokenStore(self.tmp.name)).resolve(a)

    def test_renamed_families_and_siblings_cannot_reset_exposure(self):
        root = self.node("root")
        child, sibling = self.node("renamed", [root]), self.node("sibling", [root])
        unrelated = self.node("independent root")
        log = TrialLog(Path(self.tmp.name) / "trials.jsonl")
        for i, (node, family) in enumerate([(root, "old"), (child, "new"), (sibling, "another"), (unrelated, "new"), (None, "legacy")]):
            payload = {"kind": "INSPECTED", "trial_id": str(i), "family_id": family, "configuration_id": content_id({"i": i})}
            if node is not None:
                payload["procedure_id"] = node
            tip = log.append(payload)["record_id"]
        result = log.lineage_exposure(self.store, child, expected_tip=tip)
        self.assertEqual(result["inspected_configurations"], 4)
        self.assertEqual(len(result["legacy_unbound_inspections"]), 1)
        self.assertFalse(result["performance_inherited"])
        with self.assertRaisesRegex(RegistryError, "ANCHOR"):
            log.lineage_exposure(self.store, child, expected_tip="f" * 64)


class RegistryV2LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def assess(self, f, at="2026-10-22T21:00:00Z", procedure=None):
        return f["registry"].assess(procedure or f["procedure_id"], f["target"], at,
                                    selector_config_id=f["config_id"])

    def append_action(self, f, action, at="2026-10-22T22:00:00Z", **changes):
        event = {"schema": "procedure-lifecycle-event-v1", "action": action, "record_id": f["record_id"],
                 "procedure_id": f["procedure_id"], "selector_config_id": f["config_id"], "target": f["target"],
                 "created_utc": at, "reason": "TEST_ONLY lifecycle symmetry"}
        event.update(changes)
        event_id = f["store"].put(event)
        receipt = f["sign"](event_id, "procedure_lifecycle", "TEST_ONLY_reviewer", at)
        f["lifecycle_log"].journal.clock = lambda: datetime.fromisoformat(at.replace("Z", "+00:00"))
        result = f["lifecycle_log"].append(event_id, receipt, expected_tip=f["registry"].lifecycle_tip)
        f["registry"].lifecycle_tip = result["record_id"]
        return event_id, receipt

    def test_v1_signed_replay_preserved_but_new_admission_blocked(self):
        f = make_registry_fixture(self.tmp.name, legacy=True)
        old = f["registry"].replay_legacy_record(f["record_id"], f["procedure_id"], f["target"], f["at_utc"],
                                                  selector_config_id=f["config_id"])
        self.assertTrue(old["legacy_eligible"])
        self.assertFalse(old["selection_eligible"])
        self.assertIn("LEGACY_VALIDATION_REQUIRES_V2_ADMISSION", self.assess(f).reasons)
        revocation = f["store"].put({"record_id": f["record_id"], "reason": "TEST_ONLY legacy correction"})
        receipt = f["sign"](revocation, "validation_revocation", "TEST_ONLY_reviewer", "2026-10-22T20:00:00Z")
        f["registry"].revocation_ids = (f["store"].put({"revocation_payload_id": revocation, "revocation_receipt_id": receipt}),)
        revoked = f["registry"].replay_legacy_record(f["record_id"], f["procedure_id"], f["target"], f["at_utc"],
                                                     selector_config_id=f["config_id"])
        self.assertFalse(revoked["legacy_eligible"])
        self.assertIn("VALIDATION_REVOKED", revoked["reasons"])

    def test_v2_positive_revoke_and_expire_twins(self):
        for action in ("REVOKE", "EXPIRE"):
            with self.subTest(action=action):
                f = make_registry_fixture(self.tmp.name)
                self.assertTrue(self.assess(f).eligible)
                self.append_action(f, action)
                self.assertTrue(self.assess(f).eligible)  # Before signed transition.
                result = self.assess(f, "2026-10-23T00:00:00Z")
                self.assertFalse(result.eligible)
                self.assertIn("LIFECYCLE_NOT_QUALIFIED:" + action, result.reasons)

    def test_wrong_identity_demotion_and_replayed_event_rejected(self):
        f = make_registry_fixture(self.tmp.name)
        before = f["lifecycle_log"].journal.path.read_bytes()
        with self.assertRaisesRegex(RegistryError, "BINDING_MISMATCH"):
            self.append_action(f, "REVOKE", selector_config_id=f["store"].put({"other": "config"}))
        self.assertEqual(before, f["lifecycle_log"].journal.path.read_bytes())
        event, receipt = self.append_action(f, "REVOKE")
        with self.assertRaisesRegex(RegistryError, "DUPLICATE_LIFECYCLE_EVENT"):
            f["lifecycle_log"].append(event, receipt, expected_tip=f["registry"].lifecycle_tip)

    def test_unjustified_minima_and_unanchored_lifecycle_block(self):
        f = make_registry_fixture(self.tmp.name, protocol_overrides={"criteria_justification": {}})
        self.assertTrue(any("UNJUSTIFIED" in reason for reason in self.assess(f).reasons))
        f = make_registry_fixture(self.tmp.name)
        f["registry"].lifecycle_tip = None
        self.assertIn("ANCHORED_LIFECYCLE_LOG_REQUIRED", self.assess(f).reasons)

    def test_power_assumptions_required_with_validated_numeric_domains(self):
        base = {"minimum_useful_improvement": .05, "paired_loss_sd": .1, "design_effect": 1.2,
                "alpha": .05, "total_trials": 4, "target_power": .8, "dependence": "Synthetic independent blocks"}
        f = make_registry_fixture(self.tmp.name, protocol_overrides={"power_assumptions": base})
        self.assertTrue(self.assess(f).eligible)
        bad_values = [None, {}, dict(base, paired_loss_sd=0), dict(base, design_effect=.2),
                      dict(base, total_trials=1), dict(base, dependence=""), dict(base, target_power=.9)]
        for bad in bad_values:
            with self.subTest(assumptions=bad):
                f = make_registry_fixture(self.tmp.name, protocol_overrides={"power_assumptions": bad})
                self.assertFalse(self.assess(f).eligible)

    def test_ancestry_exposure_is_used_by_admission_not_just_reported(self):
        f = make_registry_fixture(self.tmp.name, protocol_overrides={"inspection_budget": 1})
        self.assertTrue(self.assess(f).eligible)
        child = create_procedure(f["store"], parent_ids=[f["procedure_id"]], owner="TEST_ONLY_author",
                                  created_utc="2026-01-15T00:00:00Z", change_hypothesis="TEST_ONLY renamed family",
                                  definition={"renamed_family": True})
        f["trial_log"].clock = lambda: datetime(2026, 10, 22, 20, tzinfo=timezone.utc)
        row = f["trial_log"].append({"kind": "INSPECTED", "trial_id": "new trial", "family_id": "renamed family",
                                    "configuration_id": f["config_id"], "procedure_id": child}, expected_tip=f["registry"].trial_tip)
        f["registry"].trial_tip = row["record_id"]
        self.assertIn("ANCESTRY_INSPECTION_BUDGET_EXCEEDED", self.assess(f).reasons)
        self.assertFalse(self.assess(f, procedure=child).eligible)

    def test_later_parent_defect_is_visible_to_child_without_approval(self):
        f = make_registry_fixture(self.tmp.name)
        child = create_procedure(f["store"], parent_ids=[f["procedure_id"]], owner="TEST_ONLY_author",
                                  created_utc="2026-01-15T00:00:00Z", change_hypothesis="TEST_ONLY repair candidate", definition={})
        defect = f["store"].put({"schema": "procedure-defect-v1", "owner": "TEST_ONLY_author",
                                  "created_utc": "2026-10-22T21:00:00Z", "description": "TEST_ONLY stale rest"})
        self.append_action(f, "DEFECT_RECORDED", defect_id=defect)
        history = f["lifecycle_log"].defect_history(child, "2026-10-23T00:00:00Z", expected_tip=f["registry"].lifecycle_tip)
        self.assertEqual(history, (defect,))
        self.assertFalse(self.assess(f, procedure=child).eligible)


class WalkForwardPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.f = make_registry_fixture(self.tmp.name)

    def plan(self, *, registration="2026-10-01T00:00:00Z"):
        rows, population = evaluation_fixture()
        for index, row in enumerate(rows):
            row.update(procedure_id=content_id({"fold": index//2}), fitted_state_id=content_id({"fit": index}),
                       control_fitted_state_id=content_id({"control_fit": index}),
                       training_data_cutoff_utc="2026-10-02T00:00:00Z", forecast_created_at_utc="2026-10-03T00:00:00Z",
                       decision_at_utc="2026-10-03T12:00:00Z", starts_at_utc="2026-10-04T00:00:00Z",
                       control_training_data_cutoff_utc="2026-10-02T00:00:00Z", control_forecast_created_at_utc="2026-10-03T00:00:00Z")
        artifact = {"schema": "walk-forward-plan-v1", "owner": "TEST_ONLY_author",
                    "created_utc": "2026-09-30T00:00:00Z", "change_hypothesis": "TEST_ONLY exact scheduled fits",
                    "evaluation_start_utc": "2026-10-02T00:00:00Z", "evaluation_end_utc": "2026-10-10T00:00:00Z",
                    "target_family_id": rows[0]["target_family_id"],
                    "population_id": content_id(sorted(population, key=lambda r: r["event_id"])),
                    "assignments": [{k: r[k] for k in ("event_id", "procedure_id", "selector_config_id",
                                                        "control_procedure_id", "fitted_state_id", "control_fitted_state_id")} for r in rows]}
        plan_id = self.f["store"].put(artifact)
        receipt = self.f["sign"](plan_id, "walk_forward_registration", "TEST_ONLY_witness", registration)
        plan = FrozenWalkForwardPlan(self.f["store"], plan_id, receipt, self.f["verifier"])
        return rows, population, plan

    def evaluate(self, rows, population, plan=None):
        return evaluate_decisions(rows, population=population, evidence_scope="SHADOW", bootstrap_samples=30, walk_forward_plan=plan)

    def test_exact_prefrozen_changing_states_pass_but_unplanned_mix_fails(self):
        rows, population, plan = self.plan()
        report = self.evaluate(rows, population, plan)
        self.assertEqual(report["walk_forward_plan"]["plan_id"], plan.plan_id)
        self.assertEqual(len(report["identity_bindings"]), 3)
        self.assertIsNone(report["procedure_id"])
        with self.assertRaisesRegex(EvaluationError, "mixed procedure"):
            self.evaluate(rows, population)

    def test_wrong_state_config_control_and_late_plan_twins(self):
        rows, population, plan = self.plan()
        for key in ("procedure_id", "selector_config_id", "control_procedure_id", "fitted_state_id", "control_fitted_state_id"):
            changed = copy.deepcopy(rows)
            changed[0][key] = "f" * 64
            with self.subTest(key=key), self.assertRaisesRegex(EvaluationError, "IDENTITY_MISMATCH"):
                self.evaluate(changed, population, plan)
        rows, population, plan = self.plan(registration="2026-10-03T00:00:00Z")
        with self.assertRaisesRegex(EvaluationError, "NOT_PREFROZEN"):
            self.evaluate(rows, population, plan)

    def test_state_chronology_and_unverified_plan_fail(self):
        rows, population, plan = self.plan()
        rows[0]["training_data_cutoff_utc"] = "2026-10-05T00:00:00Z"
        with self.assertRaisesRegex(EvaluationError, "CHRONOLOGY"):
            self.evaluate(rows, population, plan)
        with self.assertRaisesRegex(EvaluationError, "verified FrozenWalkForwardPlan"):
            self.evaluate(rows, population, {"valid": True})


def make_refit_policy_fixture(root, *, future_training=False, include_control=False):
    """Synthetic two-fold states actually materialized after policy registration."""
    f = make_registry_fixture(root)
    store = f["store"]
    rows, population = evaluation_fixture()
    rows, population = rows[:2], population[:2]
    for row in rows:
        row["selector_config_id"] = f["config_id"]
        row["decision_class"] = "SHADOW_SELECTED"
        if not include_control:
            row["control_procedure_id"], row["control_probability"] = None, None
            row["control_fitted_state_id"] = None
    components = {key: store.put({"TEST_ONLY_component": key}) for key in
                  ("code_id", "hyperparameters_id", "feature_definition_id", "calibration_id", "training_rule_id")}
    recipe_id = store.put({"schema": "frozen-fit-recipe-v1", **components})
    folds = [{"fold_id": "fold"+str(i), "train_start_utc": "2026-09-01T00:00:00Z",
              "train_end_utc": f"2026-10-{day:02d}T00:00:00Z",
              "evaluation_start_utc": f"2026-10-{day+1:02d}T00:00:00Z",
              "evaluation_end_utc": f"2026-10-{day+2:02d}T00:00:00Z", "event_ids": [str(i)]}
             for i, day in enumerate((2, 5))]
    policy = {"schema": "walk-forward-refit-policy-v2", "owner": "TEST_ONLY_author", "created_utc": "2026-09-30T00:00:00Z",
              "change_hypothesis": "TEST_ONLY chronological refit", "fit_authority_id": "TEST_ONLY_witness",
              "evaluation_start_utc": "2026-10-03T00:00:00Z", "evaluation_end_utc": "2026-10-07T00:00:00Z",
              "target_family_id": rows[0]["target_family_id"], "selector_config_id": f["config_id"],
              "population_id": content_id(population), "recipe_id": recipe_id,
              "control_recipe_id": recipe_id if include_control else None, "folds": folds}
    plan_id = store.put(policy)
    registration = f["sign"](plan_id, "walk_forward_registration", "TEST_ONLY_witness", "2026-10-01T00:00:00Z")
    envelopes, payloads = [], []
    for i, (row, fold) in enumerate(zip(rows, folds)):
        train = fold["train_end_utc"]
        created, witnessed = train.replace("00:00:00", "01:00:00"), train.replace("00:00:00", "02:00:00")
        forecast = train.replace("00:00:00", "03:00:00")
        row.update(decision_at_utc=fold["evaluation_start_utc"].replace("00:00:00", "11:00:00"),
                   starts_at_utc=fold["evaluation_start_utc"].replace("00:00:00", "12:00:00"))
        for role in (("candidate", "control") if include_control else ("candidate",)):
            dataset = store.put({"schema": "training-dataset-receipt-v1", "data_sha256": content_id({"synthetic_data": [i, role]}),
                                 "window_start_utc": fold["train_start_utc"], "window_end_utc": train,
                                 "max_available_at_utc": created if future_training else train,
                                 "max_event_end_utc": train, "created_utc": train.replace("00:00:00", "00:30:00")})
            state = store.put({"schema": "fitted-model-state-v1", "state_sha256": content_id({"synthetic_state": [i, role]}),
                               "recipe_id": recipe_id, "training_dataset_id": dataset, "created_utc": created})
            procedure = create_procedure(store, parent_ids=[], owner="TEST_ONLY_author", created_utc=created,
                change_hypothesis="TEST_ONLY realized fold state", definition={"recipe_id": recipe_id, "fitted_state_id": state,
                "training_dataset_id": dataset, "model_id": "TEST_ONLY_walk_forward", "model_state_id": state,
                "feature_semantics_id": components["feature_definition_id"], "calibration_id": components["calibration_id"]})
            payload = {"schema": "walk-forward-fit-v1", "plan_id": plan_id, "fold_id": fold["fold_id"], "role": role,
                       "recipe_id": recipe_id, "procedure_id": procedure, "fitted_state_id": state,
                       "training_dataset_id": dataset, "created_utc": created}
            payload_id = store.put(payload)
            receipt_id = f["sign"](payload_id, "walk_forward_fit", "TEST_ONLY_witness", witnessed)
            envelopes.append(store.put({"fit_payload_id": payload_id, "fit_receipt_id": receipt_id}))
            payloads.append((payload, witnessed))
            prefix = "" if role == "candidate" else "control_"
            row.update({prefix+"procedure_id": procedure, prefix+"fitted_state_id": state,
                        prefix+"training_data_cutoff_utc": train, prefix+"forecast_created_at_utc": forecast})
    plan = FrozenWalkForwardPlan(store, plan_id, registration, f["verifier"], realized_fit_receipt_ids=envelopes)
    return {**f, "rows": rows, "population": population, "plan": plan, "fit_envelopes": envelopes,
            "fit_payloads": payloads, "recipe_id": recipe_id}


class RefitPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def evaluate(self, f):
        return evaluate_decisions(f["rows"], population=f["population"], evidence_scope="SHADOW",
                                  bootstrap_samples=30, walk_forward_plan=f["plan"])

    def test_two_chronological_future_refits_and_control_are_admitted(self):
        for control in (False, True):
            with self.subTest(control=control):
                f = make_refit_policy_fixture(self.tmp.name, include_control=control)
                report = self.evaluate(f)
                self.assertEqual(report["walk_forward_plan"]["n_folds"], 2)
                self.assertTrue(report["walk_forward_plan"]["state_authority_attested"])
                self.assertFalse(report["walk_forward_plan"]["fit_execution_independently_verified"])
                self.assertNotEqual(f["rows"][0]["fitted_state_id"], f["rows"][1]["fitted_state_id"])

    def test_wrong_recipe_future_training_missing_receipt_and_state_laundering_twins(self):
        f = make_refit_policy_fixture(self.tmp.name, future_training=True)
        with self.assertRaisesRegex(EvaluationError, "TRAINING_DATA_LEAKAGE"):
            self.evaluate(f)
        f = make_refit_policy_fixture(self.tmp.name)
        f["plan"].realized_fit_receipt_ids = tuple(f["fit_envelopes"][:-1])
        with self.assertRaisesRegex(EvaluationError, "MISSING_REALIZED_RECEIPT"):
            self.evaluate(f)
        f = make_refit_policy_fixture(self.tmp.name)
        f["rows"][1]["fitted_state_id"] = f["rows"][0]["fitted_state_id"]
        with self.assertRaisesRegex(EvaluationError, "STATE_LAUNDERING"):
            self.evaluate(f)
        f = make_refit_policy_fixture(self.tmp.name)
        original, witnessed = f["fit_payloads"][0]
        wrong = f["store"].put(dict(original, recipe_id="f" * 64))
        signed = f["sign"](wrong, "walk_forward_fit", "TEST_ONLY_witness", witnessed)
        alternate = f["store"].put({"fit_payload_id": wrong, "fit_receipt_id": signed})
        f["plan"].realized_fit_receipt_ids = (alternate, *f["fit_envelopes"][1:])
        with self.assertRaisesRegex(EvaluationError, "WRONG_FROZEN_RECIPE"):
            self.evaluate(f)

    def test_fit_witness_must_precede_forecast_and_credential_must_be_trusted(self):
        f = make_refit_policy_fixture(self.tmp.name)
        f["rows"][0]["forecast_created_at_utc"] = "2026-10-02T01:30:00Z"
        with self.assertRaisesRegex(EvaluationError, "PRECEDES_STATE_WITNESS"):
            self.evaluate(f)
        from research.validation_registry import Ed25519Verifier
        f = make_refit_policy_fixture(self.tmp.name)
        f["plan"].state_verifier = Ed25519Verifier()
        with self.assertRaisesRegex(EvaluationError, "UNTRUSTED_SIGNER"):
            self.evaluate(f)

    def test_qualifying_predictive_identity_requires_each_component_and_nonempty_hash(self):
        good = {"model_id": "TEST_ONLY", "model_state_id": "1" * 64,
                "feature_semantics_id": "2" * 64, "calibration_id": "3" * 64}
        self.assertEqual(predictive_identity(good), good)
        for key in good:
            changed = dict(good)
            changed.pop(key)
            with self.subTest(key=key), self.assertRaises(RegistryError):
                predictive_identity(changed)
        with self.assertRaisesRegex(RegistryError, "EMPTY_PREDICTIVE_IDENTITY"):
            predictive_identity(dict(good, model_state_id=content_id({})))


if __name__ == "__main__":
    unittest.main()
