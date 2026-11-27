import copy
import json
from pathlib import Path

import pytest

from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.runtime import run
from scripts import audit_nfl_feature_access as access
from scripts.source_attestation import sha256

DATA = Path(__file__).resolve().parents[1] / "data/nfl/contextual_v1"
CUTOFF = "2026-09-14T12:00:00Z"
EVENT = "2026_01_DEN_KC"


@pytest.fixture(scope="module")
def retained():
    paths = [DATA / x for x in ("event_package_v2.json", "model_packed.json", "recovered_parameters.json")]
    args = [v for p in paths for v in (p, sha256(p.read_bytes()))]
    result = access.replay_feature_access(*args, EVENT, CUTOFF)
    return args, result


def test_existing_native_feature_access_and_governance(retained):
    args, result = retained
    assert len(result["feature_rows"]) == 100
    assert result["arms"]["combined"]["matrix_columns"] == 100
    assert result["arms"]["qb"]["matrix_columns"] == 23
    assert result["feature_families"]["AVAILABILITY"]["qb_matrix"] == 0
    assert result["feature_families"]["AVAILABILITY"]["combined_matrix"] == 72
    assert result["feature_families"]["TRAVEL"]["qb_matrix"] == 0
    assert result["source_evidence"]["status"] == "RAW_SOURCE_ROOTS_NOT_SUPPLIED"
    assert all(r["source_status"] == "FIELD_LEVEL_PIT_LINEAGE_NOT_ESTABLISHED" for r in result["feature_rows"])
    assert not result["field_level_pit_verified"] and not result["training_ready"]
    assert not result["action_authority"] and not result["prospective_registration_verified"]
    assert result["official_units"] == 0 and result["qualification"] == "NO_PICK"
    assert result["arms"]["qb"]["joint_score_support"] == "UNAVAILABLE_FOR_SELECTED_ARM"
    assert all(sha256(Path(args[i]).read_bytes()) == args[i+1] for i in (0,2,4))


def test_all_arms_replay_matches_native_runtime(retained):
    args, result = retained
    package = json.loads(args[0].read_bytes())
    model = load_artifact(args[2])
    recovered = json.loads(args[4].read_bytes())
    event = package["events"][0]
    packet = package["event_inputs"][EVENT]
    native, _, _ = run(model, recovered, packet["base"], packet["context"], event,
                       CUTOFF, 1000, model_id=model["arms"]["qb"]["model_id"])
    assert result["bindings"]["native_features"] == native["features"]
    for arm, row in result["arms"].items():
        assert row["head_diagnostics"] == native["arms"][arm]["prediction"]


def test_no_schema_expansion_or_guessed_value(retained):
    args, result = retained
    model = load_artifact(args[2])
    x = dict(result["bindings"]["native_features"])
    with pytest.raises(ValueError, match="NATIVE_FEATURE_SCHEMA_MISMATCH"):
        access.inspect_native_vector(model, {**x, "market_probability": .5})
    x["wind_mph"] = True
    with pytest.raises(ValueError, match="INVALID_NATIVE_FEATURE"):
        access.inspect_native_vector(model, x)
    x["wind_mph"] = None
    rows, arms = access.inspect_native_vector(model, x)
    assert "wind_mph" in arms["qb"]["imputed_columns"]
    row = next(r for r in rows if r["feature"] == "wind_mph")
    assert row["value"] is None and row["value_status"] == "MISSING_RAW_MATRIX_VALUE"


def test_wrong_pin_and_cutoff(retained):
    args, _ = retained
    wrong = args[:]
    wrong[1] = "0"*64
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        access.replay_feature_access(*wrong, EVENT, CUTOFF)
    with pytest.raises(ValueError, match="CHRONOLOGY"):
        access.replay_feature_access(*args, EVENT, "2026-09-15T00:15:00Z")


def test_target_leakage_and_late_weather(retained, tmp_path):
    args, _ = retained
    for kind in ("target", "late"):
        package = json.loads(args[0].read_bytes())
        packet = package["event_inputs"][EVENT]
        if kind == "target":
            packet["base"]["total_points"] = 50
        else:
            packet["context"]["weather"]["published_at_utc"] = "2026-09-14T13:00:00Z"
        p = tmp_path / (kind+".json")
        p.write_text(json.dumps(package))
        with pytest.raises(ValueError, match="TARGET_RESULT|POST_CUTOFF"):
            access.replay_feature_access(p, sha256(p.read_bytes()), *args[2:], EVENT, CUTOFF)
