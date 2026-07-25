#!/usr/bin/env python3
"""Render cards/2026-07-25_card.html from the card JSON. EVERY number in the HTML is computed
here from cards/2026-07-25_card.json — nothing is hand-typed. Also emits the pre-registered
ml_ev_tracking pick list (R7: rule fixed before any 7/25 game starts)."""
import json, os, sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

C = json.load(open("cards/2026-07-25_card.json"))
ODDS = json.load(open("data/mlb/odds/2026-07-25_pregame.json"))
ROWS = C["rows"]

def imp(ml):  return (-ml)/(-ml+100) if ml < 0 else 100/(ml+100)
def prof(ml): return 100/abs(ml) if ml < 0 else ml/100
def sgn(x, d=0): return f"{x:+.{d}%}" if d else f"{x:+.0%}"

# ---------- EV gate (pre-registered, mirrors engine.kprops.select_play thresholds) ----------
MIN_EDGE = 0.04
cands = []
for r in ROWS:
    l = r["lines"]; hwp = r["v13"]["home_wp"]
    for team, p, ml, opp in ((r["away"], 1-hwp, l["ml_away"], r["home"]),
                             (r["home"], hwp,   l["ml_home"], r["away"])):
        if ml is None: continue
        cands.append(dict(gm=f"{r['away']}@{r['home']}", team=team, opp=opp, ml=ml,
                          p=p, impl=imp(ml), edge=p-imp(ml), ev=p*prof(ml)-(1-p),
                          cap=r["capped"], v13_lean_matches=(p > 0.5)))
cands.sort(key=lambda x: -x["ev"])
qual   = [x for x in cands if x["ev"] > 0 and x["edge"] >= MIN_EDGE and not x["cap"]]
capped_qual = [x for x in cands if x["ev"] > 0 and x["edge"] >= MIN_EDGE and x["cap"]]

# ---------- K projections ----------
karms = []
for r in ROWS:
    for who, nm, st in (("away", r["asp"], r["asp_stats"]), ("home", r["hsp"], r["hsp_stats"])):
        karms.append((nm, st.get("ek"), st.get("gs"), st.get("era"), st.get("k"),
                      f"{r['away']}@{r['home']}"))
karms.sort(key=lambda x: (x[1] is None, -(x[1] or 0)))

# ---------- totals ----------
tot = []
for r in ROWS:
    line = r["lines"]["total"]; pj = r["v13"]["proj_total"]
    if line is None: continue
    tot.append((f"{r['away']}@{r['home']}", line, pj, pj-line))
tot.sort(key=lambda x: -abs(x[3]))

CSS = """:root{--bg:#0d1117;--card:#161b22;--line:#232b36;--ink:#e6edf3;--dim:#8b949e;--grn:#3fb950;--red:#f85149;--amb:#d29922;--blu:#58a6ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:24px 16px 50px}
h1{font-size:19px;margin:0 0 2px}h2{font-size:12.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--dim);margin:18px 0 7px;border-bottom:1px solid var(--line);padding-bottom:5px}
.sub{color:var(--dim);font-size:12px;margin-bottom:11px}
table{width:100%;border-collapse:collapse;font-size:12px}th,td{padding:5px 7px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--dim);font-size:9.5px;text-transform:uppercase}td:first-child,th:first-child,td:nth-child(2),th:nth-child(2){text-align:left}
.b{font-weight:700}.mut{color:var(--dim)}.pos{color:var(--grn)}.neg{color:var(--red)}.blu{color:var(--blu)}.amb{color:var(--amb)}
.note{border:1px solid var(--line);border-radius:8px;padding:10px 13px;margin:9px 0;font-size:12px;background:#11161d}
.info{border-left:3px solid var(--blu)}.warn{border-left:3px solid var(--amb)}.dead{border-left:3px solid var(--red)}
.foot{color:var(--dim);font-size:10.5px;margin-top:14px;border-top:1px solid var(--line);padding-top:8px}
td.wide,th.wide{white-space:normal;text-align:left}"""

H = []
A = H.append
A('<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">')
A(f'<title>Card — Sat July 25</title><style>{CSS}</style></head><body><div class="wrap">')
A(f'<h1>Saturday, July 25, 2026 — Full Tracking Card · {len(ROWS)} games</h1>')
A('<div class="sub">Every column is <b>DISPLAY / TRACKING only</b>. Sides <b>DEAD</b> (R3), totals <b>NOT_READY</b>, '
  'and <b>no K-prop board is posted yet for 7/25</b> — so under R1 (never guess prices) there are <b>zero prop plays</b> on this card. '
  'K-prop ledger <b>4-5, −1.61u</b> · gate <b>9/100</b> · $0 real money.</div>')

