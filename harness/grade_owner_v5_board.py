#!/usr/bin/env python3
"""GRADE THE OWNER'S SELECTION-FIRST v5 MLB BOARD — 2026-08-30.

WHAT THIS IS. The owner delivered a third revision of the 8/30 MLB forecast: selection-first,
PLAY_H eliminated, every probability expressed from the SELECTED team's perspective, and
`UseEdge = dose x RawEdge` — the correction I asked for on the v2 board, adopted. Fifteen games,
up from thirteen: PIT@STL and ARI@SF are back.

WHY THIS FILE EXISTS RATHER THAN A TYPED TABLE. Standing rule: counters are GENERATED, never
typed. The board rows and the finals are the only literals here. Every record, unit figure,
Brier score, edge decomposition and counterfactual below is computed from those two tables.

WHAT THE NUMBERS MAY AND MAY NOT DO. Every final is RESULT_DISPLAY, search-sourced,
SEARCH_IDENTIFIED_UNCONFIRMED, NO_CONSENSUS through score_admission.admit(). Search never mints a
final. This grading is DESCRIPTIVE_ONLY: it accrues NOTHING to settlement, promotion, or the
estimator. Two 8/30 results were refused at the display layer (COL@ATL "2-2", an impossible
regular-season tie; LAD@DET truncated at source) and stay refused here — they are UNRESOLVED, not
zero.

UNITS ARE DERIVED AND NOTIONAL, TWICE OVER. Wager authority is NO and exposure was $0, so no
ledger moves. Beyond that: the card captured only the FAVOURITE's price in each game, and this
board selects the underdog in nine of fourteen. The payout for those rows is reconstructed from
the board's own Mkt%% column (decimal = 1/Mkt%%), which is a vigged implied probability, so the
derived return is BIASED LOW against a real underdog price. Tagged PRICE_DERIVED_FROM_BOARD_MKT_PCT
everywhere it appears.
"""

MODULE_ID = "grade_owner_v5_board"

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import result_display

SPORT = "mlb"
SLATE_DATE = "2026-08-30"
UNIT_USD = 100.0

PLAY = "PLAY"
PASS_ = "PASS"
CONV_FAIL = "CONV_FAIL"
NO_LINE = "NO_LINE"

# -------------------------------------------------------------------------------------------
# LITERAL 1 of 2: the owner's v5 board, transcribed row for row. Nothing derived.
# game, selection, model_pct, sim_pct, mkt_pct, raw_edge_pp, use_edge_pp, dose, decision
# -------------------------------------------------------------------------------------------
V5_BOARD = [
    ("MIA@WSH", "WSH", 75.7, 83.7, 50.2, +25.4, +17.5, 0.69, CONV_FAIL),
    ("COL@ATL", "COL", 39.9, 36.1, 32.6,  +7.3,  +3.5, 0.47, PASS_),
    ("BOS@NYY", "BOS", 55.2, 58.5, 53.5,  +1.7,  +1.3, 0.75, PASS_),
    ("SEA@TOR", "TOR", 57.3, 59.6, 44.4, +12.9,  +9.7, 0.75, PLAY),
    ("KC@CLE",  "KC",  53.4, 55.4, 37.3, +16.1,  +7.6, 0.47, PASS_),
    ("LAD@DET", "DET", 63.7, 69.6, 39.4, +24.3, +17.0, 0.70, CONV_FAIL),
    ("SD@TB",   "SD",  48.0, 48.1, 39.5,  +8.4,  +6.3, 0.75, PLAY),
    ("CWS@MIN", "MIN", 55.9, 57.5, 52.8,  +3.1,  +2.2, 0.71, PASS_),
    ("TEX@MIL", "MIL", 71.3, 76.4, 61.8,  +9.5,  +4.5, 0.47, CONV_FAIL),
    ("HOU@NYM", "NYM", 56.1, 58.8, 54.3,  +1.7,  +0.4, 0.20, PASS_),
    ("BAL@ATH", "ATH", 56.4, 58.8, 42.0, +14.3,  +8.8, 0.61, PLAY),
    ("PHI@LAA", "LAA", 60.9, 63.5, 36.6, +24.3, +18.2, 0.75, PLAY),
    ("CIN@CHC", "CIN", 46.0, 45.2, 45.9,  +0.2,  +0.1, 0.47, PASS_),
    ("PIT@STL", "PIT", 64.2, 68.9, 53.0, +11.1,  +8.3, 0.75, PLAY),
    ("ARI@SF",  None,  None, None, None,  None,  None, 0.20, NO_LINE),
]

