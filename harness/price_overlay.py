#!/usr/bin/env python3
"""PRICE OVERLAY — what a price may do to a frozen board, and the five things a selection needs.

OWNER CORRECTIONS 1, 2 AND 5 (2026-08-24).

1. SAY WHAT IS TRUE. I wrote "no prices exist for this slate." That is almost certainly false —
   sportsbooks priced these games. What is true is that no price entered the admissible evidence
   package. The difference matters: "no prices exist" is a claim about the world that I cannot
   support and that happens to flatter the gap; NO_ELIGIBLE_CAPTURED_PRICE_BOARD is a claim about
   MY evidence, which is the only thing I can actually check.

2. THE BOARD NEVER BECOMES A BETTING CARD. A later capture produces a SEPARATE overlay artifact with
   its own capture instant and its own hash, referencing the frozen board hash. It may not mutate a
   single probability, arm, dose or seal on the board it points at. A board that could turn into a
   card under a later capture is a board whose probabilities were never really frozen.

   And a price enables EVALUATION, not EXECUTION. Real-money authorization is a separate gate with a
   separate owner and it stays BLOCKED regardless of what any overlay computes. There is no path in
   this module that grants execution and there is no argument that produces one.

3. A PRICE ALONE IS NOT A SELECTION. Five things are required: model probability, price, EV,
   PER-GAME model uncertainty, and stated risk. The board carries cross-game dispersion, which is a
   property of the slate and explicitly NOT an uncertainty — so on today's board the fourth
   requirement is simply absent, and no overlay could issue a selection even with a full price sheet.
   Monte Carlo error is not model uncertainty either: it measures how well the simulation converged,
   not how wrong the model may be, and conflating them would let more draws masquerade as more
   knowledge. They are separate fields and this module refuses a selection that supplies one for the
   other.

API
  price_eligibility(boards)             -> which captured boards may inform market probability
  overlay_contract(overlay, board_hash) -> may this overlay attach to that frozen board?
  selection_ready(row)                  -> (bool, missing) against the five requirements
"""
from __future__ import annotations

import json
import os
import sys

# --- status vocabulary, exactly as the owner specified ---------------------------------------------
NO_ELIGIBLE_BOARD = "NO_ELIGIBLE_CAPTURED_PRICE_BOARD"
EV_NOT_COMPUTABLE = "EV_NOT_COMPUTABLE"
ACTION_AUTHORITY_NONE = "ACTION_AUTHORITY_NONE"
ELIGIBLE = "ELIGIBLE_CAPTURED_PRICE_BOARD"

# --- overlay contract ------------------------------------------------------------------------------
OVERLAY_OK = "OVERLAY_MAY_ATTACH"
OVERLAY_NO_BOARD_REF = "OVERLAY_DOES_NOT_REFERENCE_A_FROZEN_BOARD"
OVERLAY_BOARD_MISMATCH = "OVERLAY_REFERENCES_A_DIFFERENT_BOARD"
OVERLAY_NO_CAPTURE_INSTANT = "OVERLAY_HAS_NO_CAPTURE_INSTANT"
OVERLAY_NO_HASH = "OVERLAY_HAS_NO_HASH"
OVERLAY_WOULD_MUTATE = "OVERLAY_WOULD_MUTATE_THE_FROZEN_BOARD"
OVERLAY_CLAIMS_EXECUTION = "OVERLAY_CLAIMS_EXECUTION_AUTHORITY"

#: Fields that belong to the frozen board. An overlay carrying any of them is trying to rewrite it.
FROZEN_BOARD_FIELDS = ("p_home", "winner_probability", "projected_total", "projected_home_margin",
                       "arm", "resolved_information_dose", "information_class", "simulation_seed",
                       "simulation_trials", "evidence_sha256", "total_distribution")

#: SAME-BOOK ELIGIBILITY, corrected 2026-08-24. I previously used an ABSOLUTE band of 3.5%-7.5%,
#: generalised from one observation of one market type. It is wrong, and it would have rejected a
#: genuine single-book DraftKings board: that board's ten MLB moneylines hold 1.637%-1.869%, because
#: a modern two-way MLB moneyline at a sharp book is far tighter than the 4-6% seen elsewhere.
#:
#: The test that actually discriminates one book from many is HOMOGENEITY WITHIN A MARKET TYPE, which
#: is the test that caught the 2026-08-23 board — that one was BIMODAL, eight rows at 4.5-4.8% and
#: seven at 1.6-2.0%, a 3.11pp spread that no single book produces. A real book's overround varies
#: only by the granularity of its price grid, which is a few tenths of a point.
#:
#: Two conditions, both absolute and neither fitted to a board:
#:   the spread within a market type stays under one percentage point of overround; and
#:   the level sits above the best-odds regime, which the 2026-08-03 ruling put at 0.4%-0.6%.
#: PREGAME POLICY AMENDMENT v2, 2026-08-24. NOT the originally registered rule — v1 was the absolute
#: 3.5%-7.5% band, and this supersedes it in a dated amendment rather than pretending to have always
#: been the contract.
#:
#: v1 was too narrow and would have rejected a valid board. Homogeneity alone, which was my first
#: fix, is too permissive in the other direction: a uniformly absurd 20% hold board is perfectly
#: homogeneous and would sail through. The gate needs BOTH dimensions — a plausible LEVEL for the
#: market and a tight SPREAD within it — plus the identity checks that make "one book" checkable
#: rather than asserted.
HOLD_POLICY_VERSION = "v2-2026-08-24"
HOLD_POLICY_SUPERSEDES = ("supersedes v1: the absolute SAME_BOOK_OVERROUND band [0.035, 0.075] registered 2026-08-03, which would have rejected a valid single-book board")

SAME_BOOK_MAX_OVERROUND_SPREAD_PP = 0.010
BEST_ODDS_CEILING = 0.010

# --- EXECUTABLE THRESHOLDS, BY SPORT x MARKET x PRICE BAND ----------------------------------------
#: The owner's next correction: "a plausible level band" is not a policy until the numbers are on the
#: page. Two market types are not enough of a partition either — an MLB moneyline and a WNBA
#: moneyline are the SAME market type and behave nothing alike (1.6-1.9% against 4.3-4.8%), and
#: within one sport the hold climbs with the favourite's price. So the stratum is
#: (sport, market, price band), and the band is DERIVED, not asserted.
#:
#: PRICE BANDS, cut on the FAVOURITE's American price. The cuts are round numbers and are a policy
#: choice; what is not a choice is that a stratum must be cut somewhere, because hold and price move
#: together.
PRICE_BANDS = (("NEAR_PICKEM", -135), ("MODERATE_FAVORITE", -250), ("HEAVY_FAVORITE", -600),
               ("EXTREME_FAVORITE", None))


def price_band(favorite_american):
    """The band a two-way market sits in, keyed on the FAVOURITE side's price."""
    f = _num(favorite_american)
    if f is None:
        return None
    for name, floor in PRICE_BANDS:
        if floor is None or f >= floor:
            return name
    return PRICE_BANDS[-1][0]


