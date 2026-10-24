"""Metamorphic tests of real adapters, not reporting flags or mocked predictors.

Synthetic packages exercise the existing fitted-head interfaces, not predictive
accuracy. Historical NFL artifacts exercise the actual selected QB coefficients.
Known seed contamination is asserted as a counterexample, NOT marked as a pass
for market independence. See docs/SELECTED_MARKET_INDEPENDENCE.md.
"""
import copy
import datetime as dt
import importlib
import json
from pathlib import Path

import numpy as np
import pytest

from models.current import baseline, cfb, common
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.recovered_inference import digest
from models.nfl.contextual.runtime import run
from models.nfl.modes.core import devig
from pipelines.cards.selected import apply_default
from pipelines.cards.selection import select

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = "2026-09-22T08:01:00Z"
LEAGUES = ["cfb", "wnba", "mlb", "nba", "nhl", "mls"]
QUOTES = [
    {"home_moneyline": -120, "away_moneyline": 110, "home_spread": -2.5, "total_line": 45.5},
    {"home_moneyline": 300, "away_moneyline": -350, "home_spread": 9.5, "total_line": 62.5},
    {"home_moneyline": -500, "away_moneyline": 400, "home_spread": -14, "total_line": 31},
]


def head(n, kind, intercept):
    return dict(kind=kind, impute=[0.] * n, mean=[0.] * n, scale=[1.] * n,
                coefficient=[.001 * (i + 1) for i in range(n)], intercept=intercept)


def package(league, week=2):
    event = dict(event_id="SYNTHETIC:" + league, home_team="HOME", away_team="AWAY",
                 home_id="H", away_id="A", start_time_utc="2026-09-23T20:00:00Z",
                 slate_date="2026-09-23", season=2026, neutral_site=False,
                 week=week, division_scope="FBS_VS_FBS", conference_game=True, season_type=2)
    p = dict(schema="sports.current_research_package.v1", league=league,
             action_authority=False, captured_at_utc="2026-09-22T08:00:00Z",
             training_cutoff_utc="2026-09-21T00:00:00Z", ttl_hours=6,
             source_fetches=[dict(source="SYNTHETIC_UNIT_TEST_ONLY", fetched_at_utc="2026-09-22T08:00:00Z")],
             events=[event], covered_dates=[event["slate_date"]], code_pins={},
             data_grade="SYNTHETIC_TEST_NOT_FORECAST", limitations=[], model_lineage={},
             consumed_game_ids=["synthetic-history"])
    if league == "cfb":
        p["model_id"] = select(league, week=week, division="FBS_VS_FBS")["default_model_id"]
        p["parameters"] = dict(regress=.7, hfa=55)
        p["team_state"] = dict(elo={"HOME": 1540., "AWAY": 1490.}, last_season={},
            last={"HOME": "2026-09-15T20:00Z", "AWAY": "2026-09-16T20:00Z"},
            ewpf={"HOME": 31., "AWAY": 25.}, ewpa={"HOME": 21., "AWAY": 23.},
            ewm={"HOME": 10., "AWAY": 2.})
        p["feature_names"] = list(cfb.feature_row(p["team_state"], event, p["parameters"]))
        if week == 1:
            p["feature_names"] = ["elo_diff_with_home_advantage", "neutral_site", "conference_game"]
        n = len(p["feature_names"])
        p["fitted_model"] = dict(winner=head(n, "logistic", .15), margin=head(n, "linear", 2.))
        material = dict(model=p["fitted_model"], state=p["team_state"], parameters=p["parameters"])
    elif league == "wnba":
        p["model_id"] = select(league)["default_model_id"]
        stats = dict(g=12, pts=1010, opts=970, fgm=370, fga=800, fg3m=100, fta=210,
                     oreb=110, tov=140, ofga=810, ooreb=100, otov=150, ofta=190, last="2026-09-20")
        p["team_state"] = [dict(season=2026, team=t, values={**stats, "pts": pts})
                           for t, pts in [("HOME", 1010), ("AWAY", 950)]]
        p["league_state"] = [16000., 100, 8000.]
        p["fitted_model"] = dict(mu=[0.] * 6, sd=[1.] * 6, blog=[.1] + [.2] * 7,
            bmar=[2.] + [1.] * 7, tmu=[160., 0., 0.], tsd=[1.] * 3, btot=[162., .2, .5, 1.])
        material = dict(model=p["fitted_model"], state=p["team_state"], league=p["league_state"])
    elif league == "mlb":
        p["model_id"] = select(league)["default_model_id"]
        event.update(home_pitcher_id=1, away_pitcher_id=2, park_factor=1.02)
        p["team_state"] = {"HOME": dict(rf=4.8, ra=4.), "AWAY": dict(rf=4.2, ra=4.6)}
        p["starter_state"] = {"1": dict(era=3.5, gs=22, k=25., bb=6.), "2": dict(era=4.5, gs=24, k=21., bb=9.)}
        material = dict(pins={}, teams=p["team_state"], starters=p["starter_state"])
    else:
        p["model_id"] = baseline.IDS[league]
        p["prior"] = {"nba": 110., "nhl": 3., "mls": 1.4}[league]
        p["team_state"] = {t: dict(n=20, **{"for": p["prior"] + delta, "against": p["prior"],
                                             "last": "2026-09-20T20:00Z"}) for t, delta in [("H", .2), ("A", -.1)]}
        n = len(baseline.FEATURES)
        p["fitted_model"] = (dict(home_goals=head(n, "poisson", .4), away_goals=head(n, "poisson", .2))
            if league == "mls" else dict(winner=head(n, "logistic", .1), margin=head(n, "linear", 1.),
                                        total=head(n, "linear", 2 * p["prior"])))
        material = dict(model=p["fitted_model"], state=p["team_state"], prior=p["prior"])
    p["model_sha256"] = digest(material)
    return p