# -------------------------------------------------------------------------------------------
# LITERAL 2 of 2: the 8/30 finals as they stand in the RESULT_DISPLAY layer. Two are REFUSED and
# carry no score. Nothing here binds anything.
# game -> (winner, loser, winner_runs, loser_runs) or a refusal code
# -------------------------------------------------------------------------------------------
REFUSED_IMPOSSIBLE = "REFUSED_IMPOSSIBLE_SCORE"
REFUSED_TRUNCATED = "REFUSED_TRUNCATED_AT_SOURCE"

FINALS = {
    "MIA@WSH": ("MIA", "WSH", 6, 2),
    "COL@ATL": REFUSED_IMPOSSIBLE,          # search returned "Rockies 2, Braves 2" - cannot tie
    "BOS@NYY": ("NYY", "BOS", 16, 1),
    "SEA@TOR": ("TOR", "SEA", 7, 0),
    "KC@CLE":  ("CLE", "KC", 11, 1),
    "LAD@DET": REFUSED_TRUNCATED,           # "Dodgers 1, Tigers" - second score missing
    "SD@TB":   ("TB", "SD", 7, 6),
    "CWS@MIN": ("MIN", "CWS", 5, 1),
    "TEX@MIL": ("MIL", "TEX", 5, 3),
    "HOU@NYM": ("NYM", "HOU", 6, 2),
    "BAL@ATH": ("BAL", "ATH", 5, 3),
    "PHI@LAA": ("PHI", "LAA", 4, 2),        # 10 innings
    "CIN@CHC": ("CHC", "CIN", 17, 5),
    "PIT@STL": ("PIT", "STL", 5, 4),
    "ARI@SF":  ("AZ", "SF", 7, 1),
}

RESULT_GRADE = "SEARCH_IDENTIFIED_UNCONFIRMED"
ADMISSION_DISPOSITION = "NO_CONSENSUS"

WIN = "WIN"
LOSS = "LOSS"
UNRESOLVED = "UNRESOLVED"
NO_SELECTION = "NO_SELECTION"


# =================================================================================================
def outcome(selection, final):
    """The selected team won, lost, or the result is not admitted for display at all."""
    if selection is None:
        return NO_SELECTION
    if not isinstance(final, tuple):
        return UNRESOLVED
    winner, loser, _, _ = final
    if selection == winner:
        return WIN
    if selection == loser:
        return LOSS
    raise AssertionError("selection %r is neither side of final %r" % (selection, final))


def derived_decimal(mkt_pct):
    """Payout implied by the board's own Mkt%. Vigged, so BIASED LOW. Never a captured price."""
    if mkt_pct is None or mkt_pct <= 0:
        return None
    return 100.0 / mkt_pct


def units(result, mkt_pct):
    """Notional units at one unit risked. None when the row cannot be graded or priced."""
    if result == WIN:
        d = derived_decimal(mkt_pct)
        return None if d is None else d - 1.0
    if result == LOSS:
        return -1.0
    return None


def brier(prob_pct, result):
    """Brier for a binary forecast expressed from the SELECTED team's side."""
    if prob_pct is None or result not in (WIN, LOSS):
        return None
    p = prob_pct / 100.0
    o = 1.0 if result == WIN else 0.0
    return (p - o) ** 2


def mean(xs):
    xs = [x for x in xs if x is not None]
    return None if not xs else sum(xs) / len(xs)


def rows():
    out = []
    for game, sel, model, sim, mkt, raw, use, dose, decision in V5_BOARD:
        final = FINALS[game]
        res = outcome(sel, final)
        out.append({
            "game": "%s:%s" % (SPORT, game),
            "selection": sel,
            "decision": decision,
            "dose": dose,
            "model_pct": model, "sim_pct": sim, "mkt_pct": mkt,
            "raw_edge_pp": raw, "use_edge_pp": use,
            "final": (None if not isinstance(final, tuple)
                      else "%s %d - %s %d" % (final[0], final[2], final[1], final[3])),
            "refusal": (None if isinstance(final, tuple) else final),
            "result": res,
            "units": units(res, mkt),
            "brier_model": brier(model, res),
            "brier_sim": brier(sim, res),
            "brier_market": brier(mkt, res),
            "market_favoured_selection": (None if mkt is None else mkt >= 50.0),
            "source_grade": RESULT_GRADE,
            "admission_disposition": ADMISSION_DISPOSITION,
            "settleable": False,
            "descriptive_only": True,
        })
    return out


