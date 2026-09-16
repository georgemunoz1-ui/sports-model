"""Two-sided EV screening — every priced side is evaluated, never just the model's pick.

THE DEFECT THIS REPLACES (owner correction, 2026-08-28). The prior screen selected the side with
model probability above 50% and evaluated only that one. That rule is structurally blind: a team
can be LESS likely to win and still carry value at a sufficiently large price, and the old rule
could never see it because it never looked. On the 8/28 MLB board it hid four of the five
plus-money sides — KC, SD, COL and TEX — and surfaced only NYM, which happened to be the one game
where the plus-money side was also the model's pick.

THE REGISTERED ORDER, and it does not stop early:

    model probability for BOTH teams
      -> each team's ACTUAL posted price
      -> raw EV for BOTH sides
      -> conservative EV
      -> disposition

SIDES ARE READ FROM THE RELAYED TEAM LABEL, NEVER INFERRED FROM HOME/AWAY. The plus-money side is
usually the road team and on 8/28 it was the HOME team in HOU@NYM. A screen that assumes the dog is
the away team gets that row wrong — I made exactly that mistake while auditing this correction, and
it is fixed here by construction: a price is bound to a named team or it is refused.

NO DE-VIG. Break-even comes from each side's own posted price. The pair's implied total is computed
ONLY as a transcription check and as a compression diagnostic, and is never used as a probability
in any EV. The 8/3 ruling invalidating cross-book Best-Odds de-vig is untouched.
"""
from __future__ import annotations

MODULE_ID = "two_sided_screen"

import json
import math
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

UNIT = 100.0
HOLD_PLAUSIBLE = (2.0, 8.0)
#: A model-market gap this large on a single side is not tradeable on its face; the preregistered
#: analogue in CFB is a 14-point spread rule. Here it is stated in probability points.
EXTREME_EDGE_PP = 10.0


def implied(o):
    return -o / (-o + 100.0) if o < 0 else 100.0 / (o + 100.0)


def profit(o, stake=UNIT):
    return stake * (100.0 / -o) if o < 0 else stake * (o / 100.0)


def ev(p, o, stake=UNIT):
    return p * profit(o, stake) - (1.0 - p) * stake


def screen_game(game, p_home, home, away, prices):
    """prices: {team_name: american_odds}. Returns one row PER PRICED SIDE.

    Refuses a price whose team is not one of the two named on the game — that is the guard against
    a side being attached by position rather than by identity.
    """
    unknown = [t for t in prices if t not in (home, away)]
    if unknown:
        raise ValueError(f"{game}: price given for {unknown}, which is neither {away} nor {home}. "
                         "A price must bind to a named team; positional assignment is refused.")
    out = []
    imp_sum = sum(implied(o) for o in prices.values()) if len(prices) == 2 else None
    hold = (100.0 * (imp_sum - 1.0) / imp_sum) if imp_sum else None
    for team, o in prices.items():
        p = p_home if team == home else 1.0 - p_home
        be = implied(o)
        out.append({
            "game": game, "team": team, "is_home": team == home,
            "price": o, "model_p": round(p, 6), "break_even": round(be, 6),
            "edge_pp": round(100.0 * (p - be), 4),
            "raw_ev_per_100": round(ev(p, o), 4),
            "conservative_ev": None,
            "conservative_ev_reason": "UNAVAILABLE — pending the RJ-002 consumption-spec review; "
                                      "raw EV is not a substitute and is not authorisation",
            "pair_hold_pct": None if hold is None else round(hold, 4),
        })
    return out, hold


def disposition(row, extreme_pp=EXTREME_EDGE_PP):
    if row["raw_ev_per_100"] <= 0:
        return "PASS_NEGATIVE_EV"
    if row["edge_pp"] >= extreme_pp:
        return "EXTREME_EDGE_AUDIT_REQUIRED"
    return "CANDIDATE_UNAUTHORIZED"


def run(board_path, prices_by_game, arm="mlb.winner.CHAMPION_V13"):
    b = json.load(open(board_path))
    sport = b["sport"]
    by = {}
    for r in b[sport]["rows"]:
        by.setdefault(r["game"], {})[r["arm"]] = r
    rows, holds = [], {}
    for game, prices in prices_by_game.items():
        r = by[game][arm]
        aw, hm = game.split(":")[1].split("@")
        side_rows, hold = screen_game(game, r["p_home"], hm, aw, prices)
        for s in side_rows:
            s["disposition"] = disposition(s)
        rows.extend(side_rows)
        holds[game] = hold
    return rows, holds


