#!/usr/bin/env python3
"""Grade frozen MLB forecast cards against final results and accumulate calibration evidence.

The forecast artifact is immutable. This script only appends result-bound child rows to
the calibration ledger. It never regenerates probabilities and never consumes market data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://statsapi.mlb.com/api/v1"
EPS = 1e-12
GRADER_VERSION = "mlb.calibration_grader.v2"
RESULT_SOURCE = "MLB_STATSAPI"


def utcnow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def finite_prob(value):
    if isinstance(value, bool):
        return False
    try:
        number = float(value)
    except Exception:
        return False
    return math.isfinite(number) and 0.0 <= number <= 1.0


def home_probability(row, explicit_key, legacy_key):
    grading = row.get("grading") or {}
    if finite_prob(grading.get(explicit_key)):
        return float(grading[explicit_key])
    if finite_prob(row.get(explicit_key)):
        return float(row[explicit_key])
    value = row.get(legacy_key)
    if not finite_prob(value):
        return None
    value = float(value)
    if row.get("model_winner") == row.get("home_team"):
        return value
    if row.get("model_winner") == row.get("away_team"):
        return 1.0 - value
    return None


def candidate_home_probability(row):
    grading = row.get("grading") or {}
    if finite_prob(grading.get("normal_margin_candidate_p_home")):
        return float(grading["normal_margin_candidate_p_home"])
    value = row.get("model_p_candidate_normal_margin")
    if not finite_prob(value):
        return None
    value = float(value)
    if row.get("model_winner") == row.get("home_team"):
        return value
    if row.get("model_winner") == row.get("away_team"):
        return 1.0 - value
    return None


def brier(probability, outcome):
    return (probability - outcome) ** 2


def log_loss(probability, outcome):
    p = min(1.0 - EPS, max(EPS, probability))
    return -(outcome * math.log(p) + (1 - outcome) * math.log(1 - p))


def calibration_bin(probability):
    low = min(0.9, math.floor(probability * 10.0) / 10.0)
    high = min(1.0, low + 0.1)
    return f"{low:.1f}-{high:.1f}"


def load_ledger(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def save_ledger(path, rows):
    """Append a validated suffix; never rewrite, reorder or truncate prior bytes."""
    existing = load_ledger(path)
    if rows[:len(existing)] != existing:
        raise ValueError("LEDGER_PREFIX_MUTATED")
    ids = [row["grade_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("DUPLICATE_GRADE_ID_IN_LEDGER")
    suffix = rows[len(existing):]
    if not suffix:
        return
    if path.exists() and path.stat().st_size and not path.read_bytes().endswith(b"\n"):
        raise ValueError("LEDGER_INCOMPLETE_LAST_LINE")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in suffix))
        handle.flush()
        os.fsync(handle.fileno())


def outcome_map(card_date, results_json=None, capture_path=None):
    url = f"{BASE}/schedule?sportId=1&date={card_date}"
    if results_json:
        raw = Path(results_json).read_bytes()
        source = "RESULTS_JSON"
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "sports-model-calibration/2.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
        source = RESULT_SOURCE
    observed_at = utcnow()
    digest = hashlib.sha256(raw).hexdigest()
    data = json.loads(raw)
    if not isinstance(data.get("dates"), list):
        raise ValueError("RESULT_SCHEDULE_INVALID")
    if capture_path:
        capture_path = Path(capture_path)
        capture_path.mkdir(parents=True, exist_ok=True)
        target = capture_path / (digest + ".json")
        if not target.exists():
            target.write_bytes(raw)
        elif target.read_bytes() != raw:
            raise ValueError("RESULT_SNAPSHOT_CONFLICT")
        receipt = {"sha256": digest, "source": source, "url": url if not results_json else None,
                   "source_file": str(results_json) if results_json else None,
                   "observed_at_utc": observed_at}
        receipt_path = capture_path / (digest + ".receipt.json")
        if not receipt_path.exists():
            receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    result = {}
    for date_row in data["dates"]:
        if date_row.get("date") != card_date:
            continue
        for game in date_row.get("games", []):
            event_id = str(game.get("gamePk"))
            status = game.get("status", {})
            abstract = status.get("abstractGameState")
            detailed = status.get("detailedState")
            is_final = abstract == "Final" and detailed in {"Final", "Game Over", "Completed Early"}
            home = game.get("teams", {}).get("home", {})
            away = game.get("teams", {}).get("away", {})
            hs, aws = home.get("score"), away.get("score")
            if not is_final:
                continue
            if any(type(score) is not int or score < 0 for score in (hs, aws)) or hs == aws:
                raise ValueError(f"INVALID_FINAL_SCORE:{event_id}")
            if event_id in result:
                raise ValueError(f"DUPLICATE_RESULT_EVENT:{event_id}")
            result[event_id] = {
                "status": detailed, "home_score": hs, "away_score": aws, "home_won": hs > aws,
                "home_team": home.get("team", {}).get("name"),
                "away_team": away.get("team", {}).get("name"),
                "result_source": source, "result_source_id": event_id,
                "result_snapshot_sha256": digest, "result_observed_at_utc": observed_at,
            }
    return result


def forecast_output_hash(row):
    output_hash = (row.get("provenance") or {}).get("output_hash")
    if output_hash:
        return output_hash
    payload = {
        "event_id": row.get("event_id"),
        "input_snapshot_hash": row.get("input_snapshot_hash"),
        "model_state_config_hash": row.get("model_state_config_hash"),
        "simulation": row.get("simulation"),
        "analytic_p": row.get("analytic_p"),
        "stochastic_sim_p": row.get("stochastic_sim_p"),
    }
    return "fallback:" + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def grade_identity(output_hash, result_source_id):
    raw = f"{output_hash}|{result_source_id}|{GRADER_VERSION}"
    return hashlib.sha256(raw.encode()).hexdigest()


def bound_grade_identity(card, forecast, result_source_id, card_sha256):
    provenance = forecast.get("provenance") or {}
    identity = {
        "identity_version": 3, "event_id": str(forecast["event_id"]),
        "model_id": provenance.get("model_id"), "model_version": provenance.get("model_version"),
        "pregame_cutoff": card.get("requested_as_of_utc", card.get("as_of_utc")),
        "forecast_generated_at": card["generated_at_utc"],
        "forecast_output_hash": forecast_output_hash(forecast), "forecast_card_sha256": card_sha256,
        "result_source_id": result_source_id, "grader_version": GRADER_VERSION,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _paired_summary(rows):
    if not rows:
        return {
            "mean_brier_analytic_minus_sim": None,
            "median_brier_analytic_minus_sim": None,
            "mean_log_loss_analytic_minus_sim": None,
            "median_log_loss_analytic_minus_sim": None,
            "sim_lower_brier_count": 0,
            "analytic_lower_brier_count": 0,
            "brier_tie_count": 0,
            "sim_lower_log_loss_count": 0,
            "analytic_lower_log_loss_count": 0,
            "log_loss_tie_count": 0,
        }
    brier_d = [float(r["brier_analytic"]) - float(r["brier_sim"]) for r in rows]
    log_d = [float(r["log_loss_analytic"]) - float(r["log_loss_sim"]) for r in rows]
    tol = 1e-15
    return {
        "mean_brier_analytic_minus_sim": statistics.fmean(brier_d),
        "median_brier_analytic_minus_sim": statistics.median(brier_d),
        "mean_log_loss_analytic_minus_sim": statistics.fmean(log_d),
        "median_log_loss_analytic_minus_sim": statistics.median(log_d),
        "sim_lower_brier_count": sum(d > tol for d in brier_d),
        "analytic_lower_brier_count": sum(d < -tol for d in brier_d),
        "brier_tie_count": sum(abs(d) <= tol for d in brier_d),
        "sim_lower_log_loss_count": sum(d > tol for d in log_d),
        "analytic_lower_log_loss_count": sum(d < -tol for d in log_d),
        "log_loss_tie_count": sum(abs(d) <= tol for d in log_d),
    }


def _rolling(rows, windows=(30, 60, 100)):
    ordered = sorted(rows, key=lambda r: (r.get("start_time_utc", ""), r.get("graded_at_utc", "")))
    result = {}
    for window in windows:
        sample = ordered[-window:] if len(ordered) >= window else []
        result[str(window)] = {"n": len(sample), **_paired_summary(sample)} if sample else {"n": 0}
    return result


def aggregate(rows):
    n = len(rows)
    if not n:
        return {
            "n": 0,
            "status": "ACCUMULATING",
            "brier_analytic": None,
            "brier_sim": None,
            "brier_delta_sim_minus_analytic": None,
            "log_loss_analytic": None,
            "log_loss_sim": None,
            "directional_accuracy_analytic": None,
            "directional_accuracy_sim": None,
            "paired": _paired_summary([]),
            "rolling_paired": _rolling([]),
            "decision_gate": "INSUFFICIENT_SAMPLE",
            "reliability": {},
        }

    mean = lambda key: statistics.fmean(float(row[key]) for row in rows)
    brier_a = mean("brier_analytic")
    brier_s = mean("brier_sim")
    ll_a = mean("log_loss_analytic")
    ll_s = mean("log_loss_sim")
    acc_a = statistics.fmean(int((float(r["analytic_p_home"]) >= 0.5) == bool(r["home_won"])) for r in rows)
    acc_s = statistics.fmean(int((float(r["stochastic_sim_p_home"]) >= 0.5) == bool(r["home_won"])) for r in rows)

    if n < 50:
        decision = "PIPELINE_VALIDATION_ONLY_UNDER_50"
    elif n < 100:
        decision = "ACCUMULATE_50_TO_100_NO_PROMOTION"
    elif n < 250:
        decision = "PAIRED_COMPARISON_AND_BROAD_RELIABILITY_ONLY"
    elif n < 500:
        decision = "SEASONAL_DIAGNOSTIC_NO_SINGLE_SLICE_CALIBRATION_TRANSFORM"
    elif brier_s < brier_a - 0.005:
        decision = "EVIDENCE_FAVORS_STOCHASTIC_SIM_P_REVIEW_FOR_PROMOTION"
    elif brier_a < brier_s - 0.005:
        decision = "EVIDENCE_FAVORS_ANALYTIC_P_RETAIN_PRIMARY"
    else:
        decision = "CONTINUE_ACCUMULATION_DIFFERENCE_WITHIN_0_005"

    reliability = {}
    for estimator, p_key, bin_key in (
        ("analytic", "analytic_p_home", "calibration_bin_analytic"),
        ("sim", "stochastic_sim_p_home", "calibration_bin_sim"),
    ):
        bins = {}
        for row in rows:
            name = row[bin_key]
            bucket = bins.setdefault(name, {"n": 0, "predicted_sum": 0.0, "wins": 0})
            bucket["n"] += 1
            bucket["predicted_sum"] += float(row[p_key])
            bucket["wins"] += int(row["home_won"])
        reliability[estimator] = {
            name: {
                "n": bucket["n"],
                "mean_predicted_p": bucket["predicted_sum"] / bucket["n"],
                "actual_home_win_rate": bucket["wins"] / bucket["n"],
            }
            for name, bucket in sorted(bins.items())
        }

    return {
        "n": n,
        "status": "ACCUMULATING" if n < 500 else "DECISION_SAMPLE_REACHED",
        "brier_analytic": brier_a,
        "brier_sim": brier_s,
        "brier_delta_sim_minus_analytic": brier_s - brier_a,
        "log_loss_analytic": ll_a,
        "log_loss_sim": ll_s,
        "log_loss_delta_sim_minus_analytic": ll_s - ll_a,
        "directional_accuracy_analytic": acc_a,
        "directional_accuracy_sim": acc_s,
        "paired": _paired_summary(rows),
        "rolling_paired": _rolling(rows),
        "decision_gate": decision,
        "sample_policy": {
            "under_50": "pipeline_validation_only",
            "50_to_99": "bias_and_directionality_no_promotion",
            "100_to_249": "paired_comparison_and_broad_reliability",
            "250_to_499": "seasonal_and_rolling_diagnostics",
            "500_plus": "model_definition_review_permitted_if_time_stable",
        },
        "promotion_margin_brier": 0.005,
        "reliability": reliability,
    }


def grade(card, ledger_rows, results, registered_event_ids=(), card_sha256=None):
    if not card_sha256:
        raise ValueError("FROZEN_CARD_BINDING_REQUIRED")
    existing = {row["grade_id"]: row for row in ledger_rows}
    added, pending, skipped, duplicates = [], [], [], []

    for forecast in card.get("forecasts", []):
        if forecast.get("forecast_status") != "FORECAST_GENERATED":
            continue
        grading = forecast.get("grading") or {}
        attested = (str(forecast.get("event_id")) in registered_event_ids
                    and grading.get("eligibility_reason") == "REGISTRATION_ATTESTATION_REQUIRED")
        if grading and grading.get("eligible_for_prospective_grading") is False and not attested:
            skipped.append({"event_id": forecast.get("event_id"), "reason": grading.get("eligibility_reason")})
            continue

        event_id = str(forecast.get("event_id"))
        outcome = results.get(event_id)
        if outcome is None:
            pending.append(event_id)
            continue

        for side in ("home", "away"):
            if outcome.get(side + "_team") != forecast.get(side + "_team"):
                raise ValueError(f"RESULT_TEAM_MISMATCH:{event_id}:{side}")
        output_hash = forecast_output_hash(forecast)
        identity = bound_grade_identity(card, forecast, outcome["result_source_id"], card_sha256)
        legacy_id = grade_identity(output_hash, outcome["result_source_id"])
        if legacy_id in existing:
            legacy = existing[legacy_id]
            if not legacy.get("forecast_card_sha256"):
                raise ValueError(f"LEGACY_GRADE_BINDING_REQUIRED:{event_id}")
            if legacy["forecast_card_sha256"] == card_sha256:
                if (legacy.get("event_id") != event_id
                        or legacy.get("requested_as_of_utc") != card.get("requested_as_of_utc", card.get("as_of_utc"))):
                    raise ValueError(f"LEGACY_GRADE_IDENTITY_CONFLICT:{event_id}")
                # Read-only compatibility: never rewrite already appended v2 grade IDs.
                identity = legacy_id
        if identity in existing:
            previous = existing[identity]
            actual = previous["actual_result"]
            if (actual["home_score"], actual["away_score"], previous["home_won"]) != (
                    outcome["home_score"], outcome["away_score"], outcome["home_won"]):
                raise ValueError(f"RESULT_CONFLICT:{event_id}")
            duplicates.append({"event_id": event_id, "grade_id": identity, "status": "GRADE_ALREADY_EXISTS"})
            continue

        analytic_home = home_probability(forecast, "analytic_p_home", "analytic_p")
        sim_home = home_probability(forecast, "stochastic_sim_p_home", "stochastic_sim_p")
        candidate_home = candidate_home_probability(forecast)
        if analytic_home is None or sim_home is None:
            skipped.append({"event_id": event_id, "reason": "HOME_PROBABILITY_UNAVAILABLE"})
            continue

        y = 1 if outcome["home_won"] else 0
        graded_at = utcnow()
        row = {
            "grade_id": identity,
            "grade_identity_version": 3,
            "grader_version": GRADER_VERSION,
            "event_id": event_id,
            "card_date": card.get("card_date"),
            "requested_as_of_utc": card.get("requested_as_of_utc", card.get("as_of_utc")),
            "forecast_generated_at_utc": card.get("generated_at_utc"),
            "actual_data_vintage_utc": (card.get("pit_provenance") or {}).get("actual_data_vintage_utc"),
            "pit_status": (card.get("pit_provenance") or {}).get("pit_status"),
            "away_team": forecast.get("away_team"),
            "home_team": forecast.get("home_team"),
            "start_time_utc": forecast.get("start_time_utc"),
            "forecast_output_hash": output_hash,
            "simulation_engine_version": (forecast.get("simulation") or {}).get("simulation_engine_version"),
            "forecast_tier": forecast.get("forecast_tier"),
            "projected_total": forecast.get("projected_total"),
            "projected_margin": forecast.get("projected_margin"),
            "analytic_sim_abs_gap_pp": forecast.get("analytic_sim_abs_gap_pp"),
            "starter_confidence_tier": (forecast.get("diagnostics") or {}).get("starter_confidence_tier"),
            "analytic_p_home": analytic_home,
            "stochastic_sim_p_home": sim_home,
            "normal_margin_candidate_p_home": candidate_home,
            "home_won": bool(y),
            "actual_result": {
                "home_score": outcome["home_score"],
                "away_score": outcome["away_score"],
                "status": outcome["status"],
            },
            "result_source": outcome["result_source"],
            "result_source_id": outcome["result_source_id"],
            "result_observed_at_utc": outcome["result_observed_at_utc"],
            "result_snapshot_sha256": outcome.get("result_snapshot_sha256"),
            "brier_analytic": brier(analytic_home, y),
            "brier_sim": brier(sim_home, y),
            "brier_difference_analytic_minus_sim": brier(analytic_home, y) - brier(sim_home, y),
            "log_loss_analytic": log_loss(analytic_home, y),
            "log_loss_sim": log_loss(sim_home, y),
            "log_loss_difference_analytic_minus_sim": log_loss(analytic_home, y) - log_loss(sim_home, y),
            "probability_clip_epsilon": EPS,
            "calibration_bin_analytic": calibration_bin(analytic_home),
            "calibration_bin_sim": calibration_bin(sim_home),
            "graded_at_utc": graded_at,
            "market_features_used": False,
            "action_authority": False,
        }
        if candidate_home is not None:
            row["brier_normal_margin_candidate"] = brier(candidate_home, y)
            row["log_loss_normal_margin_candidate"] = log_loss(candidate_home, y)
        ledger_rows.append(row)
        added.append(row)
        existing[identity] = row

    return added, pending, skipped, duplicates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--card", required=True)
    parser.add_argument("--ledger", default="data/grading/mlb/calibration_ledger.jsonl")
    parser.add_argument("--summary-out", default="data/grading/mlb/calibration_summary.json")
    parser.add_argument("--report-out", default="output/mlb_calibration_grade_report.json")
    parser.add_argument("--results-json")
    args = parser.parse_args()

    # Delegate to the registry transaction, preserving this CLI's output argument names.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.grade_mlb_registry import main as registry_main
    card = json.loads(Path(args.card).read_text())
    cli = ["--grade-date", card["card_date"], "--ledger", args.ledger,
           "--summary", args.summary_out, "--output-dir", str(Path(args.report_out).parent),
           "--include-graded"]
    if args.results_json:
        cli.extend(["--results-json", args.results_json])
    # --card is an assertion, not permission to grade an unregistered artifact.
    cli.extend(["--card", args.card, "--report-out", args.report_out])
    return registry_main(cli)


if __name__ == "__main__":
    raise SystemExit(main())
