#!/usr/bin/env python3
"""THE 9/1 PITCHER-CORPUS REFRESH EXPERIMENT — baseline, control, after, isolation.

DESIGN, as directed by the owner:
  BASELINE  assemble (never recompute) the pre-ingestion state of all 15 games from the three
            frozen artifacts: my FREEZE_v2, the owner's PA-state v2 (fixed external comparator,
            untouched), and the market overlay.
  CONTROL   after the feature-plumbing patch and with the as-of moved to 2026-09-01, rerun on
            the UNREFRESHED corpus. It must reproduce FREEZE_v2's probabilities exactly, or the
            experiment cannot claim the Δ isolates the refresh.
  AFTER     identical coordinator, seeds, trials, parks, RF/RA, thresholds — only the pitcher
            logs differ.
  The owner's board is never rerun and never altered.

WHY THE AS-OF MOVES AND WHY THAT IS NOT A CONFOUND. build_board_0825.SLATE_DATE is 2026-08-25
and starter() reads it as the sp_asof cutoff. On the OLD corpus (no rows after 2026-07-23)
every cutoff from 2026-07-24 onward selects the identical row set, so 8/25 -> 9/1 is provably
a no-op there — the CONTROL run is the proof, not an assumption. On the refreshed corpus the
9/1 cutoff is what "strictly before the slate" means. PIT holds under both.
"""

MODULE_ID = "refresh_experiment_0901"

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SLATE_DATE = "2026-09-01"
FREEZE_V2 = "cards/2026-09-01_mlb_board_FREEZE_v2.json"
OWNER_V2 = "cards/2026-09-01_mlb_owner_shadow_v2.json"
OVERLAY = "cards/2026-09-01_mlb_market_overlay.json"
BASELINE_OUT = "cards/2026-09-01_refresh_baseline.json"

FOCUS_DIRECTION = ("DET@MIN", "ATL@WSH")
FOCUS_MAGNITUDE = ("CWS@HOU", "BAL@COL", "NYY@LAA")


def _starter_block(snap, side):
    d = snap["starter_dispositions"][side]
    st = d.get("stamp") or {}
    return {
        "name": snap["%s_starter" % side],
        "disposition": d.get("disposition"),
        "grade": d.get("grade"),
        "dose_multiplier": d.get("dose_multiplier"),
        "actionable": d.get("actionable"),
        "observed_at": st.get("observed_at"),
        "age_days": d.get("age_days"),
        "limit_days": d.get("limit_days"),
        "sp_consumed": snap["sp_%s" % ("away" if side == "away" else "home")],
        "consumed_is_registered_fallback": not d.get("actionable", False),
    }


def build_baseline():
    fz = json.load(open(FREEZE_V2))
    own = {r["event"]: r for r in json.load(open(OWNER_V2))["rows"]}
    ovl = json.load(open(OVERLAY))
    prices = ovl["PRICES"]
    mine_by_ev = {r["event"]: r for r in ovl["MY_V13_OVERLAY"]}
    rows = []
    for g in fz["games"]:
        ev = g["event"]
        o = own[ev]
        m = prices.get(ev)
        mo = mine_by_ev[ev]
        rows.append({
            "event": ev,
            "raw_v13_p_home": g["forecast"]["p_home"],
            "dosed_p_home": g["forecast"]["p_home_dosed"],
            "resolved_information_dose": g["snapshot"]["resolved_information_dose"],
            "starter_away": _starter_block(g["snapshot"], "away"),
            "starter_home": _starter_block(g["snapshot"], "home"),
            "owner_model_home": o["model_home_pct"] / 100.0,
            "owner_sim_home": o["sim_home_pct"] / 100.0,
            "market": (None if m is None else {"away_ml": m["away_ml"],
                                               "home_ml": m["home_ml"],
                                               "source": m["source"]}),
            "novig_home": mo.get("market_no_vig_home"),
            "execution_state": mo.get("execution_state"),
        })
    return {"schema": "ops.refresh_experiment.baseline.v1", "slate_date": SLATE_DATE,
            "record_id": "2026-09-01_refresh_baseline",
            "assembled_from": [FREEZE_V2, OWNER_V2, OVERLAY],
            "assembled_not_recomputed": True,
            "owner_board_is_fixed_comparator": True,
            "rows": rows}


def selftest():
    f = []
    b = build_baseline()
    if len(b["rows"]) != 15:
        f.append("baseline is not 15 rows")
    for r in b["rows"]:
        for k in ("raw_v13_p_home", "dosed_p_home", "resolved_information_dose",
                  "owner_model_home", "owner_sim_home"):
            if r.get(k) is None:
                f.append("%s missing %s" % (r["event"], k))
        for side in ("starter_away", "starter_home"):
            s = r[side]
            if s["name"] is not None and s["disposition"] is None:
                f.append("%s %s named but no disposition" % (r["event"], side))
            if not s["consumed_is_registered_fallback"] and s["sp_consumed"]["era"] is None:
                f.append("%s %s claims actionable but consumed nulls" % (r["event"], side))
    mil = [r for r in b["rows"] if r["event"] == "MIL@CHC"][0]
    if mil["market"] is not None or mil["execution_state"] != "NO_LINE":
        f.append("MIL@CHC conflicted price leaked into the baseline as a market")
    print("%s selftest: %s" % (MODULE_ID, "PASS" if not f else "FAIL"))
    for x in f:
        print("  -", x)
    return not f


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    b = build_baseline()
    with open(BASELINE_OUT, "w") as fh:
        json.dump(b, fh, indent=1, sort_keys=True)
    print("baseline frozen ->", BASELINE_OUT)
    for r in b["rows"]:
        print("%-8s raw %.4f dosed %.4f dose %.2f  away %-11s(%s) home %-11s(%s)" % (
            r["event"], r["raw_v13_p_home"], r["dosed_p_home"],
            r["resolved_information_dose"],
            r["starter_away"]["disposition"], r["starter_away"]["observed_at"] or "-",
            r["starter_home"]["disposition"], r["starter_home"]["observed_at"] or "-"))


