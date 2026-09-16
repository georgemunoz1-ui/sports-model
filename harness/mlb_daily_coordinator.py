#!/usr/bin/env python3
"""MLB daily cycle. Enforces NO_ACTION != NO_FORECAST.

THE INVARIANT. Every canonically scheduled MLB game receives a registered forecast unless the
PREDICTION ENGINE ITSELF cannot execute. Unresolved starters, unposted lineups, a blocked feed,
an owner-relay field that is missing, a stale source -- these change UNCERTAINTY, FEATURE
TREATMENT and EXECUTION STATUS. None of them erases the forecast.

WHY. On 2026-08-30 the board carried fifteen MLB games and zero forecasts. The stated reason was
0/14 SP_CONFIRMED. But the CONFIRMED grade is minted only from a boxscore past first pitch, so a
PREGAME board can never satisfy it -- not "usually does not", CANNOT. An action gate that can
never open was reported as an information problem. Meanwhile the owner's relay named all 28
starters, the pitcher registry knew 25 of them, every team had run-scoring form and every park
had a factor. The engine could have run fifteen times and ran zero.

ORDER IS LOAD-BEARING. Features freeze BEFORE any price is read. market_overlay() takes the
frozen forecast as an argument and returns a separate object; there is no path by which a price
reaches v13_sim. That is the market-independence rule expressed as a call graph rather than a
promise.

TRUE_NO_FORECAST is reserved. It requires a machine-readable MATHEMATICAL reason -- the engine
raised, or a required numeric input is absent with no registered fallback. "Starter not
confirmed", "relay missing a field", "ESPN blocked" and "one source stale" are explicitly NOT
sufficient, and the module refuses to record them as such.
"""
from __future__ import annotations

MODULE_ID = "mlb_daily_coordinator"

import datetime as dt
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.chdir(REPO)

UTC = dt.timezone.utc

FORECAST_VALID = "VALID_WITH_UNCERTAINTY"
FORECAST_CLEAN = "VALID"
NO_FORECAST = "TRUE_NO_FORECAST"

EXEC_ACTIONABLE = "ACTIONABLE"
EXEC_WAIT = "WAIT"
EXEC_NO_LINE = "NO_LINE"
EXEC_BLOCKED = "NOT_ACTIONABLE"

#: The ONLY admissible reasons for TRUE_NO_FORECAST. Each names a mathematical failure.
MATHEMATICAL_BLOCKERS = {
    "ENGINE_RAISED": "v13_sim raised; the simulation did not produce a distribution",
    "TEAM_RUN_FORM_ABSENT": "no runs-for/runs-against for a side and no registered league "
                            "fallback, so the offence term has no value at all",
    "NO_STARTER_TREATMENT": "neither a pitcher profile nor the registered league treatment is "
                            "available for a slot",
}
#: Explicitly rejected as reasons. Recording one of these as TRUE_NO_FORECAST is a defect.
NOT_A_FORECAST_BLOCKER = (
    "SP_NOT_CONFIRMED", "LINEUP_NOT_POSTED", "RELAY_FIELD_MISSING", "FEED_EGRESS_BLOCKED",
    "SOURCE_STALE", "NO_MARKET_PRICE", "AVAILABILITY_UNKNOWN",
)


class ForecastSuppressed(RuntimeError):
    """Raised when a caller tries to record a non-mathematical reason as TRUE_NO_FORECAST."""


def assert_mathematical(reason):
    if reason in NOT_A_FORECAST_BLOCKER:
        raise ForecastSuppressed(
            f"{reason!r} is NOT a forecast blocker. It affects uncertainty and execution status. "
            "NO_ACTION != NO_FORECAST — see the module docstring and the 2026-08-30 incident.")
    if reason not in MATHEMATICAL_BLOCKERS:
        raise ForecastSuppressed(
            f"{reason!r} is not a registered mathematical blocker; known: "
            f"{sorted(MATHEMATICAL_BLOCKERS)}. An unregistered reason cannot be audited.")
    return True


# ----------------------------------------------------------------- stages

def canonical_schedule(date_et, relay_events, extra=()):
    """Stage 1. The schedule is the SUPERSET. A game absent from the book is retained NO_LINE.

    extra: games known to be scheduled but absent from the relay. On 2026-08-30 that is ARI@SF,
    which the board correctly flagged as absent from the DK board and then carried as BLOCKED.
    Blocked is the right execution status and the wrong forecast status.
    """
    sched = {e["event"]: dict(e, in_relay=True) for e in relay_events}
    for e in extra:
        sched.setdefault(e["event"], dict(e, in_relay=False))
    return sched



