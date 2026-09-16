#!/usr/bin/env python3
"""BASELINE OFFSET — the expanding home prior is the default forecast; the model earns every move.

OWNER SPECIFICATION 2026-08-23, item 2:

    logit(p_home) = logit(p_home_prior_asof) + f(X)

    * p_home_prior_asof uses only games completed before first pitch.
    * f(X) predicts the residual contribution from team strength, starters, bullpen, park, rest and
      other frozen features.
    * Prices and implied probabilities remain downstream-only.
    * Strong regularization pulls f(X) toward zero when the features add no validated information.

WHY THIS SHAPE. V13 produced probabilities with a standard deviation of about 3.25pp against a
market SD near 11.5pp, and its edges of 5pp or more are 0-6 lifetime. A model that compresses toward
the middle and is then read as if it discriminates is worse than one that admits it does not. Making
the prior the intercept inverts the burden: the forecast IS the base rate until a feature earns a
move away from it, and the size of that move is the thing evaluated.

THE ADDITION IS IN LOG-ODDS, NEVER IN PROBABILITY. Adding to a probability is not closed on (0,1)
and is not symmetric: +0.05 on 0.52 and +0.05 on 0.97 are different amounts of evidence. Invariant 4
enforces this, and invariant 3 pins the degenerate case — with every residual coefficient zero the
challenger must equal the prior EXACTLY, not approximately.

THE PRIOR POOL IS TIER-1 BY DEFAULT. 126 of the 1934 canonical 2026 finals are legacy tier-2/3 rows
under a standing frozen exposure. A prior is a MODEL INPUT, so it is built from tier-1 evidence
only; the filter is an explicit bound parameter and the record carries the pool hash, so which games
produced the intercept is reconstructable rather than asserted.
"""
from __future__ import annotations

MODULE_ID = "baseline_offset"

import csv
import hashlib
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(BASE, "data/backfill/mlb/2026/results.csv")

# Smoothing toward a coin flip so an early-season prior is not a raw ratio over a handful of games.
# At n=0 the prior is exactly 0.5, hence logit 0, which is what makes invariant 3 checkable.
PRIOR_PSEUDO_COUNT = 20.0
PRIOR_PSEUDO_CENTER = 0.5
DEFAULT_TIER_FILTER = ("1",)
EPS = 1e-12

# Anything naming a price, a book or an implied probability. These may never reach the feature
# matrix (invariant 6): market data is downstream evaluation evidence forever.
MARKET_TOKENS = ("ml", "moneyline", "money_line", "price", "odds", "book", "line", "spread",
                 "total_line", "close", "closing", "implied", "vig", "devig", "no_vig", "novig",
                 "juice", "overround", "market")


def logit(p):
    if not (0.0 < p < 1.0):
        raise ValueError(f"logit undefined at p={p}")
    return math.log(p / (1.0 - p))


