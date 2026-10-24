"""Presentation-only path attribution; never a market-independence certificate.

Exact identities describe the reviewed implementation, not the authenticity or
full historical lineage of a supplied card. No fitted values or RNG are changed.
"""
import copy

PATHS = {
    "nfl.integrated_context.qb.v1.research": (
        "nfl", "models/nfl/contextual/runtime.py:run",
        "Historical EPA/team state, weather/rest and fitted QB features; independent logistic and Ridge heads.",
        "Winner selected; Ridge margin/total remain diagnostics, with no selected QB joint-score sampler."),
    "cfb.fbs.elo_form_logit_ridge.v1_0.shadow": (
        "cfb", "models/current/cfb.py:forecast",
        "Historical Elo, scoring EWMAs, rest, neutral-site/home advantage and conference features.",
        "Winner and separate margin point estimate; selected total head unavailable."),
    "cfb.fbs.elo_context_logit.v1_0.week1_shadow": (
        "cfb", "harness/cfb_forecast_0829.py:build; models/current/cfb.py:forecast",
        "Opener-specific Elo, neutral-site and conference feature subset.",
        "Requires a matching opener package; current preparer builds the week-2-plus identity."),
    "wnba.rs.ff7_logit_ridge.v1_0.shadow": (
        "wnba", "models/current/wnba.py:forecast -> harness/wnba_model_v1.py:predict_slate",
        "Historical box-score efficiency/four factors, rest/back-to-back, league scoring and pace.",
        "Fitted winner, margin and total heads; winner draws do not supply cover/total probabilities."),
    "mlb.v13.current_input.research.v1": (
        "mlb", "pipelines/cards/selected.py:apply_default -> harness/run_v13_historical.py:v13_sim",
        "Team runs for/against, starter ERA/starts/K/BB, park and frozen V13 constants; selected probability is Monte Carlo.",
        "Winner with declared tie proxy; run-line and total settlement unsupported. Logistic candidate is separate."),
}
for _league in ("nba", "nhl", "mls"):
    PATHS[_league + ".initial_causal_score.research.v1"] = (
        _league, "models/current/baseline.py:forecast",
        "Historical scoring EWMAs, training prior, rest, cold-start and neutral-site features.",
        ("Opt-in initial research, no verified default. Poisson goal rates supply regulation 1X2 and mean total; no exposed margin product."
         if _league == "mls" else
         "Opt-in initial research, no verified default. Independent winner/margin/total heads; no joint-score sampler."))


def describe(row, league):
    diagnostics = row.get("diagnostics") or {}
    mid = row.get("model_id")
    declared = diagnostics.get("market_input")
    declared = declared if isinstance(declared, bool) else None
    result = {
        "schema": "sports.market_path_disclosure.v1", "model_id": mid,
        "review_scope": "SOURCE_PATH_ATTRIBUTION_NOT_ARTIFACT_OR_TRAINING_LINEAGE_CERTIFICATION",
        "reported_market_input": declared, "path_class": "UNREVIEWED",
        "numerical_source": "Unknown model identity; market independence not established.",
        "market_comparison_role": "Downstream quotes are benchmarks or contract thresholds; changing a line changes the event being priced.",
        "simulation_independence": "NOT_CERTIFIED",
        "predictive_validation": "NOT_ASSESSED", "action_authority": False,
        "audit_reference": "docs/SELECTED_MARKET_INDEPENDENCE.md",
    }
    if row.get("forecast_status") != "FORECAST_GENERATED":
        result["path_class"] = "NO_FORECAST"
        return result
    market_ids = {"nfl.market_ensemble.v1.research", "nfl.live_state_hgb.v1.research"}
    if declared is True or (league.lower() == "nfl" and mid in market_ids):
        result.update(path_class="MARKET_INFORMED",
            numerical_source="Explicit market blend or pregame market prior; not an independent model-versus-market estimate.",
            simulation_independence="MARKET_DEPENDENT_BY_DESIGN")
        if mid == "nfl.market_ensemble.v1.research":
            result["source_path"] = "models/nfl/modes/runtime.py:enhanced -> models/nfl/modes/core.py:ensemble"
            result["football_weights_reported"] = {
                target: term.get("football_weight") for target, term in
                (diagnostics.get("contribution_trace") or {}).items() if isinstance(term, dict)}
        elif mid == "nfl.live_state_hgb.v1.research":
            result["source_path"] = "models/nfl/modes/runtime.py:live -> models/nfl/modes/core.py:state_features"
        return result
    profile = PATHS.get(mid)
    if profile and profile[0] == league.lower():
        result.update(path_class="REVIEWED_NONMARKET_FEATURE_PATH", source_path=profile[1],
            numerical_source=profile[2], product_scope=profile[3],
            simulation_independence="SEPARATE_MARKET_SIDECAR_INVARIANT; EMBEDDED_PAYLOAD_SEED_EXCEPTION_OPEN",
            limitation="Event/package metadata participates in RNG identity. Embedded market fields can change retained draws without changing fitted heads; reporting flags do not certify independence.")
        if row.get("identity_semantics") == "market_blind_numeric.v2":
            result.update(
                simulation_independence="MARKET_BLIND_NUMERIC_V2_DECLARED; RECEIPT_VERIFICATION_REQUIRED",
                limitation="This row declares the separate numeric-v2 procedure introduced after the legacy seed audit. The embedded-payload counterexample remains a legacy.v1 finding; this display does not authenticate the numerical receipt or grant predictive qualification.",
                identity_source_path="pipelines/cards/semantic_identity.py")
    return copy.deepcopy(result)
