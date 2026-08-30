"""Governed multi-sport Monte Carlo engine: MLB / WNBA / CFB.

WHAT THIS IS. A Monte Carlo simulator that turns DECLARED inputs (relayed numbers, ensemble
components, market prices) into simulated win/cover/total probabilities with a convergence
contract. It exists because the review found (a) no convergence diagnostics on any simulated
number in the repo and (b) freshness dose multipliers that were computed and then never
consumed. Both are fixed here: every emitted probability carries an mc_se and a per-block
convergence gap that can RAISE, and every ensemble component's dose shrinks its weight.

INPUTS ARE RELAYED / ENSEMBLE. Nothing in this module fetches anything. The numbers fed in
through the CLI input file are owner-relayed or ensemble outputs from other governed arms;
their provenance (source, grade) travels with each component and is echoed in the output.
Weights are JUDGMENT, declared in the input file, and configurable — they are not measured
quantities and are labeled as such.

R1 — never invent a number. Every emitted number is either (a) simulated from declared inputs
under a keyed seed, or (b) an input echoed through and labeled as an input. Frozen constants
below each carry their reason.

R3 — frozen stays frozen. WNBA_MARGIN_SD matches wnba_model_v1's frozen 13.97 and may not be
re-tuned inside this module.

MC PROTOCOL. TRIALS (default 30000) split into BLOCKS (10) equal batch blocks. Each block gets
its own RNG seeded by seed_for(engine_version, date, game_id, block) — the same keyed-seed
convention as keyed_seed.seed_for (sha256 of pipe-joined parts, first 8 hex digits), so results
are deterministic per (engine version, date, game, block) and re-running the slate byte-for-byte
reproduces the card. Per-block p_home is tracked; mc_se is the pooled-Bernoulli standard error
OF A BLOCK PROPORTION, sqrt(p_pooled*(1-p_pooled)/trials_per_block) — the natural scale on
which a single batch can drift. (The alternative reading, the se of the pooled estimate, is
sqrt(BLOCKS) tighter and false-fires on a healthy simulation: a max over 10 honest blocks sits
at ~1.5 block-sigmas by construction. That reading was tested and rejected; this is disclosed,
not silent.) mc_convergence_gap_pp = max |block p_home - pooled p_home| in percentage points.
If gap_pp > 3 * mc_se_pp the game RAISES ConvergenceError — fail loud, no card row — because a
simulator whose batches disagree is measuring its own RNG, not the game.

DOSE CONSUMPTION (logit-scale ensemble). Each component carries {source, grade, p_home OR
mov_home, total?, weight, dose}. Effective weight w_eff = weight * dose, so an
IDENTIFIED_UNCONFIRMED component at dose 0.75 pulls exactly 3/4 as hard as a confirmed one.
Pooling is on the logit scale: p = sigmoid( sum(w_eff_i * logit(p_i)) / sum(w_eff_i) ), which
keeps the ensemble between the component extremes and respects the geometry of probabilities.
MOV ens = MARGIN_SD * Phi^-1(p) for the normal sports; MLB solves Poisson lambdas to match the
ensemble (total, p_home) — seeded with the Skellam approximation, refined by bisection on the
analytic Poisson win probability, then VERIFIED in Monte Carlo (the lambda solve test checks
the MC recovers the target within mc tolerance). Ensemble total = dose-weighted mean of the
totals actually provided; an absent total is never synthesized from a margin (R1), it falls
back to the sport's frozen default with the fallback declared in the output.

DE-VIG. Proportional method on American odds: implied = 1/decimal_odds each side, normalized to
sum 1. No shin, no favourite-longshot model — proportional is the documented, arguable choice.
"""
from __future__ import annotations

MODULE_ID = "mc_engine"

import argparse
import hashlib
import json
import math
import random
import sys

ENGINE_VERSION = "mc_engine_v1"

# ------------------------------------------------------------------ frozen constants
# Each carries its reason; argue with the reason, not the number (R3).
TRIALS = 30000            # default protocol; 30k keeps mc_se <= ~0.29pp at p=0.5
BLOCKS = 10               # batch blocks for the convergence diagnostic
CONVERGENCE_SIGMAS = 3.0  # fail when max |block - pooled| exceeds 3 pooled Bernoulli sigmas