def expit(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def load_results(path=None):
    p = path or RESULTS
    if not os.path.exists(p):
        return []
    return list(csv.DictReader(open(p)))


def prior_pool(slate_date, rows, tier_filter=DEFAULT_TIER_FILTER):
    """Every completed game STRICTLY BEFORE the slate date, from the permitted evidence tiers.

    Strictly before is the whole point: a same-day game is not complete before that day's first
    pitch, so including the slate's own results would leak the outcome into its own prior."""
    out = []
    for r in rows:
        if str(r.get("status", "")).lower() != "final":
            continue
        if (r.get("date") or "") >= slate_date:
            continue
        if tier_filter is not None and str(r.get("source_tier", "")) not in tier_filter:
            continue
        hw = r.get("home_win")
        if hw in (None, ""):
            continue
        out.append(r)
    return sorted(out, key=lambda r: (r.get("date", ""), r.get("game_id", "")))


def pool_hash(pool):
    """Hash over the EXACT rows behind the intercept, so the prior reconstructs or the gate fails."""
    payload = [[r.get("game_id"), r.get("date"), int(r["home_win"])] for r in pool]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def home_prior(slate_date, rows=None, tier_filter=DEFAULT_TIER_FILTER, cutoff_utc=None,
               pseudo_count=PRIOR_PSEUDO_COUNT, pseudo_center=PRIOR_PSEUDO_CENTER):
    """The expanding home-win prior as of a slate date, with its provenance."""
    rows = load_results() if rows is None else rows
    pool = prior_pool(slate_date, rows, tier_filter)
    n = len(pool)
    wins = sum(int(r["home_win"]) for r in pool)
    p = (wins + pseudo_count * pseudo_center) / (n + pseudo_count)
    return {
        "p_home_prior": p,
        "prior_games_n": n,
        "prior_home_wins": wins,
        "prior_raw_rate": (wins / n) if n else None,
        "prior_cutoff_utc": cutoff_utc or f"{slate_date}T00:00:00Z",
        "prior_source_hash": pool_hash(pool),
        "prior_pool_tier_filter": list(tier_filter) if tier_filter else None,
        "prior_pseudo_count": pseudo_count,
        "prior_pseudo_center": pseudo_center,
        "prior_last_game_date": pool[-1].get("date") if pool else None,
    }


def combine(p_prior, residual_logit):
    """logit(p_home) = logit(prior) + f(X). THE ONLY PLACE THE TWO ARE COMBINED.

    CLAMPED to the open interval. expit saturates to exactly 1.0 in float arithmetic once the
    composed log-odds pass about 37, and invariant 5 requires a probability strictly between zero
    and one — a forecast of exactly 1.0 claims certainty and makes log-loss infinite. Under the
    intended strong regularization a residual that large should never occur, so the clamp is a
    guard rather than a working range; it is applied here so no caller can produce a degenerate
    probability by any path."""
    z = logit(p_prior) + residual_logit
    return min(max(expit(z), EPS), 1.0 - EPS)


def forecast(prior_rec, residual_logit, model_id, feature_cutoff_utc, training_snapshot_hash,
             game_start_utc, information_class=None, information_fraction=None,
             named_cap_slots=None, verified_profile_slots=None):
    """One registered baseline/challenger pair for one game, with every required field present."""
    p_prior = prior_rec["p_home_prior"]
    p_ch = combine(p_prior, residual_logit)
    return {
        "p_home_prior": p_prior,
        "prior_games_n": prior_rec["prior_games_n"],
        "prior_cutoff_utc": prior_rec["prior_cutoff_utc"],
        "prior_source_hash": prior_rec["prior_source_hash"],
        "p_home_challenger": p_ch,
        "delta_logit_from_prior": residual_logit,
        "predicted_winner": "home" if p_ch >= 0.5 else "away",
        "starter_information_class": information_class,
        "starter_information_fraction": information_fraction,
        "named_cap_slots": named_cap_slots,
        "verified_profile_slots": verified_profile_slots,
        "feature_cutoff_utc": feature_cutoff_utc,
        "model_id": model_id,
        "training_snapshot_hash": training_snapshot_hash,
        "game_start_utc": game_start_utc,
    }


REQUIRED_FIELDS = (
    "p_home_prior", "prior_games_n", "prior_cutoff_utc", "prior_source_hash",
    "p_home_challenger", "delta_logit_from_prior", "predicted_winner",
    "starter_information_class", "starter_information_fraction", "named_cap_slots",
    "verified_profile_slots",
    "feature_cutoff_utc", "model_id", "training_snapshot_hash",
)


# ---------------------------------------------------------------------------------------------
# THE TEN STRUCTURAL INVARIANTS (owner specification 2026-08-23). Each returns a failure string or
# None, and each is checked by a fixture that can only be satisfied by that invariant.
# ---------------------------------------------------------------------------------------------

def inv1_prior_cutoff_precedes_first_pitch(rec):
    c, g = rec.get("prior_cutoff_utc"), rec.get("game_start_utc")
    if not c or not g:
        return "INV1: prior_cutoff_utc or game_start_utc missing"
    if not (c < g):
        return f"INV1: prior_cutoff_utc {c} is not strictly before game_start_utc {g}"
    return None


def inv2_prior_reconstructs(rec, rows=None, slate_date=None, tier_filter=DEFAULT_TIER_FILTER):
    rows = load_results() if rows is None else rows
    d = slate_date or (rec.get("prior_cutoff_utc") or "")[:10]
    pool = prior_pool(d, rows, tier_filter)
    if pool_hash(pool) != rec.get("prior_source_hash"):
        return (f"INV2: the prior does not reconstruct from its bound historical pool "
                f"({len(pool)} rows hash {pool_hash(pool)[:12]} vs recorded "
                f"{str(rec.get('prior_source_hash'))[:12]})")
    if rec.get("prior_games_n") != len(pool):
        return f"INV2: prior_games_n {rec.get('prior_games_n')} but the bound pool holds {len(pool)}"
    return None


def inv3_zero_residual_equals_prior(rec, tol=0.0):
    """With all residual coefficients zero the challenger must equal the prior EXACTLY."""
    if rec.get("delta_logit_from_prior") == 0:
        d = abs(rec["p_home_challenger"] - rec["p_home_prior"])
        if d > tol:
            return (f"INV3: delta_logit is zero but the challenger differs from the prior by {d:.3e} "
                    f"— the composition is not an identity at zero")
    return None


def inv4_adjustment_is_in_log_odds(rec, tol=1e-9):
    """The recorded challenger must be the LOG-ODDS composition, not a probability addition."""
    try:
        want = combine(rec["p_home_prior"], rec["delta_logit_from_prior"])
    except (KeyError, TypeError, ValueError) as e:
        return f"INV4: cannot recompose ({e})"
    if abs(want - rec["p_home_challenger"]) > tol:
        naive = rec["p_home_prior"] + rec["delta_logit_from_prior"]
        hint = " (it matches a RAW PROBABILITY ADDITION)" if abs(naive - rec["p_home_challenger"]) <= tol else ""
        return (f"INV4: challenger {rec['p_home_challenger']:.6f} is not "
                f"expit(logit(prior)+delta)={want:.6f}{hint}")
    return None


def inv5_probabilities_finite_and_open(rec):
    for k in ("p_home_prior", "p_home_challenger"):
        v = rec.get(k)
        if v is None or not isinstance(v, (int, float)) or isinstance(v, bool):
            return f"INV5: {k} is not a number ({v!r})"
        if math.isnan(v) or math.isinf(v):
            return f"INV5: {k} is not finite ({v!r})"
        if not (0.0 < v < 1.0):
            return f"INV5: {k}={v} is not strictly between zero and one"
    d = rec.get("delta_logit_from_prior")
    if d is None or math.isnan(d) or math.isinf(d):
        return f"INV5: delta_logit_from_prior is not finite ({d!r})"
    return None


def inv6_no_market_fields_in_features(feature_names):
    """Market data is downstream evaluation evidence forever. A price never becomes a feature."""
    bad = []
    for name in (feature_names or []):
        toks = str(name).lower().replace("-", "_").split("_")
        if any(t in MARKET_TOKENS for t in toks):
            bad.append(name)
    return f"INV6: market-derived feature(s) in the matrix: {bad}" if bad else None


def inv6b_residual_has_no_free_intercept(coefficients, intercept_names=("intercept", "const",
                                                                          "bias", "_intercept",
                                                                          "b0", "alpha")):
    """The residual model f(X) must carry NO unrestricted intercept.

    OWNER RULING 2026-08-23: "Use the expanding prior as an offset: logit(prior_p_t) with feature
    effects modeling residual information. Do not allow an unrestricted intercept to relearn the
    base rate."

    A free intercept in f(X) is not a harmless extra parameter — it lets the residual model
    re-estimate the very quantity the offset already supplies, and under regularization it will,
    because an intercept is the cheapest way to fit an average. The offset then stops being the
    default forecast and becomes a starting guess the model is free to overwrite. Any coefficient
    named like an intercept, or any nonzero constant term, is refused."""
    if coefficients is None:
        return "INV6b: no coefficient set supplied; an unchecked residual model is not a checked one"
    bad = []
    for name, value in dict(coefficients).items():
        n = str(name).strip().lower()
        if n in intercept_names or n.endswith("intercept"):
            if value not in (0, 0.0, None):
                bad.append(f"{name}={value}")
            else:
                bad.append(f"{name} is present (pinned to {value}) — the term must be ABSENT, not "
                           f"zeroed, so it cannot be un-pinned by a later fit")
    return (f"INV6b: the residual model carries an intercept term {bad} — an unrestricted intercept "
            f"relearns the base rate the offset already supplies") if bad else None


def inv7_baseline_and_challenger_registered_together(baseline_ids, challenger_ids):
    b, c = set(baseline_ids or []), set(challenger_ids or [])
    if b != c:
        return (f"INV7: baseline and challenger are not registered on identical games "
                f"(baseline-only {sorted(b - c)[:4]}, challenger-only {sorted(c - b)[:4]})")
    if not b:
        return "INV7: no games registered"
    return None


def inv8_evaluation_is_paired(pairs):
    """Every evaluated game must carry BOTH probabilities. An unpaired row is a slate difference
    reported as a model difference — the exact error that excluded 2026-08-18 from the 29-game
    head-to-head."""
    bad = [p.get("game_id") for p in pairs
           if p.get("p_home_prior") is None or p.get("p_home_challenger") is None
           or p.get("home_win") is None]
    return f"INV8: {len(bad)} unpaired evaluation row(s) {bad[:4]}" if bad else None


def inv9_no_retroactive_relabel(card_path, recorded_sha, information_class, recorded_class):
    if recorded_class is not None and information_class != recorded_class:
        return (f"INV9: {card_path} is now class {information_class} but was registered as "
                f"{recorded_class} — cards are not retroactively relabelled")
    if recorded_sha is not None and os.path.exists(os.path.join(BASE, card_path)):
        got = hashlib.sha256(open(os.path.join(BASE, card_path), "rb").read()).hexdigest()
        if got != recorded_sha:
            return f"INV9: {card_path} was restamped ({got[:12]} vs registered {recorded_sha[:12]})"
    return None


def inv10_all_cap_rows_have_no_action_authority(rec):
    if rec.get("starter_information_class") == "ALL_CAP_BASELINE":
        if rec.get("action_authority", "NONE") != "NONE":
            return (f"INV10: an ALL_CAP_BASELINE row carries action_authority "
                    f"{rec.get('action_authority')!r}")
    return None


def check_invariants(rec, rows=None, slate_date=None, feature_names=None, coefficients=None,
                     baseline_ids=None, challenger_ids=None, pairs=None,
                     card_path=None, recorded_sha=None, recorded_class=None,
                     tier_filter=DEFAULT_TIER_FILTER):
    """Every invariant that the supplied evidence permits checking. Missing evidence never turns
    into a pass: a check that cannot run is reported as NOT_CHECKED, never silently skipped."""
    fails, notchecked = [], []
    for name, fn in (
        ("INV1", lambda: inv1_prior_cutoff_precedes_first_pitch(rec)),
        ("INV3", lambda: inv3_zero_residual_equals_prior(rec)),
        ("INV4", lambda: inv4_adjustment_is_in_log_odds(rec)),
        ("INV5", lambda: inv5_probabilities_finite_and_open(rec)),
        ("INV10", lambda: inv10_all_cap_rows_have_no_action_authority(rec)),
    ):
        r = fn()
        if r:
            fails.append(r)
    for k in REQUIRED_FIELDS:
        if k not in rec:
            fails.append(f"REQUIRED FIELD MISSING: {k}")
    if rows is not None or slate_date is not None:
        r = inv2_prior_reconstructs(rec, rows, slate_date, tier_filter)
        if r:
            fails.append(r)
    else:
        notchecked.append("INV2 (no historical pool supplied)")
    if feature_names is not None:
        r = inv6_no_market_fields_in_features(feature_names)
        if r:
            fails.append(r)
    else:
        notchecked.append("INV6 (no feature list supplied)")
    if coefficients is not None:
        r = inv6b_residual_has_no_free_intercept(coefficients)
        if r:
            fails.append(r)
    else:
        notchecked.append("INV6b (no residual coefficient set supplied)")
    if baseline_ids is not None or challenger_ids is not None:
        r = inv7_baseline_and_challenger_registered_together(baseline_ids, challenger_ids)
        if r:
            fails.append(r)
    else:
        notchecked.append("INV7 (no registration sets supplied)")
    if pairs is not None:
        r = inv8_evaluation_is_paired(pairs)
        if r:
            fails.append(r)
    else:
        notchecked.append("INV8 (no evaluation pairs supplied)")
    if card_path is not None:
        r = inv9_no_retroactive_relabel(card_path, recorded_sha, rec.get("starter_information_class"),
                                        recorded_class)
        if r:
            fails.append(r)
    else:
        notchecked.append("INV9 (no card binding supplied)")
    return (not fails), fails, notchecked


def selftest():
    f = []
    ROWS = ([{"status": "final", "date": "2026-04-0%d" % (i + 1), "game_id": f"g{i}",
              "home_win": str(i % 2), "source_tier": "1"} for i in range(10)] +
            [{"status": "final", "date": "2026-04-05", "game_id": "t3", "home_win": "1",
              "source_tier": "3"},
             {"status": "postponed", "date": "2026-04-06", "game_id": "pp", "home_win": "",
              "source_tier": "1"},
             # a postponed game that nonetheless carries an outcome value: ONLY the status check can
             # exclude this one, so it isolates that rule from the blank-outcome guard
             {"status": "postponed", "date": "2026-04-07", "game_id": "pp2", "home_win": "1",
              "source_tier": "1"},
             {"status": "final", "date": "2026-05-01", "game_id": "same", "home_win": "1",
              "source_tier": "1"}])

    # --- the prior ----------------------------------------------------------------------------
    pr = home_prior("2026-05-01", ROWS)
    if pr["prior_games_n"] != 10:
        f.append(f"prior pool held {pr['prior_games_n']} rows; expected the 10 tier-1 finals dated "
                 f"before the slate")
    # SAME-DAY LEAKAGE: the slate's own result must never enter its own prior
    if any(r.get("game_id") == "same" for r in prior_pool("2026-05-01", ROWS)):
        f.append("a game dated ON the slate date entered that slate's prior")
    # tier filter
    if any(r.get("source_tier") == "3" for r in prior_pool("2026-05-01", ROWS)):
        f.append("a tier-3 row entered the prior pool under the tier-1 filter")
    if home_prior("2026-05-01", ROWS, tier_filter=None)["prior_games_n"] != 11:
        f.append("disabling the tier filter did not widen the pool")
    # a postponed game is not a completed game
    for gid in ("pp", "pp2"):
        if any(r.get("game_id") == gid for r in prior_pool("2026-05-01", ROWS, tier_filter=None)):
            f.append(f"a postponed game ({gid}) entered the prior pool")
    # smoothing: 5 of 10 with a 20-count pull toward .5 is exactly .5
    if abs(pr["p_home_prior"] - 0.5) > 1e-12:
        f.append(f"a 5-5 pool did not give a .5 prior: {pr['p_home_prior']}")
    # an EMPTY pool must be exactly .5, so logit is exactly 0 and INV3 is checkable
    e = home_prior("2026-01-01", ROWS)
    if e["prior_games_n"] != 0 or e["p_home_prior"] != 0.5:
        f.append(f"an empty pool gave p={e['p_home_prior']} n={e['prior_games_n']}")
    # smoothing actually pulls: an all-home 4-game pool must land between .5 and 1
    allh = [{"status": "final", "date": "2026-04-0%d" % (i + 1), "game_id": f"h{i}",
             "home_win": "1", "source_tier": "1"} for i in range(4)]
    ph = home_prior("2026-05-01", allh)["p_home_prior"]
    if not (0.5 < ph < 1.0):
        f.append(f"a 4-0 pool gave an unsmoothed prior {ph}")
    if ph >= 4 / 4:
        pass
    if abs(ph - (4 + 10.0) / (4 + 20.0)) > 1e-12:
        f.append(f"smoothing formula wrong: {ph}")
    # the pool hash must depend on the OUTCOMES, not just the ids
    flipped = [dict(r, home_win="1") for r in prior_pool("2026-05-01", ROWS)]
    if pool_hash(flipped) == pr["prior_source_hash"]:
        f.append("the prior source hash does not change when the pooled outcomes change")

    # --- composition --------------------------------------------------------------------------
    if abs(combine(0.5, 0.0) - 0.5) > 1e-15:
        f.append("combine is not the identity at a .5 prior with a zero residual")
    if abs(combine(0.62, 0.0) - 0.62) > 1e-15:
        f.append("combine is not the identity at an arbitrary prior with a zero residual")
    # LOG-ODDS, NOT PROBABILITY. +0.05 applied to .52 and to .97 must move them by different amounts.
    d1 = combine(0.52, 0.05) - 0.52
    d2 = combine(0.97, 0.05) - 0.97
    if abs(d1 - d2) < 1e-6:
        f.append("a fixed residual moves a .52 and a .97 prior by the same amount — the addition is "
                 "happening in probability space, not log-odds")
    for pp, dd in ((0.999, 50.0), (0.001, -50.0), (0.5, 700.0), (0.5, -700.0)):
        c = combine(pp, dd)
        if not (0.0 < c < 1.0):
            f.append(f"combine({pp}, {dd}) = {c!r} escaped the open unit interval")
        if inv5_probabilities_finite_and_open({"p_home_prior": pp, "p_home_challenger": c,
                                               "delta_logit_from_prior": dd}) is not None:
            f.append(f"a saturating composition produced a record INV5 rejects: {pp} {dd} -> {c}")
    # symmetry: the same residual with opposite sign is symmetric about the prior in log-odds
    if abs(logit(combine(0.4, 1.3)) - logit(0.4) - 1.3) > 1e-12:
        f.append("combine does not add exactly in log-odds")

    # --- a well-formed registered record --------------------------------------------------------
    prior_rec = home_prior("2026-05-01", ROWS)
    rec = forecast(prior_rec, 0.35, model_id="mlb.baseline_offset.v0_1",
                   feature_cutoff_utc="2026-05-01T00:00:00Z",
                   training_snapshot_hash="deadbeef", game_start_utc="2026-05-01T23:05:00Z",
                   information_class="PARTIAL_STARTER_INFORMATION", information_fraction=0.8,
                   named_cap_slots=1, verified_profile_slots=24)
    ok, ff, nc = check_invariants(rec, rows=ROWS, slate_date="2026-05-01",
                                  feature_names=["home_form", "rest_days", "park_factor"],
                                  baseline_ids=["g1"], challenger_ids=["g1"],
                                  pairs=[{"game_id": "g1", "p_home_prior": .5,
                                          "p_home_challenger": .58, "home_win": 1}])
    if not ok:
        f.append(f"a well-formed record failed its invariants: {ff}")
    for k in REQUIRED_FIELDS:
        if k not in rec:
            f.append(f"forecast() omits required field {k}")

    # --- each invariant, isolated ----------------------------------------------------------------
    if inv1_prior_cutoff_precedes_first_pitch(dict(rec, prior_cutoff_utc="2026-05-02T00:00:00Z")) is None:
        f.append("INV1 passed a prior cutoff AFTER first pitch")
    if inv1_prior_cutoff_precedes_first_pitch(dict(rec, prior_cutoff_utc=rec["game_start_utc"])) is None:
        f.append("INV1 passed a cutoff EQUAL to first pitch; it must be strictly before")
    if inv2_prior_reconstructs(dict(rec, prior_source_hash="0" * 64), ROWS, "2026-05-01") is None:
        f.append("INV2 passed a prior whose bound pool hash does not reconstruct")
    if inv2_prior_reconstructs(dict(rec, prior_games_n=999), ROWS, "2026-05-01") is None:
        f.append("INV2 passed a prior whose game count disagrees with its pool")
    if inv2_prior_reconstructs(rec, ROWS, "2026-05-02") is None:
        f.append("INV2 passed when the pool was taken as of a DIFFERENT date")
    zero = forecast(prior_rec, 0.0, "m", "c", "h", "2026-05-01T23:05:00Z")
    if inv3_zero_residual_equals_prior(dict(zero, p_home_challenger=zero["p_home_prior"] + 1e-9)) is None:
        f.append("INV3 tolerated a challenger drifting from the prior at a zero residual")
    if inv3_zero_residual_equals_prior(zero) is not None:
        f.append("INV3 fired on a correct zero-residual record")
    # INV4 must specifically catch a RAW PROBABILITY ADDITION
    naive = dict(rec, p_home_challenger=rec["p_home_prior"] + rec["delta_logit_from_prior"])
    msg = inv4_adjustment_is_in_log_odds(naive)
    if msg is None:
        f.append("INV4 passed a raw probability addition")
    elif "RAW PROBABILITY ADDITION" not in msg:
        f.append(f"INV4 caught the error but did not name it: {msg}")
    for bad in (float("nan"), float("inf"), 0.0, 1.0, -0.1, 1.2, "0.5", None):
        if inv5_probabilities_finite_and_open(dict(rec, p_home_challenger=bad)) is None:
            f.append(f"INV5 passed p_home_challenger={bad!r}")
    if inv5_probabilities_finite_and_open(dict(rec, delta_logit_from_prior=float("inf"))) is None:
        f.append("INV5 passed an infinite delta_logit")
    # INV6b: NO FREE INTERCEPT in the residual model
    if inv6b_residual_has_no_free_intercept({"home_form": 0.3, "rest_days": -0.1}) is not None:
        f.append("a clean coefficient set was refused by the no-intercept rule")
    for bad in ({"intercept": 0.12, "home_form": 0.3}, {"const": -0.4}, {"bias": 0.01},
                {"b0": 0.9}, {"alpha": 0.2}, {"model_intercept": 0.05}):
        if inv6b_residual_has_no_free_intercept(bad) is None:
            f.append(f"the residual model was allowed an intercept {bad}")
    # a ZEROED intercept is still refused: the term must be ABSENT so a later fit cannot un-pin it
    if inv6b_residual_has_no_free_intercept({"intercept": 0.0, "home_form": 0.3}) is None:
        f.append("an intercept pinned to zero was accepted; the term must be absent, not zeroed")
    if "ABSENT, not" not in inv6b_residual_has_no_free_intercept({"intercept": 0.0}):
        f.append("the zeroed-intercept refusal does not explain why absence is required")
    if inv6b_residual_has_no_free_intercept(None) is None:
        f.append("a missing coefficient set was treated as clean")
    ok6, ff6, nc6 = check_invariants(rec)
    if not any("INV6b" in x for x in nc6):
        f.append("an unsupplied coefficient set was silently skipped instead of reported")
    ok6, ff6, _ = check_invariants(rec, coefficients={"intercept": 0.2})
    if ok6 or not any("INV6b" in x for x in ff6):
        f.append("check_invariants did not run the no-intercept rule")
    for bad in ("close_ml_home", "market_implied_p", "no_vig_prob", "closing-total",
                "book_price", "spread_home"):
        if inv6_no_market_fields_in_features(["home_form", bad]) is None:
            f.append(f"INV6 passed the market feature {bad!r} into the matrix")
    if inv6_no_market_fields_in_features(["home_form", "rest_days", "park_factor",
                                          "starter_k_rate"]) is not None:
        f.append("INV6 rejected a clean feature list")
    if inv7_baseline_and_challenger_registered_together(["a", "b"], ["a"]) is None:
        f.append("INV7 passed a challenger registered on fewer games than the baseline")
    if inv7_baseline_and_challenger_registered_together([], []) is None:
        f.append("INV7 passed an EMPTY registration as if it were paired")
    if inv8_evaluation_is_paired([{"game_id": "x", "p_home_prior": .5, "p_home_challenger": None,
                                   "home_win": 1}]) is None:
        f.append("INV8 passed an evaluation row missing the challenger probability")
    if inv8_evaluation_is_paired([{"game_id": "x", "p_home_prior": .5, "p_home_challenger": .6,
                                   "home_win": None}]) is None:
        f.append("INV8 passed an evaluation row with no outcome")
    if inv9_no_retroactive_relabel("cards/x.json", None, "ALL_CAP_BASELINE",
                                   "PARTIAL_STARTER_INFORMATION") is None:
        f.append("INV9 passed a card whose registered information class was changed")
    if inv9_no_retroactive_relabel("cards/2026-08-22_card.json", "0" * 64, "ALL_CAP_BASELINE",
                                   "ALL_CAP_BASELINE") is None:
        f.append("INV9 passed a card that no longer hashes to its registered bytes")
    if inv10_all_cap_rows_have_no_action_authority(
            {"starter_information_class": "ALL_CAP_BASELINE",
             "action_authority": "GATE_GOVERNED"}) is None:
        f.append("INV10 passed an ALL_CAP_BASELINE row carrying action authority")
    if inv10_all_cap_rows_have_no_action_authority(
            {"starter_information_class": "FULL_STARTER_INFORMATION",
             "action_authority": "GATE_GOVERNED"}) is not None:
        f.append("INV10 fired on a non-baseline row")

    # a check that cannot run must be REPORTED, never counted as a pass
    ok2, ff2, nc2 = check_invariants(rec)
    if not any("INV2" in x for x in nc2) or not any("INV6" in x for x in nc2):
        f.append(f"unrunnable invariants were silently skipped instead of reported: {nc2}")
    # a missing required field fails
    ok3, ff3, _ = check_invariants({k: v for k, v in rec.items() if k != "model_id"})
    if not any("model_id" in x for x in ff3):
        f.append("a record missing model_id passed the required-field check")

    print("baseline_offset selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("same-day results leak into their own prior",
     '        if (r.get("date") or "") >= slate_date:', '        if (r.get("date") or "") > slate_date:'),
    ("the tier filter is dropped and legacy tier-2/3 rows build the intercept",
     '        if tier_filter is not None and str(r.get("source_tier", "")) not in tier_filter:',
     "        if False:"),
    ("postponed games counted as completed",
     '        if str(r.get("status", "")).lower() != "final":', "        if False:"),
    ("the prior is unsmoothed, so an early-season pool gives a degenerate intercept",
     "    p = (wins + pseudo_count * pseudo_center) / (n + pseudo_count)",
     "    p = (wins / n) if n else 0.5"),
    ("the prior source hash ignores the pooled OUTCOMES",
     '    payload = [[r.get("game_id"), r.get("date"), int(r["home_win"])] for r in pool]',
     '    payload = [[r.get("game_id"), r.get("date")] for r in pool]'),
    ("the adjustment is applied in PROBABILITY space",
     "    z = logit(p_prior) + residual_logit\n    return min(max(expit(z), EPS), 1.0 - EPS)",
     "    return min(max(p_prior + residual_logit, EPS), 1.0 - EPS)"),
    ("the composition is left unclamped and may reach certainty",
     "    return min(max(expit(z), EPS), 1.0 - EPS)", "    return expit(z)"),
    ("INV1 accepts a cutoff equal to first pitch",
     "    if not (c < g):", "    if not (c <= g):"),
    ("INV1 removed", "    if not (c < g):", "    if False:"),
    ("INV2 stops comparing the pool hash",
     '    if pool_hash(pool) != rec.get("prior_source_hash"):', "    if False:"),
    ("INV2 stops comparing the pool SIZE",
     '    if rec.get("prior_games_n") != len(pool):', "    if False:"),
    ("INV3 tolerates drift at a zero residual", "        if d > tol:", "        if d > 1e-3:"),
    ("INV4 removed — a raw probability addition passes",
     "    if abs(want - rec[\"p_home_challenger\"]) > tol:", "    if False:"),
    ("INV4 no longer names a raw probability addition",
     '        hint = " (it matches a RAW PROBABILITY ADDITION)" if abs(naive - rec["p_home_challenger"]) <= tol else ""',
     '        hint = ""'),
    ("INV5 allows probabilities at the closed boundary",
     "        if not (0.0 < v < 1.0):", "        if not (0.0 <= v <= 1.0):"),
    # NOT A MUTANT, deliberately. The open-interval predicate `not (0.0 < v < 1.0)` is already True
    # for nan and for both infinities, so the explicit finiteness check on p cannot be isolated by
    # any fixture. It is kept for the clearer error message, and is recorded here as redundant
    # defence rather than dressed up with a mutant that appears to kill. The finiteness check on
    # delta_logit_from_prior is NOT redundant — there is no range bound on a log-odds shift — and it
    # has its own mutant below.
    ("INV5 stops checking a non-finite delta_logit",
     '    if d is None or math.isnan(d) or math.isinf(d):', "    if d is None:"),
    ("INV5 accepts a non-numeric probability",
     "        if v is None or not isinstance(v, (int, float)) or isinstance(v, bool):", "        if False:"),
    ("INV6 lets market fields into the feature matrix",
     "        if any(t in MARKET_TOKENS for t in toks):", "        if False:"),
    ("INV6 matches only whole names, so close_ml_home slips through",
     '        toks = str(name).lower().replace("-", "_").split("_")',
     "        toks = [str(name).lower()]"),
    ("the residual model may carry a free intercept, relearning the base rate",
     "        if n in intercept_names or n.endswith(\"intercept\"):", "        if False:"),
    ("a zeroed intercept is accepted, leaving a term a later fit can un-pin",
     "            if value not in (0, 0.0, None):", "            if True:"),
    ("a missing coefficient set is treated as clean",
     "    if coefficients is None:\n        return \"INV6b: no coefficient set supplied;",
     "    if False:\n        return \"INV6b: no coefficient set supplied;"),
    ("INV6b is silently skipped when no coefficients are supplied",
     '        notchecked.append("INV6b (no residual coefficient set supplied)")', "        pass"),
    ("INV7 accepts a challenger registered on a different game set",
     "    if b != c:", "    if b < c:"),
    ("INV7 accepts an empty registration as paired", "    if not b:", "    if False:"),
    ("INV8 accepts unpaired evaluation rows",
     '    bad = [p.get("game_id") for p in pairs\n           if p.get("p_home_prior") is None or p.get("p_home_challenger") is None\n           or p.get("home_win") is None]',
     "    bad = []"),
    ("INV9 accepts a retroactive relabel",
     "    if recorded_class is not None and information_class != recorded_class:", "    if False:"),
    ("INV9 accepts a restamped card artifact", "        if got != recorded_sha:", "        if False:"),
    ("INV10 lets an all-CAP row carry action authority",
     '        if rec.get("action_authority", "NONE") != "NONE":', "        if False:"),
    ("a missing required field is no longer a failure",
     "    for k in REQUIRED_FIELDS:\n        if k not in rec:\n            fails.append(f\"REQUIRED FIELD MISSING: {k}\")",
     "    for k in ():\n        pass"),
    ("an unrunnable invariant is silently skipped instead of reported",
     '        notchecked.append("INV2 (no historical pool supplied)")', "        pass"),
]


