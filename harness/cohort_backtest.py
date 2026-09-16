#!/usr/bin/env python3
"""Per-cohort prospective performance. Cohorts are NEVER merged into one statistic.

WHY: this repository runs four structurally different prediction tracks — an MLB simulator (V13),
an externally-delivered MLB shadow artifact (V19, message-attested), a WNBA ridge model, and an NFL
MARKET BENCHMARK that contains no model at all. Averaging them would manufacture a number that
describes nothing. Each cohort is reported alone, with its own n, exclusions and evidence tier.

Evidence tiering is part of cohort identity, not a footnote: grades resting on tier-3 observations
(all appended BEFORE the owner's 2026-08-16 tier-1-only ruling) are reported as their own cohorts and
are never pooled with tier-1 grades.

Usage: python3 harness/cohort_backtest.py [--json]
"""
from __future__ import annotations

MODULE_ID = "cohort_backtest"
import csv, json, math, os, sys, collections

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)


def _jsonl(p):
    return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []


def _results():
    return list(csv.DictReader(open("data/backfill/mlb/2026/results.csv")))


def _stats(rows, name, evidence_tier, notes, exclusions=(), unresolved=()):
    """rows: list of dicts with p_home, home_win, and optional margin/total pred+actual."""
    n = len(rows)
    if not n:
        return {"cohort": name, "n": 0, "evidence_tier": evidence_tier, "notes": notes,
                "exclusions": list(exclusions), "unresolved": list(unresolved)}
    sides = sum(1 for r in rows if (r["home_win"] == 1) == (r["p_home"] >= 0.5))
    brier = sum((r["home_win"] - r["p_home"]) ** 2 for r in rows) / n
    # log loss is undefined at p in {0,1}; report only when every p is interior
    interior = all(0.0 < r["p_home"] < 1.0 for r in rows)
    ll = (-sum(r["home_win"] * math.log(r["p_home"]) + (1 - r["home_win"]) * math.log(1 - r["p_home"])
               for r in rows) / n) if interior else None
    mp = [r for r in rows if r.get("margin_pred") is not None and r.get("margin_actual") is not None]
    tp = [r for r in rows if r.get("total_pred") is not None and r.get("total_actual") is not None]
    # calibration: favourite-side probability buckets vs realised favourite win rate
    buckets = collections.OrderedDict()
    for lo, hi in ((0.50, 0.55), (0.55, 0.60), (0.60, 0.70), (0.70, 1.01)):
        sel = [r for r in rows if lo <= max(r["p_home"], 1 - r["p_home"]) < hi]
        if sel:
            hit = sum(1 for r in sel if (r["home_win"] == 1) == (r["p_home"] >= 0.5))
            buckets[f"{lo:.2f}-{hi:.2f}"] = {
                "n": len(sel), "mean_pred": round(sum(max(r["p_home"], 1 - r["p_home"]) for r in sel) / len(sel), 4),
                "realised": round(hit / len(sel), 4)}
    favs = [max(r["p_home"], 1 - r["p_home"]) for r in rows]
    mean_fav = sum(favs) / n
    sd_fav = math.sqrt(sum((f - mean_fav) ** 2 for f in favs) / (n - 1)) if n > 1 else 0.0
    return {
        "cohort": name, "n": n, "evidence_tier": evidence_tier,
        "side_record": f"{sides}-{n - sides}", "accuracy": round(sides / n, 4),
        "mean_brier": round(brier, 4),
        "log_loss": (round(ll, 4) if ll is not None else None),
        "margin_mae": (round(sum(abs(r["margin_pred"] - r["margin_actual"]) for r in mp) / len(mp), 4) if mp else None),
        "margin_n": len(mp),
        "total_mae": (round(sum(abs(r["total_pred"] - r["total_actual"]) for r in tp) / len(tp), 4) if tp else None),
        "total_n": len(tp),
        "spread_diagnostic": {"mean_favourite_prob": round(mean_fav, 4), "sd_pp": round(sd_fav * 100, 2),
                              "n_ge_58pct": sum(1 for f in favs if f >= 0.58)},
        "calibration_buckets": buckets,
        "exclusions": list(exclusions), "unresolved": list(unresolved), "notes": notes,
    }


