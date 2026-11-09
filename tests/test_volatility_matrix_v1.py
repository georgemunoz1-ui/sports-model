"""Synthetic software checks only: none is predictive validation."""
import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from models.common import discrete_research as D
from models.common import volatility_matrix_v1 as V
from pipelines.cards import volatility_research as R


def rows(league="nfl", settlement="FULL_GAME_OT_REGULAR", n=40, *, scale=False):
    result = []
    for i in range(n):
        eh, ea = (i % 7 - 3) * 2, (i % 5 - 2)
        day = i + 1
        features = {"pace": 50 + i, "rest_days": 3 + i % 4} if scale else {}
        result.append({
            "event_id": f"train-{league}-{i}", "league": league, "settlement": settlement,
            "parent_model_id": f"{league}.parent.v1", "information_set": "PREGAME_TEST",
            "market_input": False, "prediction_kind": "CHRONOLOGICAL_OUT_OF_TIME",
            "forecast_sha256": hashlib.sha256(f"forecast-{league}-{i}".encode()).hexdigest(),
            "result_source_sha256": hashlib.sha256(f"result-{league}-{i}".encode()).hexdigest(),
            "parent_fit_cutoff": "2025-01-01T00:00:00Z",
            "forecast_cutoff": f"2025-02-{day:02d}T00:00:00Z" if day <= 28 else f"2025-03-{day-28:02d}T00:00:00Z",
            "start_time_utc": f"2025-02-{day:02d}T02:00:00Z" if day <= 28 else f"2025-03-{day-28:02d}T02:00:00Z",
            "result_available_at": f"2025-02-{day:02d}T05:00:00Z" if day <= 28 else f"2025-03-{day-28:02d}T05:00:00Z",
            "predicted_home": 30, "predicted_away": 24,
            "actual_home": 30 + eh, "actual_away": 24 + ea - int(
                30 + eh == 24 + ea and not V.SETTLEMENTS[league][settlement]),
            "scale_features": features,
        })
    return result


def fit(league="nfl", settlement="FULL_GAME_OT_REGULAR", **kwargs):
    scale = bool(kwargs.get("scale_features"))
    return V.fit(rows(league, settlement, scale=scale), league=league, settlement=settlement,
                 parent_model_id=f"{league}.parent.v1", information_set="PREGAME_TEST",
                 fitted_at="2026-01-01T00:00:00Z", **kwargs)


def prediction(model, event_id="unseen-game", **kwargs):
    return V.predict(model, home_mean=30, away_mean=24, event_id=event_id,
                     cutoff="2026-02-01T00:00:00Z", parent_model_id=model["parent_model_id"],
                     information_set="PREGAME_TEST", parent_forecast_sha256="a" * 64, **kwargs)


def test_uploaded_covariance_algebra_and_bias_separation():
    covariance = np.array([[100., 30.], [30., 81.]])
    margin_sd = np.sqrt(100 + 81 - 2 * 30)
    total_sd = np.sqrt(100 + 81 + 2 * 30)
    assert margin_sd == pytest.approx(11.0, abs=.01)
    assert total_sd == pytest.approx(np.sqrt(241))
    model = fit()
    report = V.volatility(model)
    residuals = np.asarray(model["residuals_centered_transformed"])
    np.testing.assert_allclose(np.cov(residuals, rowvar=False, ddof=1), model["covariance_home_away"])
    assert report["margin_variance"] == pytest.approx(report["home_score_variance"] + report["away_score_variance"] - 2 * report["home_away_covariance"])
    assert report["total_variance"] == pytest.approx(report["home_score_variance"] + report["away_score_variance"] + 2 * report["home_away_covariance"])
    assert report["mean_bias_actual_minus_predicted"] == pytest.approx(np.asarray([[r["actual_home"]-r["predicted_home"], r["actual_away"]-r["predicted_away"]] for r in rows()]).mean(0))
    assert report["bias_applied_to_point_forecast"] is False
    assert report["predictive_sd_not_monte_carlo_se"] is True


def test_ledoit_wolf_retains_target_covariance_and_psd():
    model = fit(method="ledoit_wolf")
    target = np.asarray(model["covariance_home_away"])
    retained = np.asarray(model["residuals_centered_transformed"])
    assert np.linalg.eigvalsh(target).min() > 0
    np.testing.assert_allclose(np.cov(retained, rowvar=False, ddof=1), target)
    assert 0 <= model["shrinkage"]["shrinkage"] <= 1


