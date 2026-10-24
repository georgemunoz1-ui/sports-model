"""Numerical, chronology and identity guards; synthetic fixtures are not sports evidence."""
import copy
import datetime as dt
import hashlib
import json

import numpy as np
import pytest

from models.experiments import nba_efficiency as nba


def games(n=240):
    rng = np.random.default_rng(81)
    result = []
    for i in range(n):
        season = 2023 if i < 140 else 2024
        start = dt.datetime(season - 1, 10, 1, 20, tzinfo=dt.timezone.utc) + dt.timedelta(days=(i if i < 140 else i - 140) * 2)
        boxes = []
        for _ in range(2):
            fgm, fg3m, ftm = (int(rng.integers(32, 48)), int(rng.integers(5, 15)), int(rng.integers(8, 23)))
            boxes.append(dict(fgm=fgm, fga=int(rng.integers(85, 99)), fg3m=fg3m,
                              fg3a=int(rng.integers(29, 40)), ftm=ftm, fta=ftm + int(rng.integers(2, 8)),
                              orb=int(rng.integers(8, 17)), drb=int(rng.integers(25, 40)), tov=int(rng.integers(7, 21))))
        scores = [2*b["fgm"]+b["fg3m"]+b["ftm"] for b in boxes]
        if scores[0] == scores[1]:
            boxes[0]["ftm"] += 1
            scores[0] += 1
        result.append({"event_id": f"NBA:test-{i}", "start_time_utc": start.isoformat(),
                       "season": season, "home_id": "1", "away_id": "2", "home_team": "Home", "away_team": "Away",
                       "home_score": scores[0], "away_score": scores[1], "home_stats": boxes[0], "away_stats": boxes[1],
                       "neutral_site": False, "final": True,
                       "sources": [{"source": "TEST_ONLY", "sha256": "a"*64, "retrieved_at_utc": "2026-10-23T09:00:00+00:00", "observed_at_utc": None}]})
    return result


def test_hand_computed_possession_and_four_factors():
    g = games(1)[0]
    g["home_stats"] = dict(fgm=40, fga=90, fg3m=10, fg3a=30, ftm=10, fta=20, orb=10, drb=30, tov=10)
    g["away_stats"] = dict(fgm=35, fga=85, fg3m=8, fg3a=30, ftm=12, fta=20, orb=10, drb=30, tov=15)
    g.update(home_score=100, away_score=90)
    r = nba.game_rates(g)
    assert r["home"]["possessions"] == pytest.approx(98.8)
    assert r["home"]["off_efg"] == .5
    assert r["home"]["off_orb"] == .25
    assert r["home"]["off_efficiency"] == pytest.approx(10000/98.8)
    assert r["home"]["def_efficiency"] == r["away"]["off_efficiency"]


@pytest.mark.parametrize("mutation,error", [
    (lambda g: g.update(away_id="1"), "SELF_MATCH"),
    (lambda g: g.update(home_score=g["home_score"]+1), "POINTS_CONFLICT"),
    (lambda g: g["home_stats"].update(fgm=1000), "MAKES_EXCEED_ATTEMPTS"),
    (lambda g: g["home_stats"].update(fga=True), "INVALID_NUMBER"),
    (lambda g: g.update(sources=[]), "SOURCE_RECEIPTS_REQUIRED"),
])
def test_source_reconciliation_rejects(mutation, error):
    g = games(1)[0]
    mutation(g)
    with pytest.raises(ValueError, match=error):
        nba.validate_game(g)


def test_current_target_never_changes_own_features():
    history = games(30)
    before = nba.prepare_examples(history)
    history[20]["home_stats"]["ftm"] += 1
    history[20]["home_score"] += 1
    after = nba.prepare_examples(history)
    assert before[20]["features"] == after[20]["features"]
    assert before[20]["targets"] != after[20]["targets"]
    assert before[21]["features"] != after[21]["features"]
    assert history[20]["event_id"] not in before[20]["history_event_ids"]


