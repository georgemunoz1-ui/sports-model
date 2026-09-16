#!/usr/bin/env python3
"""MARKET OVERLAY, 2026-09-01 — prices join the two FROZEN forecast sets, after the fact.

ORDER OF OPERATIONS, kept honest: my v2 freeze (07:0xZ) and the owner's PA-state shadow v2 were
both registered BEFORE any price below was captured. Prices were then acquired over the search
rung — each pair is a SINGLE NAMED SOURCE's two-sided quote, de-vigged within that pair only
(cross-book de-vig is INVALID and is not done). A search-lane price identifies; it does not
constitute a book feed, and the whole card is paper-only regardless.

MIL@CHC is the honest hole: two sources disagree on WHICH SIDE IS FAVOURED (youwager MIL -132 /
CHC +110 against rawchili CHC -126 / MIL +108). Opposite-favourite quotes cannot be averaged,
picked between, or "resolved" from here — the row is CONFLICTED_PRICE and carries no decision.

TWO OVERLAYS from the same prices:
  mine    dose-scaled edge on the V13 freeze (edge = dose x (p_raw - novig), bar 3pp).
          Doses are 0.20-0.25 slate-wide, so this card mostly WAITS — that is what a stale
          pitcher corpus is supposed to produce.
  owner   the owner's Model/Sim mean vs the same novig, decided with the owner's own v5
          vocabulary (PLAY > 6pp usable, LEAN 3-6, PASS < 3; DIR_SPLIT rows carry no side).
          The owner's board has no dose register, so its usable edge IS its raw edge and is
          labelled UNSHRUNK — reader beware, that asymmetry is disclosed, not hidden.
"""

MODULE_ID = "market_overlay_0901"

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SLATE_DATE = "2026-09-01"
FREEZE_V2 = "cards/2026-09-01_mlb_board_FREEZE_v2.json"
OWNER_V2 = "cards/2026-09-01_mlb_owner_shadow_v2.json"
OUT = "cards/2026-09-01_mlb_market_overlay.json"

CAPTURED_UTC = "2026-08-31T2xxxZ-see-git-commit-timestamp"

# ONE two-sided quote per game from ONE named source. American odds, (away_ml, home_ml).
PRICES = {
    "SD@CIN":  {"away_ml": -134, "home_ml": +114, "source": "rawchili 5086844"},
    "SF@PIT":  {"away_ml": +136, "home_ml": -162, "source": "rawchili 5086844"},
    "NYM@TB":  {"away_ml": +108, "home_ml": -126, "source": "rawchili 5086844"},
    "TOR@CLE": {"away_ml": +152, "home_ml": -180, "source": "rawchili 5086844"},
    "ATL@WSH": {"away_ml": -164, "home_ml": +138, "source": "rawchili 5086844"},
    "SEA@BOS": {"away_ml": +106, "home_ml": -124, "source": "rawchili 5086844"},
    "DET@MIN": {"away_ml": -112, "home_ml": -104, "source": "rawchili 5086844"},
    "MIA@KC":  {"away_ml": +100, "home_ml": -118, "source": "rawchili 5086844"},
    "MIL@CHC": None,  # CONFLICTED_PRICE - see module docstring
    "ATH@TEX": {"away_ml": +126, "home_ml": -152, "source": "youwager blog 8/31",
                "alt_quote": "rawchili +160/-190 same direction, wider"},
    "CWS@HOU": {"away_ml": +126, "home_ml": -152, "source": "youwager blog 8/31",
                "alt_quote": "unpaired 'HOU -130' snippet, same direction"},
    "BAL@COL": {"away_ml": -142, "home_ml": +120, "source": "rawchili 5086844"},
    "NYY@LAA": {"away_ml": -145, "home_ml": +125, "source": "youwager blog 8/31"},
    "PHI@AZ":  {"away_ml": -134, "home_ml": +114, "source": "rawchili 5086844"},
    "STL@LAD": {"away_ml": +150, "home_ml": -180, "source": "sportsbetting3/BetRivers"},
}

MIL_CHC_CONFLICT = {"youwager": {"away_ml": -132, "home_ml": +110},
                    "rawchili": {"away_ml": +108, "home_ml": -126},
                    "code": "CONFLICTED_PRICE_OPPOSITE_FAVOURITES"}

PLAY_BAR_PP = 6.0
LEAN_FLOOR_PP = 3.0


def implied(american):
    return (-american) / ((-american) + 100) if american < 0 else 100 / (american + 100)


def novig_home(m):
    ih, ia = implied(m["home_ml"]), implied(m["away_ml"])
    return ih / (ih + ia)


def my_overlay():
    import mlb_daily_coordinator as C
    out = []
    for g in json.load(open(FREEZE_V2))["games"]:
        ev = g["event"]
        m = PRICES.get(ev)
        fc = dict(g["forecast"])
        fc["resolved_information_dose"] = g["snapshot"]["resolved_information_dose"]
        if m is None:
            out.append({"event": ev, "execution_state": "NO_LINE",
                        "why": MIL_CHC_CONFLICT["code"], "valued": False})
            continue
        ov = C.market_overlay(fc, m)
        ov["price_source"] = m["source"]
        out.append(ov)
    return out