def test_conditional_scale_is_pregame_and_not_bias_correction():
    model = fit(scale_features=("pace", "rest_days"))
    low = V.volatility(model, scale_features={"pace": 50, "rest_days": 3})
    high = V.volatility(model, scale_features={"pace": 89, "rest_days": 6})
    assert low["conditional_scale"] > 0 and high["conditional_scale"] > 0
    assert high["home_away_correlation"] == pytest.approx(low["home_away_correlation"])
    assert high["margin_sd"] == pytest.approx(low["margin_sd"] * high["conditional_scale"] / low["conditional_scale"])
    with pytest.raises(ValueError, match="MARKET_FEATURE"):
        fit(scale_features=("closing_spread",))
    with pytest.raises(ValueError, match="SCALE_FEATURE_NAMES_INVALID"):
        fit(scale_features="pace")
    assert model["scaling"]["target"] == "LOG1P_MEAN_SQUARED_CENTERED_HOME_AWAY_ERROR"
    raw = np.asarray([[r["actual_home"]-r["predicted_home"], r["actual_away"]-r["predicted_away"]]
                      for r in rows(scale=True)])
    assert model["mean_bias_actual_minus_predicted"] == pytest.approx(raw.mean(0).tolist())
    assert model["residual_center"] == pytest.approx(((raw-raw.mean(0)) /
        np.exp(np.clip(np.column_stack([np.ones(len(raw)),
            (np.asarray([[r["scale_features"][k] for k in ("pace", "rest_days")] for r in rows(scale=True)]) -
             np.asarray(model["scaling"]["mean"])) / np.asarray(model["scaling"]["sd"])]) @
            np.asarray(model["scaling"]["beta"]), -8, 16) / 2)[:, None]).mean(0).tolist())


def test_parent_means_retained_before_legal_conditioning_and_pairs_coherent():
    model = fit()
    d = prediction(model)
    moments = V.moments(d)
    # No score or tie cells are removed at these synthetic means.
    assert moments["home_mean"] == pytest.approx(30)
    assert moments["away_mean"] == pytest.approx(24)
    margin, total = V.derive(d, "margin"), V.derive(d, "total")
    h, a, p = V.validate(d)
    assert moments["margin_mean"] == pytest.approx(moments["home_mean"] - moments["away_mean"])
    assert moments["total_mean"] == pytest.approx(moments["home_mean"] + moments["away_mean"])
    assert np.asarray(margin["support"]) @ np.asarray(margin["masses"]) == pytest.approx((h-a) @ p)
    assert np.asarray(total["support"]) @ np.asarray(total["masses"]) == pytest.approx((h+a) @ p)
    assert V.outcome_probabilities(d)["identity"] == "JOINT_SCORE_DERIVATIVE_NOT_DIRECT_WINNER_HEAD"


def test_unscaled_fit_ignores_unrelated_parent_snapshot_features():
    model = fit()
    d = prediction(model, scale_features={"pace": 101, "unrelated_input": 7})
    assert d["provenance"]["conditional_scale"] == 1.0
    assert d["provenance"]["scale_features_used"] == {}


def test_no_tie_settlement_conditions_support_explicitly():
    model = fit(league="nba", settlement="FULL_GAME_OT")
    d = V.predict(model, home_mean=.1, away_mean=.1, event_id="unseen-nba",
                  cutoff="2026-02-01T00:00:00Z", parent_model_id=model["parent_model_id"],
                  information_set="PREGAME_TEST", parent_forecast_sha256="a" * 64)
    h, a, p = V.validate(d)
    assert np.all(h != a)
    assert d["provenance"]["removed_illegal_support_mass"] > 0
    with pytest.raises(ValueError, match="FINAL_TIE_UNSUPPORTED"):
        V.make_joint([0], [0], [1], league="nba", settlement="FULL_GAME_OT",
                     model_id="bad", provenance={})


@pytest.mark.parametrize("league,settlement", [(league, settlement) for league, values in V.SETTLEMENTS.items() for settlement in values])
def test_all_sport_settlements_predict_and_settle(league, settlement):
    model = fit(league=league, settlement=settlement)
    d = prediction(model, event_id=f"unseen-{league}-{settlement}")
    V.validate(d)
    for product in ("margin", "total"):
        derived = V.derive(d, product)
        line = 0.25 if league == "mls" else 0.5
        side = "HOME" if product == "margin" else "OVER"
        priced = D.price(derived, line, side)
        assert sum(priced.values()) == pytest.approx(1)
    if league != "mls":
        with pytest.raises(ValueError, match="QUARTER_LINES_ONLY_MLS"):
            D.price(V.derive(d, "total"), 0.25, "OVER")