# ================================================================= control / after runs
#
# The coordinator is untouched. Two runtime injections, both proven no-ops on the old corpus by
# the CONTROL run: (a) B.SLATE_DATE moves to 2026-09-01 (the old corpus has no row after
# 2026-07-23, so every cutoff past 7/24 selects identical rows); (b) starter() gains the
# ERA-placeholder exclusion (on the old corpus no slate starter is actionable, so excluded or
# not, no ERA reaches V13). HFA, park factors, RF/RA, thresholds, seeds, trials: untouched.

def patched_starter_factory(B):
    import board_freshness as BF
    import build_ml_asof as ASOF
    import run_v13_historical as V13
    from ingest_lancebroz import er_placeholder_dates

    def starter(pid_map, name, acquire=None, now=None):
        if name == "TBD" or name is None:
            _, status, disp = BF.resolve_starter_slot(name, None, "OFFICIAL_TBD_CAP",
                                                      B.SLATE_DATE, None, acquire=acquire, now=now)
            return V13._sp({}), status, None, disp
        pid = pid_map.get(name)
        if pid is None:
            _, status, disp = BF.resolve_starter_slot(name, None, "NO_PID_CAP(%s)" % name,
                                                      B.SLATE_DATE, None, acquire=acquire, now=now)
            return V13._sp({}), status, None, disp
        source = "pitcher_logs/%s.txt via sp_asof_strict" % pid
        ph = er_placeholder_dates(pid)
        feats, flags = ASOF.sp_asof_strict(pid, B.SLATE_DATE, ph)
        if feats is None:
            _, status, disp = BF.resolve_starter_slot(name, None,
                                                      "NO_LOG_CAP(%s)" % flags["reason"],
                                                      B.SLATE_DATE, source,
                                                      acquire=acquire, now=now)
            return V13._sp({}), status, None, disp
        # ERA over GENUINE-ER rows only. sp_asof's cumulative era spans every row; recompute the
        # numerator and denominator excluding registered ER-placeholder dates. Zero genuine
        # innings -> era None -> the row cannot be actioned on a fabricated 0.00.
        if ph:
            rows = ASOF.log_rows(pid) or []
            ip = er = 0.0
            for d, i_, e_, *_rest in rows:
                if d >= B.SLATE_DATE or d in ph:
                    continue
                ip += i_
                er += e_
            feats["era"] = round(er * 9 / ip, 3) if ip >= 1 else None
            feats["era_window_note"] = "genuine-ER rows only; placeholder dates excluded"
        if feats.get("era") is None:
            _, status, disp = BF.resolve_starter_slot(name, None,
                                                      "NO_GENUINE_ER_WINDOW_CAP",
                                                      B.SLATE_DATE, source,
                                                      acquire=acquire, now=now)
            return V13._sp({}), status, None, disp
        feats2, status, disp = BF.resolve_starter_slot(name, feats, "RESOLVED", B.SLATE_DATE,
                                                       source, acquire=acquire, now=now)
        if feats2 is None:
            return V13._sp({}), status, None, disp
        sp = {"era": feats2["era"], "gs": feats2["gs"], "k": feats2["k_pct"],
              "bb": feats2["bb_pct"]}
        return sp, status, V13.rs(sp["era"], sp["gs"], sp["k"], sp["bb"]), disp

    return starter


def run_slate(tag):
    """Run the 9/1 slate through the untouched coordinator with the injections above."""
    import build_board_0825 as B
    import build_board_0901 as B901
    old_starter, old_slate = B.starter, B.SLATE_DATE
    B.starter = patched_starter_factory(B)
    B.SLATE_DATE = SLATE_DATE
    try:
        import mlb_daily_coordinator as C
        res = C.run(SLATE_DATE, [], extra=B901.events_v2(), trials=30000)
    finally:
        B.starter, B.SLATE_DATE = old_starter, old_slate
    res["experiment_tag"] = tag
    return res


def control_check():
    fz = {g["event"]: g for g in json.load(open(FREEZE_V2))["games"]}
    ctl = run_slate("CONTROL_OLD_CORPUS")
    diffs = []
    for g in ctl["games"]:
        ev = g["event"]
        a, b = g["forecast"], fz[ev]["forecast"]
        for k in ("p_home", "p_home_dosed"):
            if abs((a[k] or 0) - (b[k] or 0)) > 1e-12:
                diffs.append({"event": ev, "field": k, "control": a[k], "freeze_v2": b[k]})
        da = g["snapshot"]["resolved_information_dose"]
        db = fz[ev]["snapshot"]["resolved_information_dose"]
        if abs(da - db) > 1e-12:
            diffs.append({"event": ev, "field": "dose", "control": da, "freeze_v2": db})
    return {"identical": not diffs, "n_games": len(ctl["games"]), "diffs": diffs}