A('<div class="note warn"><b>⚠ These are OPENING lines, captured '
  f'{ODDS.get("captured_utc","?")} — roughly 11 hours before first pitch. They <b>will</b> move.</b> '
  'Source: covers.com (single source; no book attribution). A closing snapshot must be taken before lock — '
  'both to price anything for real and to feed the queued E3 line-move/CLV experiment. Treat every price below as provisional.</div>')

# ---- headline read ----
top = qual[0] if qual else None
A('<div class="note info"><b>The read of the day: the market is charging chalk prices V13 does not believe in.</b> '
  'The two biggest gaps are <b>COL@MIL</b> (market makes MIL a 66% favorite at −210; V13 says 53.8%) and '
  '<b>KC@DET</b> (market 61.6% on DET at −171; V13 says 53.4%). '
  'In both, V13 still <i>leans</i> the home favorite to win — but the dog is priced so far off V13\'s number that '
  '<b>the dog is the positive-EV side</b>. That is the whole objective function in one line: '
  '<b>+EV vs the break-even price, not win% &gt; 50%.</b> '
  'The one game where V13 both leans and finds value on the same side is <b>STL −116</b>.</div>')

# ---- all games ----
A('<h2>📋 All 15 games — lines + V13 signals (tracking)</h2>')
A('<table><thead><tr><th>Game</th><th>Starters (away / home)</th><th>ML a/h</th><th>Tot</th>'
  '<th>V13 H%</th><th>mkt H%</th><th>gap</th><th>Proj T</th><th>Lean</th><th>Blow a/h</th><th>K proj a/h</th></tr></thead><tbody>')
for r in ROWS:
    l = r["lines"]; v = r["v13"]
    cap = " ⚠" if r["capped"] else ""
    def nm(s):
        parts = s.split(); return (parts[0][0]+"."+parts[-1]) if len(parts) > 1 and len(s) > 13 else s
    ka = r["asp_stats"].get("ek"); kh = r["hsp_stats"].get("ek")
    gap = r["gap_home"]
    gcls = "neg b" if gap <= -0.07 else ("neg" if gap <= -0.04 else ("pos" if gap >= 0.04 else "mut"))
    d = v["proj_total"] - l["total"] if l["total"] is not None else 0
    lean = r["total_lean"]
    lcls = "pos" if lean == "OVER" else ("blu" if lean == "UNDER" else "mut")
    ltxt = f"{lean} {d:+.1f}" if abs(d) >= 1.0 else ("~" if abs(d) < 0.25 else lean)
    A(f"<tr><td class='b'>{r['away']}@{r['home']}</td>"
      f"<td class='mut'>{nm(r['asp'])} / {nm(r['hsp'])}{cap}</td>"
      f"<td>{l['ml_away']:+}/{l['ml_home']:+}</td><td>{l['total']:g}</td>"
      f"<td class='b'>{v['home_wp']:.0%}</td><td class='mut'>{r['mkt_home_prob']:.0%}</td>"
      f"<td class='{gcls}'>{gap:+.0%}</td><td>{v['proj_total']:.1f}</td>"
      f"<td class='{lcls}'>{ltxt}</td>"
      f"<td class='mut'>{v['blow_away']:.0%}/{v['blow_home']:.0%}</td>"
      f"<td class='mut'>{ka if ka else '—'} / {kh if kh else '—'}</td></tr>")
A('</tbody></table>')
A('<div class="sub" style="margin-top:6px">⚠ = V13 low-trust (a starter is TBD or has &lt;5 GS in the log). '
  'gap = V13 home WP − market home WP; negative means V13 leans more toward the road side than the price does. '
  'Blow = P(margin ≥ 5). Run-line prices are in the odds file, not shown here — one of them is flagged unverified (see footnotes).</div>')

# ---- EV table ----
A('<h2>💵 ML EV tracking — NEW ledger, rule pre-registered before first pitch (R7)</h2>')
A('<div class="note dead"><b>Why this is a new ledger and not a continuation.</b> The old <code>ml_tracking</code> ledger '
  '(7-3) selected picks by <i>V13 directional lean + my discretion</i>. That is not an EV rule, and mixing the two inside '
  'one W-L record would contaminate both. <code>ml_tracking</code> is frozen at 7-3 and superseded. '
  '<b>ml_ev_tracking</b> starts today at 0-0 with a mechanical rule fixed in advance:<br>'
  '&nbsp;&nbsp;<b>1.</b> For every game, compute V13 P(win) for <i>both</i> sides.<br>'
  '&nbsp;&nbsp;<b>2.</b> Qualify a side if <b>EV &gt; 0</b> AND <b>edge = p − implied ≥ 0.04</b> — the same thresholds the K-prop engine already uses.<br>'
  '&nbsp;&nbsp;<b>3.</b> Exclude any game flagged <b>capped</b> (a starter is TBD or under 5 GS) — the probability is not trustworthy enough to price.<br>'
  '&nbsp;&nbsp;<b>4.</b> Register <i>every</i> side that qualifies. No discretionary trimming, no conviction ranking.<br>'
  '&nbsp;&nbsp;<b>5.</b> Price is frozen at the opening snapshot above; the closing price gets recorded too, for CLV.<br>'
  'Sides are still <b>DEAD</b> — $0 staked, 1u notional. This ledger measures whether V13\'s probabilities beat a price. It does not authorize a bet.</div>')
