"""Witness a bounded research cohort using a verified GitHub Actions artifact."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from models.current.linear import predict
from scripts.canonical_forecasts import card_rows, verified_artifact
from scripts.register_mlb_calibration import atomic_json, dt

BASE_HASH = "1fc44a87d4c1fe23abba272484d5e2c8ae77c9c95a2874020e8cf72aa0d3695a"
ADDENDUM_HASH = "891f8fcef8de0ca9a1a2e651a1a83aa3f6301a0c79bd98e448f299224fd5ff2a"
CBB_ARMS = {"UNCHANGED_INCUMBENT", "LOCATION_ONLY", "SCALE_ONLY", "LOCATION_PLUS_SCALE"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_bytes())


def same(actual, expected, name):
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        if math.isfinite(actual) and math.isfinite(expected) and math.isclose(actual, expected, rel_tol=1e-11, abs_tol=1e-11):
            return
    elif actual == expected:
        return
    raise ValueError("BINDING_MISMATCH:" + name)


def verify_bundle(root, registered_at):
    root = Path(root).resolve()
    manifest = load(root / "bundle-manifest.json")
    for relative, expected in manifest["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha(path) != expected:
            raise ValueError("BUNDLE_MEMBER_MISMATCH:" + relative)
    same(sha(root / "protocol/evaluation-protocol.v1.json"), BASE_HASH, "protocol")
    same(sha(root / "protocol/evaluation-protocol.v1.addendum.json"), ADDENDUM_HASH, "addendum")
    protocol = load(root / "protocol/evaluation-protocol.v1.json")
    freezes = [dt(protocol["frozen_at_utc"])]
    events, forecasts, refusals = {}, [], []

    native = load(root / "cfb/diagnostic_card.json")
    card_rows(native, registered_at)
    freezes.append(dt(native["generated_at_utc"]))
    for row in native["forecasts"]:
        events[row["event_id"]] = row["start_time_utc"]
        forecasts.append({"event_id": row["event_id"], "procedure": row["forecast_procedure_id"], "source": "cfb/diagnostic_card.json", "source_row_hash": hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()})

    source = load(root / "cbb/source-card.json")
    source_rows = {r["event_id"]: r for r in source["forecasts"]}
    cbb = load(root / "cbb/forward-candidates.json")
    same(cbb["source_card_sha256"], sha(root / "cbb/source-card.json"), "CBB_parent")
    same(cbb["parameter_sha256"], sha(root / "cbb/parameters.json"), "CBB_parameters")
    same(cbb["protocol_sha256"], BASE_HASH, "CBB_protocol")
    same(cbb["protocol_addendum_sha256"], ADDENDUM_HASH, "CBB_addendum")
    if not dt(cbb["input_cutoff_utc"]) <= dt(cbb["created_at_utc"]) <= dt(registered_at):
        raise ValueError("CBB_CHRONOLOGY")
    freezes.append(dt(cbb["created_at_utc"]))
    same({r["event_id"] for r in cbb["rows"]}, set(source_rows), "CBB_complete_population")
    for row in cbb["rows"]:
        parent = source_rows[row["event_id"]]
        for key in ("event_id", "home_team", "away_team", "start_time_utc"):
            same(row[key], parent[key], "CBB_" + key)
        if row["actual_home_margin"] is not None:
            raise ValueError("PREGAME_OUTCOME_PRESENT")
        events[row["event_id"]] = row["start_time_utc"]
        if "arms" not in row:
            same(parent["forecast_status"], "UNAVAILABLE", "refusal_status")
            refusals.append({"event_id": row["event_id"], "reason": row["refusal_reason"]})
            continue
        same(set(row["arms"]), CBB_ARMS, "CBB_arm_population")
        same(row["input_snapshot_hash"], parent["input_snapshot_hash"], "CBB_features")
        same(row["settlement_scope"], parent["settlement"], "CBB_settlement")
        for name, arm in row["arms"].items():
            pmf = arm["margin_pmf"]
            support, counts = pmf["support"], pmf["counts"]
            if len(support) != len(counts) or support != sorted(set(support)) or 0 in support:
                raise ValueError("MARGIN_SUPPORT")
            if any(type(n) is not int or n <= 0 for n in counts):
                raise ValueError("MARGIN_COUNTS")
            same(sum(counts), pmf["denominator"], "margin_denominator")
            p = sum(n for m, n in zip(support, counts) if m > 0) / sum(counts)
            mean = sum(m * n for m, n in zip(support, counts)) / sum(counts)
            same(p, arm["winner_probability_home"], "CBB_winner_probability")
            same(mean, arm["law_mean_home_margin"], "CBB_distribution_mean")
            same(arm["qualification"], "HOLD", "CBB_qualification")
            if name == "UNCHANGED_INCUMBENT":
                same(p, parent["p_home_win"], "CBB_parent_probability")
                same(arm["point_home_margin"], parent["home_margin"], "CBB_point_head")
                same(support, parent["distributions"]["margin"]["support"], "CBB_parent_support")
                for n, mass in zip(counts, parent["distributions"]["margin"]["masses"]):
                    same(n / sum(counts), mass, "CBB_parent_mass")
            forecasts.append({"event_id": row["event_id"], "procedure": arm["model_id"], "source": "cbb/forward-candidates.json", "arm": name, "input_snapshot_hash": row["input_snapshot_hash"]})

    history = load(root / "history/forward-candidate-predictions.json")
    for row in history["rows"]:
        league, event = row["league"], row["event"]
        candidate = load(root / f"history/{league}-forward-candidate.json")
        package = load(root / f"history/{league}-incumbent-package.json")
        same(row["candidate_artifact_sha256"], sha(root / f"history/{league}-forward-candidate.json"), "history_candidate")
        same(candidate["protocol_sha256"], BASE_HASH, "history_protocol")
        same(candidate["PREDICTIVE_VALIDATION"], "HOLD", "history_qualification")
        if not dt(row["forecast_cutoff_utc"]) <= dt(candidate["created_at_utc"]) <= dt(registered_at):
            raise ValueError("HISTORY_CHRONOLOGY")
        freezes.append(dt(candidate["created_at_utc"]))
        same(event, next(e for e in candidate["events"] if e["event_id"] == event["event_id"]), "history_event")
        same(set(row["arms"]), {"A", "B", "C"}, "history_arms")
        for name, arm in row["arms"].items():
            features = row["incumbent" if name == "A" else "expanded"]["features"]
            fitted = candidate["fitted_model"] if name == "C" else package["fitted_model"]
            values = [features[k] for k in candidate["feature_names"]]
            for head, field in (("winner", "p_home"), ("margin", "home_margin"), ("total", "total")):
                same(predict(fitted[head], values), arm[field], "history_" + head)
            forecasts.append({"event_id": event["event_id"], "procedure": f"{league}.history_policy.{name}.v1", "source": "history/forward-candidate-predictions.json", "arm": name, "input_snapshot_hash": arm["feature_sha256"]})
        events[event["event_id"]] = event["start_time_utc"]

    if len(events) != 85 or len(forecasts) != 266 or len(refusals) != 13:
        raise ValueError("COHORT_POPULATION_MISMATCH")
    if min(dt(start) for start in events.values()) <= dt(registered_at):
        raise ValueError("REGISTRATION_AFTER_START")
    if min(freezes[1:]) < freezes[0] or max(freezes) > dt(registered_at):
        raise ValueError("FORECAST_PROTOCOL_CHRONOLOGY")
    if len({(r["event_id"], r["procedure"]) for r in forecasts}) != len(forecasts):
        raise ValueError("DUPLICATE_PROCEDURE_EVENT")
    return {"events": events, "forecasts": forecasts, "refusals": refusals}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--artifact-id", type=int)
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat()
    rows = verify_bundle(args.bundle, now)
    if args.verify_only:
        print(json.dumps({"status": "LOCAL_BINDING_CHECK_PASS", "events": len(rows["events"]), "forecast_procedures": len(rows["forecasts"]), "refusals": len(rows["refusals"])}))
        return
    if args.receipt.exists():
        raise ValueError("REGISTRATION_RECEIPT_ALREADY_EXISTS")
    artifact = verified_artifact(args.bundle / "cfb/diagnostic_card.json", args.run_id, args.artifact_id)
    if not dt(artifact["created_at"]) <= dt(now):
        raise ValueError("ARTIFACT_AFTER_WRITER_CLOCK")
    with tempfile.TemporaryDirectory() as work:
        subprocess.run(["gh", "run", "download", str(args.run_id), "--repo", os.environ["GITHUB_REPOSITORY"], "--name", artifact["name"], "--dir", work], check=True)
        matches = list(Path(work).rglob("bundle-manifest.json"))
        if len(matches) != 1 or sha(matches[0]) != sha(args.bundle / "bundle-manifest.json"):
            raise ValueError("REMOTE_MANIFEST_MISMATCH")
        verify_bundle(matches[0].parent, now)
    receipt = {"schema": "study.prospective_registration.v1", "study_id": "sports_validation_20261110.v1",
               "registered_at_utc": now, "protocol_sha256": BASE_HASH, "addendum_sha256": ADDENDUM_HASH,
               "artifact": artifact, "bundle_manifest_sha256": sha(args.bundle / "bundle-manifest.json"),
               "status": "REGISTERED_RESEARCH_SOURCE_UNVERIFIED", "production_canonical_registry": False,
               "source_authentication": "LIMITED_TO_RETAINED_BYTES_AND_REMOTE_ARTIFACT", "wagering_authority": "OFF",
               "official_selections": 0, "units": 0, "qualification": "HOLD", **rows}
    atomic_json(args.receipt, receipt)
    print(json.dumps({"status": receipt["status"], "events": len(rows["events"]), "forecast_procedures": len(rows["forecasts"]), "registered_at_utc": now}))


if __name__ == "__main__":
    main()
