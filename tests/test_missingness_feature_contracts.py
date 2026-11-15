"""Unregistered transformed inputs must not acquire substantive attribution.

The forecasts here use synthetic fitted parameters through the real adapters.
These checks cover engineering declarations, not independent statistical review.
"""
import copy
import importlib

import pytest

from pipelines.cards.missingness import verify_audit
from pipelines.cards.shared_missingness import attach_shared_audit, binding
from scripts.generate_card_force import normalize
from test_selected_market_independence import CUTOFF, package


def current_row(league, tmp_path, monkeypatch):
    packed = package(league)
    event = packed["events"][0]
    context = {"package": packed, "package_sha256": "SYNTHETIC_TEST", "cutoff": CUTOFF}
    monkeypatch.setenv("SPORTS_INITIAL_BASELINES", "1")
    monkeypatch.setenv("SPORTS_RESEARCH_DRAW_OUTPUT", str(tmp_path / league))
    adapter = importlib.import_module("pipelines.cards.adapters." + league)
    row = normalize(event, adapter.forecast_event(event, context, 97))
    return row, event, context


def test_unregistered_cfb_column_cannot_be_described_as_substantive(tmp_path, monkeypatch):
    row, event, context = current_row("cfb", tmp_path, monkeypatch)
    # Identical columns and coefficients; only the feature's unregistered meaning changes.
    name = "home_ewma_points_for"
    undocumented = "collector_worked"
    row["model_input_snapshot"][undocumented] = row["model_input_snapshot"].pop(name)
    names = context["package"]["feature_names"]
    names[names.index(name)] = undocumented
    original = copy.deepcopy(row)
    attach_shared_audit("cfb", row, event, context, CUTOFF)
    evidence = row["missingness_audit"]["details"]
    assert evidence["status"] == "TRACE_BLOCKED"
    assert undocumented in evidence["feature_contracts"]["unregistered_features"]
    assert evidence["feature_contracts"]["status"] == "INCOMPLETE_ENGINEERING_INVENTORY"
    assert {key: value for key, value in row.items() if key != "missingness_audit"} == original
    assert verify_audit(row["missingness_audit"], **binding(row, "cfb", CUTOFF))
    assert row["missingness_audit"]["release_status"] == "HOLD_PENDING_SCOPE_REVIEW"


@pytest.mark.parametrize("league", ["nba", "nhl", "mls", "cfb"])
def test_each_consumed_feature_has_head_specific_contract_without_claiming_review(league, tmp_path, monkeypatch):
    row, event, context = current_row(league, tmp_path, monkeypatch)
    original = copy.deepcopy(row)
    attach_shared_audit(league, row, event, context, CUTOFF)
    evidence = row["missingness_audit"]["details"]
    contracts = evidence["feature_contracts"]
    assert contracts["status"] == "COMPLETE_ENGINEERING_INVENTORY"
    assert contracts["review_status"] == "ENGINEERING_INVENTORY_PENDING_INDEPENDENT_MODEL_REVIEW"
    assert not contracts["unregistered_features"]
    assert set(contracts["features"]) == set(row["model_input_snapshot"])
    for name, contract in contracts["features"].items():
        for field in ("definition", "source", "freshness_requirement", "missing_representation",
                      "imputation_rule", "missingness_indicator_usage", "fallback_or_refusal", "input_unit"):
            assert isinstance(contract[field], str) and contract[field]
        assert contract["model_id"] == row["model_id"]
        assert contract["current_pattern"]["raw_value"] == row["model_input_snapshot"][name]
        assert contract["historical_pattern"]["status"] == "UNMEASURED"
        assert set(contract["heads"]) == set(context["package"]["fitted_model"])
        for head, use in contract["heads"].items():
            assert use["consumed"] is True
            assert use["fitted_kind"] == context["package"]["fitted_model"][head]["kind"]
            assert use["fitted_artifact_sha256"] == contracts["fitted_artifact_sha256"]
            assert isinstance(use["imputation_value"], (int, float))
    assert {key: value for key, value in row.items() if key != "missingness_audit"} == original
    assert evidence["status"] == "FITTED_HEADS_REPLAYED"