def execute(p, directory, monkeypatch, external_market=None):
    """Use real loaders, state-hash guards, adapters and selected-output routing."""
    league = p["league"]
    path = directory / "packages" / league / "package.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(p, sort_keys=True))
    monkeypatch.setenv("SPORTS_RESEARCH_PACKAGE_DIR", str(directory / "packages"))
    monkeypatch.setenv("SPORTS_RESEARCH_DRAW_OUTPUT", str(directory / "draws"))
    monkeypatch.setenv("SPORTS_INITIAL_BASELINES", "1")
    adapter = importlib.import_module("pipelines.cards.adapters." + league)
    events = adapter.load_schedule("2026-09-23", CUTOFF)
    ctx = adapter.build_context(events, CUTOFF)
    if external_market is not None:
        ctx["market_comparison"] = copy.deepcopy(external_market)
    raw = apply_default(league, events[0], adapter.forecast_event(events[0], ctx, 100000))
    folder = Path(raw["simulation"].pop("draw_directory"))
    files = {f.name: f.read_bytes() for f in folder.iterdir()}
    assert raw["action_authority"] is False and raw["dose"] == 0
    return raw, files


@pytest.mark.parametrize("league", LEAGUES)
def test_separate_market_prices_leave_predictions_and_retained_bytes_identical(league, tmp_path, monkeypatch):
    p = package(league); before = digest(p)
    outputs = [execute(p, tmp_path / str(i), monkeypatch, q) for i, q in enumerate(QUOTES)]
    assert outputs[0] == outputs[1] == outputs[2]
    assert digest(p) == before
    # Positive control: this really changes the market benchmark.
    assert len({devig(q["home_moneyline"], q["away_moneyline"]) for q in QUOTES}) == 3
    row = outputs[0][0]
    if league in {"cfb", "mlb"}:
        assert row["projected_total"] is None
    if league == "mlb":
        assert row["analytic_p"] is None
    if league == "mls":
        assert row["projected_margin"] is None  # no invented margin product


def test_cfb_opener_scope_with_separate_prices(tmp_path, monkeypatch):
    p = package("cfb", week=1)
    a = execute(p, tmp_path / "a", monkeypatch, QUOTES[0])
    b = execute(p, tmp_path / "b", monkeypatch, QUOTES[1])
    assert a == b
    assert "week1_shadow" in a[0]["model_id"]


