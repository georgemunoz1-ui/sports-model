"""Validation harness for the margin-distribution layer (models.common.margins).

RESEARCH-ONLY diagnostic module. No output of this module carries action
authority, mutates a frozen artifact, or promotes any model. All verdicts are
flags + statistics intended for human review under the repo's preregistration
governance (see docs/MARGIN_LAYER_PREREG.md).

Conventions (binding; mirrors repo governance style):
  * Chronological evaluation only. ``cover_calibration`` and
    ``paired_brier_vs_baseline`` REQUIRE input records sorted by kickoff time
    and raise ``ValueError('VALIDATION_REQUIRES_CHRONOLOGICAL_ORDER')``
    otherwise. The harness never re-sorts for you: order is part of the
    audit trail.
  * Pushes are excluded from Brier / log loss / reliability scoring and are
    reported separately with explicit denominators (n_scored vs n_push).
    Unconditional cover probabilities are divided by (1 - p_push) before
    scoring this conditional, non-push population. Explicit conditional
    probabilities are used as supplied; missing basis is rejected.
  * Block bootstrap by season-week (20,000 reps, pinned seed) mirrors the CFB
    prereg machinery (1000 games / 60 season-week blocks / Holm intervals).
  * Every flag emitted here is a *diagnostic heuristic*, not a promotion rule.

Record schema (list[dict]) consumed here:
    p_cover        float in [0, 1]  — predicted probability the *bet side*
                                       (see ``orientation``) covers the line.
    p_push         float in [0, 1]  — unconditional predicted push probability.
    probability_basis str          — UNCONDITIONAL or CONDITIONAL_ON_NO_PUSH.
    line           float            — home spread, signed convention
                                      (negative = home favored). Half-point
                                      lines cannot push; integer lines can.
    actual_margin  float            — home_score - away_score.
    orientation    'home' | 'away'  — which side ``p_cover`` refers to.
    sport          str              — e.g. 'nfl', 'cfb', 'mlb'.
    season         int|str          — season label (block-bootstrap unit part).
    week           int|str, optional — in-season week (block-bootstrap unit).
    date           str, optional    — ISO date; used when ``week`` absent.

This module codes against the models.common.margins contract but deliberately
does NOT import it: validation must remain runnable standalone so a broken
core-library change can never silently break the audit harness.
"""

from __future__ import annotations

import math
import numbers
from typing import Any, Iterable, Optional, Sequence

import numpy as np
from scipy import stats

# ---------------------------------------------------------------------------
# Constants (pinned; changing any of these invalidates prior audit outputs)
# ---------------------------------------------------------------------------

CHRONO_ERROR = "VALIDATION_REQUIRES_CHRONOLOGICAL_ORDER"

LOG_LOSS_EPS = 1e-7  # probability clip for log loss; pinned, do not tune

BOOTSTRAP_REPS = 20_000        # mirrors CFB prereg block-bootstrap count
BOOTSTRAP_SEED = 20261007      # pinned seed; determinism is required by tests
BOOTSTRAP_CI = 0.95

KEY_NUMBERS_FOOTBALL = (3, 6, 7, 10, 14, 17, 21)
KEY_NUMBER_EXCESS_FLAG_PP = 0.02  # total excess mass > 2pp -> flag (heuristic)

SIGMA_DRIFT_TOLERANCE = 0.15    # >15% recent-vs-fit sigma shift -> flag
SIGMA_RECENT_FRACTION = 0.25    # last 25% of chronological residuals = recent
SIGMA_MIN_N = 30                # below this, per-group sigmas are 'low_n'

DEFAULT_ABS_PRED_EDGES = (0.0, 3.0, 7.0, 10.0, 14.0, 21.0, math.inf)

REQUIRED_RECORD_FIELDS = (
    "p_cover",
    "p_push",
    "probability_basis",
    "line",
    "actual_margin",
    "orientation",
    "sport",
    "season",
)

__all__ = [
    "cover_calibration",
    "sigma_audit",
    "key_number_audit",
    "paired_brier_vs_baseline",
    "CHRONO_ERROR",
    "BOOTSTRAP_REPS",
    "BOOTSTRAP_SEED",
    "KEY_NUMBERS_FOOTBALL",
]


# ---------------------------------------------------------------------------
# Record parsing helpers
# ---------------------------------------------------------------------------

