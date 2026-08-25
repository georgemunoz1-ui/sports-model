#!/usr/bin/env python3
"""DRIFT MONITOR — preregistered alarms, and a response that goes to the baseline, not to a retune.

OWNER SPECIFICATION 2026-08-23. Rolling checks at 50, 100 and 250 games:
Brier and log-loss versus the expanding prior, calibration intercept and slope, probability-range
contraction, error by starter-information dose, home/away directional bias, model-market
disagreement performance, and margin/total tail coverage.

    On alarm: reduce trust status, widen uncertainty, revert action output to the BASELINE, continue
    registering champion and challenger, diagnose before retraining.

    "The model should not automatically reverse its picks or retune until yesterday's losses
     disappear."

THE RESPONSE IS THE DESIGN. An alarm that triggers retraining is a system that retrains hardest
exactly when its recent sample is least representative — the mechanical form of chasing losses.
Reverting to the BASELINE is the opposite move: when the model can no longer show it beats the
expanding prior, the expanding prior is what it outputs, and both arms keep being registered so the
diagnosis has data to work with.

THRESHOLDS ARE PREREGISTERED AND FROZEN. Every one is a constant with a registration date. An alarm
threshold tuned after seeing which alarms fired is not an alarm, and the register carries the date
so that fact is checkable rather than remembered.

PROBABILITY-RANGE CONTRACTION is on this list because it is the failure this system has actually
had: the model's spread is ~3.25pp against a market ~11.5pp. A model collapsing toward its own mean
keeps scoring near a coin flip and never trips a Brier alarm, because a coin flip is hard to beat.
Only a direct check on the spread catches it.
"""
from __future__ import annotations

MODULE_ID = "drift_monitor"

import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HORIZONS = (50, 100, 250)
THRESHOLDS_REGISTERED_UTC = "2026-08-23T00:00:00Z"

# Frozen 2026-08-23. Changing any of these is a SLOW-layer act at a formal model release.
THRESHOLDS = {
    # the model must not be WORSE than the expanding prior it is supposed to improve on
    "brier_excess_over_prior": {"limit": 0.0050, "direction": "above",
                                "why": "the model scoring worse than its own intercept"},
    "logloss_excess_over_prior": {"limit": 0.0100, "direction": "above",
                                  "why": "same failure on the proper scoring rule"},
    # calibration
    "calibration_slope_low": {"limit": 0.60, "direction": "below",
                              "why": "overconfidence: the model's spread outruns its accuracy"},
    "calibration_slope_high": {"limit": 1.80, "direction": "above",
                               "why": "severe underconfidence, the signature of compression"},
    "calibration_intercept_abs": {"limit": 0.75, "direction": "above",
                                  "why": "a systematic level shift toward one side"},
    # the failure this system actually has
    "probability_sd_pp_low": {"limit": 2.50, "direction": "below",
                              "why": "probability-range contraction toward the model's own mean"},
    # directional bias
    "home_pick_share_high": {"limit": 0.80, "direction": "above",
                             "why": "the model has become a home-side proxy"},
    "home_pick_share_low": {"limit": 0.20, "direction": "below",
                            "why": "the model has become an away-side proxy"},
    "directional_brier_gap": {"limit": 0.0300, "direction": "above",
                              "why": "performance depends on which way the model moved"},
    # dose
    "dose_brier_gap": {"limit": 0.0400, "direction": "above",
                       "why": "performance depends on how much starter information was available, "
                              "which means the aggregate describes no configuration"},
    # market disagreement
    "disagreement_win_rate_low": {"limit": 0.35, "direction": "below",
                                  "why": "the model loses when it disagrees with the market"},
    # tails
    "total_tail_coverage_low": {"limit": 0.85, "direction": "below",
                                "why": "totals intervals do not contain the outcomes they claim to"},
}

