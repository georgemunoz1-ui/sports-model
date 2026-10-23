"""Synthetic regression fixtures only: no predictive evidence from these tests."""
import copy
import math

import numpy as np
import pandas as pd
import pytest

from models.experiments import cfb_efficiency as c


def history():
    games, metrics = [], []
    gid = 1000
    for season in range(2019, 2027):
        for week in range(1, 7):
            gid += 1
            start = pd.Timestamp(f"{season}-09-01T18:00:00Z") + pd.Timedelta(days=7 * (week - 1))
            home, away = ("1", "2") if week % 2 else ("2", "1")
            g = {"game_id": gid, "season": season, "week": week, "home_id": home, "away_id": away,
                 "home_team": "A" if home == "1" else "B", "away_team": "A" if away == "1" else "B",
                 "home_points": 24 + week % 3, "away_points": 20 + week % 4 * 3,
                 "home_division": "fbs", "away_division": "fbs", "start_date": start.isoformat(),
                 "completed": True, "neutral_site": False, "conference_game": True}
            games.append(g)
            for team, opponent in ((home, away), (away, home)):
                metrics.append({"event_id": f"CFB:{gid}", "season": season, "week": week,
                                "team_id": team, "opponent_id": opponent, "start_time_utc": start.isoformat(),
                                "available_at_utc": (start + pd.Timedelta(days=1)).isoformat(),
                                "pass_plays": 30, "rush_plays": 30,
                                "pass_epa_sum": float(week - 3 + int(team)), "rush_epa_sum": float(2 - week + int(team)),
                                "pass_successes": 12 + week, "rush_successes": 18 - week,
                                "source": {"source": "synthetic://cfb-fixture", "sha256": "a" * 64,
                                           "retrieved_at_utc": "2026-10-23T09:00:00Z"}})
    return {"games": games, "team_games": metrics}


def prepared():
    return c.prepare_examples(history())


def test_target_outcome_changes_do_not_change_its_features():
    h = history()
    before = c.prepare_examples(h)[-1]
    h["games"][-1]["home_points"] = 70
    h["team_games"][-1]["pass_epa_sum"] = 1000
    after = c.prepare_examples(h)[-1]
    assert before["features"] == after["features"]
    assert before["component_state_sha256"] == after["component_state_sha256"]
    assert before["target"] != after["target"]
    assert c.utc(after["cutoff_utc"]) < c.utc(after["start_time_utc"])


def test_same_week_legacy_history_is_explicitly_blocked():
    h = history()
    h["games"][-1]["week"] = h["games"][-2]["week"]
    h["team_games"][-1]["week"] = h["games"][-1]["week"]
    h["team_games"][-2]["week"] = h["games"][-1]["week"]
    examples = c.prepare_examples(h)
    assert "LEGACY_BASELINE_FEATURES_AFTER_WEEK_CUTOFF" in examples[-1]["reasons"]
    assert examples[-1]["components"] == examples[-2]["components"] or not examples[-1]["eligible"]


def test_missing_latest_metric_game_is_not_silent_stale_state():
    h = history()
    h["team_games"] = h["team_games"][:-4] + h["team_games"][-2:]
    r = c.prepare_examples(h)[-1]
    assert "HOME_LATEST_FBS_EFFICIENCY_GAME_MISSING" in r["reasons"]
    assert not r["eligible"]


@pytest.mark.parametrize("bad", [None, True, "bad", 0, 1.5])
def test_bad_provider_identity_rejected(bad):
    g = history()["games"][0]
    g["home_id"] = bad
    with pytest.raises(ValueError):
        c.canonical_game(g)


def test_conflicting_metric_identity_rejected():
    h = history()
    h["team_games"][0]["opponent_id"] = "3"
    with pytest.raises(ValueError, match="TEAM_ID_MISMATCH"):
        c.prepare_examples(h)


def test_impossible_success_count_rejected():
    h = history()
    h["team_games"][0]["pass_successes"] = 31
    with pytest.raises(ValueError, match="SUCCESS_COUNT"):
        c.prepare_examples(h)


def test_fitted_receipt_reconciles_logit_and_margin_components():
    examples = prepared()
    state = c.fit([r for r in examples if r["season"] <= 2024], {"minimum_training_rows": 10})
    prediction = c.predict(state, examples[-1])
    components = prediction["components"]
    logit = components["winner_intercept"] + sum(v for k, v in components.items() if k.startswith("winner_contribution_"))
    margin = components["margin_intercept"] + sum(v for k, v in components.items() if k.startswith("margin_contribution_"))
    assert prediction["p_home"] == pytest.approx(1 / (1 + math.exp(-logit)))
    assert prediction["home_margin"] == pytest.approx(margin)
    assert prediction["total"] is None


def test_fitted_state_mutation_rejected():
    examples = prepared()
    state = c.fit([r for r in examples if r["season"] <= 2024], {"minimum_training_rows": 10})
    state["fitted_model"]["winner"]["intercept"] += 5
    with pytest.raises(ValueError, match="STATE_DIGEST"):
        c.predict(state, examples[-1])


def test_fit_cannot_silently_change_feature_transform():
    with pytest.raises(ValueError, match="FEATURE_CONFIG_DRIFT"):
        c.fit([r for r in prepared() if r["season"] <= 2024], {"minimum_training_rows": 10, "opponent_ridge_alpha": 50.0})


def test_actual_control_preserves_minimum_history_and_matched_control_has_distinct_id():
    train = [r for r in prepared() if r["season"] <= 2024]
    with pytest.raises(ValueError, match="INCUMBENT_MINIMUM_HISTORY"):
        c.fit_control(train, {"minimum_training_rows": 10})
    matched = c.fit_matched_control(train, {"minimum_training_rows": 10})
    assert matched["model_id"] == c.MATCHED_CONTROL_ID
    assert matched["feature_names"] == c.BASELINE_FEATURES


def test_personnel_does_not_impute_unknown_availability_to_zero():
    with pytest.raises(ValueError, match="PERSONNEL_SOURCE_BOUND"):
        c.fit_personnel([r for r in prepared() if r["season"] <= 2024], {"minimum_training_rows": 10})


def test_personnel_known_values_still_require_pre_cutoff_sources():
    row = prepared()[-1]
    row["personnel_features"] = {key: 1.0 for key in c.PERSONNEL_FEATURES}
    row["personnel_sources"] = [{"source": "synthetic://personnel", "sha256": "a" * 64,
                                 "available_at_utc": row["start_time_utc"]}]
    with pytest.raises(ValueError, match="PERSONNEL_AFTER_CUTOFF"):
        c.personnel_values(row)


def test_joint_stage_never_claims_unfitted_distribution():
    examples = prepared()
    with pytest.raises(ValueError, match="JOINT_CALIBRATION_POPULATION"):
        c.fit_joint([r for r in examples if r["season"] < 2024], [r for r in examples if r["season"] == 2024], {"minimum_training_rows": 10})