def test_future_rows_never_change_existing_forecast_features():
    history = games(30)
    before = nba.prepare_examples(history)
    history[-1]["home_stats"]["tov"] += 25
    after = nba.prepare_examples(history)
    assert [r["features"] for r in before] == [r["features"] for r in after]


def test_result_availability_adds_to_embargo():
    history = games(30)
    history[10]["result_available_at_utc"] = history[29]["start_time_utc"]
    rows = nba.prepare_examples(history)
    assert history[10]["event_id"] not in rows[20]["history_event_ids"]


def test_previous_utc_day_excluded_and_missing_target_never_advances():
    history = games(30)
    history[20]["home_score"] += 1  # inconsistent source gets quarantined
    rows = nba.prepare_examples(history)
    assert not rows[20]["eligible"]
    assert history[20]["event_id"] not in rows[21]["history_event_ids"]
    for row in rows:
        if row["eligible"]:
            boundary = nba.history_boundary(row["cutoff_utc"])
            assert nba._utc(row["history_max_event_time_utc"]) < boundary


def test_duplicate_ids_rejected():
    history = games(10)
    history.append(copy.deepcopy(history[-1]))
    with pytest.raises(ValueError, match="DUPLICATE_EVENT"):
        nba.prepare_examples(history)


def test_unknown_history_excluded_not_imputed():
    rows = nba.prepare_examples(games(10))
    assert rows[0]["features"] is None
    assert not rows[0]["eligible"]
    assert "HOME_INSUFFICIENT_PRIOR_GAMES" in rows[0]["exclusion_reasons"]


def test_fit_predict_components_and_no_target_dependency():
    rows = nba.prepare_examples(games(240))
    state = nba.fit(rows[:220])
    prediction = nba.predict(state, rows[230])
    assert prediction["home_score"] == pytest.approx(prediction["components"]["expected_possessions"] * prediction["components"]["home_efficiency_per100"] / 100)
    assert prediction["total"] == pytest.approx(prediction["home_score"] + prediction["away_score"])
    assert 0 < prediction["p_home"] < 1
    assert prediction["probability_semantics"] == "SEPARATE_LOGISTIC_WINNER_HEAD"
    changed = copy.deepcopy(rows[230]); changed["targets"]["home_score"] += 1000
    assert prediction == nba.predict(state, changed)
    assert state["training_n"] == sum(r["eligible"] for r in rows[:220])


def test_heldout_training_refused():
    rows = nba.prepare_examples(games(40))
    rows[-1]["season"] = 2025
    with pytest.raises(ValueError, match="HELDOUT_SEASON_IN_TRAINING"):
        nba.fit(rows)


def test_joint_separately_fitted_and_retained_draws():
    rows = nba.prepare_examples(games(240))
    base = nba.fit(rows)
    joint = nba.fit(rows, {"stage": "joint"})
    assert joint["model_id"] != base["model_id"]
    assert joint["heads"] == base["heads"]
    assert set(joint["joint"]["calibration_event_ids"]).isdisjoint(set(base["training_event_ids"][:100]))
    later = copy.deepcopy(rows[-1]); later["event_id"] = "NBA:later"; later["event"]["event_id"] = later["event_id"]
    later["event"]["start_time_utc"] = "2025-01-01T00:00:00+00:00"
    later["event"]["forecast_cutoff_utc"] = "2024-12-31T23:59:59.999999+00:00"
    later["cutoff_utc"] = later["event"]["forecast_cutoff_utc"]
    prediction = nba.predict(joint, later, simulations=1000)
    again = nba.predict(joint, later, simulations=1000)
    assert np.array_equal(prediction["joint_draws"], again["joint_draws"])
    assert prediction["simulation"]["draw_sha256"] == again["simulation"]["draw_sha256"]
    assert prediction["exact_discrete_settlement_supported"] is False
    assert prediction["probability_semantics"] == "CONTINUOUS_JOINT_SCORE_SURROGATE"