def test_discretization_variance_increment_is_explicit_and_measured():
    model = fit()
    d = V.predict(model, home_mean=30.5, away_mean=24.5, event_id="rounding",
                  cutoff="2026-02-01T00:00:00Z", parent_model_id=model["parent_model_id"],
                  information_set="PREGAME_TEST", parent_forecast_sha256="a"*64)
    analytic = d["provenance"]["volatility"]
    emitted = V.moments(d)
    increment = d["provenance"]["pre_conditioning_rounding_variance"]
    assert 0 < increment["home"] <= .25
    assert 0 < increment["away"] <= .25
    assert emitted["margin_sd"]**2 == pytest.approx(analytic["empirical_margin_variance_before_discretization"] + increment["margin_and_total"])
    assert emitted["total_sd"]**2 == pytest.approx(analytic["empirical_total_variance_before_discretization"] + increment["margin_and_total"])
    assert d["provenance"]["analytic_volatility_excludes_discretization_and_legal_conditioning"] is True
    assert d["provenance"]["emitted_support_moments_are_authoritative_for_distribution"] is True


def test_ledoit_wolf_fixed_reference_and_spherical_metadata():
    rng = np.random.default_rng(7)
    x = rng.normal(size=(30, 2)) @ np.array([[2., .5], [0., 1.]])
    covariance, metadata = V._ledoit_wolf(x-x.mean(0))
    np.testing.assert_allclose(covariance, [[3.3273120214586025, .7195432760861272],
                                            [.7195432760861272, 1.1179303354914831]])
    assert metadata["shrinkage"] == pytest.approx(.18765739412027546)
    spherical = np.array([[1., 0.], [-1., 0.], [0., 1.], [0., -1.]])
    _, metadata = V._ledoit_wolf(spherical)
    assert metadata["shrinkage"] == 0.0


def test_missing_scale_feature_and_authority_tampering_fail_closed():
    incomplete = rows(scale=True)
    del incomplete[0]["scale_features"]["pace"]
    with pytest.raises(ValueError, match="MISSING_SCALE_FEATURE"):
        V.fit(incomplete, league="nfl", settlement="FULL_GAME_OT_REGULAR",
              parent_model_id="nfl.parent.v1", information_set="PREGAME_TEST",
              fitted_at="2026-01-01T00:00:00Z", scale_features=("pace", "rest_days"))
    model = fit(scale_features=("pace", "rest_days"))
    with pytest.raises(ValueError, match="MISSING_SCALE_FEATURE"):
        prediction(model, scale_features={"pace": 100})
    d = prediction(fit())
    record = V.account_result(d, actual_home=31, actual_away=20,
                              result_source_sha256="b"*64,
                              result_available_at="2026-02-01T05:00:00Z")
    other = V.account_result(prediction(fit(), event_id="other"), actual_home=30, actual_away=20,
                             result_source_sha256="c"*64,
                             result_available_at="2026-02-01T05:00:00Z")
    tampered = copy.deepcopy(record); tampered["action_authority"] = True
    material = dict(tampered); material.pop("artifact_sha256")
    tampered["artifact_sha256"] = D.digest(material)
    with pytest.raises(ValueError, match="RESEARCH_ONLY"):
        V.evaluate([tampered, other], evaluated_at="2026-02-02T00:00:00Z")


def test_paired_simulation_is_reproducible_and_mc_se_is_distinct():
    d = prediction(fit())
    h1, a1, meta1 = V.simulate(d, draws=1000)
    h2, a2, meta2 = V.simulate(d, draws=1000)
    assert np.array_equal(h1, h2) and np.array_equal(a1, a2)
    assert meta1["draw_sha256"] == meta2["draw_sha256"]
    assert meta1["mc_se_is_not_predictive_sd"] is True
    assert meta1["worst_case_mc_se_pp"] != V.moments(d)["margin_sd"]


