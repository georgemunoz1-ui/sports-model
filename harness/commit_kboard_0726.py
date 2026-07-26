#!/usr/bin/env python3
"""Commit the 7/26 K price-board work to state.json.

Writes: the board audit result, the SHADOW engine run, the engine-vs-market
shrinkage fit, and the E5 pre-registration that the fit motivates.

Does NOT touch gates.kprops_go_live. Does NOT change the engine. Idempotent.
"""
import json, unicodedata, statistics as st

def a_(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()

S = json.load(open("state.json"))
B = json.load(open("data/mlb/props/2026-07-26_kboard_full.json"))
AUD = json.load(open("data/mlb/props/2026-07-26_kboard_audit.json"))
SH = json.load(open("data/mlb/props/2026-07-26_kboard_shadow.json"))
C = json.load(open("cards/2026-07-26_card.json"))

clean = set(AUD["clean"])
PS = {}
for r in C["rows"]:
    for sp in ("asp", "hsp"):
        s = r.get(sp + "_stats") or {}
        PS[a_(r[sp]).lower()] = (s.get("ek"), s.get("gs"))

def fit(pred):
    xs, ys = [], []
    for r in B["rows"]:
        k = a_(r["pitcher"]).lower()
        if k not in PS or PS[k][0] is None:
            continue
        ek, gs = PS[k]
        if not pred(r["pitcher"], gs):
            continue
        lns = sorted(ln for b, ln, u, o in r["q"] if ln is not None)
        xs.append(lns[len(lns) // 2]); ys.append(ek)
    mx, my = st.mean(xs), st.mean(ys)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    corr = (sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            / (len(xs) * st.pstdev(xs) * st.pstdev(ys)))
    return dict(n=len(xs), slope=round(b, 3), intercept=round(my - b * mx, 2),
                corr=round(corr, 3), implied_stretch=round(1.0 / b, 2))

f_all = fit(lambda p, g: True)
f_clean = fit(lambda p, g: p in clean)
f_stable = fit(lambda p, g: p in clean and g >= 15)

S["mlb_kprops"]["kboard_2026_07_26"] = {
 "source": "user screenshot of an aggregator strikeout board, 30 arms x 6 books",
 "captured_utc_upper_bound": "2026-07-26T19:13Z",
 "what_is_actually_in_it": {
   "arms": len(B["rows"]),
   "book_columns": 6,
   "hard_rock_column": "cut off at the image edge - LINE legible, prices absent. Contributes zero quotes (R1).",
   "arms_with_at_least_one_price": len({r["pitcher"] for r in B["rows"]
                                        for bk, ln, u, o in r["q"] if u is not None or o is not None}),
   "two_sided_quotes": AUD["n_two_sided"],
   "line_only_rows": len([r for r in B["rows"]
                          if not any(u is not None or o is not None for bk, ln, u, o in r["q"])])
 },
 "integrity_tests": {
   "T1_hold": "PASS - %d/%d two-sided quotes inside the 2-12%% band, zero out of band."
              % (AUD["n_two_sided"] - len(AUD["hold_out_of_band"]), AUD["n_two_sided"]),
   "T2_rung_coherence": "PASS - 0 rows with an incoherent ladder.",
   "T2_caveat": ("T2 is NECESSARY BUT NOT SUFFICIENT and this board proves it. Misiorowski's "
                 "ladder (12.5@-135 / 11.5@-330) is perfectly rung-coherent and is still not a "
                 "usable main line: OVER 12.5 K at -135 does not exist as a starter market. "
                 "A coherent ladder can be an alt-line ladder. Do not treat T2 as a pass to price."),
   "T3_dispersion": "10 of 30 rows QUARANTINED for cross-book line spread > 1.0 K.",
   "T3_is_the_discriminator": ("Dispersion, not hold and not rung coherence, is what separates a "
                               "book's main line from an alt rung on an aggregator display."),
   "T4_independent_reread": "PASS - the 4 rows transcribed in the live pass re-read identically from a fresh crop, 0 disagreements."
 },
 "quarantined": AUD["quarantined"],
 "engine_vs_market_shrinkage": {
   "design": ("OLS of the engine's pre-slate E[K] on the board's median posted line. "
              "Slope 1.0 = the engine moves with the market. Slope < 1.0 = the engine is "
              "over-shrunk toward the mean and will mechanically buy every low line and "
              "sell every high line."),
   "all_rows": f_all, "clean_rows_only": f_clean, "clean_and_gs_ge_15": f_stable,
   "finding": ("The engine is materially over-shrunk. On the clean, stable subset the slope is "
               "%.3f, implying the point projection needs stretching by about %.2fx around its mean."
               % (f_stable["slope"], f_stable["implied_stretch"])),
   "why_the_filter_matters": ("Unfiltered the slope reads %.3f (stretch %.2fx). The quarantined "
                              "alt-rung rows alone would have inflated the required correction by "
                              "roughly %.0f%%. Measuring on dirty rows would have produced a much "
                              "more aggressive and wrong engine change."
                              % (f_all["slope"], f_all["implied_stretch"],
                                 100 * (f_all["implied_stretch"] / f_stable["implied_stretch"] - 1))),
   "convergence": ("This is the SECOND independent measurement pointing the same way. The 7/25 "
                   "out-of-sample grade gave an OLS slope of actual-on-projected of 1.35 (n=24, "
                   "outcome-based). This board gives an implied stretch of %.2f (n=%d, market-based). "
                   "Outcomes and prices are independent yardsticks and they agree on both the "
                   "direction and roughly the magnitude."
                   % (f_stable["implied_stretch"], f_stable["n"])),
   "status": "HYPOTHESIS-GENERATING ONLY. Neither measurement was pre-registered. No engine change is licensed by either (R7)."
 },
 "shadow_run": {
   "gate_eligible": False, "staked": 0.0,
   "note": SH["note"],
   "permitted_rows": len(SH["permitted"]),
   "plays": [dict(pitcher=p["pitcher"], side=p["side"], line=p["line"], price=p["price"],
                  book=p["book"], ev=p["ev"], edge=p["edge"], p=p["p"], ek=p["ek"])
             for p in SH["plays"]],
   "read": ("2 selections out of 30 arms. One is Soriano, which is the play already registered "
            "live and pre-lock - the shadow run reproducing it independently is a consistency "
            "check on the pipeline, not a second play. The other is Fedde OVER 2.5 at +106 with "
            "a claimed EV of +0.469, and that number is a red flag, not a find: see known_issues.")
 }
}

# ---- E5 pre-registration ----------------------------------------------------
if not any(e["id"] == "E5" for e in S["experiment_queue"]):
    S["experiment_queue"].append({
     "id": "E5",
     "passes": False,
     "status": "PRE-REGISTERED 2026-07-26, NOT YET RUN. Engine unchanged until it passes.",
     "title": "Variance correction (stretch) of the K point projection",
     "hypothesis": ("E[K] is over-shrunk toward the league mean. Both the 7/25 outcome regression "
                    "(actual-on-projected slope 1.35) and the 7/26 market regression (E[K]-on-line "
                    "slope %.3f, stretch %.2fx) say the same thing from independent directions."
                    % (f_stable["slope"], f_stable["implied_stretch"])),
     "method": ("ek_adj = mu + s * (ek - mu), where mu is the as-of league mean starter E[K] and s "
                "is a single global scalar. Fit s ONCE on data strictly before the holdout window "
                "and then freeze it. E[TBF], the Poisson tail, and select_play are all untouched."),
     "holdout": ("UNTOUCHED FORWARD ROWS ONLY. The 7/25 n=24 and the 7/26 n=%d that generated this "
                 "hypothesis are BURNED and may not appear in the confirmatory sample. Window opens "
                 "at the first slate graded after s is frozen." % f_stable["n"]),
     "primary_endpoint": "MAE of ek_adj vs actual starter SO on the holdout, against unadjusted E[K] on the same rows.",
     "secondary": ["calibration slope/intercept of P(over) on lined rows",
                   "Brier on lined rows",
                   "count and direction of flipped select_play decisions",
                   "paper ROI of the flipped set",
                   "slice by gs (5-9 vs >=15) - the stretch may be a small-sample artifact"],
     "adopt_rule": ("Adopt only if ALL: holdout MAE improves >= 0.10 K; calibration slope stays in "
                    "[0.9, 1.1]; Brier not worse; the flipped-decision set is not net negative. "
                    "A MAE gain that comes with calibration drift is a REJECT - stretching the point "
                    "estimate without widening the variance would manufacture fake tail edges."),
     "kill_criterion": ("If the fitted s on pre-holdout data is inside [0.95, 1.05], the effect was "
                        "small-sample noise and E5 closes NO-PROMOTE without running the holdout."),
     "why": ("Every 'edge' the engine currently reports is suspiciously correlated with the market "
             "line level (corr of residual with line = -0.87 on the 7/26 board). If that is pure "
             "shrinkage artifact, then the K play selection is not finding value, it is just "
             "systematically buying overs on low lines. This has to be settled before n=100.")
    })

# ---- known issues -----------------------------------------------------------
NEW = [
 ("KPROP-OPENER-2", "The engine's single largest claimed edge on the first real price board (Fedde "
  "OVER 2.5 @ +106, EV +0.469) sits on the lowest line on the board. A 2.5 K line IS the market "
  "telling us it expects a short outing. The engine's E[TBF] prior does not read that signal, so it "
  "projects a full start and manufactures an edge. Freeland (1.5), Avila (1.5) and Baz (2.5 at DK) "
  "have the same shape. Treat a posted line at or below 3.5 as evidence about TBF, not as value."),
 ("KPROP-EDGE-ARTIFACT", "Residual (E[K] - posted line) correlates with the posted line at -0.87 on "
  "the 7/26 board. Direction of every selection is nearly determined by whether the line is high or "
  "low. Until E5 settles this, no K selection should be read as genuine information."),
 ("KBOARD-COVERAGE", "The board looks like 30 priced arms and is not. 8 of 30 rows carry no price at "
  "all, the Hard Rock column is cut off entirely, and only 12 arms have any two-sided quote. Total "
  "usable two-sided quotes: 31."),
 ("KBOARD-T2-INSUFFICIENT", "Rung coherence passed on 100% of rows including ones that are plainly "
  "alt-line ladders (Misiorowski 12.5). T2 can no longer be cited alone as evidence that a board is "
  "a real per-book market. T3 dispersion is the load-bearing test."),
 ("KBOARD-LATE", "This board arrived after first pitch for 26 of 30 arms. The engine's first-ever "
  "look at a full real price board is therefore a shadow measurement, not a slate. A board captured "
  "pre-lock remains the single highest-value missing input.")
]
have = {i["id"] for i in S["known_issues"] if isinstance(i, dict) and "id" in i}
for iid, txt in NEW:
    if iid not in have:
        S["known_issues"].append({"id": iid, "opened": "2026-07-26", "text": txt})

S["next_actions"] = [
 "Grade Jose Soriano OVER 4.5 K (-166 FD, paper, weight 1.0) after LAA@SF; it is the only gate-eligible K play outstanding.",
 "Grade the two pending 7/26 ML rows (COL +265, NYY +140) after the slate.",
 "Fit and FREEZE the E5 stretch scalar s on pre-2026-07-26 data, then open the forward holdout. Do not touch the engine before the holdout reads out.",
 "Capture one genuine CLOSING price snapshot. Still never done. Blocks E3 and E4, and results.csv close_* columns are opens, so this is the only path to real CLV.",
 "Build the opener / bulk-arm detector, or hard-exclude any arm whose posted line is <= 3.5 until E[TBF] can read the market's TBF signal.",
 "Ask Taco for a K board captured BEFORE first pitch. Every board so far has arrived mid-slate.",
 "Amend rule 3's written text to match the code (TBD or gs<2), effective 2026-07-27, forward only.",
 "Sunday weekly review: dashboard, backup bundle, cumulative Brier raw-vs-shrunk A/B.",
 "8-field opponent-aware parser fix before any 8-field forward writes.",
 "GitHub remote setup - still waiting on Taco's repo URL and a fine-grained token."
]

before = S["gates"]["kprops_go_live"]["progress"]
S["updated_utc"] = "2026-07-26T19:30:00Z"
json.dump(S, open("state.json", "w"), indent=1)
assert json.load(open("state.json"))["gates"]["kprops_go_live"]["progress"] == before
print("state.json updated; gate untouched: %r" % before)
print("engine_vs_market: all %s | clean %s | clean+gs>=15 %s" % (f_all, f_clean, f_stable))
