import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from models.common import discrete_research as D
from pipelines.cards import disclosures as C

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = "2026-10-20T16:00:00Z"
HASH = "a" * 64


def card(league="CFB"):
    return {"league": league, "as_of_utc": CUTOFF, "forecasts": [
        {"event_id": "event-1", "model_id": "parent.v1", "input_snapshot_hash": HASH,
         "forecast_status": "FORECAST_GENERATED", "model_input_snapshot": {"qb": "player-1"},
         "analytic_p": .6, "sim_p": .601}]}


def event():
    return {"event_id": "event-1", "parent_model_id": "parent.v1", "parent_input_sha256": HASH,
            "known_inputs": [{"name": "expected_qb", "value": "player-1", "source_sha256": HASH,
                "observed_at_utc": "2026-10-20T14:00:00Z", "retrieved_at_utc": "2026-10-20T15:00:00Z",
                "input_path": ["qb"]}],
            "unknown_inputs": [{"name": "final_availability", "reason": "Final report not captured."}],
            "assumptions": [{"name": "rotation", "value": "starter plays", "rationale": "Conditional scenario only."}],
            "availability_scenarios": [{"scenario_id": "in", "conditions": [{"entity_id": "player-1", "availability": "IN"}], "rationale": "Availability unresolved."},
                                       {"scenario_id": "out", "conditions": [{"entity_id": "player-1", "availability": "OUT"}], "rationale": "Availability unresolved."}],
            "pass_reasons": [{"code": "METHOD_INSTABILITY", "detail": "Two methods disagree.", "evidence_ref": "study:example"}]}


def packet():
    return {"schema": C.INPUT_SCHEMA, "action_authority": False, "events": [event()]}


def write_json(tmp_path, name, value):
    path = tmp_path / name
    path.write_text(json.dumps(value, allow_nan=False))
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def leg(lid, product, side, line, *, league="cfb", settlement="FULL_GAME_OT"):
    return {"leg_id": lid, "event_id": "event-1", "model_id": "distribution.v1",
            "league": league, "product": product, "settlement": settlement, "side": side, "line": line}


def parlay():
    return {"parlay_id": "five-leg-example", "legs": [
        leg("over27", "total", "OVER", 27.5), leg("under75", "total", "UNDER", 75.5),
        leg("over30", "total", "OVER", 30.5), leg("home20", "margin", "HOME", 20.5),
        leg("under72", "total", "UNDER", 72.5)]}


def draws(spec):
    bindings = {D.digest({k: l[k] for k in ("event_id", "model_id", "league", "product", "settlement")}):
                {k: l[k] for k in ("event_id", "model_id", "league", "product", "settlement")} for l in spec["legs"]}
    return {"schema": "sports.joint_draw_disclosure.research.v1", "joint_model_id": "synthetic.joint.v1",
            "joint_model_sha256": HASH, "dependence_assumption": "SYNTHETIC paired outcomes; no predictive claim",
            "draw_count": 4, "cutoff": CUTOFF,
            "parent_bindings": {"event-1": {"model_id": "parent.v1", "input_snapshot_hash": HASH}},
            "variables": [{"variable_id": k, "binding": b,
                           "values": [40, 60, 29, 80] if b["product"] == "total" else [6, -2, 9, -24]}
                          for k, b in bindings.items()]}


def evaluate(spec, tmp_path):
    return C.parlay_disclosure(spec, {r["event_id"]: r for r in card()["forecasts"]}, tmp_path,
                              cutoff=CUTOFF, league="CFB")


@pytest.mark.parametrize("league", ["NFL", "CFB", "NBA", "WNBA", "MLB", "NHL", "MLS"])
def test_default_disclosures_preserve_every_sport_parent(league):
    parent = card(league); before = D.digest(parent)
    report = C.build_report(parent)
    assert before == D.digest(parent) == report["parent_card_sha256"]
    row = report["events"][0]
    assert row["decision"] == "PASS" and not row["action_authority"]
    assert row["unknown_inputs"] and not row["availability_scenarios"]
    assert report["predictive_validation"] == "NOT_ASSESSED"


