import copy
import json

import pytest

from models.common import discrete_research as D
from pipelines.cards.candidate_board import INPUT_SCHEMA, build_board, run_file


def fixture():
    binding = {"event_id": "test:1", "league": "nba", "product": "margin",
               "settlement": "FULL_GAME_OT", "cutoff": "2026-10-01T10:00:00Z",
               "parent_forecast_sha256": "a" * 64, "orientation": "HOME_MINUS_AWAY",
               "orientation_evidence_sha256": "b" * 64}
    d = D.make_distribution([-7, 3, 7], [.25, .3, .45], league="nba", product="margin",
                            settlement="FULL_GAME_OT", model_id="synthetic.margin.v1", provenance={
                                k: binding[k] for k in ("event_id", "cutoff", "parent_forecast_sha256")})
    quote = {"source_class": "TEST_ONLY", "source_sha256": "c" * 64, "book": None,
             "retrieved_at_utc": None, "provider_updated_at_utc": None}
    contract = {"event_id": "test:1", "league": "nba", "product": "margin", "period": "full_game",
                "settlement": "FULL_GAME_OT", "side": "HOME", "line": -3.,
                "distribution_sha256": d["distribution_sha256"], "odds": -110,
                "odds_format": "american", "quote": quote}
    return {"schema": INPUT_SCHEMA,
            "events": [{"event_id": "test:1", "league": "nba", "matchup": "A @ B"},
                       {"event_id": "test:2", "league": "cfb", "matchup": "unsupported @ missing"}],
            "distributions": [{"distribution": d, "binding": binding}],
            "contracts": [contract, {**copy.deepcopy(contract), "side": "AWAY"}]}


def test_independent_settlement_oracle_inventory_and_preservation():
    payload = fixture(); original = copy.deepcopy(payload)
    report = build_board(payload)
    row = report["rows"][0]
    assert row["contract"]["side"] == "HOME"
    assert row["probabilities"] == {"win": .45, "half_win": 0., "push": .3, "half_loss": 0., "loss": .25, "void": 0.}
    assert row["winning_settlement_probability"] == .45  # not .45/.7 ex-push
    assert report["coverage"][1]["candidate"] is None
    assert report["candidate_count"] == 1 and report["event_count"] == 2
    assert row["risk"]["expected_return_per_unit"] == pytest.approx(.45 * 100/110 - .25)
    assert payload == original and row["model_id"] == "synthetic.margin.v1"
    assert report["wagering_authority"] == "OFF"
    assert "QUOTE_BOOK_UNKNOWN" in row["missing_inputs"]


def test_price_changes_do_not_change_probability_selection_or_negative_ev_visibility():
    p = fixture(); before = build_board(p)
    p["contracts"][0]["odds"] = -10000
    p["contracts"][1]["odds"] = 10000
    after = build_board(p)
    assert before["rows"][0]["contract_id"] == after["rows"][0]["contract_id"]
    assert after["rows"][0]["risk"]["price_assessment"] == "NEGATIVE_MODEL_EV"
    assert after["rows"][0]["selection_eligibility"] == "RESEARCH_ONLY"


@pytest.mark.parametrize("key,value", [("event_id", "test:2"), ("league", "nhl"), ("product", "total"),
                                      ("settlement", "REGULATION"), ("period", "first_half"),
                                      ("line", True), ("line", float("nan")), ("side", "over")])
def test_wrong_contract_or_head_refused(key, value):
    p = fixture(); p["contracts"][0][key] = value
    with pytest.raises(ValueError):
        build_board(p)


@pytest.mark.parametrize("key,value", [("orientation", "AWAY_MINUS_HOME"), ("parent_forecast_sha256", "d"*64),
                                      ("cutoff", "2026-10-01T11:00:00Z"), ("product", "total"),
                                      ("orientation_evidence_sha256", None)])
def test_binding_mutation_refused(key, value):
    p = fixture(); p["distributions"][0]["binding"][key] = value
    with pytest.raises(ValueError):
        build_board(p)


def test_duplicate_events_and_contract_vintages_are_not_silently_resolved():
    p = fixture(); p["events"].append(copy.deepcopy(p["events"][0]))
    with pytest.raises(ValueError, match="DUPLICATE_EVENT"):
        build_board(p)
    p = fixture(); p["contracts"].append({**copy.deepcopy(p["contracts"][0]), "odds": -120})
    with pytest.raises(ValueError, match="DUPLICATE_CONTRACT"):
        build_board(p)