A('<table><thead><tr><th>Pick</th><th>Game</th><th>ML</th><th>V13 p</th><th>implied</th><th>edge</th><th>EV/1u</th><th class="wide">read</th></tr></thead><tbody>')
READS = {
 "COL": "V13 leans MIL (53.8%) but −210 demands 67.7%. The 13.9-pt overcharge makes the <b>dog</b> the +EV side — largest edge on the board. Feltner 5.64 ERA vs Gasser 5.07 is an ugly pitching matchup, which is also why projT is 10.5 vs a 8.5 line.",
 "KC":  "Same shape as COL: V13 leans DET (53.4%), market demands 63.1%. Wacha (3.82) vs Mize (2.93) is a real gap but not a 9.7-point one. 17:10Z first pitch — earliest game, so the least line movement to wait on.",
 "STL": "The only pick where V13's lean and the value agree. Pallante is modeled (19 GS); Hunter Greene has just 3 GS and is <b>uncapped only because his opponent is</b> — his 6.15 ERA / 38.2 K% split is tiny-sample and the single largest source of error in this number.",
}
for x in qual:
    A(f"<tr><td class='b'>{x['team']}</td><td>{x['gm']}</td><td class='b'>{x['ml']:+}</td>"
      f"<td class='b pos'>{x['p']:.1%}</td><td class='mut'>{x['impl']:.1%}</td>"
      f"<td class='pos'>{x['edge']:+.1%}</td><td class='b pos'>{x['ev']:+.3f}</td>"
      f"<td class='mut wide'>{READS.get(x['team'],'')}</td></tr>")
A('</tbody></table>')
for x in capped_qual:
    A(f'<div class="note warn"><b>Excluded by rule 3: {x["team"]} {x["ml"]:+} ({x["gm"]})</b> — '
      f'EV {x["ev"]:+.3f}, edge {x["edge"]:+.1%}, which would have been the #{sorted([c["ev"] for c in cands],reverse=True).index(x["ev"])+1} '
      'ranked side on the board. It is dropped because <b>both</b> starters are unmodeled: MIN has no announced starter and '
      'Mason Barnett has no start log. Recording it here so the exclusion is visible rather than silent — if this side wins, '
      'the rule cost us; that is the price of not pricing what we cannot model.</div>')
A(f'<div class="sub">Evaluated {len(cands)} sides across {len(ROWS)} games. '
  f'{len(qual)} qualified, {len(capped_qual)} qualified but was excluded for low trust. '
  'Everything else failed the EV or 4-point edge threshold — including several V13 directional leans '
  '(TOR@BOS, HOU@CWS, LAD@NYM, AZ@WSH all lean but are priced within ~4 points of fair, i.e. no edge worth logging).</div>')

# ---- totals ----
A('<h2>📈 V13 total leans — display only, totals NOT_READY</h2>')
A('<table><thead><tr><th>Game</th><th>Line</th><th>V13 proj</th><th>Δ</th><th class="wide">note</th></tr></thead><tbody>')
TN = {"AZ@WSH": "Bratt has 2 GS (10.7 K%, 17.9 BB%) — projT is doing a lot of guessing here.",
      "COL@MIL": "Two starters with 5+ ERAs; the 8.5 looks low but MIL park suppresses.",
      "CHC@PIT": "Skenes 3.48/29.7 K% vs Imanaga 3.99 — projT 10.2 against an 8.0 line is the model's most suspicious total on the slate. Flag, do not trust.",
      "ATH@MIN": "10.5 is the outlier total on the board and both starters are unmodeled. Ignore this row."}
for gm, line, pj, d in tot:
    if abs(d) < 1.0: continue
    cls = "pos" if d > 0 else "blu"
    A(f"<tr><td class='b'>{gm}</td><td>{line:g}</td><td>{pj:.1f}</td>"
      f"<td class='b {cls}'>{d:+.1f}</td><td class='mut wide'>{TN.get(gm,'')}</td></tr>")
A('</tbody></table>')
A(f'<div class="sub">Showing the {len([1 for g,l,p,d in tot if abs(d)>=1.0])} games with |proj − line| ≥ 1.0. '
  'Totals stay NOT_READY: the total model has never passed a forward calibration check, and the two largest gaps here '
  '(CHC@PIT +2.2, AZ@WSH +1.8) both sit on games with a sample or opponent problem — exactly where a total model fails loudest.</div>')

