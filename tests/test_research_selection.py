"""Contract tests for research selection; synthetic evidence is not validation."""
import copy

import pytest

from pipelines.cards.research_selection import (
    ResearchSelectionError, content_hash, seal_forecast, seal_quality_receipt,
    select_research, selector_config_artifact, selector_config_id, target_id, verify_selection_record,
)
from research.validation_registry import ArtifactStore, Eligibility, ValidationRegistry


AT = "2026-10-22T21:00:00Z"


def forecast_payload():
    return {
        "schema": "research-forecast-v1", "procedure_id": "a" * 64,
        "input_snapshot_sha256": "b" * 64,
        "target": {"event_id": "TEST_ONLY-NE-CHI", "league": "nfl", "product": "spread",
                   "period": "full_game", "side": "away", "line": 3.0,
                   "settlement_rules_id": "full-game-ot-push-refund-v1",
                   "starts_at_utc": "2026-10-22T23:00:00Z"},
        "probabilities": {"win": .6, "loss": .3, "push": .1, "void": 0.0},
        "forecast_cutoff_utc": "2026-10-22T19:00:00Z",
        "forecast_created_at_utc": "2026-10-22T20:00:00Z",
    }


@pytest.fixture
def forecast():
    return seal_forecast(forecast_payload())


@pytest.fixture
def config():
    return {"schema": "research-selector-config-v1", "objective": "unconditional_win",
            "threshold": .6, "require_quality_receipt": False}


@pytest.fixture
def qualified_registry(tmp_path, monkeypatch):
    """Isolate the selector; actual signature verification is tested separately."""
    registry = ValidationRegistry(ArtifactStore(tmp_path))
    result = Eligibility(True, (), "c" * 64, "d" * 64, "e" * 64, "TEST_ONLY-reviewer")
    monkeypatch.setattr(registry, "assess", lambda *args, **kwargs: result)
    return registry


def decide(forecast, config, **kwargs):
    return select_research(forecast, config, decision_at_utc=AT, **kwargs)


def quote(forecast, decimal=2):
    return {"target_id": target_id(forecast["target"]), "decimal_odds": decimal,
            "quoted_at_utc": "2026-10-22T20:30:00Z"}


def test_missing_registry_preserves_raw_and_emits_no_pick(forecast, config):
    result = decide(forecast, config)
    assert result["decision_class"] == "BLOCKED"
    assert result["selection_decision"] == "NO_PICK"
    assert result["raw_probability"] == .6
    assert result["selection_probability"] is None
    assert result["confidence_band"] is None
    assert not result["publication_allowed"]
    assert result["wagering_status"] == "OFF"


def test_empty_real_registry_does_not_qualify(tmp_path, forecast, config):
    result = decide(forecast, config, registry=ValidationRegistry(ArtifactStore(tmp_path)))
    assert result["decision_class"] == "BLOCKED"


@pytest.mark.parametrize("registry", [{"eligible": True}, type("Fake", (), {"eligible": True})()])
def test_caller_status_cannot_certify(registry, forecast, config):
    with pytest.raises(ResearchSelectionError, match="VERIFIED_VALIDATION_REGISTRY_REQUIRED"):
        decide(forecast, config, registry=registry)


def test_threshold_is_unconditional_and_no_half_credit(forecast, config, qualified_registry):
    config["threshold"] = .65
    result = decide(forecast, config, registry=qualified_registry)
    assert result["decision_class"] == "ELIGIBLE_NOT_SELECTED"
    assert result["selection_probability"] == .6
    assert result["decisive_probability"] == pytest.approx(2 / 3)
    assert result["selection_decision"] == "NO_PICK"


def test_exact_threshold_selects_only_shadow(forecast, config, qualified_registry):
    result = decide(forecast, config, registry=qualified_registry)
    assert result["decision_class"] == "SHADOW_SELECTED"
    assert result["selection_decision"] == "SHADOW_PICK"
    assert not result["official_release"]
    assert not result["action_authority"]
    assert not result["prospective_registration_verified"]