CFB_MARGIN_SD = 16.64     # restated 2026-08-29 (owner directive, R3 going-forward):
                            # SD = MAE x sqrt(pi/2) = 13.279 x 1.2533 = 16.64, where 13.279
                            # is the registered CFB arm out-of-sample margin MAE (full seasons).
                            # Optimistic bound: Week-1 variance is wider (no current-season form);
                            # owner notes real CFB margin SD ~= 16-17, wider in Week 1. Arm is
                            # validated on winner Brier (CI vs Elo [-0.00503, +0.00099] incl. 0),
                            # NOT on margin - treat cover probabilities as carrying that limit.
                            # Supersedes frozen 13.5 (understated; house arm calibration note kept:
                            # restatement changes valuation-layer cover probs, not the arm itself)
WNBA_MARGIN_SD = 13.97    # frozen: empirical, matches wnba_model_v1 frozen value (R3).
                          # OWNER RULING 2026-08-30: 13.97 is registered as a COHERENCE
                          # TOLERANCE (the model's p<->margin coherence check), NOT a
                          # distributional cover law. WNBA cover probabilities must NOT
                          # use it — see WNBA_COVER_SD.
WNBA_COVER_SD = 12.53     # cover math only. Provenance: MEASURED, not inferred —
                          # walk-forward margin MAE 9.995 (n=1633) x sqrt(pi/2)=1.2533
                          # (normal |error|->sd bridge) = 12.53.
WNBA_COVER_SD_ALT = 14.91 # upper bound of the honest range: the 2026-08-28 MAE 11.90
                          # (n=4, disagrees with the walk-forward measurement) x 1.2533.
                          # The card quotes a RANGE: covers are emitted at both sigmas.
CFB_TOTAL_SD = 16.0       # frozen: CFB historical total SD
WNBA_TOTAL_SD = 16.5      # frozen: WNBA historical total SD
MLB_DEFAULT_TOTAL = 8.5   # frozen: league-average scoring environment when no line exists
# NFL structural priors (mc_components.NFLComponent REFUSES — nfl v0_2.shadow has no live
# authority). Declared here so the engine STRUCTURE is NFL-ready: they are frozen priors,
# not refits, and simulate_game's sport gate below still rejects "nfl" until a live NFL
# authority exists. NFL historical margin/total dispersion scale.
NFL_MARGIN_SD = 13.8
NFL_TOTAL_SD = 15.5

MARGIN_SD = {"cfb": CFB_MARGIN_SD, "wnba": WNBA_MARGIN_SD, "nfl": NFL_MARGIN_SD}
TOTAL_SD = {"cfb": CFB_TOTAL_SD, "wnba": WNBA_TOTAL_SD, "nfl": NFL_TOTAL_SD}


class ConvergenceError(RuntimeError):
    """A game's batch blocks disagree beyond 3 sigmas. Raised, never warned — fail loud."""


class InputError(ValueError):
    """A declared input is missing or malformed. Raised rather than defaulted — R1."""


# ------------------------------------------------------------------ keyed seeds

def seed_for(*parts):
    """Deterministic per (engine_version, date, game_id, block). Mirrors keyed_seed.seed_for."""
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


# ------------------------------------------------------------------ math helpers

def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p):
    """Bisection inverse of norm_cdf. Deterministic, stdlib-only, good to ~1e-12."""
    if not 0.0 < p < 1.0:
        raise InputError(f"norm_ppf requires 0<p<1, got {p}")
    lo, hi = -12.0, 12.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if norm_cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def logit(p):
    if not 0.0 < p < 1.0:
        raise InputError(f"logit requires 0<p<1, got {p}")
    return math.log(p / (1.0 - p))


def sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


def american_to_prob(ml):
    """Implied probability from American odds (vig included)."""
    ml = float(ml)
    if ml > 0:
        return 100.0 / (ml + 100.0)
    if ml < 0:
        return -ml / (-ml + 100.0)
    raise InputError("American odds of exactly 0 are not a price")


# ------------------------------------------------------------------ valuation layer ONLY
# de_vig is a MARKET function. Per MARKET_INDEPENDENCE_RULE.md it may run only in the
# post-freeze valuation layer; the forecast path (build_ensemble / _component_p_home /
# component adapters in mc_components) must never call it. The guard below enforces that:
# build_ensemble enters a forecast context, and de_vig raises inside it.

_FORECAST_CONTEXT = {"depth": 0}