# The response ladder, in order. Every step runs; there is no partial response.
RESPONSE = (
    "REDUCE_TRUST_STATUS",
    "WIDEN_UNCERTAINTY",
    "REVERT_ACTION_OUTPUT_TO_BASELINE",
    "CONTINUE_REGISTERING_CHAMPION_AND_CHALLENGER",
    "DIAGNOSE_BEFORE_RETRAINING",
)
FORBIDDEN_RESPONSES = ("RETRAIN", "RETUNE", "REVERSE_PICKS", "FLIP_SIDES", "REFIT",
                       "SELECT_NEW_WINDOW", "ADJUST_THRESHOLDS")


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _sd(xs):
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def breach(name, value):
    """(is_breached, detail) for one preregistered threshold."""
    t = THRESHOLDS.get(name)
    if t is None:
        return False, {"error": f"{name} is not a preregistered threshold"}
    if value is None:
        return False, {"value": None, "reason": "not measurable on this window"}
    v = abs(value) if name.endswith("_abs") else value
    hit = (v > t["limit"]) if t["direction"] == "above" else (v < t["limit"])
    return hit, {"value": value, "limit": t["limit"], "direction": t["direction"], "why": t["why"]}


def measure(rows):
    """Every monitored quantity over one window of settled rows.

    Each row: p_home_model, p_home_prior, home_win, and optionally starter_information_fraction,
    market_p_home, total_interval_covered."""
    import paired_eval as PE
    n = len(rows)
    if n == 0:
        return {"n": 0}
    ys = [int(r["home_win"]) for r in rows]
    pm = [float(r["p_home_model"]) for r in rows]
    pp = [float(r["p_home_prior"]) for r in rows]
    cal_rows = [{"p_home_challenger": p, "home_result": y} for p, y in zip(pm, ys)]
    cal = PE.calibration(cal_rows)
    out = {
        "n": n,
        "brier_model": _mean([(p - y) ** 2 for p, y in zip(pm, ys)]),
        "brier_prior": _mean([(p - y) ** 2 for p, y in zip(pp, ys)]),
        "logloss_model": _mean([PE.logloss(p, y) for p, y in zip(pm, ys)]),
        "logloss_prior": _mean([PE.logloss(p, y) for p, y in zip(pp, ys)]),
        "calibration_slope": cal.get("slope"),
        "calibration_intercept": cal.get("intercept"),
        "probability_sd_pp": (_sd(pm) * 100.0) if _sd(pm) is not None else None,
        "home_pick_share": _mean([1.0 if p >= .5 else 0.0 for p in pm]),
    }
    out["brier_excess_over_prior"] = out["brier_model"] - out["brier_prior"]
    out["logloss_excess_over_prior"] = out["logloss_model"] - out["logloss_prior"]
    # directional: model moved toward home vs toward away relative to the prior
    toward_home = [(p, y) for p, pr, y in zip(pm, pp, ys) if p > pr]
    toward_away = [(p, y) for p, pr, y in zip(pm, pp, ys) if p < pr]
    bh = _mean([(p - y) ** 2 for p, y in toward_home])
    ba = _mean([(p - y) ** 2 for p, y in toward_away])
    out["directional_brier_gap"] = (abs(bh - ba) if (bh is not None and ba is not None) else None)
    out["directional_detail"] = {"toward_home_n": len(toward_home), "toward_home_brier": bh,
                                 "toward_away_n": len(toward_away), "toward_away_brier": ba}
    # dose
    bins = {}
    for r, p, y in zip(rows, pm, ys):
        b = PE.dose_bin(r.get("starter_information_fraction"))
        bins.setdefault(b, []).append((p - y) ** 2)
    dose = {b: _mean(v) for b, v in bins.items() if len(v) >= 5}
    out["dose_brier_gap"] = (max(dose.values()) - min(dose.values())) if len(dose) >= 2 else None
    out["dose_detail"] = {b: {"n": len(bins[b]), "brier": _mean(bins[b])} for b in bins}
    # model-market disagreement
    dis = [(p, y) for r, p, y in zip(rows, pm, ys)
           if r.get("market_p_home") is not None
           and ((p >= .5) != (float(r["market_p_home"]) >= .5))]
    out["disagreement_n"] = len(dis)
    out["disagreement_win_rate"] = _mean([1.0 if (p >= .5) == (y == 1) else 0.0 for p, y in dis])
    # totals tail coverage
    cov = [1.0 if r["total_interval_covered"] else 0.0 for r in rows
           if r.get("total_interval_covered") is not None]
    out["total_tail_coverage"] = _mean(cov)
    return out