def test_knowledge_states_conditional_scenarios_and_pass_reasons():
    p = packet(); before = D.digest(p)
    report = C.build_report(card(), p)
    row = report["events"][0]
    assert not report["errors"] and before == D.digest(p)
    assert row["known_inputs"][0]["numerical_use"] == "BOUND_TO_PARENT_INPUT_NOT_CONSUMPTION_PROOF"
    assert row["assumptions"][0]["numerical_use"] == "NOT_ESTABLISHED"
    assert all(s["weight"] is None and s["probability_of_playing"] is None and s["execution_status"] == "NOT_RUN"
               for s in row["availability_scenarios"])
    assert row["pass_reasons"][-1]["evidence_status"] == "SUPPLIED_NOT_INDEPENDENTLY_VERIFIED"
    rendered = C.render_md(report)
    for text in ["Unknown inputs", "Assumptions", "METHOD_INSTABILITY", "no availability weights"]:
        assert text in rendered


@pytest.mark.parametrize("field,value,reason", [
    ("parent_model_id", "other.arm", "DISCLOSURE_PARENT_MISMATCH"),
    ("parent_input_sha256", "b" * 64, "DISCLOSURE_PARENT_MISMATCH"),
    ("decision", "BET", "UNSUPPORTED_DISCLOSURE_FIELD"),
    ("action_authority", True, "UNSUPPORTED_DISCLOSURE_FIELD"),
])
def test_parent_mismatch_and_authority_fail_closed(field, value, reason):
    p = packet(); p["events"][0][field] = value
    report = C.build_report(card(), p)
    assert report["execution_status"] == "PARTIAL" and reason in report["errors"][0]["reason"]
    assert report["events"][0]["decision"] == "PASS"


@pytest.mark.parametrize("mutation,reason", [
    (lambda e: e["known_inputs"][0].update(retrieved_at_utc="2026-10-20T17:00:00Z"), "AFTER_CUTOFF"),
    (lambda e: e["known_inputs"][0].update(value="wrong qb"), "VALUE_MISMATCH"),
    (lambda e: e["known_inputs"][0].update(used=True), "UNSUPPORTED_DISCLOSURE_FIELD"),
    (lambda e: e["unknown_inputs"][0].update(name="expected_qb"), "KNOWLEDGE_STATE_CONFLICT"),
    (lambda e: e["availability_scenarios"][0].update(weight=.5), "UNSUPPORTED_DISCLOSURE_FIELD"),
    (lambda e: e["availability_scenarios"][0].update(probability_of_playing=.5), "UNSUPPORTED_DISCLOSURE_FIELD"),
    (lambda e: e["availability_scenarios"].append(copy.deepcopy(e["availability_scenarios"][0])), "DUPLICATE_SCENARIO_ID"),
    (lambda e: e["availability_scenarios"][0]["conditions"][0].update(availability="CONFIRMED"), "AVAILABILITY_INVALID"),
    (lambda e: e["pass_reasons"][0].pop("evidence_ref"), "EVIDENCE_REFERENCE_REQUIRED"),
])
def test_invalid_input_evidence_is_visible_and_other_events_continue(mutation, reason):
    p = packet(); mutation(p["events"][0])
    c = card(); c["forecasts"].append({**c["forecasts"][0], "event_id": "event-2"})
    report = C.build_report(c, p)
    assert len(report["events"]) == 2 and len(report["errors"]) == 1
    assert reason in report["errors"][0]["reason"]


def test_conditional_distribution_requires_exact_parent_and_conditions(tmp_path):
    p = packet(); scenario = p["events"][0]["availability_scenarios"][0]
    provenance = {"event_id": "event-1", "cutoff": CUTOFF, "parent_model_id": "parent.v1",
        "base_input_sha256": HASH, "scenario_id": "in", "scenario_conditions_sha256": D.digest(scenario["conditions"])}
    d = D.make_distribution([1, 3], [.5, .5], league="cfb", product="margin", settlement="FULL_GAME_OT",
                            model_id="conditional.v1", provenance=provenance)
    scenario["distribution_artifact"] = write_json(tmp_path, "scenario.json", d)
    report = C.build_report(card(), p, root=tmp_path)
    s = report["events"][0]["availability_scenarios"][0]
    assert s["conditional_mean"] == 2 and s["weight"] is None and s["predictive_validation"] == "NOT_ASSESSED"
    scenario["conditions"][0]["availability"] = "OUT"
    assert "CONDITION_MISMATCH" in C.build_report(card(), p, root=tmp_path)["errors"][0]["reason"]