def test_personnel_missing_not_neutral_zero():
    rows = nba.prepare_examples(games(40))
    with pytest.raises(ValueError, match="AUTHENTIC_PERSONNEL_INPUTS_REQUIRED"):
        nba.fit(rows, {"stage": "personnel"})


def test_personnel_stage_late_input_rejected():
    history = games(40)
    for game in history:
        game["personnel"] = {"home_impact_per100": 1.0, "away_impact_per100": -1.0,
                             "available_at_utc": "2030-01-01T00:00:00+00:00", "sources": game["sources"]}
    rows = nba.prepare_examples(history, {"stage": "personnel"})
    assert all(not r["eligible"] for r in rows)
    assert "NBA_PERSONNEL_INPUT_AFTER_CUTOFF" in rows[-1]["exclusion_reasons"]


def test_baseline_calls_existing_procedure_exactly():
    from scripts.prepare_initial_baselines import causal_rows, fit
    from models.current.baseline import probabilities
    from models.current.linear import predict
    history = games(240)
    control = nba.prepare_baseline_control(history, training_end_season=2023)
    prior = float(np.mean([r[s+"_score"] for r in history if r["season"] <= 2023 for s in ("home", "away")]))
    rows, _, _ = causal_rows(history, prior, history[-1]["start_time_utc"])
    fitted = fit([r for r in rows if r[0]["season"] <= 2023], "nba")
    assert control["fitted"] == fitted
    out = nba.predict_baseline(control, history[-1])
    x = rows[-1][1]
    assert out["p_home"] == probabilities(fitted, x, "nba")[1]
    assert out["home_margin"] == predict(fitted["margin"], x)
    assert out["total"] == predict(fitted["total"], x)
    assert control["not_original_frozen_fit"] is True


def test_future_event_uses_cutoff_and_no_target():
    history = games(40)
    event = copy.deepcopy(history[-1])
    event.update(event_id="NBA:future", final=False, start_time_utc="2023-06-01T20:00:00+00:00", forecast_cutoff_utc="2023-05-31T09:00:00+00:00")
    for name in ("home_score", "away_score", "home_stats", "away_stats"):
        event.pop(name)
    row = nba.prepare_examples(history + [event])[-1]
    assert row["eligible"]
    assert row["targets"] is None
    assert event["event_id"] not in row["history_event_ids"]


def _midnight_boundary_history():
    history = games(10)
    starts = [f"2022-10-{day:02d}T20:00:00+00:00" for day in range(1, 6)] + [
        "2022-10-06T23:59:59.999999+00:00", "2022-10-07T00:00:00+00:00",
        "2022-10-07T01:00:00+00:00", "2022-10-08T00:00:00+00:00",
        "2022-10-09T00:00:00+00:00"]
    for event, start in zip(history, starts):
        event["start_time_utc"] = start
    return history


def test_midnight_default_cutoff_is_applied_before_features_and_preserves_sources():
    history = _midnight_boundary_history()
    original = copy.deepcopy(history)
    row = nba.prepare_examples(history)[-1]
    assert row["cutoff_utc"] == "2022-10-08T23:59:59.999999+00:00"
    assert row["event"]["forecast_cutoff_utc"] == row["cutoff_utc"]
    assert row["history_boundary_utc"] == "2022-10-07T00:00:00+00:00"
    assert row["history_event_ids"] == [e["event_id"] for e in history[:6]]
    assert row["features"]["home_games"] == row["features"]["away_games"] == 6
    assert history == original


@pytest.mark.parametrize("start,cutoff,boundary", [
    ("2022-10-09T00:00:00Z", "2022-10-08T23:59:59.999999+00:00", "2022-10-07T00:00:00+00:00"),
    ("2022-10-09T00:00:00.000001Z", "2022-10-09T00:00:00+00:00", "2022-10-08T00:00:00+00:00"),
    ("2022-10-09T20:00:00Z", "2022-10-09T19:59:59.999999+00:00", "2022-10-08T00:00:00+00:00"),
])
def test_pre_feature_cutoff_boundary_is_exact(start, cutoff, boundary):
    event = {"start_time_utc": start}
    actual = nba.forecast_cutoff(event)
    assert actual.isoformat() == cutoff
    assert nba.history_boundary(actual).isoformat() == boundary