def equal_price_equivalent(hold):
    """The American price a book would have to quote on BOTH sides to produce this overround.

    This is what makes a ceiling legible instead of arbitrary. A 20% overround is not an abstraction:
    it is a book quoting -150 on both sides of a coin flip. Anyone can see that is off-market.
    """
    h = _num(hold)
    if h is None or h >= 1.0:
        return None
    return -100.0 * (1.0 + h) / (1.0 - h)


#: STRUCTURAL LIMITS — true of any two-way market, independent of sport, book or board.
#: A non-positive overround is not a tight book, it is an arbitrage or a transcription error, and
#: either way the board is not a market. The ceiling is stated as an equal-price equivalent so it can
#: be argued with: -150 on both sides of a two-way market.
STRUCTURAL_HOLD_FLOOR = 0.0                       # strictly greater than
STRUCTURAL_CEILING_EQUAL_PRICE = -150.0
STRUCTURAL_HOLD_CEILING = 0.20                    # = (150-100)/(150+100)
NON_POSITIVE_HOLD = "REFUSED_NON_POSITIVE_OVERROUND_ARBITRAGE_OR_TRANSCRIPTION_ERROR"

#: CALIBRATION POLICY. A band fitted to a handful of quotes is a description of those quotes, so:
#:   - fewer than MIN_OBS_TO_CALIBRATE quotes in a stratum yields NO band. The stratum is
#:     UNCALIBRATED and the gate REFUSES rather than passes — the failure mode to avoid is a stratum
#:     with one observation silently becoming a zero-width band that admits only itself.
#:   - the allowance factor widens the observed range so one board is not mistaken for the
#:     population. It is a POLICY CHOICE and is recorded as one; it is not fitted to anything.
MIN_OBS_TO_CALIBRATE = 3
ALLOWANCE_FACTOR = 1.75
#: A dispersion ceiling cannot be tighter than the book's own price grid, or a perfectly ordinary
#: one-tick difference between two games would read as two books. TICK_ALLOWANCE_PP is derived
#: below from what a single 1-point American move actually does to a two-way overround.
TICK_PROBE = (-110, -110)
DISPERSION_FLOOR_TICKS = 2

UNCALIBRATED = "UNCALIBRATED_INSUFFICIENT_OBSERVATIONS_IN_STRATUM"
IMPLAUSIBLE_LEVEL = "OVERROUND_LEVEL_OUTSIDE_PLAUSIBLE_BAND_FOR_THIS_MARKET"
UNVERIFIED_BOOK = "SPORTSBOOK_IDENTITY_OR_QUOTE_LINKS_UNVERIFIED"


def _two_way_overround(a, b):
    """Overround of a two-way American market. Local, so this module does not import a screener."""
    def imp(o):
        o = float(o)
        return (-o) / ((-o) + 100.0) if o < 0 else 100.0 / (o + 100.0)
    return imp(a) + imp(b) - 1.0


def tick_pp(probe=TICK_PROBE):
    """How much one point of American price moves a two-way overround, in percentage points.

    This is what stops a dispersion ceiling from being tighter than the book's own price grid: two
    games one tick apart are one book, not two, and a ceiling below this would say otherwise.
    """
    a, b = probe
    return abs(100.0 * _two_way_overround(a - 1, b) - 100.0 * _two_way_overround(a, b))


def calibrate_stratum(overrounds, factor=ALLOWANCE_FACTOR, min_obs=MIN_OBS_TO_CALIBRATE):
    """Derive one stratum's level band and dispersion ceiling from observed quotes.

    Returns a dict that always states n, the observed range, and whether it is usable. An
    UNCALIBRATED stratum is not a permissive stratum: nothing passes there.
    """
    vals = sorted(v for v in (_num(x) for x in (overrounds or [])) if v is not None)
    out = {"n": len(vals), "min_obs_to_calibrate": min_obs, "allowance_factor": factor}
    if vals:
        out.update(observed_min=vals[0], observed_max=vals[-1],
                   observed_spread_pp=100.0 * (vals[-1] - vals[0]))
    if len(vals) < min_obs:
        out.update(status=UNCALIBRATED, level_band=None, dispersion_ceiling_pp=None,
                   why=(f"{len(vals)} quote(s) in this stratum, below {min_obs}. A band fitted to "
                        f"this many quotes describes the quotes, not the market. The stratum "
                        f"REFUSES; it does not wave things through."))
        return out
    lo = max(vals[0] / factor, STRUCTURAL_HOLD_FLOOR)
    hi = min(vals[-1] * factor, STRUCTURAL_HOLD_CEILING)
    disp = max(100.0 * (vals[-1] - vals[0]) * factor, DISPERSION_FLOOR_TICKS * tick_pp())
    out.update(status="CALIBRATED", level_band=(lo, hi), dispersion_ceiling_pp=disp,
               level_band_equal_price=(equal_price_equivalent(lo), equal_price_equivalent(hi)),
               why=(f"observed [{vals[0]:.6f}, {vals[-1]:.6f}] over {len(vals)} quotes, widened by "
                    f"x{factor} and clipped to the structural ceiling {STRUCTURAL_HOLD_CEILING} "
                    f"(equal price {STRUCTURAL_CEILING_EQUAL_PRICE:+.0f})"))
    return out


def stratum_key(sport, market, favorite_american):
    return (str(sport).lower(), str(market).upper(), price_band(favorite_american))


def level_gate(hold_value, stratum):
    """(ok, why) for ONE quote against its stratum. Structural limits first, then the derived band."""
    h = _num(hold_value)
    if h is None:
        return False, "no overround supplied"
    if h <= STRUCTURAL_HOLD_FLOOR:
        return False, (f"{NON_POSITIVE_HOLD}: overround {h:.6f}. A two-way market at or below zero "
                       f"is arbitrageable, which means it is not one book's market.")
    if h > STRUCTURAL_HOLD_CEILING:
        return False, (f"{IMPLAUSIBLE_LEVEL}: overround {h:.6f} exceeds the structural ceiling "
                       f"{STRUCTURAL_HOLD_CEILING} — a book quoting "
                       f"{equal_price_equivalent(h):+.0f} on both sides of a two-way market.")
    if not stratum or stratum.get("status") != "CALIBRATED":
        return False, (f"{UNCALIBRATED}: this stratum has "
                       f"{(stratum or {}).get('n', 0)} observation(s) and no derived band, so no "
                       f"quote in it can be validated. Not calibrated is not permissive.")
    lo, hi = stratum["level_band"]
    if not (lo <= h <= hi):
        return False, (f"{IMPLAUSIBLE_LEVEL}: overround {h:.6f} outside the derived band "
                       f"[{lo:.6f}, {hi:.6f}] (equal prices "
                       f"{equal_price_equivalent(lo):+.0f} to {equal_price_equivalent(hi):+.0f})")
    return True, None

# --- selection requirements ------------------------------------------------------------------------
SELECTION_REQUIREMENTS = ("model_probability", "price", "expected_value",
                          "model_uncertainty", "stated_risk")