def mutation_suite(verbose=True):
    import subprocess as _sp, tempfile as _tf
    src = open(os.path.abspath(__file__)).read()
    i = src.index("MUTANTS = [")
    j = src.index("\ndef mutation_suite", i)
    head, block, tail = src[:i], src[i:j], src[j:]
    surv, unapp = [], []
    for name, old, new in MUTANTS:
        where = "head" if old in head else ("tail" if old in tail else None)
        if where is None:
            unapp.append(f"{name}: pattern not found"); continue
        mut = (head.replace(old, new, 1) + block + tail) if where == "head" \
            else (head + block + tail.replace(old, new, 1))
        if mut == src:
            unapp.append(f"{name}: no-op"); continue
        with _tf.NamedTemporaryFile("w", suffix="_mutant.py", delete=False,
                                    dir=os.path.dirname(os.path.abspath(__file__))) as fh:
            fh.write(mut); path = fh.name
        try:
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True, timeout=180)
            killed = pr.returncode != 0
        except _sp.TimeoutExpired:
            killed = True
        finally:
            os.unlink(path)
        if verbose:
            print(f"  {'KILLED  ' if killed else 'SURVIVED'}  {name}")
        if not killed:
            surv.append(name)
    for u in unapp:
        print(f"  UNAPPLIED  {u}")
    print(f"mutation suite: {len(MUTANTS)-len(surv)-len(unapp)}/{len(MUTANTS)} killed"
          f"{'' if not (surv or unapp) else '  — SURVIVORS MEAN DECORATIVE FIXTURES'}")
    return surv + unapp


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    if "--mutants" in sys.argv:
        sys.exit(1 if mutation_suite() else 0)
    if "--prior" in sys.argv:
        d = sys.argv[sys.argv.index("--prior") + 1]
        print(json.dumps(home_prior(d), indent=1))
        sys.exit(0)
    print(__doc__)
