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
    pf = parks.get(B.VENUE.get(hab, ""), 1.0)
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
    return {
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
    edge = fc["p_home"] - novig_h
    return {"event": fc["event"], "valued": True,
            "market_no_vig_home": round(novig_h, 6),
            "edge_pp_home": round(100 * edge, 2),
            "execution_state": EXEC_WAIT,
            "why": "actionability is gated separately from the forecast and is not opened here"}


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