def cohorts():
    F = {f["forecast_id"]: f for f in _jsonl("data/mlb/forecasts/forecasts.jsonl")}
    G_all = _jsonl("data/mlb/forecasts/grades.jsonl")
    # A grade named by another grade's supersedes_grade_id is HISTORY, not current state. Iterating
    # the raw list double-counted the two 7/29 R6 supersessions, whose labels are contradictory
    # (home_win 0 then 1) — a latent double-grade that only stayed harmless because no active cohort
    # prefix reached them.
    _superseded = {g["supersedes_grade_id"] for g in G_all if g.get("supersedes_grade_id")}
    G = [g for g in G_all if g.get("grade_id") not in _superseded]
    res = {(r["date"], r["away"], r["home"]): r for r in _results()}
    out = []

    def mlb_rows(prefix, tier_filter):
        rows = []
        for g in G:
            fid = g["forecast_id"]
            if not fid.startswith(prefix):
                continue
            is_t3 = "tier3" in g.get("source", "")
            if tier_filter == 1 and is_t3:
                continue
            if tier_filter == 3 and not is_t3:
                continue
            f = F.get(fid)
            p = (f or {}).get("payload") or {}
            # PAYLOAD SCHEMA DRIFT (found 2026-08-16): 8/13 registrations named the probability
            # `v13_home_wp`; 8/14 named it `p_home`. Reading only one key silently produced n=0
            # cohorts — i.e. a missing-data bug that looked like "no forecasts existed". Accept both,
            # and never treat an unreadable payload as an empty cohort.
            p_home = p.get("p_home", p.get("v13_home_wp"))
            if p_home is None:
                continue
            t = p["teams"]
            r = res.get((f["slate_date"], t["away"], t["home"]))
            row = {"game": f'{t["away"]}@{t["home"]}', "p_home": p_home, "home_win": int(g["home_win"]),
                   "total_pred": p.get("proj_total")}
            # BOTH predicates: 10 rows are source_tier==1 but result_status==PROVISIONAL (winner
            # proven by tier-1 standings arithmetic, score not yet officially captured). Enforcing
            # tier alone would admit them as finals.
            if (r and r.get("total") not in ("", None) and r.get("source_tier") == "1"
                    and r.get("result_status") == "FINAL"):
                row["total_actual"] = float(r["total"])
            rows.append(row)
        return rows

    out.append(_stats(
        mlb_rows("P4-20260814-", 1), "MLB V13 prospective — 2026-08-14", "TIER_1",
        "ml.v13_1.hfa1005.card.s722n30000, frozen; registered pre-pitch; graded on the tier-1 owner "
        "finals board. This is the only fully tier-1 MLB cohort in the repository.",
        exclusions=["none"], unresolved=["none"]))

    t3_v1 = mlb_rows("P4-20260813-", 3)
    out.append(_stats(
        t3_v1, "MLB V13 prospective — 2026-08-13 v1 (PRE-RULING TIER-3 EXCEPTION)", "TIER_3_PRE_RULING",
        "Graded 2026-08-15 on multi-source tier-3 finals, BEFORE the owner's tier-1-only ruling. The "
        "grade chain is append-only so these stand, but they are a separate cohort and must never be "
        "pooled with the tier-1 cohort above.",
        exclusions=["not poolable with tier-1"], unresolved=["none"]))

    t3_v2 = mlb_rows("P4-20260813v2-", 3)
    v2_all = [g for g in G if g["forecast_id"].startswith("P4-20260813v2-")]
    out.append(_stats(
        t3_v2, "MLB V13 v2 evening cohort — 2026-08-13 (PRE-RULING TIER-3 EXCEPTION)", "TIER_3_PRE_RULING",
        f"{len(v2_all)} graded rows total; MIL@LAD's grade rests on a TIER-1 series-state winner proof "
        "rather than a tier-3 score and is therefore excluded from this tier-3 statistic and named below.",
        exclusions=["P4-20260813v2-MIL@LAD (winner proven tier-1; different evidence tier)"],
        unresolved=["none"]))

    # V19: external, message-attested frozen table; graded against the same tier-1 finals
    v19p = "data/mlb/forecasts/2026-08-14_v19_external_attested.json"
    if os.path.exists(v19p):
        d = json.load(open(v19p))
        rows = []
        for r in d["rows_verbatim"]:
            away, home = r["g"].split("@")
            key = ("2026-08-14", "AZ" if away == "ARI" else away, home)
            rr = res.get(key)
            if not rr or rr.get("source_tier") != "1" or rr.get("result_status") != "FINAL":
                continue
            p_home = r["p"] if r["pick"] == home else round(1 - r["p"], 3)
            rows.append({"game": r["g"], "p_home": p_home, "home_win": int(rr["home_win"])})
        out.append(_stats(
            rows, "MLB V19 external shadow — 2026-08-14 (MESSAGE-ATTESTED)", "TIER_1_FINAL / ATTESTED_FORECAST",
            "V18's frozen artifact run prospectively; NO_PROMOTE (paired CIs crossed zero). The FINALS are "
            "tier-1; the FORECAST payload is a message transcription, not canonical bytes — control "
            "C-V19-SUPERSESSION governs if canonical bytes later differ.",
            exclusions=["none"], unresolved=["none"]))

    # WNBA — split by evidence tier, never pooled
    W = _jsonl("data/wnba/forecasts/grades.jsonl")
    for tier, label, note in (
        (1, "WNBA v1.0 shadow — TIER-1 graded", "wnba.rs.ff7_logit_ridge.v1_0.shadow; registered pre-tip; "
            "graded on tier-1 owner finals boards."),
        (3, "WNBA v1.0 shadow — TIER-3 graded (PRE-RULING EXCEPTION)", "2026-08-13 night, converted on "
            "corroborated multi-source finals before the tier-1-only ruling; separate cohort."),
    ):
        sel = [g for g in W if g.get("source_tier") == tier]
        reg = {r["forecast_id"]: r for r in _jsonl("data/wnba/forecasts/registrations.jsonl")}
        rows = []
        for g in sel:
            r = reg.get(g["forecast_id"])
            if not r:
                continue
            rows.append({"game": g["forecast_id"].split("-")[-1], "p_home": r["payload"]["p_home"],
                         "home_win": int(g["home_win"]), "margin_pred": g.get("margin_pred"),
                         "margin_actual": g.get("margin_actual"), "total_pred": g.get("total_pred"),
                         "total_actual": g.get("total_actual")})
        out.append(_stats(rows, label, f"TIER_{tier}" + ("_PRE_RULING" if tier == 3 else ""), note,
                          exclusions=["none"], unresolved=["none"]))

    # NFL market benchmark — no model; binary side record only, and NOT a Brier cohort
    N = _jsonl("data/nfl/results_ledger.jsonl")
    cur = {}
    for r in N:
        cur[(r["date"], r["game"])] = r if (r["date"], r["game"]) not in cur or \
            r.get("revision", 1) > cur[(r["date"], r["game"])].get("revision", 1) else cur[(r["date"], r["game"])]
    t1 = [r for r in cur.values() if r.get("source_tier") == 1 and r["grade_state"].startswith("GRADED_")]
    t3 = [r for r in cur.values() if r.get("source_tier") == 3 and r["grade_state"].startswith("GRADED_PROVISIONAL")]
    excl = [r for r in cur.values() if r["grade_state"] == "TIE_EXCLUDED"]
    pend = [f'{r["date"]} {r["game"]} ({r["grade_state"]})' for r in cur.values()
            if r["grade_state"] in ("PENDING_FINAL", "AWAITING_FROZEN_PAYLOAD_AND_TIER1_FINAL")]
    for label, sel, tier in (("NFL market benchmark — TIER-1 graded", t1, "TIER_1"),
                             ("NFL market benchmark — TIER-3 provisional", t3, "TIER_3_PROVISIONAL")):
        w = sum(1 for r in sel if r["grade_state"].endswith("CORRECT"))
        out.append({
            "cohort": label, "n": len(sel), "evidence_tier": tier,
            "side_record": f"{w}-{len(sel) - w}",
            "accuracy": (round(w / len(sel), 4) if sel else None),
            "mean_brier": None, "log_loss": None, "margin_mae": None, "total_mae": None,
            "calibration_buckets": {},
            "exclusions": [f'{r["date"]} {r["game"]} TIE_EXCLUDED' for r in excl] if tier == "TIER_1" else [],
            "unresolved": pend if tier == "TIER_1" else [],
            "notes": "NO MODEL EXISTS. This is the market's declared favourite graded against finals — "
                     "market-benchmark evidence, never NFL model performance. Brier/log-loss are NULL "
                     "BY DESIGN because no probability was ever emitted (R1). n is far too small for any "
                     "signal claim in either direction (owner control OWNER-CONTROLS-2026-08-15).",
        })
    return out


