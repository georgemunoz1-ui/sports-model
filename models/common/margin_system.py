"""Contract-aware margin analytics, adapters and reproducible research simulations.

The only orientation used internally is ``M = home score - away score``. A
``home_spread`` is the handicap ADDED to M. The matching away handicap is its
negative. Winner probabilities and every spread price come from the same PMF;
there is deliberately no inverse map from a winner-only probability to a margin.

These are software capabilities, not an assertion that a source, fit or historical
forecast has been independently certified. Adapters bind caller-supplied source
hashes and timestamps; they never manufacture prospective registration or authority.
"""
from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
from typing import Iterable

import numpy as np

from models.common import discrete_research as discrete

SCHEMA = "sports.margin_system.research.v1"
ORIENTATION = "HOME_MINUS_AWAY"
QUANTILES = (0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975)
MC_CONFIDENCE = 0.95
MC_Z = 1.959963984540054


def _margin(distribution):
    """Validate, without normalizing or repairing the supplied frozen PMF."""
    x, p = discrete.validate(distribution)
    if distribution["product"] != "margin":
        raise ValueError("MARGIN_DISTRIBUTION_REQUIRED")
    if not math.isclose(float(p.sum()), 1.0, rel_tol=0, abs_tol=1e-12):
        raise ValueError("PROBABILITY_MASS_INVALID")
    provenance = distribution["provenance"]
    if not isinstance(provenance, dict):
        raise ValueError("PROVENANCE_OBJECT_REQUIRED")
    if provenance.get("orientation", ORIENTATION) != ORIENTATION:
        raise ValueError("HOME_MINUS_AWAY_REQUIRED")
    return x, p


def from_discrete(distribution):
    """Accept a hash-verified discrete margin artifact, preserving its identity.

    Verification here means structural/hash verification. This does not certify
    its training provenance or whether the artifact existed before the event.
    """
    _margin(distribution)
    return copy.deepcopy(distribution)


def _integers(values: Iterable, label: str, *, nonnegative: bool = False):
    material = list(values)
    if not material:
        raise ValueError(label + "_NONEMPTY_REQUIRED")
    for value in material:
        value = discrete.finite(value)
        # Prevent integer casts from wrapping or losing precision. Sports scores
        # are tiny compared with this bound; imposing it costs no valid contract.
        if value != round(value) or abs(value) > 2**52:
            raise ValueError(label + "_EXACT_INTEGER_REQUIRED")
        if nonnegative and value < 0:
            raise ValueError(label + "_NONNEGATIVE_REQUIRED")
    return np.asarray(material, dtype=np.int64)


def _binding(*, event_id, cutoff, source_sha256, adapter):
    discrete.identity(event_id, "EVENT_ID")
    discrete.stamp(cutoff)
    discrete.source_hash(source_sha256)
    return {"event_id": event_id, "cutoff": cutoff,
            "source_sha256": source_sha256, "adapter": adapter,
            "orientation": ORIENTATION,
            "source_verification": "CALLER_SUPPLIED_BINDING_NOT_INDEPENDENT_ATTESTATION",
            "support_policy": "PRESERVE_ALL_SOURCE_STATES_OR_REJECT",
            "removed_illegal_support_mass": 0.0}