def _validate_record_schema(records: Sequence[dict]) -> None:
    if len(records) == 0:
        raise ValueError("VALIDATION_REQUIRES_NONEMPTY_RECORDS")
    for i, rec in enumerate(records):
        missing = [f for f in REQUIRED_RECORD_FIELDS if f not in rec]
        if missing:
            raise ValueError(
                f"RECORD_SCHEMA_MISSING_FIELDS index={i} missing={missing}"
            )
        if rec["orientation"] not in ("home", "away"):
            raise ValueError(
                f"RECORD_BAD_ORIENTATION index={i} "
                f"orientation={rec['orientation']!r}"
            )
        p = float(rec["p_cover"])
        if not (0.0 <= p <= 1.0):
            raise ValueError(f"RECORD_BAD_P_COVER index={i} p_cover={p!r}")
        push = float(rec["p_push"])
        if isinstance(rec["p_cover"], bool) or isinstance(rec["p_push"], bool) or not math.isfinite(push) or not 0 <= push <= 1:
            raise ValueError("RECORD_BAD_PROBABILITY_MASS")
        basis = rec["probability_basis"]
        if basis not in ("UNCONDITIONAL", "CONDITIONAL_ON_NO_PUSH"):
            raise ValueError("RECORD_PROBABILITY_BASIS_REQUIRED")
        if basis == "UNCONDITIONAL" and p + push > 1 + 1e-12:
            raise ValueError("RECORD_BAD_PROBABILITY_MASS")
        line, actual = float(rec["line"]), float(rec["actual_margin"])
        if not math.isfinite(line) or not (2 * line).is_integer() or not math.isfinite(actual):
            raise ValueError("RECORD_SETTLEMENT_UNSUPPORTED")
        if not line.is_integer() and push != 0:
            raise ValueError("RECORD_HALF_LINE_PUSH_MASS")
        if push == 1 and actual + line != 0:
            raise ValueError("RECORD_NONPUSH_CONDITION_UNDEFINED")


def _season_key(season) -> tuple:
    """Typed chronological key for a season label.

    Numeric seasons (int/float, incl. numpy scalars) compare NUMERICALLY:
    str(10) < str(9) lexicographically, so stringifying seasons silently
    inverts chronology for 1- vs 2-digit labels. String seasons compare
    lexicographically. The leading tag keeps mixed numeric/string labels
    deterministic (numeric sorts first) instead of raising TypeError.
    """
    if isinstance(season, bool):
        return (1, str(season))
    if isinstance(season, numbers.Real):
        return (0, float(season))
    return (1, str(season))


def _record_time_key(rec: dict) -> tuple:
    """Chronological sort key for one record.

    (season, week) when week is present, else (season, date). Mixed presence
    of week/date across records is rejected to keep ordering unambiguous.
    """
    season_key = _season_key(rec["season"])
    week = rec.get("week")
    date = rec.get("date")
    if week is not None:
        return (season_key, 0, float(week))
    if date is not None:
        return (season_key, 1, str(date))
    raise ValueError(
        "RECORD_REQUIRES_WEEK_OR_DATE: chronological audits need a "
        "'week' or 'date' field on every record"
    )


def _require_chronological(records: Sequence[dict]) -> None:
    keys = [_record_time_key(r) for r in records]
    kinds = {k[1] for k in keys}
    if len(kinds) > 1:
        raise ValueError(
            "RECORD_MIXED_TIME_FIELDS: cannot mix week-keyed and "
            "date-keyed records in one chronological audit"
        )
    for prev, cur in zip(keys, keys[1:]):
        if cur < prev:
            raise ValueError(CHRONO_ERROR)


