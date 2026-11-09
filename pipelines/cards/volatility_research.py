"""Optional joint-volatility child cards for all seven shared-card leagues.

Parent cards and direct winner heads are read-only. Missing paired score heads
produce visible coverage gaps; no totals or margins are inferred from winners.
Derived margin/total PMFs are mathematical diagnostics, not product activation;
CONTRACT_PRODUCTS separately gates every configured contract in this pipeline.
"""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from models.common import discrete_research as D
from models.common import volatility_matrix_v1 as V
from pipelines.cards.distribution_research import _contracts, point
from pipelines.cards import derived_missingness as M

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


PRODUCTS = ["joint_score", "margin", "total"]


def _scale_inputs(model, distribution, point_source):
    provenance = distribution["provenance"]
    scaling = model["scaling"]
    names = scaling["features"] if scaling is not None else []
    used = provenance["scale_features_used"]
    if set(used) != set(names):
        raise ValueError("JOINT_MISSINGNESS_SCALE_SCOPE")
    return {
        "score_head_source": point_source,
        "parent_home_mean": provenance["parent_home_mean"],
        "parent_away_mean": provenance["parent_away_mean"],
        "parent_forecast_sha256": provenance["parent_forecast_sha256"],
        "parent_model_id": model["parent_model_id"],
        "information_set": model["information_set"],
        "fitted_state_sha256": provenance["fitted_artifact_sha256"],
        "settlement": model["settlement"],
        "missing_scale_policy": "REFUSE_MISSING_REQUIRED_SCALE_INPUT",
        "scale_mode": "FITTED_CONDITIONAL" if names else "FITTED_UNCONDITIONAL",
        "conditional_scale": provenance["conditional_scale"],
        "features": {name: {"used":used[name], "training_mean":scaling["mean"][i],
                            "training_scaler_sd":scaling["sd"][i],
                            "fitted_log_mse_coefficient":scaling["beta"][i+1],
                            "imputation":None} for i,name in enumerate(names)},
        "numeric_law_sha256": D.digest({k: distribution[k] for k in ("home_scores", "away_scores", "masses")}),
        "training_and_current_use_same_declared_scale_features": True,
        "historical_missingness_by_season": None,
        "scope_limits_reviewed": False,
    }


def _parent_model_id(row):
    value = row.get("model_id")
    return value if isinstance(value, str) and value.strip() else None


def _matching_fits(row, league, config):
    return [e for e in config["loaded_models"] if e["model"]["league"] == league
            and e["model"]["parent_model_id"] == row.get("model_id")]