MC_IS_NOT_UNCERTAINTY = "MONTE_CARLO_ERROR_SUPPLIED_AS_MODEL_UNCERTAINTY"

EXECUTION_BLOCKED = "EXECUTION_BLOCKED_REAL_MONEY_AUTHORIZATION_IS_A_SEPARATE_GATE"


def _num(x):
    if x is None or isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def market_homogeneity(overrounds, market="default", stratum=None):
    """(ok, detail) for one market type: plausible LEVEL and tight SPREAD, both required."""
    vals = [v for v in (_num(x) for x in (overrounds or [])) if v is not None]
    if len(vals) < 2:
        return None, {"n": len(vals), "reason": "fewer than two priced markets; homogeneity is "
                                                "undefined and is not assumed"}
    lo, hi = min(vals), max(vals)
    mean = sum(vals) / len(vals)
    spread = hi - lo
    detail = {"n": len(vals), "mean_overround": mean, "min": lo, "max": hi, "spread_pp": spread}
    if mean < BEST_ODDS_CEILING:
        detail["reason"] = (f"mean overround {mean:.4f} is at or below the best-odds regime "
                            f"({BEST_ODDS_CEILING}); a cross-book best-of board cannot support a "
                            f"de-vigged market probability")
        return False, detail
    # LEVEL — against the stratum's DERIVED band when one exists, and against the structural limits
    # always. `stratum` is passed in by the caller because only the caller knows the price band.
    # NEVER calibrate from the board under test: a stratum fitted to these very quotes admits them
    # by construction and the gate becomes a tautology.
    st = stratum if stratum is not None else lookup_stratum(market_label=market)
    detail["stratum"] = {k: st.get(k) for k in ("n", "status", "level_band",
                                                "dispersion_ceiling_pp", "why")}
    ok_level, why_level = level_gate(mean, st)
    if not ok_level:
        detail["reason"] = why_level
        return False, detail
    # SPREAD — against the stratum's derived dispersion ceiling, floored at the book's price grid
    ceiling = st.get("dispersion_ceiling_pp")
    if ceiling is None:
        detail["reason"] = f"{UNCALIBRATED}: no dispersion ceiling derived for this stratum"
        return False, detail
    if 100.0 * spread > ceiling:
        detail["reason"] = (f"overround spread {100.0 * spread:.4f}pp exceeds this stratum's "
                            f"dispersion ceiling {ceiling:.4f}pp; a single book varies only by its "
                            f"price grid ({tick_pp():.4f}pp per point), so this board holds more "
                            f"than one population")
        return False, detail
    return True, detail


#: THE REGISTERED STRATUM TABLE. Derived ONCE, from the 2026-08-24 DraftKings capture, and frozen
#: as part of hold policy v2. It is NOT recomputed from the board being judged — a stratum calibrated
#: from its own board admits that board by construction, and the level test would then be a
#: tautology dressed as a gate. That was a live defect in my first draft of this section and it is
#: exactly the masked-fixture failure mode: the check could not fail.
#:
#: Because the calibration source IS the 8/24 board, judging the 8/24 board against this table is
#: still circular at the policy level. That circularity is not hidden — it is labelled
#: CALIBRATION_SOURCE_SELF_REFERENTIAL, and a board so labelled may not cite the level test as
#: independent evidence of anything. The table becomes real evidence only once a second, independent
#: single-book capture has passed through it.
HOLD_STRATA_CALIBRATION_SOURCE = "PRICE-BOARD-2026-08-24-DRAFTKINGS"
HOLD_STRATA_STATUS = "PROVISIONAL_SINGLE_BOARD_CALIBRATION"
SELF_REFERENTIAL = "CALIBRATION_SOURCE_SELF_REFERENTIAL"

#: (sport, MARKET, PRICE_BAND) -> the observed overrounds the band was derived from. Storing the
#: OBSERVATIONS rather than the derived numbers means the derivation is re-runnable and a reader can
#: check the arithmetic instead of trusting a literal.
HOLD_STRATA_OBSERVATIONS = {
    ("mlb", "MONEYLINE", "NEAR_PICKEM"):
        [0.018688, 0.018688, 0.017864, 0.016743, 0.016743],
    ("mlb", "MONEYLINE", "MODERATE_FAVORITE"):
        [0.017137, 0.017261, 0.016373, 0.017966, 0.017822],
    ("mlb", "TOTAL_OU", "NEAR_PICKEM"):
        [0.045867, 0.047079, 0.045210, 0.047079, 0.047273,
         0.047533, 0.047619, 0.044599, 0.047079, 0.046235],
    ("wnba", "MONEYLINE", "MODERATE_FAVORITE"): [0.042677],
    ("wnba", "MONEYLINE", "HEAVY_FAVORITE"): [0.047619],
    ("wnba", "TOTAL_OU", "NEAR_PICKEM"): [0.047079, 0.047619],
    ("wnba", "SPREAD", "NEAR_PICKEM"): [0.047079, 0.047533],
}

#: legacy market labels, so a caller passing "mlb_moneyline" still resolves to a real stratum
MARKET_ALIASES = {
    "mlb_moneyline": ("mlb", "MONEYLINE"),
    "wnba_moneyline": ("wnba", "MONEYLINE"),
    "mlb_total": ("mlb", "TOTAL_OU"),
    "wnba_total": ("wnba", "TOTAL_OU"),
}


def hold_strata():
    """The registered table, derived from the recorded observations. Re-runnable, not a literal."""
    return {k: calibrate_stratum(v) for k, v in HOLD_STRATA_OBSERVATIONS.items()}


def lookup_stratum(sport=None, market=None, favorite_american=None, market_label=None):
    """Find the REGISTERED stratum for a quote. Returns None when none is registered — and None
    means refuse, never 'derive one from whatever is in front of you'."""
    if sport is None and market_label:
        sport, market = MARKET_ALIASES.get(str(market_label).lower(), (None, None))
    if sport is None or market is None:
        return None
    band = price_band(favorite_american) if favorite_american is not None else None
    table = hold_strata()
    if band is not None:
        return table.get((str(sport).lower(), str(market).upper(), band))
    # no price band supplied: only answer if EVERY registered band for this sport+market agrees on
    # calibration status, so an unbanded caller cannot accidentally pick the permissive one
    cands = [v for k, v in table.items()
             if k[0] == str(sport).lower() and k[1] == str(market).upper()]
    if not cands:
        return None
    cal = [c for c in cands if c["status"] == "CALIBRATED"]
    if len(cal) != len(cands):
        return dict(cands[0], status=UNCALIBRATED, level_band=None, dispersion_ceiling_pp=None,
                    why=f"{len(cands) - len(cal)} of {len(cands)} price bands in this sport+market "
                        f"are uncalibrated and no price band was supplied to disambiguate")
    lo = min(c["level_band"][0] for c in cal)
    hi = max(c["level_band"][1] for c in cal)
    return {"n": sum(c["n"] for c in cal), "status": "CALIBRATED", "level_band": (lo, hi),
            "level_band_equal_price": (equal_price_equivalent(lo), equal_price_equivalent(hi)),
            "dispersion_ceiling_pp": min(c["dispersion_ceiling_pp"] for c in cal),
            "why": "union of every calibrated price band in this sport+market; the tightest "
                   "dispersion ceiling is kept so the union is not more permissive than its parts"}


