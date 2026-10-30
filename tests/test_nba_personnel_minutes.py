"""Synthetic software evidence only; no sports performance or source-authenticity claims."""
import copy
import datetime as dt
import hashlib
import json
import subprocess
import sys

import pytest

from models.experiments import nba_personnel as m
from research.efficiency.nba_personnel_runner import experiment, shadow_from_card


def seal_sources(row, tmp_path):
    """Explicit TEST_ONLY normalized evidence with every consumed field bound."""
    event, parent, packet = row["event"], row["baseline"], row["personnel"]
    state_object = {"schema": "TEST_ONLY-numeric-parent.v1", "coefficient": [1., 2.]}
    parent["state_sha256"] = m.digest(state_object)
    training = m.parent_training(parent)
    records = {"baseline": m.binding("baseline_forecast", event, {**training, "home_margin": parent["home_margin"]}),
               "parent_state": state_object, "training": {"role": "parent_training", "values": training},
               "roster": m.binding("roster", event, packet["roster_by_team"]), "status": {}, "minutes": {}}
    for player in packet["players"]:
        pid = player["player_id"]
        records["status"][pid] = m.binding("status", event, {k: player[k] for k in ("team_id", "player_id", "status")})
        values = {k: player[k] for k in ("team_id", "player_id", "expected_minutes", "reference_minutes", "minutes_method", "reference_minutes_method", "scenario_assumptions")}
        values["conditional_on"] = player.get("conditional_on")
        records["minutes"][pid] = m.binding("minutes", event, values)
    envelope = {"schema": "nba-personnel-normalized-evidence.v1", "provider": "TEST_ONLY",
                "source_uri": "TEST_ONLY:synthetic", "retrieved_at_utc": "2020-01-01T00:00:00Z",
                "provider_updated_at_utc": None, "records": records}
    path = tmp_path / (event["event_id"].replace(":", "-") + "-source.json")
    path.write_text(json.dumps(envelope))
    def reference(pointer):
        return {**{k: envelope[k] for k in ("provider", "source_uri", "retrieved_at_utc", "provider_updated_at_utc")},
                "path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "data_pointer": pointer}
    parent["source"] = reference("/records/baseline")
    parent["state_source"] = reference("/records/parent_state")
    parent["training_source"] = reference("/records/training")
    packet["roster_source"] = reference("/records/roster")
    for player in packet["players"]:
        player["status_source"] = reference("/records/status/" + player["player_id"])
        player["minutes_source"] = reference("/records/minutes/" + player["player_id"])
    result = row["result"]
    envelope["records"] = {"result": m.binding("result", event, {k: result[k] for k in ("home_margin", "available_at_utc")})}
    envelope["retrieved_at_utc"] = result["available_at_utc"]
    path = tmp_path / (event["event_id"].replace(":", "-") + "-result.json")
    path.write_text(json.dumps(envelope))
    result["source"] = reference("/records/result")


def data(tmp_path, n=26):
    ref = {}
    rows = []
    for i in range(n):
        start = dt.datetime(2020, 1, 3, 20, tzinfo=dt.timezone.utc) + dt.timedelta(days=i)
        shift = (-8, -4, 4, 8)[i % 4]
        players = []
        roster = {team: [f"{team}-{j}" for j in range(6)] for team in ("H", "A")}
        for team in ("H", "A"):
            for j in range(6):
                minutes = 40 + (shift if j == 0 else -shift if j == 1 else 0) if team == "H" else 40
                players.append({"team_id": team, "player_id": f"{team}-{j}", "status": "AVAILABLE",
                                "expected_minutes": minutes, "reference_minutes": 40,
                                "minutes_method": "TEST_ONLY_frozen_projected_rotation",
                                "reference_minutes_method": "TEST_ONLY_baseline_reference_rotation",
                                "scenario_assumptions": [], "status_source": copy.deepcopy(ref), "minutes_source": copy.deepcopy(ref)})
        rows.append({"event": {"event_id": f"NBA:synthetic-{i}", "home_id": "H", "away_id": "A", "home_team": "Home", "away_team": "Away",
                               "start_time_utc": start.isoformat(), "cutoff_utc": (start-dt.timedelta(hours=1)).isoformat()},
                     "baseline": {"model_id": "TEST_ONLY.parent.v1", "home_margin": 3., "state_sha256": "a"*64,
                                  "training_event_ids": ["TEST_ONLY-prior"], "training_max_available_at_utc": "2019-12-01T00:00:00Z",
                                  "personnel_adjustment_included": False, "reference_rotation_policy": "BASELINE_PARTICIPATION_REFERENCE",
                                  "source": copy.deepcopy(ref)},
                     "personnel": {"players": players, "roster_by_team": roster, "roster_source": copy.deepcopy(ref)},
                     "result": {"home_margin": 3+shift, "available_at_utc": (start+dt.timedelta(hours=4)).isoformat(), "source": copy.deepcopy(ref)}})
    for row in rows:
        seal_sources(row, tmp_path)
    return rows


def fit(rows, tmp_path):
    return m.fit(rows[:22], base=tmp_path, fit_cutoff_utc="2020-01-25T12:00:00Z")


def test_actual_fit_and_component_consumption_without_invented_heads(tmp_path):
    rows = data(tmp_path)
    state = fit(rows, tmp_path)
    p = m.predict(state, rows[24], base=tmp_path)
    assert p["home_margin"] < p["parent_home_margin"]
    assert p["personnel_margin_delta"] == pytest.approx(sum(p["components"].values()))
    assert p["home_margin"] == pytest.approx(p["parent_home_margin"] + p["personnel_margin_delta"])
    assert p["p_home"] is p["cover_probability"] is p["total"] is None
    assert p["input_status"] == "USED" and p["action_authority"] is False
    assert state["model_id"] != state["parent_model_id"]
    neutral = copy.deepcopy(rows[24])
    for player in neutral["personnel"]["players"]:
        player["expected_minutes"] = player["reference_minutes"]
    seal_sources(neutral, tmp_path)
    assert m.predict(state, neutral, base=tmp_path)["personnel_margin_delta"] == 0


@pytest.mark.parametrize("mutation,reason", [
    (lambda r: r["personnel"]["players"][0].update(status="UNKNOWN"), "UNKNOWN_AVAILABILITY"),
    (lambda r: r["personnel"]["players"][0].update(status="QUESTIONABLE"), "UNRESOLVED_SCENARIO"),
    (lambda r: r["personnel"]["players"][0].update(status="OUT"), "OUT_WITH_POSITIVE_MINUTES"),
    (lambda r: r["personnel"]["players"][0].update(expected_minutes=True), "INVALID_NUMBER"),
    (lambda r: r["personnel"]["players"][0].update(reference_minutes=float("nan")), "INVALID_NUMBER"),
    (lambda r: r["personnel"]["players"][0].update(expected_minutes=49), "MINUTES_OUT_OF_RANGE"),
    (lambda r: r["personnel"]["players"][0].update(expected_minutes=0), "SOURCE_VALUE_BINDING_MISMATCH"),
    (lambda r: r["personnel"]["players"].pop(), "ROTATION_COVERAGE_INCOMPLETE"),
    (lambda r: r["personnel"]["players"].append(copy.deepcopy(r["personnel"]["players"][0])), "PLAYER_IDENTITY_CONFLICT"),
    (lambda r: r["baseline"].update(personnel_adjustment_included=True), "DOUBLE_COUNT"),
    (lambda r: r["baseline"].pop("personnel_adjustment_included"), "DOUBLE_COUNT"),
    (lambda r: r["baseline"].update(reference_rotation_policy="UNKNOWN"), "REFERENCE_ROTATION_BINDING"),
    (lambda r: r["baseline"].update(training_event_ids=[r["event"]["event_id"]]), "NOT_OUT_OF_SAMPLE"),
    (lambda r: r["baseline"].update(training_max_available_at_utc=r["event"]["start_time_utc"]), "TRAINING_AFTER_CUTOFF"),
    (lambda r: r["personnel"]["players"][0]["status_source"].update(retrieved_at_utc="2030-01-01T00:00:00Z"), "SOURCE_METADATA_MISMATCH"),
    (lambda r: r["personnel"]["players"][0]["minutes_source"].update(provider_updated_at_utc="2030-01-01T00:00:00Z"), "SOURCE_METADATA_MISMATCH"),
])
def test_bad_inputs_refused_before_transform(tmp_path, mutation, reason):
    r = data(tmp_path)[0]
    mutation(r)
    with pytest.raises(ValueError, match=reason):
        m.features(r, tmp_path)


def test_source_bytes_tamper_refused(tmp_path):
    r = data(tmp_path)[0]
    (tmp_path / r["baseline"]["source"]["path"]).write_text("tampered")
    with pytest.raises(ValueError, match="SOURCE_BYTES_MISMATCH"):
        m.features(r, tmp_path)


def test_fit_rejects_late_outcomes_duplicate_and_conditional_training(tmp_path):
    rows = data(tmp_path)
    with pytest.raises(ValueError, match="TRAINING_RESULT_CHRONOLOGY"):
        m.fit(rows, base=tmp_path, fit_cutoff_utc="2020-01-10T00:00:00Z")
    duplicate = copy.deepcopy(rows[:22]); duplicate[-1] = duplicate[0]
    with pytest.raises(ValueError, match="DUPLICATE_TRAINING_EVENT"):
        fit(duplicate, tmp_path)
    conditional = copy.deepcopy(rows)
    conditional[0]["personnel"]["players"][0].update(status="QUESTIONABLE", conditional_on="ACTIVE", scenario_assumptions=["TEST_ONLY active scenario"])
    seal_sources(conditional[0], tmp_path)
    with pytest.raises(ValueError, match="CONDITIONAL_TRAINING_NOT_SUPPORTED"):
        fit(conditional, tmp_path)


def test_target_does_not_change_forecast_and_fit_cannot_consume_target(tmp_path):
    rows = data(tmp_path)
    state = fit(rows, tmp_path)
    before = m.predict(state, rows[24], base=tmp_path)
    rows[24]["result"]["home_margin"] = 900
    after = m.predict(state, rows[24], base=tmp_path)
    assert before == after
    with pytest.raises(ValueError, match="EVALUATION_NOT_AFTER_TRAINING"):
        m.predict(state, rows[10], base=tmp_path)
    state["coefficient"][0] += 1
    with pytest.raises(ValueError, match="STATE_HASH_MISMATCH"):
        m.predict(state, rows[24], base=tmp_path)


def test_unknown_player_not_silently_zero_and_conditionals_not_mixed(tmp_path):
    rows = data(tmp_path); state = fit(rows, tmp_path)
    row = copy.deepcopy(rows[24]); row["personnel"]["players"][0]["player_id"] = "new"
    row["personnel"]["roster_by_team"]["H"][0] = "new"
    seal_sources(row, tmp_path)
    with pytest.raises(ValueError, match="UNSEEN_PLAYER_EFFECT_REQUIRED"):
        m.predict(state, row, base=tmp_path)
    row = copy.deepcopy(rows[24]); row["personnel"]["players"][0].update(status="QUESTIONABLE", conditional_on="ACTIVE", scenario_assumptions=["TEST_ONLY"])
    seal_sources(row, tmp_path)
    assert m.predict(state, row, base=tmp_path)["forecast_semantics"] == "CONDITIONAL_MARGIN_POINT_ESTIMATE"


def test_real_runner_immutable_and_blocked_missing_training(tmp_path):
    rows = data(tmp_path)
    p = tmp_path / "input.json"
    manifest = {"schema": "nba-personnel-experiment.v1", "evidence_scope": "TEST_ONLY", "fit_cutoff_utc": "2020-01-25T12:00:00Z", "training": rows[:22], "evaluation": rows[24:]}
    p.write_text(json.dumps(manifest))
    report = experiment(p, tmp_path / "run")
    assert report["n_paired"] == 2 and report["status"] == "COMPLETED"
    assert report["challenger_mae"] < report["baseline_mae"]
    assert report["evidence_scope"] == "TEST_ONLY"
    with pytest.raises(FileExistsError):
        experiment(p, tmp_path / "run")
    manifest["training"] = []; p.write_text(json.dumps(manifest))
    refusal = experiment(p, tmp_path / "blocked")
    assert refusal["status"] == "BLOCKED" and refusal["n_paired"] == 0


def test_shadow_binds_actual_parent_card_and_keeps_missing_events(tmp_path):
    rows = data(tmp_path); state = fit(rows, tmp_path)
    row = copy.deepcopy(rows[24]); event = row["event"]
    parent = {"event_id": event["event_id"], "home_team": "Home", "away_team": "Away", "model_id": row["baseline"]["model_id"], "start_time_utc": event["start_time_utc"], "diagnostics": {"home_margin": 3.}, "numerical_identity": {"fitted_state_sha256": row["baseline"]["state_sha256"]}}
    row["baseline"]["parent_forecast_sha256"] = m.digest(parent)
    card = {"league": "NBA", "as_of_utc": event["cutoff_utc"], "forecasts": [parent, {"event_id": "NBA:missing"}]}
    card_path = tmp_path / "card.json"; card_path.write_text(json.dumps(card)); original = card_path.read_bytes()
    state_path = tmp_path / "state.json"; state_path.write_text(json.dumps(state))
    inputs_path = tmp_path / "inputs.json"; inputs_path.write_text(json.dumps({"schema": "nba-personnel-inputs.v1", "rows": [row]}))
    refs = lambda p: {"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    config_path = tmp_path / "config.json"; config_path.write_text(json.dumps({"schema": "nba-personnel-shadow.v1", "state": refs(state_path), "inputs": refs(inputs_path)}))
    report = shadow_from_card(card_path, config_path, tmp_path / "shadow")
    assert report["completed_count"] == report["blocked_count"] == 1
    assert card_path.read_bytes() == original
    altered = copy.deepcopy(card)
    altered["forecasts"][0]["numerical_identity"]["fitted_state_sha256"] = "f" * 64
    row["baseline"]["parent_forecast_sha256"] = m.digest(altered["forecasts"][0])
    card_path.write_text(json.dumps(altered))
    inputs_path.write_text(json.dumps({"schema": "nba-personnel-inputs.v1", "rows": [row]}))
    config_path.write_text(json.dumps({"schema": "nba-personnel-shadow.v1", "state": refs(state_path), "inputs": refs(inputs_path)}))
    report = shadow_from_card(card_path, config_path, tmp_path / "state-mismatch")
    assert "PARENT_FITTED_STATE_MISMATCH" in report["coverage"][0]["reason"]
    row["baseline"]["parent_forecast_sha256"] = m.digest(parent)
    inputs_path.write_text(json.dumps({"schema": "nba-personnel-inputs.v1", "rows": [row]}))
    config_path.write_text(json.dumps({"schema": "nba-personnel-shadow.v1", "state": refs(state_path), "inputs": refs(inputs_path)}))
    card["forecasts"][0]["diagnostics"]["home_margin"] = 99
    card_path.write_text(json.dumps(card))
    report = shadow_from_card(card_path, config_path, tmp_path / "mismatch")
    assert "PARENT_FORECAST_BINDING_MISMATCH" in report["coverage"][0]["reason"]


def test_cli_runs_actual_experiment(tmp_path):
    rows = data(tmp_path)
    p = tmp_path / "input.json"; p.write_text(json.dumps({"schema": "nba-personnel-experiment.v1", "evidence_scope": "TEST_ONLY", "fit_cutoff_utc": "2020-01-25T12:00:00Z", "training": rows[:22], "evaluation": rows[24:]}))
    run = subprocess.run([sys.executable, "scripts/run_nba_personnel_experiment.py", "--input", str(p), "--output", str(tmp_path / "cli")], text=True, capture_output=True)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["n_paired"] == 2


def test_balanced_minutes_cannot_change_under_unchanged_sources(tmp_path):
    rows = data(tmp_path); state = fit(rows, tmp_path)
    row = rows[24]
    row["personnel"]["players"][0]["expected_minutes"] += 1
    row["personnel"]["players"][1]["expected_minutes"] -= 1
    with pytest.raises(ValueError, match="SOURCE_VALUE_BINDING_MISMATCH"):
        m.predict(state, row, base=tmp_path)


@pytest.mark.parametrize("field,value", [("home_margin", 999), ("state_sha256", "f"*64),
                                           ("training_event_ids", ["unbound-claim"])])
def test_parent_forecast_and_training_values_bound_to_evidence(tmp_path, field, value):
    row = data(tmp_path)[0]
    row["baseline"][field] = value
    with pytest.raises(ValueError, match="SOURCE_VALUE_BINDING_MISMATCH"):
        m.features(row, tmp_path)


def test_result_values_bound_before_fit_and_wrong_role_pointer_refused(tmp_path):
    rows = data(tmp_path)
    rows[0]["result"]["home_margin"] = 999
    with pytest.raises(ValueError, match="SOURCE_VALUE_BINDING_MISMATCH"):
        fit(rows, tmp_path)
    rows = data(tmp_path)
    rows[0]["personnel"]["players"][0]["minutes_source"]["data_pointer"] = "/records/status/H-0"
    with pytest.raises(ValueError, match="SOURCE_VALUE_BINDING_MISMATCH"):
        m.features(rows[0], tmp_path)


def test_parent_fitted_state_bytes_not_replaceable_by_other_role(tmp_path):
    row = data(tmp_path)[0]
    row["baseline"]["state_source"]["data_pointer"] = "/records/training"
    with pytest.raises(ValueError, match="SOURCE_VALUE_BINDING_MISMATCH"):
        m.features(row, tmp_path)


def test_unrelated_source_blob_and_changed_event_cannot_bind(tmp_path):
    row = data(tmp_path)[0]
    ref = row["baseline"]["source"]
    path = tmp_path / ref["path"]
    path.write_text(json.dumps({"fixture": "arbitrary unrelated bytes"}))
    ref["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="SOURCE_ENVELOPE_REQUIRED"):
        m.features(row, tmp_path)
    row = data(tmp_path)[0]
    row["event"]["event_id"] = "NBA:wrong-event"
    with pytest.raises(ValueError, match="SOURCE_VALUE_BINDING_MISMATCH"):
        m.features(row, tmp_path)


def test_metadata_cannot_backdate_late_source_and_bool_cannot_equal_number(tmp_path):
    row = data(tmp_path)[0]
    ref = row["baseline"]["source"]
    path = tmp_path / ref["path"]
    envelope = json.loads(path.read_text())
    envelope["retrieved_at_utc"] = "2030-01-01T00:00:00Z"
    path.write_text(json.dumps(envelope)); ref["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="SOURCE_METADATA_MISMATCH"):
        m.features(row, tmp_path)
    row = data(tmp_path)[0]
    ref = row["baseline"]["source"]; path = tmp_path/ref["path"]; envelope=json.loads(path.read_text())
    envelope["records"]["baseline"]["values"]["home_margin"] = True
    path.write_text(json.dumps(envelope)); ref["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="SOURCE_VALUE_BINDING_MISMATCH"):
        m.features(row, tmp_path)


@pytest.mark.parametrize("margin", [0, 0.5, True, float("inf")])
def test_invalid_observed_margin_never_treated_as_nba_final(margin):
    with pytest.raises(ValueError):
        m.observed_margin(margin)
