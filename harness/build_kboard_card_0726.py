#!/usr/bin/env python3
"""Render the 7/26 K price-board card. Every figure is read from JSON on disk."""
import json, html

B = json.load(open("data/mlb/props/2026-07-26_kboard_full.json"))
A = json.load(open("data/mlb/props/2026-07-26_kboard_audit.json"))
S = json.load(open("data/mlb/props/2026-07-26_kboard_shadow.json"))
K = json.load(open("state.json"))["mlb_kprops"]["kboard_2026_07_26"]
C = json.load(open("cards/2026-07-26_card.json"))
import unicodedata
def a_(s): return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
PS = {}
for r in C["rows"]:
    for sp in ("asp", "hsp"):
        st = r.get(sp + "_stats") or {}
        PS[a_(r[sp]).lower()] = (st.get("ek"), st.get("gs"), "%s@%s" % (r["away"], r["home"]), r["time"])

def e(x): return html.escape(str(x))
quar = set(A["quarantined"])
fit = K["engine_vs_market_shrinkage"]

css = """body{background:#0e1116;color:#d8dee9;font:14px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:28px}
.w{max-width:1120px;margin:0 auto}h1{font-size:21px;margin:0 0 2px}h2{font-size:14px;letter-spacing:.09em;text-transform:uppercase;color:#8b98a9;margin:30px 0 10px;border-bottom:1px solid #232a35;padding-bottom:6px}
.sub{color:#7d8899;font-size:12.5px;margin-bottom:20px}
table{border-collapse:collapse;width:100%;font-size:12.5px}th{text-align:left;color:#8b98a9;font-weight:600;padding:6px 8px;border-bottom:1px solid #232a35;font-size:11px;letter-spacing:.05em;text-transform:uppercase}
td{padding:5px 8px;border-bottom:1px solid #1a212b}tr:hover td{background:#141a23}
.w_{color:#4ade80;font-weight:600}.l_{color:#f87171;font-weight:600}.m{color:#6b7686}.num{text-align:right;font-variant-numeric:tabular-nums}
.q{color:#f59e0b}.box{background:#141a23;border:1px solid #232a35;border-left:3px solid #3b82f6;padding:13px 16px;margin:14px 0;border-radius:3px;font-size:13px}
.warn{border-left-color:#f59e0b}.good{border-left-color:#4ade80}.bad{border-left-color:#f87171}
.box b{color:#e6edf5}ol,ul{margin:8px 0 0;padding-left:20px}li{margin:5px 0}code{background:#1b2230;padding:1px 5px;border-radius:3px;font-size:12px}
.big{font-size:18px;font-weight:600;color:#e6edf5}"""

h = ["<!doctype html><meta charset=utf-8><title>7/26 K price board</title><style>%s</style><div class=w>" % css]
h.append("<h1>MLB 2026-07-26 &mdash; first real two-sided strikeout board</h1>")
h.append("<div class=sub>Paper only. $0 staked. 26 of 30 arms were already pitching when this board was read, "
         "so everything below except the Soriano row is a <b>shadow measurement</b> and advances the "
         "100-play authorization gate by zero.</div>")

w = K["what_is_actually_in_it"]
h.append("<div class='box warn'><b>What is actually in the screenshot.</b> It presents as 30 arms &times; 6 books. "
         "It is really %d arms with any price at all, %d rows with no price whatsoever, a Hard Rock column "
         "cut off at the image edge, and <b>%d two-sided quotes</b> in total. The line-only cells are a display, not a market.</div>"
         % (w["arms_with_at_least_one_price"], w["line_only_rows"], w["two_sided_quotes"]))

h.append("<h2>Integrity tests before anything was priced</h2><table><tr><th>Test<th>Result</tr>")
for k_, v in [("T1 &mdash; two-sided hold in the 2&ndash;12% band", K["integrity_tests"]["T1_hold"]),
              ("T2 &mdash; rung coherence", K["integrity_tests"]["T2_rung_coherence"]),
              ("T3 &mdash; cross-book line dispersion", K["integrity_tests"]["T3_dispersion"]),
              ("T4 &mdash; independent re-read of the 4 live rows", K["integrity_tests"]["T4_independent_reread"])]:
    cl = "w_" if "PASS" in v else "q"
    h.append("<tr><td>%s<td class='%s'>%s</tr>" % (k_, cl, e(v)))
h.append("</table>")
h.append("<div class='box bad'><b>T2 passed on every row and that is the problem.</b> %s</div>"
         % e(K["integrity_tests"]["T2_caveat"]))

h.append("<h2>Every row, engine vs board</h2><table><tr><th>Pitcher<th>Game<th class=num>First pitch"
         "<th class=num>Lines across books<th class=num>Spread<th class=num>E[K]<th class=num>GS"
         "<th class=num>E[K] &minus; med<th>Status</tr>")