def test_chronology_duplicates_scope_drift_and_training_reuse_fail_closed():
    bad = rows()
    bad[0]["prediction_kind"] = "IN_SAMPLE"
    with pytest.raises(ValueError, match="OUT_OF_TIME"):
        V.fit(bad, league="nfl", settlement="FULL_GAME_OT_REGULAR",
              parent_model_id="nfl.parent.v1", information_set="PREGAME_TEST",
              fitted_at="2026-01-01T00:00:00Z")
    duplicate = rows(); duplicate[1]["event_id"] = duplicate[0]["event_id"]
    with pytest.raises(ValueError, match="DUPLICATE"):
        V.fit(duplicate, league="nfl", settlement="FULL_GAME_OT_REGULAR",
              parent_model_id="nfl.parent.v1", information_set="PREGAME_TEST",
              fitted_at="2026-01-01T00:00:00Z")
    model = fit()
    with pytest.raises(ValueError, match="TRAINING_EVENT_REUSED"):
        prediction(model, event_id=model["training_event_ids"][0])
    with pytest.raises(ValueError, match="PARENT_SCOPE_MISMATCH"):
        V.predict(model, home_mean=30, away_mean=24, event_id="new", cutoff="2026-02-01T00:00:00Z",
                  parent_model_id="other", information_set="PREGAME_TEST", parent_forecast_sha256="a"*64)
    tampered = copy.deepcopy(model); tampered["covariance_home_away"][0][1] += 1
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        V.volatility(tampered)
    drift = copy.deepcopy(model); drift["code_sha256"] = "0" * 64
    # Re-seal only the code field to isolate the code-drift guard.
    material = dict(drift); material.pop("artifact_sha256")
    drift["artifact_sha256"] = D.digest(material)
    with pytest.raises(ValueError, match="CODE_DRIFT"):
        V.volatility(drift)


def test_luck_accounting_freezes_forecast_and_separates_single_game_bias():
    d = prediction(fit())
    before = D.digest(d)
    record = V.account_result(d, actual_home=31, actual_away=20,
                              result_source_sha256="b" * 64,
                              result_available_at="2026-02-01T05:00:00Z")
    assert D.digest(d) == before
    assert record["forecast_unchanged"] is True
    assert record["causal_luck_identified"] is False
    assert record["single_game_model_bias_estimated"] is False
    assert record["actual_minus_predictive_mean"]["margin"] == pytest.approx(11 - V.moments(d)["margin_mean"])
    assert 0 <= record["mid_pit"]["margin"] <= 1
    assert record["action_authority"] is False
    assert record["mid_pit_not_randomized_calibration_pit"] is True
    assert record["start_time_lineage_retained"] is False
    assert record["joint_energy_score"]["energy_score"] >= 0


def test_evaluation_aggregates_bias_coverage_and_crps_without_claiming_validation():
    model = fit()
    records = []
    for i, (h, a) in enumerate(((31, 20), (25, 26), (35, 22))):
        d = prediction(model, event_id=f"graded-{i}")
        records.append(V.account_result(d, actual_home=h, actual_away=a,
                                        result_source_sha256=hashlib.sha256(str(i).encode()).hexdigest(),
                                        result_available_at="2026-02-01T05:00:00Z"))
    result = V.evaluate(records, evaluated_at="2026-02-02T00:00:00Z")
    assert result["n"] == 3
    assert result["status"] == "DIAGNOSTIC_NOT_WALK_FORWARD_VALIDATION"
    assert set(result["central_interval_coverage"]) == {"50", "80", "95"}
    assert result["mean_joint_energy_score"] >= 0
    with pytest.raises(ValueError, match="DUPLICATE"):
        V.evaluate([records[0], records[0]], evaluated_at="2026-02-02T00:00:00Z")


def _card(league):
    settlement = next(iter(V.SETTLEMENTS[league]))
    row = {"event_id": f"card-{league}", "start_time_utc": "2026-02-01T03:00:00Z",
           "home_team": "Home", "away_team": "Away", "model_id": f"{league}.parent.v1",
           "forecast_status": "FORECAST_GENERATED", "input_snapshot_hash": "1" * 64,
           "model_state_config_hash": "2" * 64, "model_input_snapshot": {},
           "projected_home_points": 30, "projected_away_points": 24,
           "diagnostics": {"market_input": False}, "warnings": []}
    return {"league": league.upper(), "as_of_utc": "2026-02-01T00:00:00Z",
            "generated_at_utc": "2026-02-01T00:30:00Z", "forecasts": [row]}, settlement