def test_five_nominal_three_effective_constraints_are_proven_without_draws(tmp_path):
    spec = parlay(); spec.update(reported_joint_probability=.83415, report_source_sha256=HASH)
    report = evaluate(spec, tmp_path)
    assert report["nominal_leg_count"] == 5 and report["effective_constraint_count"] == 3
    assert {r["leg_id"] for r in report["redundant_legs"]} == {"over27", "under75"}
    assert report["recomputed_joint_probability"] is None
    assert report["intersection_status"] == "REPORTED_NOT_REPLAYED"
    assert report["sampler_replay_status"] == "NOT_PERFORMED"


def test_same_draw_intersection_differs_from_naive_product_and_is_not_validation(tmp_path):
    spec = parlay(); spec["joint_draw_artifact"] = write_json(tmp_path, "joint.json", draws(spec))
    report = evaluate(spec, tmp_path)
    assert report["recomputed_joint_probability"] == .5
    assert report["naive_independent_product"] == pytest.approx(.75**4)
    assert report["dependence_effect"] == pytest.approx(.5-.75**4)
    assert report["intersection_status"] == "RECOMPUTED_FROM_SUPPLIED_JOINT_DRAWS"
    assert report["sampler_replay_status"] == "NOT_PERFORMED" and report["predictive_validation"] == "NOT_ESTABLISHED"
    assert report["offered_odds"] is None and report["expected_value"] is None


@pytest.mark.parametrize("mutation,reason", [
    (lambda a: a.update(draw_count=5), "COUNT_OR_SUPPORT_MISMATCH"),
    (lambda a: a["variables"][0]["values"].append(1), "COUNT_OR_SUPPORT_MISMATCH"),
    (lambda a: a["variables"][0]["values"].__setitem__(0, .25), "COUNT_OR_SUPPORT_MISMATCH"),
    (lambda a: a["variables"].pop(), "COVERAGE_MISMATCH"),
    (lambda a: a["variables"].append(copy.deepcopy(a["variables"][0])), "DUPLICATE_VARIABLE_ID"),
    (lambda a: a["variables"][0]["binding"].update(model_id="other"), "IDENTITY_MISMATCH"),
    (lambda a: a.update(cutoff="2026-10-21T16:00:00Z"), "CUTOFF_MISMATCH"),
    (lambda a: a["parent_bindings"]["event-1"].update(model_id="combined.not.qb"), "PARENT_OR_CUTOFF_MISMATCH"),
    (lambda a: a.pop("dependence_assumption"), "DEPENDENCE_ASSUMPTION_REQUIRED"),
])
def test_draw_evidence_mismatches_fail_closed(tmp_path, mutation, reason):
    spec = parlay(); artifact = draws(spec); mutation(artifact)
    spec["joint_draw_artifact"] = write_json(tmp_path, "joint.json", artifact)
    with pytest.raises(ValueError, match=reason): evaluate(spec, tmp_path)


def test_reported_probability_must_match_retained_intersection(tmp_path):
    spec = parlay(); spec.update(reported_joint_probability=.99, report_source_sha256=HASH)
    spec["joint_draw_artifact"] = write_json(tmp_path, "joint.json", draws(spec))
    with pytest.raises(ValueError, match="REPORTED_JOINT_DOES_NOT_MATCH_DRAWS"): evaluate(spec, tmp_path)


def test_contradictory_integer_contracts_cannot_have_positive_joint_probability(tmp_path):
    spec = {"parlay_id": "contradiction", "legs": [leg("over", "total", "OVER", 30), leg("under", "total", "UNDER", 31)],
            "reported_joint_probability": .5, "report_source_sha256": HASH}
    with pytest.raises(ValueError, match="IMPOSSIBLE_JOINT_PROBABILITY"): evaluate(spec, tmp_path)


def test_nested_contracts_do_not_collapse_different_settlement_or_model(tmp_path):
    spec = parlay(); spec["legs"][0]["model_id"] = "different.model"
    assert evaluate(spec, tmp_path)["effective_constraint_count"] == 4
    spec["legs"][0]["league"] = "nhl"
    with pytest.raises(ValueError, match="LEAGUE_MISMATCH"): evaluate(spec, tmp_path)