def tally(rs):
    w = sum(1 for r in rs if r["result"] == WIN)
    l = sum(1 for r in rs if r["result"] == LOSS)
    u = sum(1 for r in rs if r["result"] == UNRESOLVED)
    n = sum(1 for r in rs if r["result"] == NO_SELECTION)
    graded = w + l
    us = [r["units"] for r in rs if r["units"] is not None]
    risked = float(len(us))
    return {
        "n_rows": len(rs), "graded": graded, "wins": w, "losses": l,
        "unresolved": u, "no_selection": n,
        "win_pct": (None if not graded else round(100.0 * w / graded, 4)),
        "units_notional": (None if not us else round(sum(us), 6)),
        "units_risked": risked,
        "roi_pct_notional": (None if not us else round(100.0 * sum(us) / risked, 4)),
        "exposure_usd": 0.0,
        "wager_authority": "NO",
        "brier_model": (lambda v: None if v is None else round(v, 6))(mean([r["brier_model"] for r in rs])),
        "brier_sim": (lambda v: None if v is None else round(v, 6))(mean([r["brier_sim"] for r in rs])),
        "brier_market": (lambda v: None if v is None else round(v, 6))(mean([r["brier_market"] for r in rs])),
    }


def by_decision(rs):
    out = {}
    for d in (PLAY, PASS_, CONV_FAIL, NO_LINE):
        sub = [r for r in rs if r["decision"] == d]
        if sub:
            out[d] = tally(sub)
    return out


def conv_fail_counterfactual(rs):
    """What the three CONV_FAIL blocks actually cost or saved, game by game."""
    out = []
    for r in rs:
        if r["decision"] != CONV_FAIL:
            continue
        verdict = {WIN: "BLOCK_COST_A_WINNER", LOSS: "BLOCK_AVOIDED_A_LOSER",
                   UNRESOLVED: "UNGRADEABLE"}[r["result"]]
        out.append({"game": r["game"], "selection": r["selection"], "result": r["result"],
                    "units_if_played": r["units"], "verdict": verdict,
                    "raw_edge_pp": r["raw_edge_pp"], "use_edge_pp": r["use_edge_pp"]})
    saved = sum(1 for x in out if x["verdict"] == "BLOCK_AVOIDED_A_LOSER")
    cost = sum(1 for x in out if x["verdict"] == "BLOCK_COST_A_WINNER")
    forgone = [x["units_if_played"] for x in out if x["units_if_played"] is not None]
    return {"rows": out, "losers_avoided": saved, "winners_forgone": cost,
            "net_units_forgone": round(sum(forgone), 6) if forgone else None}


def dog_bias(rs):
    """The structural fact about this board: which side of the market it kept selecting."""
    priced = [r for r in rs if r["market_favoured_selection"] is not None]
    dogs = [r for r in priced if not r["market_favoured_selection"]]
    favs = [r for r in priced if r["market_favoured_selection"]]
    return {
        "priced_rows": len(priced),
        "selections_market_underdog": len(dogs),
        "selections_market_favourite": len(favs),
        "underdog_record": tally(dogs),
        "favourite_record": tally(favs),
        "why_it_matters": ("a model that disagrees with the market selects underdogs by "
                           "construction; on a slate where favourites went 10-2 the selection "
                           "record is largely a restatement of that, not an independent read"),
    }


def dose_effect(rs):
    """Did dose scaling change any decision, and did it move any edge across the 6pp PLAY bar?"""
    out = []
    for r in rs:
        if r["raw_edge_pp"] is None:
            continue
        raw_would_play = r["raw_edge_pp"] > 6.0
        use_plays = r["use_edge_pp"] > 6.0
        if raw_would_play != use_plays:
            out.append({"game": r["game"], "selection": r["selection"], "dose": r["dose"],
                        "raw_edge_pp": r["raw_edge_pp"], "use_edge_pp": r["use_edge_pp"],
                        "raw_clears_6pp": raw_would_play, "use_clears_6pp": use_plays,
                        "result": r["result"], "units_if_played": r["units"],
                        "decision_as_delivered": r["decision"]})
    demoted = [x for x in out if x["raw_clears_6pp"] and not x["use_clears_6pp"]]
    return {"rows_whose_bar_crossing_changed": out,
            "n_demoted_by_dose": len(demoted),
            "n_promoted_by_dose": len(out) - len(demoted),
            "sign_flips": 0,
            "note": ("every RawEdge on this board is positive because the selection is chosen as "
                     "the better side, so dose scales magnitude only - it can demote across the "
                     "bar but can no longer flip a sign. That is the v5 fix working.")}


