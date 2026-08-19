#!/usr/bin/env python3
"""Unified card: one immutable row per game, three estimands, a trust ladder instead of raw gaps.

CONTRACT: docs/experiments/2026-08-19_CARD_CONTRACT.json (owner specification, frozen). The 8/18
lesson it encodes: "model closer to 50% than the market" is not automatically sharp — the largest
dog gaps were compression artifacts, went 0-3, and raw-gap sorting put the least trustworthy rows
first. Claimed edges >=5pp are 0-6 lifetime, so QUALIFIED_PAPER_EDGE is EMPTY BY CONSTRUCTION until
an edge class earns forward validation; this module prints that emptiness rather than relaxing it.

Row store: data/cards_unified/{date}_{sport}.jsonl — the pregame line is immutable; settlement
APPENDS a type=settlement line with the same row_id. No separate results table is ever recreated.

Usage: python3 harness/unified_card.py --selftest | --wnba-date YYYY-MM-DD
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

COMPRESSION_PP = 0.05
QUALIFIED_MIN_CONS_EDGE_PP = 2.0
TRUST_ORDER = ["QUALIFIED_PAPER_EDGE", "PRICE_SENSITIVE", "COMPRESSION_CONFLICT",
               "PERSONNEL_INCOMPLETE", "NO_VALUE", "BLOCKED"]


def imp(a):
    a = float(a)
    return (-a) / ((-a) + 100) if a < 0 else 100 / (a + 100)


def dec(a):
    a = float(a)
    return 1 + (100 / -a) if a < 0 else 1 + a / 100


def compression_conflict(p_model, p_market):
    """Frozen gate: market confidence exceeds model confidence by >= 5pp (confidence = |p-.5|)."""
    if p_market is None:
        return False
    return (abs(p_market - .5) - abs(p_model - .5)) >= COMPRESSION_PP


def price_screen(p_model, price, sigma, uncertainty_basis):
    """Uncertainty-adjusted moneyline screen for ONE side at ONE price. Returns the display block."""
    be = imp(price)
    raw = (p_model - be) * 100
    if sigma is None:
        cons_p, cons_edge = None, None
        ev_cons = None
    else:
        cons_p = max(0.0, p_model - 1.96 * sigma)
        cons_edge = (cons_p - be) * 100
        ev_cons = cons_p * (dec(price) - 1) - (1 - cons_p)
    return {"price": price, "break_even": round(be, 4), "raw_edge_pp": round(raw, 2),
            "uncertainty_sigma": (round(sigma, 5) if sigma is not None else None),
            "uncertainty_basis": uncertainty_basis,
            "conservative_p": (round(cons_p, 4) if cons_p is not None else None),
            "conservative_edge_pp": (round(cons_edge, 2) if cons_edge is not None else None),
            "ev_at_conservative_p": (round(ev_cons, 4) if ev_cons is not None else None)}


def classify(row):
    """Trust status for one game row. Precedence (frozen): BLOCKED > PERSONNEL_INCOMPLETE >
    COMPRESSION_CONFLICT > PRICE_SENSITIVE > NO_VALUE. QUALIFIED additionally requires a
    forward-validated edge class, which none is — enforced by the validated_edge_class flag that
    nothing currently sets true."""
    if row.get("blocked_reason"):
        return "BLOCKED"
    if row.get("personnel_incomplete"):
        return "PERSONNEL_INCOMPLETE"
    if row.get("compression_conflict"):
        return "COMPRESSION_CONFLICT"
    edges = [s.get("conservative_edge_pp") for s in row.get("price_sides", []) if s]
    raw = [s.get("raw_edge_pp") for s in row.get("price_sides", []) if s]
    have_cons = [e for e in edges if e is not None]
    if have_cons:
        best = max(have_cons)
        if best >= QUALIFIED_MIN_CONS_EDGE_PP and row.get("validated_edge_class") is True:
            return "QUALIFIED_PAPER_EDGE"
        if best > 0:
            return "PRICE_SENSITIVE"
        return "NO_VALUE"
    # uncertainty not quantified: positive RAW edge caps at PRICE_SENSITIVE
    if any(r is not None and r > 0 for r in raw):
        return "PRICE_SENSITIVE"
    return "NO_VALUE"


def sort_rows(rows):
    return sorted(rows, key=lambda r: (TRUST_ORDER.index(r["trust_status"]),
                                       -(max([s.get("conservative_edge_pp") or s.get("raw_edge_pp") or -99
                                              for s in r.get("price_sides", [{}])] or [-99]))))


def totals_report(errors):
    """The banned-mean rule: MAE, MEDIAN, signed bias and LARGEST miss, always together."""
    import statistics as st
    a = [abs(e) for e in errors]
    return {"n": len(errors), "mae": round(sum(a) / len(a), 2), "median_ae": round(st.median(a), 2),
            "signed_bias": round(sum(errors) / len(errors), 2),
            "largest_miss": round(max(errors, key=abs), 2)}


def build_wnba(date):
    """Unified rows for a WNBA slate from the already-registered card + selections + lines."""
    card = json.load(open(f"data/wnba/forecasts/{date}_card.json"))
    regs = {json.loads(l)["forecast_id"]: json.loads(l)
            for l in open("data/wnba/forecasts/registrations.jsonl") if l.strip()}
    sels = {}
    if os.path.exists("data/wnba/forecasts/ats_selections.jsonl"):
        for l in open("data/wnba/forecasts/ats_selections.jsonl"):
            s = json.loads(l)
            sels[s["game_ref"]] = s
    # best available ML per side from the multibook capture, if present (screening prices)
    mb = {}
    p = f"data/wnba/evidence_{date}_multibook_prices.json"
    if os.path.exists(p):
        # the price screenshots abbreviate Washington as WSH while the registration crosswalk uses
        # WAS; resolve either spelling so one team never silently loses its price row
        ALIAS = {"WAS": ["WAS", "WSH"], "WSH": ["WSH", "WAS"], "GSV": ["GSV", "GS"], "GS": ["GS", "GSV"]}
        def _get(b, t):
            for k in ALIAS.get(t, [t]):
                if k in b:
                    return b[k]
            return None
        for g in json.load(open(p))["games"]:
            a, h = g["game"].split("@")
            # "open" is a historical reference, not an executable quote — never a best price
            aps = [(_get(b, a), bk) for bk, b in g["moneyline_by_book"].items()
                   if bk != "open" and _get(b, a) is not None]
            hps = [(_get(b, h), bk) for bk, b in g["moneyline_by_book"].items()
                   if bk != "open" and _get(b, h) is not None]
            best_a = max(aps, key=lambda x: dec(x[0]))
            best_h = max(hps, key=lambda x: dec(x[0]))
            # same-book de-vig for the market probability: use each book's own pair, take the range mid
            pairs = [(_get(b, a), _get(b, h)) for bk, b in g["moneyline_by_book"].items()
                     if _get(b, a) is not None and _get(b, h) is not None and bk != "open"]
            phs = [imp(x[1]) / (imp(x[0]) + imp(x[1])) for x in pairs]
            mb[g["game"]] = {"best_away": best_a, "best_home": best_h,
                             "p_home_devig_range": [round(min(phs), 4), round(max(phs), 4)],
                             "p_home_devig_mid": round(sum(phs) / len(phs), 4)}
    rows = []
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in card["rows"]:
        g = f'{r["away"]}@{r["home"]}'
        fid = f"WNBA-V1-{date.replace('-','')}-{g}"
        reg = regs[fid]
        sel = sels.get(f"{g}:{date}")
        m = mb.get(g, {})
        p_home = r["p_home"]
        p_mkt = m.get("p_home_devig_mid")
        sides = []
        for team, pmod, best in ((r["home"], p_home, m.get("best_home")),
                                 (r["away"], 1 - p_home, m.get("best_away"))):
            if best:
                sides.append({"team": team, "book": best[1],
                              **price_screen(pmod, best[0], None, "NOT_QUANTIFIED — WNBA shadow "
                              "logistic carries no frozen per-game uncertainty; positive raw edge "
                              "caps at PRICE_SENSITIVE by contract")})
        conf = compression_conflict(p_home, p_mkt)
        row = {"type": "pregame", "row_id": f"UC-{date}-WNBA-{g}", "sport": "wnba", "date": date,
               "game": g, "generated_at_utc": now,
               "forecast_id": fid, "winner_selection_id": fid,
               "ats_selection_id": (sel or {}).get("ats_selection_id"),
               "total_selection_id": None,
               "total_selection_reason_null": "no total selection rule is preregistered; TOTAL is DIRECTIONAL_DIAGNOSTIC only",
               "registered_lines": reg.get("lines_at_registration"),
               "WINNER": {"p_home": p_home, "predicted_winner": r["home"] if p_home >= .5 else r["away"],
                          "market_p_home_devig": p_mkt, "market_range": m.get("p_home_devig_range")},
               "PRICE": {"sides": sides, "note": "screening only; wager authority NO"},
               "ATS": ({"selection": sel["selection"], "home_cover_delta": sel["home_cover_delta"],
                        "rule_id": sel["rule_id"], "class": "DIRECTIONAL_DIAGNOSTIC",
                        "reason": "no cover/push/fail distribution exists for the WNBA shadow"}
                       if sel else {"selection": "NO_SELECTION"}),
               "TOTAL": {"model_total": r["total"], "line": (reg.get("lines_at_registration") or {}).get("total"),
                         "class": "DIRECTIONAL_DIAGNOSTIC"},
               "personnel": {"starter_state": "N/A_WNBA", "lineup_state": "NONE_AVAILABLE",
                             "feature_age_days": card.get("staleness_days"),
                             "late_change_flag": False},
               "price_sides": sides,
               "compression_conflict": conf,
               "compression_note": ("COMPRESSION_CONFLICT — AUDIT_REQUIRED" if conf else None),
               "personnel_incomplete": False, "validated_edge_class": False,
               "flags": reg.get("dq_flags", [])}
        row["trust_status"] = classify(row)
        rows.append(row)
    rows = sort_rows(rows)
    os.makedirs("data/cards_unified", exist_ok=True)
    out = f"data/cards_unified/{date}_wnba.jsonl"
    if os.path.exists(out):
        raise SystemExit(f"REFUSED: {out} exists — pregame rows are immutable; settlement appends")
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return out, rows


def selftest():
    fails = []
    # contract fixtures: the three 8/18 cases MUST flag compression conflict
    for name, pm, pk in (("WSH@TEX", .464, .591), ("CWS@CHC", .482, .603), ("TOR-away", .405, .208)):
        if not compression_conflict(pm, pk):
            fails.append(f"{name}: owner fixture NOT flagged as compression conflict")
    # a model MORE confident than the market must not flag
    if compression_conflict(.567, .543):
        fails.append("model-more-confident case wrongly flagged")
    # near-tie: 4.9pp gap must NOT flag (threshold is >= 5pp)
    if compression_conflict(.50, .549):
        fails.append("sub-threshold gap flagged")
    if not compression_conflict(.50, .551):
        fails.append("5.1pp gap not flagged")
    # screen arithmetic: at a fair price the conservative edge must be NEGATIVE (LCB < p)
    s = price_screen(.60, -150, 0.01, "test")
    if not (s["raw_edge_pp"] == 0.0 and s["conservative_edge_pp"] < 0):
        fails.append(f"fair-price screen wrong: {s}")
    # classification precedence: compression conflict subordinates a positive edge
    row = {"price_sides": [{"raw_edge_pp": 19.6, "conservative_edge_pp": 19.0}],
           "compression_conflict": True, "personnel_incomplete": False, "validated_edge_class": False}
    if classify(row) != "COMPRESSION_CONFLICT":
        fails.append("compression conflict did not subordinate a large edge")
    # QUALIFIED is unreachable while validated_edge_class is False
    row2 = {"price_sides": [{"raw_edge_pp": 6, "conservative_edge_pp": 5}],
            "compression_conflict": False, "personnel_incomplete": False, "validated_edge_class": False}
    if classify(row2) != "PRICE_SENSITIVE":
        fails.append("unvalidated edge class reached QUALIFIED or fell through")
    row2["validated_edge_class"] = True
    if classify(row2) != "QUALIFIED_PAPER_EDGE":
        fails.append("validated large edge not QUALIFIED")
    # personnel subordinates edge
    row3 = dict(row2, personnel_incomplete=True)
    if classify(row3) != "PERSONNEL_INCOMPLETE":
        fails.append("personnel incompleteness did not subordinate edge")
    # NOT_QUANTIFIED uncertainty with positive raw edge caps at PRICE_SENSITIVE
    row4 = {"price_sides": [{"raw_edge_pp": 1.2, "conservative_edge_pp": None}],
            "compression_conflict": False, "personnel_incomplete": False, "validated_edge_class": False}
    if classify(row4) != "PRICE_SENSITIVE":
        fails.append("NOT_QUANTIFIED positive raw edge misclassified")
    # sort order: ladder, not raw gap
    rows = [{"trust_status": "COMPRESSION_CONFLICT", "price_sides": [{"raw_edge_pp": 20}]},
            {"trust_status": "PRICE_SENSITIVE", "price_sides": [{"raw_edge_pp": 1, "conservative_edge_pp": 1}]}]
    if sort_rows(rows)[0]["trust_status"] != "PRICE_SENSITIVE":
        fails.append("sorting still ranks the big raw gap first")
    # totals report: the mean must never travel alone, and the largest miss must survive cancellation
    t = totals_report([15.8, -20.3, 4.2, 0.3])
    if t["signed_bias"] == t["mae"] or t["largest_miss"] != -20.3 or "median_ae" not in t:
        fails.append(f"totals report defective: {t}")
    if fails:
        print("unified_card selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("unified_card selftest: PASS (all three owner compression fixtures flag; threshold exact at "
          "5pp; conflict/personnel subordinate edges; QUALIFIED unreachable without a validated class; "
          "ladder sorting beats raw-gap sorting; totals report carries median and largest miss)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--wnba-date")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    if a.wnba_date:
        out, rows = build_wnba(a.wnba_date)
        print(f"wrote {out} ({len(rows)} immutable pregame rows)")
        for r in rows:
            w, pr, ats = r["WINNER"], r["PRICE"], r["ATS"]
            print(f'\n[{r["trust_status"]}] {r["game"]}  row_id {r["row_id"]}')
            print(f'  WINNER  {w["predicted_winner"]} p_home {w["p_home"]:.4f} vs market {w["market_p_home_devig"]}')
            for s in pr["sides"]:
                print(f'  PRICE   {s["team"]:<4} @{s["price"]:+} ({s["book"]}) raw {s["raw_edge_pp"]:+.2f}pp '
                      f'cons {s["conservative_edge_pp"]} ({s["uncertainty_basis"][:40]}...)')
            print(f'  ATS     {ats.get("selection")} [{ats.get("class","-")}]')
            print(f'  TOTAL   {r["TOTAL"]["model_total"]} vs {r["TOTAL"]["line"]} [{r["TOTAL"]["class"]}]')
            if r["compression_note"]:
                print(f'  !! {r["compression_note"]}')