def de_vig(home_ml, away_ml):
    """Proportional de-vig: normalize the two implied probs to sum 1. VALUATION LAYER ONLY.

    Returns (p_home, p_away). The vig is removed in proportion to each side's implied
    probability — the documented, deliberately simple choice.

    Raises RuntimeError if called from inside the forecast path (build_ensemble) — market
    prices are firewalled from predictive components (MARKET_INDEPENDENCE_RULE.md).
    """
    if _FORECAST_CONTEXT["depth"]:
        raise RuntimeError("MARKET INDEPENDENCE: de_vig called inside the forecast path — "
                           "market prices are firewalled from predictive components")
    ph, pa = american_to_prob(home_ml), american_to_prob(away_ml)
    s = ph + pa
    if s <= 0:
        raise InputError("degenerate moneyline pair")
    return ph / s, pa / s


def american_profit_per_100(ml):
    """Profit on a winning 100-unit stake at American odds."""
    ml = float(ml)
    return ml if ml > 0 else 10000.0 / (-ml)


def ev_per_100(p, ml):
    """Expected value per 100 staked at price ml, given true win prob p."""
    return p * american_profit_per_100(ml) - (1.0 - p) * 100.0


# ------------------------------------------------------------------ Poisson (MLB)

def analytic_poisson_win_prob(lam_home, lam_away):
    """P(home runs > away runs) + 0.5 * P(tie), exact to float precision.

    Ties count as half a win so the analytic target and the MC estimator (which also credits
    a tie as 0.5) measure the same thing. MLB games cannot end tied; the 0.5 convention is the
    standard analytic bridge and is documented rather than hidden.
    """
    p = 0.0
    ka = 0
    p_a = math.exp(-lam_away)
    while p_a > 1e-15 or ka < lam_away + 12 * math.sqrt(lam_away + 1):
        # inner: P(home > ka) + 0.5 * P(home == ka)
        cdf_h = 0.0
        p_h = math.exp(-lam_home)
        kh = 0
        while kh <= ka:
            cdf_h += p_h
            kh += 1
            p_h = p_h * lam_home / kh
        p += p_a * ((1.0 - cdf_h) + 0.5 * p_h)
        ka += 1
        p_a = p_a * lam_away / ka
    return p


def solve_poisson_lambdas(total, p_home):
    """Find (lam_home, lam_away) with lam_home + lam_away == total matching p_home.

    Seed: Skellam approximation — the run margin is approximately Normal(lam_h - lam_a,
    lam_h + lam_a), so diff0 = sqrt(total) * Phi^-1(p_home). Refine: bisection on the exact
    analytic Poisson win probability until convergence. The MC then VERIFIES the solve
    empirically (see selftest S5 and the unit tests).
    """
    if total <= 0:
        raise InputError(f"MLB total must be positive, got {total}")
    if not 0.0 < p_home < 1.0:
        raise InputError(f"MLB p_home must be in (0,1), got {p_home}")
    diff = math.sqrt(total) * norm_ppf(p_home)  # Skellam seed
    lo, hi = diff - 2.0 * math.sqrt(total), diff + 2.0 * math.sqrt(total)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        lh = 0.5 * (total + mid)
        la = total - lh
        if lh <= 0 or la <= 0:
            raise InputError(f"no Poisson solution for total={total} p_home={p_home}")
        if analytic_poisson_win_prob(lh, la) < p_home:
            lo = mid
        else:
            hi = mid
    diff = 0.5 * (lo + hi)
    lh = 0.5 * (total + diff)
    return lh, total - lh


def _poisson_draw(rng, lam):
    """Knuth's method; fine for lambda <= ~15 (MLB run scoring). Pure stdlib so results do
    not depend on whether numpy happens to be installed."""
    if lam <= 0:
        return 0
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while p > L:
        k += 1
        p *= rng.random()
    return k - 1


# ------------------------------------------------------------------ ensemble

def _component_p_home(comp, sport):
    """p_home from a declared component: direct p_home, or mov_home mapped through the
    sport's margin scale. Nothing is invented; a component must carry one or the other."""
    if comp.get("p_home") is not None:
        p = float(comp["p_home"])
    elif comp.get("mov_home") is not None:
        mov = float(comp["mov_home"])
        if sport == "mlb":
            tot = comp.get("total")
            sd = math.sqrt(float(tot) if tot else MLB_DEFAULT_TOTAL)  # Poisson margin SD
        else:
            sd = MARGIN_SD[sport]
        p = norm_cdf(mov / sd)
    else:
        raise InputError(f"component {comp.get('source')!r} carries neither p_home nor mov_home")
    if not 0.0 < p < 1.0:
        raise InputError(f"component {comp.get('source')!r} p_home out of (0,1): {p}")
    return p