# Abbrev -> home park, ALL 30 clubs. Found 2026-08-31 while building the 9/1 board: the pf lookup
# below fed B.VENUE (15 FULL-NAME keys from the 8/25 slate) with an ABBREV, so every game on the
# 8/30 regression quietly ran at pf 1.0. A park factor that defaults is a feature that lies;
# the lookup now refuses instead.
HOME_PARK = {
    "ARI": "Chase Field", "AZ": "Chase Field", "ATL": "Truist Park",
    "ATH": "Sutter Health Park", "OAK": "Sutter Health Park",
    "BAL": "Oriole Park at Camden Yards", "BOS": "Fenway Park", "CHC": "Wrigley Field",
    "CIN": "Great American Ball Park", "CLE": "Progressive Field", "COL": "Coors Field",
    "CWS": "Rate Field", "DET": "Comerica Park", "HOU": "Daikin Park",
    "KC": "Kauffman Stadium", "LAA": "Angel Stadium", "LAD": "UNIQLO Field at Dodger Stadium",
    "MIA": "loanDepot park", "MIL": "American Family Field", "MIN": "Target Field",
    "NYM": "Citi Field", "NYY": "Yankee Stadium", "PHI": "Citizens Bank Park",
    "PIT": "PNC Park", "SD": "Petco Park", "SEA": "T-Mobile Park", "SF": "Oracle Park",
    "STL": "Busch Stadium", "TB": "Tropicana Field", "TEX": "Globe Life Field",
    "TOR": "Rogers Centre", "WSH": "Nationals Park",
}


def park_factor(parks, home_abbrev):
    """The home club's park factor, or a refusal. Never a silent 1.0."""
    park = HOME_PARK.get(home_abbrev)
    if park is None or park not in parks:
        raise ValueError("PARK_FACTOR_ABSENT:%s" % home_abbrev)
    return parks[park]


def freeze_features(event, *, pid_map, rf, ra, parks, B, trials, slate_date):
    """Stage 2-4. Enrich and FREEZE. No price is read here and none is reachable from here."""
    aab, hab = event["away"], event["home"]
    spa, sa_status, _rsa, disp_a = B.starter(pid_map, event.get("away_starter"))
    sph, sh_status, _rsh, disp_h = B.starter(pid_map, event.get("home_starter"))

    def capped(d):
        return not (d["disposition"] == "FRESH"
                    or (d["disposition"] == "ACQUIRING" and d["grade"] == "CONFIRMED"))

    import board_freshness as BF
    n_capped = int(capped(disp_a)) + int(capped(disp_h))
    dose = BF.game_dose([disp_a, disp_h])
    pf = park_factor(parks, hab)
    return {
        "event": event["event"], "away": aab, "home": hab,
        "away_starter": event.get("away_starter"), "home_starter": event.get("home_starter"),
        "sp_away": spa, "sp_home": sph,
        "sp_status": {"away": sa_status, "home": sh_status},
        "starter_dispositions": {"away": disp_a, "home": disp_h},
        "starter_slots_capped": n_capped,
        "resolved_information_dose": dose,
        "rf_away": rf.get(aab), "ra_away": ra.get(aab),
        "rf_home": rf.get(hab), "ra_home": ra.get(hab),
        "park_factor": pf, "trials": trials, "slate_date": slate_date,
        "frozen": True, "market_read": False,
    }