def test_duplicates_reduce_deterministically_and_push_is_not_full_win(tmp_path):
    spec = {"parlay_id": "duplicates", "legs": [leg("b", "margin", "HOME", -3), leg("a", "margin", "HOME", -3)]}
    artifact = draws(spec); artifact["variables"][0]["values"] = [3, 4, 5, 2]
    spec["joint_draw_artifact"] = write_json(tmp_path, "joint.json", artifact)
    report = evaluate(spec, tmp_path)
    assert report["effective_leg_ids"] == ["a"] and report["recomputed_joint_probability"] == .5
    spec["legs"].reverse()
    assert evaluate(spec, tmp_path)["effective_leg_ids"] == ["a"]


@pytest.mark.parametrize("side,line,expected", [("HOME", -.25, ("gt", .5)), ("AWAY", -.25, ("lt", 0)),
                                                ("OVER", 2.25, ("gt", 2.5)), ("UNDER", 2.25, ("lt", 2))])
def test_mls_quarter_line_full_win_constraints(side, line, expected):
    product = "margin" if side in {"HOME", "AWAY"} else "total"
    l = leg("q", product, side, line, league="mls", settlement="REGULATION_90_STOPPAGE")
    assert C._constraint(l) == expected
    for value in range(-5 if product == "margin" else 0, 8):
        direction, threshold = expected
        full_win = value > threshold if direction == "gt" else value < threshold
        assert full_win == (D.outcome(value, league="mls", product=product, settlement=l["settlement"], line=line, side=side) == "win")


def test_file_tampering_and_outside_root_are_rejected(tmp_path):
    spec = parlay(); spec["joint_draw_artifact"] = write_json(tmp_path, "joint.json", draws(spec))
    (tmp_path / "joint.json").write_text("{}")
    with pytest.raises(ValueError, match="HASH_MISMATCH"): evaluate(spec, tmp_path)
    spec["joint_draw_artifact"]["path"] = "../other.json"
    with pytest.raises(ValueError, match="OUTSIDE_PACKET"): evaluate(spec, tmp_path)


@pytest.mark.parametrize("value", [5, 500])
def test_joint_margin_and_total_must_represent_legal_paired_scores(tmp_path, value):
    spec = parlay(); artifact = draws(spec)
    for variable in artifact["variables"]:
        if variable["binding"]["product"] == "margin": variable["values"][0] = value
    spec["joint_draw_artifact"] = write_json(tmp_path, "joint.json", artifact)
    with pytest.raises(ValueError, match="JOINT_SCORE_PARITY_OR_NONNEGATIVITY"): evaluate(spec, tmp_path)


def test_non_object_joint_artifact_is_rejected_without_losing_event_reports(tmp_path):
    p = packet(); spec = parlay(); p["parlays"] = [spec]
    spec["joint_draw_artifact"] = write_json(tmp_path, "joint.json", None)
    report = C.build_report(card(), p, root=tmp_path)
    assert report["events"] and "OBJECT_REQUIRED" in report["errors"][0]["reason"]


@pytest.mark.parametrize("invalid", [[], False, {"schema": C.INPUT_SCHEMA, "action_authority": True},
                                      {"schema": C.INPUT_SCHEMA, "action_authority": False, "sampler_replay_status": "VERIFIED"}])
def test_invalid_packet_and_caller_attestation_cannot_grant_authority(invalid):
    with pytest.raises(ValueError): C.build_report(card(), invalid)