def test_simultaneous_starts_have_equal_cutoffs_and_cannot_consume_each_other():
    history = _midnight_boundary_history()
    other = copy.deepcopy(history[-1])
    other["event_id"] = "NBA:simultaneous"
    rows = [r for r in nba.prepare_examples(history + [other]) if r["event"]["start_time_utc"] == other["start_time_utc"]]
    assert len(rows) == 2
    assert rows[0]["cutoff_utc"] == rows[1]["cutoff_utc"]
    assert rows[0]["features"] == rows[1]["features"]
    assert rows[0]["history_event_ids"] == rows[1]["history_event_ids"]
    assert {r["event_id"] for r in rows}.isdisjoint(rows[0]["history_event_ids"])


def test_explicit_current_cutoff_is_preserved_without_any_source_time_rewrite():
    from research.efficiency.runner import prepare
    history = _midnight_boundary_history()[:-1]
    future = copy.deepcopy(history[-1])
    future.update(event_id="NBA:current", final=False, start_time_utc="2022-10-09T20:00:00Z")
    for key in ("home_score", "away_score", "home_stats", "away_stats"):
        future.pop(key)
    cutoff = "2022-10-08T09:00:00Z"
    source = {"history": history}
    before = copy.deepcopy(source)
    row = prepare("nba", source, future_events=[future], cutoff=cutoff)[-1]
    assert row["cutoff_utc"] == row["event"]["forecast_cutoff_utc"] == cutoff
    assert row["history_event_ids"] == [e["event_id"] for e in history[:6]]
    assert row["targets"] is None
    assert source == before


def test_explicit_cutoff_at_start_is_not_silently_clipped():
    history = _midnight_boundary_history()
    history[-1]["forecast_cutoff_utc"] = history[-1]["start_time_utc"]
    with pytest.raises(ValueError, match="FORECAST_CUTOFF_NOT_PRESTART"):
        nba.prepare_examples(history)


def test_training_rejects_cutoff_and_history_boundary_contract_mismatches():
    rows = nba.prepare_examples(games(40))
    altered = copy.deepcopy(rows)
    altered[-1]["cutoff_utc"] = "2020-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="FEATURE_CUTOFF_MISMATCH"):
        nba.fit(altered)
    altered = copy.deepcopy(rows)
    altered[-1]["history_max_event_time_utc"] = altered[-1]["history_boundary_utc"]
    with pytest.raises(ValueError, match="FEATURE_HISTORY_EMBARGO_VIOLATION"):
        nba.fit(altered)


def test_cutoff_aligned_score_control_matches_admission_and_preserves_start_for_rest():
    from scripts.prepare_initial_baselines import causal_rows
    from models.current.baseline import feature, update
    history = _midnight_boundary_history()
    prior = 105.
    causal, _, _, trace = nba._cutoff_aligned_causal_rows(history, prior, nba.forecast_cutoff(history[-1]).isoformat())
    state = {}
    for event in history[:6]:
        update(state, event)
    expected = list(feature(state, history[-1], prior).values())
    assert causal[-1][1] == expected
    assert trace[history[-1]["event_id"]]["team_history_counts"] == {"home": 6, "away": 6}
    assert trace[history[-1]["event_id"]]["cutoff_utc"] == nba.prepare_examples(history)[-1]["cutoff_utc"]
    legacy_rows, _, _ = causal_rows(history, prior, history[-1]["start_time_utc"])
    assert legacy_rows[-1][1] != expected
    assert causal[-1][0]["start_time_utc"] == history[-1]["start_time_utc"]