def check_window(rows):
    """(alarms, measurements) for one window."""
    m = measure(rows)
    alarms = []
    for name in THRESHOLDS:
        key = name
        if name in ("calibration_slope_low", "calibration_slope_high"):
            key = "calibration_slope"
        elif name == "calibration_intercept_abs":
            key = "calibration_intercept"
        elif name == "probability_sd_pp_low":
            key = "probability_sd_pp"
        elif name in ("home_pick_share_high", "home_pick_share_low"):
            key = "home_pick_share"
        elif name == "disagreement_win_rate_low":
            key = "disagreement_win_rate"
        elif name == "total_tail_coverage_low":
            key = "total_tail_coverage"
        hit, detail = breach(name, m.get(key))
        if hit:
            alarms.append(dict(detail, alarm=name))
    return alarms, m


def run(rows, horizons=HORIZONS):
    """Rolling checks at each horizon over the MOST RECENT rows. Rows must arrive oldest-first."""
    out = {"horizons": {}, "thresholds_registered_utc": THRESHOLDS_REGISTERED_UTC,
           "n_available": len(rows)}
    fired = []
    for h in horizons:
        if len(rows) < h:
            out["horizons"][str(h)] = {"status": "INSUFFICIENT_SAMPLE", "n_available": len(rows),
                                       "required": h}
            continue
        alarms, m = check_window(rows[-h:])
        out["horizons"][str(h)] = {"status": "ALARM" if alarms else "CLEAR",
                                   "alarms": alarms, "measurements": m}
        for a in alarms:
            fired.append(dict(a, horizon=h))
    out["any_alarm"] = bool(fired)
    out["alarms_fired"] = fired
    out["response"] = response_for(fired)
    return out


def response_for(fired):
    """The full preregistered response, or none. There is no partial response and no retune."""
    if not fired:
        return {"triggered": False, "steps": [],
                "note": "no preregistered alarm fired; nothing changes"}
    return {"triggered": True, "steps": list(RESPONSE),
            "action_output": "BASELINE",
            "forbidden": list(FORBIDDEN_RESPONSES),
            "note": ("Every step runs. The action output reverts to the expanding prior, both arms "
                     "keep registering, and diagnosis precedes any retraining. The model does not "
                     "reverse its picks and does not retune until yesterday's losses disappear.")}


