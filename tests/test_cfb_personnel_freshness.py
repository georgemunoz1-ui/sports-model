"""Adversarial engineering fixtures. All personnel and signing keys are synthetic."""
import base64
import copy
from datetime import timedelta
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from models.experiments import cfb_efficiency as c, cfb_personnel as p
from research.efficiency import cfb_personnel_freshness as f, integrity, runner
from research.validation_registry import canonical_bytes
from test_cfb_personnel_v2 import with_personnel


def save(path, value):
    path.write_bytes(canonical_bytes(value))
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def revise(request, root, stamp, *, version="r1", previous=None, probability=.3):
    request = copy.deepcopy(request)
    evidence = request["personnel_evidence"]
    for side in ("home", "away"):
        record = evidence[side]
        source = record["sources"][0]
        old = copy.deepcopy(source)
        raw = json.loads(Path(source["path"]).read_bytes())
        raw.update(published_at=stamp, version=version)
        raw["quarterback"]["player_id"] = "SYNTHETIC-BACKUP-" + side + version
        record["quarterback"].update(player_id=raw["quarterback"]["player_id"], expected_participation_probability=probability)
        source.update(save(root / (side + version + ".json"), raw), version_id=version,
            version_pointer="/version", observed_time_pointer="/published_at",
            observed_at_utc=stamp, retrieved_at_utc=stamp, available_at_utc=stamp)
        if previous:
            source["supersedes_sha256"] = old["sha256"]
        assumption = json.loads(Path(record["participation_assumption"]["path"]).read_bytes())
        assumption.update(created_at_utc=stamp, evidence_source_sha256=[source["sha256"]])
        assumption["assumptions"].update(player_id=raw["quarterback"]["player_id"], expected_participation_probability=probability)
        record["participation_assumption"] = save(root / (side + version + "-assumption.json"), assumption)
    return request


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    history = with_personnel(tmp_path)
    training = runner.prepare("cfb", history)
    state = c.fit_personnel_v2([r for r in training if r["season"] <= 2024], {"minimum_training_rows": 10})
    # A Thursday event on different teams fixes the unchanged weekly cutoff;
    # the target is Saturday. No target results or metrics enter the state.
    target = c.canonical_game(history["games"][-1])
    thursday = copy.deepcopy(target)
    thursday.update(game_id="9999", event_id="CFB:9999", home_id="3", away_id="4", home_team="C", away_team="D", completed=False)
    thursday.pop("personnel_evidence")
    target.update(start_time_utc=(c.utc(target["start_time_utc"]) + timedelta(days=2)).isoformat(), completed=False)
    target.pop("personnel_evidence")
    history["games"][-1] = target
    history["games"].append(thursday)
    history["team_games"] = history["team_games"][:-2]
    rows = runner.prepare("cfb", history)
    example = next(r for r in rows if r["event_id"] == target["event_id"])
    weekly = f.time(example["cutoff_utc"])
    request = {"event": target, "requested_as_of_utc": (weekly + timedelta(days=1, hours=2)).isoformat(),
               "personnel_evidence": training[-1]["personnel_evidence"], "previous_receipt_sha256": None}
    request = revise(request, tmp_path, (weekly + timedelta(days=1)).isoformat())
    policy = {"policy_id": f.POLICY_ID, "lead_seconds": 300}
    key = Ed25519PrivateKey.generate()
    roots = {"schema": "cfb.personnel-clock-authorities.v1", "authorities": {"synthetic-test-clock": {
        "public_key_base64": base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode(),
        "valid_from_utc": "2000-01-01T00:00:00Z", "valid_until_utc": "2100-01-01T00:00:00Z"}}}
    roots_path = tmp_path / "synthetic-clock-roots.json"
    save(roots_path, roots)
    monkeypatch.setattr(f, "TRUST_ROOTS", roots_path)
    def sign(req):
        req = copy.deepcopy(req)
        payload = {"schema": "cfb.personnel-clock-attestation.v1", "authority_id": "synthetic-test-clock",
                   "event": f.identity(req["event"]), "evidence_sha256": f.digest(req["personnel_evidence"]),
                   "recorded_at_utc": (max(f.time(s["retrieved_at_utc"]) for side in ("home", "away")
                       for s in req["personnel_evidence"][side]["sources"]) + timedelta(seconds=1)).isoformat()}
        req["chronology_anchor"] = {"payload": payload,
            "signature_base64": base64.b64encode(key.sign(canonical_bytes(payload))).decode()}
        return req
    return {"history": history, "state": state, "example": example, "request": sign(request),
            "policy": policy, "sign": sign, "root": tmp_path, "weekly": weekly}