def test_aligned_control_has_distinct_identity_and_reuses_baseline_fit_math():
    from scripts.prepare_initial_baselines import fit
    history = games(240)
    control = nba.prepare_baseline_control(history, training_end_season=2023, align_forecast_cutoff=True)
    causal, _, _, trace = nba._cutoff_aligned_causal_rows(history, control["prior"], nba.forecast_cutoff(history[-1]).isoformat())
    assert control["model_id"] == nba.ALIGNED_BASELINE_REFIT_ID
    assert control["model_id"] != nba.BASELINE_REFIT_ID
    assert control["fitted"] == fit([r for r in causal if r[0]["season"] <= 2023], "nba")
    assert control["cutoff_trace"] == trace
    nba.predict_baseline(control, history[-1])
    altered = copy.deepcopy(history[-1])
    altered["forecast_cutoff_utc"] = (nba.forecast_cutoff(altered) - dt.timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="BASELINE_FEATURE_CUTOFF_MISMATCH"):
        nba.predict_baseline(control, altered)


def test_component_receipt_binds_pre_feature_cutoff_and_rejects_posthoc_retime(monkeypatch):
    from research.efficiency import runner, integrity
    row = nba.prepare_examples(_midnight_boundary_history())[-1]
    monkeypatch.setattr(integrity, "build_component_receipt", lambda **kwargs: kwargs)
    fitted = {"config": nba.DEFAULT_CONFIG}
    forecast = {"model_id": nba.MODEL_IDS["efficiency"], "p_home": .6, "components": {"score": 100.}}
    receipt = runner.component_receipt("nba", "efficiency", row, fitted, forecast, {}, mode="HISTORICAL_REPLAY")
    assert receipt["cutoff_utc"] == row["cutoff_utc"]
    assert receipt["inputs"]["event"]["forecast_cutoff_utc"] == row["cutoff_utc"]
    with pytest.raises(ValueError, match="FEATURE_RECEIPT_CUTOFF_MISMATCH"):
        runner.component_receipt("nba", "efficiency", row, fitted, forecast, {}, mode="HISTORICAL_REPLAY", cutoff="2022-10-07T23:59:59Z")


def test_matched_training_control_uses_exact_frozen_labels_and_distinct_identity():
    from scripts.prepare_initial_baselines import causal_rows, fit
    history = games(240)
    selected = [r["event_id"] for r in history[10:130]]
    control = nba.prepare_baseline_control(history, training_end_season=2023,
                                           training_event_ids=selected)
    original = nba.prepare_baseline_control(history, training_end_season=2023)
    prior = float(np.mean([r[s+"_score"] for r in history if r["event_id"] in selected
                          for s in ("home", "away")]))
    rows, _, _ = causal_rows(history, prior, history[-1]["start_time_utc"])
    expected = fit([r for r in rows if r[0]["event_id"] in selected], "nba")
    assert control["model_id"] == nba.MATCHED_BASELINE_REFIT_ID
    assert control["model_id"] != original["model_id"]
    assert control["training_event_ids"] == selected
    assert control["fitted"] == expected
    assert control["prior"] == prior
    assert original["training_event_ids"] == [r["event_id"] for r in history if r["season"] <= 2023]


@pytest.mark.parametrize("ids,error", [
    ([], "IDS_INVALID"),
    (["NBA:test-0", "NBA:test-0"], "IDS_INVALID"),
    (["NBA:absent"], "EVENT_ABSENT"),
    (["NBA:test-150"], "EVENT_AFTER_CUTOFF"),
])
def test_matched_training_control_refuses_missing_or_future_labels(ids, error):
    with pytest.raises(ValueError, match=error):
        nba.prepare_baseline_control(games(240), training_end_season=2023,
                                     training_event_ids=ids)


