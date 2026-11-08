"""Mandatory missing-input accounting for the standalone men's CBB score model."""
from collections import Counter
from itertools import groupby
from pathlib import Path
import json

from models.common.discrete_research import digest
from pipelines.cards.missingness import seal_audit, verify_audit

MODEL = "cbb.men.d1.opponent_adjusted_score_residual.v1.research"
PRODUCTS = ["home_score", "away_score", "home_margin", "total", "home_win", "margin_pmf", "total_pmf"]
REGISTRY = Path(__file__).resolve().parents[1] / "data/model_selection/cbb_missingness_v1.json"


def historical_support(games, minimum):
    counts, seasons = Counter(), {}
    for _, group in groupby(games, key=lambda g: g["day"]):
        batch = list(group)
        for game in batch:
            row = seasons.setdefault(str(game["season"]), {"games": 0, "below_history_minimum": 0,
                                                           "unseen_team": 0, "neutral": 0})
            prior = min(counts[game["h"]], counts[game["a"]])
            row["games"] += 1
            row["below_history_minimum"] += int(prior < minimum)
            row["unseen_team"] += int(prior == 0)
            row["neutral"] += int(game["neutral"])
        for game in batch:
            counts.update((game["h"], game["a"]))
    return seasons


def binding(row, context):
    return {"row": {k:v for k,v in row.items() if k != "missingness_audit"},
            "provenance": context}


def context(card):
    return {key: card[key] for key in ("date", "as_of_utc", "model", "state_sha256",
                                       "input_manifest_sha256", "history_games_sha256",
                                       "missingness_registry_sha256", "missingness_historical_support", "missingness_runtime_checks",
                                       "previous_card_sha256")}


def change(old, row, old_card, card):
    common = {"model_version_changed": None, "missingness_imputation": None,
              "sporting_observations": None, "interaction": None, "simulation_win_probability_delta": None}
    if old is None:
        return {**common, "status":"NO_MATCHED_PRIOR_EVENT"}
    if any(r["forecast_status"] != "FORECAST_GENERATED" for r in (old, row)):
        return {**common, "status": "UNAVAILABLE_HEAD_TRANSITION",
                "old_status": old["forecast_status"], "old_reason": old.get("reason")}
    if digest(old_card["model"]) != digest(card["model"]):
        return {**common, "status": "PROCEDURE_CHANGED_REPLAY_REQUIRED", "model_version_changed": True}
    a, b = old["model_input_snapshot"], row["model_input_snapshot"]
    if (a["h"],a["a"]) != (b["h"],b["a"]):
        return {**common, "status":"TEAM_IDENTITY_CHANGED", "model_version_changed": False}
    # With admitted sides and a fixed law there is no imputation on the point heads.
    # A rating difference can combine earlier results, coverage and off-season carry.
    # Without the old sources and state replay we do not assign it all to sporting news.
    venue = card["model"]["priors"][0] * (int(a["neutral"]) - int(b["neutral"]))
    delta_margin = row["home_margin"] - old["home_margin"]
    delta_total = row["total"] - old["total"]
    same_ratings = all(a[key] == b[key] for key in ("home_state","away_state"))
    return {**common, "status":"PAIRED_SAME_PROCEDURE", "model_version_changed": False,
            "missingness_imputation": {"home_margin":0., "total":0.} if same_ratings else None,
            "sporting_observations": {"home_margin":venue, "total":0.} if same_ratings else None,
            "observed_venue_margin_points": venue, "rating_state_margin_points": delta_margin - venue,
            "rating_state_total_points": delta_total, "home_win_probability_delta": row["p_home_win"]-old["p_home_win"],
            "sampling_error_delta": ((row["p_home_win_sim"] - row["p_home_win"])
                                      -(old["p_home_win_sim"] - old["p_home_win"])),
            "interaction": "RATING_LINEAGE_AND_DISCRETE_PMF_REQUIRE_MATCHED_INPUT_REPLAY"}


def attach(card, targets, state, minimum, prior_card=None):
    registry = json.loads(REGISTRY.read_bytes())
    card["missingness_registry_sha256"] = digest(registry)
    old_rows = {} if prior_card is None else {r["event_id"]:r for r in prior_card["forecasts"]}
    provenance = context(card)
    for row, game in zip(card["forecasts"], targets, strict=True):
        assert row["event_id"] == "CBB:" + game["id"]
        prior_counts = [int(state[t][2]) if t in state else 0 for t in (game["h"],game["a"])]
        generated = row["forecast_status"] == "FORECAST_GENERATED"
        sensitivity = None
        if generated:
            # Exact coefficients and refusal boundaries of the same native point law.
            venue_delta = card["model"]["priors"][0] if game["neutral"] else -card["model"]["priors"][0]
            sensitivity = {"observed_venue_flip_delta_margin_points":venue_delta,
                           "observed_venue_flip_delta_total_points":0.0,
                           "unknown_venue":"REFUSED", "team_history_below_minimum":"REFUSED",
                           "training_and_inference_projector":"scripts.cbb_shadow.project",
                           "interpretation":"Diagnostic venue and admission sensitivity; no forecast substitution."}
        details = {
            "source_state": "VERIFIED_OBSERVATION", "sensitivity": sensitivity, "coverage": row["forecast_status"],
            "team_identity": "UNRESOLVED" if "TEAM_IDENTITY" in game["issues"] else "EXPLICIT_ORIENTED_TEAM_IDS",
            "venue": "UNRESOLVED" if game["neutral"] is None else "VERIFIED_OBSERVATION",
            "eligible_prior_games_home_away": prior_counts, "minimum_prior_games_each": minimum,
            "team_history": "INSUFFICIENT" if min(prior_counts)<minimum else "AVAILABLE",
            "d1_pair_confirmed": game["d1"], "affiliation_resolution": game["affiliation_resolution"],
            "source_issues": game["issues"], "fallback_applied_at_issuance": False,
            "lineup_and_injuries": "NOT_CONSUMED", "historical_cutoff": "EARLIER_PACIFIC_DAYS",
            "change": change(old_rows.get(row["event_id"]),row,prior_card,card),
            "reviewed_limits": None, "forward_monitoring": "PENDING",
        }
        row["missingness_audit"] = seal_audit(league="cbb",event_id=row["event_id"],model_id=MODEL,
                                               products=PRODUCTS,forecast=binding(row, provenance),details=details)


def verify(card):
    registry = json.loads(REGISTRY.read_bytes())
    checked = (card["schema"] == "sports.cbb.shadow_card.v2" and card["model"]["model_id"] == MODEL
               and card["missingness_registry_sha256"] == digest(registry) and card["action_authority"] is False
               and card["league"] == "CBB" and card["market_input"] is card["official_release_eligible"] is False
               and len(card["forecasts"]) == card["scheduled"])
    if not checked:
        raise ValueError("CBB_MISSINGNESS_SCOPE_OR_REGISTRY")
    if any(not isinstance(row,dict) for row in card["forecasts"]):
        raise ValueError("CBB_MISSINGNESS_ROW_TYPE")
    seen = set()
    provenance = context(card)
    for row in card["forecasts"]:
        eid=row["event_id"]
        if (eid in seen or row["qualification"] != "NO_PICK" or row["action_authority"] is not False
            or not verify_audit(row.get("missingness_audit"),league="cbb",event_id=eid,model_id=MODEL,
                                products=PRODUCTS,forecast=binding(row, provenance))):
            raise ValueError("CBB_MISSINGNESS_READBACK:" + eid)
        seen.add(eid)
