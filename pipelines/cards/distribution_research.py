"""Opt-in downstream research products for every shared-card sport/model.

Does not refit, rewrite parent rows, infer margins from win probabilities, or
activate model selection. Direct margin/total heads remain separate distributions.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import numpy as np
from models.common import discrete_research as D
from models.common import discrete_calibration as C


def load_config(path):
    path = Path(path).resolve()
    config = json.loads(path.read_text())
    if config.get("schema") != "sports.distribution_card_config.research.v1":
        raise ValueError("CONFIG_SCHEMA")
    if config.get("action_authority") is not False:
        raise ValueError("RESEARCH_ONLY_CONFIG")
    result = copy.deepcopy(config)
    result["config_file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    result["loaded_models"] = []
    for entry in config["models"]:
        model_path = (path.parent / entry["path"]).resolve()
        raw = model_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("CONFIG_MODEL_FILE_HASH_MISMATCH")
        model = json.loads(raw)
        calibrator = None
        if entry.get("calibration"):
            cal_path = (path.parent / entry["calibration"]["path"]).resolve()
            raw_cal = cal_path.read_bytes()
            if hashlib.sha256(raw_cal).hexdigest() != entry["calibration"]["sha256"]:
                raise ValueError("CONFIG_CALIBRATION_FILE_HASH_MISMATCH")
            calibrator = json.loads(raw_cal)
        result["loaded_models"].append({"model": model, "calibrator": calibrator})
    return result


def point(row, product):
    """Only explicit point outputs, with documented home orientation."""
    d = row.get("diagnostics") or {}
    prediction = d.get("prediction") or {}
    if product == "margin":
        if d.get("home_margin") is not None:
            return D.finite(d["home_margin"])
        if prediction.get("home_margin") is not None:
            return D.finite(prediction["home_margin"])
        for home, away in [("projected_home_runs", "projected_away_runs"),
                           ("projected_home_points", "projected_away_points")]:
            if row.get(home) is not None and row.get(away) is not None:
                return D.finite(row[home]) - D.finite(row[away])
        if row.get("projected_margin_orientation") == "WINNER_MINUS_OPPONENT" and row.get("projected_margin") is not None and row.get("model_winner") in {row["home_team"], row["away_team"]}:
            value = D.finite(row["projected_margin"])
            return value if row["model_winner"] == row["home_team"] else -value
    else:
        for value in [d.get("total"), prediction.get("total_points"), row.get("projected_total")]:
            if isinstance(value, (int, float)):
                return D.finite(value)
        for home, away in [("projected_home_runs", "projected_away_runs"),
                           ("projected_home_points", "projected_away_points")]:
            if row.get(home) is not None and row.get(away) is not None:
                return D.finite(row[home]) + D.finite(row[away])
    raise ValueError("POINT_HEAD_UNAVAILABLE:" + product)


def _contracts(config, row, distribution, cutoff):
    result = []
    for c in config.get("contracts", []):
        if c["event_id"] != row["event_id"] or c["product"] != distribution["product"]:
            continue
        if c["settlement"] != distribution["settlement"]:
            raise ValueError("CONTRACT_SETTLEMENT_MISMATCH")
        if c["kind"] not in {"HYPOTHETICAL", "MARKET"}:
            raise ValueError("CONTRACT_KIND_REQUIRED")
        if c["kind"] == "MARKET":
            q = c["quote"]
            if q["event_id"] != row["event_id"] or q["line"] != c["line"] or q["side"] != c["side"] or q["settlement"] != c["settlement"]:
                raise ValueError("QUOTE_IDENTITY_MISMATCH")
            D.source_hash(q["source_sha256"])
            D.identity(q["book"], "BOOK")
            if D.stamp(q["observed_at_utc"]) > D.stamp(cutoff) or D.stamp(q["retrieved_at_utc"]) > D.stamp(cutoff):
                raise ValueError("FUTURE_QUOTE")
            if min(D.finite(q["decimal_odds"]), D.finite(q["opposing_decimal_odds"])) <= 1:
                raise ValueError("DECIMAL_ODDS_INVALID")
        elif c.get("quote"):
            raise ValueError("HYPOTHETICAL_CONTRACT_WITH_QUOTE")
        D.price(distribution, c["line"], c["side"])
        result.append(copy.deepcopy(c))
    return result


def nfl_card(bundle, created_at_utc):
    """Bridge the canonical NFL pregame bundle, preserving its parent identity."""
    if bundle.get("mode") == "live":
        raise ValueError("LIVE_DISTRIBUTION_NOT_IMPLEMENTED")
    if bundle.get("schema") not in {"nfl.integrated_context_forecast.v1", "nfl.enhanced_pregame_forecast.v1"}:
        raise ValueError("NFL_BUNDLE_SCHEMA")
    event = bundle["event"]
    return {"league": "NFL", "as_of_utc": bundle["cutoff_utc"], "generated_at_utc": created_at_utc,
            "parent_bundle_sha256": D.digest(bundle), "forecasts": [{
                "event_id": event["event_id"], "start_time_utc": event["start_time_utc"],
                "home_team": event["home_team"], "away_team": event["away_team"],
                "model_id": bundle["model_id"], "forecast_status": "FORECAST_GENERATED",
                "input_snapshot_hash": D.digest(bundle["features"]),
                "model_state_config_hash": bundle["model_artifact_sha256"],
                "model_input_snapshot": bundle["features"], "diagnostics": bundle,
                "warnings": bundle.get("warnings", [])}]}


def build(card, config, output, *, simulations=100000):
    """Create a separate child report; unaffected events continue after refusals."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    league = card["league"].lower()
    if league not in D.SETTLEMENTS:
        raise ValueError("LEAGUE_UNSUPPORTED")
    cutoff = card["as_of_utc"]
    report = {"schema": "sports.distribution_card.research.v1", "league": league,
              "parent_card_sha256": D.digest(card), "config_sha256": config["config_file_sha256"],
              "as_of_utc": cutoff, "results": [], "coverage": [],
              "joint_score_distribution": False, "prospective_grade_eligible": False,
              "predictive_validation": "NOT_ESTABLISHED", "action_authority": False}
    for row in card["forecasts"]:
        eid = row["event_id"]
        entries = [e for e in config["loaded_models"] if e["model"]["league"] == league and
                   e["model"]["parent_model_id"] == row.get("model_id")]
        if row.get("forecast_status") != "FORECAST_GENERATED":
            report["coverage"].append({"event_id": eid, "status": "PARENT_NOT_FORECAST", "detail": row.get("forecast_status")})
            continue
        if not entries:
            report["coverage"].append({"event_id": eid, "status": "FIT_REQUIRED", "parent_model_id": row.get("model_id")})
        for entry in entries:
            model = entry["model"]
            try:
                if not D.stamp(cutoff) < D.stamp(row["start_time_utc"]):
                    raise ValueError("PARENT_CUTOFF_NOT_PREGAME")
                if D.stamp(card["generated_at_utc"]) >= D.stamp(row["start_time_utc"]):
                    raise ValueError("PARENT_CREATED_POST_START")
                D.source_hash(row["input_snapshot_hash"])
                D.source_hash(row["model_state_config_hash"])
                if (row.get("diagnostics") or {}).get("market_input", False) is not model["market_input"]:
                    raise ValueError("PARENT_MARKET_ROLE_MISMATCH")
                mean = point(row, model["product"])
                d = D.predict(model, mean=mean, event_id=eid, cutoff=cutoff, parent_model_id=row["model_id"],
                              information_set=config["information_set"], parent_forecast_sha256=D.digest(row),
                              scale_features=row.get("model_input_snapshot") or {})
                # Optional scenario forecasts must already be frozen with source
                # and event/cutoff bindings. No unsupported player-value guesses.
                scenario_key = eid + ":" + model["product"]
                if scenario_key in config.get("availability_scenarios", {}):
                    scenarios = config["availability_scenarios"][scenario_key]
                    for scenario in scenarios:
                        sd = scenario["distribution"]
                        if sd["model_id"] != model["model_id"] or sd["provenance"].get("parent_forecast_sha256") != D.digest(row):
                            raise ValueError("SCENARIO_PARENT_BINDING_MISMATCH")
                    d = D.mix(scenarios, cutoff=cutoff, model_id=model["model_id"] + ".availability_mixture")
                if entry["calibrator"]:
                    d = C.apply(d, entry["calibrator"])
                contracts = _contracts(config, row, d, cutoff)
                draws, metadata = D.simulate(d, draws=simulations)
                name = d["distribution_sha256"] + ".npy"
                path = output / name
                if path.exists():
                    raise ValueError("DUPLICATE_DISTRIBUTION_OUTPUT")
                np.save(path, draws, allow_pickle=False)
                empirical = D.make_distribution(draws.tolist(), [1.] * len(draws), league=league,
                                                 product=d["product"], settlement=d["settlement"],
                                                 model_id=d["model_id"], provenance=d["provenance"])
                report["results"].append({"event_id": eid, "distribution": d,
                    "simulation": {**metadata, "file": name, "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                    "contracts": [{**c, "model_probabilities": D.price(d, c["line"], c["side"]),
                                   "simulation_probabilities": D.price(empirical, c["line"], c["side"])} for c in contracts],
                    "parent_warnings": list(row.get("warnings", [])), "status": "DIAGNOSTIC"})
                report["coverage"].append({"event_id": eid, "model_id": model["model_id"], "product": model["product"], "status": "COMPLETED"})
            except (ValueError, KeyError, TypeError) as exc:
                report["coverage"].append({"event_id": eid, "model_id": model.get("model_id"),
                                          "product": model.get("product"), "status": "UNAVAILABLE", "reason": str(exc)})
    report["created_at_utc"] = D.writer_clock()
    report["post_start_event_ids"] = [r["event_id"] for r in card["forecasts"]
                                      if D.stamp(r["start_time_utc"]) <= D.stamp(report["created_at_utc"])]
    report["artifact_sha256"] = D.digest(report)
    (output / "distribution_report.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return report