def from_joint_scores(home_scores, away_scores, *, league, settlement, model_id,
                     event_id, cutoff, source_sha256, weights=None):
    """Convert explicit paired integer scores into their exact margin marginal.

    With weights, each row is one weighted joint-score state. Without weights,
    rows are equally weighted empirical samples. A tied score in a no-tie final
    settlement is rejected, never silently dropped or reassigned to a winner.
    Input settlement must already include any applicable OT/shootout bookkeeping.
    """
    h = _integers(home_scores, "HOME_SCORE", nonnegative=True)
    a = _integers(away_scores, "AWAY_SCORE", nonnegative=True)
    if h.shape != a.shape:
        raise ValueError("PAIRED_SCORE_LENGTH_MISMATCH")
    empirical = weights is None
    w = np.ones(len(h)) if empirical else discrete.vector(weights)
    if w.shape != h.shape:
        raise ValueError("PAIRED_WEIGHT_LENGTH_MISMATCH")
    p = _binding(event_id=event_id, cutoff=cutoff, source_sha256=source_sha256,
                 adapter="EXPLICIT_INTEGER_JOINT_SCORES")
    p.update({"input_row_count": len(h), "joint_score_distribution": True,
              "distribution_kind": "EMPIRICAL_DRAWS" if empirical else "WEIGHTED_JOINT_STATES",
              "source_sampling_uncertainty": "NOT_ESTIMATED" if empirical else "SOURCE_DEPENDENT",
              "paired_scores_sha256": discrete.digest({"home": h.tolist(), "away": a.tolist(),
                                                        "weights": w.tolist()})})
    return discrete.make_distribution((h - a).tolist(), w.tolist(), league=league,
                                      product="margin", settlement=settlement,
                                      model_id=model_id, provenance=p)


def from_margin_draws(margins, *, league, settlement, model_id, event_id, cutoff,
                      source_sha256, orientation):
    """Build an empirical PMF only from supplied integer margin draws.

    Orientation is mandatory. Explicit AWAY_MINUS_HOME inputs are negated and
    recorded. No assumed spread scale or Gaussian winner inversion is supported.
    """
    x = _integers(margins, "MARGIN")
    if orientation not in {ORIENTATION, "AWAY_MINUS_HOME"}:
        raise ValueError("EXPLICIT_MARGIN_ORIENTATION_REQUIRED")
    canonical = x if orientation == ORIENTATION else -x
    p = _binding(event_id=event_id, cutoff=cutoff, source_sha256=source_sha256,
                 adapter="EXPLICIT_INTEGER_MARGIN_DRAWS")
    p.update({"input_row_count": len(x), "input_orientation": orientation,
              "distribution_kind": "EMPIRICAL_DRAWS", "joint_score_distribution": False,
              "source_sampling_uncertainty": "NOT_ESTIMATED",
              "source_margin_draw_sha256": hashlib.sha256(x.astype("<i8").tobytes()).hexdigest()})
    return discrete.make_distribution(canonical.tolist(), np.ones(len(x)).tolist(),
                                      league=league, product="margin", settlement=settlement,
                                      model_id=model_id, provenance=p)


def _quantile(x, p, probability):
    probability = discrete.finite(probability)
    if not 0 <= probability <= 1:
        raise ValueError("QUANTILE_PROBABILITY_INVALID")
    # Generalized inverse of the discrete CDF; never interpolate to an impossible
    # fractional score margin. Enforce the final endpoint against roundoff only.
    cumulative = np.cumsum(p)
    cumulative[-1] = 1.0
    index = min(int(np.searchsorted(cumulative, probability, side="left")), len(x) - 1)
    return int(x[index])


def quantile(distribution, probability):
    """Return the smallest supported integer whose CDF reaches probability."""
    x, p = _margin(distribution)
    return _quantile(x, p, probability)