def prepare(data, request=None, mode="HISTORICAL_REPLAY"):
    return f.prepare_snapshot(data["example"], request or data["request"], data["policy"], mode, data["history"])


def run(data, request=None, *, mode="HISTORICAL_REPLAY", suffix="1"):
    root = data["root"]
    history = save(root / ("history" + suffix + ".json"), data["history"])
    state = save(root / ("state" + suffix + ".json"), data["state"])
    event = data["example"]["event"]
    card = root / "card.json"
    save(card, {"league": "CFB", "as_of_utc": data["example"]["cutoff_utc"], "forecasts": [{
        "event_id": event["event_id"], "start_time_utc": event["start_time_utc"],
        "home_team": event["home_team"], "away_team": event["away_team"], "p_home": .5}]})
    config = root / ("config" + suffix + ".json")
    save(config, {"schema": "cfb.personnel-refresh-run.v1", "mode": mode, "history": history,
                  "parent_state": state, "policy": data["policy"], "requests": [request or data["request"]],
                  "refresh_store": "refresh-store"})
    before = {p: p.read_bytes() for p in (card, config, Path(history["path"]), Path(state["path"]))}
    report = runner.personnel_refresh_from_card(card, config, root / ("run" + suffix))
    assert all(p.read_bytes() == raw for p, raw in before.items())
    return report


def test_late_qb_update_uses_real_predict_but_weekly_parent_refuses(fixture):
    d = fixture
    original = copy.deepcopy(d["example"])
    row, snapshot = prepare(d)
    with pytest.raises(ValueError, match="AFTER_CUTOFF"):
        c.predict(d["state"], row)
    forecast = c.predict(d["state"], row, personnel_refresh=snapshot)
    assert forecast["model_id"] == f.MODEL_ID
    assert forecast["personnel_consumption"]["feature_values"]["home_qb_availability"] == .3
    assert row["features"] == original["features"]
    assert row["cutoff_utc"] == original["cutoff_utc"]
    assert d["example"] == original
    assert forecast["parent_model_state_sha256"] == d["state"]["state_sha256"]
    assert forecast["action_authority"] is False


@pytest.mark.parametrize("field", ["observed_at_utc", "retrieved_at_utc", "available_at_utc"])
@pytest.mark.parametrize("bad", [None, "2026-10-08T12:00:00", "bad", "NaT"])
def test_missing_naive_invalid_source_timestamps(fixture, field, bad):
    fixture["request"]["personnel_evidence"]["home"]["sources"][0][field] = bad
    with pytest.raises(ValueError):
        prepare(fixture)


@pytest.mark.parametrize("offset", [0, 1, 3600])
def test_observation_retrieval_and_availability_at_or_after_cutoff_refused(fixture, offset):
    for field in ("observed_at_utc", "retrieved_at_utc", "available_at_utc"):
        request = copy.deepcopy(fixture["request"])
        request["personnel_evidence"]["home"]["sources"][0][field] = (
            f.time(request["requested_as_of_utc"]) + timedelta(seconds=offset)).isoformat()
        with pytest.raises(ValueError):
            prepare(fixture, request)