# --- SECTION 8: MARKET PHASE ---------------------------------------------------------------------
#: The 2026-08-25 lesson, made executable. A quote captured after actual start is not a stale offer,
#: it is not an offer, and combining a live price with a frozen pregame probability compares a
#: number that knows the first three innings against one that does not.
MARKET_PHASES = ("PRE_GAME", "LIVE", "HALFTIME", "FINAL", "UNVERIFIED")
PREGAME_ONLY = "PRE_GAME"
LIVE_IN_PREGAME = "LIVE_PRICE_IN_A_PREGAME_OVERLAY"
UNVERIFIED_PHASE = "MARKET_PHASE_UNVERIFIED_MAY_NOT_AUTHORIZE"
POST_START_QUOTE = "QUOTE_CAPTURED_AFTER_ACTUAL_START"
CROSS_BOOK_HOLD = "CROSS_BOOK_PRICES_USED_FOR_SAME_BOOK_HOLD"
OPENING_CURRENT_MIXED = "OPENING_AND_CURRENT_PRICES_NOT_SEPARATED"


def market_phase(captured_at_utc, actual_start_utc, declared_phase=None):
    """(phase, ok_for_pregame, why). The clock decides; a declared phase may only be stricter."""
    if not captured_at_utc or not actual_start_utc:
        return "UNVERIFIED", False, (f"{UNVERIFIED_PHASE}: a capture time and an actual start time "
                                     f"are both required to establish the phase")
    if declared_phase is not None and declared_phase not in MARKET_PHASES:
        return "UNVERIFIED", False, f"UNKNOWN_MARKET_PHASE: {declared_phase!r}"
    after = str(captured_at_utc) >= str(actual_start_utc)
    if after:
        return ("LIVE" if declared_phase in (None, "PRE_GAME") else declared_phase), False, (
            f"{POST_START_QUOTE}: captured {captured_at_utc}, actual start {actual_start_utc}. A "
            f"quote taken at or after first pitch is not a pregame offer, and pairing it with a "
            f"frozen pregame probability compares a price that knows the game has begun against a "
            f"forecast that does not.")
    if declared_phase in ("LIVE", "HALFTIME", "FINAL"):
        return declared_phase, False, (f"{LIVE_IN_PREGAME}: the source declares {declared_phase} "
                                       f"even though the capture precedes the recorded start; the "
                                       f"stricter of clock and declaration wins")
    if declared_phase == "UNVERIFIED":
        return "UNVERIFIED", False, UNVERIFIED_PHASE
    return PREGAME_ONLY, True, None


def pregame_overlay_gate(quotes):
    """Refuse any quote that may not enter a pregame overlay, and say which rule stopped it."""
    problems = []
    for q in quotes or []:
        phase, ok, why = market_phase(q.get("captured_at_utc"), q.get("actual_start_utc"),
                                      q.get("declared_phase"))
        if not ok:
            problems.append({"code": POST_START_QUOTE if phase in ("LIVE", "HALFTIME", "FINAL")
                             else UNVERIFIED_PHASE, "game": q.get("game"), "phase": phase,
                             "why": why})
        if q.get("books") and len(set(q["books"])) > 1:
            problems.append({"code": CROSS_BOOK_HOLD, "game": q.get("game"),
                             "books": sorted(set(q["books"])),
                             "note": "cross-book best prices are for line shopping. A hold computed "
                                     "across two books is not any book's hold - the 8/3 ruling."})
        if q.get("opening") is not None and q.get("current") is not None \
                and q.get("opening_current_separated") is not True:
            problems.append({"code": OPENING_CURRENT_MIXED, "game": q.get("game")})
    return {"status": ELIGIBLE if not problems else NO_ELIGIBLE_BOARD,
            "n_problems": len(problems), "problems": problems}


def price_eligibility(boards):
    """Which captured boards may inform a market probability, and the honest status when none can."""
    graded = []
    for b in (boards or []):
        cap = b.get("captured_at_utc")
        start = b.get("first_start_utc")
        why = None
        ovs = b.get("overrounds")
        if ovs is None and _num(b.get("overround")) is not None:
            ovs = [b["overround"]]
        st = b.get("stratum")
        if st is None:
            st = lookup_stratum(sport=b.get("sport"), market=b.get("market_type"),
                                favorite_american=b.get("favorite_american"),
                                market_label=b.get("market"))
        hom, detail = market_homogeneity(ovs, b.get("market", "default"), stratum=st)
        if hom is not False and not (b.get("book") and b.get("source_urls")):
            hom, detail = False, dict(detail or {}, reason=(
                f"{UNVERIFIED_BOOK}: a board must name its book AND its quote links, or 'one book' "
                f"is an assertion rather than a check"))
        if hom is None:
            why = f"homogeneity undefined: {detail.get('reason')}"
        elif hom is False:
            why = detail.get("reason")
        elif not cap or not start or str(cap) >= str(start):
            why = "not captured before the first start"
        graded.append(dict(b, eligible=why is None, reason=why, homogeneity=detail,
                           hold_policy_version=HOLD_POLICY_VERSION))
    ok = [g for g in graded if g["eligible"]]
    return {
        "n_boards": len(graded),
        "n_eligible": len(ok),
        "graded": graded,
        "status": ELIGIBLE if ok else NO_ELIGIBLE_BOARD,
        "ev_status": "EV_COMPUTABLE" if ok else EV_NOT_COMPUTABLE,
        "action_authority": ACTION_AUTHORITY_NONE,
        "note": "a captured board that fails the band is not absent — it is present and inadmissible, "
                "and saying 'no prices exist' would be a claim about the world rather than about the "
                "evidence package",
    }


def overlay_contract(overlay, frozen_board_hash):
    """(ok, status, problems). May this overlay attach to that frozen board without changing it?"""
    p = []
    o = overlay or {}
    if not o.get("board_sha256"):
        p.append(OVERLAY_NO_BOARD_REF)
    elif o["board_sha256"] != frozen_board_hash:
        p.append(f"{OVERLAY_BOARD_MISMATCH}: references {o['board_sha256'][:16]} but the frozen "
                 f"board hashes to {str(frozen_board_hash)[:16]}")
    if not o.get("captured_at_utc"):
        p.append(OVERLAY_NO_CAPTURE_INSTANT)
    if not o.get("overlay_sha256"):
        p.append(OVERLAY_NO_HASH)
    for row in (o.get("rows") or []):
        for k in FROZEN_BOARD_FIELDS:
            if k in row:
                p.append(f"{OVERLAY_WOULD_MUTATE}: row carries {k}, which belongs to the board")
                break
    if o.get("execution_authority") not in (None, "NONE", False):
        p.append(f"{OVERLAY_CLAIMS_EXECUTION}: {o.get('execution_authority')!r}")
    return (not p), (OVERLAY_OK if not p else "OVERLAY_REFUSED"), p