def test_complete_quote_metadata_cannot_authenticate_raw_terms_or_rules():
    p = fixture()
    for c in p["contracts"]:
        c["quote"].update(book="Example", retrieved_at_utc="2026-10-01T12:00:00Z",
                          provider_updated_at_utc="2026-10-01T11:59:00Z")
    row = build_board(p)["rows"][0]
    assert row["missing_inputs"] == ["QUOTE_TERMS_RAW_BINDING_UNVERIFIED", "SETTLEMENT_RULES_UNVERIFIED"]
    assert row["provider_authenticity"] == "NOT_ASSESSED"


def test_higher_confidence_challenger_cannot_become_implicit_selected_model():
    p = fixture(); challenger = copy.deepcopy(p["distributions"][0])
    challenger["distribution"].update(model_id="unselected.challenger", masses=[.01, .01, .98])
    challenger["distribution"].pop("distribution_sha256")
    challenger["distribution"]["distribution_sha256"] = D.digest(challenger["distribution"])
    p["distributions"].append(challenger)
    quote = copy.deepcopy(p["contracts"][0]); quote["distribution_sha256"] = challenger["distribution"]["distribution_sha256"]
    p["contracts"].append(quote)
    with pytest.raises(ValueError, match="EXPLICIT_UPSTREAM_MODEL_SELECTION"):
        build_board(p)


def test_quote_chronology_refused_and_missing_times_not_fabricated():
    p = fixture(); p["contracts"][0]["quote"].update(retrieved_at_utc="2026-10-01T12:00:00Z",
                                                    provider_updated_at_utc="2026-10-01T13:00:00Z")
    with pytest.raises(ValueError, match="QUOTE_PROVIDER_TIME"):
        build_board(p)


def test_rank_within_league_does_not_use_ev_or_ex_push_probability():
    p = fixture(); p["events"] = p["events"][:1]
    p["events"].append({"event_id": "test:3", "league": "nba", "matchup": "C @ D"})
    entry = copy.deepcopy(p["distributions"][0]); entry["binding"]["event_id"] = "test:3"
    entry["distribution"]["provenance"]["event_id"] = "test:3"
    entry["distribution"]["masses"] = [.1, .5, .4]
    entry["distribution"].pop("distribution_sha256")
    entry["distribution"]["distribution_sha256"] = D.digest(entry["distribution"])
    p["distributions"].append(entry)
    c = copy.deepcopy(p["contracts"][0]); c.update(event_id="test:3", odds=500,
        distribution_sha256=entry["distribution"]["distribution_sha256"])
    p["contracts"].append(c)
    rows = build_board(p)["rows"]
    assert [(r["event_id"], r["league_rank"]) for r in rows] == [("test:1", 1), ("test:3", 2)]
    assert rows[0]["risk"]["expected_return_per_unit"] < rows[1]["risk"]["expected_return_per_unit"]


def test_quarter_handicap_complete_states_and_total_binding():
    p = fixture(); p["events"] = [{"event_id": "test:1", "league": "mls", "matchup": "A @ B"}]
    b = p["distributions"][0]["binding"]; b.update(league="mls", settlement="REGULATION_90_STOPPAGE")
    d = D.make_distribution([-1, 0, 1], [.2, .3, .5], league="mls", product="margin",
        settlement="REGULATION_90_STOPPAGE", model_id="synthetic.mls", provenance={
            k: b[k] for k in ("event_id", "cutoff", "parent_forecast_sha256")})
    p["distributions"][0]["distribution"] = d
    for c in p["contracts"]:
        c.update(league="mls", settlement="REGULATION_90_STOPPAGE", period="regulation", line=-.25,
                 distribution_sha256=d["distribution_sha256"])
    report = build_board(p)
    home = next(r for r in report["all_contracts"] if r["contract"]["side"] == "HOME")
    assert home["probabilities"]["half_loss"] == .3
    assert home["risk"]["expected_return_per_unit"] == pytest.approx(.5*100/110 - .15 - .2)
    away = next(r for r in report["all_contracts"] if r["contract"]["side"] == "AWAY")
    assert away["positive_return_probability"] == .5
    assert away["winning_settlement_probability"] == .2


def test_file_cli_boundary_is_immutable_and_invalid_input_creates_no_output(tmp_path):
    source = tmp_path / "input.json"; source.write_text(json.dumps(fixture()))
    raw = source.read_bytes(); output = tmp_path / "board"
    run_file(source, output)
    saved = (output / "candidate_board.json").read_bytes()
    with pytest.raises(FileExistsError):
        run_file(source, output)
    assert (output / "candidate_board.json").read_bytes() == saved and source.read_bytes() == raw
    source.write_text(json.dumps({"schema": "bad"}))
    with pytest.raises(ValueError):
        run_file(source, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()