def _cover_outcomes(records: Sequence[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Return (p_cover, y) for NON-PUSH games only, plus nothing else.

    y=1 means the bet side (per ``orientation``) covered, y=0 means it lost.
    Pushes (actual_margin + line == 0) are excluded here and counted by the
    caller. Floating tolerance is exact-zero: lines and margins in this repo
    are recorded in exact half-point increments, so equality is well defined.
    """
    ps, ys = [], []
    for rec in records:
        adjusted = float(rec["actual_margin"]) + float(rec["line"])  # home POV
        if adjusted == 0.0:
            continue  # push: excluded from scoring, reported separately
        home_covers = adjusted > 0.0
        bet_covers = home_covers if rec["orientation"] == "home" else not home_covers
        p = float(rec["p_cover"])
        if rec["probability_basis"] == "UNCONDITIONAL":
            p /= 1.0 - float(rec["p_push"])
        ps.append(p)
        ys.append(1.0 if bet_covers else 0.0)
    return np.asarray(ps, dtype=float), np.asarray(ys, dtype=float)


def _n_pushes(records: Sequence[dict]) -> int:
    return sum(
        1
        for rec in records
        if float(rec["actual_margin"]) + float(rec["line"]) == 0.0
    )


# ---------------------------------------------------------------------------
# 1. cover_calibration
# ---------------------------------------------------------------------------

def cover_calibration(records: list[dict]) -> dict:
    """Chronological calibration audit of cover probabilities.

    Returns a dict with:
      brier, log_loss           — scored on non-push games only
      n_total, n_push, n_scored — explicit denominators (brier_denominator ==
                                  n_scored; pushes never enter it)
      push_rate
      bias                      — mean(p_cover) - mean(observed cover), scored
      reliability               — 10 equal-width decile buckets over [0, 1],
                                  each {bucket, lo, hi, n, predicted_mean,
                                  observed_rate}; empty buckets have n=0 and
                                  NaN means (never silently dropped)
      calibration_slope         — n-weighted least-squares slope of
                                  observed_rate on predicted_mean across
                                  non-empty buckets (prereg gate: 0.9-1.1);
                                  NaN if fewer than 2 non-empty buckets
      warnings                  — list[str] of diagnostic flags

    Raises ValueError(VALIDATION_REQUIRES_CHRONOLOGICAL_ORDER) if the input
    timestamps are not nondecreasing. Input is never re-sorted.
    """
    _validate_record_schema(records)
    _require_chronological(records)

    n_total = len(records)
    n_push = _n_pushes(records)
    p, y = _cover_outcomes(records)
    n_scored = int(p.shape[0])

    warnings: list[str] = []
    if n_scored == 0:
        warnings.append("NO_SCORED_GAMES_ALL_PUSHES")
        return {
            "brier": math.nan,
            "log_loss": math.nan,
            "n_total": n_total,
            "n_push": n_push,
            "n_scored": 0,
            "brier_denominator": 0,
            "push_rate": 1.0,
            "bias": math.nan,
            "reliability": _empty_reliability_table(),
            "calibration_slope": math.nan,
            "warnings": warnings,
        }

    brier = float(np.mean((p - y) ** 2))
    p_clip = np.clip(p, LOG_LOSS_EPS, 1.0 - LOG_LOSS_EPS)
    log_loss = float(-np.mean(y * np.log(p_clip) + (1.0 - y) * np.log(1.0 - p_clip)))
    bias = float(np.mean(p) - np.mean(y))

    reliability = _reliability_table(p, y)
    slope = _calibration_slope(reliability)

    if n_scored < 50:
        # mirrors repo gate style: small samples are pipeline-validation only
        warnings.append("PIPELINE_VALIDATION_ONLY_UNDER_50")
    if abs(bias) > 0.05:
        warnings.append("COVER_BIAS_EXCEEDS_5PP")

    return {
        "brier": brier,
        "log_loss": log_loss,
        "n_total": n_total,
        "n_push": n_push,
        "n_scored": n_scored,
        "brier_denominator": n_scored,
        "push_rate": n_push / n_total,
        "bias": bias,
        "reliability": reliability,
        "calibration_slope": slope,
        "warnings": warnings,
    }


def _bucket_index(p: float) -> int:
    # [0.0,0.1) ... [0.8,0.9), [0.9,1.0]; p==1.0 lands in last bucket
    return min(int(p * 10.0), 9)


def _empty_reliability_table() -> list[dict]:
    return [
        {
            "bucket": b,
            "lo": b / 10.0,
            "hi": (b + 1) / 10.0,
            "n": 0,
            "predicted_mean": math.nan,
            "observed_rate": math.nan,
        }
        for b in range(10)
    ]


def _reliability_table(p: np.ndarray, y: np.ndarray) -> list[dict]:
    table = _empty_reliability_table()
    idx = np.array([_bucket_index(v) for v in p], dtype=int)
    for b in range(10):
        mask = idx == b
        n = int(mask.sum())
        if n == 0:
            continue
        table[b]["n"] = n
        table[b]["predicted_mean"] = float(np.mean(p[mask]))
        table[b]["observed_rate"] = float(np.mean(y[mask]))
    return table


def _calibration_slope(reliability: list[dict]) -> float:
    pts = [
        (row["predicted_mean"], row["observed_rate"], row["n"])
        for row in reliability
        if row["n"] > 0
    ]
    if len(pts) < 2:
        return math.nan
    x = np.array([t[0] for t in pts])
    obs = np.array([t[1] for t in pts])
    w = np.array([t[2] for t in pts], dtype=float)
    x_bar = float(np.sum(w * x) / np.sum(w))
    y_bar = float(np.sum(w * obs) / np.sum(w))
    var_x = float(np.sum(w * (x - x_bar) ** 2))
    if var_x <= 0.0:
        return math.nan
    cov = float(np.sum(w * (x - x_bar) * (obs - y_bar)))
    return cov / var_x


# ---------------------------------------------------------------------------
# 2. sigma_audit
# ---------------------------------------------------------------------------

def sigma_audit(
    pred: Sequence[float],
    actual: Sequence[float],
    sport: str,
    *,
    seasons: Optional[Sequence[Any]] = None,
    abs_pred_edges: Sequence[float] = DEFAULT_ABS_PRED_EDGES,
    recent_fraction: float = SIGMA_RECENT_FRACTION,
    drift_tolerance: float = SIGMA_DRIFT_TOLERANCE,
    min_n: int = SIGMA_MIN_N,
) -> dict:
    """Residual-sigma audit for one sport (never pooled across sports).

    ``pred`` / ``actual`` must be in chronological order (fit-window first,
    recent-window last); this mirrors the OOF-only sigma provenance rule in
    models.common.margins.estimate_sigma. ``seasons`` (optional) labels each
    observation for the per-season table.

    Sigma is the sample standard deviation (ddof=1) of residuals
    ``actual - pred``. Dispersion is reported overall, per season, and per
    |pred| bucket (edges default to football-ish spread bands but are
    configurable; dispersion growing with |pred| is expected, not a defect).

    Drift heuristic (DOCUMENTED HEURISTIC, NOT A PROMOTION RULE): the
    chronological tail (last ``recent_fraction`` of observations, default 25%)
    is the 'recent window'; the remainder is the 'fit window'. Flag
    'SIGMA_DRIFT' when |sigma_recent - sigma_fit| / sigma_fit >
    ``drift_tolerance`` (default 15%).
    """
    pred = np.asarray(pred, dtype=float)
    actual = np.asarray(actual, dtype=float)
    if pred.shape != actual.shape:
        raise ValueError("SIGMA_AUDIT_SHAPE_MISMATCH")
    if pred.ndim != 1 or pred.size < 2:
        raise ValueError("SIGMA_AUDIT_REQUIRES_AT_LEAST_2_OBSERVATIONS")
    if not (0.0 < recent_fraction < 1.0):
        raise ValueError("SIGMA_AUDIT_BAD_RECENT_FRACTION")

    resid = actual - pred
    n = resid.size
    warnings: list[str] = []
    flags: list[str] = []

    sigma_overall = float(np.std(resid, ddof=1))

    # --- by season -------------------------------------------------------
    by_season: dict[str, dict] = {}
    if seasons is None:
        warnings.append("SIGMA_AUDIT_NO_SEASON_LABELS")
    else:
        seasons_arr = np.asarray(list(seasons), dtype=object)
        if seasons_arr.shape[0] != n:
            raise ValueError("SIGMA_AUDIT_SEASONS_LENGTH_MISMATCH")
        for s in dict.fromkeys(seasons_arr.tolist()):  # stable order
            mask = seasons_arr == s
            by_season[str(s)] = _sigma_summary(resid[mask], min_n)

    # --- by |pred| bucket --------------------------------------------------
    edges = list(abs_pred_edges)
    if edges[0] != 0.0 or edges[-1] != math.inf or any(
        b <= a for a, b in zip(edges, edges[1:])
    ):
        raise ValueError("SIGMA_AUDIT_BAD_ABS_PRED_EDGES")
    abs_pred = np.abs(pred)
    by_abs_pred_bucket = []
    for lo, hi in zip(edges, edges[1:]):
        mask = (abs_pred >= lo) & (abs_pred < hi)
        entry = {"lo": float(lo), "hi": float(hi) if math.isfinite(hi) else None}
        entry.update(_sigma_summary(resid[mask], min_n))
        by_abs_pred_bucket.append(entry)

    # --- drift heuristic ---------------------------------------------------
    n_recent = max(2, int(round(n * recent_fraction)))
    n_fit = n - n_recent
    drift: dict[str, Any] = {"computable": False}
    if n_fit >= 2:
        sigma_fit = float(np.std(resid[:n_fit], ddof=1))
        sigma_recent = float(np.std(resid[n_fit:], ddof=1))
        rel_change = (
            (sigma_recent - sigma_fit) / sigma_fit if sigma_fit > 0.0 else math.nan
        )
        drift = {
            "computable": True,
            "n_fit": int(n_fit),
            "n_recent": int(n_recent),
            "sigma_fit": sigma_fit,
            "sigma_recent": sigma_recent,
            "relative_change": rel_change,
            "tolerance": drift_tolerance,
        }
        if math.isfinite(rel_change) and abs(rel_change) > drift_tolerance:
            flags.append("SIGMA_DRIFT")
    else:
        warnings.append("SIGMA_DRIFT_WINDOW_TOO_SMALL")

    if n < min_n:
        warnings.append("SIGMA_AUDIT_LOW_N")

    return {
        "sport": sport,
        "n": int(n),
        "sigma_overall": sigma_overall,
        "residual_mean": float(np.mean(resid)),
        "by_season": by_season,
        "by_abs_pred_bucket": by_abs_pred_bucket,
        "drift": drift,
        "flags": flags,
        "warnings": warnings,
    }


def _sigma_summary(resid: np.ndarray, min_n: int) -> dict:
    n = int(resid.size)
    out = {"n": n, "sigma": math.nan, "low_n": True}
    if n >= 2:
        out["sigma"] = float(np.std(resid, ddof=1))
        out["low_n"] = n < min_n
    return out


# ---------------------------------------------------------------------------
# 3. key_number_audit
# ---------------------------------------------------------------------------

def key_number_audit(
    margins: np.ndarray,
    key_numbers: Iterable[int] = KEY_NUMBERS_FOOTBALL,
    excess_flag_threshold: float = KEY_NUMBER_EXCESS_FLAG_PP,
) -> dict:
    """Empirical mass at football key numbers vs smooth-normal expectation.

    Key numbers apply to the *magnitude* of the margin, so all statistics use
    ``abs(margins)``. Expected mass at key k under a smooth normal fitted to
    the sample (mu = mean(|m|), sigma = std(|m|)) is the normal probability of
    the rounding bin [k - 0.5, k + 0.5].

    Returns per-key rows {key, empirical_mass, expected_mass, excess} plus
    ``total_excess_mass`` (sum of per-key excess). Flags
    'KEY_NUMBER_MASS_SIGNIFICANT' when total excess > 2pp (documented
    heuristic motivating discrete_football_margin; NOT a promotion rule).
    """
    margins = np.asarray(margins, dtype=float).ravel()
    if margins.size < 2:
        raise ValueError("KEY_NUMBER_AUDIT_REQUIRES_AT_LEAST_2_MARGINS")
    abs_m = np.abs(margins)
    n = abs_m.size

    mu = float(np.mean(abs_m))
    sigma = float(np.std(abs_m, ddof=1))
    if sigma <= 0.0:
        raise ValueError("KEY_NUMBER_AUDIT_DEGENERATE_ZERO_VARIANCE")

    rows = []
    total_excess = 0.0
    for k in key_numbers:
        k = int(k)
        empirical = float(np.mean(abs_m == k))
        expected = float(
            stats.norm.cdf((k + 0.5 - mu) / sigma)
            - stats.norm.cdf((k - 0.5 - mu) / sigma)
        )
        excess = empirical - expected
        total_excess += excess
        rows.append(
            {
                "key": k,
                "empirical_mass": empirical,
                "expected_mass": expected,
                "excess": excess,
            }
        )

    flags = []
    if total_excess > excess_flag_threshold:
        flags.append("KEY_NUMBER_MASS_SIGNIFICANT")

    return {
        "n": int(n),
        "mu_abs_margin": mu,
        "sigma_abs_margin": sigma,
        "table": rows,
        "total_excess_mass": float(total_excess),
        "excess_flag_threshold": excess_flag_threshold,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# 4. paired_brier_vs_baseline
# ---------------------------------------------------------------------------

def _block_keys(records: Sequence[dict]) -> np.ndarray:
    keys = []
    for rec in records:
        season = rec["season"]
        week = rec.get("week")
        date = rec.get("date")
        if week is not None:
            keys.append(f"{season}|w{week}")
        elif date is not None:
            keys.append(f"{season}|d{date}")
        else:
            raise ValueError(
                "RECORD_REQUIRES_WEEK_OR_DATE: block bootstrap needs a "
                "'week' or 'date' field on every record"
            )
    return np.asarray(keys, dtype=object)


def paired_brier_vs_baseline(
    records: list[dict],
    baseline: str = "fifty_fifty",
    *,
    reps: int = BOOTSTRAP_REPS,
    seed: int = BOOTSTRAP_SEED,
    ci: float = BOOTSTRAP_CI,
) -> dict:
    """Block-bootstrap CI of the paired Brier difference vs a baseline.

    Per-game paired difference: d_i = (p_i - y_i)^2 - (b_i - y_i)^2, scored
    on non-push games only (pushes excluded, reported separately). Negative
    mean difference = model better than baseline.

    baseline='fifty_fifty': b_i = 0.5 for every scored game (the
    '0.5-minus-push' baseline: coin-flip on decided games, abstains on
    pushes by construction since pushes are excluded for both sides).

    Resampling unit is the season-week block (season-date when only dates
    exist), resampled with replacement; mirrors the repo's CFB prereg
    machinery. Default 20,000 reps with a pinned seed — identical inputs
    MUST produce identical CIs (tested).

    Requires chronological input (same enforcement as cover_calibration).
    """
    if baseline != "fifty_fifty":
        raise ValueError(f"UNKNOWN_BASELINE {baseline!r}")
    _validate_record_schema(records)
    _require_chronological(records)

    n_total = len(records)
    n_push = _n_pushes(records)
    p, y = _cover_outcomes(records)
    n_scored = int(p.shape[0])
    if n_scored == 0:
        raise ValueError("BOOTSTRAP_REQUIRES_SCORED_GAMES")

    # keep only scored records' block labels, aligned with p/y
    scored_blocks = np.asarray(
        [
            key
            for key, rec in zip(_block_keys(records), records)
            if float(rec["actual_margin"]) + float(rec["line"]) != 0.0
        ],
        dtype=object,
    )

    d = (p - y) ** 2 - (0.5 - y) ** 2  # paired per-game Brier difference
    diff_mean = float(np.mean(d))
    model_brier = float(np.mean((p - y) ** 2))
    baseline_brier = float(np.mean((0.5 - y) ** 2))

    # aggregate per block, then resample block indices (vectorized)
    uniq, inverse = np.unique(scored_blocks, return_inverse=True)
    n_blocks = int(uniq.size)
    block_sum = np.zeros(n_blocks)
    block_cnt = np.zeros(n_blocks)
    np.add.at(block_sum, inverse, d)
    np.add.at(block_cnt, inverse, 1.0)

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n_blocks, size=(reps, n_blocks))
    boot_sum = block_sum[idx].sum(axis=1)
    boot_cnt = block_cnt[idx].sum(axis=1)
    boot_diff = boot_sum / boot_cnt

    alpha = 1.0 - ci
    lo = float(np.quantile(boot_diff, alpha / 2.0))
    hi = float(np.quantile(boot_diff, 1.0 - alpha / 2.0))

    warnings: list[str] = []
    if n_blocks < 60:
        # mirrors CFB prereg minimum of 60 season-week blocks
        warnings.append("BLOCK_BOOTSTRAP_UNDER_60_BLOCKS_PIPELINE_ONLY")

    return {
        "baseline": baseline,
        "diff_mean": diff_mean,  # negative => model better
        "ci_level": ci,
        "ci_lower": lo,
        "ci_upper": hi,
        "ci_excludes_zero": bool(lo > 0.0 or hi < 0.0),
        "model_better": bool(hi < 0.0),
        "model_brier": model_brier,
        "baseline_brier": baseline_brier,
        "n_total": n_total,
        "n_push": n_push,
        "n_scored": n_scored,
        "brier_denominator": n_scored,
        "n_blocks": n_blocks,
        "reps": int(reps),
        "seed": int(seed),
        "warnings": warnings,
    }
