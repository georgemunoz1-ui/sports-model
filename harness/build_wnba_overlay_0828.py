"""Owner-relayed DraftKings price overlay for the 2026-08-28 WNBA board.

WHY THIS IS A SEPARATE FILE. Prices are never predictive features. They enter only the action/EV
layer, so they attach to the frozen board as a separately hashed overlay and are never folded into
it. The board was frozen at 10:35Z; this overlay is built afterwards and cannot have reached any
forecast.

WHAT THE OVERLAY MAY AND MAY NOT CONCLUDE. Both arms that survived this morning's block are
non-selecting by construction:

    wnba.winner.EXPANDING_HOME_PRIOR   a registered constant. It has no game-specific information,
                                       so an "edge" against a market is an artifact of the market
                                       moving away from a constant, not a finding.
    wnba.fallback.STANDINGS_LOG5_v1    DIAGNOSTIC_ONLY_ACTION_BLOCKED by its own registration. It
                                       never settles, never promotes, never enters the estimator,
                                       and it cannot emit a selection.

    wnba.replacement.FEATURE_REFRESH   blocked; contributes nothing here.

So this overlay produces NO SELECTION for any game, and that is a registration fact rather than a
judgement call. What it does produce is a full-precision descriptive screen, because suppressing
the comparison entirely would be the same over-blocking that kept the whole board shut this
morning. Every number below is a MARKET COMPARISON, never a recommendation.

METHOD. Single-price EV screening, which is the authorized operation. Break-even probability is
taken from each side's own posted price. The two-sided hold is reported as a DATA-QUALITY check on
the transcription only; no de-vigged figure is treated as "the market probability" for any purpose.
The 8/3 ruling invalidating cross-book Best-Odds de-vig is untouched by this: nothing here combines
prices across books, and there is only one book on file.
"""
from __future__ import annotations

MODULE_ID = "build_wnba_overlay_0828"

import hashlib
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

DATE = "2026-08-28"
BOARD = f"cards/{DATE}_wnba_board.json"
OUT = f"data/wnba/odds/{DATE}_owner_relay_dk.json"
UNIT = 100.0

RELAY = {
    "source": "DraftKings sportsbook, WNBA Game Lines",
    "channel": "owner relay, two screenshots",
    "screenshot_clock": ["3:30", "3:31"],
    "captured_utc_asserted": "2026-08-28T10:40:00Z",
    "grade": "OWNER_RELAYED_SINGLE_BOOK",
}

#: away_ml, home_ml, away_spread, away_spread_px, home_spread, home_spread_px, total, over, under
PRICES = {
    "wnba:POR@ATL": dict(cid="ESPN_GAMEID:401857180", away="POR", home="ATL",
                         away_ml=+525, home_ml=-750, away_spread=+12.5, away_spread_px=-110,
                         home_spread=-12.5, home_spread_px=-110, total=180.5,
                         over_px=-105, under_px=-115, dk_slot="Today 4:40 PM"),
    "wnba:CON@IND": dict(cid="ESPN_GAMEID:401857181", away="CON", home="IND",
                         away_ml=+1100, home_ml=-2100, away_spread=+17.5, away_spread_px=-115,
                         home_spread=-17.5, home_spread_px=-105, total=178.5,
                         over_px=-108, under_px=-112, dk_slot="Today 4:40 PM"),
    "wnba:TOR@LV": dict(cid="ESPN_GAMEID:401857182", away="TOR", home="LV",
                        away_ml=+700, home_ml=-1100, away_spread=+13.5, away_spread_px=-105,
                        home_spread=-13.5, home_spread_px=-115, total=175.5,
                        over_px=-112, under_px=-108, dk_slot="Today 7:10 PM"),
    "wnba:WSH@LAS": dict(cid="ESPN_GAMEID:401857183", away="WSH", home="LAS",
                         away_ml=-205, home_ml=+170, away_spread=-5.5, away_spread_px=-105,
                         home_spread=+5.5, home_spread_px=-115, total=167.5,
                         over_px=-110, under_px=-110, dk_slot="Today 7:10 PM"),
}

