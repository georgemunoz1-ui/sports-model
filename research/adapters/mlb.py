"""Read-only MLB adapter for frozen Phase 1.1 dual-estimator artifacts."""
from __future__ import annotations
from typing import Any

from research.adapters.base import (
    Adapted, BaseAdapter, EVALUATABLE_SCOPES, EvaluationError, GradeIndex,
    binary_probabilities, digest, enforce_requested_scope,
    event_date_local_from_grade_or_start, exclusion_record, grade_status, make_row,
    quantiles_from_prefix, score_actuals, source_scope,
)

EXPERIMENT_ID = "mlb.fixed_poisson_vs_gamma_poisson_workload.v1"
ARM_CONTRACTS = {
    "analytic": "fixed_poisson.v1",
    "monte_carlo": "gamma_poisson_workload_mc.v1",
}


def _first(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _orientation_hash(game: dict[str, Any], entry: dict[str, Any], payload: dict[str, Any]):
    explicit = _first(game.get("event_orientation_hash"), entry.get("event_orientation_hash"),
                      payload.get("event_orientation_hash"))
    if explicit:
        return explicit
    away = _first(game.get("away_team_id"), game.get("away_team"), game.get("away_abbr"))
    home = _first(game.get("home_team_id"), game.get("home_team"), game.get("home_abbr"))
    return digest({"away": str(away), "home": str(home)}) if away is not None and home is not None else None


def _source_hash_set_hash(game: dict[str, Any], entry: dict[str, Any], payload: dict[str, Any]):
    explicit = _first(game.get("source_input_hash_set_hash"), entry.get("source_input_hash_set_hash"),
                      payload.get("source_input_hash_set_hash"))
    if explicit:
        return explicit
    source_hashes = _first(game.get("source_input_hashes"), entry.get("source_input_hashes"),
                           payload.get("source_input_hashes"))
    if isinstance(source_hashes, list):
        return digest(sorted(source_hashes))
    if isinstance(source_hashes, dict):
        return digest(source_hashes)
    return None


def _pairing_metadata(*, payload: dict[str, Any], entry: dict[str, Any], game: dict[str, Any],
                      forecast: dict[str, Any], arm: str, universe_hash: str):
    if entry.get("experiment_id") != EXPERIMENT_ID:
        return None
    home_runs = forecast.get("home_expected_runs")
    away_runs = forecast.get("away_expected_runs")
    names = _first(forecast.get("predictive_input_field_names"), game.get("predictive_input_field_names"),
                   payload.get("predictive_input_field_names"), entry.get("predictive_input_field_names"))
    if names is None:
        names = []
    if not isinstance(names, list) or any(not isinstance(x, str) for x in names):
        raise EvaluationError("predictive_input_field_names must be a string list")
    market_used = _first(forecast.get("market_input_used"), game.get("market_input_used"),
                         payload.get("market_input_used"), entry.get("market_input_used"),
                         forecast.get("market_inputs_used"), game.get("market_inputs_used"),
                         payload.get("market_inputs_used"), entry.get("market_inputs_used"))
    if market_used is True:
        raise EvaluationError("MARKET_INPUT_FORBIDDEN_IN_DISTRIBUTION_EXPERIMENT")
    feature_contract = _first(forecast.get("feature_contract_version"), game.get("feature_contract_version"),
                              payload.get("feature_contract_version"), entry.get("feature_contract_version"))
    model_code = _first(forecast.get("model_code_identity"), payload.get("model_code_identity"),
                        entry.get("model_code_identity"))
    simulation_seed = _first(forecast.get("simulation_seed"), forecast.get("seed")) if arm == "monte_carlo" else None
    output_hash = forecast.get("forecast_output_hash") if arm == "analytic" else forecast.get("simulation_output_hash")
    if arm == "analytic":
        context = {
            "distribution_contract_id": ARM_CONTRACTS[arm],
            "forecast_output_hash": output_hash,
            "analytic_home_win_probability": forecast.get("analytic_home_win_probability"),
            "home_expected_runs": home_runs,
            "away_expected_runs": away_runs,
            "tie_resolution_method": forecast.get("tie_resolution_method"),
        }
    else:
        context = {
            "distribution_contract_id": ARM_CONTRACTS[arm],
            "forecast_output_hash": output_hash,
            "sim_home_win_probability": forecast.get("sim_home_win_probability"),
            "mean_margin_home": forecast.get("mean_margin_home"),
            "mean_total": forecast.get("mean_total"),
            "simulation_seed": simulation_seed,
            "simulation_count": _first(forecast.get("simulation_count"), payload.get("simulation_count"),
                                       entry.get("simulation_count")),
        }
    return {
        "experiment_id": EXPERIMENT_ID,
        "paired_game_universe_hash": _first(entry.get("paired_game_universe_hash"),
                                             payload.get("paired_game_universe_hash"), universe_hash),
        "event_orientation_hash": _orientation_hash(game, entry, payload),
        "expected_run_input_hash": digest({"home_expected_runs": home_runs, "away_expected_runs": away_runs}),
        "feature_contract_version": feature_contract,
        "source_input_hash_set_hash": _source_hash_set_hash(game, entry, payload),
        "model_code_identity": model_code,
        "predictive_input_field_names": sorted(names),
        "market_input_used": market_used,
        "distribution_contract_id": ARM_CONTRACTS[arm],
        "arm_context_hash": digest(context),
        "simulation_seed": simulation_seed,
    }


class MLBAdapter(BaseAdapter):
    league = "MLB"
    accepted_artifact_schemas = {"mlb.phase1_1_shadow.v1", "mlb.phase1_1_shadow.2026-09"}

    def adapt(self, payload: dict[str, Any], entry: dict[str, Any], grades: GradeIndex,
              requested_scope: str, *, exclude_statuses: set[str], fail_on_unexpected_row: bool,
              allow_combined_descriptive: bool) -> Adapted:
        self.validate_entry(entry)
        if not isinstance(payload, dict) or not isinstance(payload.get("games"), list):
            raise EvaluationError("MLB artifact must be object with games[]")
        root_cutoff = payload.get("forecast_cutoff_utc")
        root_model = payload.get("model_id")
        if not root_cutoff or not root_model:
            raise EvaluationError("MLB artifact missing root cutoff/model_id")
        row_scope = source_scope(entry, payload)
        enforce_requested_scope(row_scope, requested_scope,
                                allow_combined_descriptive=allow_combined_descriptive)
        canonical_eligible = bool(entry.get("canonical_prospective_eligible", False))
        rows, excluded, seen_events, seen_hashes = [], [], set(), set()
        universe_ids = []
        for game in payload["games"]:
            eid = str(game.get("game_id") or game.get("canonical_game_id") or "")
            if not eid:
                raise EvaluationError("MLB missing event id")
            universe_ids.append(eid)
        if len(set(universe_ids)) != len(universe_ids):
            raise EvaluationError("MLB duplicate event id in frozen universe")
        universe_hash = digest(sorted(universe_ids))

        for game in payload["games"]:
            event_id = str(game.get("game_id") or game.get("canonical_game_id") or "")
            if not event_id or event_id in seen_events:
                raise EvaluationError(f"MLB missing/duplicate event id: {event_id!r}")
            seen_events.add(event_id)
            start = game.get("start_utc")
            forecast = game.get("forecast")
            if not start or not isinstance(forecast, dict):
                raise EvaluationError(f"MLB game {event_id} missing start/forecast")
            try:
                grade = grades.one("MLB", event_id)
            except EvaluationError:
                if fail_on_unexpected_row:
                    raise
                excluded.append(exclusion_record(league="MLB", event_id=event_id,
                                                 reason="MISSING_GRADE", status="UNGRADABLE",
                                                 model_id=root_model))
                continue
            status = grade_status(grade)
            if status not in EVALUATABLE_SCOPES:
                if status not in exclude_statuses and fail_on_unexpected_row:
                    raise EvaluationError(f"unexpected MLB grade status {status} for {event_id}")
                excluded.append(exclusion_record(league="MLB", event_id=event_id, reason=status,
                                                 status=status, model_id=root_model))
                continue
            if status != row_scope:
                raise EvaluationError(f"MLB grade scope {status} disagrees with frozen source scope {row_scope}")

            record_hash = game.get("forecast_record_hash")
            if not record_hash or grade.get("forecast_record_hash") != record_hash:
                raise EvaluationError(f"MLB {event_id} grade links wrong forecast record hash")
            actuals = score_actuals(grade)
            if actuals["home_score"] == actuals["away_score"]:
                raise EvaluationError(f"MLB final cannot be tied: {event_id}")
            outcome = int(actuals["home_score"] > actuals["away_score"])
            graded_at = grade.get("graded_at_utc")
            if not graded_at:
                raise EvaluationError(f"MLB {event_id} missing graded_at_utc")
            event_date = event_date_local_from_grade_or_start(grade, start)
            extras = bool(grade.get("went_extra_innings", False))
            if grade.get("innings_played") is not None:
                try:
                    extras = extras or float(grade["innings_played"]) > 9.0
                except Exception as exc:
                    raise EvaluationError(f"invalid innings_played for {event_id}") from exc
            score_ok = not extras
            score_reason = None if score_ok else "EXTRA_INNINGS_UNSUPPORTED"
            dq = self._data_quality(game)
            cutoff = game.get("forecast_cutoff_utc") or root_cutoff
            model_id = forecast.get("model_id") or root_model
            contract = {"winner_target": "MODEL_WINNER_WITH_DISCLOSED_TIE_PROXY",
                        "margin_target": "REGULATION_ONLY", "total_target": "REGULATION_ONLY",
                        "tie_resolution_method": forecast.get("tie_resolution_method")}

            analytic_hash = forecast.get("forecast_output_hash")
            if not analytic_hash or analytic_hash in seen_hashes:
                raise EvaluationError(f"duplicate/missing forecast hash: {analytic_hash}")
            seen_hashes.add(analytic_hash)
            if grade.get("forecast_output_hash") is not None and grade.get("forecast_output_hash") != analytic_hash:
                raise EvaluationError(f"MLB {event_id} grade links wrong forecast_output_hash")
            home_runs, away_runs = forecast.get("home_expected_runs"), forecast.get("away_expected_runs")
            points = {"home_runs": home_runs, "away_runs": away_runs, "home_margin": None, "total": None}
            if home_runs is not None and away_runs is not None:
                points["home_margin"] = home_runs - away_runs
                points["total"] = home_runs + away_runs
            rows.append(make_row(
                league="MLB", event_id=event_id, event_date_local=event_date,
                forecast_output_hash=analytic_hash, grade_record_hash=grade["grade_record_hash"],
                model_id=model_id, model_arm_id="analytic", experiment_id=entry.get("experiment_id"),
                evidence_scope=row_scope, canonical_prospective_eligible=canonical_eligible,
                forecast_cutoff_utc=cutoff, scheduled_start_utc=start, graded_at_utc=graded_at,
                outcome_type="BINARY_HOME_WIN", outcome_value=outcome,
                probabilities=binary_probabilities(forecast.get("analytic_home_win_probability"),
                                                   forecast.get("analytic_away_win_probability")),
                point_predictions=points, quantiles={}, actuals=actuals, data_quality=dq,
                target_contract=contract, score_target_compatible=score_ok,
                score_metrics_excluded_reason=score_reason,
                pairing=_pairing_metadata(payload=payload, entry=entry, game=game, forecast=forecast,
                                          arm="analytic", universe_hash=universe_hash)))

            sim_hash = forecast.get("simulation_output_hash")
            if not sim_hash or sim_hash in seen_hashes:
                raise EvaluationError(f"duplicate/missing forecast hash: {sim_hash}")
            seen_hashes.add(sim_hash)
            margin, total = forecast.get("mean_margin_home"), forecast.get("mean_total")
            sim_points = {"home_runs": None, "away_runs": None, "home_margin": margin, "total": total}
            if margin is not None and total is not None:
                sim_points["home_runs"] = (total + margin) / 2.0
                sim_points["away_runs"] = (total - margin) / 2.0
            rows.append(make_row(
                league="MLB", event_id=event_id, event_date_local=event_date,
                forecast_output_hash=sim_hash, grade_record_hash=grade["grade_record_hash"],
                model_id=model_id, model_arm_id="monte_carlo", experiment_id=entry.get("experiment_id"),
                evidence_scope=row_scope, canonical_prospective_eligible=canonical_eligible,
                forecast_cutoff_utc=cutoff, scheduled_start_utc=start, graded_at_utc=graded_at,
                outcome_type="BINARY_HOME_WIN", outcome_value=outcome,
                probabilities=binary_probabilities(forecast.get("sim_home_win_probability"),
                                                   forecast.get("sim_away_win_probability")),
                point_predictions=sim_points,
                quantiles={"home_margin": quantiles_from_prefix(forecast, "margin"),
                           "total": quantiles_from_prefix(forecast, "total")},
                actuals=actuals, data_quality=dq, target_contract=contract,
                score_target_compatible=score_ok, score_metrics_excluded_reason=score_reason,
                pairing=_pairing_metadata(payload=payload, entry=entry, game=game, forecast=forecast,
                                          arm="monte_carlo", universe_hash=universe_hash)))
        return Adapted(rows=rows, excluded=excluded)

    @staticmethod
    def _data_quality(game: dict[str, Any]) -> dict[str, Any]:
        lineups = game.get("lineup_snapshots") or {}
        lineup = [x.get("lineup_state") for x in lineups.values() if isinstance(x, dict)]
        bullpens = game.get("bullpen_snapshots") or {}
        bullpen = [x.get("bullpen_state") for x in bullpens.values() if isinstance(x, dict)]
        return {"lineup_state": lineup[0] if lineup else None,
                "bullpen_state": bullpen[0] if bullpen else None,
                "weather_state": (game.get("weather") or {}).get("state"),
                "roof_state": (game.get("roof") or {}).get("state"),
                "source_flags": list(game.get("data_quality") or [])}
