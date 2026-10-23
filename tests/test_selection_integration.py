"""Automatic entrypoint and real writer/grader plumbing; fixtures are synthetic."""
import copy
from datetime import datetime, timezone
import hashlib
import json

import numpy as np
import pytest

from pipelines.cards.selection_integration import (
    build_card_selection, write_card_selection, verify_sidecar, settle_target,
)
from scripts import canonical_forecasts as canonical
from scripts.run_nfl_integrated import persist_replay


CREATED = "2026-10-22T18:00:00Z"
EXECUTED = "2026-10-23T06:00:00Z"


def card(league="nba"):
    return {"league": league.upper(), "card_date": "2026-10-22", "as_of_utc": "2026-10-22T17:00:00Z",
        "generated_at_utc": CREATED, "forecasts": [{"event_id": "TEST_ONLY:1",
            "home_team": "HOME", "away_team": "AWAY", "start_time_utc": "2026-10-22T23:00:00Z",
            "forecast_status": "FORECAST_GENERATED", "model_id": f"{league}.initial_causal_score.research.v1",
            "input_snapshot_hash": "a" * 64, "model_state_config_hash": "b" * 64,
            "model_winner": "HOME", "model_p": .6, "diagnostics": {}, "warnings": []}]}


def build(source):
    return build_card_selection(source, source_sha256="c" * 64, source_ref="TEST_ONLY.json",
                                evaluated_at_utc=EXECUTED, retrospective=True)


def test_automatic_default_retains_raw_identity_gaps_and_no_pick():
    result = build(card())
    decision = result["decisions"][0]
    assert decision["raw_probability"] == .6
    assert decision["selection_probability"] is None and decision["selection_decision"] == "NO_PICK"
    assert "CALIBRATION_PROCEDURE_ID_UNRESOLVED" in decision["blocking_reasons"]
    assert result["execution_mode"] == "RETROSPECTIVE_DIAGNOSTIC"
    assert not result["prospective_registration_verified"]
    assert result["opportunity_count"] == result["event_count"] == 1


def test_nhl_affected_rest_suspends_selections_not_research():
    result = build(card("nhl"))
    assert result["forecasts"][0]["probabilities"]["win"] == .6
    assert "NHL_EMBARGO_REST_CONSTRUCTION_SELECTION_SUSPENDED" in result["decisions"][0]["blocking_reasons"]


def test_nfl_non_tie_probability_is_not_unconditional_settlement():
    result = build(card("nfl"))
    d = result["decisions"][0]
    assert d["raw_probability"] == .6
    assert d["raw_probability_basis"] == "conditional_decisive"
    assert "RAW_PROBABILITY_BASIS_NOT_UNCONDITIONAL" in d["blocking_reasons"]


@pytest.mark.parametrize("winner,probs,expected", [("HOME", [.25, .2, .55], .55), ("Draw", [.2, .6, .2], .6)])
def test_mls_regulation_three_way_target_keeps_draw_semantics(winner, probs, expected):
    source = card("mls")
    row = source["forecasts"][0]
    row.update(model_winner=winner, model_p=expected,
               diagnostics={"outcome_order": ["away", "draw", "home"], "analytic_probabilities": probs})
    result = build(source)
    target, mass = result["forecasts"][0]["target"], result["forecasts"][0]["probabilities"]
    assert target["period"] == "regulation_90"
    assert target["settlement_rules_id"] == "REGULATION_90_1X2_DRAW_IS_SEPARATE_OUTCOME_v1"
    assert target["side"] == ("draw" if winner == "Draw" else "home")
    assert mass["win"] == expected and mass["loss"] == pytest.approx(1-expected)


@pytest.mark.parametrize("mass", [[-.1, .55, .55], [True, -.55, .55], [.25, .25, .55], [float("inf"), -.1, .55]])
def test_mls_raw_three_way_mass_cannot_hide_invalid_nonselected_components(mass):
    source = card("mls")
    source["forecasts"][0].update(model_p=.55,
        diagnostics={"outcome_order": ["away", "draw", "home"], "analytic_probabilities": mass})
    with pytest.raises(ValueError, match="MLS_THREE_WAY_PROBABILITY_MASS_INVALID"):
        build(source)