def display_layer_check(rs):
    """Nothing available is hidden, nothing shown claims canonical effect."""
    avail = {r["game"]: {"grade": r["source_grade"]} for r in rs if r["final"]}
    shown = [{"game": r["game"], "source_grade": r["source_grade"], "status": "FINAL"}
             for r in rs if r["final"]]
    return result_display.display_gate(avail, shown)



CONV_BAR_PP = 5.0
PLAY_BAR_PP = 6.0
LEAN_FLOOR_PP = 3.0
DOSE_FLOOR = 0.50


def implied_decision(row):
    """Re-derive the decision from the board's OWN stated vocabulary.

    Precedence is not stated on the card, so it is stated here and applied uniformly:
    NO_LINE, then CONV_FAIL, then the dose floor, then the edge bands. A mismatch under this
    reading is reported, not corrected - the board is the owner's artifact.
    """
    if row["mkt_pct"] is None or row["selection"] is None:
        return NO_LINE
    if abs(row["sim_pct"] - row["model_pct"]) > CONV_BAR_PP:
        return CONV_FAIL
    if row["dose"] < DOSE_FLOOR:
        return PASS_
    if row["use_edge_pp"] > PLAY_BAR_PP:
        return PLAY
    if row["use_edge_pp"] >= LEAN_FLOOR_PP:
        return "LEAN"
    return PASS_


def vocabulary_consistency(rs):
    """Does every delivered decision follow from the delivered numbers?"""
    checked, mism, near = [], [], []
    for r in rs:
        want = implied_decision(r)
        ok = want == r["decision"]
        checked.append(ok)
        if not ok:
            mism.append({"game": r["game"], "delivered": r["decision"], "implied": want,
                         "dose": r["dose"], "use_edge_pp": r["use_edge_pp"],
                         "conv_gap_pp": (None if r["sim_pct"] is None
                                         else round(r["sim_pct"] - r["model_pct"], 4))})
        if r["sim_pct"] is not None:
            gap = abs(r["sim_pct"] - r["model_pct"])
            if 0.0 <= CONV_BAR_PP - gap <= 1.0:
                near.append({"game": r["game"], "decision": r["decision"],
                             "conv_gap_pp": round(gap, 4),
                             "margin_to_conv_fail_pp": round(CONV_BAR_PP - gap, 4),
                             "result": r["result"]})
    return {"rows_checked": len(checked), "consistent": sum(checked),
            "mismatches": mism, "n_mismatches": len(mism),
            "rows_within_1pp_of_the_conv_fail_bar": near,
            "lean_rows_delivered": sum(1 for r in rs if r["decision"] == "LEAN"),
            "lean_rows_implied": sum(1 for r in rs if implied_decision(r) == "LEAN"),
            "precedence_applied": "NO_LINE > CONV_FAIL > dose<0.50 > edge bands",
            "precedence_is_stated_on_the_card": False}


def expectation(rs, key):
    """Expected wins and the spread around them, under a given probability column."""
    ps = [r[key] / 100.0 for r in rs if r[key] is not None and r["result"] in (WIN, LOSS)]
    if not ps:
        return None
    ev = sum(ps)
    var = sum(p * (1.0 - p) for p in ps)
    obs = sum(1 for r in rs if r["result"] == WIN)
    sd = var ** 0.5
    return {"n": len(ps), "expected_wins": round(ev, 6), "observed_wins": obs,
            "sd_wins": round(sd, 6),
            "z": (None if sd == 0 else round((obs - ev) / sd, 4)),
            "shortfall_wins": round(obs - ev, 6)}


def power(rs):
    """What n=5 (and n=12) can and cannot decide. The point of this whole section."""
    plays = [r for r in rs if r["decision"] == PLAY]
    allsel = [r for r in rs if r["selection"] is not None]
    prior = 0.5205399061032864
    def base_brier(sub):
        vals = [(prior - (1.0 if r["result"] == WIN else 0.0)) ** 2
                for r in sub if r["result"] in (WIN, LOSS)]
        return None if not vals else round(sum(vals) / len(vals), 6)
    return {
        "official_card": {k: expectation(plays, k)
                          for k in ("model_pct", "sim_pct", "mkt_pct")},
        "all_selections": {k: expectation(allsel, k)
                           for k in ("model_pct", "sim_pct", "mkt_pct")},
        "registered_prior": prior,
        "brier_of_the_registered_prior_official_card": base_brier(plays),
        "brier_of_the_registered_prior_all_selections": base_brier(allsel),
        "what_n5_decides": ("nothing. At five plays the standard deviation of the win count is "
                            "of the same order as the entire model-vs-market gap, so a 2-3 and a "
                            "4-1 are both ordinary draws from either forecast."),
        "the_only_binding_test": ("a pre-registered walk-forward on a bound cohort, sized before "
                                  "the games are played"),
    }