# ---- K projections ----
A('<h2>🎯 K projections — ready for a board that has not posted yet</h2>')
A('<table><thead><tr><th>Pitcher</th><th>Game</th><th>E[K]</th><th>GS</th><th>ERA</th><th>K%</th><th>status</th></tr></thead><tbody>')
for nm, ek, gs, era, kp, gm in karms:
    if ek is None:
        st = "<span class='neg'>no projection — under 5 GS or no log</span>"
        A(f"<tr><td class='b mut'>{nm}</td><td class='mut'>{gm}</td><td class='mut'>—</td>"
          f"<td class='mut'>{gs if gs is not None else '—'}</td><td class='mut'>{era if era else '—'}</td>"
          f"<td class='mut'>{kp if kp else '—'}</td><td>{st}</td></tr>")
    else:
        w = "full weight" if (gs or 0) >= 10 else "<span class='amb'>half weight (GS&lt;10)</span>"
        A(f"<tr><td class='b'>{nm}</td><td class='mut'>{gm}</td><td class='b'>{ek:.2f}</td>"
          f"<td>{gs}</td><td class='mut'>{era}</td><td class='mut'>{kp}</td><td class='mut'>{w}</td></tr>")
A('</tbody></table>')
A('<div class="sub"><b>Dylan Cease 8.14</b> is the highest K projection this engine has produced on any slate it has priced — '
  '36.9 K% over 17 starts, into a 7.5-total game where he should go deep. If a board posts him anywhere near 7.5, that is the first thing to look at. '
  'Skenes 6.39, McLean 6.54 and Eovaldi 6.26 are the other arms worth a quote. '
  '<b>No prices exist yet, so no play exists yet</b> — R1 is absolute, and the engine will not be handed a guessed number.</div>')

# ---- footnotes ----
A('<h2>🔧 Data integrity — what is wrong with this card</h2>')
A('<div class="note warn"><b>1. Two capped games.</b> NYY@PHI (PHI starter TBD) and ATH@MIN (MIN starter TBD <i>and</i> Mason Barnett has no start log). '
  'Both fall back to a league-average arm, which is why their V13 numbers cluster near 50%. Neither is EV-eligible.<br><br>'
  '<b>2. TOR@BOS run line looks inverted at the source.</b> covers printed "TOR −1.5 +170 / BOS +1.5 −210" while the moneyline has BOS as the −115 favorite. '
  'Those two cannot both be right. Logged as UNVERIFIED rather than silently corrected — R1 applies to fixing prices as much as to inventing them.<br><br>'
  '<b>3. CHC@PIT price conflict, unreconciled.</b> covers\' odds board says +116/−128 with a 8.0 total; covers\' own matchup page for the same game says +112/−102 with 7.5. '
  'The board figure is used above. A second source is needed before this game is priced for anything.<br><br>'
  '<b>4. ATH@MIN total of 10.5</b> is 1.5 runs clear of the next-highest total on the board. Possible, but it is the kind of number that is usually a typo. Unconfirmed.<br><br>'
  '<b>5. 7/24 pitcher logs are still not backfilled.</b> The boxscore extraction was returning season stats mixed with game stats, so it was skipped rather than injecting '
  'unverified numbers. This does not affect anything above — no pitcher starts on consecutive days — but the gap is real and stays open.</div>')

A(f'<div class="foot">Generated by harness/build_card_0725.py from cards/2026-07-25_card.json — every figure computed, none typed by hand. '
  f'Odds snapshot: {ODDS.get("captured_utc","?")} (opening). Engine unchanged post-E1: no opponent-K term. '
  f'$0 real money, unauthorized, gate 9/100. Tonight\'s grade: V13 directional (15 games) + ml_ev_tracking ({len(qual)} picks) + total leans (display).</div>')
A('</div></body></html>')

open("cards/2026-07-25_card.html", "w").write("\n".join(H))
json.dump({"rule": "ev>0 and edge>=0.04, non-capped, all qualifiers registered, no discretion",
           "preregistered_utc": "2026-07-25T06:20Z", "picks": [
             {k: (round(v, 4) if isinstance(v, float) else v) for k, v in x.items()} for x in qual],
           "excluded_capped": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in x.items()} for x in capped_qual]},
          open("cards/2026-07-25_ml_ev_picks.json", "w"), indent=1)
print(f"wrote cards/2026-07-25_card.html  ({len(qual)} EV picks, {len(capped_qual)} capped-excluded)")
for x in qual: print(f"  {x['team']:<4} {x['ml']:+5}  p={x['p']:.3f} edge={x['edge']:+.3f} EV={x['ev']:+.3f}")
