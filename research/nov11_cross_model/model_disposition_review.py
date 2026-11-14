"""Validate the eight-model November 11 research disposition manifest.

A valid manifest *with blockers* is not a successful model fit. This is a
read-only accounting control to prevent the phrase 'all models updated' from
implying unexecuted parameter changes or a false promotion.
"""
from __future__ import annotations

MODULE_ID = "model_disposition_review_v1"

import json
import re
from pathlib import Path

LEAGUES=frozenset({"NFL","CFB","NBA","WNBA","MLB","NHL","MLS","CBB"})
SHA40=re.compile(r"^[0-9a-f]{40}$")
SHA256=re.compile(r"^[0-9a-f]{64}$")


class DispositionError(ValueError):
    """Invalid/unreviewable model disposition."""


def validate_dispositions(payload):
    if not isinstance(payload,dict) or payload.get("schema")!="sports.cross_model_research_dispositions.v1":
        raise DispositionError("missing versioned schema")
    leagues=payload.get("leagues")
    if not isinstance(leagues,dict) or set(leagues)!=LEAGUES:
        raise DispositionError("all and only eight league dispositions required")
    if not SHA40.fullmatch(str(payload.get("main_baseline_commit", ""))):
        raise DispositionError("pinned parent code commit required")
    if payload.get("independent_policy_registration") != "NOT_PROVEN":
        raise DispositionError("independent policy registration must be NOT_PROVEN in this packet")
    control=payload.get("shared_evaluator")
    if not isinstance(control,dict) or control.get("official_units")!=0:
        raise DispositionError("official exposure must be exactly zero")
    if control.get("status") != "LOCALLY_TESTED_IN_PR":
        raise DispositionError("shared evaluator status must be LOCALLY_TESTED_IN_PR in this packet")
    for name in ("model_defaults_changed","production_runner_enabled","canonical_forecasts_rewritten","wagering_authorized"):
        if control.get(name) is not False:
            raise DispositionError(f"{name} must stay false")
    if control.get("models_retrained")!=0:
        raise DispositionError("no model fitting evidence in this packet")
    for league,row in leagues.items():
        if not isinstance(row,dict) or not SHA40.fullmatch(str(row.get("parent_code_commit",""))):
            raise DispositionError(f"{league}: exact code commit required")
        if row.get("numerical_update_executed") is not False or row.get("baseline_state")!="UNCHANGED":
            raise DispositionError(f"{league}: no pre-approved model replacement or refit")
        if row.get("registration_receipt_verified") is not False or row.get("training_labels_verified") is not False:
            raise DispositionError(f"{league}: do not invent training or prospective receipts")
        if row.get("evaluation_adapter_status")!="LOCALLY_EXERCISED_RESEARCH_ONLY":
            raise DispositionError(f"{league}: evaluation applicability only")
        if not isinstance(row.get("review_focus"),list) or not row["review_focus"]:
            raise DispositionError(f"{league}: missing product-specific review queue")
        if not isinstance(row.get("blockers"),list) or not row["blockers"]:
            raise DispositionError(f"{league}: incomplete blocker accounting")
        if not isinstance(row.get("parent_dependency_prs"),list):
            raise DispositionError(f"{league}: dependency PR list required")
        for key in ("parent_model_id","parent_fitted_state_sha256","parent_input_manifest_sha256"):
            val=row.get(key)
            if val is not None:
                if key.endswith("sha256") and not SHA256.fullmatch(str(val)):
                    raise DispositionError(f"{league}: malformed {key}")
                if key=="parent_model_id" and (not isinstance(val,str) or not val.strip()):
                    raise DispositionError(f"{league}: malformed model identity")
        # This dated packet has no verified training labels or registration.
        # Supplying digest strings cannot advance its recorded disposition.
        if row.get("model_disposition") != "BLOCKED_PENDING_SOURCE_AND_MODEL_STATE_RECONCILIATION":
            raise DispositionError(f"{league}: must name blocker for this research-only manifest")
    return {
        "status":"VALID_RESEARCH_ONLY_WITH_NAMED_BLOCKERS",
        "model_families":8,
        "evaluation_adapter_status":"LOCALLY_EXERCISED_RESEARCH_ONLY",
        "model_numerical_updates":0,
        "all_parent_states_pinned":False,
        "production_authority":False,
        "action":"NO_PICK",
        "official_units":0,
        "league_dispositions":{k:leagues[k]["model_disposition"] for k in sorted(leagues)},
    }


def read_manifest(path):
    return validate_dispositions(json.loads(Path(path).read_text(encoding="utf-8")))
