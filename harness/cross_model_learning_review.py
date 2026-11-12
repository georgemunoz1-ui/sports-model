"""Opt-in, non-authorizing cross-model learning review.

The Nov 11, 2026 bounded outcome review motivated these *evaluation* controls.
This module does not fit, recalibrate, select a live wager, mutate a frozen
forecast, or populate the canonical grader. Sport-specific native probabilities
and settlement rules remain authoritative and must be supplied as inputs.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math

SCHEMA = "sports.cross_model_learning_review.v1"
LEAGUES = frozenset({"NFL", "CFB", "NBA", "WNBA", "MLB", "NHL", "MLS", "CBB"})
PRODUCTS = frozenset({"MONEYLINE", "SPREAD", "PUCK_LINE", "RUN_LINE", "TOTAL", "THREE_WAY"})
NO_ACTION = "NO_PICK"

# Default presentation policy, not a statement that a league/product forecast exists.
DECISION_VIEW_PRODUCTS = frozenset({"MONEYLINE", "SPREAD", "PUCK_LINE", "RUN_LINE"})
RESEARCH_ONLY_PRODUCTS = frozenset({"TOTAL", "THREE_WAY"})

# These flags call for an explicit arm-level review; they do NOT impute features,
# prohibit grading a valid frozen forecast or make a new numerical prediction.
LEAGUE_REVIEW_QUEUES = {
    "NFL": ("QB_IDENTITY_AND_ACTIVES_AT_CUTOFF", "MISSINGNESS_REPORT_SUPPORT", "MARGIN_HEAD_SEPARATION"),
    "CFB": ("FBS_POPULATION_AND_TIME_CUTOFF", "MARGIN_SUPPORT_AND_INTEGER_PUSH", "TOTAL_ARM_CAPABILITY"),
    "NBA": ("PLAYER_STATUS_PUBLISHED_VS_CONSUMED", "SCORE_CENTER_AND_PROPER_BRIER"),
    "WNBA": ("SEASON_AND_POSTSEASON_SCOPE", "PLAYER_AVAILABILITY_CHRONOLOGY"),
    "MLB": ("PROBABLE_STARTER_AND_BULLPEN_STATE", "EXTRA_INNINGS_SETTLEMENT_SUPPORT"),
    "NHL": ("CONFIRMED_GOALIE_AT_CUTOFF", "OT_SHOOTOUT_PLUS_ONE_AND_PUCK_LINE_LAW"),
    "MLS": ("REGULATION_THREE_WAY_DRAW_PROBABILITY", "EXTRA_TIME_AND_QUARTER_LINE_SCOPE"),
    "CBB": ("D1_PAIR_IDENTITY", "EXTREME_UNDERDOG_COVER_CALIBRATION", "CENTER_VS_SCALE_CHALLENGER"),
}


class ReviewError(ValueError):
    """Invalid or unsupported research observation; refuse rather than substitute."""


def _utc(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ReviewError(f"{field}: UTC offset timestamp required")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewError(f"{field}: invalid timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ReviewError(f"{field}: timezone offset required")
    return dt.astimezone(timezone.utc)


def _prob(value, field):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ReviewError(f"{field}: finite probability required")
    p = float(value)
    if not math.isfinite(p) or not 0 <= p <= 1:
        raise ReviewError(f"{field}: probability outside [0,1]")
    return p


def _numeric(value, field):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(float(value)):
        raise ReviewError(f"{field}: finite number required")
    return float(value)


def purchase_probability(price):
    """The purchase hurdle is distinct from paired *no-vig* probability."""
    if isinstance(price, bool) or not isinstance(price, int) or -100 < price < 100:
        raise ReviewError("American odds must be an integer >=+100 or <=-100")
    if price == -100:
        return 0.5
    return 100 / (price + 100) if price > 0 else abs(price) / (abs(price) + 100)


def payout_per_unit(price):
    purchase_probability(price)
    return (price / 100) if price > 0 else (100 / abs(price))


def expected_return(p_win, p_push, price):
    w = _prob(p_win, "p_win")
    u = _prob(p_push, "p_push")
    if w + u > 1 + 1e-10:
        raise ReviewError("win+push exceeds one")
    return w * payout_per_unit(price) - max(0.0, 1.0 - w - u)


def paired_novig(price, opposite_price):
    """Only a *verified matching quote pair* may invoke this function.

    Authentication and time/settlement matching are done by the caller. The
    numbers alone cannot prove a book offered both sides at the same time.
    """
    a = purchase_probability(price)
    b = purchase_probability(opposite_price)
    return a / (a + b)


def preferred_side(sides):
    """Pick highest *unconditional* win probability before examining prices.

    A tie is an abstention; do not infer preferred side from price. Supply a
    complete law to compare candidate sides; a single quoted side is insufficient.
    """
    if not isinstance(sides, dict) or len(sides) < 2:
        raise ReviewError("preferred_side requires at least two model outcomes")
    pairs = [(str(k), _prob(v, f"sides.{k}")) for k, v in sides.items()]
    mx = max(v for _, v in pairs)
    choices = [k for k, v in pairs if v == mx]
    return choices[0] if len(choices) == 1 else None


def personnel_asof(observations, forecast_cutoff_utc, *, transform_fitted=False):
    """Return last *available at cutoff* observed state, never an invented effect.

    Publication and retrieval must each precede cutoff. Outcome-only/DNP and
    in-game retrospective observations do not turn prior PROBABLE into OUT.
    A future fitted personnel increment must live under a separately identified
    model; this review deliberately returns numerical_delta=None in all cases.
    """
    cutoff = _utc(forecast_cutoff_utc, "forecast_cutoff_utc")
    eligible = []
    for x in observations:
        if x.get("kind") in {"POSTGAME_DNP", "IN_GAME_EVENT"}:
            continue
        try:
            published = _utc(x["published_at_utc"], "published_at_utc")
            retrieved = _utc(x["retrieved_at_utc"], "retrieved_at_utc")
        except (KeyError, ReviewError):
            continue
        if published <= cutoff and retrieved <= cutoff:
            eligible.append((published, retrieved, x))
    if not eligible:
        return {"state": "UNAVAILABLE_AT_CUTOFF", "numerical_delta": None, "feature_used": False}
    source = sorted(eligible, key=lambda v: (v[0], v[1]))[-1][2]
    state = source.get("state")
    if state not in {"OUT", "DOUBTFUL", "QUESTIONABLE", "PROBABLE", "ACTIVE", "VERIFIED_CLEAR"}:
        raise ReviewError("unknown personnel state")
    return {
        "state": state,
        "numerical_delta": None,
        "feature_used": False,
        "numeric_status": "FIT_AND_POINT_IN_TIME_TRANSFORM_NOT_EXECUTED" if transform_fitted
                          else "NO_FITTED_PERSONNEL_TRANSFORM",
    }


def audit_observation(row):
    """Evaluate one source-bound research contract; never authorize an action.

    Required row properties are supplied by an actual frozen research issuer, not
    produced by this function. Missing provenance results in explicit HOLD flags.
    """
    if not isinstance(row, dict):
        raise ReviewError("observation must be an object")
    league = row.get("league")
    product = row.get("product")
    if league not in LEAGUES:
        raise ReviewError(f"unsupported league: {league!r}")
    if product not in PRODUCTS:
        raise ReviewError(f"unsupported product: {product!r}")
    if product == "THREE_WAY" and league != "MLS":
        raise ReviewError("three-way regulation outcome requires explicit MLS scope")
    if league == "MLS" and product == "MONEYLINE" and row.get("draw_mode") != "TWO_WAY_CONTRACT_EXPLICIT":
        raise ReviewError("MLS regulation 1X2 cannot be graded as binary moneyline")
    if not row.get("event_id") or not row.get("model_id") or not row.get("arm_id"):
        raise ReviewError("event/model/arm identity required")
    if row.get("action_authority") is not False or row.get("stake_units", 0) != 0:
        raise ReviewError("research review cannot carry wagering authority or stake")
    cutoff = _utc(row.get("forecast_cutoff_utc"), "forecast_cutoff_utc")
    start = _utc(row.get("start_time_utc"), "start_time_utc")
    if cutoff >= start:
        raise ReviewError("forecast information cutoff must precede scheduled start")
    issued_at = row.get("forecast_issued_at_utc")
    if issued_at is not None:
        issued = _utc(issued_at, "forecast_issued_at_utc")
        if issued < cutoff or issued >= start:
            raise ReviewError("forecast issuance must follow cutoff and precede event start")
    # Recorded registration may be absent or self-declared. A timestamp alone
    # is NOT an independent prospective-registration receipt.
    registered = row.get("protocol_registered_at_utc")
    reg = _utc(registered, "protocol_registered_at_utc") if registered else None
    prestart_procedure = bool(reg and reg <= cutoff)
    threeway = product == "THREE_WAY"
    probs = None
    if threeway:
        probs = row.get("three_way_probabilities")
        if not isinstance(probs, dict) or set(probs) != {"HOME", "DRAW", "AWAY"}:
            raise ReviewError("MLS 1X2 requires HOME/DRAW/AWAY probability vector")
        probs = {k: _prob(v, f"three_way_probabilities.{k}") for k, v in probs.items()}
        if abs(sum(probs.values()) - 1.0) > 1e-8:
            raise ReviewError("MLS 1X2 vector must sum to one")
        if row.get("selected_outcome") not in probs:
            raise ReviewError("MLS 1X2 must bind selected HOME/DRAW/AWAY outcome")
        p = probs[row["selected_outcome"]]
        push = 0.0
    else:
        p = _prob(row.get("model_p_win"), "model_p_win")
        push = _prob(row.get("model_p_push", 0.0), "model_p_push")
    if p + push > 1 + 1e-10:
        raise ReviewError("model win/push/loss masses inconsistent")
    sim = row.get("sim_p_win")
    sim_p = _prob(sim, "sim_p_win") if sim is not None else None
    # Simulation is the same law; do not blend it or call its difference market edge.
    diff_pp = (sim_p - p) * 100 if sim_p is not None else None
    nsim = row.get("simulation_draws")
    if nsim is not None and (isinstance(nsim, bool) or not isinstance(nsim, int) or nsim < 1):
        raise ReviewError("simulation_draws must be a positive integer")
    se_pp = (100 * math.sqrt(p * (1-p) / nsim)) if nsim is not None else None
    quote = row.get("quote")
    quote_status = "NO_QUOTE"
    ev = hurdle = no_vig = value_gap_pp = None
    if quote is not None:
        if not isinstance(quote, dict):
            raise ReviewError("quote must be an object")
        price = quote.get("american")
        hurdle = purchase_probability(price)
        ev = expected_return(p, push, price)
        retrieved = _utc(quote.get("retrieved_at_utc"), "quote.retrieved_at_utc")
        asof_text = quote.get("provider_asof_utc")
        asof = _utc(asof_text, "quote.provider_asof_utc") if asof_text else None
        # The observation can still be displayed after seal, but cannot be
        # backdated to justify at-cutoff model/price comparison.
        quote_status = ("AT_CUTOFF_SOURCE_DECLARED_UNVERIFIED" if asof is not None and asof <= cutoff
                        and retrieved <= cutoff else
                        "POST_SEAL_COMPARISON_ONLY" if retrieved > cutoff else
                        "PROVIDER_ASOF_NOT_ESTABLISHED")
        pair = quote.get("matching_opposite")
        if product == "THREE_WAY" and pair is not None:
            raise ReviewError("MLS regulation 1X2 needs all three market prices; a two-side no-vig pair is invalid")
        if pair is not None:
            if (not isinstance(pair, dict) or not quote.get("book") or
                not quote.get("event_id") or quote.get("event_id") != row["event_id"] or
                pair.get("event_id") != row["event_id"] or
                pair.get("book") != quote.get("book") or
                pair.get("market_key") != quote.get("market_key") or
                pair.get("period") != quote.get("period") or
                not quote.get("side") or not pair.get("side") or
                pair.get("side") == quote.get("side") or
                pair.get("retrieved_at_utc") != quote.get("retrieved_at_utc") or
                pair.get("provider_asof_utc") != quote.get("provider_asof_utc")):
                raise ReviewError("no-vig requires exactly paired same-event/line/provider market vintage")
            line_a, line_b = quote.get("line"), pair.get("line")
            if product in {"SPREAD", "PUCK_LINE", "RUN_LINE"}:
                a = _numeric(line_a, "quote.line")
                b = _numeric(line_b, "pair.line")
                if abs(a + b) > 1e-9:
                    raise ReviewError("no-vig requires complementary signed handicaps")
            elif line_a != line_b:
                raise ReviewError("no-vig requires an identical ML/total threshold")
            no_vig = paired_novig(price, pair.get("american"))
            # Two quoted decisive sides condition out a refund. A native three-
            # outcome grade must keep the push mass separately.
            value_gap_pp = (p / (1-push) - no_vig) * 100 if push < 1 else None
    if row.get("product_supported") is not True:
        product_state = "PRODUCT_SUPPORT_NOT_VERIFIED"
    else:
        product_state = "PRODUCT_SCOPE_DECLARED_RESEARCH_ONLY"
    result = row.get("observed_result")
    allowed_results = ({None, "HOME", "DRAW", "AWAY"} if threeway
                       else {None, "WIN", "LOSS", "PUSH", "VOID"})
    if result not in allowed_results:
        raise ReviewError("unsupported settlement status; halves require native settlement engine")
    if result == "PUSH" and product == "MONEYLINE":
        raise ReviewError("moneyline push requires separately supported native contract")
    threeway_brier = None
    settlement_brier = None
    decisive_brier = None
    market_brier = None
    if result is None or result == "VOID":
        brier = pnl = None
    elif threeway:
        brier = None  # MLS 1X2 uses its own three-outcome proper score.
        threeway_brier = sum((prob - float(outcome == result)) ** 2
                             for outcome, prob in probs.items())
        won = result == row["selected_outcome"]
        pnl = (payout_per_unit(quote["american"]) if won else -1.0) if quote else None
    elif result == "PUSH":
        brier = None
        settlement_brier = p*p + (push-1)**2 + (1-p-push)**2
        pnl = 0.0
    else:
        y = 1.0 if result == "WIN" else 0.0
        brier = (p-y)**2 if push == 0 else None
        if push > 0:
            targets = (1.0, 0.0, 0.0) if result == "WIN" else (0.0, 0.0, 1.0)
            settlement_brier = sum((a-b)**2 for a,b in zip((p,push,1-p-push),targets))
        decisive_brier = ((p/(1-push))-y)**2 if push < 1 else None
        market_brier = (no_vig-y)**2 if decisive_brier is not None and no_vig is not None else None
        pnl = (payout_per_unit(quote["american"]) if result == "WIN" else -1.0) if quote else None
    grade_type = ("NOT_GRADED" if result is None else
                  "RESEARCH_ONLY_SOURCE_HASH_ABSENT" if not row.get("final_source_sha256") else
                  "RESEARCH_ONLY_HASH_DECLARED_NOT_INDEPENDENTLY_VERIFIED")
    warnings = []
    if not prestart_procedure:
        warnings.append("POLICY_NOT_PROSPECTIVELY_REGISTERED")
    else:
        warnings.append("POLICY_TIMESTAMP_ONLY_INDEPENDENT_RECEIPT_UNVERIFIED")
    if not row.get("final_source_sha256") and result is not None:
        warnings.append("FINAL_SOURCE_HASH_ABSENT")
    if product_state == "PRODUCT_SUPPORT_NOT_VERIFIED":
        warnings.append(product_state)
    if product in RESEARCH_ONLY_PRODUCTS:
        warnings.append("NON_DECISION_FACING_PRODUCT")
    if result == "PUSH" and push == 0:
        warnings.append("OBSERVED_PUSH_OUTSIDE_FROZEN_SUPPORT")
    if league == "CBB" and product == "SPREAD" and p >= .90 and quote is None:
        warnings.append("CBB_EXTREME_UNPRICED_TAIL_MONITOR")
    if row.get("personnel_source_consumed") is False:
        warnings.append("PERSONNEL_EVIDENCE_NOT_NUMERICALLY_CONSUMED")
    warnings.append("QUOTE_NOT_INDEPENDENTLY_PROVEN_AT_CUTOFF")
    if len(row.get("red_flags", [])) >= 2:
        warnings.append("RED_FLAG_GATE_PASS")
    # No research artifact is authorized; future release requires separate gates.
    return {
        "schema": SCHEMA,
        "event_id": row["event_id"], "league": league, "model_id": row["model_id"],
        "arm_id": row["arm_id"], "product": product,
        "model_p_win": p, "model_p_push": push, "model_p_loss": max(0,1-p-push),
        "sim_p_win": sim_p, "sim_minus_model_pp": diff_pp,
        "monte_carlo_se_pp": se_pp,
        "quote_status": quote_status, "purchase_break_even": hurdle,
        "paper_ev_per_unit": ev, "paired_market_no_vig_decisive": no_vig,
        "model_minus_market_decisive_pp": value_gap_pp,
        "grade_status": grade_type, "binary_brier": brier,
        "settlement_three_class_brier": settlement_brier,
        "conditional_decisive_brier": decisive_brier,
        "paired_market_decisive_brier": market_brier,
        "three_way_brier": threeway_brier, "selected_outcome": row.get("selected_outcome"),
        "paper_realized_units": pnl, "observed_result": result,
        "policy_prestart_chronology_consistent": prestart_procedure,
        "prospective_policy_registration_proven": False,
        "product_state": product_state, "review_queue": LEAGUE_REVIEW_QUEUES[league],
        "warnings": sorted(set(warnings)),
        "decision": NO_ACTION, "action_authority": False, "official_stake_units": 0.0,
    }


def cohort_summary(observations):
    """Model-arm/product groups, not a pooled multi-league calibration claim.

    Duplicate event/product rows within a grouped evaluation are refused to
    avoid counting both opposite sides or successive editions as new games.
    The number of distinct events across products is returned separately.
    """
    graded = [audit_observation(r) for r in observations]
    group = defaultdict(list)
    event_ids = set()
    for r in graded:
        event_ids.add((r["league"], r["event_id"]))
        key = (r["league"], r["model_id"], r["arm_id"], r["product"])
        group[key].append(r)
    summaries = []
    for key, rows in sorted(group.items()):
        ids = [r["event_id"] for r in rows]
        if len(set(ids)) != len(ids):
            raise ReviewError("duplicate event within league/model/arm/product cohort")
        settled = [r for r in rows if r["observed_result"] in {"WIN", "LOSS", "HOME", "DRAW", "AWAY"}]
        comparable = [r for r in settled if r["binary_brier"] is not None]
        paired = [r for r in settled if r["paired_market_decisive_brier"] is not None]
        threeway = [r for r in settled if r["three_way_brier"] is not None]
        summaries.append({
            "league": key[0], "model_id": key[1], "arm_id": key[2], "product": key[3],
            "events": len(rows), "observed_decisions": len(set(ids)),
            "settled_win_loss": len(settled),
            "wins": sum((r["observed_result"] == "WIN") or
                        (r["product"] == "THREE_WAY" and
                         r["observed_result"] == r["selected_outcome"])
                        for r in settled),
            "mean_binary_brier": (sum(r["binary_brier"] for r in comparable) / len(comparable)
                                  if comparable else None),
            "mean_three_way_brier": (sum(r["three_way_brier"] for r in threeway) / len(threeway)
                                     if threeway else None),
            "market_paired_count": sum(r["paired_market_no_vig_decisive"] is not None for r in rows),
            "market_paired_settled_count": len(paired),
            "model_decisive_brier_on_market_pairs": (
                sum(r["conditional_decisive_brier"] for r in paired) / len(paired) if paired else None),
            "market_decisive_brier_on_market_pairs": (
                sum(r["paired_market_decisive_brier"] for r in paired) / len(paired) if paired else None),
            "official_units": 0.0, "predictive_qualification": "HOLD",
        })
    return {
        "schema": SCHEMA, "population": "BOUNDED_RESEARCH_NOT_CANONICAL",
        "unique_events": len(event_ids), "contract_rows": len(graded),
        "groups": summaries, "rows": graded,
        "official_units": 0.0, "wagering_authority": False,
    }