def selection_ready(row):
    """(bool, missing). The five requirements, with Monte Carlo error refused as a stand-in."""
    r = row or {}
    missing = [k for k in SELECTION_REQUIREMENTS
               if r.get(k) is None or (isinstance(r.get(k), str) and not r[k].strip())]
    if r.get("model_uncertainty") is None and r.get("monte_carlo_sd_pp") is not None:
        missing.append(MC_IS_NOT_UNCERTAINTY)
    if (r.get("model_uncertainty") is not None
            and r.get("model_uncertainty") == r.get("monte_carlo_sd_pp")):
        missing.append(MC_IS_NOT_UNCERTAINTY)
    return (not missing), sorted(set(missing))


def evaluation_not_execution():
    return {"a_price_board_enables": "EVALUATION — EV, calibration against a market, and grading",
            "a_price_board_never_enables": "EXECUTION",
            "real_money_authorization": EXECUTION_BLOCKED,
            "why": "the two gates have different owners. No computation on this side can satisfy the "
                   "other, and there is no code path here that tries."}


# =================================================================================================
def selftest():
    f = []
    B = "a" * 64

    # --- 1: absent is not the same as inadmissible ------------------------------------------------
    DK_MLB = [0.018688, 0.018688, 0.017143, 0.017857, 0.017262,
              0.016372, 0.017966, 0.016744, 0.016744, 0.017821]   # the real 2026-08-24 board
    BIMODAL_0823 = [0.0456, 0.0462, 0.0460, 0.0453, 0.0451, 0.0462, 0.0468, 0.0475,
                    0.0164, 0.0174, 0.0167, 0.0171, 0.0195, 0.0179, 0.0192]
    BEST_ODDS = [0.0045, 0.0052, 0.0048, 0.0050]

    none_captured = price_eligibility([])
    if none_captured["status"] != NO_ELIGIBLE_BOARD or none_captured["ev_status"] != EV_NOT_COMPUTABLE:
        f.append("no captured board must report NO_ELIGIBLE_CAPTURED_PRICE_BOARD and EV_NOT_COMPUTABLE")
    if none_captured["action_authority"] != ACTION_AUTHORITY_NONE:
        f.append("action authority must be NONE with no eligible board")

    # THE CORRECTION: a genuine single-book MLB board holds under 2% and MUST be eligible. An
    # absolute 3.5% floor would have rejected the owner's real DraftKings board.
    DKID = {"book": "DRAFTKINGS", "source_urls": ["https://www.espn.com/mlb/odds"]}
    real = price_eligibility([{**DKID, "market": "mlb_moneyline", "overrounds": DK_MLB,
                               "captured_at_utc": "2026-08-24T16:41:27Z",
                               "first_start_utc": "2026-08-24T22:40:00Z"}])
    if real["status"] != ELIGIBLE:
        f.append(f"the real single-book MLB board must be eligible, got {real['graded'][0]['reason']}")
    if real["ev_status"] != "EV_COMPUTABLE":
        f.append("an eligible board makes EV computable")
    if real["action_authority"] != ACTION_AUTHORITY_NONE:
        f.append("even an ELIGIBLE board confers no action authority by itself")

    # the 8/23 bimodal board must still fail — that is the case the homogeneity test exists for
    bim = price_eligibility([{**DKID, "market": "mlb_moneyline", "overrounds": BIMODAL_0823, "captured_at_utc": "2026-08-23T15:00:00Z",
                              "first_start_utc": "2026-08-23T17:35:00Z"}])
    if bim["status"] != NO_ELIGIBLE_BOARD:
        f.append("the bimodal 8/23 board must remain ineligible")
    # ...and the SPREAD test must catch a bimodal board ON ITS OWN. The real 8/23 board happens to
    # also breach the level band, by 0.016pp — near enough to luck that resting the case on it would
    # be a fixture that passes for the wrong reason. So: a bimodal board whose MEAN sits comfortably
    # inside the band, which only the dispersion ceiling can reject.
    hidden = [0.017] * 10 + [0.045] * 4                      # mean 2.50%, spread 2.80pp
    union = lookup_stratum(market_label="mlb_moneyline")
    lo, hi = union["level_band"]
    hmean = sum(hidden) / len(hidden)
    if not (lo <= hmean <= hi):
        f.append("fixture is wrong: this bimodal mean must sit INSIDE the band so only spread bites")
    okh, deth = market_homogeneity(hidden, "mlb_moneyline")
    if okh is not False:
        f.append("a bimodal board hiding inside the level band must still fail on dispersion")
    if "more than one population" not in (deth.get("reason") or ""):
        f.append(f"the dispersion refusal must name the population problem, got {deth.get('reason')}")
    if "dispersion ceiling" not in (deth.get("reason") or ""):
        f.append("the dispersion refusal must cite the stratum's derived ceiling, not a constant")

    # --- the structural limits, tested where ONLY they can bite ---------------------------------
    # a deliberately permissive synthetic stratum, so a refusal here can only come from the
    # structural limits and not from the derived band doing the work
    wide = {"n": 99, "status": "CALIBRATED", "level_band": (0.0001, 0.99),
            "dispersion_ceiling_pp": 99.0}
    okc, whyc = level_gate(0.25, wide)
    if okc:
        f.append("a 25% two-way hold must be refused by the structural ceiling however wide the band")
    if "structural ceiling" not in (whyc or ""):
        f.append(f"the 25% refusal must cite the structural ceiling, got {whyc}")
    if f"{equal_price_equivalent(0.25):+.0f}" not in (whyc or ""):
        f.append("the structural refusal must show the equal-price equivalent, so it can be argued with")
    if not level_gate(0.05, wide)[0]:
        f.append("fixture is wrong: a 5% hold must pass the same permissive stratum")
    for bad in (0.0, -0.01, -0.5):
        okn, whyn = level_gate(bad, wide)
        if okn:
            f.append(f"a non-positive overround {bad} must be refused")
        elif NON_POSITIVE_HOLD not in (whyn or ""):
            f.append(f"a non-positive overround must be refused BY NAME, got {whyn}")
    if equal_price_equivalent(STRUCTURAL_HOLD_CEILING) is None or \
            abs(equal_price_equivalent(STRUCTURAL_HOLD_CEILING) - STRUCTURAL_CEILING_EQUAL_PRICE) > 0.5:
        f.append("the structural ceiling and its stated equal price must agree")

    # --- the dispersion floor: one tick of the book's own grid is not two books -------------------
    flat = [0.0470] * 5                                  # zero observed spread
    fst = calibrate_stratum(flat)
    if fst["status"] != "CALIBRATED":
        f.append("fixture is wrong: five quotes must calibrate")
    if fst["dispersion_ceiling_pp"] <= 0:
        f.append("a zero-spread stratum must still get a ceiling from the price grid, not zero")
    onetick = [0.0470, 0.0470 + tick_pp() / 100.0]        # exactly one price tick apart
    okt, dett = market_homogeneity(onetick, "ignored", stratum=fst)
    if okt is not True:
        f.append(f"two quotes one price tick apart are one book, got {dett.get('reason')}")
    fourticks = [0.0470, 0.0470 + 4 * tick_pp() / 100.0]
    if market_homogeneity(fourticks, "ignored", stratum=fst)[0] is not False:
        f.append("four ticks of spread on a flat stratum must still fail")

    # a stratum may NEVER be calibrated from the board under test: that admits it by construction
    self_cal = calibrate_stratum(hidden)
    if self_cal["status"] == "CALIBRATED":
        selfok, _ = market_homogeneity(hidden, "mlb_moneyline", stratum=self_cal)
        if selfok is not False:
            pass          # documents the tautology; the guard below is what enforces it
    if market_homogeneity(hidden, "mlb_moneyline")[1].get("stratum", {}).get("n") == len(hidden):
        f.append("the stratum used to judge a board must not have been derived from that board")
    if bim["n_boards"] != 1:
        f.append("an inadmissible board must still be COUNTED as captured, not reported as absent")

    # a cross-book best-of board is tight AND homogeneous, so only the LEVEL test catches it
    bo = price_eligibility([{**DKID, "market": "mlb_moneyline", "overrounds": BEST_ODDS, "captured_at_utc": "2026-08-24T16:00:00Z",
                             "first_start_utc": "2026-08-24T22:40:00Z"}])
    if bo["status"] != NO_ELIGIBLE_BOARD:
        f.append("a best-odds board must be ineligible")
    if "best-odds regime" not in (bo["graded"][0]["reason"] or ""):
        f.append("the best-odds refusal must name the regime, not the spread")

    # a single market cannot be tested for homogeneity, and that is reported rather than assumed
    one = price_eligibility([{**DKID, "market": "mlb_moneyline", "overrounds": [0.0177], "captured_at_utc": "2026-08-24T16:00:00Z",
                              "first_start_utc": "2026-08-24T22:40:00Z"}])
    if one["status"] != NO_ELIGIBLE_BOARD or "undefined" not in (one["graded"][0]["reason"] or ""):
        f.append("one priced market cannot establish homogeneity and must not be assumed eligible")

    late = price_eligibility([{**DKID, "market": "mlb_moneyline", "overrounds": DK_MLB, "captured_at_utc": "2026-08-24T23:00:00Z",
                               "first_start_utc": "2026-08-24T22:40:00Z"}])
    if late["status"] != NO_ELIGIBLE_BOARD:
        f.append("a board captured after the first start is not eligible")

    # and the WNBA half of the same capture is a DIFFERENT market type with a legitimately wider
    # hold; grouping them together would manufacture a bimodal board out of two honest ones
    # THE WNBA HALF NOW REFUSES, and that is the correct answer under a derived policy rather than a
    # hand-set band. Its two moneylines sit in two DIFFERENT price bands (-218 moderate, -600 heavy),
    # so each band holds exactly one quote and neither can be calibrated. Under the old hand-set
    # band this board passed; it passed because the band was invented, not because the board was
    # validated. UNCALIBRATED is a refusal, never a wave-through.
    wn = price_eligibility([{**DKID, "market": "wnba_moneyline", "overrounds": [0.04268, 0.04762], "captured_at_utc": "2026-08-24T16:41:27Z",
                             "first_start_utc": "2026-08-25T00:00:00Z"}])
    if wn["status"] != NO_ELIGIBLE_BOARD:
        f.append("a WNBA moneyline stratum with one quote per price band cannot be validated")
    if UNCALIBRATED not in (wn["graded"][0]["reason"] or ""):
        f.append(f"the WNBA refusal must be UNCALIBRATED, got {wn['graded'][0]['reason']}")
    if price_band(-218) == price_band(-600):
        f.append("fixture is wrong: -218 and -600 must fall in different price bands")
    # and an uncalibrated stratum must not be more permissive than a calibrated one
    for h in (0.001, 0.043, 0.19):
        okg, _ = level_gate(h, lookup_stratum(sport="wnba", market="MONEYLINE",
                                              favorite_american=-600))
        if okg:
            f.append(f"an uncalibrated stratum admitted overround {h}; it must admit nothing")
    pooled = price_eligibility([{**DKID, "market": "mlb_moneyline", "overrounds": DK_MLB + [0.04268, 0.04762],
                                 "captured_at_utc": "2026-08-24T16:41:27Z",
                                 "first_start_utc": "2026-08-24T22:40:00Z"}])
    if pooled["status"] != NO_ELIGIBLE_BOARD:
        f.append("pooling two market types must fail homogeneity — they must be graded separately")

    # a uniformly absurd board is perfectly homogeneous — the LEVEL test is what catches it
    absurd = price_eligibility([{**DKID, "market": "mlb_moneyline",
                                 "overrounds": [0.20, 0.203, 0.198, 0.201],
                                 "captured_at_utc": "2026-08-24T16:00:00Z",
                                 "first_start_utc": "2026-08-24T22:40:00Z"}])
    if absurd["status"] != NO_ELIGIBLE_BOARD:
        f.append("a uniformly absurd 20% hold board must be refused on LEVEL despite being homogeneous")
    if IMPLAUSIBLE_LEVEL not in (absurd["graded"][0]["reason"] or ""):
        f.append("the absurd board must be refused on level, not on spread")
    # a board that does not name its book and links cannot claim to be one book
    anon = price_eligibility([{"market": "mlb_moneyline", "overrounds": DK_MLB,
                               "captured_at_utc": "2026-08-24T16:41:27Z",
                               "first_start_utc": "2026-08-24T22:40:00Z"}])
    if anon["status"] != NO_ELIGIBLE_BOARD or UNVERIFIED_BOOK not in (anon["graded"][0]["reason"] or ""):
        f.append("a board with no book identity or quote links must be refused")
    # naming the book is NOT enough on its own: without quote links "one book" is still an assertion
    named_only = price_eligibility([{"book": "DRAFTKINGS", "market": "mlb_moneyline",
                                     "overrounds": DK_MLB,
                                     "captured_at_utc": "2026-08-24T16:41:27Z",
                                     "first_start_utc": "2026-08-24T22:40:00Z"}])
    if named_only["status"] != NO_ELIGIBLE_BOARD \
            or UNVERIFIED_BOOK not in (named_only["graded"][0]["reason"] or ""):
        f.append("naming a book without quote links must still be refused")
    # the amendment is versioned, not backdated
    if HOLD_POLICY_VERSION == "v1" or "supersedes" not in HOLD_POLICY_SUPERSEDES.lower():
        f.append("the hold policy must be versioned and name what it supersedes")
    if real["graded"][0].get("hold_policy_version") != HOLD_POLICY_VERSION:
        f.append("every graded board must record which policy version judged it")

    # --- 2: the overlay may not rewrite the board -------------------------------------------------
    ok_overlay = {"board_sha256": B, "captured_at_utc": "2026-08-24T20:00:00Z",
                  "overlay_sha256": "b" * 64,
                  "rows": [{"game": "mlb:BOS@MIA", "price_home": -120, "ev": 0.012}]}
    ok, st, pr = overlay_contract(ok_overlay, B)
    if not ok or st != OVERLAY_OK:
        f.append(f"a well-formed overlay must attach, got {st} {pr}")
    for k in ("p_home", "arm", "resolved_information_dose", "simulation_seed", "total_distribution"):
        bad = {**ok_overlay, "rows": [{"game": "x", k: 1}]}
        ok2, _, pr2 = overlay_contract(bad, B)
        if ok2 or not any(OVERLAY_WOULD_MUTATE in x for x in pr2):
            f.append(f"an overlay carrying {k} must be refused as a mutation")
    ok3, _, pr3 = overlay_contract({**ok_overlay, "board_sha256": "c" * 64}, B)
    if ok3 or not any(OVERLAY_BOARD_MISMATCH in x for x in pr3):
        f.append("an overlay pointing at a different board must be refused")
    for drop, code in (("board_sha256", OVERLAY_NO_BOARD_REF),
                       ("captured_at_utc", OVERLAY_NO_CAPTURE_INSTANT),
                       ("overlay_sha256", OVERLAY_NO_HASH)):
        d = {k: v for k, v in ok_overlay.items() if k != drop}
        ok4, _, pr4 = overlay_contract(d, B)
        if ok4 or code not in pr4:
            f.append(f"an overlay missing {drop} must be refused with {code}")
    ok5, _, pr5 = overlay_contract({**ok_overlay, "execution_authority": "GRANTED"}, B)
    if ok5 or not any(OVERLAY_CLAIMS_EXECUTION in x for x in pr5):
        f.append("an overlay claiming execution authority must be refused")
    if "BLOCKED" not in evaluation_not_execution()["real_money_authorization"]:
        f.append("a price board must never be described as enabling execution")

    # --- 5: five requirements, and Monte Carlo error is not one of them ---------------------------
    full = {"model_probability": 0.52, "price": -120, "expected_value": 0.011,
            "model_uncertainty": 0.031, "stated_risk": "0.5u paper"}
    ok6, miss = selection_ready(full)
    if not ok6 or miss:
        f.append(f"a complete row must be selection-ready, got {miss}")
    # NAMED explicitly, not iterated over SELECTION_REQUIREMENTS: a loop over the list under test
    # cannot fail when the list is shortened, which guards nothing (lesson 24).
    for k in ("model_probability", "price", "expected_value", "model_uncertainty", "stated_risk"):
        if k not in SELECTION_REQUIREMENTS:
            f.append(f"{k} must be a stated selection requirement")
        part = {kk: vv for kk, vv in full.items() if kk != k}
        ok7, miss7 = selection_ready(part)
        if ok7 or k not in miss7:
            f.append(f"a row missing {k} must not be selection-ready")
    # today's board shape: uncertainty absent, Monte Carlo error present
    mc_only = {"model_probability": 0.52, "price": -120, "expected_value": 0.011,
               "stated_risk": "0.5u paper", "monte_carlo_sd_pp": 0.158}
    ok8, miss8 = selection_ready(mc_only)
    if ok8 or MC_IS_NOT_UNCERTAINTY not in miss8:
        f.append("Monte Carlo error must not substitute for model uncertainty")
    # nor may they be set to the same number and called two fields
    same = dict(full, model_uncertainty=0.158, monte_carlo_sd_pp=0.158)
    ok9, miss9 = selection_ready(same)
    if ok9 or MC_IS_NOT_UNCERTAINTY not in miss9:
        f.append("identical values in both fields is the same conflation wearing two names")
    # an empty string is not a stated risk
    if selection_ready(dict(full, stated_risk="  "))[0]:
        f.append("a blank stated risk is not a stated risk")

    # --- section 8: market phase -----------------------------------------------------------------
    if len(MARKET_PHASES) != 5:
        f.append("section 4 names five market phases")
    START = "2026-08-24T23:40:00Z"
    ph, okp, _ = market_phase("2026-08-24T16:41:27Z", START)
    if ph != PREGAME_ONLY or not okp:
        f.append("a capture before first pitch is PRE_GAME and admissible")
    for cap in (START, "2026-08-25T01:58:16Z"):
        ph2, ok2, why2 = market_phase(cap, START)
        if ok2:
            f.append(f"a quote captured at/after start must be inadmissible ({cap})")
        if POST_START_QUOTE not in (why2 or ""):
            f.append("the refusal must name the post-start rule")
        if "does not" not in (why2 or ""):
            f.append("the refusal must explain the pregame-probability mismatch")
    for dp in ("LIVE", "HALFTIME", "FINAL"):
        _, ok3, why3 = market_phase("2026-08-24T16:41:27Z", START, declared_phase=dp)
        if ok3:
            f.append(f"a declared {dp} market may not enter a pregame overlay")
        if LIVE_IN_PREGAME not in (why3 or ""):
            f.append(f"a declared {dp} must be refused by the live-in-pregame rule")
    for args in (("2026-08-24T16:41:27Z", None), (None, START),
                 ("2026-08-24T16:41:27Z", START, "UNVERIFIED")):
        if market_phase(*args)[1]:
            f.append(f"an unverified phase must not authorize: {args}")
    if market_phase("2026-08-24T16:41:27Z", START, "NOT_A_PHASE")[1]:
        f.append("an unknown declared phase must be refused")
    good_q = {"game": "mlb:TEX@CWS", "captured_at_utc": "2026-08-24T16:41:27Z",
              "actual_start_utc": START, "declared_phase": "PRE_GAME", "books": ["DRAFTKINGS"]}
    if pregame_overlay_gate([good_q])["status"] != ELIGIBLE:
        f.append("a clean pregame single-book quote must be eligible")
    lg = pregame_overlay_gate([dict(good_q, captured_at_utc="2026-08-25T01:58:16Z")])
    if lg["status"] == ELIGIBLE or not any(p["code"] == POST_START_QUOTE for p in lg["problems"]):
        f.append("a post-start quote must be refused from the pregame overlay")
    xb = pregame_overlay_gate([dict(good_q, books=["DRAFTKINGS", "FANDUEL"])])
    if not any(p["code"] == CROSS_BOOK_HOLD for p in xb["problems"]):
        f.append("a two-book quote must be refused for same-book hold")
    if "8/3 ruling" not in str(xb["problems"]):
        f.append("the cross-book refusal must cite the standing ruling")
    mixed = pregame_overlay_gate([dict(good_q, opening=-130, current=-124)])
    if not any(p["code"] == OPENING_CURRENT_MIXED for p in mixed["problems"]):
        f.append("opening and current must be separated")
    if pregame_overlay_gate([dict(good_q, opening=-130, current=-124,
                                  opening_current_separated=True)])["status"] != ELIGIBLE:
        f.append("separately recorded opening and current prices are fine")

    for x in f:
        print("FAIL:", x)
    if not f:
        print("price_overlay selftest: OK")
    return f