def _captured_sources(tmp_path, *, bad_box=False):
    import pandas as pd
    game = games(1)[0]
    game["event_id"] = "NBA:100"
    schedule = [{"id": 100, "season_type": 2, "type_id": 1, "date": game["start_time_utc"],
                 "home_id": 1, "away_id": 2, "home_display_name": "Home", "away_display_name": "Away",
                 "neutral_site": False, "status_type_completed": True,
                 "home_score": game["home_score"], "away_score": game["away_score"]}]
    boxes = []
    for side, other in (("home", "away"), ("away", "home")):
        box = {column: game[side + "_stats"][key] for key, column in nba.BOX_COLUMNS.items()}
        box.update(game_id=100, team_home_away=side, team_id=int(game[side+"_id"]), opponent_team_id=int(game[other+"_id"]),
                   team_score=game[side+"_score"], opponent_team_score=game[other+"_score"], season=2023, season_type=2,
                   turnovers=game[side+"_stats"]["tov"], team_turnovers=0)
        boxes.append(box)
    if bad_box:
        boxes[0]["field_goals_made"] += 1
    records = []
    for name, frame in (("schedule", pd.DataFrame(schedule)), ("team_box", pd.DataFrame(boxes))):
        p = tmp_path / (name + ".parquet"); frame.to_parquet(p)
        records.append({"league": "nba", "dataset": name, "season": 2023, "status": "CAPTURED",
                        "path": p.name, "url": "TEST_ONLY:" + name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                        "retrieved_at_utc": "2026-10-23T09:00:00+00:00"})
    (tmp_path/"report.json").write_text(json.dumps({"sources": records}))


def test_normalizer_accepts_actual_schedule_dataset_name(tmp_path):
    _captured_sources(tmp_path)
    result = nba.normalize_sportsdataverse(tmp_path)
    assert len(result["history"]) == len(result["score_history"]) == 1
    assert result["history"][0]["event_id"] == "NBA:100"
    assert result["player_reconciliation_issues"] == [{"event_id": "NBA:100", "reason": "PLAYER_BOX_ABSENT"}]


def test_bad_box_is_excluded_without_changing_baseline_population(tmp_path):
    _captured_sources(tmp_path, bad_box=True)
    result = nba.normalize_sportsdataverse(tmp_path)
    assert not result["history"]
    assert len(result["score_history"]) == 1
    assert result["excluded"][0]["reason"] == "NBA_BOX_SCORE_POINTS_CONFLICT"


@pytest.mark.parametrize("type_id", [4, "4", 4.0])
def test_explicit_allstar_type_is_outside_regular_season_even_when_season_type_two(type_id):
    assert nba.allstar_schedule_event({"season_type": 2, "type_id": type_id})
    assert nba.allstar_schedule_event({"season_type": 2, "type_id": 1, "type_abbreviation": "ALLSTAR"})
    assert not nba.allstar_schedule_event({"season_type": 2, "type_id": 1, "type_abbreviation": "STD"})


def test_allstar_never_enters_score_control_or_efficiency_population(tmp_path):
    import pandas as pd
    _captured_sources(tmp_path)
    path = tmp_path/'schedule.parquet'
    schedule = pd.read_parquet(path)
    schedule['type_id'] = 4
    schedule['type_abbreviation'] = 'ALLSTAR'
    schedule.to_parquet(path)
    report = json.loads((tmp_path/'report.json').read_text())
    report['sources'][0]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path/'report.json').write_text(json.dumps(report))
    result = nba.normalize_sportsdataverse(tmp_path)
    assert result['history'] == result['score_history'] == result['future_events'] == []
    assert result['excluded'] == [{'event_id':'NBA:100', 'reason':'OUTSIDE_REGULAR_SEASON_ALLSTAR_EVENT', 'season':2023}]


def test_normalizer_rejects_changed_source_bytes(tmp_path):
    _captured_sources(tmp_path)
    with (tmp_path/"team_box.parquet").open("ab") as f:
        f.write(b"tamper")
    with pytest.raises(ValueError, match="RAW_SOURCE_HASH_MISMATCH"):
        nba.normalize_sportsdataverse(tmp_path)


def test_normalizer_refuses_empty_schedule_coverage(tmp_path):
    (tmp_path/"report.json").write_text(json.dumps({"sources": []}))
    with pytest.raises(ValueError, match="SCHEDULE_COVERAGE_EMPTY"):
        nba.normalize_sportsdataverse(tmp_path)
