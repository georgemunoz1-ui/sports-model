"""Real-adapter perturbations; fixed coefficients are not predictive validation."""
import copy
import hashlib
import importlib
import json
from pathlib import Path

import numpy as np
import pytest

from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.recovered_inference import digest
from models.nfl.contextual.runtime import run
from pipelines.cards.selected import apply_default
from pipelines.cards.selection import select
from pipelines.cards.semantic_identity import LEGACY, SEMANTIC, forecast_with_identity, reidentify_nfl_run
from tests.semantic_identity_fixtures import package

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = "2026-09-22T08:01:00Z"
LEAGUES = ("cfb", "wnba", "mlb", "nba", "nhl", "mls")
QUOTES = [dict(home_moneyline=-120, away_moneyline=110, home_spread=-2.5, total_line=45.5),
          dict(home_moneyline=300, away_moneyline=-350, home_spread=9.5, total_line=62.5)]


def execute(p, directory, monkeypatch, semantics=SEMANTIC):
    league = p["league"]
    path = directory / "packages" / league / "package.json"; path.parent.mkdir(parents=True)
    path.write_text(json.dumps(p, sort_keys=True))
    monkeypatch.setenv("SPORTS_RESEARCH_PACKAGE_DIR", str(directory / "packages"))
    monkeypatch.setenv("SPORTS_RESEARCH_DRAW_OUTPUT", str(directory / "draws"))
    monkeypatch.setenv("SPORTS_INITIAL_BASELINES", "1")
    adapter = importlib.import_module("pipelines.cards.adapters." + league)
    events = adapter.load_schedule("2026-09-23", CUTOFF); ctx = adapter.build_context(events, CUTOFF)
    row = forecast_with_identity(adapter, events[0], ctx, 100000, semantics=semantics)
    row = apply_default(league, events[0], row)
    folder = Path(row["simulation"]["draw_directory"])
    arrays = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.glob("*.npy")}
    return row, arrays


def numeric(row):
    return {key: row.get(key) for key in ("numerical_identity", "model_p", "sim_p", "analytic_p", "stochastic_sim_p",
        "projected_margin", "projected_total", "projected_home_points", "projected_away_points", "projected_home_runs", "projected_away_runs")}


@pytest.mark.parametrize("league", LEAGUES)
@pytest.mark.parametrize("location", ["event", "package"])
def test_metadata_changes_archive_not_numeric_identity_or_draws(league, location, tmp_path, monkeypatch):
    results = []
    for i, quote in enumerate(QUOTES):
        p = package(league); target = p["events"][0] if location == "event" else p
        target.update(market_quotes=quote, display_metadata={"label": str(i), "color": str(i)}, scrape_receipt="capture-" + str(i))
        before = copy.deepcopy(p)
        results.append(execute(p, tmp_path / str(i), monkeypatch))
        assert p == before
    a, ad = results[0]; b, bd = results[1]
    assert numeric(a) == numeric(b) and ad == bd
    assert a["diagnostics"]["identity_provenance"]["legacy_parent_forecast_sha256"] != b["diagnostics"]["identity_provenance"]["legacy_parent_forecast_sha256"]
    assert a["identity_semantics"] == SEMANTIC and not a["action_authority"]
    components = a["diagnostics"]["identity_provenance"]["identity_components"]
    for key in ("feature", "calibration"):
        component = components[key]
        assert component["procedure_id"] == digest({k: v for k, v in component.items() if k != "procedure_id"})
        assert a[key + "_procedure_id"] == component["procedure_id"]
        assert a["numerical_identity"][key + "_procedure_id"] == component["procedure_id"]
    assert components["calibration"]["stage"].startswith("NONE_NO_SEPARATE_FITTED_POSTHOC")
    assert Path(a["simulation"]["draw_directory"]).joinpath("legacy_parent_forecast.json").is_file()


@pytest.mark.parametrize("league", LEAGUES)
def test_consumed_feature_change_changes_semantic_identity(league, tmp_path, monkeypatch):
    p = package(league); q = copy.deepcopy(p)
    if league == "mlb":
        q["team_state"]["HOME"]["rf"] += .5
        material = dict(pins=q["code_pins"], teams=q["team_state"], starters=q["starter_state"])
    elif league == "wnba":
        q["team_state"][0]["values"]["pts"] += 100
        material = dict(model=q["fitted_model"], state=q["team_state"], league=q["league_state"])
    elif league == "cfb":
        q["team_state"]["elo"]["HOME"] += 30
        material = dict(model=q["fitted_model"], state=q["team_state"], parameters=q["parameters"])
    else:
        q["team_state"]["H"]["for"] += .5
        material = dict(model=q["fitted_model"], state=q["team_state"], prior=q["prior"])
    q["model_sha256"] = digest(material)
    a, ad = execute(p, tmp_path / "a", monkeypatch); b, bd = execute(q, tmp_path / "b", monkeypatch)
    assert a["numerical_identity"]["feature_sha256"] != b["numerical_identity"]["feature_sha256"]
    assert a["numerical_identity"]["identity_sha256"] != b["numerical_identity"]["identity_sha256"] and ad != bd