@pytest.mark.parametrize("drift", ["model", "head", "kind"])
def test_unknown_arm_and_head_do_not_inherit_feature_contracts(tmp_path, monkeypatch, drift):
    row, event, context = current_row("cfb", tmp_path, monkeypatch)
    if drift == "model":
        row["model_id"] = "cfb.unreviewed.replacement"
    elif drift == "head":
        fit = context["package"]["fitted_model"]
        fit["renamed_margin"] = fit.pop("margin")
    else:
        from models.current.linear import predict
        packed = context["package"]
        packed["fitted_model"]["margin"]["kind"] = "logistic"
        values = [row["model_input_snapshot"][name] for name in packed["feature_names"]]
        row["diagnostics"]["home_margin"] = predict(packed["fitted_model"]["margin"], values)
    attach_shared_audit("cfb", row, event, context, CUTOFF)
    assert row["missingness_audit"]["details"]["status"] == "TRACE_BLOCKED"
    key = "model_scope_matches" if drift == "model" else "head_scope_matches"
    assert row["missingness_audit"]["details"]["feature_contracts"][key] is False


def test_observed_zero_and_missing_history_are_distinct_in_contract(tmp_path, monkeypatch):
    row, event, context = current_row("cfb", tmp_path, monkeypatch)
    # Recompute through the native transform after withholding the state, with one observed zero.
    from models.current import cfb
    from models.current.linear import predict
    packed = context["package"]
    packed["team_state"]["ewpf"]["HOME"] = 0.
    del packed["team_state"]["ewpf"]["AWAY"]
    row["model_input_snapshot"] = cfb.feature_row(packed["team_state"], event, packed["parameters"])
    values = [row["model_input_snapshot"][name] for name in packed["feature_names"]]
    row["diagnostics"]["home_win"] = predict(packed["fitted_model"]["winner"], values)
    row["diagnostics"]["home_margin"] = predict(packed["fitted_model"]["margin"], values)
    attach_shared_audit("cfb", row, event, context, CUTOFF)
    entries = row["missingness_audit"]["details"]["feature_contracts"]["features"]
    assert entries["home_ewma_points_for"]["current_pattern"] == {
        "raw_value": 0., "input_state": "OBSERVED_TRANSFORMED"}
    assert entries["away_ewma_points_for"]["current_pattern"] == {
        "raw_value": None, "input_state": "IMPUTED_TRAINING_MEDIAN"}
    assert "None" in entries["away_ewma_points_for"]["missing_representation"]


def test_historical_count_support_never_invents_provider_coverage(tmp_path, monkeypatch):
    row, event, context = current_row("nba", tmp_path, monkeypatch)
    packed = context["package"]
    packed["missingness_training_support"] = {
        "basis": "DEPLOYMENT_FIT_ROWS_BEFORE_IMPUTATION",
        "limitation": "Upstream defaults are not identifiable from normalized vectors.",
        "by_season": {"2025": {"rows": 17, "missing": {"home_cold": 0}, "cold_indicators": {"home_cold": 3}}}}
    attach_shared_audit("nba", row, event, context, CUTOFF)
    entries = row["missingness_audit"]["details"]["feature_contracts"]["features"]
    history = entries["home_cold"]["historical_pattern"]
    assert history["status"] == "PACKAGE_RECORDED_NOT_INDEPENDENTLY_REVIEWED"
    assert history["by_season"]["2025"] == {"rows": 17, "missing": 0, "cold_indicator": 3}
    assert history["provider_coverage"] == "NOT_ESTABLISHED"
    assert entries["away_for"]["historical_pattern"]["status"] == "UNMEASURED"


def test_unknown_season_marker_and_normalized_flags_remain_unresolved(tmp_path, monkeypatch):
    row, event, context = current_row("cfb", tmp_path, monkeypatch)
    attach_shared_audit("cfb", row, event, context, CUTOFF)
    entries = row["missingness_audit"]["details"]["feature_contracts"]["features"]
    assert entries["elo_diff_with_home_advantage"]["current_pattern"]["input_state"] == "ELO_SEASON_MARKER_UNRESOLVED"
    for name in ("neutral_site", "conference_game"):
        assert entries[name]["current_pattern"]["input_state"] == "NORMALIZED_SCHEDULE_FLAG_RAW_MISSINGNESS_UNRESOLVED"


def test_malformed_head_keeps_the_research_row_and_reports_trace_failure(tmp_path, monkeypatch):
    row, event, context = current_row("nba", tmp_path, monkeypatch)
    original = copy.deepcopy(row)
    context["package"]["fitted_model"]["winner"]["impute"] = []
    attach_shared_audit("nba", row, event, context, CUTOFF)
    assert row["missingness_audit"]["details"]["reason"] == "FITTED_HEAD_CONTRACT_SHAPE_MISMATCH"
    assert {key: value for key, value in row.items() if key != "missingness_audit"} == original

