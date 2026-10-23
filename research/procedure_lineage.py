"""Content-addressed procedure ancestry and explicitly frozen walk-forward plans.

Ancestry carries defects and inspection exposure, never scores or qualification.
Declared roots remain an external authorship claim: software cannot discover an
omitted ancestor or an experiment that was never logged.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping

from research.validation_registry import (ArtifactStore, Ed25519Verifier, RegistryError,
                                          _digest, _time, content_id)

PROCEDURE_SCHEMA = "research-procedure-v1"
PLAN_SCHEMA = "walk-forward-plan-v1"


def predictive_identity(definition):
    """Require a complete declared predictive identity for admission, not raw observation."""
    if not isinstance(definition, dict):
        raise RegistryError("PREDICTIVE_DEFINITION_REQUIRED")
    model = _text(definition.get("model_id"), "definition.model_id")
    if model.strip().lower() in {"unknown", "unverified", "missing", "null", "none"}:
        raise RegistryError("MODEL_ID_UNVERIFIED")
    identity = {"model_id": model}
    empty = {"0" * 64, hashlib.sha256(b"").hexdigest(), *(content_id(v) for v in ({}, [], None, ""))}
    for key in ("model_state_id", "feature_semantics_id", "calibration_id"):
        value = _digest(definition.get(key))
        if value in empty:
            raise RegistryError("EMPTY_PREDICTIVE_IDENTITY:" + key)
        identity[key] = value
    return identity


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise RegistryError("LINEAGE_REQUIRED:" + field)
    return value


@dataclass(frozen=True)
class LineageSummary:
    procedure_id: str
    ancestor_ids: tuple[str, ...]
    root_ids: tuple[str, ...]
    defect_ids: tuple[str, ...]
    lineage_id: str


class ProcedureLineage:
    def __init__(self, store: ArtifactStore):
        if not isinstance(store, ArtifactStore):
            raise TypeError("ArtifactStore required")
        self.store = store

    def resolve(self, procedure_id: str) -> LineageSummary:
        """Resolve the entire parent DAG; neither scores nor approval are read."""
        root = _digest(procedure_id)
        completed, visiting, nodes, defects = set(), set(), {}, set()
        stack = [(root, False)]
        while stack:
            node_id, exiting = stack.pop()
            if exiting:
                visiting.remove(node_id)
                completed.add(node_id)
                continue
            if node_id in visiting:
                raise RegistryError("LINEAGE_CYCLE")
            if node_id in completed:
                continue
            try:
                node = self.store.read(node_id)
            except RegistryError as exc:
                raise RegistryError("LINEAGE_MISSING_OR_INVALID_PARENT:" + node_id) from exc
            if node.get("schema") != PROCEDURE_SCHEMA:
                raise RegistryError("PROCEDURE_SCHEMA_REQUIRED")
            for field in ("owner", "change_hypothesis"):
                _text(node.get(field), field)
            _time(node.get("created_utc"))
            if not isinstance(node.get("definition"), dict):
                raise RegistryError("PROCEDURE_DEFINITION_REQUIRED")
            parents = node.get("parent_ids")
            if (not isinstance(parents, list) or any(not isinstance(p, str) for p in parents)
                    or len(set(parents)) != len(parents)):
                raise RegistryError("EXPLICIT_UNIQUE_PARENT_IDS_REQUIRED")
            for parent in parents:
                _digest(parent)
                if parent in visiting or parent == node_id:
                    raise RegistryError("LINEAGE_CYCLE")
            defect_ids = node.get("defect_ids")
            if (not isinstance(defect_ids, list) or any(not isinstance(p, str) for p in defect_ids)
                    or len(set(defect_ids)) != len(defect_ids)):
                raise RegistryError("EXPLICIT_UNIQUE_DEFECT_IDS_REQUIRED")
            for defect_id in defect_ids:
                defect = self.store.read(_digest(defect_id))
                if defect.get("schema") != "procedure-defect-v1":
                    raise RegistryError("DEFECT_SCHEMA_REQUIRED")
                _text(defect.get("owner"), "defect.owner")
                _text(defect.get("description"), "defect.description")
                if _time(defect.get("created_utc")) > _time(node["created_utc"]):
                    raise RegistryError("DEFECT_FROM_FUTURE")
                defects.add(defect_id)
            visiting.add(node_id)
            nodes[node_id] = node
            stack.append((node_id, True))
            stack.extend((p, False) for p in reversed(parents))
        for node in nodes.values():
            if any(_time(nodes[p]["created_utc"]) > _time(node["created_utc"]) for p in node["parent_ids"]):
                raise RegistryError("PARENT_CREATED_AFTER_CHILD")
        ancestors = tuple(sorted(completed))
        roots = tuple(sorted(k for k, node in nodes.items() if not node["parent_ids"]))
        retained = tuple(sorted(defects))
        return LineageSummary(root, ancestors, roots, retained,
                              content_id({"procedure_ids": ancestors, "root_ids": roots, "defect_ids": retained}))


def create_procedure(store: ArtifactStore, *, parent_ids, owner: str, created_utc: str,
                     change_hypothesis: str, definition: Mapping, defect_ids=()) -> str:
    """Create a new identity; existing objects remain immutable."""
    node = {"schema": PROCEDURE_SCHEMA, "parent_ids": sorted(parent_ids), "owner": owner,
            "created_utc": created_utc, "change_hypothesis": change_hypothesis,
            "definition": dict(definition), "defect_ids": sorted(defect_ids)}
    # Resolve parents before write so missing ancestry cannot leave a valid-looking node.
    for parent in node["parent_ids"]:
        ProcedureLineage(store).resolve(parent)
    node_id = store.put(node)
    ProcedureLineage(store).resolve(node_id)
    return node_id


class FrozenWalkForwardPlan:
    """Externally witnessed exact event assignments, with changing fitted states.

    v1 freezes exact state assignments. v2 freezes a refit recipe and chronology,
    then resolves later state-authority receipts for each fold. Neither executes
    or independently proves the fitting computation described by those receipts.
    """

    def __init__(self, store: ArtifactStore, plan_id: str, registration_receipt_id: str,
                 verifier: Ed25519Verifier, *, realized_fit_receipt_ids=(), state_verifier=None):
        if not isinstance(store, ArtifactStore) or not isinstance(verifier, Ed25519Verifier):
            raise TypeError("store and external verifier required")
        self.store, self.plan_id = store, _digest(plan_id)
        self.registration_receipt_id, self.verifier = _digest(registration_receipt_id), verifier
        self.realized_fit_receipt_ids = tuple(realized_fit_receipt_ids)
        self.state_verifier = state_verifier or verifier
        if not isinstance(self.state_verifier, Ed25519Verifier):
            raise TypeError("external state verifier required")

    def validate(self, rows, population):
        if any(not isinstance(row, Mapping) for row in rows) or any(not isinstance(row, Mapping) for row in population):
            raise RegistryError("WALK_FORWARD_MAPPING_ROWS_REQUIRED")
        plan = self.store.read(self.plan_id)
        if plan.get("schema") == "walk-forward-refit-policy-v2":
            return self._validate_refit(plan, rows, population)
        if plan.get("schema") != PLAN_SCHEMA:
            raise RegistryError("WALK_FORWARD_PLAN_SCHEMA_REQUIRED")
        _text(plan.get("owner"), "plan.owner")
        _text(plan.get("change_hypothesis"), "plan.change_hypothesis")
        signed = self.verifier.verify(self.store.read(self.registration_receipt_id),
                                      artifact_id=self.plan_id, purpose="walk_forward_registration")
        created, registered = _time(plan.get("created_utc")), _time(signed["witnessed_at_utc"])
        start, end = _time(plan.get("evaluation_start_utc")), _time(plan.get("evaluation_end_utc"))
        if not created <= registered < start < end:
            raise RegistryError("WALK_FORWARD_PLAN_NOT_PREFROZEN")
        family = _digest(plan.get("target_family_id"))
        expected_population_id = content_id(sorted([dict(p) for p in population], key=lambda p: p["event_id"]))
        if plan.get("population_id") != expected_population_id:
            raise RegistryError("WALK_FORWARD_POPULATION_MISMATCH")
        assignments = plan.get("assignments")
        if not isinstance(assignments, list):
            raise RegistryError("WALK_FORWARD_ASSIGNMENTS_REQUIRED")
        by_event = {}
        for item in assignments:
            if not isinstance(item, Mapping):
                raise RegistryError("WALK_FORWARD_ASSIGNMENT_MAPPING_REQUIRED")
            event = _text(item.get("event_id"), "assignment.event_id")
            if event in by_event:
                raise RegistryError("WALK_FORWARD_DUPLICATE_ASSIGNMENT")
            for key in ("procedure_id", "selector_config_id", "fitted_state_id"):
                _digest(item.get(key))
            for key in ("control_procedure_id", "control_fitted_state_id"):
                if key not in item:
                    raise RegistryError("WALK_FORWARD_EXPLICIT_CONTROL_REQUIRED")
                if item[key] is not None:
                    _digest(item[key])
            if (item["control_procedure_id"] is None) != (item["control_fitted_state_id"] is None):
                raise RegistryError("WALK_FORWARD_CONTROL_STATE_MISMATCH")
            by_event[event] = item
        if set(by_event) != {p["event_id"] for p in population} or len(rows) != len(by_event):
            raise RegistryError("WALK_FORWARD_ASSIGNMENT_COVERAGE_MISMATCH")
        seen = set()
        for row in rows:
            event = row.get("event_id")
            if event not in by_event or event in seen:
                raise RegistryError("WALK_FORWARD_EVENT_MISMATCH")
            seen.add(event)
            expected = by_event[event]
            for key in ("procedure_id", "selector_config_id", "control_procedure_id", "fitted_state_id", "control_fitted_state_id"):
                if key not in row or row[key] != expected[key]:
                    raise RegistryError("WALK_FORWARD_IDENTITY_MISMATCH:" + key)
            if row.get("target_family_id") != family:
                raise RegistryError("WALK_FORWARD_TARGET_FAMILY_MISMATCH")
            training = _time(row.get("training_data_cutoff_utc"))
            forecast = _time(row.get("forecast_created_at_utc"))
            decision, event_start = _time(row.get("decision_at_utc")), _time(row.get("starts_at_utc"))
            if not training <= forecast <= decision < event_start or not start <= event_start <= end or registered > forecast:
                raise RegistryError("WALK_FORWARD_STATE_CHRONOLOGY")
            if row["control_procedure_id"] is not None:
                control_training = _time(row.get("control_training_data_cutoff_utc"))
                control_forecast = _time(row.get("control_forecast_created_at_utc"))
                if not control_training <= control_forecast <= decision or registered > control_forecast:
                    raise RegistryError("WALK_FORWARD_CONTROL_CHRONOLOGY")
        return {"plan_id": self.plan_id, "registration_receipt_id": self.registration_receipt_id,
                "population_id": expected_population_id, "target_family_id": family,
                "registration_signer": signed["signer_id"], "n_assignments": len(by_event)}

    def _recipe(self, recipe_id):
        recipe = self.store.read(_digest(recipe_id))
        if recipe.get("schema") != "frozen-fit-recipe-v1":
            raise RegistryError("REFIT_RECIPE_SCHEMA_REQUIRED")
        for key in ("code_id", "hyperparameters_id", "feature_definition_id", "calibration_id", "training_rule_id"):
            self.store.read(_digest(recipe.get(key)))
        return recipe

    def _validate_refit(self, plan, rows, population):
        _text(plan.get("owner"), "plan.owner")
        _text(plan.get("change_hypothesis"), "plan.change_hypothesis")
        authority = _text(plan.get("fit_authority_id"), "plan.fit_authority_id")
        registration = self.verifier.verify(self.store.read(self.registration_receipt_id),
                                            artifact_id=self.plan_id, purpose="walk_forward_registration")
        registered = _time(registration["witnessed_at_utc"])
        start, end = _time(plan.get("evaluation_start_utc")), _time(plan.get("evaluation_end_utc"))
        if not _time(plan.get("created_utc")) <= registered < start < end:
            raise RegistryError("WALK_FORWARD_PLAN_NOT_PREFROZEN")
        population_id = content_id(sorted([dict(p) for p in population], key=lambda p: p["event_id"]))
        if plan.get("population_id") != population_id:
            raise RegistryError("WALK_FORWARD_POPULATION_MISMATCH")
        family, config = _digest(plan.get("target_family_id")), _digest(plan.get("selector_config_id"))
        self.store.read(config)
        recipe_id = _digest(plan.get("recipe_id"))
        self._recipe(recipe_id)
        if "control_recipe_id" not in plan:
            raise RegistryError("REFIT_EXPLICIT_CONTROL_POLICY_REQUIRED")
        control_recipe = plan["control_recipe_id"]
        if control_recipe is not None:
            self._recipe(control_recipe)
        folds = plan.get("folds")
        if not isinstance(folds, list) or not folds or any(not isinstance(f, Mapping) for f in folds):
            raise RegistryError("REFIT_FOLDS_REQUIRED")
        by_fold, by_event, prior_end = {}, {}, None
        for fold in sorted(folds, key=lambda f: _time(f.get("evaluation_start_utc"))):
            fold_id = _text(fold.get("fold_id"), "fold_id")
            if fold_id in by_fold:
                raise RegistryError("REFIT_DUPLICATE_FOLD")
            train_start, train_end = _time(fold.get("train_start_utc")), _time(fold.get("train_end_utc"))
            eval_start, eval_end = _time(fold.get("evaluation_start_utc")), _time(fold.get("evaluation_end_utc"))
            if not train_start < train_end <= eval_start < eval_end or not start <= eval_start < eval_end <= end:
                raise RegistryError("REFIT_FOLD_WINDOW_LEAKAGE")
            if prior_end is not None and eval_start < prior_end:
                raise RegistryError("REFIT_OVERLAPPING_EVALUATION_FOLDS")
            prior_end = eval_end
            event_ids = fold.get("event_ids")
            if not isinstance(event_ids, list) or not event_ids:
                raise RegistryError("REFIT_FOLD_EVENTS_REQUIRED")
            for event_id in event_ids:
                _text(event_id, "fold.event_id")
                if event_id in by_event:
                    raise RegistryError("REFIT_EVENT_ASSIGNED_TWICE")
                by_event[event_id] = fold_id
            by_fold[fold_id] = fold
        if set(by_event) != {p["event_id"] for p in population} or len(rows) != len(by_event):
            raise RegistryError("REFIT_POPULATION_COVERAGE_MISMATCH")
        realized = {}
        for envelope_id in self.realized_fit_receipt_ids:
            envelope = self.store.read(_digest(envelope_id))
            fit_id = _digest(envelope.get("fit_payload_id"))
            fit = self.store.read(fit_id)
            witness = self.state_verifier.verify(self.store.read(_digest(envelope.get("fit_receipt_id"))),
                                                 artifact_id=fit_id, purpose="walk_forward_fit")
            if witness["signer_id"] != authority:
                raise RegistryError("REFIT_STATE_AUTHORITY_MISMATCH")
            if fit.get("schema") != "walk-forward-fit-v1" or fit.get("plan_id") != self.plan_id:
                raise RegistryError("REFIT_RECEIPT_PLAN_MISMATCH")
            role, fold_id = fit.get("role"), fit.get("fold_id")
            if role not in {"candidate", "control"} or fold_id not in by_fold or (role == "control" and control_recipe is None):
                raise RegistryError("REFIT_RECEIPT_SCOPE_MISMATCH")
            key = (fold_id, role)
            if key in realized:
                raise RegistryError("REFIT_DUPLICATE_REALIZED_STATE")
            expected_recipe = recipe_id if role == "candidate" else control_recipe
            if fit.get("recipe_id") != expected_recipe:
                raise RegistryError("REFIT_WRONG_FROZEN_RECIPE")
            fold = by_fold[fold_id]
            train_start, train_end = _time(fold["train_start_utc"]), _time(fold["train_end_utc"])
            created, witnessed = _time(fit.get("created_utc")), _time(witness["witnessed_at_utc"])
            if not registered <= created <= witnessed or train_end > created:
                raise RegistryError("REFIT_RECEIPT_CHRONOLOGY")
            dataset_id, state_id, procedure_id = (_digest(fit.get(k)) for k in
                                                ("training_dataset_id", "fitted_state_id", "procedure_id"))
            dataset, state = self.store.read(dataset_id), self.store.read(state_id)
            if dataset.get("schema") != "training-dataset-receipt-v1" or state.get("schema") != "fitted-model-state-v1":
                raise RegistryError("REFIT_DATA_OR_STATE_RECEIPT_REQUIRED")
            _digest(dataset.get("data_sha256"))
            _digest(state.get("state_sha256"))
            if (_time(dataset.get("window_start_utc")) != train_start or
                    _time(dataset.get("window_end_utc")) != train_end or
                    _time(dataset.get("max_available_at_utc")) > train_end or
                    _time(dataset.get("max_event_end_utc")) > train_end or
                    not _time(dataset.get("max_available_at_utc")) <= _time(dataset.get("created_utc")) <= created):
                raise RegistryError("REFIT_TRAINING_DATA_LEAKAGE")
            if (state.get("recipe_id") != expected_recipe or state.get("training_dataset_id") != dataset_id or
                    _time(state.get("created_utc")) != created):
                raise RegistryError("REFIT_STATE_CONTENT_BINDING_MISMATCH")
            ProcedureLineage(self.store).resolve(procedure_id)
            procedure = self.store.read(procedure_id)
            definition = procedure["definition"]
            if (definition.get("recipe_id") != expected_recipe or definition.get("fitted_state_id") != state_id or
                    definition.get("training_dataset_id") != dataset_id or not created <= _time(procedure["created_utc"]) <= witnessed):
                raise RegistryError("REFIT_PROCEDURE_STATE_BINDING_MISMATCH")
            realized[key] = {"fit_id": fit_id, "envelope_id": envelope_id, "fit": fit, "witnessed": witnessed}
        expected_keys = {(fold_id, role) for fold_id in by_fold for role in
                         (("candidate", "control") if control_recipe is not None else ("candidate",))}
        if set(realized) != expected_keys:
            raise RegistryError("REFIT_MISSING_REALIZED_RECEIPT")
        seen = set()
        for row in rows:
            event = row.get("event_id")
            if event not in by_event or event in seen:
                raise RegistryError("REFIT_ROW_EVENT_MISMATCH")
            seen.add(event)
            fold_id = by_event[event]
            fold = by_fold[fold_id]
            if row.get("selector_config_id") != config or row.get("target_family_id") != family:
                raise RegistryError("REFIT_ROW_FROZEN_CONFIG_MISMATCH")
            decision, event_start = _time(row.get("decision_at_utc")), _time(row.get("starts_at_utc"))
            if not _time(fold["evaluation_start_utc"]) <= event_start < _time(fold["evaluation_end_utc"]) or decision >= event_start:
                raise RegistryError("REFIT_EVENT_OUTSIDE_FOLD")
            for role in ("candidate", "control"):
                prefix = "" if role == "candidate" else "control_"
                if role == "control" and control_recipe is None:
                    if row.get("control_procedure_id") is not None or row.get("control_fitted_state_id") is not None:
                        raise RegistryError("REFIT_UNPLANNED_CONTROL")
                    continue
                entry = realized[(fold_id, role)]
                fit = entry["fit"]
                if row.get(prefix+"procedure_id") != fit["procedure_id"] or row.get(prefix+"fitted_state_id") != fit["fitted_state_id"]:
                    raise RegistryError("REFIT_ROW_STATE_LAUNDERING")
                forecast = _time(row.get(prefix+"forecast_created_at_utc"))
                if not entry["witnessed"] <= forecast <= decision:
                    raise RegistryError("REFIT_FORECAST_PRECEDES_STATE_WITNESS")
                if _time(row.get(prefix+"training_data_cutoff_utc")) != _time(fold["train_end_utc"]):
                    raise RegistryError("REFIT_ROW_TRAINING_CUTOFF_MISMATCH")
        return {"schema": "walk-forward-refit-policy-v2", "plan_id": self.plan_id,
                "registration_receipt_id": self.registration_receipt_id, "population_id": population_id,
                "target_family_id": family, "registration_signer": registration["signer_id"],
                "fit_authority_id": authority, "realized_fit_receipt_ids": list(self.realized_fit_receipt_ids),
                "n_folds": len(by_fold), "n_assignments": len(by_event),
                "state_authority_attested": True, "fit_execution_independently_verified": False}