MUTANTS = [
    ("a post-start quote may enter a pregame overlay",
     "    if after:", "    if False:"),
    ("the phase boundary shifts, so a quote AT first pitch counts as pregame",
     "    after = str(captured_at_utc) >= str(actual_start_utc)",
     "    after = str(captured_at_utc) > str(actual_start_utc)"),
    ("a declared LIVE market is allowed into a pregame overlay",
     '    if declared_phase in ("LIVE", "HALFTIME", "FINAL"):', "    if False:"),
    ("an unverified market phase authorizes anyway",
     "    if not captured_at_utc or not actual_start_utc:", "    if False:"),
    ("cross-book prices pass same-book hold validation",
     '        if q.get("books") and len(set(q["books"])) > 1:', "        if False:"),
    ("opening and current prices may be mixed",
     '            problems.append({"code": OPENING_CURRENT_MIXED, "game": q.get("game")})',
     "            pass"),
    ("a market phase is dropped from the vocabulary",
     '"PRE_GAME", "LIVE", "HALFTIME", "FINAL", "UNVERIFIED")',
     '"PRE_GAME", "LIVE", "FINAL", "UNVERIFIED")'),
    ("the post-start refusal stops explaining the mismatch",
     '"forecast that does not.")', '"quote is late.")'),
    ("book identity and quote links stop being required",
     '        if hom is not False and not (b.get("book") and b.get("source_urls")):', "        if False:"),
    ("quote links alone are dropped from the identity check",
     '        if hom is not False and not (b.get("book") and b.get("source_urls")):',
     '        if hom is not False and not b.get("book"):'),
    ("the policy version is backdated to the original rule",
     'HOLD_POLICY_VERSION = "v2-2026-08-24"', 'HOLD_POLICY_VERSION = "v1"'),
    ("the graded board stops recording which policy judged it",
     '                           hold_policy_version=HOLD_POLICY_VERSION))', "                           ))"),

    ("an inadmissible board is reported as no board at all",
     "        graded.append(dict(b, eligible=why is None, reason=why, homogeneity=detail,\n                           hold_policy_version=HOLD_POLICY_VERSION))",
     "        pass"),
    ("the dispersion test stops running, so a bimodal board passes",
     "    if 100.0 * spread > ceiling:", "    if False:"),
    ("the level test stops running, so an absurd hold passes",
     "    ok_level, why_level = level_gate(mean, st)", "    ok_level, why_level = True, None"),
    ("the stratum is calibrated from the board under test, making the gate a tautology",
     "    st = stratum if stratum is not None else lookup_stratum(market_label=market)",
     "    st = stratum if stratum is not None else calibrate_stratum(vals)"),
    ("an uncalibrated stratum waves quotes through instead of refusing them",
     '    if not stratum or stratum.get("status") != "CALIBRATED":', "    if False:"),
    ("a single-observation stratum is treated as calibrated",
     "MIN_OBS_TO_CALIBRATE = 3", "MIN_OBS_TO_CALIBRATE = 1"),
    ("the structural ceiling is lifted, so a 20%+ hold board is plausible",
     "STRUCTURAL_HOLD_CEILING = 0.20", "STRUCTURAL_HOLD_CEILING = 0.95"),
    ("a non-positive overround stops being refused",
     "    if h <= STRUCTURAL_HOLD_FLOOR:", "    if False:"),
    ("the dispersion floor drops below the book's own price grid",
     "DISPERSION_FLOOR_TICKS = 2", "DISPERSION_FLOOR_TICKS = 0"),
    ("the price band collapses, pooling a pick-em with a heavy favourite",
     '        if floor is None or f >= floor:', "        if True:"),
    ("the dispersion refusal stops naming the population problem",
     '"than one population")', '"than one book\'s grid.")'),
    ("the unbanded lookup returns the permissive band instead of refusing",
     "    if len(cal) != len(cands):", "    if False:"),
    ("the best-odds level test stops running",
     "    if mean < BEST_ODDS_CEILING:", "    if False:"),
    ("a single market is assumed homogeneous",
     '        return None, {"n": len(vals), "reason": "fewer than two priced markets; homogeneity is "\n                                                "undefined and is not assumed"}',
     '        return True, {"n": len(vals), "reason": "assumed"}'),
    ("a board captured after the start is eligible",
     '        elif not cap or not start or str(cap) >= str(start):', "        elif False:"),
    ("an eligible board is reported as conferring action authority",
     '        "action_authority": ACTION_AUTHORITY_NONE,', '        "action_authority": "GATE_GOVERNED" if ok else ACTION_AUTHORITY_NONE,'),
    ("EV is called computable with no eligible board",
     '        "ev_status": "EV_COMPUTABLE" if ok else EV_NOT_COMPUTABLE,', '        "ev_status": "EV_COMPUTABLE",'),
    ("an overlay may carry board fields",
     "            if k in row:", "            if False:"),
    ("the mutation list is emptied",
     'FROZEN_BOARD_FIELDS = ("p_home", "winner_probability", "projected_total", "projected_home_margin",\n                       "arm", "resolved_information_dose", "information_class", "simulation_seed",\n                       "simulation_trials", "evidence_sha256", "total_distribution")',
     "FROZEN_BOARD_FIELDS = ()"),
    ("an overlay may point at a different board",
     '    elif o["board_sha256"] != frozen_board_hash:', "    elif False:"),
    ("an overlay needs no capture instant",
     '    if not o.get("captured_at_utc"):', "    if False:"),
    ("an overlay needs no hash of its own",
     '    if not o.get("overlay_sha256"):', "    if False:"),
    ("an overlay may claim execution authority",
     '    if o.get("execution_authority") not in (None, "NONE", False):', "    if False:"),
    ("Monte Carlo error substitutes for model uncertainty",
     '    if r.get("model_uncertainty") is None and r.get("monte_carlo_sd_pp") is not None:\n        missing.append(MC_IS_NOT_UNCERTAINTY)',
     "    if False:\n        missing.append(MC_IS_NOT_UNCERTAINTY)"),
    ("the two fields may hold the same number",
     '    if (r.get("model_uncertainty") is not None\n            and r.get("model_uncertainty") == r.get("monte_carlo_sd_pp")):\n        missing.append(MC_IS_NOT_UNCERTAINTY)',
     "    if False:\n        missing.append(MC_IS_NOT_UNCERTAINTY)"),
    ("the five requirements shrink to four",
     'SELECTION_REQUIREMENTS = ("model_probability", "price", "expected_value",\n                          "model_uncertainty", "stated_risk")',
     'SELECTION_REQUIREMENTS = ("model_probability", "price", "expected_value", "stated_risk")'),
    ("a blank string satisfies a requirement",
     '    missing = [k for k in SELECTION_REQUIREMENTS\n               if r.get(k) is None or (isinstance(r.get(k), str) and not r[k].strip())]',
     "    missing = [k for k in SELECTION_REQUIREMENTS if r.get(k) is None]"),
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
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True, timeout=120)
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
    print(__doc__)