def test_buffer_boundary_and_no_backdating_poststart(fixture):
    request = copy.deepcopy(fixture["request"])
    start = f.time(request["event"]["start_time_utc"])
    request["requested_as_of_utc"] = (start - timedelta(seconds=10)).isoformat()
    assert f.cutoff_for(fixture["example"], request, fixture["policy"]) == start - timedelta(seconds=300)
    request["requested_as_of_utc"] = start.isoformat()
    with pytest.raises(ValueError, match="POST_START_REQUEST"):
        prepare(fixture, request)


def test_poststart_writer_and_future_asof(fixture, monkeypatch):
    start = f.time(fixture["example"]["start_time_utc"])
    monkeypatch.setattr(f, "now", lambda: start)
    with pytest.raises(ValueError, match="POST_START_WRITER"):
        prepare(fixture, mode="SHADOW")
    monkeypatch.setattr(f, "now", lambda: fixture["weekly"])
    with pytest.raises(ValueError, match="FUTURE_ASOF"):
        prepare(fixture, mode="SHADOW")


def test_historical_claim_requires_independent_signature(fixture):
    request = copy.deepcopy(fixture["request"])
    request.pop("chronology_anchor")
    with pytest.raises(ValueError, match="HISTORICAL_INDEPENDENT_AVAILABILITY_REQUIRED"):
        prepare(fixture, request)
    request = copy.deepcopy(fixture["request"])
    request["chronology_anchor"]["payload"]["recorded_at_utc"] = "2020-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="INVALID_CLOCK_SIGNATURE"):
        prepare(fixture, request)


def test_untrusted_key_and_signed_after_cutoff_refused(fixture):
    roots = json.loads(f.TRUST_ROOTS.read_bytes())
    f.TRUST_ROOTS.write_text(json.dumps({"authorities": {}}))
    with pytest.raises(ValueError, match="UNTRUSTED_CLOCK_AUTHORITY"):
        prepare(fixture)
    f.TRUST_ROOTS.write_text(json.dumps(roots))
    request = copy.deepcopy(fixture["request"])
    request["requested_as_of_utc"] = request["chronology_anchor"]["payload"]["recorded_at_utc"]
    with pytest.raises(ValueError, match="CLOCK_AFTER_CUTOFF"):
        prepare(fixture, request)


def test_declared_version_and_provider_time_are_bound(fixture):
    for field, value in (("version_id", "not-the-source-version"), ("observed_time_pointer", "/absent")):
        request = copy.deepcopy(fixture["request"])
        request["personnel_evidence"]["home"]["sources"][0][field] = value
        with pytest.raises(ValueError):
            prepare(fixture, request)


def test_conflicting_source_revisions_in_one_snapshot(fixture):
    request = copy.deepcopy(fixture["request"])
    request["personnel_evidence"]["home"]["sources"] *= 2
    with pytest.raises(ValueError, match="CONFLICTING_SOURCE_REVISIONS"):
        prepare(fixture, request)


def test_duplicate_alias_and_schedule_identity_refused(fixture):
    event = fixture["example"]["event"]
    with pytest.raises(ValueError, match="DUPLICATE_EVENT_IDENTITY"):
        f.index_events([event, copy.deepcopy(event)])
    with pytest.raises(ValueError, match="ALIAS_CONFLICT"):
        f.index_events([{**event, "event_id": "CFB:123"}])
    for field, value in (("home_id", "333"), ("start_time_utc", "2026-10-10T12:00:00Z"), ("week", 7)):
        request = copy.deepcopy(fixture["request"])
        request["event"][field] = value
        with pytest.raises(ValueError, match="EVENT_IDENTITY_CONFLICT"):
            prepare(fixture, request)


