"""Opt-in NHL context evidence sidecar; never modifies the parent forecast."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from models.common.discrete_research import digest, stamp
from models.current.baseline import FEATURES, IDS
from models.current.common import current, save
from models.nhl.context_controls import PROCEDURE_ID, goalie_context, load_goalie_reports
from scripts.build_operational_rest_candidate import build as build_rest

ROOT = Path(__file__).resolve().parents[1]


def _reference(base, entry):
    path = (base / entry["path"]).resolve()
    # Config may explicitly reference an absolute retained artifact. It is a local
    # read only; raw members of a capture still cannot escape their packet root.
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError("CONTEXT_INPUT_HASH_MISMATCH")
    return path, raw


def _package(raw, cutoff):
    p = json.loads(raw)
    if (p.get("league") != "nhl" or p.get("model_id") != IDS["nhl"]
            or p.get("schema") != "sports.current_research_package.v1"
            or p.get("action_authority") is not False or p.get("feature_names") != FEATURES):
        raise ValueError("NHL_INITIAL_PACKAGE_REQUIRED")
    required = {"models/current/common.py", "models/current/linear.py", "models/current/baseline.py",
                "pipelines/cards/adapters/nhl.py"}
    if not required.issubset(p.get("code_pins", {})):
        raise ValueError("RUNTIME_CODE_PINS_REQUIRED")
    for name, sha in p["code_pins"].items():
        code = (ROOT / name).resolve()
        if not code.is_relative_to(ROOT) or hashlib.sha256(code.read_bytes()).hexdigest() != sha:
            raise ValueError("RUNTIME_CODE_DRIFT")
    if digest({"model": p["fitted_model"], "state": p["team_state"], "prior": p["prior"]}) != p["model_sha256"]:
        raise ValueError("MODEL_STATE_DIGEST_MISMATCH")
    current(p, cutoff)
    return p


def shadow_from_card(card_path, config_path, output):
    """Execute source/rest checks against an existing immutable NHL card.

    No goalie effects, refit, distribution changes, registration, or qualification
    are performed. Missing source captures have per-product BLOCKED reasons.
    """
    card_path, config_path, output = map(Path, (card_path, config_path, output))
    card_raw, config_raw = card_path.read_bytes(), config_path.read_bytes()
    card, config = json.loads(card_raw), json.loads(config_raw)
    if str(card.get("league", "")).lower() != "nhl":
        raise ValueError("NHL_CARD_REQUIRED")
    if config.get("schema") != "sports.nhl_context_config.v1" or config.get("action_authority") is not False:
        raise ValueError("RESEARCH_CONTEXT_CONFIG_REQUIRED")
    cutoff = card["as_of_utc"]
    if stamp(card["generated_at_utc"]) < stamp(cutoff):
        raise ValueError("CARD_CREATION_BEFORE_CUTOFF")
    package_path, package_raw = _reference(config_path.resolve().parent, config["package"])
    package = _package(package_raw, cutoff)
    by_id = {e["event_id"]: e for e in package["events"]}
    if len(by_id) != len(package["events"]):
        raise ValueError("DUPLICATE_PACKAGE_EVENT")
    history_path = None
    if config.get("rest_history"):
        history_path, _ = _reference(config_path.resolve().parent, config["rest_history"])
    goalie_path, reports = None, []
    if config.get("goalie_capture"):
        goalie_path, _ = _reference(config_path.resolve().parent, config["goalie_capture"])
        reports = load_goalie_reports(goalie_path)
    forecasts = card["forecasts"]
    if not isinstance(forecasts, list) or not forecasts:
        raise ValueError("NONEMPTY_NHL_CARD_REQUIRED")
    if len({r["event_id"] for r in forecasts}) != len(forecasts):
        raise ValueError("DUPLICATE_CARD_EVENT")
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema": "sports.nhl_context_shadow.v1", "procedure_id": PROCEDURE_ID,
              "parent_card_sha256": hashlib.sha256(card_raw).hexdigest(),
              "config_sha256": hashlib.sha256(config_raw).hexdigest(),
              "parent_package_sha256": hashlib.sha256(package_raw).hexdigest(),
              "cutoff_utc": cutoff, "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "coverage": [], "contexts": [], "forecast_generated": False,
              "parent_forecasts_changed": False, "PREDICTIVE_VALIDATION": "NOT_ASSESSED",
              "PUBLICATION_ELIGIBILITY": "INELIGIBLE", "WAGERING_AUTHORITY": "OFF",
              "provider_authenticity": "NOT_ATTESTED_BY_BYTE_BINDING", "action_authority": False,
              "source_code_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in (Path(__file__).resolve(), ROOT / "models/nhl/context_controls.py",
                                               ROOT / "models/current/freshness.py", ROOT / "scripts/build_operational_rest_candidate.py")}}
    for row in forecasts:
        eid = row["event_id"]
        try:
            event = by_id[eid]
            if row.get("forecast_status") != "FORECAST_GENERATED":
                raise ValueError("PARENT_FORECAST_REQUIRED")
            if row.get("model_id") != package["model_id"]:
                raise ValueError("PARENT_MODEL_BINDING")
            for key in ("home_team", "away_team", "start_time_utc"):
                if row[key] != event[key]:
                    raise ValueError("PARENT_EVENT_BINDING")
            if row.get("model_state_config_hash") != package["model_sha256"]:
                raise ValueError("PARENT_STATE_BINDING")
            goals = goalie_context(event, [r for r in reports if r["event_id"] == eid], cutoff_utc=cutoff,
                                   max_age_hours=config.get("max_goalie_age_hours", 6))
            blockers = ["GOALIE_TRANSFORM_FIT_AND_EVALUATION_REQUIRED", "REST_SUCCESSOR_REFIT_AND_EVALUATION_REQUIRED"]
            if history_path:
                rest = build_rest(package_path, history_path, eid, cutoff, output / "rest" / hashlib.sha256(eid.encode()).hexdigest()[:24])
                if not rest["candidate_ready"]:
                    blockers.append("REST_SOURCE_COVERAGE_UNPROVEN")
            else:
                rest = None
                blockers.append("REST_HISTORY_CAPTURE_REQUIRED")
            if any(r["status"] == "UNKNOWN" for r in goals["per_side"].values()):
                blockers.append("GOALIE_UNKNOWN_OR_CONFLICTED")
            context = {"event_id": eid, "goalies": goals, "rest_candidate": rest,
                       "model_usage": "NOT_USED_BY_PARENT_FORECAST",
                       "data_capture": "COMPLETE" if goals["data_capture"] == "COMPLETE" and rest is not None else "PARTIAL",
                       "personnel_transform": "BLOCKED_UNFITTED", "blocking_reasons": blockers}
            report["contexts"].append(context)
            report["coverage"].append({"event_id": eid, "status": "COMPLETED", "input_eligibility": "BLOCKED",
                                       "blocking_reasons": blockers})
        except (KeyError, TypeError, ValueError) as exc:
            report["coverage"].append({"event_id": eid, "status": "BLOCKED", "reason": str(exc)})
    report["run_id"] = PROCEDURE_ID + ":" + digest({k: v for k, v in report.items() if k != "created_at_utc"})[:20]
    report["EXECUTION_STATUS"] = "COMPLETED" if all(r["status"] == "COMPLETED" for r in report["coverage"]) else "PARTIAL"
    save(output / "report.json", report)
    save(output / "manifest.json", {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in sorted(output.rglob("*")) if p.is_file()})
    return report