@pytest.mark.parametrize("league", LEAGUES)
@pytest.mark.parametrize("location", ["event", "package"])
def test_documented_unfiltered_payload_seed_counterexample(league, location, tmp_path, monkeypatch):
    """OPEN exception: do not claim end-to-end independence from this test passing."""
    results = []
    for i, quote in enumerate(QUOTES[:2]):
        p = package(league)
        target = p["events"][0] if location == "event" else p
        target["market_quotes"] = copy.deepcopy(quote)
        results.append(execute(p, tmp_path / str(i), monkeypatch))
    a, af = results[0]; b, bf = results[1]
    assert a["model_state_config_hash"] == b["model_state_config_hash"]
    assert a["diagnostics"].get("home_win") == b["diagnostics"].get("home_win")
    assert a["analytic_p"] == b["analytic_p"]
    assert any(af[k] != bf[k] for k in af if k.endswith(".npy"))
    if league == "mlb":
        assert a["model_p"] != b["model_p"]  # selected estimator is MC-only
    else:
        assert a["projected_margin"] == b["projected_margin"]
        assert a["projected_total"] == b["projected_total"]


@pytest.fixture
def nfl_inputs():
    folder = ROOT / "data/nfl/contextual_v1"
    read = lambda name: json.loads((folder / name).read_text())
    return (load_artifact(folder / "model_packed.json"), read("recovered_parameters.json"),
            read("mnf_base_row.json")[0], read("mnf_context_integrated.json"), read("mnf_event.json"),
            "2026-09-14T12:00:00Z")


def nfl_selected(inputs, **kwargs):
    return run(*inputs, 100000, model_id=select("nfl")["default_model_id"], **kwargs)


def test_nfl_selected_qb_ignores_sidecar_market_and_rejects_explicit_packet(nfl_inputs, monkeypatch):
    from pipelines.cards.adapters import nfl
    artifact, recovered, base, context, event, cutoff = nfl_inputs
    monkeypatch.setenv("NFL_CONTEXT_PACKAGE", str(ROOT / "data/nfl/contextual_v1/event_package_v2.json"))
    outputs = []
    for quote in QUOTES:
        ctx = nfl.build_context([event], cutoff)
        ctx["market_comparison"] = copy.deepcopy(quote)
        outputs.append(nfl.forecast_event(event, ctx, 100000))
        with pytest.raises(ValueError, match="MARKET_OR_LIVE_INPUT_IN_FOOTBALL_ONLY"):
            nfl_selected(nfl_inputs, market=quote)
    assert outputs[0] == outputs[1] == outputs[2]
    a, aw, scores = nfl_selected(nfl_inputs)
    b, bw, _ = nfl_selected(nfl_inputs)
    assert a == b and aw.tobytes() == bw.tobytes()
    assert scores is None and outputs[0]["projected_total"] is None and outputs[0]["projected_margin"] is None
    assert set(a["prediction"]) == {"home_win", "home_margin", "total_points"}


def test_nfl_event_metadata_seed_counterexample(nfl_inputs):
    outputs = []
    for quote in QUOTES[:2]:
        args = copy.deepcopy(nfl_inputs)
        args[4]["market_quotes"] = quote
        outputs.append(nfl_selected(args))
    a, aw, _ = outputs[0]; b, bw, _ = outputs[1]
    assert a["prediction"] == b["prediction"] and a["features"] == b["features"]
    assert a["identity"] != b["identity"] and aw.tobytes() != bw.tobytes()


def market_packet(event, quote):
    return {**{k: event[k] for k in ("event_id", "home_team", "away_team")},
        "source": "SYNTHETIC_TEST_ONLY", "source_sha256": "a" * 64,
        "observed_at_utc": "2026-09-14T11:59:00Z", "retrieved_at_utc": "2026-09-14T11:59:01Z",
        "period": "FULL_GAME", "odds_format": "AMERICAN", "state": "PREGAME", "quotes": quote}


