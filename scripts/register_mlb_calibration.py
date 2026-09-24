#!/usr/bin/env python3
"""Writer-owned pregame registration of one immutable MLB calibration card per date."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.accumulate_mlb_calibration import finite_prob, forecast_output_hash, home_probability


def utcnow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def dt(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return parsed


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text() == content:
        return
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(handle.name, path)


@contextmanager
def registry_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def validate_card(card, card_date, registered_at):
    if card.get("league") != "MLB" or card.get("card_date") != card_date:
        raise ValueError("CARD_IDENTITY_MISMATCH")
    pit = card.get("pit_provenance") or {}
    if pit.get("pit_status") != "PIT_ALIGNED":
        raise ValueError("PIT_NOT_ALIGNED")
    for layer in (card, pit, card.get("grading_policy") or {}):
        if layer.get("action_authority") or layer.get("market_overlay_enabled") or layer.get("market_features_used"):
            raise ValueError("MARKET_ACTION_FIREWALL_FAIL")
    created = dt(card["generated_at_utc"])
    source = dt(pit["max_source_timestamp_utc"])
    registered = dt(registered_at)
    # Retain the card's declared PIT policy; registration never repairs its input vintage.
    if source > created or created > registered:
        raise ValueError("REGISTRATION_CHRONOLOGY_INVALID")
    rows = [r for r in card.get("forecasts", []) if r.get("forecast_status") == "FORECAST_GENERATED"]
    if not rows:
        raise ValueError("NO_GENERATED_FORECASTS")
    ids, hashes = set(), set()
    for row in rows:
        event_id = str(row["event_id"])
        output_hash = forecast_output_hash(row)
        if event_id in ids or output_hash in hashes:
            raise ValueError("DUPLICATE_FORECAST_IDENTITY")
        ids.add(event_id)
        hashes.add(output_hash)
        if registered >= dt(row["start_time_utc"]):
            raise ValueError(f"REGISTRATION_NOT_PREGAME:{event_id}")
        if row.get("action_authority") or row.get("market_features_used"):
            raise ValueError("MARKET_ACTION_FIREWALL_FAIL")
        grading = row.get("grading") or {}
        if grading.get("eligible_for_prospective_grading") is False and grading.get("eligibility_reason") != "REGISTRATION_ATTESTATION_REQUIRED":
            raise ValueError(f"FORECAST_INELIGIBLE:{event_id}:{grading.get('eligibility_reason')}")
        for explicit, legacy in (("analytic_p_home", "analytic_p"), ("stochastic_sim_p_home", "stochastic_sim_p")):
            if not finite_prob(home_probability(row, explicit, legacy)):
                raise ValueError(f"HOME_PROBABILITY_UNAVAILABLE:{event_id}")
    return ids


def validate_registration(card_path, entry, card_date):
    if digest(card_path) != entry.get("card_sha256"):
        raise ValueError("REGISTERED_CARD_HASH_MISMATCH")
    card = json.loads(Path(card_path).read_text())
    ids = validate_card(card, card_date, entry["registered_at_utc"])
    artifact = entry.get("artifact") or {}
    if not artifact.get("id") or not artifact.get("digest") or int(artifact.get("run_id", 0)) != int(entry["run_id"]):
        raise ValueError("ARTIFACT_BINDING_REQUIRED")
    observed = dt(artifact["created_at"])
    if observed > dt(entry["registered_at_utc"]):
        raise ValueError("ARTIFACT_NOT_AVAILABLE_AT_REGISTRATION")
    if observed < dt(card["generated_at_utc"]):
        raise ValueError("ARTIFACT_TIMESTAMP_PRECEDES_CARD")
    for row in card["forecasts"]:
        if str(row.get("event_id")) in ids and observed >= dt(row["start_time_utc"]):
            raise ValueError("ARTIFACT_NOT_PREGAME")
    if entry.get("registration_version") != "mlb.calibration_writer.v1":
        # Legacy recovery must preserve an independently observed pregame registry anchor.
        anchor = entry.get("legacy_registration_anchor") or {}
        if anchor.get("kind") != "github_workflow_run_created_at" or not anchor.get("commit_sha") or not anchor.get("run_id"):
            raise ValueError("LEGACY_REGISTRATION_ANCHOR_REQUIRED")
        for row in card["forecasts"]:
            if str(row.get("event_id")) in ids and dt(anchor["observed_at_utc"]) >= dt(row["start_time_utc"]):
                raise ValueError("LEGACY_REGISTRATION_ANCHOR_NOT_PREGAME")
    return card, ids


def register(card_path, registry_path, run_id, artifact):
    """Called after artifact upload; the caller cannot supply the writer clock."""
    card_path, registry_path = Path(card_path), Path(registry_path)
    card = json.loads(card_path.read_text())
    card_date = card["card_date"]
    with registry_lock(registry_path):
        registry = json.loads(registry_path.read_text()) if registry_path.exists() else {"schema_version": "mlb_calibration_registry_v1", "cards": {}}
        existing = registry["cards"].get(card_date)
        sha = digest(card_path)
        if existing:
            if str(existing["run_id"]) == str(run_id) and existing.get("card_sha256") == sha:
                validate_registration(card_path, existing, card_date)
                return "ALREADY_REGISTERED"
            raise ValueError(f"REGISTERED_CARD_IMMUTABLE:{card_date}")
        now = utcnow()
        frozen = registry_path.parent / "cards" / (sha + ".json")
        entry = {
            "run_id": int(run_id), "registered_at_utc": now,
            "registration_version": "mlb.calibration_writer.v1",
            "registration_basis": "Writer clock and immutable pregame Actions artifact; research calibration only",
            "card_path": str(frozen), "card_sha256": sha, "artifact": artifact,
            "status": "REGISTERED", "market_overlay_enabled": False, "action_authority": False,
        }
        validate_registration(card_path, entry, card_date)
        frozen.parent.mkdir(parents=True, exist_ok=True)
        if frozen.exists():
            if frozen.read_bytes() != card_path.read_bytes():
                raise ValueError("FROZEN_CARD_CONFLICT")
        else:
            with frozen.open("xb") as handle:
                handle.write(card_path.read_bytes())
                handle.flush()
                os.fsync(handle.fileno())
        registry["cards"][card_date] = entry
        registry["updated_at_utc"] = now
        atomic_json(registry_path, registry)
        return "REGISTERED"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--card", required=True)
    parser.add_argument("--registry", default="data/grading/mlb/registry.json")
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--artifact-id", required=True, type=int)
    args = parser.parse_args()
    repository = os.environ["GITHUB_REPOSITORY"]
    meta = json.loads(subprocess.check_output(["gh", "api", f"repos/{repository}/actions/artifacts/{args.artifact_id}"], text=True))
    if meta.get("expired") or meta["workflow_run"]["id"] != args.run_id:
        raise SystemExit("ARTIFACT_RUN_MISMATCH_OR_EXPIRED")
    # Bind the local card to the actual uploaded artifact, not caller-supplied metadata.
    with tempfile.TemporaryDirectory() as work:
        subprocess.run(["gh", "run", "download", str(args.run_id), "--repo", repository, "--name", meta["name"], "--dir", work], check=True)
        matches = list(Path(work).rglob("diagnostic_card.json"))
        if len(matches) != 1 or digest(matches[0]) != digest(args.card):
            raise SystemExit("UPLOADED_CARD_MISMATCH")
    artifact = {k: meta[k] for k in ("id", "name", "digest", "created_at")}
    artifact["run_id"] = args.run_id
    print(register(args.card, args.registry, args.run_id, artifact))


if __name__ == "__main__":
    main()