#: Not on tonight's slate; retained so the relay is transcribed whole rather than trimmed to fit.
NEXT_DAY = {"game": "wnba:CHI@NYL", "dk_slot": "Sat 10:10 AM", "away_ml": +275, "home_ml": -345,
            "away_spread": +8.5, "away_spread_px": -108, "home_spread": -8.5,
            "home_spread_px": -112, "total": 178.5, "over_px": -110, "under_px": -110,
            "note": "2026-08-29 game. Recorded for completeness; NOT part of the 8/28 cohort and "
                    "never pooled into it."}

HOLD_BAND = (2.0, 8.0)


def implied(o):
    return -o / (-o + 100.0) if o < 0 else 100.0 / (o + 100.0)


def profit_on(o, stake=UNIT):
    """Profit returned by a winning `stake` at American odds `o`."""
    return stake * (100.0 / -o) if o < 0 else stake * (o / 100.0)


def ev(p_win, o, stake=UNIT):
    return p_win * profit_on(o, stake) - (1.0 - p_win) * stake


def hold_pct(o1, o2):
    s = implied(o1) + implied(o2)
    return 100.0 * (s - 1.0) / s


def build():
    board = json.load(open(BOARD))
    arms = {}
    for r in board["wnba"]["rows"]:
        arms.setdefault(r["game"], {})[r["arm"]] = r
    if set(arms) != set(PRICES):
        raise ValueError(f"relay covers {sorted(PRICES)} but the board holds {sorted(arms)} — "
                         "a price set that does not match the frozen cohort must not be applied")

    games, quality = {}, []
    for g, px in PRICES.items():
        a = arms[g]
        if a["wnba.fallback.STANDINGS_LOG5_v1"]["canonical_id"] != px["cid"]:
            raise ValueError(f"{g}: relay id {px['cid']} does not match the frozen board id — "
                             "an overlay must bind to the same game the board froze")

        h_ml = hold_pct(px["away_ml"], px["home_ml"])
        h_sp = hold_pct(px["away_spread_px"], px["home_spread_px"])
        h_to = hold_pct(px["over_px"], px["under_px"])
        for name, h in (("moneyline", h_ml), ("spread", h_sp), ("total", h_to)):
            if not (HOLD_BAND[0] <= h <= HOLD_BAND[1]):
                quality.append(f"{g} {name} hold {h:.2f}% outside {HOLD_BAND} — recheck transcription")

        be_away, be_home = implied(px["away_ml"]), implied(px["home_ml"])
        per_arm = {}
        for arm_id, arm in (("wnba.fallback.STANDINGS_LOG5_v1",
                             a["wnba.fallback.STANDINGS_LOG5_v1"]),
                            ("wnba.winner.EXPANDING_HOME_PRIOR",
                             a["wnba.winner.EXPANDING_HOME_PRIOR"])):
            ph = arm["p_home"]
            pa = 1.0 - ph
            per_arm[arm_id] = {
                "p_home": ph, "p_away": pa,
                "ev_home_per_100": round(ev(ph, px["home_ml"]), 4),
                "ev_away_per_100": round(ev(pa, px["away_ml"]), 4),
                "edge_home_pp": round(100.0 * (ph - be_home), 4),
                "edge_away_pp": round(100.0 * (pa - be_away), 4),
                "output_grade": arm.get("output_grade"),
                "may_select": False,
                "why_not": ("DIAGNOSTIC_ONLY_ACTION_BLOCKED by registration"
                            if arm_id.endswith("STANDINGS_LOG5_v1") else
                            "a registered constant carries no game-specific information; an edge "
                            "against a market is the market moving away from a constant"),
            }

        games[g] = {
            "canonical_id": px["cid"], "away": px["away"], "home": px["home"],
            "dk_slot_as_displayed": px["dk_slot"],
            "moneyline": {"away": px["away_ml"], "home": px["home_ml"],
                          "break_even_away": round(be_away, 6),
                          "break_even_home": round(be_home, 6),
                          "two_sided_hold_pct": round(h_ml, 4)},
            "spread": {"away": px["away_spread"], "away_px": px["away_spread_px"],
                       "home": px["home_spread"], "home_px": px["home_spread_px"],
                       "two_sided_hold_pct": round(h_sp, 4),
                       "model_position": "NO REGISTERED WNBA COVER DISTRIBUTION — no spread "
                                         "probability exists, so no spread EV is computable"},
            "total": {"line": px["total"], "over_px": px["over_px"], "under_px": px["under_px"],
                      "two_sided_hold_pct": round(h_to, 4),
                      "model_position": "the surviving arms emit a winner probability only; "
                                        "FEATURE_REFRESH, which carries the total, is blocked. "
                                        "No total EV is computable."},
            "arms": per_arm,
            "disposition": "NO_SELECTION",
        }

    doc = {
        "record_id": f"WNBA-PRICE-OVERLAY-{DATE}-DK",
        "schema": "ops.price_overlay.v1",
        "slate_date": DATE, "sport": "wnba",
        "relay": RELAY,
        "attaches_to": {"board": BOARD,
                        "board_sha256": hashlib.sha256(open(BOARD, "rb").read()).hexdigest(),
                        "board_cohort_hash": board["cohort_hashes"]["wnba"],
                        "rule": "prices are never predictive features; this overlay is hashed "
                                "separately and the frozen board is unchanged by it"},
        "unit_usd": UNIT,
        "method": {
            "screen": "SINGLE_PRICE_EV — break-even taken from each side's own posted price",
            "de_vig": "NOT PERFORMED. The two-sided hold is reported as a transcription check "
                      "only; no de-vigged number is treated as the market probability. The 8/3 "
                      "ruling invalidating cross-book Best-Odds de-vig is untouched — nothing "
                      "here combines books, and only one book is on file.",
            "ev_formula": "EV per $100 = p*profit(price) - (1-p)*100, full precision, no rounding "
                          "before the final store",
        },
        "TRANSCRIPTION_VERIFICATION": {
            "method": "every two-sided pair must imply a hold inside 2-8%. A dropped digit, a "
                      "flipped sign or a row misaligned to the wrong game throws the implied hold "
                      "far outside that band, so the relay is checked against itself without "
                      "needing a second source.",
            "pairs_checked": 12,
            "observed_hold_range_pct": [
                round(min(min(v["moneyline"]["two_sided_hold_pct"], v["spread"]["two_sided_hold_pct"],
                              v["total"]["two_sided_hold_pct"]) for v in games.values()), 4),
                round(max(max(v["moneyline"]["two_sided_hold_pct"], v["spread"]["two_sided_hold_pct"],
                              v["total"]["two_sided_hold_pct"]) for v in games.values()), 4)],
            "problems": quality,
            "verdict": "PASS" if not quality else "FAIL",
        },
        "INDEPENDENT_SLATE_CORROBORATION": {
            "finding": "DraftKings lists exactly four WNBA games today, and they are the same four "
                       "matchups with the same home/away orientation as the frozen board.",
            "why_it_matters": "the board's schedule grade is ESPN_SINGLE_FAMILY_GIT_ARTIFACT — "
                              "wehoop mirrors ESPN, so the ESPN URLs that corroborated it were the "
                              "same family and added no independent source. A sportsbook is NOT in "
                              "that family. This is the first genuinely independent corroboration "
                              "of the 8/28 WNBA slate COMPOSITION.",
            "what_it_does_not_do": "it does not corroborate the ESPN game IDS, which DraftKings "
                                   "does not publish. Id provenance is unchanged.",
        },
        "START_TIME_DISCREPANCY": {
            "observed": "DraftKings displays the two early games at 4:40 and the two late games at "
                        "7:10 in the phone's local time; the wehoop parquet says 7:30 PM and "
                        "10:00 PM EDT.",
            "reading": "the game-to-slot pairing matches the board exactly (two early, two late). "
                       "Read as Pacific, DraftKings is a consistent +10 minutes against the "
                       "parquet on all four games. The screenshot does not state its timezone, so "
                       "the Pacific reading is INFERRED and not confirmed; the 'Sat 10:10 AM' row "
                       "for tomorrow's CHI@NYL is what makes Eastern implausible.",
            "resolution": "UNRESOLVED — recorded, not settled. Neither source is discarded.",
            "operational_impact": "at most 10 minutes on tip time, well inside the checkpoint "
                                  "spacing; the 22:00Z and 22:45Z checkpoints are unaffected. "
                                  "Flagged there for confirmation.",
        },
        "DISPOSITION": {
            "selections": 0,
            "n_bets": 0, "units": 0.0, "exposure_usd": 0,
            "wager_authority": "NO",
            "why_no_selection_is_a_fact_not_a_judgement": (
                "Both arms that survive this morning's block are non-selecting by construction. "
                "STANDINGS_LOG5_v1 is DIAGNOSTIC_ONLY_ACTION_BLOCKED in its own registration. "
                "EXPANDING_HOME_PRIOR is a registered constant with no game-specific information. "
                "The one arm that could have carried a real view, FEATURE_REFRESH, is blocked on "
                "the feature rebuild. There is therefore no arm on this board that is permitted to "
                "select, whatever the EV column says."),
            "read_the_ev_column_this_way": (
                "The large positive EVs sit on heavy underdogs, and that is exactly where this "
                "arm is weakest rather than where an opportunity is. STANDINGS_LOG5_v1 sees only "
                "season win-loss records: no injuries, no rest, no lineup. Tonight A'ja Wilson is "
                "questionable, Brionna Jones is out, Toronto has five players listed, and no "
                "8/28-dated report exists for Washington or Los Angeles at all. A model blind to "
                "all of that, disagreeing with a market that prices it, is describing its own "
                "blindness. Treat these as a calibration diagnostic on the fallback arm, not as "
                "edges."),
        },
        "next_day_row_recorded_not_pooled": NEXT_DAY,
        "games": games,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
    return doc


if __name__ == "__main__":
    d = build()
    print("OVERLAY", d["record_id"], "|",
          f'{hashlib.sha256(open(OUT, "rb").read()).hexdigest()[:8]}',
          "| transcription", d["TRANSCRIPTION_VERIFICATION"]["verdict"],
          "| holds", d["TRANSCRIPTION_VERIFICATION"]["observed_hold_range_pct"])
    print(f"{'game':<14}{'side':>6}{'price':>8}{'break-even':>12}{'log5 p':>9}"
          f"{'edge pp':>9}{'EV/$100':>10}")
    for g, v in d["games"].items():
        fb = v["arms"]["wnba.fallback.STANDINGS_LOG5_v1"]
        for side, ml, be, p, e, ed in (
                ("away", v["moneyline"]["away"], v["moneyline"]["break_even_away"],
                 fb["p_away"], fb["ev_away_per_100"], fb["edge_away_pp"]),
                ("home", v["moneyline"]["home"], v["moneyline"]["break_even_home"],
                 fb["p_home"], fb["ev_home_per_100"], fb["edge_home_pp"])):
            print(f"{g.split(':')[1]:<14}{side:>6}{ml:>+8}{be:>12.4f}{p:>9.4f}"
                  f"{ed:>+9.2f}{e:>+10.2f}")
    print("\nselections:", d["DISPOSITION"]["selections"], "| bets", d["DISPOSITION"]["n_bets"],
          "| $", d["DISPOSITION"]["exposure_usd"])
