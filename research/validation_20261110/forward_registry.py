"""Witness a bounded research cohort using a verified GitHub Actions artifact."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from models.current.linear import predict
from scripts.canonical_forecasts import card_rows, verified_artifact
from scripts.register_mlb_calibration import atomic_json, dt
from research.validation_20261110.cfb_source_check import verify_cfb
from research.validation_20261110.source_quote_parser import source_contracts

BASE_HASH = "1fc44a87d4c1fe23abba272484d5e2c8ae77c9c95a2874020e8cf72aa0d3695a"
ADDENDUM_HASH = "891f8fcef8de0ca9a1a2e651a1a83aa3f6301a0c79bd98e448f299224fd5ff2a"
CBB_ARMS = {"UNCHANGED_INCUMBENT", "LOCATION_ONLY", "SCALE_ONLY", "LOCATION_PLUS_SCALE"}
TRUSTED_INPUTS_HASH = "b8f9a8fee5046793a8fc88f13b9807beb7de33d67da909a49ad97b60fe987c62"
VERIFICATION_INPUTS = Path(__file__).parent / "verification-inputs"


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


def trusted_inputs(root):
    path = VERIFICATION_INPUTS / "trusted-source-versions.json"
    same(sha(path), TRUSTED_INPUTS_HASH, "trusted_source_version")
    trusted = load(path)
    for relative, expected in trusted["input_versions"].items():
        source = root / relative if "/" in relative else VERIFICATION_INPUTS / relative
        same(sha(source), expected, "source_version:" + relative)
    return trusted


def archived_readback(root, receipt_path, receipt_artifact_id):
    receipt = load(receipt_path)
    rows = verify_bundle(root, receipt["registered_at_utc"])
    for key, value in rows.items():
        same(receipt[key], value, "registered_" + key)
    same(receipt["bundle_manifest_sha256"], sha(Path(root) / "bundle-manifest.json"), "registered_manifest")
    repo = receipt["artifact"]["repository"]
    meta = json.loads(subprocess.check_output(["gh", "api", f"repos/{repo}/actions/artifacts/{receipt_artifact_id}"], text=True))
    same(meta["workflow_run"]["id"], receipt["artifact"]["run_id"], "receipt_witness_run")
    if meta.get("expired") or not dt(receipt["registered_at_utc"]) <= dt(meta["created_at"]) < min(dt(v) for v in receipt["events"].values()):
        raise ValueError("INDEPENDENT_PRESTART_RECEIPT_WITNESS_REQUIRED")
    with tempfile.TemporaryDirectory() as work:
        subprocess.run(["gh", "run", "download", str(meta["workflow_run"]["id"]), "--repo", repo, "--name", meta["name"], "--dir", work], check=True)
        matches = list(Path(work).rglob("cohort-receipt.json"))
        if len(matches) != 1 or sha(matches[0]) != sha(receipt_path):
            raise ValueError("REMOTE_REGISTRATION_RECEIPT_MISMATCH")
    return {"status": "ARCHIVED_READBACK_PASS", "registered_at_utc": receipt["registered_at_utc"],
            "verified_at_utc": datetime.now(timezone.utc).isoformat(), "receipt_witness_artifact_id": receipt_artifact_id,
            "forecast_procedures": len(rows["forecasts"]), "events": len(rows["events"]), "new_registration": False}


def verify_cbb_law(row, name, arm, parameters, bank):
    days = (date.fromisoformat(row["day"]) - date.fromisoformat(parameters["season_origins"]["2027"])).days
    same(row["days_since_season_origin"], days, "CBB_season_phase")
    same(dt(row["start_time_utc"]).astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat(), row["day"], "CBB_day")
    venue, margin, early = float(not row["neutral"]), row["point_home_margin"] / 10, int(days < 14)
    shift = float(np.dot([venue, margin, early * venue, early * margin], parameters["beta"])) if name in {"LOCATION_ONLY", "LOCATION_PLUS_SCALE"} else 0.0
    scale = parameters["phase_scales"]["early14" if early else "later"] if name in {"SCALE_ONLY", "LOCATION_PLUS_SCALE"} else 1.0
    margin_error, total_error = bank[:, 0] - bank[:, 1], bank[:, 0] + bank[:, 1]
    errors = bank if scale == 1 else np.column_stack(((total_error + scale * margin_error) / 2, (total_error - scale * margin_error) / 2))
    centers = np.array([row["projected_home_score"] + shift / 2, row["projected_away_score"] - shift / 2])
    scores = np.floor(errors + centers + 0.5).astype(np.int32)
    scores = scores[(scores[:, 0] >= 0) & (scores[:, 1] >= 0) & (scores[:, 0] != scores[:, 1])]
    support, counts = np.unique(scores[:, 0] - scores[:, 1], return_counts=True)
    expected = {"support": support.tolist(), "counts": counts.tolist(), "denominator": int(counts.sum())}
    same(arm["margin_pmf"], expected, "CBB_reconstructed_law")
    same(arm["point_home_margin"], float(centers[0] - centers[1]), "CBB_reconstructed_point")
    same(arm["point_total"], row["point_total"], "CBB_total_head")
    same(arm["location_adjustment"], shift, "CBB_location_transform")
    same(arm["residual_scale"], scale, "CBB_scale_transform")
    same(arm["model_id"], parameters["arm_model_ids"][name], "CBB_model_identity")
    same(arm["paired_legal_scores_sha256"], hashlib.sha256(scores.astype("<i4").tobytes()).hexdigest(), "CBB_legal_scores")


def verify_history_features(row, candidate, expanded_package):
    event = row["event"]
    original = load(VERIFICATION_INPUTS / f"{row['league']}-original-package.json")
    for label, package in (("incumbent", original), ("expanded", expanded_package)):
        record = row[label]
        values = []
        states = {}
        for side in ("home", "away"):
            state = package["team_state"][event[side + "_id"]]
            same(record["team_states"][side], state, "history_team_state")
            states[side] = state
            weight = state["n"] / (state["n"] + 10)
            values.extend([weight * state[field] + (1 - weight) * candidate["prior"] for field in ("for", "against")])
        for side in ("home", "away"):
            last = states[side]["last"]
            values.append(min(14, max(0, (dt(event["start_time_utc"]) - dt(last)).total_seconds() / 86400)) if last else 14.0)
        values.extend([float(states[side]["n"] < 10) for side in ("home", "away")])
        values.append(float(event["neutral_site"]))
        features = dict(zip(candidate["feature_names"], values))
        for key, value in features.items():
            same(record["features"][key], value, "history_feature:" + key)
        feature_hash = hashlib.sha256(json.dumps(features, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        same(record["feature_sha256"], feature_hash, "history_feature_digest")
        for arm in (("A",) if label == "incumbent" else ("B", "C")):
            same(row["arms"][arm]["feature_sha256"], feature_hash, "history_arm_feature_digest")


def verify_quotes(root, events, trusted):
    paths = {"CFB": "cfb/diagnostic_card.json", "CBB": "cbb/forward-candidates.json", "NBA": "history/nba-forward-view.json", "NHL": "history/nhl-forward-view.json"}
    observed, quote_ids = set(), set()
    for label in ("cfb-cbb", "nba-nhl"):
        ledger = load(root / f"quotes/{label}.json")
        bindings = {item["league"]: item for item in ledger["forecast_bindings"]}
        for league, binding in bindings.items():
            same(binding["sha256"], sha(root / paths[league]), "quote_forecast_version")
        for event in ledger["events"]:
            event_id = event["event_id"]
            if event_id in observed:
                raise ValueError("DUPLICATE_QUOTE_EVENT")
            observed.add(event_id)
            receipt = trusted["quote_source_receipts"][event_id]
            same(event["source_receipt"], receipt["source_receipt"], "quote_capture_receipt")
            path = root / f"quotes/excerpts/{event_id.replace(':', '_')}.json"
            same(sha(path), receipt["source_excerpt_sha256"], "quote_source_version")
            source = load(path)
            same(str(source["header"]["id"]), event_id.split(":")[-1], "quote_event")
            competition = source["header"]["competitions"][0]
            same(dt(competition["date"]), dt(events[event_id]), "quote_start")
            same(dt(event["authoritative_start_utc"]), dt(competition["date"]), "quote_declared_start")
            binding = bindings[event["league"]]
            same(event["forecast_sha256"], binding["sha256"], "quote_forecast_parent")
            if not dt(binding["sealed_at_utc"]) < dt(event["source_receipt"]["requested_at_utc"]) <= dt(event["source_receipt"]["retrieved_at_utc"]) < dt(competition["date"]):
                raise ValueError("QUOTE_CHRONOLOGY")
            for team in competition["competitors"]:
                same(str(team["team"]["id"]), event["team_ids"][team["homeAway"]], "quote_team")
            expected = {(q["market"], q["side"]): q for q in source_contracts(source)}
            actual = [q for q in ledger["quotes"] if q["event_id"] == event_id]
            same(len(actual), len(expected), "quote_complete_population")
            same(set(event["quote_ids"]), {q["quote_id"] for q in actual}, "quote_references")
            for quote in actual:
                if quote["quote_id"] in quote_ids:
                    raise ValueError("DUPLICATE_QUOTE_ID")
                quote_ids.add(quote["quote_id"])
                source_quote = expected[(quote["market"], quote["side"])]
                for key, value in source_quote.items():
                    same(quote[key], value, "quote_" + key)
                for key, value in {"forecast_sha256": binding["sha256"], "provider_asof_utc": None, "captured_at_utc": receipt["source_receipt"]["retrieved_at_utc"], "source_response_sha256": receipt["source_receipt"]["raw_sha256"], "executable_verified": False, "sportsbook_rules_verified": False, "official_selection": False, "stake_units": 0}.items():
                    same(quote[key], value, "quote_evidence_" + key)
                body = {k: v for k, v in quote.items() if k != "quote_id"}
                same(quote["quote_id"], "quote-" + hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(), "quote_identity")
    same(observed, set(events), "quote_event_coverage")
    same(len(quote_ids), 422, "quote_side_coverage")


def verify_bundle(root, registered_at):
    root = Path(root).resolve()
    manifest = load(root / "bundle-manifest.json")
    actual_members = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and p != root / "bundle-manifest.json"}
    same(set(manifest["files"]), actual_members, "manifest_membership")
    for relative, expected in manifest["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha(path) != expected:
            raise ValueError("BUNDLE_MEMBER_MISMATCH:" + relative)
    same(sha(root / "protocol/evaluation-protocol.v1.json"), BASE_HASH, "protocol")
    same(sha(root / "protocol/evaluation-protocol.v1.addendum.json"), ADDENDUM_HASH, "addendum")
    protocol = load(root / "protocol/evaluation-protocol.v1.json")
    trusted = trusted_inputs(root)
    freezes = [dt(protocol["frozen_at_utc"])]
    events, forecasts, refusals = {}, [], []

    native = load(root / "cfb/diagnostic_card.json")
    card_rows(native, registered_at)
    verify_cfb(root, VERIFICATION_INPUTS)
    freezes.append(dt(native["generated_at_utc"]))
    for row in native["forecasts"]:
        events[row["event_id"]] = row["start_time_utc"]
        forecasts.append({"event_id": row["event_id"], "procedure": row["forecast_procedure_id"], "source": "cfb/diagnostic_card.json", "source_row_hash": hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()})

    source = load(root / "cbb/source-card.json")
    source_rows = {r["event_id"]: r for r in source["forecasts"]}
    cbb = load(root / "cbb/forward-candidates.json")
    parameters = load(root / "cbb/parameters.json")
    bank = np.load(VERIFICATION_INPUTS / "native-residual-bank.npy", allow_pickle=False)
    same(hashlib.sha256(bank.astype("<f8").tobytes()).hexdigest(), source["model"]["bank_sha256"], "CBB_residual_source")
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
            same(row["refusal_reason"], parent["reason"], "refusal_reason")
            refusals.append({"event_id": row["event_id"], "reason": row["refusal_reason"]})
            continue
        same(set(row["arms"]), CBB_ARMS, "CBB_arm_population")
        same(row["input_snapshot_hash"], parent["input_snapshot_hash"], "CBB_features")
        same(row["input_snapshot"], parent["model_input_snapshot"], "CBB_input_snapshot")
        for side, key in (("home", "h"), ("away", "a")):
            same(row[side + "_id"], parent["model_input_snapshot"][key], "CBB_team_id")
            same(row["projected_" + side + "_score"], parent["projected_" + side + "_score"], "CBB_score_head")
        same(row["neutral"], parent["model_input_snapshot"]["neutral"], "CBB_venue")
        same(row["point_home_margin"], parent["home_margin"], "CBB_baseline_point")
        same(row["point_total"], parent["total"], "CBB_baseline_total")
        same(row["settlement_scope"], parent["settlement"], "CBB_settlement")
        for name, arm in row["arms"].items():
            verify_cbb_law(row, name, arm, parameters, bank)
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
        verify_history_features(row, candidate, package)
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
    verify_quotes(root, events, trusted)
    return {"events": events, "forecasts": forecasts, "refusals": refusals}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--archived-readback", action="store_true")
    parser.add_argument("--receipt-artifact-id", type=int)
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--artifact-id", type=int)
    args = parser.parse_args()
    if args.archived_readback:
        if not args.receipt_artifact_id:
            raise ValueError("RECEIPT_ARTIFACT_ID_REQUIRED")
        print(json.dumps(archived_readback(args.bundle, args.receipt, args.receipt_artifact_id)))
        return
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