def forecast(snap, *, V13, KS, prior_p):
    """Stage 5. Run the engine. Returns a forecast for EVERY game the engine can execute."""
    problems = []
    if snap["rf_away"] is None or snap["rf_home"] is None:
        problems.append("TEAM_RUN_FORM_ABSENT")
    if snap["sp_away"] is None or snap["sp_home"] is None:
        problems.append("NO_STARTER_TREATMENT")
    if problems:
        for p in problems:
            assert_mathematical(p)
        return {"event": snap["event"], "forecast_state": NO_FORECAST,
                "mathematical_reason": problems,
                "reason_text": [MATHEMATICAL_BLOCKERS[p] for p in problems],
                "p_home": None}
    seed = KS.seed_for(f"mlb.winner.CHAMPION_V13.{snap['trials']}", snap["slate_date"],
                       snap["event"], "v13_1")
    try:
        sim = V13.v13_sim(snap["sp_away"], snap["sp_home"], snap["rf_away"], snap["ra_away"],
                          snap["rf_home"], snap["ra_home"], snap["park_factor"], seed,
                          snap["trials"])
    except Exception as e:
        assert_mathematical("ENGINE_RAISED")
        return {"event": snap["event"], "forecast_state": NO_FORECAST,
                "mathematical_reason": ["ENGINE_RAISED"],
                "reason_text": [f"{type(e).__name__}: {e}"], "p_home": None}
    state = FORECAST_CLEAN if snap["starter_slots_capped"] == 0 else FORECAST_VALID
    dose = snap["resolved_information_dose"]
    p_dosed = apply_dose(sim["p_home"], dose, prior_p)
    return {
        "p_home_dosed": round(p_dosed, 6),
        "dose_consumed": True,
        "event": snap["event"], "forecast_state": state,
        "p_home": sim["p_home"], "p_away": round(1 - sim["p_home"], 6),
        "projected_margin_home": sim.get("margin"), "projected_total": sim.get("total"),
        "monte_carlo_sd_pp": 100 * sim["mc_se"] if sim.get("mc_se") is not None else None,
        "arms": {"mlb.winner.CHAMPION_V13": sim["p_home"],
                 "mlb.winner.EXPANDING_HOME_PRIOR": prior_p},
        "starter_slots_capped": snap["starter_slots_capped"],
        "resolved_information_dose": snap["resolved_information_dose"],
        "uncertainty": {"starter": "PROBABLE" if snap["starter_slots_capped"] else "REGISTERED",
                        "lineup": "NOT_POSTED", "dose": snap["resolved_information_dose"]},
        "seed": seed, "trials": snap["trials"], "simulation_version": "v13_1",
    }


#: Base edge a full-information forecast must clear. The threshold WIDENS as dose falls.
BASE_EDGE_PP = 3.0


def required_edge_pp(dose, base=BASE_EDGE_PP):
    """How much edge a forecast must show to be actionable AT THIS DOSE.

    2026-08-31. A proposal arrived to consume dose by shrinking the point estimate toward the
    prior and leaving the decision threshold alone. Tested on the 8/30 slate, that GREW the
    apparent edge on 9 of 14 games -- LAD@DET went 5.20pp -> 11.33pp -- because the market is
    priced away from the league prior, so pulling the model toward the prior pulls it AWAY from
    the market. Removing information made the system look more confident about a disagreement.
    That is exactly backwards, and the proposal's own worked example hit it (KC@CLE -0.9pp ->
    +11.3pp) and corrected it by hand rather than by mechanism.

    Shrinking a point estimate is not the same as widening an interval, and only the second one
    is what low information means. The point estimate still shrinks -- shrink_to_prior is
    registered and tested and stays -- but the BAR moves with it.
    """
    if not dose or dose <= 0:
        return float("inf")
    return base / dose


def effective_edge_pp(p_raw, novig, dose):
    """The only edge a forecast may claim: its departure from the market, scaled by what it knows.

    edge -> 0 as dose -> 0. The alternative (shrink the probability, then difference) leaves
    |prior - market| behind at zero information and reads it as a model edge.
    """
    return (dose or 0.0) * 100 * (p_raw - novig)


def apply_dose(p_raw, dose, prior):
    """The registered consumption. NOTE the target is the REGISTERED PRIOR, not 0.5.

    prior for MLB is 0.5205399061032864, the measured home rate over the 1,684-game canonical
    pool. Shrinking toward 0.5 instead would discard the measured home-field advantage and bias
    every low-dose forecast against the home side by about half a point of probability.
    """
    import freshness_contract as FC
    return FC.shrink_to_prior(p_raw, dose, prior)