def verify_readback(report, output, card, config, *, expected_report_sha256):
    """Use the issuer's pre-write digest or an independently pinned copy for offline review."""
    expected = {k:v for k,v in report.items() if k != "artifact_sha256"}
    if D.digest(expected) != report["artifact_sha256"]:
        raise ValueError("JOINT_MISSINGNESS_ARTIFACT_HASH")
    league = card["league"].lower()
    parent_hash = D.digest(card)
    if (report["league"] != league or report["as_of_utc"] != card["as_of_utc"]
            or report["parent_card_sha256"] != parent_hash
            or report["config_sha256"] != config["config_file_sha256"]):
        raise ValueError("JOINT_MISSINGNESS_PARENT_OR_CONFIG")

    # Derive every expected attempt and refusal from the supplied parents and fits.
    # Matching the two output lists alone would accept deletion of an entire event.
    expected_slots = Counter()
    fitted_states = {e["model"]["model_id"]: e["model"]["artifact_sha256"] for e in config["loaded_models"]}
    parent_counts = Counter(row["event_id"] for row in card["forecasts"])
    parent_rows = {row["event_id"]: row for row in card["forecasts"]}
    for row in card["forecasts"]:
        event = row["event_id"]
        parent_model = _parent_model_id(row)
        fits = _matching_fits(row, league, config)
        if parent_counts[event] > 1:
            expected_slots[event, None, parent_model, "UNAVAILABLE"] += 1
        elif row.get("forecast_status") != "FORECAST_GENERATED":
            expected_slots[event, None, None, "PARENT_NOT_FORECAST"] += 1
        elif parent_model is None:
            expected_slots[event, None, None, "UNAVAILABLE"] += 1
        elif not fits:
            expected_slots[event, None, parent_model, "FIT_REQUIRED"] += 1
        else:
            for entry in fits:
                expected_slots[event, entry["model"]["model_id"], None, "FITTED"] += 1
    observed_slots = Counter()
    covered = Counter()
    for row in report["coverage"]:
        model_id = row.get("model_id") or row.get("parent_model_id") or "joint_fit_unavailable"
        M.check(row, report["league"], row["event_id"], model_id, PRODUCTS)
        status = row["status"]
        inputs = row["missingness_audit"]["details"]["input_observations"]
        if inputs["parent_card_sha256"] != parent_hash or inputs["config_sha256"] != config["config_file_sha256"]:
            raise ValueError("JOINT_MISSINGNESS_PARENT_OR_CONFIG")
        slot = "FITTED" if row.get("model_id") and status in ("COMPLETED", "UNAVAILABLE") else status
        observed_slots[row["event_id"], row.get("model_id"), row.get("parent_model_id"), slot] += 1
        if status == "COMPLETED":
            covered[row["event_id"], model_id] += 1
    if observed_slots != expected_slots:
        raise ValueError("JOINT_MISSINGNESS_PARENT_COVERAGE")
    forecasts = Counter()
    for row in report["results"]:
        model_id = row["distribution"]["model_id"]
        M.check(row, report["league"], row["event_id"], model_id, PRODUCTS)
        inputs = row["missingness_audit"]["details"]["input_observations"]
        provenance = row["distribution"]["provenance"]
        if (inputs["config_sha256"] != config["config_file_sha256"]
                or inputs["fitted_state_sha256"] != fitted_states.get(model_id)
                or provenance["fitted_artifact_sha256"] != fitted_states.get(model_id)):
            raise ValueError("JOINT_MISSINGNESS_FITTED_CONFIG")
        parent = parent_rows.get(row["event_id"])
        if parent is None or row["distribution"]["provenance"]["parent_forecast_sha256"] != D.digest(parent):
            raise ValueError("JOINT_MISSINGNESS_RESULT_PARENT")
        forecasts[row["event_id"], model_id] += 1
        filename = row["distribution"]["distribution_sha256"] + ".npz"
        if (row["simulation"]["file"] != filename or
                hashlib.sha256((output / filename).read_bytes()).hexdigest() != row["simulation"]["file_sha256"]):
            raise ValueError("JOINT_MISSINGNESS_DRAWS_READBACK")
    if forecasts != covered or any(count != 1 for count in covered.values()):
        raise ValueError("JOINT_MISSINGNESS_COVERAGE")
    if report["artifact_sha256"] != D.source_hash(expected_report_sha256):
        raise ValueError("JOINT_MISSINGNESS_EXPECTED_REPORT_HASH")


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
    counts = Counter(row["event_id"] for row in card["forecasts"])
    for row in card["forecasts"]:
        event_id = row["event_id"]
        if counts[event_id] > 1:
            report["coverage"].append({"event_id": event_id, "status": "UNAVAILABLE",
                                       "reason": "DUPLICATE_PARENT_EVENT", "parent_model_id": _parent_model_id(row)})
            continue
        entries = _matching_fits(row, league, config)
        if row.get("forecast_status") != "FORECAST_GENERATED":
            report["coverage"].append({"event_id": event_id, "status": "PARENT_NOT_FORECAST",
                                       "detail": row.get("forecast_status")})
            continue
        if _parent_model_id(row) is None:
            report["coverage"].append({"event_id": event_id, "status": "UNAVAILABLE",
                                       "reason": "PARENT_MODEL_ID_REQUIRED"})
            continue
        if not entries:
            report["coverage"].append({"event_id": event_id, "status": "FIT_REQUIRED",
                                       "parent_model_id": row.get("model_id")})
        seen_models = Counter(e["model"]["model_id"] for e in entries)
        for entry in entries:
            model = entry["model"]
            try:
                if seen_models[model["model_id"]] != 1:
                    raise ValueError("DUPLICATE_CHILD_MODEL")
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
                result = {
                    "event_id": event_id, "distribution": distribution,
                    "predictive_moments": V.moments(distribution),
                    "margin_distribution": margin, "total_distribution": total,
                    "score_outcome_probabilities": V.outcome_probabilities(distribution),
                    "point_head_source": point_source,
                    "simulation": {**metadata, "file": name,
                                   "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                    "contracts": priced, "parent_warnings": list(row.get("warnings", [])),
                    "limitations": list(model["limitations"]), "status": "DIAGNOSTIC"}
                M.attach(result, league, event_id, model["model_id"], PRODUCTS,
                         inputs={**_scale_inputs(model, distribution, point_source),
                                 "config_sha256": config["config_file_sha256"]},
                         method="Bound parent heads and fitted joint residual law; no missing-feature imputation",
                         missing=["SOURCE_SEASON_SUPPORT_AND_PAIRED_REFRESH_UNREVIEWED"])
                report["results"].append(result)
                report["coverage"].append({"event_id": event_id, "model_id": model["model_id"],
                                           "product": "joint_score", "status": "COMPLETED"})
            except (ValueError, KeyError, TypeError) as exc:
                report["coverage"].append({"event_id": event_id, "model_id": model.get("model_id"),
                                           "product": "joint_score", "status": "UNAVAILABLE",
                                           "reason": str(exc)})
    for record in report["coverage"]:
        model_id = record.get("model_id") or record.get("parent_model_id") or "joint_fit_unavailable"
        M.attach(record, league, record["event_id"], model_id, PRODUCTS,
                 inputs={"status":record["status"], "parent_card_sha256":report["parent_card_sha256"],
                         "config_sha256": config["config_file_sha256"]},
                 method="Joint child event coverage", missing=[] if record["status"] == "COMPLETED"
                 else [record.get("reason") or record.get("detail") or record["status"]])
    report["created_at_utc"] = D.writer_clock()
    issued = D.stamp(report["created_at_utc"])
    report["post_start_event_ids"], report["timing_unassessed_event_ids"] = [], []
    for row in card["forecasts"]:
        try:
            start = D.stamp(row.get("start_time_utc"))
        except (TypeError, ValueError):
            report["timing_unassessed_event_ids"].append(row["event_id"])
        else:
            if start <= issued:
                report["post_start_event_ids"].append(row["event_id"])
    report["artifact_sha256"] = D.digest(report)
    (output / "volatility_report.json").write_text(json.dumps(report, indent=2, sort_keys=True,
                                                              allow_nan=False) + "\n")
    verify_readback(json.loads((output / "volatility_report.json").read_bytes()), output, card, config,
                    expected_report_sha256=report["artifact_sha256"])
    return report