def test_standalone_cli_preserves_frozen_card_and_refuses_output_overwrite(tmp_path):
    src = tmp_path / "card.json"; src.write_text(json.dumps(card()))
    before = src.read_bytes(); out = tmp_path / "report"
    command = [sys.executable, str(ROOT / "scripts/render_card_disclosures.py"), "--card", str(src), "--output", str(out)]
    first = subprocess.run(command, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    saved = (out / "disclosures.json").read_bytes()
    report = json.loads(saved); actual_hash = report.pop("artifact_sha256")
    assert actual_hash == D.digest(report) and src.read_bytes() == before
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert (out / "disclosures.json").read_bytes() == saved


def test_rejected_parlay_is_an_explicit_partial_failure(tmp_path):
    p = packet(); p["parlays"] = [parlay()]; p["parlays"][0]["legs"][0]["event_id"] = "wrong"
    report = C.build_report(card(), p, root=tmp_path)
    assert report["execution_status"] == "PARTIAL" and report["parlays"] == []
    assert "NOT_IN_CARD" in report["errors"][0]["reason"]


@pytest.mark.parametrize("league", ["nfl", "cfb", "nba", "wnba", "mlb", "nhl", "mls"])
def test_shared_runner_emits_disclosures_without_changing_probabilities(tmp_path, monkeypatch, league):
    import datetime as dt
    from types import SimpleNamespace
    from scripts import generate_card_force as runner
    from pipelines.cards import selected
    game = {"event_id": "event-1", "home_team": "Home", "away_team": "Away", "start_time_utc": "2099-10-20T23:00:00Z"}
    raw = {"model_p": .6, "sim_p": .601, "model_winner": "Home", "model_id": "parent.v1", "dose": 0,
           "input_snapshot_hash": HASH, "model_state_config_hash": HASH, "model_input_snapshot": {"qb": "player-1"}}
    adapter = SimpleNamespace(load_schedule=lambda *a: [game], build_context=lambda *a: {},
                              forecast_event=lambda *a: copy.deepcopy(raw))
    monkeypatch.setattr(runner, "load_adapter", lambda *a: adapter)
    monkeypatch.setattr(runner, "now_utc", lambda: dt.datetime(2026, 10, 20, 16, 0, tzinfo=dt.timezone.utc))
    monkeypatch.setattr(selected, "apply_default", lambda league, event, row: row)
    out = tmp_path / league
    p = tmp_path / "packet.json"; p.write_text(json.dumps(packet()))
    monkeypatch.setattr(sys, "argv", ["generate", "--league", league, "--date", "2026-10-20", "--as-of-utc", CUTOFF,
                                      "--output-dir", str(out), "--disclosures", str(p)])
    with pytest.raises(SystemExit) as exc: runner.main()
    assert exc.value.code == 0
    parent = json.loads((out / "diagnostic_card.json").read_text())
    report = json.loads((out / "disclosures/disclosures.json").read_text())
    assert parent["forecasts"][0]["analytic_p"] == .6 and parent["forecasts"][0]["sim_p"] == .601
    assert report["parent_card_sha256"] == D.digest(parent)
    assert "METHOD_INSTABILITY" in (out / "diagnostic_card.md").read_text()


def test_nfl_separate_runner_emits_bound_disclosure_sidecar(tmp_path, monkeypatch):
    from scripts import run_nfl_integrated as runner
    from models.nfl.contextual import week2
    game = {"event_id": "event-1", "home_team": "Home", "away_team": "Away", "start_time_utc": "2099-10-20T23:00:00Z"}
    bundle = {"schema": "nfl.integrated_context_forecast.v1", "mode": "research_pregame", "event": game,
              "cutoff_utc": CUTOFF, "model_id": "parent.v1", "model_artifact_sha256": HASH,
              "features": {"qb": "player-1"}, "prediction": {}, "winner_simulation": {}, "score_simulation": {}}
    context = {"model": {"design": {}}, "recovered": {}, "package": {"event_inputs": {"event-1": {"base": {}, "context": {}}}}}
    monkeypatch.setattr(runner.nfl, "load_schedule", lambda *a: [game])
    monkeypatch.setattr(runner.nfl, "build_context", lambda *a, **kw: context)
    monkeypatch.setattr(week2, "applies", lambda *a: False)
    monkeypatch.setattr(runner, "run", lambda *a, **kw: (copy.deepcopy(bundle), [1], None))
    def persist(folder, result, *args):
        folder.mkdir(parents=True)
        (folder / "forecast.json").write_text(json.dumps(result))
        (folder / "registration.jsonl").write_text(json.dumps({"created_at_utc": CUTOFF}))
    monkeypatch.setattr(runner, "persist_run", persist)
    out = tmp_path / "nfl"
    monkeypatch.setattr(sys, "argv", ["run", "--date", "2026-10-20", "--output", str(out)])
    runner.main()
    report = json.loads((out / "event-1/disclosures/disclosures.json").read_text())
    assert report["events"][0]["parent_model_id"] == "parent.v1"
    assert json.loads((out / "event-1/forecast.json").read_text()) == bundle
