"""Read-only MLS H/D/A adapter with identity/quarantine gates."""
from __future__ import annotations
from typing import Any

from research.adapters.base import (
    Adapted, BaseAdapter, EVALUATABLE_SCOPES, EvaluationError, GradeIndex,
    enforce_requested_scope, event_date_local_from_grade_or_start, exclusion_record,
    grade_status, make_row, multiclass_probabilities, score_actuals, source_scope,
)


class MLSAdapter(BaseAdapter):
    league = "MLS"
    accepted_artifact_schemas = {"mls.hda_matrix_bundle.v1", "mls.dixon_coles_bundle.v1"}

    def adapt(self, payload: dict[str, Any], entry: dict[str, Any], grades: GradeIndex,
              requested_scope: str, *, exclude_statuses: set[str], fail_on_unexpected_row: bool,
              allow_combined_descriptive: bool) -> Adapted:
        self.validate_entry(entry)
        if not isinstance(payload, dict) or not isinstance(payload.get("games"), list):
            raise EvaluationError("MLS artifact must be object with games[]")
        model = payload.get("model_id") or entry.get("model_id")
        cutoff = payload.get("forecast_cutoff_utc") or entry.get("forecast_cutoff_utc")
        if not model or not cutoff:
            raise EvaluationError("MLS bundle missing model/cutoff")
        row_scope = source_scope(entry, payload)
        enforce_requested_scope(row_scope, requested_scope,
                                allow_combined_descriptive=allow_combined_descriptive)
        canonical_eligible = bool(entry.get("canonical_prospective_eligible", False))
        rows, excluded, seen_events, seen_hashes = [], [], set(), set()
        for game in payload["games"]:
            event_id = str(game.get("event_id") or game.get("game_id") or game.get("canonical_game_id") or "")
            if not event_id or event_id in seen_events:
                raise EvaluationError(f"MLS missing/duplicate event id: {event_id!r}")
            seen_events.add(event_id)
            start = game.get("start_utc") or game.get("scheduled_start_utc")
            if not start:
                raise EvaluationError(f"MLS {event_id} missing start")
            try:
                grade = grades.one("MLS", event_id)
            except EvaluationError:
                if fail_on_unexpected_row:
                    raise
                excluded.append(exclusion_record(league="MLS", event_id=event_id,
                                                 reason="MISSING_GRADE", status="UNGRADABLE", model_id=model))
                continue
            status = grade_status(grade)
            identity = grade.get("identity_status") or game.get("identity_status")
            if identity in {"QUARANTINED_IDENTITY_FAILURE", "HOME_AWAY_IDENTITY_FAILURE", "INVALID"}:
                status = "QUARANTINED_IDENTITY_FAILURE"
            if grade.get("postponed") is True:
                status = "POSTPONED"
            if status not in EVALUATABLE_SCOPES:
                if status not in exclude_statuses and fail_on_unexpected_row:
                    raise EvaluationError(f"unexpected MLS grade status {status} for {event_id}")
                excluded.append(exclusion_record(league="MLS", event_id=event_id, reason=status,
                                                 status=status, model_id=model))
                continue
            if status != row_scope:
                raise EvaluationError(f"MLS grade scope {status} != source scope {row_scope}")
            output_hash = game.get("forecast_output_hash") or game.get("output_hash")
            if not output_hash or output_hash in seen_hashes:
                raise EvaluationError(f"duplicate/missing forecast hash: {output_hash}")
            seen_hashes.add(output_hash)
            if grade.get("forecast_output_hash") != output_hash:
                raise EvaluationError(f"MLS {event_id} grade links wrong forecast_output_hash")
            probs = game.get("probabilities") or {}
            actuals = score_actuals(grade)
            outcome = "HOME" if actuals["home_score"] > actuals["away_score"] else (
                      "AWAY" if actuals["home_score"] < actuals["away_score"] else "DRAW")
            rows.append(make_row(
                league="MLS", event_id=event_id,
                event_date_local=event_date_local_from_grade_or_start(grade, start),
                forecast_output_hash=output_hash, grade_record_hash=grade["grade_record_hash"],
                model_id=game.get("model_id") or model, model_arm_id=game.get("model_arm_id") or "hda_matrix",
                experiment_id=entry.get("experiment_id") or payload.get("experiment_id"),
                evidence_scope=row_scope, canonical_prospective_eligible=canonical_eligible,
                forecast_cutoff_utc=game.get("forecast_cutoff_utc") or cutoff,
                scheduled_start_utc=start, graded_at_utc=grade.get("graded_at_utc"),
                outcome_type="MULTICLASS_HDA", outcome_value=outcome,
                probabilities=multiclass_probabilities(probs.get("home_win", game.get("home_win_probability")),
                                                       probs.get("draw", game.get("draw_probability")),
                                                       probs.get("away_win", game.get("away_win_probability"))),
                point_predictions={}, quantiles={}, actuals=actuals,
                data_quality={"identity_status": identity or "VALID"},
                target_contract={"winner_target": "FINAL_HDA"}, score_target_compatible=False,
                score_metrics_excluded_reason="MLS_SCORE_STATE_NOT_IN_V1_REPORT"))
        return Adapted(rows=rows, excluded=excluded)
