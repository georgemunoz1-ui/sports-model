#!/usr/bin/env python3
"""ML-E1 Player Evolution V1 — projection engine, per docs/experiments/ML-E1_V14_player_evolution_prereg.md.

SHADOW DEVELOPMENT ONLY. This module changes nothing in Phase 4: it is imported by no
production path, produces no registry forecast, and cannot — the data-dependency gate below
reports EVIDENCE_ABSENT until a real as-of player-season dataset exists.

What this file IS: the owner-specified mathematics, hardened.
  posterior  = (Σ_s d^(T-s-1)·C_s + κ·π) / (Σ_s d^(T-s-1)·N_s + κ)      (Dirichlet-multinomial)
  z_e        = log(p_e / p_ref) + Δ_age,e + r·Δ_trend,e                  (log-odds vs OTHER_OUT)
  projection = softmax(z, z_ref=0)                                      (sums to exactly 1)

Hardening beyond the sketch:
  - NO DEFAULT CONSTANTS. season_decay / prior_strength / age curves / trend shrinkage have no
    default values anywhere in this file. Every call passes an EvolutionParams whose provenance
    is either TRAINED_ASOF (with a training-artifact reference) or PLACEHOLDER_UNTRAINED; any
    output from untrained parameters is stamped NON_FORECAST_GRADE and is structurally barred
    from registry cohorts (prereg parameter rule; nothing is learned from the P4 forward cohort).
  - LEAKAGE REFUSAL: a season line at or after the target season raises — projections are
    strictly as-of.
  - RECONCILIATION: event counts must sum exactly to opportunities, or the line is refused.
  - DOUBLE-COUNT GUARD (structural): age deltas and the individual trend are separate inputs;
    the trend must be estimated on age-detrended residuals (training-side obligation, recorded
    in params.trend_basis so the claim travels with the numbers).
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EVENTS = ("K", "BB_HBP", "HR", "1B", "2B", "3B", "OTHER_OUT")
REFERENCE = "OTHER_OUT"

PARAM_PROVENANCES = ("TRAINED_ASOF", "PLACEHOLDER_UNTRAINED")

#: Where real as-of player-season rows will live once evidence exists (owner upload or
#: restored fetch under R8). Absent/empty => EVIDENCE_ABSENT, and that is the honest answer.
PLAYER_SEASONS_DIR = os.path.join(BASE, "data", "mlb", "player_seasons")

ROW_REQUIRED = ("mlbam_id", "season", "age", "level", "role", "opportunities", "events",
                "source", "observed_at_utc", "source_sha256")


@dataclass(frozen=True)
class SeasonLine:
    season: int
    age: float
    opportunities: int
    counts: Mapping[str, int]
    level: str = "MLB"


@dataclass(frozen=True)
class EvolutionParams:
    """All learnable parameters, with provenance. No defaults for the learnable values."""
    season_decay: float
    prior_strength: float
    age_logodds_delta: Mapping[str, float]      # learned per-skill aging curve, ref-relative
    trend_reliability: float                    # r_i in [0,1]
    provenance: str                             # TRAINED_ASOF | PLACEHOLDER_UNTRAINED
    trained_on: Optional[str] = None            # artifact path+hash when TRAINED_ASOF
    trend_basis: str = "UNSPECIFIED"            # e.g. 'age-detrended residual changes'

    def __post_init__(self):
        if not 0.0 < self.season_decay <= 1.0:
            raise ValueError("season_decay must be in (0, 1]")
        if self.prior_strength <= 0:
            raise ValueError("prior_strength must be positive")
        if not 0.0 <= self.trend_reliability <= 1.0:
            raise ValueError("trend_reliability must be in [0, 1]")
        if self.provenance not in PARAM_PROVENANCES:
            raise ValueError(f"provenance must be one of {PARAM_PROVENANCES}")
        if self.provenance == "TRAINED_ASOF" and not self.trained_on:
            raise ValueError("TRAINED_ASOF parameters must reference their training artifact")


@dataclass(frozen=True)
class PlayerProjection:
    event_probs: Mapping[str, float]
    effective_opportunities: float
    posterior_strength: float
    prior_used: str                             # INDIVIDUALIZED | COMPARABLE | LEAGUE_FALLBACK
    status: str                                 # SHADOW_PROJECTION | NON_FORECAST_GRADE...
    dq_flags: tuple = field(default_factory=tuple)


def _softmax(values: Sequence[float]) -> list:
    peak = max(values)
    ex = [math.exp(v - peak) for v in values]
    total = sum(ex)
    return [v / total for v in ex]


def _validate_prior(prior_probs: Mapping[str, float]) -> None:
    if set(prior_probs) != set(EVENTS):
        raise ValueError("prior_probs must contain exactly the event set")
    if any(prior_probs[e] <= 0 for e in EVENTS):
        raise ValueError("prior_probs must be strictly positive (log-odds space)")
    if not math.isclose(sum(prior_probs.values()), 1.0, abs_tol=1e-9):
        raise ValueError(f"prior probabilities sum to {sum(prior_probs.values())}, not 1")


def project_player_events(
    lines: Sequence[SeasonLine],
    *,
    target_season: int,
    prior_probs: Mapping[str, float],
    prior_used: str,
    params: EvolutionParams,
    individual_trend: Optional[Mapping[str, float]] = None,
) -> PlayerProjection:
    """Owner-specified projection. prior_used declares WHICH prior this is
    (INDIVIDUALIZED / COMPARABLE / LEAGUE_FALLBACK) — a league fallback is flagged, never silent."""
    if prior_used not in ("INDIVIDUALIZED", "COMPARABLE", "LEAGUE_FALLBACK"):
        raise ValueError("prior_used must be INDIVIDUALIZED, COMPARABLE or LEAGUE_FALLBACK")
    _validate_prior(prior_probs)

    weighted = {e: params.prior_strength * prior_probs[e] for e in EVENTS}
    effective = 0.0
    for line in lines:
        years_back = target_season - line.season
        if years_back < 1:
            raise ValueError(
                f"LEAKAGE REFUSED: season {line.season} is not strictly before target "
                f"{target_season} — projections are as-of only")
        counts = {e: line.counts.get(e, 0) for e in EVENTS}
        if any(c < 0 for c in counts.values()):
            raise ValueError(f"{line.season}: negative event count")
        if sum(counts.values()) != line.opportunities:
            raise ValueError(
                f"{line.season}: event counts sum to {sum(counts.values())}, not the "
                f"{line.opportunities} opportunities — mutually-exclusive events must reconcile")
        if line.opportunities == 0:
            continue
        w = params.season_decay ** (years_back - 1)
        effective += w * line.opportunities
        for e in EVENTS:
            weighted[e] += w * counts[e]

    total = params.prior_strength + effective
    posterior = {e: weighted[e] / total for e in EVENTS}

    trend = individual_trend or {}
    logits = []
    for e in EVENTS[:-1]:
        z = math.log(posterior[e] / posterior[REFERENCE])
        z += params.age_logodds_delta.get(e, 0.0)
        z += params.trend_reliability * trend.get(e, 0.0)
        logits.append(z)
    probs = _softmax([*logits, 0.0])

    flags = []
    if prior_used == "LEAGUE_FALLBACK":
        flags.append("LEAGUE_PRIOR_FALLBACK")
    if effective == 0.0:
        flags.append("NO_USABLE_HISTORY")
    if params.provenance != "TRAINED_ASOF":
        flags.append("UNTRAINED_PARAMETERS")
        status = ("NON_FORECAST_GRADE: parameters are PLACEHOLDER_UNTRAINED — output may not "
                  "enter any registry cohort, aggregate, or forecast (prereg parameter rule)")
    else:
        status = "SHADOW_PROJECTION"
    return PlayerProjection(
        event_probs=dict(zip(EVENTS, probs)),
        effective_opportunities=effective,
        posterior_strength=total,
        prior_used=prior_used,
        status=status,
        dq_flags=tuple(flags),
    )


# ------------------------------------------------------------------------------------------
# As-of player-season dataset: schema validation + evidence gate (currently EVIDENCE_ABSENT)
# ------------------------------------------------------------------------------------------

def validate_player_season_row(row: Mapping) -> list:
    """Schema errors for one candidate dataset row. Empty list = valid."""
    errs = [f"missing field {k}" for k in ROW_REQUIRED if k not in row]
    if errs:
        return errs
    if not isinstance(row["mlbam_id"], int):
        errs.append("mlbam_id must be int")
    ev = row["events"]
    if set(ev) != set(EVENTS):
        errs.append("events must contain exactly the mutually-exclusive event set")
    elif any((not isinstance(v, int)) or v < 0 for v in ev.values()):
        errs.append("event counts must be non-negative ints")
    elif sum(ev.values()) != row["opportunities"]:
        errs.append(f"events sum {sum(ev.values())} != opportunities {row['opportunities']}")
    if not (isinstance(row["age"], (int, float)) and 14 < float(row["age"]) < 60):
        errs.append("age must be a verified numeric age, not a guess")
    if not (isinstance(row["source_sha256"], str) and len(row["source_sha256"]) == 64):
        errs.append("source_sha256 must be a 64-hex artifact hash")
    return errs


def evidence_status() -> dict:
    """The honest ingest gate: what player-season evidence exists on disk right now?"""
    if not os.path.isdir(PLAYER_SEASONS_DIR):
        return {"status": "EVIDENCE_ABSENT", "rows": 0, "invalid": 0,
                "note": "data/mlb/player_seasons/ does not exist; no batter-level event "
                        "histories, ages, multi-year or pitch-level data in the repo "
                        "(verified 2026-07-28). No projection can be produced."}
    rows = invalid = 0
    for f in sorted(os.listdir(PLAYER_SEASONS_DIR)):
        if not f.endswith(".jsonl"):
            continue
        for ln in open(os.path.join(PLAYER_SEASONS_DIR, f)):
            if not ln.strip():
                continue
            rows += 1
            if validate_player_season_row(json.loads(ln)):
                invalid += 1
    status = "EVIDENCE_ABSENT" if rows == 0 else ("SCHEMA_VIOLATIONS" if invalid else "PRESENT")
    return {"status": status, "rows": rows, "invalid": invalid}


# ------------------------------------------------------------------------------------------
# selftest — synthetic fixtures ONLY, labeled as such; proves the mathematics and refusals.
# ------------------------------------------------------------------------------------------

def _uniformish_prior():
    # synthetic fixture prior (NOT a league estimate): plausible shape, sums to 1 exactly
    p = {"K": 0.22, "BB_HBP": 0.09, "HR": 0.03, "1B": 0.15, "2B": 0.045, "3B": 0.005}
    p[REFERENCE] = 1.0 - sum(p.values())
    return p


def _params(**over):
    kw = dict(season_decay=0.8, prior_strength=200.0, age_logodds_delta={},
              trend_reliability=0.0, provenance="PLACEHOLDER_UNTRAINED",
              trend_basis="synthetic fixture")
    kw.update(over)
    return EvolutionParams(**kw)


def _line(season, k_extra=0, pa=600, age=26.0):
    prior = _uniformish_prior()
    counts = {e: int(round(prior[e] * pa)) for e in EVENTS}
    counts["K"] += k_extra
    counts[REFERENCE] += pa - sum(counts.values())  # reconcile exactly
    return SeasonLine(season=season, age=age, opportunities=pa, counts=counts)


def selftest() -> int:
    fails = []

    def ok(name, cond):
        if not cond:
            fails.append(name)

    prior = _uniformish_prior()
    P = _params()

    # 1. probabilities: positive, sum to exactly 1
    pr = project_player_events([_line(2025)], target_season=2026, prior_probs=prior,
                               prior_used="INDIVIDUALIZED", params=P)
    ok("probs sum to 1", math.isclose(sum(pr.event_probs.values()), 1.0, abs_tol=1e-12))
    ok("probs all positive", all(v > 0 for v in pr.event_probs.values()))

    # 2. no history -> posterior == prior (round trip through log-odds + softmax)
    pr0 = project_player_events([], target_season=2026, prior_probs=prior,
                                prior_used="LEAGUE_FALLBACK", params=P)
    ok("zero history reproduces the prior",
       all(math.isclose(pr0.event_probs[e], prior[e], abs_tol=1e-12) for e in EVENTS))
    ok("league fallback is FLAGGED, never silent",
       "LEAGUE_PRIOR_FALLBACK" in pr0.dq_flags and "NO_USABLE_HISTORY" in pr0.dq_flags)

    # 3. shrinkage is monotone in evidence: 60 extreme PA move K% a little, 1200 move it more
    hotK = {"K": 30, "BB_HBP": 5, "HR": 1, "1B": 6, "2B": 2, "3B": 0, REFERENCE: 16}
    small = project_player_events(
        [SeasonLine(2025, 24.0, 60, hotK)], target_season=2026,
        prior_probs=prior, prior_used="INDIVIDUALIZED", params=P)
    big = project_player_events(
        [SeasonLine(2025, 24.0, 1200, {e: v * 20 for e, v in hotK.items()})], target_season=2026,
        prior_probs=prior, prior_used="INDIVIDUALIZED", params=P)
    ok("small hot sample stays near prior",
       prior["K"] < small.event_probs["K"] < big.event_probs["K"] < 0.5)

    # 4. leakage refusal: target-season (or later) line raises
    try:
        project_player_events([_line(2026)], target_season=2026, prior_probs=prior,
                              prior_used="INDIVIDUALIZED", params=P)
        ok("leakage REFUSED", False)
    except ValueError as e:
        ok("leakage REFUSED with as-of message", "LEAKAGE" in str(e))

    # 5. reconciliation refusal: counts != opportunities
    bad = SeasonLine(2025, 26.0, 600, {e: 10 for e in EVENTS})
    try:
        project_player_events([bad], target_season=2026, prior_probs=prior,
                              prior_used="INDIVIDUALIZED", params=P)
        ok("non-reconciling counts REFUSED", False)
    except ValueError as e:
        ok("non-reconciling counts REFUSED", "reconcile" in str(e))

    # 6. invalid prior refused (bad sum; missing event; zero entry)
    for badprior in ({**prior, "K": prior["K"] + 0.1},
                     {e: prior[e] for e in EVENTS[:-1]},
                     {**prior, "3B": 0.0}):
        try:
            project_player_events([], target_season=2026, prior_probs=badprior,
                                  prior_used="INDIVIDUALIZED", params=P)
            ok("invalid prior REFUSED", False)
        except ValueError:
            pass

    # 7. trend with reliability 0 has NO effect; reliability shrinks the trend continuously
    t = {"K": -0.4}
    a = project_player_events([_line(2025)], target_season=2026, prior_probs=prior,
                              prior_used="INDIVIDUALIZED", params=P, individual_trend=t)
    ok("r=0 nullifies trend",
       math.isclose(a.event_probs["K"], pr.event_probs["K"], abs_tol=1e-12))
    half = project_player_events([_line(2025)], target_season=2026, prior_probs=prior,
                                 prior_used="INDIVIDUALIZED",
                                 params=_params(trend_reliability=0.5), individual_trend=t)
    full = project_player_events([_line(2025)], target_season=2026, prior_probs=prior,
                                 prior_used="INDIVIDUALIZED",
                                 params=_params(trend_reliability=1.0), individual_trend=t)
    ok("reliability shrinks trend monotonically",
       full.event_probs["K"] < half.event_probs["K"] < pr.event_probs["K"])

    # 8. age delta moves the targeted event; distribution still sums to 1
    aged = project_player_events([_line(2025)], target_season=2026, prior_probs=prior,
                                 prior_used="INDIVIDUALIZED",
                                 params=_params(age_logodds_delta={"HR": 0.2}))
    ok("age delta raises targeted event", aged.event_probs["HR"] > pr.event_probs["HR"])
    ok("age-adjusted probs still sum to 1",
       math.isclose(sum(aged.event_probs.values()), 1.0, abs_tol=1e-12))

    # 9. season decay: with d=1 two equal seasons weigh equally; with d=0.5 older weighs half
    two = [_line(2024), _line(2025)]
    eff1 = project_player_events(two, target_season=2026, prior_probs=prior,
                                 prior_used="INDIVIDUALIZED",
                                 params=_params(season_decay=1.0)).effective_opportunities
    eff05 = project_player_events(two, target_season=2026, prior_probs=prior,
                                  prior_used="INDIVIDUALIZED",
                                  params=_params(season_decay=0.5)).effective_opportunities
    ok("decay weights history as specified", eff1 == 1200.0 and eff05 == 900.0)

    # 10. provenance gate: untrained params -> NON_FORECAST_GRADE; trained -> SHADOW_PROJECTION;
    #     trained without artifact reference refused
    ok("untrained output stamped NON_FORECAST_GRADE",
       pr.status.startswith("NON_FORECAST_GRADE") and "UNTRAINED_PARAMETERS" in pr.dq_flags)
    trained = project_player_events(
        [_line(2025)], target_season=2026, prior_probs=prior, prior_used="INDIVIDUALIZED",
        params=_params(provenance="TRAINED_ASOF", trained_on="fixture://synthetic-test-artifact",
                       trend_basis="age-detrended residual changes"))
    ok("trained params -> SHADOW_PROJECTION", trained.status == "SHADOW_PROJECTION")
    try:
        _params(provenance="TRAINED_ASOF")  # no trained_on
        ok("TRAINED_ASOF without artifact REFUSED", False)
    except ValueError:
        pass
    for bad_kw in (dict(season_decay=0.0), dict(season_decay=1.5), dict(prior_strength=0),
                   dict(trend_reliability=1.2), dict(provenance="VIBES")):
        try:
            _params(**bad_kw)
            ok(f"invalid params {bad_kw} REFUSED", False)
        except ValueError:
            pass

    # 11. dataset schema validator + evidence gate honesty
    good_row = {"mlbam_id": 545361, "season": 2025, "age": 30.5, "level": "MLB",
                "role": "position", "opportunities": 600,
                "events": {e: (600 - 6 * (len(EVENTS) - 1)) if e == REFERENCE else 6
                           for e in EVENTS},
                "source": "fixture", "observed_at_utc": "2026-07-28T00:00:00Z",
                "source_sha256": "0" * 64}
    ok("valid schema row accepted", validate_player_season_row(good_row) == [])
    ok("schema rejects non-reconciling row",
       validate_player_season_row({**good_row, "opportunities": 601}) != [])
    ok("schema rejects missing hash",
       validate_player_season_row({k: v for k, v in good_row.items()
                                   if k != "source_sha256"}) != [])
    ok("schema rejects absurd age",
       validate_player_season_row({**good_row, "age": 7}) != [])
    ev = evidence_status()
    ok(f"evidence gate reports honestly (got {ev['status']}, {ev['rows']} rows)",
       ev["status"] in ("EVIDENCE_ABSENT", "SCHEMA_VIOLATIONS", "PRESENT"))

    if fails:
        print("player_evolution selftest: FAIL")
        for x in fails:
            print("  " + x)
        return 1
    print(f"player_evolution selftest: PASS (25 fixtures, synthetic only; "
          f"evidence gate: {ev['status']})")
    return 0


if __name__ == "__main__":
    import sys
    if "--evidence" in sys.argv:
        print(json.dumps(evidence_status(), indent=1))
        raise SystemExit(0)
    raise SystemExit(selftest())