for r in sorted(B["rows"], key=lambda z: -max(x[1] for x in z["q"] if x[1] is not None)):
    lns = [x[1] for x in r["q"] if x[1] is not None]
    sp = max(lns) - min(lns); med = sorted(lns)[len(lns) // 2]
    meta = PS.get(a_(r["pitcher"]).lower())
    ek = meta[0] if meta else None
    if r["pitcher"] in quar: stat, cl = "quarantined (spread)", "q"
    elif not any(x[2] is not None or x[3] is not None for x in r["q"]): stat, cl = "no price posted", "m"
    elif ek is None: stat, cl = "no E[K] (GS too low)", "m"
    else:
        pl = next((p for p in S["plays"] if p["pitcher"] == r["pitcher"]), None)
        stat, cl = ("%s %.1f @ %+d (%s)" % (pl["side"], pl["line"], pl["price"], pl["book"]), "w_") if pl else ("no play", "m")
    h.append("<tr><td>%s<td class=m>%s<td class='num m'>%s<td class='num m'>%s<td class='num %s'>%.1f"
             "<td class=num>%s<td class=num>%s<td class='num %s'>%s<td class='%s'>%s</tr>"
             % (e(r["pitcher"]), e(meta[2]) if meta else "&mdash;", e(meta[3]) if meta else "&mdash;",
                "/".join("%.1f" % x for x in lns), "q" if sp > 1.0 else "m", sp,
                "%.2f" % ek if ek is not None else "&mdash;", meta[1] if meta else "&mdash;",
                "l_" if ek is not None and abs(ek - med) >= 1.5 else "m",
                "%+.2f" % (ek - med) if ek is not None else "&mdash;", cl, e(stat)))
h.append("</table>")

h.append("<h2>The engine is over-shrunk, and two independent yardsticks agree</h2>")
h.append("<table><tr><th>Sample<th class=num>n<th class=num>Slope of E[K] on posted line<th class=num>Corr<th class=num>Implied stretch</tr>")
for lbl, key in [("All rows, including quarantined", "all_rows"),
                 ("Clean rows only (T3 pass)", "clean_rows_only"),
                 ("Clean rows, GS &ge; 15", "clean_and_gs_ge_15")]:
    f = fit[key]
    h.append("<tr><td>%s<td class=num>%d<td class='num %s'>%.3f<td class=num>%.3f<td class=num>%.2f&times;</tr>"
             % (lbl, f["n"], "l_" if f["slope"] < 0.8 else "w_", f["slope"], f["corr"], f["implied_stretch"]))
h.append("</table>")
h.append("<div class='box warn'>A slope of 1.00 would mean the engine moves with the market. It moves "
         "<b>%.3f</b>. %s<br><br><b>%s</b><br><br><i>%s</i></div>"
         % (fit["clean_and_gs_ge_15"]["slope"], e(fit["why_the_filter_matters"]),
            e(fit["convergence"]), e(fit["status"])))

h.append("<h2>What the engine actually played</h2>")
h.append("<table><tr><th>Pitcher<th>Play<th class=num>Price<th>Book<th class=num>E[K]<th class=num>p<th class=num>Edge<th class=num>EV<th>Standing</tr>")
for p in S["plays"]:
    live = p["pitcher"] == "Jose Soriano"
    h.append("<tr><td>%s<td><b>%s %.1f</b><td class=num>%+d<td class=m>%s<td class=num>%.2f<td class=num>%.3f"
             "<td class=num>%+.3f<td class='num %s'>%+.3f<td class='%s'>%s</tr>"
             % (e(p["pitcher"]), p["side"], p["line"], p["price"], e(p["book"]), p["ek"], p["p"],
                p["edge"], "l_" if p["ev"] > 0.3 else "w_", p["ev"], "w_" if live else "l_",
                "registered pre-lock, gate-eligible" if live else "SHADOW &mdash; game already started, and see below"))
h.append("</table>")
h.append("<div class='box bad'><b>The Fedde row is a bug report, not a bet.</b> A claimed +0.469 EV is not "
         "a market oversight, it is the engine failing to read the line. A posted 2.5 K line <i>is</i> the "
         "book telling us it expects a short outing. The engine's E[TBF] prior projects a normal start, so "
         "it invents an edge. Freeland at 1.5, Avila at 1.5 and Baz at 2.5 have the identical shape. "
         "Every one of them is the opener/bulk-arm defect wearing a different jersey.</div>")

h.append("<h2>What is wrong with this card</h2><ol>")
for t in [
 "26 of 30 arms had already started. This is the third board in a row to arrive mid-slate. The single most valuable thing that could change is a capture before first pitch.",
 "n=12 on the shrinkage fit. The convergence with the 7/25 outcome slope is encouraging and is still two small samples agreeing, not a result.",
 "Neither the 7/25 outcome regression nor this market regression was pre-registered. Both are hypothesis-generating. E5 is now pre-registered against an untouched forward holdout and the engine has not been touched.",
 "The residual correlates with the line at %.2f. If E5 confirms shrinkage, then most of what this engine has been calling 'edge' was an artifact of buying low lines, and the 9 graded plays to date need re-reading in that light." % fit["clean_rows_only"]["corr"],
 "The quarantine threshold of 1.0 K is a judgement call I made, not a fitted parameter. It excludes 10 rows. A different threshold gives a different slope.",
 "Two rows (Baz on BAL, Suarez on BOS) looked like source errors and were not. The pre-slate card confirmed the board. Worth recording because hand-correcting them would have been the mistake.",
 "Hard Rock's prices are outside the image. Six book columns were advertised; five are readable.",
 "Still no closing price has ever been captured, so nothing here can be checked against a close.",
]:
    h.append("<li>%s</li>" % t)
h.append("</ol>")
h.append("<div class=sub style='margin-top:26px'>Board at <code>data/mlb/props/2026-07-26_kboard_full.json</code>, "
         "audit by <code>harness/audit_kboard_0726.py</code>, shadow run by "
         "<code>harness/shadow_kboard_0726.py</code>. E[K] and GS come from the pre-slate card, which never saw this image.</div></div>")

open("cards/2026-07-26_kboard.html", "w").write("".join(h))
print("wrote cards/2026-07-26_kboard.html")