@pytest.mark.parametrize("league", list(V.SETTLEMENTS))
def test_card_adapter_all_leagues_preserves_parent_and_pairs_draws(tmp_path, league):
    card, settlement = _card(league)
    parent_before = copy.deepcopy(card)
    model = fit(league=league, settlement=settlement)
    model_path = tmp_path / f"{league}.json"
    model_path.write_text(json.dumps(model))
    product, line, side = ("margin", 5.5, "HOME") if league == "mlb" else ("total", 54.5, "OVER")
    config = {"schema": "sports.volatility_card_config.research.v1", "information_set": "PREGAME_TEST",
              "action_authority": False, "models": [{"path": model_path.name,
              "sha256": hashlib.sha256(model_path.read_bytes()).hexdigest()}],
              "contracts": [{"event_id": f"card-{league}", "product": product, "settlement": settlement,
                             "line": line, "side": side, "kind": "HYPOTHETICAL"}]}
    config_path = tmp_path / "config.json"; config_path.write_text(json.dumps(config))
    report = R.build(card, R.load_config(config_path), tmp_path / "out", simulations=500)
    assert card == parent_before
    assert report["coverage"][0]["status"] == "COMPLETED"
    result = report["results"][0]
    assert result["distribution"]["joint_score_distribution"] is True
    assert report["direct_winner_heads_unchanged"] is True
    assert result["distribution"]["provenance"]["start_time_utc"] == card["forecasts"][0]["start_time_utc"]
    draws = np.load(tmp_path / "out" / result["simulation"]["file"])
    assert draws["home"].shape == draws["away"].shape == (500,)
    assert sum(result["contracts"][0]["model_probabilities"].values()) == pytest.approx(1)
    with pytest.raises(FileExistsError):
        R.build(card, R.load_config(config_path), tmp_path / "out", simulations=500)


def test_future_market_quote_is_refused_in_joint_card(tmp_path):
    card, settlement = _card("nfl")
    model = fit()
    model_path = tmp_path / "model.json"; model_path.write_text(json.dumps(model))
    quote = {"event_id": "card-nfl", "line": 54.5, "side": "OVER", "settlement": settlement,
             "source_sha256": "3"*64, "book": "TEST", "observed_at_utc": "2026-02-01T01:00:00Z",
             "retrieved_at_utc": "2026-02-01T01:00:00Z", "decimal_odds": 2.0,
             "opposing_decimal_odds": 2.0}
    config = {"schema": "sports.volatility_card_config.research.v1", "information_set": "PREGAME_TEST",
              "action_authority": False, "models": [{"path": model_path.name,
              "sha256": hashlib.sha256(model_path.read_bytes()).hexdigest()}],
              "contracts": [{"event_id": "card-nfl", "product": "total", "settlement": settlement,
                             "line": 54.5, "side": "OVER", "kind": "MARKET", "quote": quote}]}
    config_path = tmp_path / "config.json"; config_path.write_text(json.dumps(config))
    report = R.build(card, R.load_config(config_path), tmp_path / "out", simulations=10)
    assert report["coverage"][0]["status"] == "UNAVAILABLE"
    assert report["coverage"][0]["reason"] == "FUTURE_QUOTE"


def test_unsupported_mls_margin_contract_fails_closed(tmp_path):
    card, settlement = _card("mls")
    model = fit(league="mls", settlement=settlement)
    model_path = tmp_path / "model.json"; model_path.write_text(json.dumps(model))
    config = {"schema": "sports.volatility_card_config.research.v1", "information_set": "PREGAME_TEST",
              "action_authority": False, "models": [{"path": model_path.name,
              "sha256": hashlib.sha256(model_path.read_bytes()).hexdigest()}],
              "contracts": [{"event_id": "card-mls", "product": "margin", "settlement": settlement,
                             "line": -0.25, "side": "HOME", "kind": "HYPOTHETICAL"}]}
    config_path = tmp_path / "config.json"; config_path.write_text(json.dumps(config))
    report = R.build(card, R.load_config(config_path), tmp_path / "out", simulations=10)
    assert report["coverage"][0]["status"] == "UNAVAILABLE"
    assert report["coverage"][0]["reason"] == "UNSUPPORTED_PRODUCT"