def test_price_changes_diagnostics_never_selection(forecast, config, qualified_registry):
    results = [decide(forecast, config, registry=qualified_registry, price=p)
               for p in [None, quote(forecast, 1.01), quote(forecast, 100)]]
    assert len({row["decision_id"] for row in results}) == 1
    assert len({row["price_diagnostics_id"] for row in results}) == 3
    assert {row["decision_class"] for row in results} == {"SHADOW_SELECTED"}
    assert all(row["confidence_band"] is None for row in results)


def test_refunded_push_and_void_expected_payoff(forecast, config):
    payload = forecast_payload()
    payload["probabilities"] = {"win": .4, "loss": .2, "push": .3, "void": .1}
    forecast = seal_forecast(payload)
    result = decide(forecast, config, price=quote(forecast, 2.5))
    assert result["estimated_value"] == pytest.approx(.4 * 1.5 - .2)
    assert result["price_break_even"] == {
        "value": .4, "probability_basis": "conditional_decisive", "push_and_void": "stake_refunded"}
    assert result["decisive_probability"] == pytest.approx(2 / 3)


def test_all_push_no_decisive_probability(forecast, config):
    payload = forecast_payload()
    payload["probabilities"] = {"win": 0., "loss": 0., "push": 1., "void": 0.}
    result = decide(seal_forecast(payload), config)
    assert result["decisive_probability"] is None
    assert result["raw_probability"] == 0


@pytest.mark.parametrize("change", [
    {"target_id": "f" * 64}, {"decimal_odds": 1}, {"decimal_odds": float("nan")},
    {"decimal_odds": True}, {"quoted_at_utc": "2026-10-22T22:00:00Z"},
])
def test_bad_price_is_diagnostic_only(change, forecast, config, qualified_registry):
    good = decide(forecast, config, registry=qualified_registry)
    bad = decide(forecast, config, registry=qualified_registry, price={**quote(forecast), **change})
    assert bad["price_status"] == "INVALID_PRICE"
    assert bad["estimated_value"] is None
    assert bad["decision_id"] == good["decision_id"]


@pytest.mark.parametrize("probability", [float("nan"), float("inf"), -float("inf"), True, "0.6", -.1, 1.1, 10 ** 1000])
def test_malformed_probability_rejected(probability):
    payload = forecast_payload()
    payload["probabilities"]["win"] = probability
    with pytest.raises(ResearchSelectionError):
        seal_forecast(payload)


def test_incomplete_mass_is_blocked_but_raw_kept(config, qualified_registry):
    payload = forecast_payload()
    payload["probabilities"]["push"] = None
    result = decide(seal_forecast(payload), config, registry=qualified_registry)
    assert result["raw_probability"] == .6
    assert result["selection_probability"] is None
    assert "PROBABILITY_MASS_INCOMPLETE" in result["blocking_reasons"]


def test_bad_sum_rejected():
    payload = forecast_payload()
    payload["probabilities"]["push"] = .2
    with pytest.raises(ResearchSelectionError, match="PROBABILITY_MASS"):
        seal_forecast(payload)


def test_incomplete_mass_cannot_exceed_one():
    payload = forecast_payload()
    payload["probabilities"] = {"win": .9, "loss": .9, "push": None, "void": None}
    with pytest.raises(ResearchSelectionError, match="EXCEEDS_ONE"):
        seal_forecast(payload)


def test_identity_detects_silent_probability_change(forecast, config):
    forecast["probabilities"]["win"] = .7
    forecast["probabilities"]["loss"] = .2
    with pytest.raises(ResearchSelectionError, match="FORECAST_ID_MISMATCH"):
        decide(forecast, config)


@pytest.mark.parametrize("key,value", [("line", 2.5), ("period", "first_half"),
                                       ("side", "home"), ("settlement_rules_id", "different")])
