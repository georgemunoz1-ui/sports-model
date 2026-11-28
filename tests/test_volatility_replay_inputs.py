"""Persisted replay fits are retrospective diagnostics, never prospective proof."""
import hashlib
import json
from pathlib import Path

import pytest

from models.common import discrete_research as D
from models.common import volatility_matrix_v1 as V
from scripts.build_volatility_replay_inputs import build_rows

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/research/distribution_replay_20261007"
FITS = ROOT / "data/research/volatility_matrix_replay_20261103"


@pytest.mark.parametrize("league,n", [("nba", 1230), ("nhl", 1312), ("mls", 493)])
def test_replay_rows_and_persisted_fits_reconcile(league, n):
    rows, provenance = build_rows(INPUT, league)
    assert len(rows) == n
    assert provenance["source_capture_kind"] == "RETROSPECTIVE_RECONSTRUCTION"
    assert provenance["historical_availability_proven"] is False
    assert provenance["prospective_evidence"] is False
    assert all(r["forecast_hash_derivation"] == "COMPOSITE_MARGIN_TOTAL_FORECAST_HASH_HOME_MINUS_AWAY_V1" for r in rows)
    summary = json.loads((FITS / league / "summary.json").read_text())
    encoded = (json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    assert summary["joint_input_rows_sha256"] == hashlib.sha256(encoded).hexdigest()
    assert summary["training_n"] == n
    assert summary["action_authority"] is False
    for entry in summary["artifacts"]:
        model = json.loads((FITS / league / (entry["method"] + ".json")).read_text())
        V._validate_fit(model)
        assert model["artifact_sha256"] == entry["artifact_sha256"]
        assert model["training_sha256"] == D.digest(rows)
        assert model["source_provenance"] == provenance
        assert model["status"] == "FITTED_RESEARCH_NOT_VALIDATED"
        assert model["prospective_grade_eligible"] is False
        d = V.predict(model, home_mean=rows[0]["predicted_home"], away_mean=rows[0]["predicted_away"],
                      event_id="UNSEEN_SYNTHETIC_SOFTWARE_CHECK", cutoff="2026-11-05T00:00:00Z",
                      start_time_utc="2026-11-06T00:00:00Z",
                      parent_model_id=model["parent_model_id"], information_set=model["information_set"],
                      parent_forecast_sha256="a"*64)
        assert d["provenance"]["fit_source_provenance"]["prospective_evidence"] is False
        V.validate(d)


def test_replay_converter_refuses_blocked_league():
    with pytest.raises(ValueError, match="LEAGUE_UNSUPPORTED"):
        build_rows(INPUT, "cfb")
