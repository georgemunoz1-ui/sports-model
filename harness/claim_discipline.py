"""Two rules adopted 2026-08-29, enforced rather than written.

RULE 1 — CONVERGENCE MUST QUOTE MAGNITUDE, NOT ONLY DIRECTION.
On 2026-08-29 TCU -8.5 was ranked the board's only "full-convergence play": house arm, external
sim and market all on TCU. TCU lost outright, UNC 15-10. The residuals ordered themselves exactly
by distance from the price — market 0.73 sigma, sim 0.90, ensemble 1.19, house arm 1.33. Agreement
on SIDE had concealed an 11-point disagreement on MAGNITUDE (house +19.4 against a market +8.5),
and the signal furthest from the price was the one furthest from the outcome. A convergence claim
that cannot quote its magnitude spread is not evidence of agreement; it is evidence that nobody
looked.

RULE 2 — NO TOTALS PLAY WITHOUT A MEASURED TOTALS ERROR TERM FOR THAT SPORT.
Margins earned their sigma by measurement this week (CFB 16.716 over 10,818 retained OOF
residuals; WNBA 12.5523 over 1,721). Totals had no such term anywhere, and three observations were
read as a systematic high bias. The gate refuses a totals play until the sport has a measured
sigma on file, and refuses to accept an MAE-inferred one in its place.

WHAT MEASURING IT ACTUALLY SHOWED, and it is the reason this module records evidence rather than a
verdict: on the only sport where per-game totals residuals are recoverable today, the model runs
LOW, not high. WNBA n=1721, mean residual -0.7352 (t = -1.69), sigma 18.0156. The high-bias
observations all trace to the external sim or to ensembles containing it, not to a registered house
arm. So "totals run high" is a property of specific arms and is not systemic — which is a finding
the moratorium would have hidden if it had been left as a standing prohibition instead of a
question with a measurement attached.
"""
from __future__ import annotations

MODULE_ID = "claim_discipline"

import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: sport -> path to a MEASURED totals sigma record. Absent sport = no totals play permitted.
TOTALS_SIGMA_RECORDS = {
    "wnba": "data/wnba/model/wnba_total_sd_measurement.json",
}


class ClaimRefused(Exception):
    pass


def convergence_claim(name, signals, market):
    """Assert convergence honestly. signals: {label: predicted_margin}. Raises if magnitude is not
    quotable, returns the spread that MUST accompany the claim.

    A claim is only 'convergent' if the signals agree on side AND their magnitude spread is stated.
    This function never decides whether the spread is small enough — that is a judgment. It refuses
    to let the claim be made without the number in hand.
    """
    if len(signals) < 2:
        raise ClaimRefused(f"{name}: convergence needs at least two signals, got {len(signals)}")
    vals = list(signals.values())
    sides = {v >= market for v in vals}
    same_side = len(sides) == 1
    spread = max(vals) - min(vals)
    furthest = max(signals.items(), key=lambda kv: abs(kv[1] - market))
    return {
        "claim": name,
        "same_side_as_each_other": same_side,
        "market": market,
        "signals": dict(signals),
        "magnitude_spread": round(spread, 4),
        "max_departure_from_market": {"label": furthest[0],
                                      "delta": round(furthest[1] - market, 4)},
        "REQUIRED_DISCLOSURE": (
            f"signals agree on side: {same_side}; magnitude spread {spread:.1f} pts; furthest from "
            f"price is {furthest[0]} at {furthest[1] - market:+.1f}. Quote all three or do not "
            "call it convergence."),
    }


def totals_sigma(sport):
    """The MEASURED totals sigma for a sport, or None. An MAE-inferred value is not accepted."""
    p = TOTALS_SIGMA_RECORDS.get(sport)
    if not p:
        return None
    full = os.path.join(BASE, p)
    if not os.path.exists(full):
        return None
    d = json.load(open(full))
    return d.get("sd_measured")


def assert_totals_playable(sport):
    """Refuse a totals play on a sport with no measured totals error term."""
    s = totals_sigma(sport)
    if s is None:
        raise ClaimRefused(
            f"TOTALS REFUSED for {sport!r}: no measured totals error term on file. Margins earned "
            "their sigma by measurement; totals have not. An MAE-inferred sigma does not satisfy "
            "this — measure the residuals or do not play the total.")
    return s


def selftest():
    f = []
    # C1 — the TCU case. Same side, but an 11-point magnitude spread that must be quoted.
    c = convergence_claim("TCU -8.5", {"house": 19.4, "sim": 11.5}, market=8.5)
    if not c["same_side_as_each_other"]:
        f.append("C1: TCU signals were on the same side and were reported otherwise")
    if abs(c["magnitude_spread"] - 7.9) > 1e-9:
        f.append(f"C1: magnitude spread {c['magnitude_spread']}, expected 7.9")
    if c["max_departure_from_market"]["label"] != "house":
        f.append("C1: the house arm was furthest from the price and was not identified as such")
    if "magnitude spread" not in c["REQUIRED_DISCLOSURE"]:
        f.append("C1: the disclosure omits the magnitude spread")

    # C2 — a single signal can never be a convergence claim.
    try:
        convergence_claim("solo", {"house": 10.0}, market=5.0)
        f.append("C2: a one-signal convergence claim was accepted")
    except ClaimRefused:
        pass

    # C3 — WNBA totals ARE measured, so a totals play is permitted there.
    try:
        s = assert_totals_playable("wnba")
        if not (17.0 < s < 19.0):
            f.append(f"C3: wnba totals sigma {s} outside the measured range")
    except ClaimRefused as e:
        f.append(f"C3: wnba totals refused despite a measured record: {e}")

    # C4 — CFB/MLB/NFL totals are NOT measured, so they must refuse.
    for sport in ("cfb", "mlb", "nfl"):
        try:
            assert_totals_playable(sport)
            f.append(f"C4: {sport} totals accepted with no measured error term")
        except ClaimRefused:
            pass

    print(f"{MODULE_ID} selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("  !", x)
    return 0 if not f else 1


if __name__ == "__main__":
    sys.exit(selftest())