def build_ensemble(components, sport):
    """Logit-scale pooling with dose-shrunk weights.

    w_eff_i = weight_i * dose_i
    p_ens   = sigmoid( sum(w_eff_i * logit(p_i)) / sum(w_eff_i) )
    mov_ens = MARGIN_SD * Phi^-1(p_ens)            (normal sports)
    total   = sum(w_eff_i * total_i) / sum(w_eff_i over components that declare a total)

    Returns {p_home, mov_home, total, total_fallback, components:[echo with w_eff]}.
    """
    if not components:
        raise InputError("ensemble requires at least one component")
    _FORECAST_CONTEXT["depth"] += 1   # market functions (de_vig) refuse inside this block
    used = []
    num = 0.0
    den = 0.0
    tnum = 0.0
    tden = 0.0
    try:
        for c in components:
            w = float(c.get("weight", 1.0))
            dose = float(c.get("dose", 1.0))
            w_eff = w * dose
            if w_eff <= 0:
                continue
            p_i = _component_p_home(c, sport)
            num += w_eff * logit(p_i)
            den += w_eff
            if c.get("total") is not None:
                tnum += w_eff * float(c["total"])
                tden += w_eff
            echo = {"source": c.get("source"), "grade": c.get("grade"),
                    "weight": w, "dose": dose, "w_eff": round(w_eff, 6),
                    "p_home": round(p_i, 6),
                    "mov_home": c.get("mov_home"), "total": c.get("total")}
            if c.get("arm") is not None:          # p_home-supplying arms (v13) carry
                echo["arm"] = c["arm"]            # their registered identity through
            if c.get("provenance") is not None:
                echo["provenance"] = c["provenance"]
            used.append(echo)
        if den <= 0:
            raise InputError("all components have zero effective weight")
        p = sigmoid(num / den)
        if sport == "mlb":
            mov = None  # MLB MOV comes from the solved lambdas, not a normal margin
        else:
            mov = MARGIN_SD[sport] * norm_ppf(p)
        fallback = False
        if tden > 0:
            total = tnum / tden
        elif sport == "mlb":
            total = MLB_DEFAULT_TOTAL
            fallback = True
        else:
            raise InputError(f"no component declares a total for a {sport} game — R1, not defaulting")
        return {"p_home": p, "mov_home": mov, "total": total,
                "total_fallback": fallback, "components": used}
    finally:
        _FORECAST_CONTEXT["depth"] -= 1


# ------------------------------------------------------------------ simulation

def _simulate_blocks(sport, params, seeds, trials_per_block, rng_factory):
    """Run the batch blocks; return per-block (wins, cover, over, margins, totals)."""
    wins_b, cover_b, over_b = [], [], []
    margins_b, totals_b = [], []
    for seed in seeds:
        rng = rng_factory(seed)
        w = c = o = 0
        msum = tsum = 0.0
        for _ in range(trials_per_block):
            if sport == "mlb":
                h = _poisson_draw(rng, params["lam_home"])
                a = _poisson_draw(rng, params["lam_away"])
            else:
                m = rng.gauss(params["mov"], params["margin_sd"])
                t = rng.gauss(params["total"], params["total_sd"])
                h = 0.5 * (t + m)
                a = 0.5 * (t - m)
            margin, tot = h - a, h + a
            msum += margin
            tsum += tot
            w += 1 if margin > 0 else (0.5 if margin == 0 else 0)
            if params.get("spread") is not None:
                c += 1 if margin > params["spread"] else (
                    0.5 if margin == params["spread"] else 0)
            if params.get("total_line") is not None:
                o += 1 if tot > params["total_line"] else 0  # a push is not an over; for
                # integer MLB lines the push mass is reported via under_prob=None
        n = trials_per_block
        wins_b.append(w / n)
        cover_b.append(c / n if params.get("spread") is not None else None)
        over_b.append(o / n if params.get("total_line") is not None else None)
        margins_b.append(msum / n)
        totals_b.append(tsum / n)
    return wins_b, cover_b, over_b, margins_b, totals_b


