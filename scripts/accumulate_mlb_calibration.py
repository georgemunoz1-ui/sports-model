#!/usr/bin/env python3
"""Grade frozen MLB forecast cards against final results and accumulate calibration evidence.

This script never regenerates forecasts and never consumes sportsbook prices. It grades
only probabilities already frozen in a diagnostic card. The durable ledger is idempotent
by forecast output hash + event id so reproduction runs cannot double-count a forecast.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://statsapi.mlb.com/api/v1"
EPS = 1e-12


def utcnow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sports-model-calibration/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def finite_prob(value):
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
    # Fixed 10-point bins; 1.00 is folded into the final bin.
    low = min(0.9, math.floor(probability * 10.0) / 10.0)
    high = min(1.0, low + 0.1)
    return f"{low:.1f}-{high:.1f}"


def load_ledger(path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def save_ledger(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda row: (row.get("card_date", ""), row.get("event_id", ""), row.get("grade_id", "")))
    text = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in ordered)
    path.write_text(text)


def outcome_map(card_date, results_json=None):
    if results_json:
        data = json.loads(Path(results_json).read_text())
    else:
        data = get_json(f"{BASE}/schedule?sportId=1&date={card_date}")
    result = {}
    for date_row in data.get("dates", []):
        for game in date_row.get("games", []):
            event_id = str(game.get("gamePk"))
            status = game.get("status", {})
            abstract = status.get("abstractGameState")
            detailed = status.get("detailedState")
            is_final = abstract == "Final" or str(detailed).startswith("Final") or detailed == "Game Over"
            home = game.get("teams", {}).get("home", {})
            away = game.get("teams", {}).get("away", {})
            home_score = home.get("score")
            away_score = away.get("score")
            if is_final and home_score is not None and away_score is not None and int(home_score) != int(away_score):
                result[event_id] = {
                    "status": detailed or abstract,
                    "home_score": int(home_score),
                    "away_score": int(away_score),
                    "home_won": int(home_score) > int(away_score),
                }
    return result


def forecast_identity(row):
    output_hash = (row.get("provenance") or {}).get("output_hash")
    if not output_hash:
        payload = {
            "event_id": row.get("event_id"),
            "input_snapshot_hash": row.get("input_snapshot_hash"),
            "model_state_config_hash": row.get("model_state_config_hash"),
            "simulation": row.get("simulation"),
            "analytic_p": row.get("analytic_p"),
            "stochastic_sim_p": row.get("stochastic_sim_p"),
        }
        output_hash = "fallback:" + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    raw = f"{row.get('event_id')}|{output_hash}"
    return hashlib.sha256(raw.encode()).hexdigest(), output_hash


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
            "decision_gate": "INSUFFICIENT_SAMPLE",
            "reliability": {},
        }

    mean = lambda key: sum(float(row[key]) for row in rows) / n
    brier_a = mean("brier_analytic")
    brier_s = mean("brier_sim")
    ll_a = mean("log_loss_analytic")
    ll_s = mean("log_loss_sim")

    if n < 100:
        decision = "ACCUMULATE_TO_100"
    elif n < 200:
        decision = "BRIER_COMPARISON_VISIBLE_CALIBRATION_GATE_NOT_MET"
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
        "status": "ACCUMULATING" if n < 200 else "DECISION_SAMPLE_REACHED",
        "brier_analytic": brier_a,
        "brier_sim": brier_s,
        "brier_delta_sim_minus_analytic": brier_s - brier_a,
        "log_loss_analytic": ll_a,
        "log_loss_sim": ll_s,
        "log_loss_delta_sim_minus_analytic": ll_s - ll_a,
        "decision_gate": decision,
        "minimum_brier_comparison_games": 100,
        "minimum_calibration_decision_games": 200,
        "promotion_margin_brier": 0.005,
        "reliability": reliability,
    }


def grade(card, ledger_rows, results):
    existing = {row["grade_id"] for row in ledger_rows}
    added = []
    pending = []
    skipped = []

    for forecast in card.get("forecasts", []):
        if forecast.get("forecast_status") != "FORECAST_GENERATED":
            continue
        grading = forecast.get("grading") or {}
        if grading and grading.get("eligible_for_prospective_grading") is False:
            skipped.append({"event_id": forecast.get("event_id"), "reason": grading.get("eligibility_reason")})
            continue

        event_id = str(forecast.get("event_id"))
        identity, output_hash = forecast_identity(forecast)
        if identity in existing:
            continue
        outcome = results.get(event_id)
        if outcome is None:
            pending.append(event_id)
            continue

        analytic_home = home_probability(forecast, "analytic_p_home", "analytic_p")
        sim_home = home_probability(forecast, "stochastic_sim_p_home", "stochastic_sim_p")
        candidate_home = candidate_home_probability(forecast)
        if analytic_home is None or sim_home is None:
            skipped.append({"event_id": event_id, "reason": "HOME_PROBABILITY_UNAVAILABLE"})
            continue

        y = 1 if outcome["home_won"] else 0
        row = {
            "grade_id": identity,
            "event_id": event_id,
            "card_date": card.get("card_date"),
            "requested_as_of_utc": card.get("requested_as_of_utc", card.get("as_of_utc")),
            "actual_data_vintage_utc": (card.get("pit_provenance") or {}).get("actual_data_vintage_utc"),
            "pit_status": (card.get("pit_provenance") or {}).get("pit_status"),
            "away_team": forecast.get("away_team"),
            "home_team": forecast.get("home_team"),
            "start_time_utc": forecast.get("start_time_utc"),
            "forecast_output_hash": output_hash,
            "simulation_engine_version": (forecast.get("simulation") or {}).get("simulation_engine_version"),
            "analytic_p_home": analytic_home,
            "stochastic_sim_p_home": sim_home,
            "normal_margin_candidate_p_home": candidate_home,
            "home_won": bool(y),
            "actual_result": {
                "home_score": outcome["home_score"],
                "away_score": outcome["away_score"],
                "status": outcome["status"],
            },
            "brier_analytic": brier(analytic_home, y),
            "brier_sim": brier(sim_home, y),
            "log_loss_analytic": log_loss(analytic_home, y),
            "log_loss_sim": log_loss(sim_home, y),
            "calibration_bin_analytic": calibration_bin(analytic_home),
            "calibration_bin_sim": calibration_bin(sim_home),
            "graded_at_utc": utcnow(),
            "market_features_used": False,
            "action_authority": False,
        }
        if candidate_home is not None:
            row["brier_normal_margin_candidate"] = brier(candidate_home, y)
            row["log_loss_normal_margin_candidate"] = log_loss(candidate_home, y)
        ledger_rows.append(row)
        added.append(row)
        existing.add(identity)

    return added, pending, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--card", required=True)
    parser.add_argument("--ledger", default="data/grading/mlb/calibration_ledger.jsonl")
    parser.add_argument("--summary-out", default="data/grading/mlb/calibration_summary.json")
    parser.add_argument("--report-out", default="output/mlb_calibration_grade_report.json")
    parser.add_argument("--results-json")
    args = parser.parse_args()

    card = json.loads(Path(args.card).read_text())
    if str(card.get("league")).upper() != "MLB":
        raise SystemExit("CARD_LEAGUE_NOT_MLB")

    ledger_path = Path(args.ledger)
    ledger = load_ledger(ledger_path)
    results = outcome_map(card["card_date"], args.results_json)
    added, pending, skipped = grade(card, ledger, results)
    save_ledger(ledger_path, ledger)

    summary = {
        "artifact_type": "mlb_probability_calibration_summary_v1",
        "generated_at_utc": utcnow(),
        "market_overlay_enabled": False,
        "action_authority": False,
        "metrics": aggregate(ledger),
    }
    summary_path = Path(args.summary_out)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    report = {
        "artifact_type": "mlb_forecast_grade_run_v1",
        "card_date": card.get("card_date"),
        "added_count": len(added),
        "pending_event_ids": pending,
        "skipped": skipped,
        "ledger_count": len(ledger),
        "summary": summary["metrics"],
    }
    report_path = Path(args.report_out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