def test_target_changes_new_identity_and_component_not_comparable(key, value, forecast, config):
    payload = forecast_payload()
    payload["target"][key] = value
    sibling = seal_forecast(payload)
    result = decide(forecast, config, components=[sibling])
    assert target_id(sibling["target"]) != target_id(forecast["target"])
    assert not result["same_target_components"]
    assert result["noncomparable_component_ids"] == [sibling["forecast_id"]]


def test_same_target_disagreement_is_disclosed_not_forced_gate(forecast, config, qualified_registry):
    payload = forecast_payload()
    payload["probabilities"] = {"win": .4, "loss": .5, "push": .1, "void": 0}
    result = decide(forecast, config, registry=qualified_registry, components=[seal_forecast(payload)])
    assert result["same_target_components"][0]["raw_probability"] == .4
    assert result["decision_class"] == "SHADOW_SELECTED"


def test_future_component_rejected_even_if_target_differs(forecast, config):
    payload = forecast_payload()
    payload["target"]["line"] = 2.5
    payload["forecast_created_at_utc"] = "2026-10-22T22:00:00Z"
    with pytest.raises(ResearchSelectionError, match="COMPONENT_FROM_FUTURE"):
        decide(forecast, config, components=[seal_forecast(payload)])


@pytest.mark.parametrize("timestamp", ["2026-10-22T20:00:00", "2026-10-22T20:00:00-04:00", "garbage"])
def test_timestamps_must_be_explicit_utc(timestamp):
    payload = forecast_payload()
    payload["forecast_created_at_utc"] = timestamp
    with pytest.raises(ResearchSelectionError):
        seal_forecast(payload)


def test_future_forecast_and_closed_pregame_window_block(forecast, config, qualified_registry):
    before = select_research(forecast, config, registry=qualified_registry,
                             decision_at_utc="2026-10-22T19:30:00Z")
    assert "FORECAST_FROM_FUTURE" in before["blocking_reasons"]
    after = select_research(forecast, config, registry=qualified_registry,
                            decision_at_utc="2026-10-22T23:00:00Z")
    assert "PREGAME_DECISION_WINDOW_CLOSED" in after["blocking_reasons"]


def test_replay_time_preserved_without_prospective_claim(forecast, config):
    result = decide(forecast, config, replay_at_utc="2026-10-23T14:00:00Z")
    assert result["decision_at_utc"] == AT
    assert result["replay_at_utc"] == "2026-10-23T14:00:00Z"
    assert result["execution_mode"] == "RETROSPECTIVE_DIAGNOSTIC"
    assert not result["prospective_registration_verified"]
    with pytest.raises(ResearchSelectionError, match="REPLAY_BEFORE"):
        decide(forecast, config, replay_at_utc="2026-10-21T14:00:00Z")


def test_required_quality_and_binding(forecast, config, qualified_registry):
    config["require_quality_receipt"] = True
    missing = decide(forecast, config, registry=qualified_registry)
    assert "REQUIRED_INPUT_QUALITY_RECEIPT_MISSING" in missing["blocking_reasons"]
    quality = seal_quality_receipt({
        "forecast_id": forecast["forecast_id"], "input_snapshot_sha256": forecast["input_snapshot_sha256"],
        "created_at_utc": AT, "blocking_reasons": ["STALE_REQUIRED_SOURCE"],
        "review_notes": ["GOALIE_LAYER_UNAVAILABLE"],
    })
    result = decide(forecast, config, registry=qualified_registry, quality_receipt=quality)
    assert result["selection_probability"] is None
    assert "STALE_REQUIRED_SOURCE" in result["blocking_reasons"]
    quality["forecast_id"] = "c" * 64
    quality = seal_quality_receipt({k: v for k, v in quality.items() if k != "receipt_id"})
    with pytest.raises(ResearchSelectionError, match="BINDING_MISMATCH"):
        decide(forecast, config, quality_receipt=quality)