def test_missing_forecast_stays_in_blocked_opportunity_denominator():
    source = card()
    missing = copy.deepcopy(source["forecasts"][0])
    missing.update(event_id="TEST_ONLY:2", forecast_status="FORECAST_FAILED")
    missing.pop("model_p"); missing.pop("model_winner")
    source["forecasts"].append(missing)
    result = build(source)
    assert result["event_count"] == result["opportunity_count"] == len(result["population"]) == 2
    decision = result["decisions"][1]
    assert decision["raw_probability"] is None and decision["selection_probability"] is None
    assert "NO_PARENT_FORECAST" in decision["blocking_reasons"]


@pytest.mark.parametrize("side,h,a,expected", [("home", 1, 1, "LOSS"), ("away", 1, 1, "LOSS"),
                                               ("draw", 1, 1, "WIN"), ("home", 2, 1, "WIN")])
def test_mls_exact_settlement_requires_authoritative_regulation_period(side, h, a, expected):
    target = {"league": "mls", "product": "winner", "period": "regulation_90", "side": side,
              "line": None, "settlement_rules_id": "REGULATION_90_1X2_DRAW_IS_SEPARATE_OUTCOME_v1"}
    assert settle_target(target, h, a, score_period="REGULATION_90") == expected
    for period in (None, "FULL_GAME", "EXTRA_TIME"):
        with pytest.raises(ValueError, match="VERIFIED_REGULATION"):
            settle_target(target, h, a, score_period=period)


def semantic_card():
    """Synthetic identity fixture, never a fitted performance record."""
    from pipelines.cards.research_selection import content_hash
    source = card()
    row = source["forecasts"][0]
    components = {}
    for kind in ("feature", "calibration"):
        artifact = {"schema": "TEST_ONLY:" + kind, "description": "synthetic hash binding"}
        components[kind] = {**artifact, "procedure_id": content_hash(artifact)}
        row[kind + "_procedure_id"] = content_hash(artifact)
    numerical = {"schema": "sports.numeric_stochastic_identity.v2", "semantics": "market_blind_numeric.v2",
        "event_id": row["event_id"], "model_id": row["model_id"], "feature_sha256": "d" * 64,
        "fitted_state_sha256": "e" * 64, "engine": "TEST_ONLY", "draw_count": 100,
        "numpy_version": "TEST_ONLY", "semantic_runtime_sha256": "f" * 64,
        "feature_procedure_id": row["feature_procedure_id"], "calibration_procedure_id": row["calibration_procedure_id"]}
    numerical["identity_sha256"] = content_hash(numerical)
    row.update(identity_semantics="market_blind_numeric.v2", numerical_identity=numerical,
        diagnostics={"identity_provenance": {"identity_components": components}})
    return source


def test_complete_observed_procedure_uses_numeric_state_and_ignores_archive_quote_changes():
    source = semantic_card()
    first = build(source)
    source["forecasts"][0]["model_state_config_hash"] = "1" * 64
    source["forecasts"][0]["nonconsumed_quote"] = -300
    second = build(source)
    a, b = first["procedure_bindings"][0], second["procedure_bindings"][0]
    assert a["forecast_procedure_id"] == b["forecast_procedure_id"]
    assert a["fitted_state_id"] == "e" * 64
    assert a["identity_registration_status"] == "OBSERVED_NOT_REGISTERED"
    definition = first["objects"][a["forecast_procedure_id"]]["definition"]
    assert definition["model_state_id"] == "e" * 64
    for field in ("feature_semantics_id", "calibration_id"):
        assert definition[field] in first["objects"]
    assert first["decisions"][0]["selection_probability"] is None
    assert "FEATURE_PROCEDURE_ID_UNRESOLVED" not in first["decisions"][0]["blocking_reasons"]
    assert "AUTOMATIC_DIAGNOSTIC_POLICY_NOT_PREREGISTERED" in first["decisions"][0]["blocking_reasons"]


def test_semantic_component_hash_tamper_refused():
    source = semantic_card()
    source["forecasts"][0]["diagnostics"]["identity_provenance"]["identity_components"]["feature"]["description"] = "tampered"
    with pytest.raises(ValueError, match="COMPONENT_HASH_MISMATCH"):
        build(source)


def test_source_bytes_preserved_write_once_and_tamper_detected(tmp_path):
    source = tmp_path / "card.json"
    source.write_text(json.dumps(card()))
    before = source.read_bytes()
    report = write_card_selection(source, tmp_path / "sidecar", retrospective=True, evaluated_at_utc=EXECUTED)
    verify_sidecar(report, source_card_sha256=hashlib.sha256(before).hexdigest())
    assert source.read_bytes() == before
    with pytest.raises(ValueError, match="ALREADY_EXISTS"):
        write_card_selection(source, tmp_path / "sidecar", retrospective=True, evaluated_at_utc=EXECUTED)
    report["decisions"][0]["raw_probability"] = .8
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        verify_sidecar(report)