def test_fitted_parameter_change_changes_semantic_model_digest(tmp_path, monkeypatch):
    p = package("nba"); q = copy.deepcopy(p); q["fitted_model"]["winner"]["coefficient"][0] += .001
    q["model_sha256"] = digest(dict(model=q["fitted_model"], state=q["team_state"], prior=q["prior"]))
    a, _ = execute(p, tmp_path / "a", monkeypatch); b, _ = execute(q, tmp_path / "b", monkeypatch)
    assert a["numerical_identity"]["fitted_state_sha256"] != b["numerical_identity"]["fitted_state_sha256"]


def test_legacy_compatibility_retains_counterexample_and_exact_default(tmp_path, monkeypatch):
    rows = []
    for i, quote in enumerate(QUOTES):
        p = package("mlb"); p["market_quotes"] = quote
        rows.append(execute(p, tmp_path / str(i), monkeypatch, LEGACY))
    assert rows[0][1] != rows[1][1]
    assert rows[0][0]["model_p"] != rows[1][0]["model_p"]
    assert "identity_semantics" not in rows[0][0]


def nfl_inputs():
    folder = ROOT / "data/nfl/contextual_v1"
    read = lambda name: json.loads((folder / name).read_text())
    return [load_artifact(folder / "model_packed.json"), read("recovered_parameters.json"),
            read("mnf_base_row.json")[0], read("mnf_context_integrated.json"), read("mnf_event.json"), "2026-09-14T12:00:00Z"]


def test_actual_fitted_nfl_qb_numeric_child_and_legacy_replay():
    inputs = nfl_inputs(); outputs = []
    for i, quote in enumerate(QUOTES):
        args = copy.deepcopy(inputs); args[4].update(market_quotes=quote, display_metadata=str(i))
        legacy, draws, scores = run(*args, 100000, model_id=select("nfl")["default_model_id"])
        before = copy.deepcopy(legacy); bytes_before = draws.tobytes()
        child, cd, cs = reidentify_nfl_run(args[0], args[4], args[5], legacy, draws, scores, semantics=SEMANTIC)
        assert legacy == before and draws.tobytes() == bytes_before
        exact = reidentify_nfl_run(args[0], args[4], args[5], legacy, draws, scores)
        assert exact[0] is legacy and exact[1] is draws and exact[2] is scores
        outputs.append((legacy, bytes_before, child, cd.tobytes()))
    a, ad, ac, acd = outputs[0]; b, bd, bc, bcd = outputs[1]
    assert ad != bd and a["prediction"] == b["prediction"]
    assert acd == bcd and ac["numerical_identity"] == bc["numerical_identity"]
    assert ac["prediction"] == a["prediction"] and ac["model_artifact_sha256"] == a["model_artifact_sha256"]


def test_nfl_relevant_feature_or_fit_changes_numeric_identity():
    args = nfl_inputs(); parent, w, s = run(*args, 100000, model_id=select("nfl")["default_model_id"])
    a, _, _ = reidentify_nfl_run(args[0], args[4], args[5], parent, w, s, semantics=SEMANTIC)
    args[3]["rest"]["home_rest"] += 1  # explicit synthetic numerical perturbation
    changed, changed_w, changed_s = run(*args, 100000, model_id=select("nfl")["default_model_id"])
    b, _, _ = reidentify_nfl_run(args[0], args[4], args[5], changed, changed_w, changed_s, semantics=SEMANTIC)
    assert a["numerical_identity"]["feature_sha256"] != b["numerical_identity"]["feature_sha256"]


def test_nfl_child_refuses_forged_parent_numeric_trace():
    args = nfl_inputs(); parent, w, s = run(*args, 100000, model_id=select("nfl")["default_model_id"])
    parent["features"]["rest_days_diff"] += 1
    with pytest.raises(ValueError, match="PARENT_PREDICTION_MISMATCH"):
        reidentify_nfl_run(args[0], args[4], args[5], parent, w, s, semantics=SEMANTIC)


def test_market_aware_nfl_and_unknown_semantics_refuse():
    args = nfl_inputs(); parent, w, s = run(*args, 100000, model_id=select("nfl")["default_model_id"])
    parent["market_input"] = True
    with pytest.raises(ValueError, match="INDEPENDENT_NFL"):
        reidentify_nfl_run(args[0], args[4], args[5], parent, w, s, semantics=SEMANTIC)
    with pytest.raises(ValueError, match="UNKNOWN_STOCHASTIC"):
        reidentify_nfl_run(args[0], args[4], args[5], parent, w, s, semantics="auto")