def test_margin_without_total_is_visible_gap_not_invented_score(tmp_path):
    card, settlement = _card("cfb")
    row = card["forecasts"][0]
    row.pop("projected_home_points"); row.pop("projected_away_points")
    row["diagnostics"]["home_margin"] = 4.0
    row["home_score"], row["away_score"] = 28, 24  # possible postgame fields: ineligible
    model = fit(league="cfb", settlement=settlement)
    model_path = tmp_path / "model.json"; model_path.write_text(json.dumps(model))
    config = {"schema": "sports.volatility_card_config.research.v1", "information_set": "PREGAME_TEST",
              "action_authority": False, "models": [{"path": model_path.name,
              "sha256": hashlib.sha256(model_path.read_bytes()).hexdigest()}], "contracts": []}
    config_path = tmp_path / "config.json"; config_path.write_text(json.dumps(config))
    report = R.build(card, R.load_config(config_path), tmp_path / "out", simulations=10)
    assert report["results"] == []
    assert report["coverage"][0]["status"] == "UNAVAILABLE"
    assert "POINT_HEAD_UNAVAILABLE:total" in report["coverage"][0]["reason"]


def _missingness_config(league='nhl', scaled=False):
    card,settlement=_card(league)
    model=fit(league=league,settlement=settlement,scale_features=('pace','rest_days') if scaled else ())
    return card,{'loaded_models':[{'model':model}],'contracts':[], 'config_file_sha256':'a'*64,
                 'information_set':'PREGAME_TEST'}


def test_joint_missingness_metadata_and_record_order_preserve_law(tmp_path):
    card,config=_missingness_config(scaled=True)
    row=card['forecasts'][0]
    row['model_input_snapshot']={'pace':61.,'rest_days':3.}
    first=R.build(card,config,tmp_path/'first',simulations=200)
    revised=copy.deepcopy(card)
    revised['forecasts'][0].update(source_url='https://example.org/renamed',
        model_input_snapshot={'unused':None,'rest_days':3.,'pace':61.})
    second=R.build(revised,config,tmp_path/'second',simulations=200)
    for r in (first,second):
        result=r['results'][0]
        info=result['missingness_audit']
        assert info['release_status']=='HOLD_PENDING_SCOPE_REVIEW' and info['action_authority'] is False
        inputs=info['details']['input_observations']
        assert set(inputs['features'])=={'pace','rest_days'}
        assert inputs['features']['pace']['imputation'] is None
        assert inputs['settlement']=='FULL_GAME_OT_SO_PLUS_ONE'
    left,right=[r['results'][0]['distribution'] for r in (first,second)]
    for key in ('home_scores','away_scores','masses'):
        assert left[key]==right[key]
    revised['forecasts'][0]['model_input_snapshot']['pace']=85.
    third=R.build(revised,config,tmp_path/'third',simulations=200)
    after=third['results'][0]['missingness_audit']['details']['input_observations']
    assert after['conditional_scale']!=left['provenance']['conditional_scale']
    assert after['parent_home_mean']==left['provenance']['parent_home_mean']


@pytest.mark.parametrize('defect', ['absent','null','nan','duplicate_event','missing_score_head'])
def test_joint_missingness_refusals_keep_sibling_and_parent(tmp_path,defect):
    card,config=_missingness_config(scaled=True)
    good=card['forecasts'][0]
    good['model_input_snapshot']={'pace':61.,'rest_days':4.}
    bad=copy.deepcopy(good)
    bad['event_id']='bad'
    card['forecasts'].append(bad)
    if defect=='absent':del bad['model_input_snapshot']['pace']
    if defect=='null':bad['model_input_snapshot']['pace']=None
    if defect=='nan':bad['model_input_snapshot']['pace']='NaN'
    if defect=='duplicate_event':card['forecasts'].append(copy.deepcopy(bad))
    if defect=='missing_score_head':bad.pop('projected_away_points')
    before=copy.deepcopy(card)
    report=R.build(card,config,tmp_path/'out',simulations=200)
    assert card==before
    assert [r['event_id'] for r in report['results']]==[good['event_id']]
    refused=[r for r in report['coverage'] if r['event_id']=='bad']
    assert refused and all(r['status']=='UNAVAILABLE' and r['reason'] and
        r['missingness_audit']['release_status']=='HOLD_PENDING_SCOPE_REVIEW' for r in refused)
    if defect=='absent':
        with pytest.raises(ValueError,match='MISSING_SCALE_FEATURE'):
            V.predict(config['loaded_models'][0]['model'],home_mean=30,away_mean=24,
                parent_model_id=bad['model_id'],event_id=bad['event_id'],cutoff=card['as_of_utc'],
                information_set='PREGAME_TEST',parent_forecast_sha256='b'*64,scale_features=bad['model_input_snapshot'])