def summarize(distribution):
    """Describe predictive uncertainty and coherent winner probabilities."""
    x, p = _margin(distribution)
    mean = float(x @ p)
    variance = float(((x - mean) ** 2) @ p)
    intervals = {}
    for nominal in (0.5, 0.8, 0.95):
        alpha = (1 - nominal) / 2
        lower, upper = _quantile(x, p, alpha), _quantile(x, p, 1 - alpha)
        intervals[str(int(nominal * 100))] = {
            "lower": lower, "upper": upper, "nominal_probability": nominal,
            "attained_probability": float(p[(x >= lower) & (x <= upper)].sum()),
            "method": "DISCRETE_EQUAL_TAIL_PREDICTION_INTERVAL"}
    provenance = distribution["provenance"]
    support_adjustments = {key: provenance.get(key) for key in (
        "removed_illegal_support_mass", "removed_zero_margin_mass_before_conditioning",
        "omitted_tail_probability_before_finite_renormalization")}
    limitations = ["RESEARCH_ONLY_NOT_PROVEN_CALIBRATION_OR_MARKET_SUPERIORITY"]
    for key, value in support_adjustments.items():
        if value is not None:
            value = discrete.finite(value)
            if not 0 <= value <= 1:
                raise ValueError("REMOVED_SUPPORT_MASS_INVALID")
            support_adjustments[key] = value
    if any((support_adjustments[key] or 0) > 0 for key in (
            "removed_illegal_support_mass", "removed_zero_margin_mass_before_conditioning")):
        limitations.append("UPSTREAM_ILLEGAL_SUPPORT_CONDITIONING_PRESENT")
    if (support_adjustments["omitted_tail_probability_before_finite_renormalization"] or 0) > 0:
        limitations.append("UPSTREAM_FINITE_TAIL_TRUNCATION_PRESENT")
    if provenance.get("distribution_kind") == "EMPIRICAL_DRAWS":
        limitations.append("SOURCE_SAMPLING_UNCERTAINTY_NOT_ESTIMATED_BY_RESIMULATION")
    return {"orientation": ORIENTATION, "mean_margin": mean,
            "median_margin": _quantile(x, p, 0.5),
            "mode_margins": x[p == p.max()].astype(int).tolist(),
            "standard_deviation": math.sqrt(max(variance, 0.0)),
            "mean_implied_home_spread": -mean,
            "median_implied_home_spread": -_quantile(x, p, 0.5),
            "spread_interpretation": "POINT_SUMMARIES_NOT_A_FITTED_MARKET_PRICE",
            "quantiles": {str(q): _quantile(x, p, q) for q in QUANTILES},
            "prediction_intervals": intervals,
            "winner": {"home_win": float(p[x > 0].sum()),
                       "draw": float(p[x == 0].sum()),
                       "away_win": float(p[x < 0].sum()),
                       "scope": distribution["settlement"],
                       "method": "SAME_MARGIN_PMF"},
            "support_min": int(x[0]), "support_max": int(x[-1]),
            "support_size": len(x),
            "upstream_removed_illegal_support_mass": support_adjustments["removed_illegal_support_mass"],
            "upstream_support_adjustments": support_adjustments,
            "upstream_support_policy": provenance.get("support_policy"),
            "support_interpretation": "FINITE_RETAINED_SUPPORT_NOT_INFINITE_SCORE_SUPPORT",
            "limitations": limitations}


def _fair_odds(states):
    # An Asian half-win profits on half of the unit; a half-loss loses half.
    # Refunded stakes produce zero profit. Do not use P(win)/(1-P(push)) for
    # quarter-line contracts, because that discards the half outcomes.
    win_stake = states["win"] + 0.5 * states["half_win"]
    loss_stake = states["loss"] + 0.5 * states["half_loss"]
    return {"decimal": 1 + loss_stake / win_stake if win_stake > 0 else None,
            "winning_stake_probability": win_stake,
            "losing_stake_probability": loss_stake,
            "interpretation": "MODEL_ZERO_EXPECTED_PROFIT_PRICE_NO_VIG_OR_COSTS"}


def cover_ladder(distribution, home_spreads):
    """Price exact matching handicap contracts with five settlement states.

    The line argument ALWAYS describes the home handicap. For example -3 is
    HOME -3 and AWAY +3. MLS -.25 splits into home 0 and home -.5 equally.
    A whole-number push remains a separate probability, never a loss or win.
    """
    _margin(distribution)
    lines = [discrete.finite(line) for line in home_spreads]
    if len(set(lines)) != len(lines):
        raise ValueError("DUPLICATE_HOME_SPREAD")
    rows = []
    for line in sorted(lines):
        home = discrete.price(distribution, line, "HOME")
        away = discrete.price(distribution, line, "AWAY")
        rows.append({"home_spread": line, "away_spread": -line,
                     "line_basis": "HOME_HANDICAP",
                     "side_handicaps": {"HOME": line, "AWAY": -line},
                     "home": home, "away": away,
                     "home_fair_odds": _fair_odds(home),
                     "away_fair_odds": _fair_odds(away),
                     "settlement": distribution["settlement"],
                     "formula": "HOME: sign(M + home_spread); AWAY: opposite"})
    return rows