def test_explicit_nfl_market_mode_changes_all_three_predictions(nfl_inputs):
    from pipelines.cards.adapters.nfl import mode_artifact
    model = mode_artifact("enhanced_pregame")
    # Saved coefficients, not an invented mix: 0%, 0%, 10% football weights.
    assert model["weights"] == dict(home_win=0., home_margin=0., total_points=.1)
    outputs = [run(*nfl_inputs, 100000, mode="enhanced_pregame", mode_artifact=model,
                   market=market_packet(nfl_inputs[4], q)) for q in QUOTES[:2]]
    a, aw, asc = outputs[0]; b, bw, bsc = outputs[1]
    assert a["football_reference"] == b["football_reference"]
    for target in ("home_win", "home_margin", "total_points"):
        assert a["prediction"][target] != b["prediction"][target]
    assert aw.tobytes() != bw.tobytes() and asc.tobytes() != bsc.tobytes()
    assert a["market_input"] is True and a["action_authority"] is False


def test_downstream_lines_change_contract_probability_without_mutating_distribution():
    from models.common import discrete_research as D
    d = D.make_distribution([-7, 0, 3, 7], [.1, .2, .3, .4], league="nfl", product="margin",
        settlement="FULL_GAME_OT_REGULAR", model_id="synthetic.test.v1", provenance={})
    before = copy.deepcopy(d)
    a = D.price(d, -2.5, "HOME"); b = D.price(d, -7, "HOME")
    assert a != b and d == before


def test_live_nfl_uses_market_prior_but_not_spread_total_as_features(nfl_inputs):
    from pipelines.cards.adapters.nfl import mode_artifact
    model = mode_artifact("live"); event = nfl_inputs[4]
    snapshot = {**{k: event[k] for k in ("event_id", "home_team", "away_team")},
        "source": "SYNTHETIC_TEST_ONLY", "source_sha256": "b" * 64,
        "observed_at_utc": "2026-09-15T01:00:00Z", "retrieved_at_utc": "2026-09-15T01:00:01Z",
        "effective_at_utc": "2026-09-15T00:59:59Z", "state_boundary": "PRE_PLAY", "game_status": "IN_PROGRESS",
        "features": dict(home_score=10, away_score=7, seconds_remaining=2400,
            quarter_seconds_remaining=600, quarter=2, possession="AWAY", yardline_100=50,
            down=2, yards_to_go=6, home_timeouts=3, away_timeouts=2)}
    def execute_live(q):
        return run(*nfl_inputs[:5], "2026-09-15T01:00:02Z", 100000, mode="live",
                   mode_artifact=model, market=market_packet(event, q), live_state=snapshot)
    a, ad, _ = execute_live(QUOTES[0]); b, bd, _ = execute_live(QUOTES[1])
    assert a["features"]["pregame_logit"] != b["features"]["pregame_logit"]
    assert a["prediction"] != b["prediction"] and ad.tobytes() != bd.tobytes()
    line_only = {**QUOTES[0], "home_spread": 11, "total_line": 60}
    c, cd, _ = execute_live(line_only)
    assert a["features"] == c["features"] and a["prediction"] == c["prediction"]
    assert ad.tobytes() != cd.tobytes()  # full market packet enters the live RNG identity
    assert a["market_input"] and a["action_authority"] is False


@pytest.mark.parametrize("league", ["nfl", *LEAGUES])
def test_disclosures_name_path_without_claiming_certification(league):
    from pipelines.cards.market_provenance import describe
    from pipelines.cards import disclosures
    mid = select("nfl")["default_model_id"] if league == "nfl" else package(league)["model_id"]
    row = dict(event_id="synthetic", model_id=mid, forecast_status="FORECAST_GENERATED")
    before = copy.deepcopy(row)
    result = describe(row, league)
    assert result["path_class"] == "REVIEWED_NONMARKET_FEATURE_PATH"
    assert result["reported_market_input"] is None
    assert "EXCEPTION_OPEN" in result["simulation_independence"]
    card = dict(league=league.upper(), as_of_utc=CUTOFF, forecasts=[row])
    report = disclosures.build_report(card)
    assert "Model versus market" in disclosures.render_md(report)
    assert row == before and report["events"][0]["market_provenance"] == result


def test_market_disclosures_never_turn_unknown_or_contradiction_into_free():
    from pipelines.cards.market_provenance import describe
    row = dict(event_id="synthetic", model_id="unknown.v1", forecast_status="FORECAST_GENERATED")
    assert describe(row, "nba")["path_class"] == "UNREVIEWED"
    row["model_id"] = baseline.IDS["nba"]
    assert describe(row, "nhl")["path_class"] == "UNREVIEWED"
    row["diagnostics"] = {"market_input": True}
    assert describe(row, "nba")["path_class"] == "MARKET_INFORMED"
    for mid in ("nfl.market_ensemble.v1.research", "nfl.live_state_hgb.v1.research"):
        row.update(model_id=mid, diagnostics={"market_input": False})
        assert describe(row, "nfl")["path_class"] == "MARKET_INFORMED"