def test_joint_missingness_distribution_and_array_tampering_block_readback(tmp_path):
    card,config=_missingness_config()
    report=R.build(card,config,tmp_path/'out',simulations=200)
    changed=copy.deepcopy(report)
    changed['results'][0]['predictive_moments']['total_mean']=999.
    changed['artifact_sha256']=D.digest({k:v for k,v in changed.items() if k!='artifact_sha256'})
    with pytest.raises(ValueError,match='MISSINGNESS_CHILD_READBACK_FAILED'):
        R.verify_readback(changed,tmp_path/'out',card,config, expected_report_sha256=report["artifact_sha256"])
    (tmp_path/'out'/report['results'][0]['simulation']['file']).write_bytes(b'altered')
    with pytest.raises(ValueError,match='DRAWS_READBACK'):
        R.verify_readback(report,tmp_path/'out',card,config, expected_report_sha256=report["artifact_sha256"])

@pytest.mark.parametrize("omitted", ["fitted", "refused", "substituted", "source", "config"])
def test_readback_reconciles_every_event_against_parent_and_fitted_configuration(tmp_path, omitted):
    card, config = _missingness_config()
    good = card["forecasts"][0]
    card["forecasts"].append(dict(good, event_id="unfitted", model_id="other.parent"))
    report = R.build(card, config, tmp_path / "out", simulations=100)
    published = report["artifact_sha256"]
    if omitted == "fitted":
        report["coverage"] = [r for r in report["coverage"] if r["event_id"] != good["event_id"]]
        report["results"] = []
    elif omitted == "refused":
        report["coverage"] = [r for r in report["coverage"] if r["event_id"] != "unfitted"]
    elif omitted == "substituted":
        report["coverage"][0] = copy.deepcopy(report["coverage"][1])
    elif omitted == "source":
        card["forecasts"][0]["source_url"] = "changed"
    else:
        config["config_file_sha256"] = "f" * 64
    report["artifact_sha256"] = D.digest({k:v for k,v in report.items() if k != "artifact_sha256"})
    with pytest.raises(ValueError, match="JOINT_MISSINGNESS_PARENT"):
        R.verify_readback(report, tmp_path / "out", card, config, expected_report_sha256=published)

def test_resealed_fabricated_refusal_cannot_replace_executed_run(tmp_path):
    card, config = _missingness_config()
    report = R.build(card, config, tmp_path / "out", simulations=100)
    published = report["artifact_sha256"]
    row = report["coverage"][0]
    prior = row.pop("missingness_audit")
    row.update(status="UNAVAILABLE", reason="fabricated")
    inputs = dict(prior["details"]["input_observations"], status="UNAVAILABLE")
    R.M.attach(row, report["league"], row["event_id"], row["model_id"], R.PRODUCTS,
               inputs=inputs, method="Joint child event coverage", missing=[row["reason"]])
    report["results"] = []
    report["artifact_sha256"] = D.digest({k:v for k,v in report.items() if k != "artifact_sha256"})
    with pytest.raises(ValueError, match="EXPECTED_REPORT_HASH"):
        R.verify_readback(report, tmp_path / "out", card, config, expected_report_sha256=published)


@pytest.mark.parametrize(("field", "value"), [
    ("start_time_utc", None), ("start_time_utc", "bad-time"),
    ("model_id", None), ("model_id", ["unresolved"]),
])
def test_invalid_parent_metadata_preserves_sibling(tmp_path, field, value):
    card, config = _missingness_config()
    card["forecasts"].append(dict(card["forecasts"][0], event_id="invalid", **{field:value}))
    report = R.build(card, config, tmp_path / "out", simulations=100)
    assert [row["event_id"] for row in report["results"]] == [card["forecasts"][0]["event_id"]]
    assert report["coverage"][1]["status"] == "UNAVAILABLE"
    assert report["coverage"][1]["reason"]
    if field == "start_time_utc":
        assert report["timing_unassessed_event_ids"] == ["invalid"]
        assert "invalid" not in report["post_start_event_ids"]