@pytest.mark.parametrize("side,line,score,expected", [
    ("home", -3, (27,24), "PUSH"), ("away", 3, (27,24), "PUSH"),
    ("away", 2.5, (27,24), "LOSS"), ("home", -2.5, (27,24), "WIN"),
])
def test_exact_side_line_settlement(side, line, score, expected):
    target = {"period": "full_game", "product": "spread", "side": side, "line": line,
              "settlement_rules_id": "FULL_GAME_OT_single_stake_refund_v1"}
    assert settle_target(target, *score) == expected


@pytest.fixture
def writer():
    from tests.test_canonical_forecasts import CanonicalForecastTests
    fixture = CanonicalForecastTests()
    fixture.setUp()
    row = fixture.card["forecasts"][0]
    row.update(model_p=.7, input_snapshot_hash="a" * 64, model_state_config_hash="b" * 64)
    fixture.path.write_text(json.dumps(fixture.card))
    yield fixture
    fixture.doCleanups()


def add_sidecar(writer, retrospective=False):
    return write_card_selection(writer.path, writer.path.parent / "research_selection", retrospective=retrospective,
                               evaluated_at_utc="2026-10-20T10:01:30Z")


def test_actual_canonical_registration_and_grading_consume_sidecar(writer):
    report = add_sidecar(writer)
    writer.register()
    assert canonical.grade(writer.root, [writer.results()])["selection_added_count"] == 1
    grade = canonical.load_ledger(writer.root / "selection_ledger.jsonl")[0]
    assert grade["decision_id"] == report["decisions"][0]["decision_id"]
    assert grade["outcome"] == "WIN" and grade["selected_outcome"] is None
    assert grade["selection_decision"] == "NO_PICK"
    before = (writer.root / "selection_ledger.jsonl").read_bytes()
    assert canonical.grade(writer.root, [writer.results()])["selection_added_count"] == 0
    assert (writer.root / "selection_ledger.jsonl").read_bytes() == before
    with pytest.raises(ValueError, match="IMMUTABLE_GRADE_CONFLICT"):
        canonical.grade(writer.root, [writer.results(home_score=80)])
    assert (writer.root / "selection_ledger.jsonl").read_bytes() == before


def test_retrospective_sidecar_cannot_be_registered(writer):
    add_sidecar(writer, retrospective=True)
    with pytest.raises(ValueError, match="RETROSPECTIVE_SELECTION_CANNOT_REGISTER"):
        writer.register()
    assert not (writer.root / "registry.json").exists()


def test_registered_selection_tamper_blocks_real_grader(writer):
    add_sidecar(writer)
    writer.register()
    receipt = next(iter(json.loads((writer.root / "registry.json").read_text())["forecasts"].values()))
    path = writer.root / "selections" / (receipt["selection_sidecar_sha256"] + ".json")
    artifact = json.loads(path.read_text())
    artifact["decisions"][0]["selection_probability"] = .99
    path.write_text(json.dumps(artifact))
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        canonical.grade(writer.root, [writer.results()])
    assert not (writer.root / "selection_ledger.jsonl").exists()


def test_semantic_child_draws_are_registered_at_known_path(writer):
    row = writer.card["forecasts"][0]
    row["identity_semantics"] = "market_blind_numeric.v2"
    source = writer.path.parent / "draws/NBA_1"
    source.rename(writer.path.parent / "draws/NBA_1.semantic-v2")
    writer.register()
    assert canonical.grade(writer.root, [writer.results()])["added_count"] == 1


def test_replay_writer_uses_actual_clock_and_never_prospective_stream(tmp_path):
    before = datetime.now(timezone.utc)
    receipt = persist_replay(tmp_path / "replay", {"cutoff_utc": CREATED}, np.array([0,1]), None, {"TEST_ONLY": True})
    after = datetime.now(timezone.utc)
    assert before <= datetime.fromisoformat(receipt["created_at_utc"]) <= after
    assert receipt["execution_mode"] == "RETROSPECTIVE_DIAGNOSTIC"
    assert not receipt["prospective_registration_verified"]
    assert not (tmp_path / "replay/registration.jsonl").exists()
    assert not (tmp_path / "forecast_stream.jsonl").exists()
