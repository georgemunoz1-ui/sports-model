"""Retained CIN–ATL evidence must be visible on the actual published card paths."""
from copy import deepcopy
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from models.nfl.contextual.model import load_artifact
from pipelines.cards.nfl_missingness import audit
from pipelines.cards.missingness_presentation import audit_view, render_md
from pipelines.cards.recipient_card import write_recipient_card, verify_recipient_card
from scripts.generate_card_force import render_md as render_card

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def card():
    case = json.loads((ROOT / "tests/fixtures/nfl_missingness/cin_atl.json").read_text())
    model = load_artifact(ROOT / "data/nfl/contextual_v1/model_packed.json")
    receipt = audit(case["refresh"], model, case["prior"])
    row = dict(event_id=receipt["event_id"], home_team="ATL", away_team="CIN",
               forecast_status="FORECAST_GENERATED", model_winner="CIN", model_p=.7, sim_p=.7,
               forecast_tier="TEST_ONLY", dose=0, analytic_p=.7, stochastic_sim_p=.7,
               analytic_sim_gap_pp=0, analytic_sim_divergence="TEST_ONLY", missingness_audit=receipt)
    return dict(league="NFL", card_date="2026-11-08", pregame_coverage=1., forecasts=[row], incidents=[])


@pytest.mark.parametrize("wrapped", [False, True])
def test_native_and_shared_nfl_show_retained_reporting_shift(card, tmp_path, wrapped):
    row = card["forecasts"][0]
    if wrapped:
        row["missingness_audit"] = {**row["missingness_audit"], "details": {
            "status": "NATIVE_NFL_RECEIPT", "native": row["missingness_audit"],
            "refresh": {"status": "NO_PAIRED_PARENT"}}}
    before = deepcopy(card)
    path = tmp_path / "card.html"
    write_recipient_card(card, path)
    assert verify_recipient_card(card, path)["rows"] == 1
    document = ET.fromstring(path.read_bytes())
    html_text = " ".join(document.itertext())
    markdown = render_card(card)
    for text in (html_text, markdown):
        assert "REPORTING_STATE_DOMINATED" in text
        assert "combined / home_margin" in text
        assert "-8.01363 points" in text
        assert "qb / home_win" in text and "home_log_odds" in text
        assert "Model / version" in text and "Unresolved / mixed" in text
        assert "Simulation (separate)" in text
        assert "do not isolate sampling noise" in text
    assert card == before
    path.write_text(path.read_text().replace("REPORTING_STATE_DOMINATED", "CLEARED"))
    with pytest.raises(ValueError, match="READBACK_MISMATCH"):
        verify_recipient_card(card, path)


def test_absent_comparison_and_model_changes_remain_unavailable(card):
    row = card["forecasts"][0]
    receipt = row["missingness_audit"]
    receipt["details"] = {"comparison_status": "MODEL_OR_MODE_CHANGED", "arms": {}}
    text = render_md(card)
    assert "MODEL_OR_MODE_CHANGED" in text
    assert "must not be inferred as zero" in text
    assert "Simulation change: UNAVAILABLE" in text
    del row["missingness_audit"]
    assert audit_view(row)["summary"] == "MISSING RECEIPT"


def test_shared_units_and_unresolved_link_interaction(card):
    receipt = card["forecasts"][0]["missingness_audit"]
    receipt["details"] = {"units": "goals", "refresh": {
        "status": "PAIRED_DIAGNOSTIC", "model_version_change": "SAME_FITTED_PARAMETERS",
        "sim_p_before": .5, "sim_p_after": .6, "side_before": "Home", "side_after": "Away",
        "heads": {"home_margin": {"scale": "native", "substantive": 0,
            "missingness_indicator": -.1, "mixed_imputation_or_unknown": None,
            "native_head_interaction": {"method": "FIXED_MODEL_FOUR_CORNERS",
                                        "interaction": None, "decomposition_complete": False}}}}}
    text = render_md(card)
    assert "goals" in text and "SAME_FITTED_PARAMETERS" in text
    assert "output-scale interaction UNAVAILABLE" in text
    assert "Home P 0.5 → Away P 0.6" in text
    assert "| +0 | -0.1 |" in text


def test_audit_content_is_escaped_in_both_formats(card, tmp_path):
    card["forecasts"][0]["missingness_audit"]["details"]["unresolved_interactions"] = "<script>bad()</script>|x\n"
    path = tmp_path / "card.html"
    write_recipient_card(card, path)
    assert ET.fromstring(path.read_bytes()).findall(".//script") == []
    assert "&lt;script&gt;" in path.read_text()
    assert "&lt;script&gt;bad()&lt;/script&gt;&#124;x" in render_md(card)
