"""Full parent-to-PMF software checks; synthetic residuals are not validation."""
import copy

import numpy as np
import pytest

from models.common import discrete_research as D
from models.nfl.contextual.runtime import run
from pipelines.cards.distribution_research import build, nfl_card
from pipelines.cards.selection import select
from pipelines.cards.semantic_identity import (
    LEGACY, SEMANTIC, reidentify_nfl_run, simulate_distribution,
)
from tests.semantic_identity_fixtures import package
from tests.test_cross_sport_distributions import training, FITTED
from tests.test_semantic_identity import execute, nfl_inputs, CUTOFF, QUOTES, LEAGUES


def parent_card(league, quote_index, directory, monkeypatch, semantics=SEMANTIC):
    quote = copy.deepcopy(QUOTES[quote_index])
    if league == "nfl":
        args = nfl_inputs()
        args[4].update(market_quotes=quote, display_metadata=str(quote_index))
        parent, w, s = run(*args, 100000, model_id=select("nfl")["default_model_id"])
        parent, _, _ = reidentify_nfl_run(args[0], args[4], args[5], parent, w, s, semantics=semantics)
        return nfl_card(parent, args[5])
    p = package(league)
    p["market_quotes"] = quote
    p["events"][0].update(market_quotes=quote, display_metadata=str(quote_index))
    raw, _ = execute(p, directory, monkeypatch, semantics=semantics)
    return {"league": league.upper(), "as_of_utc": CUTOFF, "generated_at_utc": CUTOFF,
            "forecasts": [{**p["events"][0], **raw, "forecast_status": "FORECAST_GENERATED"}]}


def distribution_config(card):
    league = card["league"].lower()
    parent = card["forecasts"][0]
    rows = training(league, "margin")
    for row in rows:
        row["parent_model_id"] = parent["model_id"]
    model = D.fit_residuals(rows, league=league, product="margin", settlement=rows[0]["settlement"],
        parent_model_id=parent["model_id"], fitted_at=FITTED, information_set="PREGAME")
    contract = {"event_id": parent["event_id"], "product": "margin", "settlement": model["settlement"],
                "kind": "HYPOTHETICAL", "line": -1.5, "side": "HOME"}
    return {"information_set": "PREGAME", "config_file_sha256": D.digest(model),
            "loaded_models": [{"model": model, "calibrator": None}], "contracts": [contract]}


def full_chain(league, directory, monkeypatch, semantics=SEMANTIC):
    cards = [parent_card(league, i, directory / ("parent-" + str(i)), monkeypatch, semantics) for i in range(2)]
    config = distribution_config(cards[0])
    reports = [build(card, config, directory / ("distribution-" + str(i))) for i, card in enumerate(cards)]
    for report in reports:
        assert report["coverage"][0]["status"] == "COMPLETED", report["coverage"]
    return cards, reports


@pytest.mark.parametrize("league", LEAGUES + ("nfl",))
def test_full_selected_parent_to_pmf_draw_chain_is_metadata_invariant(league, tmp_path, monkeypatch):
    cards, reports = full_chain(league, tmp_path, monkeypatch)
    a, b = [r["results"][0] for r in reports]
    da, db = a["distribution"], b["distribution"]
    assert D.digest(cards[0]) != D.digest(cards[1])
    assert da["distribution_sha256"] != db["distribution_sha256"]
    assert da["support"] == db["support"] and da["masses"] == db["masses"]
    assert a["simulation"]["numerical_identity"] == b["simulation"]["numerical_identity"]
    assert a["simulation"]["draw_sha256"] == b["simulation"]["draw_sha256"]
    assert a["simulation"]["file_sha256"] == b["simulation"]["file_sha256"]
    assert a["contracts"] == b["contracts"]
    # Preserve the demonstrable legacy leakage, without rewriting its sampler.
    wa, ma = D.simulate(da); wb, mb = D.simulate(db)
    assert ma["seed"] != mb["seed"] and not np.array_equal(wa, wb)