def test_grading_flags_preserve_unknown_market_use(tmp_path, monkeypatch):
    from scripts.generate_card_force import normalize, attach_grading
    p = package("mlb")
    raw, _ = execute(p, tmp_path / "run", monkeypatch)
    row = normalize(p["events"][0], raw)
    card = dict(league="MLB", generated_at_utc=CUTOFF, forecasts=[row])
    attach_grading(card)
    assert row["grading"]["market_features_used"] is None
    assert row["grading"]["action_authority"] is False


@pytest.mark.parametrize("league", ["nfl", *LEAGUES])
@pytest.mark.parametrize("product", ["margin", "total"])
def test_research_child_contracts_do_not_change_distribution_or_retained_draws(league, product, tmp_path):
    from models.common import discrete_research as D
    from pipelines.cards.distribution_research import build
    settlement = next(iter(D.SETTLEMENTS[league]))
    rows = []
    for i in range(60):
        day = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=i)
        rows.append(dict(event_id=f"synthetic-history-{i}", league=league, product=product,
            settlement=settlement, parent_model_id="synthetic.parent.v1", information_set="PREGAME",
            market_input=False, forecast_sha256="a" * 64, result_source_sha256="b" * 64,
            prediction_kind="CHRONOLOGICAL_OUT_OF_TIME", parent_fit_cutoff="2025-12-01T00:00:00Z",
            forecast_cutoff=day.isoformat(), start_time_utc=(day + dt.timedelta(hours=1)).isoformat(),
            result_available_at=(day + dt.timedelta(hours=6)).isoformat(),
            predicted_mean=20., observed=20 + [-3, -2, -1, 1, 2, 3][i % 6], scale_features={}))
    model = D.fit_residuals(rows, league=league, product=product, settlement=settlement,
        parent_model_id="synthetic.parent.v1", fitted_at="2026-09-01T00:00:00Z", information_set="PREGAME")
    row = dict(event_id="synthetic", model_id="synthetic.parent.v1", forecast_status="FORECAST_GENERATED",
        start_time_utc="2026-09-23T20:00:00Z", home_team="HOME", away_team="AWAY",
        input_snapshot_hash="c" * 64, model_state_config_hash="d" * 64,
        diagnostics=dict(home_margin=20., total=20.), model_input_snapshot={})
    card = dict(league=league, as_of_utc=CUTOFF, generated_at_utc=CUTOFF, forecasts=[row])
    before = digest(card); outputs = []
    for i, (line, odds) in enumerate([(-18.5 if product == "margin" else 18.5, 1.9),
                                    (-22.5 if product == "margin" else 22.5, 2.4)]):
        contract = dict(event_id="synthetic", product=product, settlement=settlement,
                        side="HOME" if product == "margin" else "OVER", line=line, kind="MARKET")
        contract["quote"] = dict(event_id="synthetic", line=line, side=contract["side"], settlement=settlement,
            source_sha256="e" * 64, book="SYNTHETIC_TEST_ONLY", observed_at_utc=CUTOFF, retrieved_at_utc=CUTOFF,
            decimal_odds=odds, opposing_decimal_odds=2.)
        config = dict(information_set="PREGAME", config_file_sha256=digest(contract),
                      loaded_models=[dict(model=model, calibrator=None)], contracts=[contract])
        output = tmp_path / str(i)
        report = build(card, config, output, simulations=100000)
        assert report["coverage"][0]["status"] == "COMPLETED"
        result = report["results"][0]
        outputs.append((result, (output / result["simulation"]["file"]).read_bytes()))
    a, ad = outputs[0]; b, bd = outputs[1]
    assert a["distribution"] == b["distribution"] and a["simulation"] == b["simulation"] and ad == bd
    assert a["contracts"][0]["model_probabilities"] != b["contracts"][0]["model_probabilities"]
    assert digest(card) == before