def test_real_runner_retains_refreshes_and_never_rewrites_first(fixture):
    first = run(fixture)
    assert first["retained_count"] == 1, first["coverage"]
    files = {p: p.read_bytes() for p in (fixture["root"] / "refresh-store").rglob("*.json")}
    request = revise(fixture["request"], fixture["root"],
                     (fixture["weekly"] + timedelta(days=1, hours=3)).isoformat(), version="r2", previous=True, probability=.1)
    request["requested_as_of_utc"] = (fixture["weekly"] + timedelta(days=1, hours=4)).isoformat()
    request["previous_receipt_sha256"] = first["coverage"][0]["receipt_sha256"]
    request = fixture["sign"](request)
    second = run(fixture, request, suffix="2")
    assert second["retained_count"] == 1, second["coverage"]
    assert second["coverage"][0]["sequence"] == 1
    assert all(p.read_bytes() == raw for p, raw in files.items())
    assert len(list((fixture["root"] / "refresh-store" / "blobs").iterdir())) == 8
    duplicate = run(fixture, request, suffix="3")
    assert duplicate["retained_count"] == 0
    assert "PREDECESSOR_CONFLICT" in duplicate["coverage"][0]["reason"]


def test_unlinked_source_revision_does_not_append(fixture):
    first = run(fixture)
    assert first["retained_count"] == 1, first["coverage"]
    request = revise(fixture["request"], fixture["root"],
        (fixture["weekly"] + timedelta(days=1, hours=3)).isoformat(), version="r2")
    request.update(requested_as_of_utc=(fixture["weekly"] + timedelta(days=1, hours=4)).isoformat(),
                   previous_receipt_sha256=first["coverage"][0]["receipt_sha256"])
    report = run(fixture, fixture["sign"](request), suffix="2")
    assert report["retained_count"] == 0
    assert "CONFLICTING_SOURCE_REVISIONS" in report["coverage"][0]["reason"]


def test_no_new_training_labels_or_numerical_control_change(fixture):
    d = fixture
    row, snapshot = prepare(d)
    training = runner.prepare("cfb", d["history"])
    state = c.fit([r for r in training if r["season"] <= 2024], {"minimum_training_rows": 10})
    assert c.predict(state, row) == c.predict(state, d["example"])
    parent = copy.deepcopy(d["state"])
    parent["training_max_label_available_at_utc"] = d["example"]["cutoff_utc"]
    parent["state_sha256"] = c.digest({k: v for k, v in parent.items() if k != "state_sha256"})
    with pytest.raises(ValueError, match="TRAINING_LABEL_AFTER_FORECAST_CUTOFF"):
        c.predict(parent, row, personnel_refresh=snapshot)
    with pytest.raises(ValueError, match="REQUIRES_PERSONNEL_V2_PARENT"):
        c.predict(state, row, personnel_refresh=snapshot)


def test_live_unverified_is_diagnostic_and_registered_only_prestart(fixture, monkeypatch):
    d = fixture
    request = copy.deepcopy(d["request"])
    request.pop("chronology_anchor")
    clock = f.time(request["requested_as_of_utc"]) + timedelta(seconds=30)
    monkeypatch.setattr(f, "now", lambda: clock)
    monkeypatch.setattr(integrity, "_now", lambda: clock)
    # Synthetic history-source retrievals must also precede this synthetic run.
    for source in d["state"]["source_bindings"]:
        if source["source"] == "synthetic://cfb-fixture":
            source["retrieved_at_utc"] = "2018-01-01T00:00:00Z"
    d["state"]["state_sha256"] = c.digest({k: v for k, v in d["state"].items() if k != "state_sha256"})
    for metric in d["history"]["team_games"]:
        metric["source"]["retrieved_at_utc"] = "2018-01-01T00:00:00Z"
    report = run(d, request, mode="SHADOW")
    assert report["retained_count"] == 1, report["coverage"]
    forecast = report["coverage"][0]["forecast"]
    assert forecast["personnel_freshness"]["chronology"]["status"] == "UNVERIFIED"
    assert forecast["personnel_freshness"]["current_source_qualified"] is False
    assert report["canonical_prospective_eligible"] is False
    original_receipts = list((d["root"] / "refresh-store").rglob("*.json"))
    request = revise(request, d["root"], (clock + timedelta(seconds=1)).isoformat(), version="r2", previous=True)
    request.update(requested_as_of_utc=(clock + timedelta(seconds=2)).isoformat(),
                   previous_receipt_sha256=report["coverage"][0]["receipt_sha256"])
    clock += timedelta(seconds=3)
    exclusive = f._exclusive
    def cross_kickoff(path, raw):
        exclusive(path, raw)
        if path.parent.name == "blobs":
            monkeypatch.setattr(f, "now", lambda: f.time(d["example"]["start_time_utc"]))
    monkeypatch.setattr(f, "_exclusive", cross_kickoff)
    late = run(d, request, mode="SHADOW", suffix="late")
    assert late["retained_count"] == 0
    assert "WRITER_COMPLETION_CHRONOLOGY" in late["coverage"][0]["reason"]
    assert list((d["root"] / "refresh-store").rglob("*.json")) == original_receipts