def test_actual_shared_nfl_adapter_child_invariance(tmp_path, monkeypatch):
    from pipelines.cards.adapters import nfl
    args = nfl_inputs(); event, cutoff = args[4], args[5]
    monkeypatch.setenv("NFL_CONTEXT_PACKAGE", str(ROOT / "data/nfl/contextual_v1/event_package_v2.json"))
    results = []
    for i, quote in enumerate(QUOTES):
        e = copy.deepcopy(event); e["market_quotes"] = quote
        context = nfl.build_context([e], cutoff)
        monkeypatch.setenv("SPORTS_RESEARCH_DRAW_OUTPUT", str(tmp_path / str(i)))
        raw = forecast_with_identity(nfl, e, context, 100000, semantics=SEMANTIC)
        arrays = raw["simulation"]["draw_sha256"]
        results.append((raw, arrays))
    a, ad = results[0]; b, bd = results[1]
    assert numeric(a) == numeric(b) and ad == bd
    assert a["diagnostics"]["prediction"] == b["diagnostics"]["prediction"]


def test_nonconsumed_starter_and_team_metadata_never_seed_mlb(tmp_path, monkeypatch):
    outputs = []
    for i, quote in enumerate(QUOTES):
        p = package("mlb")
        p["starter_state"]["1"]["market_quotes"] = quote
        p["team_state"]["HOME"]["display_metadata"] = str(i)
        p["model_sha256"] = digest(dict(pins=p["code_pins"], teams=p["team_state"], starters=p["starter_state"]))
        outputs.append(execute(p, tmp_path / str(i), monkeypatch))
    a, ad = outputs[0]; b, bd = outputs[1]
    assert a["model_state_config_hash"] != b["model_state_config_hash"]
    assert numeric(a) == numeric(b) and ad == bd


def test_code_pin_drift_not_bypassed_by_semantic_child(tmp_path, monkeypatch):
    p = package("nba"); p["code_pins"]["models/current/baseline.py"] = "b" * 64
    with pytest.raises(ValueError, match="RUNTIME_CODE_DRIFT"):
        execute(p, tmp_path, monkeypatch)


def test_wnba_nested_state_display_metadata_excluded(tmp_path, monkeypatch):
    outputs = []
    for i, quote in enumerate(QUOTES):
        p = package("wnba")
        p["team_state"][0]["values"]["market_quotes"] = quote
        p["team_state"][1]["values"]["display_metadata"] = str(i)
        p["model_sha256"] = digest(dict(model=p["fitted_model"], state=p["team_state"], league=p["league_state"]))
        outputs.append(execute(p, tmp_path / str(i), monkeypatch))
    a, ad = outputs[0]; b, bd = outputs[1]
    assert a["model_state_config_hash"] != b["model_state_config_hash"]
    assert numeric(a) == numeric(b) and ad == bd


def test_wnba_league_state_accepts_only_consumed_numeric_triple():
    from pipelines.cards.semantic_identity import _current_material
    p = package("wnba")
    snapshot = {"home": dict.fromkeys(("net", "efg", "tov", "orb", "ftr", "rest", "b2b", "pace"), 1.),
                "away": dict.fromkeys(("net", "efg", "tov", "orb", "ftr", "rest", "b2b", "pace"), 1.),
                "league_state": [16000., 100, 8000., {"market_quotes": QUOTES[0]}]}
    with pytest.raises(ValueError, match="WNBA_NUMERIC_LEAGUE_STATE"):
        _current_material("wnba", p["events"][0], {"package": p}, {"model_id": p["model_id"], "model_input_snapshot": snapshot})


def test_selected_cfb_week_one_arm_metadata_invariance(tmp_path, monkeypatch):
    outputs = []
    for i, quote in enumerate(QUOTES):
        p = package("cfb", week=1); p["events"][0]["market_quotes"] = quote
        p["parameters"]["unused_display_label"] = str(i)
        p["model_sha256"] = digest(dict(model=p["fitted_model"], state=p["team_state"], parameters=p["parameters"]))
        outputs.append(execute(p, tmp_path / str(i), monkeypatch))
    a, ad = outputs[0]; b, bd = outputs[1]
    assert numeric(a) == numeric(b) and ad == bd
    assert a["model_state_config_hash"] != b["model_state_config_hash"]


def test_nfl_combined_score_child_invariance_and_parent_score_integrity():
    outputs = []
    for i, quote in enumerate(QUOTES):
        args = nfl_inputs(); args[4]["market_quotes"] = quote
        parent, w, s = run(*args, 100000, model_id=args[0]["arms"]["combined"]["model_id"])
        child, cw, cs = reidentify_nfl_run(args[0], args[4], args[5], parent, w, s, semantics=SEMANTIC)
        outputs.append((child, cw, cs))
        broken = s.copy(); broken[0, 0] += 1
        with pytest.raises(ValueError, match="PARENT_SCORE_DRAW_MISMATCH"):
            reidentify_nfl_run(args[0], args[4], args[5], parent, w, broken, semantics=SEMANTIC)
    a, aw, ass = outputs[0]; b, bw, bs = outputs[1]
    assert a["numerical_identity"] == b["numerical_identity"]
    assert np.array_equal(aw, bw) and np.array_equal(ass, bs)