def compression_diagnostic(rows):
    """Is a set of positive-EV dogs a finding, or the model's known compression showing through?

    If the model spans less of the probability range than the market does, it is systematically
    above the market on every longshot and below on every favourite. The tell is a positive
    correlation between price and EV across plus-money sides: real edges do not queue up in price
    order.
    """
    plus = [r for r in rows if r["price"] > 0]
    if len(plus) < 3:
        return {"n_plus_sides": len(plus), "verdict": "TOO_FEW_SIDES_TO_DIAGNOSE"}
    xs = [r["price"] for r in plus]
    ys = [r["raw_ev_per_100"] for r in plus]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((a - mx) * (c - my) for a, c in zip(xs, ys))
    vx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    vy = math.sqrt(sum((c - my) ** 2 for c in ys))
    corr = cov / (vx * vy) if vx and vy else float("nan")
    above = sum(1 for r in plus if r["edge_pp"] > 0)
    return {"n_plus_sides": n, "plus_sides_above_market": above,
            "corr_price_vs_ev": round(corr, 4),
            "verdict": ("COMPRESSION_SUSPECTED" if above == n and corr > 0.7 else "NOT_INDICATED"),
            "reading": ("the model is above the market on every plus-money side and the gap widens "
                        "with the price — that is the shape of a compressed probability scale, not "
                        "of independent value findings")}


# =================================================================================================
def selftest():
    f = []
    # THE DEFECT ITSELF: the model's pick is negative-EV and the side it never looked at is not.
    rows, hold = screen_game("mlb:AAA@BBB", p_home=0.5031, home="BBB", away="AAA",
                             prices={"AAA": +121, "BBB": -130})
    fav = next(r for r in rows if r["team"] == "BBB")
    dog = next(r for r in rows if r["team"] == "AAA")
    if len(rows) != 2:
        f.append("screen_game returned fewer than one row per priced side")
    if fav["raw_ev_per_100"] >= 0:
        f.append("fixture broken: the model-favoured side should be negative-EV here")
    if dog["raw_ev_per_100"] <= 0:
        f.append("THE DEFECT: the side below 50% carries positive EV and the screen missed it")
    # the old rule, reconstructed, must demonstrably lose that row
    old_rule = [r for r in rows if r["model_p"] >= 0.5]
    if len(old_rule) != 1 or old_rule[0]["team"] != "BBB":
        f.append("the model-side-only rule was not reconstructed faithfully")
    if any(r["raw_ev_per_100"] > 0 for r in old_rule):
        f.append("the old rule was expected to surface no positive-EV side on this fixture")

    # a price attached to a team not in the game is refused, not silently positioned
    try:
        screen_game("mlb:AAA@BBB", 0.5, "BBB", "AAA", {"AAA": +100, "CCC": -110})
        f.append("a price for a team not in the game was accepted")
    except ValueError:
        pass

    # HOME can be the plus-money side — the row that broke my own first audit
    hrows, _ = screen_game("mlb:HOU@NYM", p_home=0.521333, home="NYM", away="HOU",
                           prices={"NYM": +101, "HOU": -102})
    nym = next(r for r in hrows if r["team"] == "NYM")
    if not nym["is_home"] or nym["price"] != 101:
        f.append("the plus-money price was not bound to the HOME team where it belonged")
    if abs(nym["raw_ev_per_100"] - 4.788) > 0.01:
        f.append(f"home-dog EV wrong: {nym['raw_ev_per_100']}")

    # dispositions
    if disposition({"raw_ev_per_100": -1.0, "edge_pp": 5.0}) != "PASS_NEGATIVE_EV":
        f.append("negative EV did not pass")
    if disposition({"raw_ev_per_100": 39.5, "edge_pp": 12.8}) != "EXTREME_EDGE_AUDIT_REQUIRED":
        f.append("an extreme edge was not sent to audit")
    if disposition({"raw_ev_per_100": 4.8, "edge_pp": 2.5}) != "CANDIDATE_UNAUTHORIZED":
        f.append("an ordinary positive edge was not marked candidate-unauthorized")
    # conservative EV must never be silently filled in
    if any(r["conservative_ev"] is not None for r in rows):
        f.append("conservative EV was populated while the consumption spec is unreviewed")

    # the compression diagnostic must fire on a price-ordered edge ladder and not on a flat one
    ladder = [{"price": p, "raw_ev_per_100": e, "edge_pp": g}
              for p, e, g in ((101, 4.8, 2.5), (120, 4.5, 2.9), (121, 9.8, 5.2),
                              (194, 17.3, 5.9), (210, 39.5, 12.8))]
    if compression_diagnostic(ladder)["verdict"] != "COMPRESSION_SUSPECTED":
        f.append("compression diagnostic missed a monotone price-ordered edge ladder")
    flat = [{"price": p, "raw_ev_per_100": e, "edge_pp": 1.0}
            for p, e in ((101, 9.0), (120, -2.0), (194, 3.0), (210, -5.0))]
    if compression_diagnostic(flat)["verdict"] == "COMPRESSION_SUSPECTED":
        f.append("compression diagnostic fired on a set with negative-edge sides")

    print("two_sided_screen selftest:", "FAIL" if f else
          "PASS (both sides always screened; the model-side-only rule demonstrably loses a "
          "positive-EV dog; a price for a team not in the game is refused; the plus-money side may "
          "be HOME; conservative EV stays unavailable; compression diagnostic separates a "
          "price-ordered ladder from a flat set)")
    for x in f:
        print("   -", x)
    return 1 if f else 0


if __name__ == "__main__":
    import sys
    sys.exit(selftest())