def test_relevant_pmf_mass_support_target_or_draw_count_changes_identity(tmp_path, monkeypatch):
    cards, reports = full_chain("nfl", tmp_path, monkeypatch)
    card = cards[0]; row = card["forecasts"][0]; d = reports[0]["results"][0]["distribution"]
    base, bm = simulate_distribution(d, row, card["as_of_utc"])
    variants = []
    mass = list(d["masses"]); mass[0] *= 2
    variants.append(D.make_distribution(d["support"], mass, league="nfl", product="margin", settlement=d["settlement"], model_id=d["model_id"], provenance=d["provenance"]))
    variants.append(D.make_distribution([v+10 for v in d["support"]], d["masses"], league="nfl", product="margin", settlement=d["settlement"], model_id=d["model_id"], provenance=d["provenance"]))
    variants.append(D.make_distribution([abs(v)+20 for v in d["support"]], d["masses"], league="nfl", product="total", settlement=d["settlement"], model_id=d["model_id"], provenance=d["provenance"]))
    for changed in variants:
        draws, meta = simulate_distribution(changed, row, card["as_of_utc"])
        assert meta["numerical_identity"] != bm["numerical_identity"]
        assert not np.array_equal(draws, base)
    _, shorter = simulate_distribution(d, row, card["as_of_utc"], draws=99999)
    assert shorter["numerical_identity"] != bm["numerical_identity"]


def test_pmf_and_parent_integrity_refusals_do_not_fall_back(tmp_path, monkeypatch):
    cards, reports = full_chain("nfl", tmp_path, monkeypatch)
    card = cards[0]; row = card["forecasts"][0]; d = reports[0]["results"][0]["distribution"]
    bad = copy.deepcopy(d); bad["masses"][0] += .01
    with pytest.raises(ValueError):
        simulate_distribution(bad, row, card["as_of_utc"])
    bad_parent = copy.deepcopy(row); bad_parent["numerical_identity"]["feature_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="PARENT_HASH_MISMATCH"):
        simulate_distribution(d, bad_parent, card["as_of_utc"])
    for malformed in (["not-a-mapping"], "not-a-mapping", 3):
        bad_parent = copy.deepcopy(row); bad_parent["numerical_identity"] = malformed
        with pytest.raises(ValueError, match="PARENT_HASH_MISMATCH"):
            simulate_distribution(d, bad_parent, card["as_of_utc"])
    bad_parent = copy.deepcopy(row); bad_parent["event_id"] = "other"
    with pytest.raises(ValueError, match="PARENT_TARGET_MISMATCH"):
        simulate_distribution(d, bad_parent, card["as_of_utc"])
    legacy_parent = copy.deepcopy(row); legacy_parent.pop("identity_semantics")
    with pytest.raises(ValueError, match="NUMERIC_PARENT_REQUIRED"):
        simulate_distribution(d, legacy_parent, card["as_of_utc"])
    config = distribution_config(card)
    for i, semantics in enumerate(["unknown", SEMANTIC]):
        bad_card = copy.deepcopy(card)
        bad_card["forecasts"][0]["identity_semantics"] = semantics
        bad_card["forecasts"][0].pop("numerical_identity")
        report = build(bad_card, config, tmp_path / ("refusal-" + str(i)))
        assert not report["results"] and report["coverage"][0]["status"] == "UNAVAILABLE"


def test_unlabelled_legacy_parent_uses_exact_existing_distribution_sampler(tmp_path, monkeypatch):
    cards, reports = full_chain("nba", tmp_path, monkeypatch, LEGACY)
    for report in reports:
        r = report["results"][0]
        draws, metadata = D.simulate(r["distribution"])
        assert all(r["simulation"][k] == v for k, v in metadata.items())
        assert "numerical_identity" not in r["simulation"]
