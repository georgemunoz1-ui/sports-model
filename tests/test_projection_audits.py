import copy
import hashlib
import json

import pytest

from models.common import discrete_research as D
from pipelines.cards import disclosures as C
from pipelines.cards.projection_audits import audit_projection


def spec(tmp_path):
    source = tmp_path / "report.txt"
    source.write_text("Synthetic audit fixture, not sports evidence.\n")
    contract = {"event_id": "e", "league": "nba", "product": "total", "side": "UNDER",
                "line": 242.5, "settlement": "FULL_GAME_OT"}
    return {"audit_id": "fixture", "source_artifact": {"path": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
            "minutes_budgets": [{"team_id": "home", "component_id": "rotation", "basis": "REGULATION",
                "players": [{"entity_id": str(i), "minutes": 24} for i in range(10)]}],
            "allocation_checks": [{"check_id": "points", "unit": "points", "source_component_id": "players",
                "target_component_id": "players", "terms": [{"entity_id": "a", "value": 10.1},
                {"entity_id": "b", "value": 20.2}], "target": 30.25, "rounding_step": .1}],
            "method_sensitivities": [{"sensitivity_id": "total", "contract": contract, "variants": [
                {"method_id": "primary", "probability": .545, "contract": copy.deepcopy(contract)},
                {"method_id": "player_only", "probability": .379, "contract": copy.deepcopy(contract)},
                {"method_id": "ratings_only", "probability": .701, "contract": copy.deepcopy(contract)}]}]}


def run(s, tmp_path, league="nba"):
    return audit_projection(s, event_id="e", league=league, root=tmp_path)


def test_budget_allocation_and_unweighted_sensitivity(tmp_path):
    s = spec(tmp_path); before = copy.deepcopy(s)
    r = run(s, tmp_path)
    assert s == before and r["arithmetic_failures"] == 0
    assert r["minutes_budgets"][0]["sum_minutes"] == 240
    assert r["allocation_checks"][0]["rounding_tolerance"] == pytest.approx(.15)
    a = r["method_sensitivities"][0]
    assert a["range_percentage_points"] == pytest.approx(32.2)
    assert a["probability_of_failure"] is None and a["predictive_confidence_interval"] is None
    assert not r["point_in_time_verified"] and not r["source_facts_verified"]
    assert not r["action_authority"] and not r["numerical_forecast_modified"]


def test_wnba_regulation_budget_is_not_nba_budget(tmp_path):
    s = spec(tmp_path); s["method_sensitivities"] = []
    assert run(s, tmp_path, "wnba")["arithmetic_failures"] == 1
    for p in s["minutes_budgets"][0]["players"]: p["minutes"] = 20
    assert run(s, tmp_path, "wnba")["minutes_budgets"][0]["required_minutes"] == 200
    assert run(s, tmp_path, "wnba")["arithmetic_failures"] == 0


def test_invalid_allocation_is_reported_without_rescaling(tmp_path):
    s = spec(tmp_path); s["allocation_checks"][0]["target"] = 28
    a = run(s, tmp_path)["allocation_checks"][0]
    assert a["arithmetic_status"] == "FAIL" and a["sum_terms"] == pytest.approx(30.3)
    s["allocation_checks"][0]["target_component_id"] = "blended_game"
    a = run(s, tmp_path)["allocation_checks"][0]
    assert a["arithmetic_status"] == "NOT_COMPARABLE_COMPONENTS"
    assert a["sum_minus_target"] == pytest.approx(2.3)


def test_out_and_excessive_minutes_visible_even_when_total_balances(tmp_path):
    s = spec(tmp_path); players = s["minutes_budgets"][0]["players"]
    players[0]["reported_availability"] = "OUT"
    players[0]["minutes"] = 50; players[1]["minutes"] = 0; players[2]["minutes"] = 22
    r = run(s, tmp_path)["minutes_budgets"][0]
    assert r["sum_minutes"] == 240 and len(r["findings"]) == 2


@pytest.mark.parametrize("value", [True, -1, float('nan'), float('inf'), "24"])
def test_nonfinite_boolean_and_negative_minutes_rejected(tmp_path, value):
    s = spec(tmp_path); s["minutes_budgets"][0]["players"][0]["minutes"] = value
    with pytest.raises(ValueError): run(s, tmp_path)


@pytest.mark.parametrize("value", [True, -0.1, 1.1, float('nan'), float('inf')])
def test_invalid_probabilities_rejected(tmp_path, value):
    s = spec(tmp_path); s["method_sensitivities"][0]["variants"][0]["probability"] = value
    with pytest.raises(ValueError): run(s, tmp_path)


@pytest.mark.parametrize("mutation", [
    lambda s: s["minutes_budgets"][0]["players"].append(copy.deepcopy(s["minutes_budgets"][0]["players"][0])),
    lambda s: s["minutes_budgets"].append({**copy.deepcopy(s["minutes_budgets"][0]), "team_id": "away"}),
    lambda s: s["minutes_budgets"][0].update(basis="FULL_GAME_OT"),
    lambda s: s["allocation_checks"][0].update(rounding_step=20),
    lambda s: s["method_sensitivities"][0]["variants"][0]["contract"].update(line=240.5),
    lambda s: s["method_sensitivities"][0]["variants"][0].update(weight=.8),
    lambda s: s.update(action_authority=True),
    lambda s: s["source_artifact"].update(sha256="0" * 64),
    lambda s: s["source_artifact"].update(path="../report.txt"),
    lambda s: s.update(minutes_budgets=[], allocation_checks=[], method_sensitivities=[]),
])
def test_invalid_identity_scope_authority_hash_and_paths_rejected(tmp_path, mutation):
    s = spec(tmp_path); mutation(s)
    with pytest.raises(ValueError): run(s, tmp_path)


def parent_and_packet(s, league="NBA"):
    card = {"league": league, "as_of_utc": "2026-10-21T15:00:00Z", "forecasts": [
        {"event_id": "e", "model_id": "test.parent", "input_snapshot_hash": "a" * 64,
         "forecast_status": "FORECAST_GENERATED", "analytic_p": .6, "sim_p": .601}]}
    packet = {"schema": C.INPUT_SCHEMA, "action_authority": False, "events": [
        {"event_id": "e", "parent_model_id": "test.parent", "parent_input_sha256": "a" * 64,
         "projection_audits": [s]}]}
    return card, packet


@pytest.mark.parametrize("league", ["NFL", "CFB", "NBA", "WNBA", "MLB", "NHL", "MLS"])
def test_all_seven_existing_disclosure_paths_preserve_parent(tmp_path, league):
    s = spec(tmp_path); s["minutes_budgets"] = []; s["method_sensitivities"] = []
    card, packet = parent_and_packet(s, league)
    original = copy.deepcopy(card); original_packet = copy.deepcopy(packet)
    r = C.build_report(card, packet, root=tmp_path)
    assert not r["errors"] and r["execution_status"] == "COMPLETED"
    assert card == original and packet == original_packet
    assert r["parent_card_sha256"] == D.digest(original)
    assert r["events"][0]["decision"] == "PASS"
    assert "Projection audit" in C.render_md(r)


def test_bad_event_audit_does_not_hide_independent_event(tmp_path):
    s = spec(tmp_path); s["source_artifact"]["sha256"] = "0" * 64
    card, packet = parent_and_packet(s)
    card["forecasts"].append({**card["forecasts"][0], "event_id": "other"})
    r = C.build_report(card, packet, root=tmp_path)
    assert r["execution_status"] == "PARTIAL" and len(r["events"]) == 2
    assert not r["events"][0]["projection_audits"]
    assert not r["events"][1]["projection_audits"]


def test_immutable_sidecar_includes_audits_and_does_not_modify_sources(tmp_path):
    s = spec(tmp_path); card, packet = parent_and_packet(s)
    packet_path = tmp_path / "packet.json"; packet_path.write_text(json.dumps(packet))
    before = packet_path.read_bytes(); source_before = (tmp_path / "report.txt").read_bytes()
    r = C.write_report(card, tmp_path / "output", packet_path)
    assert r["events"][0]["projection_audits"][0]["method_sensitivities"]
    with pytest.raises(FileExistsError): C.write_report(card, tmp_path / "output", packet_path)
    assert before == packet_path.read_bytes() and source_before == (tmp_path / "report.txt").read_bytes()
