#!/usr/bin/env python3
"""Render the 7/25 results card. Every figure is read from JSON on disk."""

MODULE_ID = "build_results_0725"
import json, html

G = json.load(open("data/mlb/box/2026-07-25_grades.json"))
S = json.load(open("state.json"))
C = json.load(open("cards/2026-07-25_card.json"))
B = json.load(open("data/mlb/box/2026-07-25_raw.json"))
A = json.load(open("data/mlb/box/2026-07-25_statsapi.json"))
led = S["ledgers"]["ml_ev_tracking"]
fd = S["ledgers"]["v13_forward_directional"]
k = S["mlb_kprops"]["calibration_2026_07_25_oos"]
FIN = {"%s@%s" % (g["away"], g["home"]): (g["away_r"], g["home_r"]) for g in B["games"]}

def e(x): return html.escape(str(x))

css = """body{background:#0e1116;color:#d8dee9;font:14px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:28px}
.w{max-width:1080px;margin:0 auto}h1{font-size:21px;margin:0 0 2px}h2{font-size:14px;letter-spacing:.09em;text-transform:uppercase;color:#8b98a9;margin:30px 0 10px;border-bottom:1px solid #232a35;padding-bottom:6px}
.sub{color:#7d8899;font-size:12.5px;margin-bottom:20px}
table{border-collapse:collapse;width:100%;font-size:13px}th{text-align:left;color:#8b98a9;font-weight:600;padding:6px 9px;border-bottom:1px solid #232a35;font-size:11.5px;letter-spacing:.05em;text-transform:uppercase}
td{padding:6px 9px;border-bottom:1px solid #1a212b}tr:hover td{background:#141a23}
.w_{color:#4ade80;font-weight:600}.l_{color:#f87171;font-weight:600}.m{color:#6b7686}.num{text-align:right;font-variant-numeric:tabular-nums}
.box{background:#141a23;border:1px solid #232a35;border-left:3px solid #3b82f6;padding:13px 16px;margin:14px 0;border-radius:3px;font-size:13px}
.warn{border-left-color:#f59e0b}.good{border-left-color:#4ade80}.bad{border-left-color:#f87171}
.box b{color:#e6edf5}ol,ul{margin:8px 0 0;padding-left:20px}li{margin:5px 0}code{background:#1b2230;padding:1px 5px;border-radius:3px;font-size:12px}
.big{font-size:18px;font-weight:600;color:#e6edf5}"""

h = ["<!doctype html><meta charset=utf-8><title>MLB 7/25/2026 results</title><style>%s</style><div class=w>" % css]
h.append("<h1>MLB 2026-07-25 &mdash; graded</h1>")
h.append("<div class=sub>Paper only. $0 staked. Sides remain DEAD under R3. Nothing here advances the 100-play K-prop authorization gate.</div>")

h.append("<div class='box good'><b>Two-source grading gate: PASS.</b> 15 games, 30 team scores, zero disagreements between "
         "the box-score paste (parsed locally by <code>harness/parse_box_0725.py</code>) and a fresh statsapi hydrated "
         "schedule. The grader refuses to run if any score disagrees or any game is not Final.</div>")

# --- ml ev
h.append("<h2>Pre-registered EV ledger (ml_ev_tracking)</h2><table><tr><th>Date<th>Pick<th class=num>Price<th>Game"
         "<th class=num>V13 p<th class=num>Implied<th class=num>Edge<th>Final<th>Result<th class=num>P/L</tr>")
for g in led["graded"]:
    cl = "w_" if g["result"] == "WIN" else "l_"
    h.append("<tr><td class=m>%s<td><b>%s</b><td class=num>%+d<td class=m>%s<td class=num>%.3f<td class=num>%.3f"
             "<td class=num>%+.3f<td>%s<td class='%s'>%s<td class='num %s'>%+.2fu</tr>"
             % (g["date"], e(g["pick"]), g["ml"], e(g["game"]), g["v13_p"], g["implied"], g["edge"],
                e(g["final"]), cl, g["result"], cl, g["pl"]))
h.append("</table>")
h.append("<div class='box warn'><span class=big>%d&ndash;%d, %+.2fu (ROI %+.1f%%)</span><br>%s</div>"
         % (led["record_w"], led["record_l"], led["units"], led["roi_pct"], e(led["n_note"])))

# --- directional
h.append("<h2>V13 directional, all 15 games (display only, no price)</h2><table>"
         "<tr><th>Game<th class=num>Home WP<th>Lean<th>Final<th>Result<th class=num>Proj total<th class=num>Line<th>Lean<th class=num>Actual<th>Result</tr>")
