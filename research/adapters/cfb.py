"""Read-only CFB adapter for separately frozen model-arm bundles."""
from __future__ import annotations
from typing import Any

from research.adapters.base import (
    Adapted, BaseAdapter, EVALUATABLE_SCOPES, EvaluationError, GradeIndex,
    binary_probabilities, enforce_requested_scope, event_date_local_from_grade_or_start,
    exclusion_record, grade_status, make_row, normalize_quantiles, require_sha256,
    score_actuals, source_scope,
)


class CFBAdapter(BaseAdapter):
    league = "CFB"
    accepted_artifact_schemas = {"cfb.arm_bundle.v1", "cfb.research_score_bundle.v1"}

    def adapt(self, payload: dict[str, Any], entry: dict[str, Any], grades: GradeIndex,
              requested_scope: str, *, exclude_statuses: set[str], fail_on_unexpected_row: bool,
              allow_combined_descriptive: bool) -> Adapted:
        self.validate_entry(entry)
        if not isinstance(payload, dict) or not isinstance(payload.get("games"), list):
            raise EvaluationError("CFB artifact must be object with games[]")
        model_id = payload.get("model_id") or entry.get("model_id")
        arm_id = payload.get("model_arm_id") or payload.get("arm_id") or entry.get("model_arm_id")
        cutoff = payload.get("forecast_cutoff_utc") or entry.get("forecast_cutoff_utc")
        if not model_id or not arm_id or not cutoff:
            raise EvaluationError("CFB arm bundle requires model_id, arm_id, forecast_cutoff_utc")
        experiment_id = payload.get("experiment_id") or entry.get("experiment_id")
        universe_hash = payload.get("paired_game_universe_hash") or entry.get("paired_game_universe_hash")
        if experiment_id and not universe_hash:
            raise EvaluationError("paired CFB experiment missing paired_game_universe_hash")
        if experiment_id:
            require_sha256(universe_hash, "paired_game_universe_hash")
        row_scope = source_scope(entry, payload)
        enforce_requested_scope(row_scope, requested_scope,
                                allow_combined_descriptive=allow_combined_descriptive)
        canonical_eligible = bool(entry.get("canonical_prospective_eligible", False))
        rows, excluded, seen_events, seen_hashes = [], [], set(), set()
        for game in payload["games"]:
            event_id = str(game.get("event_id") or game.get("game_id") or game.get("canonical_game_id") or "")
            if not event_id or event_id in seen_events:
                raise EvaluationError(f"CFB missing/duplicate event id: {event_id!r}")
            seen_events.add(event_id)
            start = game.get("scheduled_start_utc") or game.get("start_utc")
            if not start:
                raise EvaluationError(f"CFB {event_id} missing start")
            try:
                grade = grades.one("CFB", event_id, model_id=model_id, model_arm_id=arm_id,
                                   allow_shared_result_grade=bool(entry.get("allow_shared_result_grade", False)))
            except EvaluationError:
                if fail_on_unexpected_row:
                    raise
                excluded.append(exclusion_record(league="CFB", event_id=event_id, reason="MISSING_GRADE",
                                                 status="UNGRADABLE", model_id=model_id, model_arm_id=arm_id))
                continue
            status = grade_status(grade)
            if status not in EVALUATABLE_SCOPES:
                if status not in exclude_statuses and fail_on_unexpected_row:
                    raise EvaluationError(f"unexpected CFB grade status {status} for {event_id}")
                excluded.append(exclusion_record(league="CFB", event_id=event_id, reason=status, status=status,
                                                 model_id=model_id, model_arm_id=arm_id))
                continue
            if status != row_scope:
                raise EvaluationError(f"CFB grade scope {status} != source scope {row_scope}")
            output_hash = game.get("forecast_output_hash") or game.get("output_hash")
            if not output_hash or output_hash in seen_hashes:
                raise EvaluationError(f"duplicate/missing forecast hash: {output_hash}")
            seen_hashes.add(output_hash)
            if grade.get("forecast_output_hash") != output_hash:
                raise EvaluationError(f"CFB {event_id} grade links wrong forecast_output_hash")
            if grade.get("model_id") not in (None, model_id):
                raise EvaluationError(f"CFB {event_id} grade model mismatch")
            grade_arm = grade.get("model_arm_id") or grade.get("arm_id")
            if grade_arm not in (None, arm_id):
                raise EvaluationError(f"CFB {event_id} grade arm mismatch")
            game_cutoff = game.get("forecast_cutoff_utc") or cutoff
            if grade.get("forecast_cutoff_utc") is not None and grade.get("forecast_cutoff_utc") != game_cutoff:
                raise EvaluationError(f"CFB {event_id} changed/mismatched cutoff")
            actuals = score_actuals(grade)
            if actuals["home_score"] == actuals["away_score"]:
                raise EvaluationError(f"CFB final cannot remain tied: {event_id}")
            outcome = int(actuals["home_score"] > actuals["away_score"])
            p_home = self._first(game, "home_win_probability", "model_home_win_p", "p_home")
            p_away = self._optional(game, "away_win_probability", "model_away_win_p", "p_away")
            home_score = self._optional(game, "home_score_prediction", "model_home_score", "home_expected_score")
            away_score = self._optional(game, "away_score_prediction", "model_away_score", "away_expected_score")
            margin = self._optional(game, "home_margin_prediction", "projected_margin_home", "model_home_margin")
            total = self._optional(game, "total_prediction", "model_total", "expected_total")
            if margin is None and home_score is not None and away_score is not None:
                margin = home_score - away_score
            if total is None and home_score is not None and away_score is not None:
                total = home_score + away_score
            q = game.get("quantiles") or {}
            quantiles = {target: normalize_quantiles(q.get(target))
                         for target in ("home_score", "away_score", "home_margin", "total")}
            contract = dict(payload.get("target_contract") or entry.get("target_contract") or {})
            contract.setdefault("winner_target", "FINAL_WINNER_WITH_DISCLOSED_OT_PROXY")
            contract.setdefault("margin_target", "DECLARED_CFB_SCORE_DISTRIBUTION")
            contract.setdefault("total_target", "DECLARED_CFB_SCORE_DISTRIBUTION")
            pairing = None
            if experiment_id:
                pairing = {"experiment_id": experiment_id, "paired_game_universe_hash": universe_hash,
                           "pair_role": payload.get("pair_role") or entry.get("pair_role"),
                           "paired_with_model_id": payload.get("paired_with_model_id") or entry.get("paired_with_model_id")}
            rows.append(make_row(
                league="CFB", event_id=event_id,
                event_date_local=event_date_local_from_grade_or_start(grade, start),
                forecast_output_hash=output_hash, grade_record_hash=grade["grade_record_hash"],
                model_id=model_id, model_arm_id=arm_id, experiment_id=experiment_id,
                evidence_scope=row_scope, canonical_prospective_eligible=canonical_eligible,
                forecast_cutoff_utc=game_cutoff, scheduled_start_utc=start,
                graded_at_utc=grade.get("graded_at_utc"), outcome_type="BINARY_HOME_WIN",
                outcome_value=outcome, probabilities=binary_probabilities(p_home, p_away),
                point_predictions={"home_score": home_score, "away_score": away_score,
                                   "home_margin": margin, "total": total},
                quantiles=quantiles, actuals=actuals, data_quality=dict(game.get("data_quality") or {}),
                target_contract=contract, score_target_compatible=True,
                score_metrics_excluded_reason=None, pairing=pairing))
        return Adapted(rows=rows, excluded=excluded)

    @staticmethod
    def _first(record: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if record.get(key) is not None:
                return record[key]
        raise EvaluationError(f"missing required CFB field; expected one of {keys}")

    @staticmethod
    def _optional(record: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if record.get(key) is not None:
                return record[key]
        return None
