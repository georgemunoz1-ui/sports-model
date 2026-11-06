"""Optional joint-volatility child cards for all seven shared-card leagues.

Parent cards and direct winner heads are read-only. Missing paired score heads
produce visible coverage gaps; no totals or margins are inferred from winners.
Derived margin/total PMFs are mathematical diagnostics, not product activation;
CONTRACT_PRODUCTS separately gates every configured contract in this pipeline.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from models.common import discrete_research as D
from models.common import volatility_matrix_v1 as V
from pipelines.cards.distribution_research import _contracts, point

CONTRACT_PRODUCTS = {
    "nfl": {"margin", "total"}, "cfb": {"margin", "total"},
    "nba": {"margin", "total"}, "wnba": {"margin", "total"},
    "mlb": {"margin"}, "nhl": {"margin", "total"}, "mls": {"total"},
}


def load_config(path):
    path = Path(path).resolve()
    config = json.loads(path.read_text())
    if config.get("schema") != "sports.volatility_card_config.research.v1":
        raise ValueError("CONFIG_SCHEMA")
    if config.get("action_authority") is not False:
        raise ValueError("RESEARCH_ONLY_CONFIG")
    D.identity(config.get("information_set"), "INFORMATION_SET")
    result = copy.deepcopy(config)
    result["config_file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    result["loaded_models"] = []
    for entry in config["models"]:
        model_path = (path.parent / entry["path"]).resolve()
        raw = model_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("CONFIG_MODEL_FILE_HASH_MISMATCH")
        model = json.loads(raw)
        V._validate_fit(model)
        result["loaded_models"].append({"model": model})
    return result


def score_point(row):
    """Use explicit paired scores, or an explicit margin plus an explicit total."""
    diagnostics = row.get("diagnostics") or {}
    prediction = diagnostics.get("prediction") or {}
    suffixes = ("score", "points", "runs", "goals")
    for container in (row, prediction, diagnostics):
        for suffix in suffixes:
            for prefix in ("projected_", "predicted_"):
                home_key, away_key = f"{prefix}home_{suffix}", f"{prefix}away_{suffix}"
                if container.get(home_key) is not None and container.get(away_key) is not None:
                    return D.finite(container[home_key]), D.finite(container[away_key]), "EXPLICIT_PAIRED_SCORE_HEADS"
    margin = point(row, "margin")
    total = point(row, "total")
    home, away = (total + margin) / 2.0, (total - margin) / 2.0
    if min(home, away) < 0:
        raise ValueError("NEGATIVE_DERIVED_SCORE_MEAN")
    return home, away, "EXPLICIT_MARGIN_AND_TOTAL_HEADS"


def _empirical(draws, template):
    values = draws.tolist()
    return D.make_distribution(values, [1.0] * len(values), league=template["league"],
                               product=template["product"], settlement=template["settlement"],
                               model_id=template["model_id"] + ".simulation",
                               provenance=template["provenance"])


def build(card, config, output, *, simulations=100000):
    """Create a new immutable joint-score child report, never revise the card."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    league = card["league"].lower()
    if league not in V.SETTLEMENTS:
        raise ValueError("LEAGUE_UNSUPPORTED")
    cutoff = card["as_of_utc"]
    report = {"schema": "sports.volatility_card.research.v1", "league": league,
              "parent_card_sha256": D.digest(card), "config_sha256": config["config_file_sha256"],
              "as_of_utc": cutoff, "results": [], "coverage": [],
              "joint_score_distribution": True,
              "direct_winner_heads_unchanged": True,
              "supported_contract_products": sorted(CONTRACT_PRODUCTS[league]),
              "derived_marginals_are_diagnostic_not_product_activation": True,
              "prospective_grade_eligible": False,
              "predictive_validation": "NOT_ESTABLISHED", "action_authority": False}
    for row in card["forecasts"]:
        event_id = row["event_id"]
        entries = [e for e in config["loaded_models"] if e["model"]["league"] == league
                   and e["model"]["parent_model_id"] == row.get("model_id")]
        if row.get("forecast_status") != "FORECAST_GENERATED":
            report["coverage"].append({"event_id": event_id, "status": "PARENT_NOT_FORECAST",
                                       "detail": row.get("forecast_status")})
            continue
        if not entries:
            report["coverage"].append({"event_id": event_id, "status": "FIT_REQUIRED",
                                       "parent_model_id": row.get("model_id")})
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
                home_mean, away_mean, point_source = score_point(row)
                parent_hash = D.digest(row)
                distribution = V.predict(
                    model, home_mean=home_mean, away_mean=away_mean, event_id=event_id,
                    cutoff=cutoff, parent_model_id=row["model_id"],
                    information_set=config["information_set"], parent_forecast_sha256=parent_hash,
                    scale_features=row.get("model_input_snapshot") or {},
                    start_time_utc=row["start_time_utc"])
                margin, total = V.derive(distribution, "margin"), V.derive(distribution, "total")
                contracts = []
                for product_distribution in (margin, total):
                    product_contracts = _contracts(config, row, product_distribution, cutoff)
                    if product_contracts and product_distribution["product"] not in CONTRACT_PRODUCTS[league]:
                        raise ValueError("UNSUPPORTED_PRODUCT")
                    contracts.extend(product_contracts)
                home_draws, away_draws, metadata = V.simulate(distribution, draws=simulations)
                name = distribution["distribution_sha256"] + ".npz"
                path = output / name
                if path.exists():
                    raise ValueError("DUPLICATE_DISTRIBUTION_OUTPUT")
                np.savez(path, home=home_draws, away=away_draws)
                margin_draws, total_draws = home_draws-away_draws, home_draws+away_draws
                empirical = {"margin": _empirical(margin_draws, margin),
                             "total": _empirical(total_draws, total)}
                priced = []
                for contract in contracts:
                    exact_distribution = margin if contract["product"] == "margin" else total
                    priced.append({**contract,
                                   "model_probabilities": D.price(exact_distribution, contract["line"], contract["side"]),
                                   "simulation_probabilities": D.price(empirical[contract["product"]],
                                                                        contract["line"], contract["side"])})
                report["results"].append({
                    "event_id": event_id, "distribution": distribution,
                    "predictive_moments": V.moments(distribution),
                    "margin_distribution": margin, "total_distribution": total,
                    "score_outcome_probabilities": V.outcome_probabilities(distribution),
                    "point_head_source": point_source,
                    "simulation": {**metadata, "file": name,
                                   "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                    "contracts": priced, "parent_warnings": list(row.get("warnings", [])),
                    "limitations": list(model["limitations"]), "status": "DIAGNOSTIC"})
                report["coverage"].append({"event_id": event_id, "model_id": model["model_id"],
                                           "product": "joint_score", "status": "COMPLETED"})
            except (ValueError, KeyError, TypeError) as exc:
                report["coverage"].append({"event_id": event_id, "model_id": model.get("model_id"),
                                           "product": "joint_score", "status": "UNAVAILABLE",
                                           "reason": str(exc)})
    report["created_at_utc"] = D.writer_clock()
    report["post_start_event_ids"] = [r["event_id"] for r in card["forecasts"]
                                      if D.stamp(r["start_time_utc"]) <= D.stamp(report["created_at_utc"])]
    report["artifact_sha256"] = D.digest(report)
    (output / "volatility_report.json").write_text(json.dumps(report, indent=2, sort_keys=True,
                                                              allow_nan=False) + "\n")
    return report