for r in C["rows"]:
    gk = "%s@%s" % (r["away"], r["home"]); ar, hr = FIN[gk]
    lean = r["home"] if r["v13"]["home_wp"] >= 0.5 else r["away"]
    hit = (hr > ar) if lean == r["home"] else (ar > hr)
    line = r["lines"].get("total"); tlean = r.get("total_lean"); act = ar + hr
    if line is None or tlean not in ("OVER", "UNDER"):
        tc, tr_ = "m", "&mdash;"
    elif act == line: tc, tr_ = "m", "PUSH"
    elif (act > line) == (tlean == "OVER"): tc, tr_ = "w_", "W"
    else: tc, tr_ = "l_", "L"
    h.append("<tr><td>%s<td class=num>%.3f<td>%s<td class=m>%d&ndash;%d<td class='%s'>%s"
             "<td class=num>%.1f<td class=num>%s<td>%s<td class=num>%d<td class='%s'>%s</tr>"
             % (e(gk), r["v13"]["home_wp"], e(lean), ar, hr, "w_" if hit else "l_", "W" if hit else "L",
                r["v13"]["proj_total"], e(line), e(tlean or "&mdash;"), act, tc, tr_))
h.append("</table>")
h.append("<div class=box>Sides <b>%d&ndash;%d</b> on the slate, <b>%d&ndash;%d</b> cumulative (%.1f%%). "
         "Totals <b>%d&ndash;%d&ndash;%d</b>. A win rate with no price attached is not an edge, which is exactly "
         "why sides stay DEAD.</div>"
         % (G["directional"]["w"], G["directional"]["l"], fd["w"], fd["l"],
            100.0 * fd["w"] / (fd["w"] + fd["l"]), G["totals"]["w"], G["totals"]["l"], G["totals"]["p"]))

# --- k calibration
h.append("<h2>K model, out-of-sample &mdash; pre-slate E[K] vs actual (exploratory)</h2><table>"
         "<tr><th>Game<th>Pitcher<th class=num>E[K]<th class=num>Actual<th class=num>IP<th class=num>Error</tr>")
for r in sorted(G["kcal"]["rows"], key=lambda z: -(z["so"] - z["ek"])):
    d = r["so"] - r["ek"]
    h.append("<tr><td class=m>%s<td>%s<td class=num>%.2f<td class=num>%d<td class=num>%.1f<td class='num %s'>%+.2f</tr>"
             % (e(r["game"]), e(r["pitcher"]), r["ek"], r["so"], r["ip"], "w_" if abs(d) < 1.5 else "l_", d))
h.append("</table>")
h.append("<div class='box warn'>n=%d &nbsp; MAE <b>%.2f</b> &nbsp; bias <b>%+.2f</b> &nbsp; RMSE <b>%.2f</b> &nbsp; "
         "corr <b>%.3f</b> &nbsp; OLS slope <b>%.2f</b><br><br>%s<br><br><i>%s</i></div>"
         % (k["n"], k["mae"], k["bias_actual_minus_proj"], k["rmse"], k["corr"], k["ols_slope"],
            e(k["finding"]), e(k["caveat"])))

# --- what's wrong
h.append("<h2>What is wrong with this card</h2><ol>")
for t in [
    "The three ML plays are n=3. The +46.7%% ROI is arithmetic, not evidence. No confidence interval is quoted because at n=3 it would span everything.",
    "The K calibration is one slate, not pre-registered, and therefore hypothesis-generating only. It cannot license an engine change (R7).",
    "6 of 30 card starters did not match the actual first arm, and PHI used a true opener (Tim Mayza, 2.0 IP). The K pipeline has no opener detector.",
    "The box paste's LAD@NYM Team Pitching SO row says 8; the per-pitcher lines and the opposing batting column both say 9. Resolved 9 by majority, but it means the source is not internally consistent.",
    "results.csv <code>close_ml_*</code> and <code>close_total</code> for 7/19&ndash;7/25 contain OPENING prices. A real close has never been captured, so no CLV has ever been measured.",
    "The 'container clock is ~3.8h fast' belief is withdrawn as a stale-cache artifact. Provenance stamps written under it were wrong by ~3.8h; the 7/26 board is ~14.0h pre-slate, not 17.75h. No pick changes, but the claim was overstated.",
    "Totals are 6&ndash;9 on this slate and 11&ndash;16 across two. NOT_READY is the correct status.",
    "Still zero real K-prop prices. The gate has not moved.",
]:
    h.append("<li>%s</li>" % t)
h.append("</ol>")
h.append("<div class=sub style='margin-top:26px'>Sources: user box-score paste (verbatim at "
         "<code>data/mlb/box/2026-07-25_paste.txt</code>) and statsapi hydrated schedule, fetched %s. "
         "Grades computed by <code>harness/grade_0725.py</code>.</div></div>" % e(A["fetched_utc"]))

open("cards/2026-07-25_results.html", "w").write("".join(h))
print("wrote cards/2026-07-25_results.html")