def _estimate(mask):
    """Monte Carlo count/SE/Wilson interval conditional on this fixed PMF."""
    n = len(mask)
    k = int(np.count_nonzero(mask))
    p = k / n
    denom = 1 + MC_Z**2 / n
    centre = (p + MC_Z**2 / (2 * n)) / denom
    half = MC_Z * math.sqrt(p * (1 - p) / n + MC_Z**2 / (4 * n**2)) / denom
    return {"count": k, "probability": p,
            "mc_standard_error": math.sqrt(p * (1 - p) / n),
            "mc_confidence_interval": [max(0.0, centre - half), min(1.0, centre + half)]}


def simulate_margin(distribution, *, draws=100000, home_spreads=()):
    """Return actual retained draws and numerical-error diagnostics separately.

    Intervals here quantify random simulation error conditional on the supplied
    PMF; they are not prediction intervals or uncertainty in model calibration,
    training parameters, availability assumptions, or source empirical sampling.
    """
    _margin(distribution)
    ladder = cover_ladder(distribution, home_spreads)
    values, receipt = discrete.simulate(distribution, draws=draws)
    summaries = []
    unique, inverse = np.unique(values, return_inverse=True)
    for row in ladder:
        # Classify unique support once, then use that mapping for all 100K draws.
        states = np.asarray([discrete.outcome(int(value), league=distribution["league"],
                            product="margin", settlement=distribution["settlement"],
                            line=row["home_spread"], side="HOME") for value in unique])[inverse]
        home = {state: _estimate(states == state) for state in discrete.STATES}
        opposites = dict(zip(discrete.STATES, reversed(discrete.STATES)))
        away = {state: copy.deepcopy(home[opposites[state]]) for state in discrete.STATES}
        summaries.append({"home_spread": row["home_spread"], "away_spread": row["away_spread"],
                          "home": home, "away": away})
    mean = float(values.mean())
    mean_se = float(values.std(ddof=1) / math.sqrt(draws)) if draws > 1 else None
    receipt.update({"margin_system_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "distribution_sha256": distribution["distribution_sha256"]})
    return values, {"receipt": receipt, "mean_margin": mean,
                    "mean_margin_mc_standard_error": mean_se,
                    "winner": {"home_win": _estimate(values > 0), "draw": _estimate(values == 0),
                               "away_win": _estimate(values < 0)},
                    "cover_ladder": summaries,
                    "mc_confidence": MC_CONFIDENCE, "mc_interval_method": "WILSON_BINOMIAL_MARGINAL",
                    "uncertainty_kind": "NUMERICAL_MONTE_CARLO_ERROR_CONDITIONAL_ON_FIXED_PMF",
                    "limitations": ["NOT_PREDICTIVE_OR_PARAMETER_UNCERTAINTY",
                                    "INTERVALS_ARE_MARGINAL_NOT_SIMULTANEOUS_ACROSS_LADDER",
                                    "REPEATED_DRAWS_DO_NOT_ADD_OBSERVED_GAMES"]}


def build_margin_report(distribution, *, home_spreads=(), draws=100000):
    """Build a JSON-safe research report; replay is bound to the PMF and RNG.

    Call simulate_margin directly when retaining draw bytes alongside the report.
    """
    distribution = from_discrete(distribution)
    home_spreads = list(home_spreads)
    _, simulation = simulate_margin(distribution, draws=draws, home_spreads=home_spreads)
    report = {"schema": SCHEMA, "league": distribution["league"],
              "model_id": distribution["model_id"], "settlement": distribution["settlement"],
              "distribution_sha256": distribution["distribution_sha256"],
              "provenance": copy.deepcopy(distribution["provenance"]),
              "analytics": summarize(distribution),
              "cover_ladder": cover_ladder(distribution, home_spreads),
              "simulation": simulation,
              "status": "DIAGNOSTIC", "prospective_grade_eligible": False,
              "action_authority": False}
    report["report_sha256"] = discrete.digest(report)
    return report