def test_optional_gap_does_not_become_blanket_stop(forecast, config, qualified_registry):
    quality = seal_quality_receipt({
        "forecast_id": forecast["forecast_id"], "input_snapshot_sha256": forecast["input_snapshot_sha256"],
        "created_at_utc": AT, "blocking_reasons": [], "review_notes": ["OPTIONAL_GOALIE_LAYER_MISSING"],
    })
    result = decide(forecast, config, registry=qualified_registry, quality_receipt=quality)
    assert result["decision_class"] == "SHADOW_SELECTED"
    assert "OPTIONAL_GOALIE_LAYER_MISSING" in result["review_notes"]


def test_no_caller_bands_or_outcomes_in_forecast(config):
    payload = forecast_payload()
    payload["final_score"] = [24, 27]
    with pytest.raises(ResearchSelectionError, match="INVALID_FORECAST_FIELDS"):
        seal_forecast(payload)
    config["confidence_band"] = "HIGH"
    with pytest.raises(ResearchSelectionError, match="INVALID_CONFIG_FIELDS"):
        selector_config_id(config)


def test_deterministic_copy_isolation_and_hash(forecast, config):
    snapshot = copy.deepcopy((forecast, config))
    one, two = decide(forecast, config), decide(forecast, config)
    assert one == two
    assert (forecast, config) == snapshot
    decision_only = {k: v for k, v in one.items() if k not in {
        "decision_id", "price_status", "price_break_even", "estimated_value", "estimated_value_basis",
        "price_reasons", "price_quote", "price_diagnostics_id"}}
    assert content_hash(decision_only) == one["decision_id"]
    one["target"]["side"] = "home"
    one["raw_probabilities"]["win"] = .99
    assert forecast == snapshot[0]
    assert two["target"]["side"] == "away"


def test_record_verification_detects_decision_or_diagnostic_edits(forecast, config):
    result = decide(forecast, config, price=quote(forecast))
    verify_selection_record(result)
    changed = copy.deepcopy(result)
    changed["selection_decision"] = "SHADOW_PICK"
    with pytest.raises(ResearchSelectionError, match="DECISION_ID_MISMATCH"):
        verify_selection_record(changed)
    changed = copy.deepcopy(result)
    changed["estimated_value"] = 9.0
    with pytest.raises(ResearchSelectionError, match="PRICE_DIAGNOSTICS_ID_MISMATCH"):
        verify_selection_record(changed)


def test_registry_receives_exact_procedure_family_and_frozen_config(tmp_path, monkeypatch, forecast, config):
    registry = ValidationRegistry(ArtifactStore(tmp_path))
    calls = []
    def assess(procedure, family, at, *, selector_config_id):
        calls.append((procedure, family, at, selector_config_id))
        return Eligibility(False, ("TEST_ONLY_UNQUALIFIED",))
    monkeypatch.setattr(registry, "assess", assess)
    decide(forecast, config, registry=registry)
    assert calls == [(forecast["procedure_id"], {
        "league": "nfl", "product": "spread", "period": "full_game",
        "settlement_rules_id": "full-game-ot-push-refund-v1"}, AT, selector_config_id(config))]


def test_signed_registry_integration_and_config_or_target_change_blocks(tmp_path, config):
    # Fabricated TEST_ONLY evidence exercises mechanics, not sports validation.
    from tests.test_validation_registry import make_registry_fixture
    evidence = make_registry_fixture(tmp_path, config_artifact=selector_config_artifact(config))
    payload = forecast_payload()
    payload["procedure_id"] = evidence["procedure_id"]
    forecast = seal_forecast(payload)
    result = decide(forecast, config, registry=evidence["registry"])
    assert result["decision_class"] == "SHADOW_SELECTED", result["blocking_reasons"]
    assert result["validation"]["evidence_id"] == evidence["evidence_id"]
    assert not result["publication_allowed"]
    changed_config = {**config, "threshold": .59}
    changed = decide(forecast, changed_config, registry=evidence["registry"])
    assert "SELECTOR_CONFIG_MISMATCH" in changed["blocking_reasons"]
    assert changed["selection_probability"] is None
    payload["target"]["period"] = "first_half"
    changed = decide(seal_forecast(payload), config, registry=evidence["registry"])
    assert "TARGET_MISMATCH" in changed["blocking_reasons"]