def selftest():
    f = []

    def mk(n, p_model, p_prior=0.527, home_rate=0.5, frac=0.8, market=None, cov=True, seed=0):
        rows = []
        for i in range(n):
            y = 1 if ((i * 7 + seed) % 100) / 100.0 < home_rate else 0
            pm = p_model(i, y) if callable(p_model) else p_model
            rows.append({"p_home_model": pm, "p_home_prior": p_prior, "home_win": y,
                         "starter_information_fraction": frac,
                         "market_p_home": market, "total_interval_covered": cov})
        return rows

    # --- thresholds are preregistered and dated ---------------------------------------------------
    if THRESHOLDS_REGISTERED_UTC != "2026-08-23T00:00:00Z":
        f.append("the threshold registration date is not frozen")
    for name, t in THRESHOLDS.items():
        if t["direction"] not in ("above", "below") or "why" not in t:
            f.append(f"threshold {name} lacks a direction or a stated reason")
    if breach("some_threshold_i_just_invented", 1.0)[0]:
        f.append("an unregistered threshold produced an alarm")

    # --- each direction fires on the correct side, tested ON the boundary --------------------------
    if breach("brier_excess_over_prior", 0.0050)[0]:
        f.append("an 'above' threshold fired exactly AT its limit")
    if not breach("brier_excess_over_prior", 0.0051)[0]:
        f.append("an 'above' threshold did not fire just past its limit")
    if breach("calibration_slope_low", 0.60)[0]:
        f.append("a 'below' threshold fired exactly AT its limit")
    if not breach("calibration_slope_low", 0.59)[0]:
        f.append("a 'below' threshold did not fire just under its limit")
    # the _abs threshold must fire on BOTH signs
    if not breach("calibration_intercept_abs", -0.90)[0]:
        f.append("the absolute intercept threshold ignored a large NEGATIVE intercept")
    if not breach("calibration_intercept_abs", 0.90)[0]:
        f.append("the absolute intercept threshold ignored a large positive intercept")
    # an unmeasurable quantity is NOT an alarm, and says why
    hit, d = breach("total_tail_coverage_low", None)
    if hit or "reason" not in d:
        f.append("an unmeasurable quantity produced an alarm instead of a stated non-measurement")

    # --- PROBABILITY-RANGE CONTRACTION: the failure this system actually has -----------------------
    # A model pinned near .5 scores close to a coin flip and trips NO Brier alarm. Only the spread
    # check catches it. This fixture is the reason that check exists.
    flat = mk(120, lambda i, y: 0.50 + (0.004 if i % 2 else -0.004))
    alarms, m = check_window(flat)
    names = {a["alarm"] for a in alarms}
    if "probability_sd_pp_low" not in names:
        f.append(f"a model with a 0.4pp spread did not trip the contraction alarm: {names}")
    if "brier_excess_over_prior" in names:
        f.append("the contraction fixture also tripped the Brier alarm, so the spread check is not "
                 "isolated by it")

    # --- a model WORSE than its own prior ------------------------------------------------------------
    bad = mk(120, lambda i, y: 0.20 if y == 1 else 0.80, p_prior=0.527, home_rate=0.6)
    alarms, m = check_window(bad)
    names = {a["alarm"] for a in alarms}
    if "brier_excess_over_prior" not in names or "logloss_excess_over_prior" not in names:
        f.append(f"a model scoring far worse than its prior did not trip both excess alarms: {names}")

    # --- directional bias ----------------------------------------------------------------------------
    homey = mk(120, 0.72, p_prior=0.527, home_rate=0.55)
    alarms, _ = check_window(homey)
    if "home_pick_share_high" not in {a["alarm"] for a in alarms}:
        f.append("a model picking home in every game did not trip the directional alarm")
    awayey = mk(120, 0.30, p_prior=0.527, home_rate=0.45)
    if "home_pick_share_low" not in {a["alarm"] for a in [*check_window(awayey)[0]]}:
        f.append("a model picking away in every game did not trip the directional alarm")

    # ISOLATION for the directional split. "Which way the model moved" is relative to the PRIOR, not
    # to a coin flip. A probability of .51 against a .527 prior is a move TOWARD AWAY even though it
    # picks home. Every other fixture here uses probabilities far from the prior, so only this one
    # can tell the two rules apart.
    split = [{"p_home_model": 0.51, "p_home_prior": 0.527, "home_win": 1},
             {"p_home_model": 0.55, "p_home_prior": 0.527, "home_win": 0}]
    dd = measure(split)["directional_detail"]
    if (dd["toward_home_n"], dd["toward_away_n"]) != (1, 1):
        f.append(f"the directional split is not measured against the PRIOR: p=.51 and p=.55 against "
                 f"a .527 prior gave {dd['toward_home_n']} toward-home and {dd['toward_away_n']} "
                 f"toward-away, expected 1 and 1")

    # --- a CLEAN window must not fire ------------------------------------------------------------------
    # A GENUINELY HEALTHY WINDOW is harder to build than it looks, and the first attempt here was
    # not one: probabilities of .62/.42 assigned FROM the outcome gave a calibration slope far above
    # 1 and a directional Brier gap that was pure confounding. A clean window needs probabilities
    # that are actually calibrated AND symmetric about .5, so the toward-home and toward-away groups
    # score the same by construction rather than by luck.
    groups, K = [], 50
    for pv in (0.30, 0.40, 0.60, 0.70):
        wins = int(round(pv * K))
        g = []
        for i in range(K):
            # spread the wins EVENLY through the group. Putting them all first makes every ROLLING
            # window unbalanced, which is what made the first healthy fixture fire on its own tail.
            y = 1 if ((i + 1) * wins) // K > (i * wins) // K else 0
            g.append({"p_home_model": pv, "p_home_prior": 0.527, "home_win": y,
                      "starter_information_fraction": 0.8, "market_p_home": 0.55,
                      "total_interval_covered": True})
        groups.append(g)
    # interleave the four probability levels so every rolling window sees the same mixture, and
    # keep them symmetric about .5 so the toward-home and toward-away groups score identically by
    # construction rather than by luck
    clean = [g[i] for i in range(K) for g in groups]
    alarms, m = check_window(clean)
    if alarms:
        f.append(f"a healthy window fired {[a['alarm'] for a in alarms]}")

    # --- ROLLING HORIZONS -----------------------------------------------------------------------------
    r = run(clean[:40])
    for h in ("50", "100", "250"):
        if r["horizons"][h]["status"] != "INSUFFICIENT_SAMPLE":
            f.append(f"horizon {h} reported a verdict on 40 rows")
    if r["any_alarm"]:
        f.append("an alarm fired on a sample too small for any horizon")
    r = run(clean)
    if r["horizons"]["50"]["status"] != "CLEAR" or r["horizons"]["100"]["status"] != "CLEAR":
        f.append(f"healthy rolling windows did not read CLEAR: {r['horizons']['50']['status']}")
    if r["horizons"]["250"]["status"] != "INSUFFICIENT_SAMPLE":
        f.append("a 250-game horizon reported on 200 rows")
    if r["horizons"]["50"]["measurements"]["n"] != 50:
        f.append("the 50-game horizon did not use exactly the most recent 50 rows")
    # the window must be the MOST RECENT rows, not the first
    tail_bad = clean[:150] + mk(60, lambda i, y: 0.50 + (0.003 if i % 2 else -0.003))
    r = run(tail_bad)
    if r["horizons"]["50"]["status"] != "ALARM":
        f.append("recent deterioration did not trip the 50-game window — the rolling window is not "
                 "taking the most recent rows")

    # --- THE RESPONSE ---------------------------------------------------------------------------------
    resp = r["response"]
    if not resp["triggered"] or list(resp["steps"]) != list(RESPONSE):
        f.append(f"the alarm response is not the full preregistered ladder: {resp.get('steps')}")
    if resp.get("action_output") != "BASELINE":
        f.append("the alarm response does not revert action output to the BASELINE")
    for bad_step in FORBIDDEN_RESPONSES:
        if bad_step in resp["steps"]:
            f.append(f"the response ladder contains {bad_step}")
    if "CONTINUE_REGISTERING_CHAMPION_AND_CHALLENGER" not in resp["steps"]:
        f.append("the response stops registering the challenger, so the diagnosis has no data")
    if "DIAGNOSE_BEFORE_RETRAINING" != resp["steps"][-1]:
        f.append("diagnosis is not the final step before any retraining")
    if "does not retune until yesterday" not in resp["note"]:
        f.append("the response does not state that it will not retune on recent losses")
    if response_for([])["triggered"] or response_for([])["steps"]:
        f.append("a response was produced with no alarm fired")

    print("drift_monitor selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("the probability-contraction alarm is removed, so compression goes unseen",
     '    "probability_sd_pp_low": {"limit": 2.50, "direction": "below",',
     '    "probability_sd_pp_low": {"limit": 0.00, "direction": "below",'),
    ("the Brier-excess alarm never fires",
     '    "brier_excess_over_prior": {"limit": 0.0050, "direction": "above",',
     '    "brier_excess_over_prior": {"limit": 99.0, "direction": "above",'),
    ("the log-loss excess alarm never fires",
     '    "logloss_excess_over_prior": {"limit": 0.0100, "direction": "above",',
     '    "logloss_excess_over_prior": {"limit": 99.0, "direction": "above",'),
    ("the directional-bias alarm never fires",
     '    "home_pick_share_high": {"limit": 0.80, "direction": "above",',
     '    "home_pick_share_high": {"limit": 1.10, "direction": "above",'),
    ("the away-side directional alarm never fires",
     '    "home_pick_share_low": {"limit": 0.20, "direction": "below",',
     '    "home_pick_share_low": {"limit": -1.0, "direction": "below",'),
    ("thresholds fire on the wrong side",
     '    hit = (v > t["limit"]) if t["direction"] == "above" else (v < t["limit"])',
     '    hit = (v < t["limit"]) if t["direction"] == "above" else (v > t["limit"])'),
    ("thresholds become inclusive at the boundary",
     '    hit = (v > t["limit"]) if t["direction"] == "above" else (v < t["limit"])',
     '    hit = (v >= t["limit"]) if t["direction"] == "above" else (v <= t["limit"])'),
    ("an absolute threshold reads the SIGNED value, missing one direction entirely",
     '    v = abs(value) if name.endswith("_abs") else value', "    v = value"),
    ("an unmeasurable quantity becomes an alarm",
     '    if value is None:\n        return False, {"value": None, "reason": "not measurable on this window"}',
     '    if value is None:\n        return True, {"value": None, "reason": "not measurable on this window"}'),
    ("an unregistered threshold produces an alarm",
     "    if t is None:\n        return False,", "    if t is None:\n        return True,"),
    ("the rolling window takes the OLDEST rows instead of the most recent",
     "        alarms, m = check_window(rows[-h:])", "        alarms, m = check_window(rows[:h])"),
    ("a horizon reports a verdict on an insufficient sample",
     "        if len(rows) < h:", "        if False:"),
    ("the response ladder drops the revert-to-baseline step",
     '            "action_output": "BASELINE",', '            "action_output": "CHAMPION",'),
    ("the response ladder becomes partial",
     '    return {"triggered": True, "steps": list(RESPONSE),', '    return {"triggered": True, "steps": list(RESPONSE)[:2],'),
    ("the response RETRAINS on the alarm",
     'RESPONSE = (\n    "REDUCE_TRUST_STATUS",', 'RESPONSE = (\n    "RETRAIN",\n    "REDUCE_TRUST_STATUS",'),
    ("the response stops registering the challenger, so diagnosis has no data",
     '    "CONTINUE_REGISTERING_CHAMPION_AND_CHALLENGER",\n', "\n"),
    ("diagnosis stops being the last word before retraining",
     '    "DIAGNOSE_BEFORE_RETRAINING",\n)', '    "DIAGNOSE_BEFORE_RETRAINING",\n    "REFIT",\n)'),
    ("a response is produced with no alarm fired",
     '    if not fired:\n        return {"triggered": False, "steps": [],', '    if False:\n        return {"triggered": False, "steps": [],'),
    ("the response stops saying it will not retune on recent losses",
     '                     "reverse its picks and does not retune until yesterday\'s losses disappear.")}',
     '                     "act.")}'),
    ("the directional split is computed against the model's own mean, not the prior",
     "    toward_home = [(p, y) for p, pr, y in zip(pm, pp, ys) if p > pr]",
     "    toward_home = [(p, y) for p, pr, y in zip(pm, pp, ys) if p > 0.5]"),
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
    if "--thresholds" in sys.argv:
        print(json.dumps({"registered_utc": THRESHOLDS_REGISTERED_UTC,
                          "horizons": list(HORIZONS), "thresholds": THRESHOLDS,
                          "response": list(RESPONSE)}, indent=1))
        sys.exit(0)
    print(__doc__)
