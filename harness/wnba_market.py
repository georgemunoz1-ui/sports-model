#!/usr/bin/env python3
"""WNBA MARKET-LAYER analysis — de-vig, no-vig consensus, hold, line-shopping.

WHY THIS EXISTS AND WHAT IT DELIBERATELY DOES NOT DO
----------------------------------------------------
sportsmodel is an MLB-only research system. There is NO WNBA model, NO WNBA team/player data, and
NO WNBA results on disk. Under R1 (never invent numbers) this module MUST NOT emit a model win
probability, an edge-vs-model, or a model EV for any WNBA game — there is nothing to compute them
from. It processes ONLY the observed multi-book prices the owner pasted:

  - de-vig each book's two-sided moneyline -> MARKET-IMPLIED probability per side (labeled as such)
  - no-vig CONSENSUS across books (mean of de-vigged probs) — the market's own fair estimate
  - per-book HOLD (overround)
  - best available price per side (line-shopping) and spread/total ranges

Every probability this emits is MARKET-IMPLIED (the books' own price, de-vigged), never a forecast
from this system. `model_status` is hard-wired to ABSENT and the selftest refuses any field that
would misrepresent a market number as a model output.

Firewall: data/wnba/** and this module are isolated from the MLB engine, model_registry,
forecast_registry, and healthcheck. No WNBA number can reach the MLB gate, forecasts, or ledgers.

Usage:
  python3 harness/wnba_market.py                      # analyze the frozen 2026-08-08 board
  python3 harness/wnba_market.py --selftest           # de-vig arithmetic + no-invented-numbers guard
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

BOARD = "data/wnba/odds/2026-08-08_board.json"
OUT = "data/wnba/analysis/2026-08-08_market.json"

MODEL_STATUS = "ABSENT (MLB-only system; no WNBA model/data — market layer only, R1)"


def american_to_implied(a):
    """Raw vig-inclusive implied probability of an American price."""
    if a is None:
        return None
    return 100.0 / (a + 100.0) if a > 0 else (-a) / ((-a) + 100.0)


def devig_two_sided(ml_a, ml_b):
    """Return (p_a, p_b, hold) from a two-sided moneyline, or None if either side missing."""
    ia, ib = american_to_implied(ml_a), american_to_implied(ml_b)
    if ia is None or ib is None:
        return None
    s = ia + ib
    return ia / s, ib / s, s - 1.0


def best_price(prices):
    """Best (highest-paying) American price for a bettor from a list, ignoring None."""
    ps = [p for p in prices if p is not None]
    if not ps:
        return None
    # higher payout: +200 beats +150 beats -110 beats -200. Rank by decimal payout.
    def dec(a):
        return 1 + (a / 100 if a > 0 else 100 / (-a))
    return max(ps, key=dec)


def analyze_game(g):
    t1, t2 = g["teams"]
    books = g["books"]
    per_book = {}
    cons_p1, cons_p2 = [], []
    for bk, ln in books.items():
        ml1, ml2 = ln["t1"]["ml"], ln["t2"]["ml"]
        dv = devig_two_sided(ml1, ml2)
        rec = {"ml": {t1: ml1, t2: ml2}, "spread": {t1: ln["t1"]["spread"], t2: ln["t2"]["spread"]},
               "total": ln["total"]}
        if dv is not None:
            p1, p2, hold = dv
            rec["market_implied_prob"] = {t1: round(p1, 4), t2: round(p2, 4)}
            rec["hold"] = round(hold, 4)
            cons_p1.append(p1)
            cons_p2.append(p2)
        else:
            rec["market_implied_prob"] = None
            rec["hold"] = None
            rec["ml_note"] = "moneyline not two-sided on this book -> no de-vig"
        per_book[bk] = rec
    consensus = None
    if cons_p1:
        consensus = {
            "n_books": len(cons_p1),
            "no_vig_consensus_prob": {t1: round(sum(cons_p1) / len(cons_p1), 4),
                                      t2: round(sum(cons_p2) / len(cons_p2), 4)},
            "label": "MARKET-IMPLIED (mean of de-vigged book prices) — NOT a model forecast",
        }
    best = {
        t1: best_price([b["t1"]["ml"] for b in books.values()]),
        t2: best_price([b["t2"]["ml"] for b in books.values()]),
    }
    spreads = sorted({b["t1"]["spread"] for b in books.values()})
    totals = sorted({b["total"] for b in books.values()})
    return {
        "teams": [t1, t2], "tip_et": g["tip_et"], "date": g["date"], "favorite": g["favorite"],
        "home_away": g.get("home_away"), "note": g.get("note"),
        "per_book": per_book,
        "consensus_market_implied": consensus,
        "best_price": best,
        "spread_range_t1": [spreads[0], spreads[-1]],
        "total_range": [totals[0], totals[-1]],
        "model_prob": None, "model_edge": None, "model_ev": None,
        "model_note": "NULL BY DESIGN — no WNBA model exists in this system (R1).",
    }


def analyze(board_path=BOARD, out_path=OUT):
    b = json.load(open(board_path))
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    games = [analyze_game(g) for g in b["games"]]
    # record_id follows the BOARD, never a hard-coded date — a stale literal here would stamp one
    # board's analysis with another board's identity, which is exactly the kind of silent
    # mislabelling the provenance rules exist to prevent.
    board_tag = b["record_id"].replace("WNBA-BOARD-", "")
    out = {
        "record_id": f"WNBA-MARKET-ANALYSIS-{board_tag}",
        "sport": "WNBA",
        "built_utc": now,
        "model_status": MODEL_STATUS,
        "board_source": {"path": board_path, "record_id": b["record_id"]},
        "what_this_is": "MARKET LAYER ONLY: de-vig, no-vig consensus, hold, best-price line-shopping "
                        "from the observed 4-book prices. Every probability is MARKET-IMPLIED.",
        "what_this_is_not": "NOT a forecast. No model win probability, edge, or EV — this system has "
                            "no WNBA model or data. No +EV claim can be made without an independent "
                            "estimate, which does not exist here.",
        "to_build_a_real_model_you_would_need": [
            "WNBA game results history (scores, dates, home/away) — none on disk",
            "team ratings / four-factor or possession data, and injuries/rest",
            "player availability + minutes (WNBA lines move hard on star rest)",
            "a fit + a rolling out-of-sample calibration, graded like the MLB forecast registry",
        ],
        "games": games,
        "governance": {"firewall": "data/wnba/** isolated from MLB engine/registries/healthcheck",
                       "gate_impact": "NONE", "ledger_impact": "NONE ($0, paper)"},
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    json.dump(out, open(out_path, "w"), indent=1)
    _print_human(out)
    return 0


def _fmt(a):
    return "  —  " if a is None else (f"+{a}" if a > 0 else f"{a}")


def _print_human(out):
    print(f"WNBA MARKET LAYER — model_status: {out['model_status']}")
    for g in out["games"]:
        t1, t2 = g["teams"]
        print(f"\n{t1}  vs  {t2}   ({g['date']} {g['tip_et']} ET)   fav: {g['favorite']}")
        if g.get("note"):
            print(f"   note: {g['note']}")
        print(f"   {'book':<9}{t1[:14]:>16} {t2[:14]:>16}   hold")
        for bk, r in g["per_book"].items():
            mp = r.get("market_implied_prob")
            p1 = f"{mp[t1]*100:4.1f}%" if mp else "  — "
            p2 = f"{mp[t2]*100:4.1f}%" if mp else "  — "
            ml1, ml2 = _fmt(r["ml"][t1]), _fmt(r["ml"][t2])
            hold = f"{r['hold']*100:4.1f}%" if r["hold"] is not None else "  — "
            print(f"   {bk:<9}{ml1:>7} {p1:>8} {ml2:>7} {p2:>8}   {hold}")
        c = g["consensus_market_implied"]
        if c:
            cp = c["no_vig_consensus_prob"]
            print(f"   CONSENSUS (no-vig, market-implied): {t1} {cp[t1]*100:.1f}%  |  {t2} {cp[t2]*100:.1f}%")
        print(f"   best price: {t1} {_fmt(g['best_price'][t1])}  {t2} {_fmt(g['best_price'][t2])}  "
              f"| spread(t1) {g['spread_range_t1']}  total {g['total_range']}")
    print("\nNo model probabilities, edges, or EV are produced — none exist for WNBA in this system.")


def selftest():
    fails = []
    # de-vig arithmetic on a known symmetric case: -110/-110 -> 50/50, hold ~4.5%
    p1, p2, hold = devig_two_sided(-110, -110)
    if not (abs(p1 - 0.5) < 1e-9 and abs(p2 - 0.5) < 1e-9):
        fails.append("symmetric -110/-110 did not de-vig to 50/50")
    if not abs(hold - (2 * (110 / 210) - 1)) < 1e-9:
        fails.append("hold on -110/-110 wrong")
    # known asymmetric case: +155 / -180
    p1, p2, hold = devig_two_sided(155, -180)
    ia, ib = 100 / 255, 180 / 280
    if not abs(p1 - ia / (ia + ib)) < 1e-9:
        fails.append("asymmetric de-vig wrong")
    # probs sum to 1
    if not abs(p1 + p2 - 1.0) < 1e-9:
        fails.append("de-vig probs do not sum to 1")
    # missing side -> None (never fabricate)
    if devig_two_sided(None, -110) is not None:
        fails.append("missing ML should yield None, not a number")
    # best price picks the higher payout
    if best_price([-180, -175, -190, -180]) != -175:
        fails.append("best_price favorite side wrong")
    if best_price([155, 165, 160, 152]) != 165:
        fails.append("best_price dog side wrong")
    # STRUCTURAL no-invented-numbers guard: analysis must never carry a non-null model field
    if os.path.exists(BOARD):
        rep = analyze_game(json.load(open(BOARD))["games"][0])
        if rep["model_prob"] is not None or rep["model_edge"] is not None or rep["model_ev"] is not None:
            fails.append("a model_* field is non-null — invented WNBA number leaked in")
        # every emitted probability must be tagged market-implied, never labeled a forecast
        c = rep["consensus_market_implied"]
        if c and "MARKET-IMPLIED" not in c["label"]:
            fails.append("consensus prob not labeled MARKET-IMPLIED")
    if fails:
        print("wnba_market selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("wnba_market selftest: PASS (de-vig arithmetic, sum-to-1, None-on-missing, best-price, "
          "and the no-invented-model-number structural guard)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--board", default=BOARD, help="path to a frozen owner board JSON")
    ap.add_argument("--out", default=None, help="analysis output path (default: derived from --board)")
    args = ap.parse_args()
    if args.selftest:
        raise SystemExit(selftest())
    out_path = args.out
    if out_path is None:
        out_path = (OUT if args.board == BOARD
                    else args.board.replace("/odds/", "/analysis/").replace("_board.json", "_market.json"))
    raise SystemExit(analyze(args.board, out_path))