def test_receipt_and_retained_blob_tampering_block_append(fixture):
    first = run(fixture)
    assert first["retained_count"] == 1, first["coverage"]
    blob = next((fixture["root"] / "refresh-store" / "blobs").iterdir())
    blob.write_bytes(b"tampered")
    request = copy.deepcopy(fixture["request"])
    request["previous_receipt_sha256"] = first["coverage"][0]["receipt_sha256"]
    report = run(fixture, request, suffix="2")
    assert "RETAINED_BYTES_MISMATCH" in report["coverage"][0]["reason"]
    receipt_path = next((fixture["root"] / "refresh-store").rglob("*.json"))
    receipt = json.loads(receipt_path.read_bytes())
    receipt["sequence"] = 99
    receipt_path.write_text(json.dumps(receipt))
    report = run(fixture, request, suffix="3")
    assert "RECEIPT_HASH_MISMATCH" in report["coverage"][0]["reason"]


def test_market_fields_do_not_change_personnel_numerics(fixture):
    row, snapshot = prepare(fixture)
    first = c.predict(fixture["state"], row, personnel_refresh=snapshot)
    row["event"].update(moneyline=-99999, spread=-31.5, market_home_probability=.99)
    second = c.predict(fixture["state"], row, personnel_refresh=snapshot)
    assert first == second


def test_retained_personnel_reverified_after_original_paths_removed(fixture):
    report = run(fixture)
    assert report["retained_count"] == 1, report["coverage"]
    store = fixture["root"] / "refresh-store"
    receipt_path = next(store.rglob("*.json"))
    for side in ("home", "away"):
        record = fixture["request"]["personnel_evidence"][side]
        for ref in [*record["sources"], record["participation_assumption"]]:
            Path(ref["path"]).unlink()
    verified = f.verify_retained_receipt(receipt_path, store)
    assert verified["personnel_bytes_and_values"] == "PASS"
    assert verified["chronology"]["independent_timestamp_verified"] is True
    assert verified["parent_model_historical_pit"] == "NOT_ESTABLISHED"


def test_policy_is_explicit_and_validated(fixture):
    for bad in (None, {}, {"policy_id": f.POLICY_ID, "lead_seconds": True},
                {"policy_id": f.POLICY_ID, "lead_seconds": 0},
                {"policy_id": f.POLICY_ID, "lead_seconds": float("nan")}):
        with pytest.raises(ValueError, match="EXPLICIT_POLICY_REQUIRED"):
            f.validate_policy(bad)


def test_real_cli_blocks_unanchored_history_and_retains_disposition(fixture):
    import subprocess
    import sys
    run(fixture)
    root = fixture["root"]
    config = json.loads((root / "config1.json").read_bytes())
    config["requests"][0].pop("chronology_anchor")
    save(root / "cli-config.json", config)
    result = subprocess.run([sys.executable, "scripts/run_efficiency_experiments.py", "--league", "cfb",
        "--source-card", str(root / "card.json"), "--personnel-refresh-config", str(root / "cli-config.json"),
        "--output-dir", str(root / "cli-run")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads((root / "cli-run" / "report.json").read_bytes())
    assert report["retained_count"] == 0
    assert "HISTORICAL_INDEPENDENT_AVAILABILITY_REQUIRED" in report["coverage"][0]["reason"]