def market_overlay(fc, market):
    """Stage 6. Prices join ONLY here, and only after the forecast exists."""
    if fc.get("p_home") is None:
        return {"event": fc["event"], "execution_state": EXEC_BLOCKED,
                "why": "no forecast to value", "valued": False}
    if not market or market.get("home_ml") is None or market.get("away_ml") is None:
        return {"event": fc["event"], "execution_state": EXEC_NO_LINE,
                "why": "scheduled game carries no captured price; retained, never dropped",
                "valued": False}

    def implied(american):
        return (-american) / ((-american) + 100) if american < 0 else 100 / (american + 100)

    ih, ia = implied(market["home_ml"]), implied(market["away_ml"])
    novig_h = ih / (ih + ia)
    # THE DECISION EDGE IS THE DOSE-SCALED EDGE, not the dosed probability minus the market.
    #
    # 2026-08-31, limit test. Shrinking the probability toward the prior and differencing against
    # the market gives edge -> |prior - market| as dose -> 0, which for COL@ATL is -15.95pp. At
    # ZERO information the model would be credited with a 15.9pp disagreement it did not produce;
    # that number is a market fact (the book is priced away from the league rate), not a model
    # finding. Scaling the edge itself gives edge -> 0, which is what "no information" has to mean.
    #
    # The registered shrink_to_prior stays and p_home_dosed is still what gets REPORTED as the
    # probability -- it is the right point estimate. It is simply not the right differencer.
    dose = fc.get("resolved_information_dose") or 0.0
    raw_edge_pp = 100 * (fc["p_home"] - novig_h)
    edge_pp = dose * raw_edge_pp
    need = BASE_EDGE_PP
    clears = abs(edge_pp) >= need
    p = fc.get("p_home_dosed", fc["p_home"])
    return {"event": fc["event"], "valued": True,
            "market_no_vig_home": round(novig_h, 6),
            "p_home_used": round(p, 6),
            "edge_pp_home": round(edge_pp, 2),
            "edge_pp_undosed": round(raw_edge_pp, 2),
            "dose": dose, "required_edge_pp": round(need, 2),
            "edge_basis": "dose x (p_raw - market). Goes to zero as information goes to zero.",
            "clears_dose_scaled_bar": clears,
            "execution_state": EXEC_ACTIONABLE if clears else EXEC_WAIT,
            "why": ("edge clears the dose-scaled bar" if clears else
                    f"edge {abs(edge_pp):.2f}pp is under the {need:.2f}pp this dose demands; "
                    "low information widens the bar, it does not lower it")}


def summarise(rows):
    """The shape the owner specified."""
    s = {"scheduled": len(rows), "forecasted": 0, "valued": 0, "actionable": 0,
         "wait": 0, "no_line": 0, "true_no_forecast": 0}
    for r in rows:
        if r["forecast"]["forecast_state"] != NO_FORECAST:
            s["forecasted"] += 1
        else:
            s["true_no_forecast"] += 1
        o = r["overlay"]
        s["valued"] += 1 if o.get("valued") else 0
        st = o.get("execution_state")
        s["actionable"] += 1 if st == EXEC_ACTIONABLE else 0
        s["wait"] += 1 if st == EXEC_WAIT else 0
        s["no_line"] += 1 if st == EXEC_NO_LINE else 0
    return s


def run(date_et, relay_events, *, extra=(), trials=30000):
    import build_board_0825 as B
    import run_v13_historical as V13
    import keyed_seed as KS
    pid_map = B.name_to_pid()
    rf, ra, _ng = B.team_form_rf_ra()
    parks = json.load(open(B.PARKS))
    sched = canonical_schedule(date_et, relay_events, extra)
    rows = []
    for ev in sorted(sched.values(), key=lambda e: e["event"]):
        snap = freeze_features(ev, pid_map=pid_map, rf=rf, ra=ra, parks=parks, B=B,
                               trials=trials, slate_date=date_et)
        fc = forecast(snap, V13=V13, KS=KS, prior_p=B.PRIOR_P)
        ov = market_overlay(fc, ev.get("market"))
        rows.append({"event": ev["event"], "in_relay": ev.get("in_relay", True),
                     "snapshot": snap, "forecast": fc, "overlay": ov})
    return {"schema": "ops.mlb_daily_cycle.v1", "date_et": date_et,
            "n_scheduled": len(rows), "summary": summarise(rows), "games": rows}


def selftest():
    f = []
    try:
        assert_mathematical("SP_NOT_CONFIRMED")
        f.append("SP_NOT_CONFIRMED was accepted as a forecast blocker — the whole point")
    except ForecastSuppressed:
        pass
    for bad in NOT_A_FORECAST_BLOCKER:
        try:
            assert_mathematical(bad)
            f.append(f"{bad} accepted as a forecast blocker")
        except ForecastSuppressed:
            pass
    for good in MATHEMATICAL_BLOCKERS:
        try:
            assert_mathematical(good)
        except ForecastSuppressed:
            f.append(f"{good} rejected but it IS a mathematical blocker")
    # a no-line game must still forecast
    ov = market_overlay({"event": "X@Y", "p_home": 0.55}, None)
    if ov["execution_state"] != EXEC_NO_LINE or ov["valued"]:
        f.append("a priceless game did not land on NO_LINE")
    ov2 = market_overlay({"event": "X@Y", "p_home": None}, {"home_ml": -110, "away_ml": -110})
    if ov2["valued"]:
        f.append("a game with no forecast was valued anyway")
    for x in f:
        print("  FAIL:", x)
    print(f"mlb_daily_coordinator selftest: {'OK' if not f else 'FAIL'}")
    return not f


if __name__ == "__main__":
    sys.exit(0 if selftest() else 1)