def simulate_game(game, trials=TRIALS, blocks=BLOCKS, rng_factory=random.Random):
    """Simulate one declared game. Returns the public result dict.

    Raises ConvergenceError if the batch blocks disagree beyond CONVERGENCE_SIGMAS pooled
    Bernoulli sigmas — a failing game gets NO card row, by construction.
    Raises InputError on malformed declared inputs.
    """
    sport = game["sport"].lower()
    if sport not in ("mlb", "cfb", "wnba"):
        raise InputError(f"unknown sport {sport!r}")
    if trials % blocks:
        raise InputError("trials must divide evenly into blocks")
    gid = game["game_id"]
    date = game["date"]

    ens = build_ensemble(game["components"], sport)
    p_target = ens["p_home"]
    total = ens["total"]

    lines = game.get("lines") or {}
    wnba_cover = None
    spread = lines.get("market_spread_home")
    if sport == "wnba" and spread is not None:
        # OWNER RULING 2026-08-30: WNBA cover probabilities never use MARGIN_SD=13.97
        # (a coherence tolerance). Covers are computed analytically on margin ~
        # N(mov, sigma) at the MEASURED cover sigma 12.53 (walk-forward MAE 9.995,
        # n=1633, x sqrt(pi/2)) AND at 14.91 (8/28 MAE 11.90, n=4, x 1.2533) so the
        # honest range is computable from the outputs. The margin simulation itself
        # keeps 13.97 in its coherence role (p_home/margin consistency with the
        # ensemble mapping); it just no longer scores covers. Push mass: the analytic
        # normal has zero mass at an exact integer spread — declared, not hidden
        # (the 8/29 spreads are half-lines; a future integer spread understates the
        # cover by half the push mass, which the normal model does not carry).
        mov = ens["mov_home"]
        wnba_cover = {
            "cover_prob_home": round(1.0 - norm_cdf((spread - mov) / WNBA_COVER_SD), 5),
            "cover_prob_home_sigma_alt": round(
                1.0 - norm_cdf((spread - mov) / WNBA_COVER_SD_ALT), 5),
            "cover_sigma_primary": WNBA_COVER_SD,
            "cover_sigma_alt": WNBA_COVER_SD_ALT,
            "cover_sigma_note": ("cover math uses the MEASURED cover SD 12.53 "
                                 "(walk-forward margin MAE 9.995 n=1633 x 1.2533), never "
                                 "the 13.97 coherence tolerance; the alt sigma 14.91 "
                                 "(8/28 MAE 11.90 n=4 x 1.2533) brackets the honest range. "
                                 "Analytic normal: zero push mass at an integer spread.")}
        spread = None  # the block simulation must not score covers at 13.97
    params = {
        "spread": spread,
        "total_line": lines.get("market_total"),
    }
    analytic = {}
    if sport == "mlb":
        lh, la = solve_poisson_lambdas(total, p_target)
        params.update(lam_home=lh, lam_away=la)
        analytic["lambda_home"] = round(lh, 4)
        analytic["lambda_away"] = round(la, 4)
        analytic["analytic_p_home"] = round(analytic_poisson_win_prob(lh, la), 6)
    else:
        params.update(mov=ens["mov_home"], margin_sd=MARGIN_SD[sport],
                      total=total, total_sd=TOTAL_SD[sport])

    seeds = [seed_for(ENGINE_VERSION, date, gid, b) for b in range(blocks)]
    n = trials // blocks
    wins_b, cover_b, over_b, margins_b, totals_b = _simulate_blocks(
        sport, params, seeds, n, rng_factory)

    p_pool = sum(wins_b) / blocks
    # pooled-Bernoulli se of a BLOCK proportion (see module docstring for why this scale).
    mc_se = math.sqrt(p_pool * (1.0 - p_pool) / (trials / blocks))
    gap = max(abs(b - p_pool) for b in wins_b)
    conv = {"trials": trials, "blocks": blocks,
            "mc_se_pp": round(mc_se * 100.0, 4),
            "mc_se_pooled_estimate_pp": round(
                math.sqrt(p_pool * (1.0 - p_pool) / trials) * 100.0, 4),
            "gap_pp": round(gap * 100.0, 4),
            "block_p_home": [round(b, 5) for b in wins_b],
            "status": "OK"}
    if gap > CONVERGENCE_SIGMAS * mc_se:
        raise ConvergenceError(
            f"CONVERGENCE_FAIL {gid}: gap {gap*100:.3f}pp > "
            f"{CONVERGENCE_SIGMAS:.0f}x mc_se {mc_se*100:.3f}pp — refusing to emit a card row")

    mov_home = (params["lam_home"] - params["lam_away"]) if sport == "mlb" else params["mov"]
    mean_margin = sum(margins_b) / blocks
    mean_total = sum(totals_b) / blocks
    result = {
        "game": gid, "date": date, "sport": sport,
        "home": game.get("home"), "away": game.get("away"),
        "p_home": round(p_pool, 5),
        "mov_home": round(mov_home, 3),
        "expected_total": round(mean_total, 3),
        "home_score": round(0.5 * (mean_total + mean_margin), 2),
        "away_score": round(0.5 * (mean_total - mean_margin), 2),
        "convergence": conv,
        "ensemble": {"p_home_target": round(p_target, 6),
                     "total_fallback": ens["total_fallback"],
                     "weights_note": "weights are judgment, declared in the inputs file",
                     "components": ens["components"]},
        "analytic": analytic or None,
    }
    out_lines = {}
    if wnba_cover is not None:
        out_lines["market_spread_home"] = lines.get("market_spread_home")
        out_lines.update(wnba_cover)
    elif params["spread"] is not None:
        out_lines["market_spread_home"] = params["spread"]
        out_lines["cover_prob_home"] = round(sum(cover_b) / blocks, 5)
    if params["total_line"] is not None:
        out_lines["market_total"] = params["total_line"]
        over = sum(over_b) / blocks
        out_lines["over_prob"] = round(over, 5)
        # under is 1-over only when push mass is zero (continuous normal totals / half lines).
        out_lines["under_prob"] = None if (sport == "mlb" and
                                           float(params["total_line"]).is_integer()
                                           ) else round(1.0 - over, 5)
    if lines.get("market_ml_home") is not None and lines.get("market_ml_away") is not None:
        out_lines["market_ml_home"] = lines["market_ml_home"]
        out_lines["market_ml_away"] = lines["market_ml_away"]
        out_lines["ev_per_100_home"] = round(ev_per_100(p_pool, lines["market_ml_home"]), 2)
        out_lines["ev_per_100_away"] = round(ev_per_100(1.0 - p_pool, lines["market_ml_away"]), 2)
    if out_lines:
        result["lines"] = out_lines
    return result