def owner_overlay():
    card = json.load(open(OWNER_V2))
    out = []
    for r in card["rows"]:
        ev = r["event"]
        m = PRICES.get(ev)
        row = {"event": ev, "flags": r["flags"]}
        if "MODEL_SIM_DIRECTION_SPLIT" in r["flags"]:
            row.update({"decision": "NO_SIDE", "why": "owner DIR_SPLIT rule: engines cross 50%"})
            out.append(row)
            continue
        if m is None:
            row.update({"decision": "NO_LINE", "why": MIL_CHC_CONFLICT["code"]})
            out.append(row)
            continue
        nv_h = novig_home(m)
        p_home = (r["model_home_pct"] + r["sim_home_pct"]) / 200.0
        # selection-first: the side with the positive edge, probabilities from its perspective
        if p_home >= nv_h:
            sel, p_sel, nv_sel, ml = ev.split("@")[1], p_home, nv_h, m["home_ml"]
        else:
            sel, p_sel, nv_sel, ml = ev.split("@")[0], 1 - p_home, 1 - nv_h, m["away_ml"]
        edge = 100 * (p_sel - nv_sel)
        decision = ("PLAY" if edge > PLAY_BAR_PP else
                    "LEAN" if edge >= LEAN_FLOOR_PP else "PASS")
        row.update({"selection": "%s ML" % sel, "selection_ml": ml,
                    "p_selection": round(p_sel, 4), "novig_selection": round(nv_sel, 4),
                    "edge_pp_unshrunk": round(edge, 2), "decision": decision,
                    "price_source": m["source"],
                    "edge_basis": "owner mean(Model,Sim) minus same-pair novig; UNSHRUNK - "
                                  "the owner board carries no dose register"})
        out.append(row)
    return out


def build():
    mine = my_overlay()
    owner = owner_overlay()
    return {
        "schema": "ops.market_overlay.v1", "sport": "mlb", "slate_date": SLATE_DATE,
        "record_id": "2026-09-01_mlb_market_overlay",
        "ORDER": {"forecasts_frozen_first": [FREEZE_V2, OWNER_V2],
                  "prices_captured_after": True,
                  "price_lane": "SEARCH - single named source per pair, de-vig within pair only",
                  "cross_book_devig": "NOT DONE (invalid)"},
        "PRICES": {k: v for k, v in PRICES.items()},
        "MIL_CHC_CONFLICT": MIL_CHC_CONFLICT,
        "MY_V13_OVERLAY": mine,
        "OWNER_PA_STATE_OVERLAY": owner,
        "LEDGER": {"wager_authority": "NO", "exposure_usd": 0, "n_bets": 0, "units": 0.0,
                   "paper_only": True, "no_guarantees": True},
        "CAVEATS": [
            "search-lane prices identify a market; they are not a book feed and may be stale",
            "lineups unconfirmed 0/30 at capture; BOS starter TBD",
            "verify starters/lineups/injuries before acting on any recommendation",
        ],
    }


def selftest():
    f = []
    if abs(implied(-134) - 134 / 234) > 1e-9 or abs(implied(+114) - 100 / 214) > 1e-9:
        f.append("implied() wrong")
    if set(PRICES) != {g["event"] for g in json.load(open(FREEZE_V2))["games"]}:
        f.append("price table and freeze disagree on the slate")
    mine = my_overlay()
    if [r for r in mine if r["event"] == "MIL@CHC"][0]["execution_state"] != "NO_LINE":
        f.append("conflicted price row was valued on my overlay")
    ow = owner_overlay()
    if [r for r in ow if r["event"] == "MIA@KC"][0]["decision"] != "NO_SIDE":
        f.append("DIR_SPLIT row got a side")
    if [r for r in ow if r["event"] == "MIL@CHC"][0]["decision"] != "NO_LINE":
        f.append("conflicted price row got a decision on owner overlay")
    for r in ow:
        if r.get("edge_pp_unshrunk") is not None and r["edge_pp_unshrunk"] < 0:
            f.append("selection-first violated: negative edge on %s" % r["event"])
    print("%s selftest: %s" % (MODULE_ID, "PASS" if not f else "FAIL"))
    for x in f:
        print("  -", x)
    return not f


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    card = build()
    with open(OUT, "w") as fh:
        json.dump(card, fh, indent=1, sort_keys=True)
    print("written ->", OUT)
    for r in card["OWNER_PA_STATE_OVERLAY"]:
        print("%-8s %-8s %-8s edge %s" % (r["event"], r.get("selection", "-"),
                                          r.get("decision"), r.get("edge_pp_unshrunk")))
    print("--- mine:")
    for r in card["MY_V13_OVERLAY"]:
        print("%-8s %-12s edge %s (raw %s, dose %s)" % (
            r["event"], r.get("execution_state"), r.get("edge_pp_home"),
            r.get("edge_pp_undosed"), r.get("dose")))