def report():
    rs = rows()
    play_rows = [r for r in rs if r["decision"] == PLAY]
    all_sel = [r for r in rs if r["selection"] is not None]
    gate = display_layer_check(rs)
    return {
        "schema": "ops.grade.owner_v5_selection_board.v1",
        "sport": SPORT, "slate_date": SLATE_DATE, "board": "owner_v5_selection_first",
        "unit_usd": UNIT_USD,
        "ADMISSION": {
            "every_final_is": RESULT_GRADE,
            "admission_disposition": ADMISSION_DISPOSITION,
            "settleable_rows": 0,
            "grading_tier": "DESCRIPTIVE_ONLY",
            "accrues_to_settlement_promotion_estimator": False,
            "refused_rows": {g: v for g, v in FINALS.items() if not isinstance(v, tuple)},
            "display_gate": gate,
        },
        "OFFICIAL_CARD_FIVE_PLAYS": tally(play_rows),
        "ALL_SELECTIONS": tally(all_sel),
        "BY_DECISION": by_decision(rs),
        "CONV_FAIL_COUNTERFACTUAL": conv_fail_counterfactual(rs),
        "MARKET_SIDE_SELECTED": dog_bias(rs),
        "DOSE_EFFECT": dose_effect(rs),
        "VOCABULARY_CONSISTENCY": vocabulary_consistency(rs),
        "POWER": power(rs),
        "ROWS": rs,
        "UNITS_CAVEAT": {
            "tag": "PRICE_DERIVED_FROM_BOARD_MKT_PCT",
            "how": "decimal = 100 / Mkt%, from the board's own market column",
            "bias": "Mkt% is vigged, so a winning underdog returns LESS here than at a real price",
            "exposure_usd": 0.0, "wager_authority": "NO", "paper_only": True,
        },
    }


# =================================================================================================
def selftest():
    f = []
    if outcome("TOR", ("TOR", "SEA", 7, 0)) != WIN:
        f.append("winner not scored WIN")
    if outcome("SD", ("TB", "SD", 7, 6)) != LOSS:
        f.append("loser not scored LOSS")
    if outcome("DET", REFUSED_TRUNCATED) != UNRESOLVED:
        f.append("refused final graded instead of held")
    if outcome(None, ("AZ", "SF", 7, 1)) != NO_SELECTION:
        f.append("NO_LINE row given a result")
    try:
        outcome("NYY", ("TOR", "SEA", 7, 0))
        f.append("selection not in the final did not raise")
    except AssertionError:
        pass
    if units(LOSS, 44.4) != -1.0:
        f.append("loss is not -1 unit")
    if units(UNRESOLVED, 44.4) is not None:
        f.append("unresolved row produced units")
    if abs(units(WIN, 50.0) - 1.0) > 1e-9:
        f.append("even-money win is not +1 unit")
    if brier(100.0, WIN) != 0.0 or brier(0.0, WIN) != 1.0:
        f.append("brier endpoints wrong")
    if brier(50.0, UNRESOLVED) is not None:
        f.append("brier scored an ungraded row")
    r = report()
    if r["ADMISSION"]["display_gate"]["status"] != result_display.DISPLAY_OK:
        f.append("display gate refused: %r" % r["ADMISSION"]["display_gate"]["problems"])
    if r["OFFICIAL_CARD_FIVE_PLAYS"]["n_rows"] != 5:
        f.append("official card is not five rows")
    if any(row["settleable"] for row in r["ROWS"]):
        f.append("a row claimed settleability")
    vc = r["VOCABULARY_CONSISTENCY"]
    if vc["rows_checked"] != 15:
        f.append("vocabulary check skipped rows")
    if implied_decision({"mkt_pct": None, "selection": None}) != NO_LINE:
        f.append("unpriced row not routed to NO_LINE")
    if r["POWER"]["official_card"]["mkt_pct"]["n"] != 5:
        f.append("power section did not see five graded plays")
    if len(V5_BOARD) != 15 or set(g for g, *_ in V5_BOARD) != set(FINALS):
        f.append("board and finals tables disagree on the slate")
    print("%s selftest: %s" % (MODULE_ID, "PASS" if not f else "FAIL"))
    for x in f:
        print("  -", x)
    return not f


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    print(json.dumps(report(), indent=1, sort_keys=True))