if __name__ == "__main__":
    cs = cohorts()
    os.makedirs("data/audit", exist_ok=True)
    json.dump(cs, open("data/audit/cohort_backtest.json", "w"), indent=1)
    if "--json" in sys.argv:
        print(json.dumps(cs, indent=1))
    else:
        for c in cs:
            print(f'\n=== {c["cohort"]}  [{c["evidence_tier"]}]  n={c["n"]}')
            if not c["n"]:
                print("  (no rows)")
            else:
                print(f'  sides {c.get("side_record")}  acc {c.get("accuracy")}  '
                      f'Brier {c.get("mean_brier")}  logloss {c.get("log_loss")}')
                if c.get("margin_mae") is not None:
                    print(f'  margin MAE {c["margin_mae"]} (n={c.get("margin_n")})')
                if c.get("total_mae") is not None:
                    print(f'  total  MAE {c["total_mae"]} (n={c.get("total_n")})')
                if c.get("spread_diagnostic"):
                    print(f'  spread {c["spread_diagnostic"]}')
                if c.get("calibration_buckets"):
                    print(f'  calibration {json.dumps(c["calibration_buckets"])}')
            if c.get("exclusions") and c["exclusions"] != ["none"]:
                print(f'  exclusions: {c["exclusions"]}')
            if c.get("unresolved") and c["unresolved"] != ["none"]:
                print(f'  unresolved: {c["unresolved"]}')
    print("\nwrote data/audit/cohort_backtest.json")