# ====================================================================== selftest

def _toy_game():
    return {"game_id": "TOY@HOME", "date": "2026-08-29", "sport": "cfb",
            "home": "HOME", "away": "TOY",
            "components": [
                {"source": "house", "grade": "CONFIRMED", "mov_home": 7.0, "total": 55.5,
                 "weight": 0.6, "dose": 1.0},
                {"source": "vss", "grade": "IDENTIFIED_UNCONFIRMED", "mov_home": 3.0,
                 "total": 53.5, "weight": 0.4, "dose": 0.75},
            ]}


_RIGGED_STATE = {"created": 0}


def _rigged_factory(seed):
    """An RNG whose draws ignore `seed` and depend on creation ORDER, so the first block always
    wins and every later block always loses — a keyed seed cannot smooth that out."""
    first = _RIGGED_STATE["created"] % BLOCKS == 0
    _RIGGED_STATE["created"] += 1

    class Rigged(random.Random):
        def gauss(self, mu, sigma):
            return mu + (100.0 if first else -100.0) * sigma

        def random(self):
            return 1e-9 if first else 1.0 - 1e-9
    return Rigged(seed)


def selftest():
    f = []

    # S1 — determinism: same declared inputs -> identical outputs.
    g = _toy_game()
    r1 = simulate_game(g)
    r2 = simulate_game(json.loads(json.dumps(g)))
    if r1 != r2:
        f.append("S1: same inputs did not reproduce identical outputs")

    # S2 — convergence gate FIRES on a rigged RNG.
    try:
        simulate_game(g, rng_factory=_rigged_factory)
        f.append("S2: a rigged RNG did NOT trip the convergence gate")
    except ConvergenceError:
        pass

    # S3 — de-vig math: -110/-110 -> 0.5/0.5; -200/+170 proportional.
    ph, pa = de_vig(-110, -110)
    if abs(ph - 0.5) > 1e-12 or abs(pa - 0.5) > 1e-12:
        f.append(f"S3: de_vig(-110,-110) gave {ph}/{pa}")
    ph, pa = de_vig(-200, 170)
    ih, ia = 200 / 300.0, 100 / 270.0
    if abs(ph - ih / (ih + ia)) > 1e-12 or abs(ph + pa - 1.0) > 1e-12:
        f.append(f"S3: proportional de-vig wrong: {ph}")

    # S4 — dose shrinkage: halving a component's dose moves the ensemble in logit space.
    c_full = [{"source": "a", "p_home": 0.8, "total": 55.0, "weight": 1.0, "dose": 1.0},
              {"source": "b", "p_home": 0.4, "total": 53.0, "weight": 1.0, "dose": 1.0}]
    c_half = [dict(c_full[0], dose=0.5), c_full[1]]
    e_full = build_ensemble(c_full, "cfb")
    e_half = build_ensemble(c_half, "cfb")
    expect = sigmoid((0.5 * logit(0.8) + 1.0 * logit(0.4)) / 1.5)
    if abs(e_half["p_home"] - expect) > 1e-9:
        f.append(f"S4: dose 0.5 gave {e_half['p_home']}, expected logit-pooled {expect}")
    if abs(e_half["p_home"] - e_full["p_home"]) < 1e-9:
        f.append("S4: dose made no difference")
    if not (0.4 < e_half["p_home"] < e_full["p_home"] < 0.8):
        f.append("S4: ensemble escaped the component extremes")

    # S5 — Poisson lambda solve recovers the target wp, analytically and in MC.
    lh, la = solve_poisson_lambdas(8.5, 0.62)
    if abs(lh + la - 8.5) > 1e-9:
        f.append("S5: lambdas do not sum to the declared total")
    if abs(analytic_poisson_win_prob(lh, la) - 0.62) > 1e-8:
        f.append("S5: analytic wp does not match the target")
    mlb_game = {"game_id": "A@B", "date": "2026-08-29", "sport": "mlb",
                "components": [{"source": "mkt", "p_home": 0.62, "total": 8.5,
                                "weight": 1.0, "dose": 1.0}]}
    rm = simulate_game(mlb_game)
    tol = 4.0 * rm["convergence"]["mc_se_pp"] / 100.0
    if abs(rm["p_home"] - 0.62) > tol:
        f.append(f"S5: MC p_home {rm['p_home']} vs target 0.62 outside 4x mc_se")

    # S6 — over + under == 1 for a non-push line.
    gl = _toy_game()
    gl["lines"] = {"market_total": 54.5, "market_spread_home": 5.5}
    rl = simulate_game(gl)
    if abs(rl["lines"]["over_prob"] + rl["lines"]["under_prob"] - 1.0) > 1e-9:
        f.append("S6: over + under != 1 at a non-push line")

    # S7 — a failing game raises; no partial row exists to leak into a card.
    try:
        simulate_game(g, rng_factory=_rigged_factory)
        f.append("S7: convergence failure produced a result instead of raising")
    except ConvergenceError:
        pass

    # S8 — seeds are keyed per game: different game_id -> different stream.
    g2 = dict(g, game_id="OTHER@HOME")
    r3 = simulate_game(g2)
    if r3["convergence"]["block_p_home"] == r1["convergence"]["block_p_home"]:
        f.append("S8: different game_id produced an identical RNG stream (seed not keyed)")

    print(f"mc_engine selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("  !", x)
    return 0 if not f else 1


# ====================================================================== mutation suite

def mutation_suite():
    """Break the engine on purpose; every mutant must be caught by selftest.

    A gate nobody can prove is a gate nobody should trust.
    """
    mutants = []
    g = globals()

    def run(name, patch, restore):
        patch()
        try:
            caught = selftest() != 0
        except Exception:
            caught = True
        restore()
        mutants.append((name, caught))

    # M1 — convergence gate removed (threshold at infinity: can never fire).
    orig_sig = g["CONVERGENCE_SIGMAS"]
    run("M1 convergence gate removed",
        lambda: g.__setitem__("CONVERGENCE_SIGMAS", float("inf")),
        lambda: g.__setitem__("CONVERGENCE_SIGMAS", orig_sig))

    # M2 — dose ignored in the ensemble.
    orig_build = g["build_ensemble"]

    def _build_no_dose(components, sport):
        return orig_build([dict(c, dose=1.0) for c in components], sport)
    run("M2 dose ignored",
        lambda: g.__setitem__("build_ensemble", _build_no_dose),
        lambda: g.__setitem__("build_ensemble", orig_build))

    # M3 — seed not keyed per game (game_id dropped from the seed parts).
    orig_seed = g["seed_for"]
    run("M3 seed not keyed per game",
        lambda: g.__setitem__("seed_for",
                              lambda *parts: orig_seed(parts[0], parts[1], parts[3])),
        lambda: g.__setitem__("seed_for", orig_seed))

    n = sum(1 for _, c in mutants if c)
    print(f"\nmc_engine mutation suite: {n}/{len(mutants)} caught")
    for name, c in mutants:
        print(f"  {'CAUGHT ' if c else 'ESCAPED'} {name}")
    return n == len(mutants)


# ====================================================================== CLI

def run_slate(inputs_path, outputs_path):
    blob = json.load(open(inputs_path))
    results, failures = [], []
    rows = []
    for game in blob["games"]:
        if game.get("status") == "ARM_UNAVAILABLE":
            # honest degradation (R1): the registered arm could not run; the exact missing
            # artifact is named and NO number is emitted for this game.
            entry = {"game": game["game_id"], "date": game["date"],
                     "sport": game["sport"], "home": game.get("home"),
                     "away": game.get("away"), "status": "ARM_UNAVAILABLE",
                     "artifact_missing": game.get("artifact_missing")}
            # going-forward (2026-08-29, documented): an input-declared card_language
            # (e.g. "interim, unvalidated" on every interim-arm MLB row) must survive the
            # skip path too — a degraded row is still a row on the card.
            if game.get("card_language"):
                entry["card_language"] = game["card_language"]
            if game.get("lines"):
                entry["lines"] = game["lines"]   # market-reference only, never a forecast
            results.append(entry)
            rows.append((game["game_id"], game["sport"], "ARM_UNAVAILABLE",
                         game.get("artifact_missing", "?"), "", "", "", "", "", ""))
            continue
        try:
            r = simulate_game(game)
        except ConvergenceError as e:
            failures.append(str(e))
            continue
        results.append(r)
        ln = r.get("lines", {})
        rows.append((r["game"], r["sport"],
                     f"{r['p_home']*100:5.1f}%", f"{r['mov_home']:+6.1f}",
                     f"{r['expected_total']:5.1f}",
                     f"{r['convergence']['gap_pp']:5.2f}",
                     (f"{ln['cover_prob_home']*100:5.1f}%" if "cover_prob_home" in ln else "  -- "),
                     (f"{ln['over_prob']*100:5.1f}%" if "over_prob" in ln else "  -- "),
                     (f"{ln['ev_per_100_home']:+6.2f}" if "ev_per_100_home" in ln else "  --  "),
                     (f"{ln['ev_per_100_away']:+6.2f}" if "ev_per_100_away" in ln else "  --  ")))
    hdr = ("game", "sport", "p_home", "MOV", "total", "gap_pp", "cover", "over",
           "EVh/100", "EVa/100")
    widths = [max(len(str(x[i])) for x in [hdr] + rows) for i in range(len(hdr))]
    fmt = "  ".join("{:" + str(w) + "}" for w in widths)
    print(fmt.format(*hdr))
    print(fmt.format(*["-" * w for w in widths]))
    for row in rows:
        print(fmt.format(*row))
    out = {"module": MODULE_ID, "engine_version": ENGINE_VERSION,
           "date": blob.get("date"),
           "protocol": {"trials": TRIALS, "blocks": BLOCKS,
                        "convergence_sigmas": CONVERGENCE_SIGMAS},
           "weights_policy": blob.get("weights_policy"),
           "disclosure": ("inputs are relayed/ensemble; weights are judgment and configurable; "
                          "R1 — every emitted number is simulated from declared inputs or labeled "
                          "as an input"),
           "results": results,
           "convergence_failures": failures}
    if outputs_path:
        with open(outputs_path, "w") as fh:
            json.dump(out, fh, indent=2)
        print(f"\nwrote {outputs_path} ({len(results)} games, {len(failures)} convergence failures)")
    for x in failures:
        print("CONVERGENCE_FAIL:", x)
    return 1 if failures else 0


def main(argv):
    ap = argparse.ArgumentParser(prog="mc_engine")
    ap.add_argument("--run", metavar="INPUTS.json")
    ap.add_argument("--out", metavar="OUTPUTS.json", default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--mutants", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.mutants:
        return 0 if mutation_suite() else 1
    if a.run:
        out = a.out
        if out is None:
            out = a.run.replace("_inputs", "_results")
            if out == a.run:
                out = a.run + ".results"
        return run_slate(a.run, out)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
