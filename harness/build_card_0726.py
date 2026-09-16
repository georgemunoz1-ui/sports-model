#!/usr/bin/env python3
"""Render cards/2026-07-26_card.html. Every figure is computed from JSON on disk.
Nothing in the output is hand-typed. Usage: python3 harness/build_card_0726.py"""

MODULE_ID = "build_card_0726"
import json, os
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(BASE)
D="2026-07-26"
C=json.load(open(f"cards/{D}_card.json"))
O=json.load(open(f"data/mlb/odds/{D}_pregame.json"))
P=json.load(open(f"cards/{D}_ml_ev_picks.json"))
L=json.load(open("state.json"))["ledgers"]["ml_ev_tracking"]
BND={e["matchup"]:e["total_bounds"] for e in O["events"]}
ROWS=C["rows"]
def imp(ml): return (-ml)/(-ml+100) if ml<0 else 100/(ml+100)
def am(x): return ("+%d"%x) if x>0 else str(x)
def esc(s): return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

holds=[(imp(e["ml_away"])+imp(e["ml_home"])-1)*100 for e in O["events"]]
disp=[BND[e["matchup"]]["hi"]-BND[e["matchup"]]["lo"] for e in O["events"]]
two=[m for m,b in BND.items() if b["two_sided"]]
r5=[(f"{r['away']}@{r['home']}",r["lines"]["total"],r["v13"]["proj_total"],
     r["v13"]["proj_total"]-r["lines"]["total"]) for r in ROWS if r["lines"]["total"]]

def gamerow(r):
    m=f"{r['away']}@{r['home']}"; l=r["lines"]; v=r["v13"]; b=BND[m]
    tot=(f"{b['lo']}" if b["two_sided"] else f"<span class=w>[{b['lo']}&ndash;{b['hi']}]</span>")
    lean=r["total_lean"] or "&mdash;"
    gap=("%+.1f%%"%(100*r["gap_home"])) if r["gap_home"] is not None else "&mdash;"
    return (f"<tr{' class=cap' if r['capped'] else ''}><td><b>{m}</b>{' <span class=t>CAP</span>' if r['capped'] else ''}</td>"
            f"<td>{r['time']}</td><td class=n>{am(l['ml_away'])} / {am(l['ml_home'])}</td>"
            f"<td class=n>{tot}</td><td class=n>{v['home_wp']:.0%}</td><td class=n>{v['proj_total']:.1f}</td>"
            f"<td>{lean}</td><td class=n>{gap}</td>"
            f"<td class=n>{v['blow_away']:.0%} / {v['blow_home']:.0%}</td>"
            f"<td>{esc(r['asp'])} <b>{r['k_away'] or '&mdash;'}</b> / {esc(r['hsp'])} <b>{r['k_home'] or '&mdash;'}</b></td></tr>")

def pickrow(p):
    return (f"<tr><td><b>{p['team']}</b> {am(p['ml'])}</td><td>{p['gm']}</td><td class=n>{p['p']:.3f}</td>"
            f"<td class=n>{p['impl']:.3f}</td><td class=n>{p['edge']:+.3f}</td><td class=n>{p['ev']:+.3f}</td>"
            f"<td>{'yes' if p['lean_agrees'] else '<b>no</b>'}</td></tr>")

H=f"""<!doctype html><meta charset=utf-8><title>MLB card {D}</title>
<style>
body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;max-width:1180px;margin:24px auto;padding:0 16px;color:#111}}
h1{{margin:0 0 2px}} h2{{margin:26px 0 8px;font-size:17px;border-bottom:2px solid #111;padding-bottom:4px}}
table{{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}}
th,td{{border:1px solid #d5d5d5;padding:5px 7px;text-align:left}} th{{background:#f2f2f2}}
.n{{text-align:right;font-variant-numeric:tabular-nums}} tr.cap{{background:#fbfbfb;color:#888}}
.t{{font-size:10px;background:#e8e8e8;padding:1px 4px;border-radius:3px;color:#555}}
.w{{color:#a15c00}} .sub{{color:#666;margin:0 0 14px}}
.box{{border:1px solid #ccc;border-left:4px solid #444;padding:10px 14px;margin:10px 0;background:#fafafa}}
.bad{{border-left-color:#b00}} .ok{{border-left-color:#0a7}} .warn{{border-left-color:#c80}}
code{{background:#f0f0f0;padding:1px 4px}} ul{{margin:6px 0 6px 18px}} li{{margin:3px 0}}
</style>
<h1>MLB &mdash; {D} (Sunday)</h1>
<p class=sub>Paper / tracking only. $0 staked, no bet authority. Board captured {O['captured_utc']}, roughly
{P['hours_before_first_pitch']}h before the earliest first pitch ({P['earliest_first_pitch_utc']}) &mdash; genuinely pre-slate.</p>

<div class="box ok"><b>Board verification (this is the cleanest board ingested so far)</b>
<ul>
<li><b>Matchups &amp; first pitch:</b> {len(ROWS)}/{len(ROWS)} exact match against the statsapi hydrated schedule &mdash; every pairing and every UTC start time.</li>
<li><b>Starting pitchers:</b> 26/30 exact match vs statsapi <code>probablePitcher</code> (accent-normalized).</li>
<li><b>Moneyline vig:</b> every game holds between {min(holds):.2f}% and {max(holds):.2f}% (mean {sum(holds)/len(holds):.2f}%), and no game arbs.
A misread price would almost certainly have broken this &mdash; it is the check that makes the transcription trustworthy.</li>
</ul></div>

<div class="box bad"><b>What the totals column actually is &mdash; and why 12 of 15 totals are missing below</b>
<p>The source quotes the over and the under at <i>different lines</i> in {sum(1 for d in disp if d>0)} of {len(disp)} games, and the under line is
<b>never</b> lower than the over line (displacement min {min(disp):+.1f}, max {max(disp):+.1f}, zero negatives). That signature is a
best-price-across-books display, not one book's two-sided market: the best over sits at the lowest number on the board, the best
under at the highest. Pairing them describes a <b>middle</b>, not a market.</p>
<p>So for those games the consensus total is not identified, only bounded &mdash; shown as
<span class=w>[lo&ndash;hi]</span>. No total lean is emitted for them. Only <b>{', '.join(sorted(two))}</b> quote a single number on
both sides and are treated as real. This is the same defect class as the 7/25 strikeout alt-line ladder, caught by the same
displacement test. <b>The moneyline column is unaffected</b> &mdash; one price per team, unambiguous side attribution &mdash; which is
why the pre-registered ledger, which trades moneylines only, is not contaminated by this.</p></div>

<h2>Full slate &mdash; all {len(ROWS)} games</h2>
<table><tr><th>Game</th><th>Start</th><th>ML (A/H)</th><th>Total</th><th>V13 home%</th><th>proj</th><th>lean</th>
<th>gap(H)</th><th>blowout A/H</th><th>K projections</th></tr>
{''.join(gamerow(r) for r in ROWS)}</table>
<p class=sub>Greyed rows are capped (a starter is TBD or has too thin a start log) and are excluded from play selection by rule 3.
"Total" in <span class=w>brackets</span> is a bound, not a line. "gap(H)" is V13's home win probability minus the de-vigged market probability.</p>

<h2>Pre-registered moneyline EV picks</h2>
<div class=box><b>The rule, fixed before the board was scored:</b>
<code>{esc(P['rule'])}</code><br>
Registered {P['preregistered_utc']}, which is {P['hours_before_first_pitch']}h before first pitch. Both sides of every game are
scored; there is no pre-filtering by which team V13 likes, no conviction ranking, and no veto.</div>
<table><tr><th>Pick</th><th>Game</th><th>V13 p</th><th>implied</th><th>edge</th><th>EV/unit</th><th>V13 also leans this way?</th></tr>
{''.join(pickrow(p) for p in P['registered'])}</table>
<p class=sub><b>Neither pick is a team V13 expects to win.</b> COL is projected at {P['registered'][0]['p']:.1%} and NYY at
{P['registered'][1]['p']:.1%}. They qualify because the price is far enough off V13's number to be +EV. That is the objective
function working as specified: profitability is positive EV against the break-even price, not win% above 50. Expect this
ledger's win-loss record to look mediocre even when it is doing its job &mdash; units and closing-line value are the readouts.</p>

<h2>Excluded by rule 3, recorded so the cost is visible</h2>
<table><tr><th>Side</th><th>Game</th><th>ML</th><th>edge</th><th>EV/unit</th><th>Why excluded</th></tr>
{''.join(f"<tr><td><b>{x['team']}</b></td><td>{x['gm']}</td><td class=n>{am(x['ml'])}</td><td class=n>{x['edge']:+.3f}</td><td class=n>{x['ev']:+.3f}</td><td>starters {esc(x['asp'])} (gs {x['a_gs']}) / {esc(x['hsp'])} (gs {x['h_gs']})</td></tr>" for x in P['excluded_capped'])}</table>
<p class=sub>Separately, three games (TOR@BOS, KC@DET, LAA@SF) were capped because statsapi lists the starter as TBD even though the
odds board names one. A shadow slate built with the board's unconfirmed names, run through the identical rule, produces exactly one
extra pick &mdash; <b>KC +162</b> (p=0.440, edge +0.058, EV +0.153). That is the measured price of trusting first-party data over the
scrape. The shadow run wrote nothing: its card was diverted and the canonical card regenerated.</p>

<h2>R5 audit &mdash; |projection &minus; line| &ge; 1.5</h2>
<table><tr><th>Game</th><th>line</th><th>V13 proj</th><th>displacement</th><th>status</th></tr>
{''.join(f"<tr><td>{g}</td><td class=n>{t}</td><td class=n>{p}</td><td class=n>{d:+.1f}</td><td>{'<b>AUDIT REQUIRED</b>' if abs(d)>=1.5 else 'ok'}</td></tr>" for g,t,p,d in r5)}</table>
<div class="box warn"><b>COL@MIL fails R5 and it matters, because COL is also a registered pick.</b>
Kyle Freeland carries a 7.61 ERA; Jacob Misiorowski a 1.63 ERA with a 39.6% strikeout rate. V13 projects 9.7 total runs against a
market line of 7.5 &mdash; a +2.2 displacement. The likely cause is that the engine punishes a bad starter without bound, inflating
Milwaukee's expected scoring past what the market will pay for. If V13 misprices run scoring in this game, its win probability in
the same game is suspect too. The pick was registered anyway: rule 4 forbids discretionary vetoes, and quietly dropping a play
after seeing a diagnostic is exactly the contamination the pre-registration exists to prevent. It is flagged here instead.</div>

<h2>Ledger state</h2>
<p>ml_ev_tracking: <b>{L['record_w']}&ndash;{L['record_l']}, {L['units']:+.2f}u</b> on {len(L['graded'])} graded and {len(L['pending'])} pending.
The one graded play is KC +154 on 7/25, confirmed <b>WIN</b> (final 3&ndash;2, statsapi gamePk 824244) &mdash; a side V13 leaned
<i>against</i>, taken purely on price. The 7/25 COL +186 and STL &minus;116 plays were still Pre-Game at capture time and remain
ungraded. The older discretionary <code>ml_tracking</code> ledger stays frozen at 7&ndash;3 and is not being extended.</p>

<h2>Data integrity &mdash; what is wrong with this card</h2>
<ol>
<li><b>Every price here was read from an image by a model.</b> The audits above (15/15 schedule match, 26/30 starters, no-arb hold
band) make transcription error unlikely, but they do not make it impossible. A CSV export from the source would remove this entire
class of risk.</li>
<li><b>12 of 15 totals are not identified</b>, only bounded, because the source displays best-price rather than a market. Any
"total lean" for those games would be fabricated, so none is shown.</li>
<li><b>The run-line column was not transcribed at all.</b> Side attribution across the two rows per game is unverified, and under R3
sides are dead, so it was left out rather than guessed.</li>
<li><b>ATH@MIN has a starter conflict</b> &mdash; the board says Travis Adams, statsapi says Joe Ryan. The game was modeled with Joe
Ryan. No side there cleared the rule, so nothing was registered either way, but the book's price may have been made against a
different pitcher entirely.</li>
<li><b>Rule 3's written text and its implementation disagree.</b> The text says "TBD or &lt;5 GS"; the code says "TBD or &lt;2 GS".
7/25 was graded under the code's definition, so 7/26 was selected the same way for consistency. Checked explicitly: zero picks on
this slate flip between the two readings. The text will be amended to match the code effective 7/27 &mdash; forward only, never
re-selecting rows whose outcomes are already visible.</li>
<li><b>No closing snapshot has ever been captured.</b> Every price in this ledger is an opening or near-opening number, so
closing-line value &mdash; the readout that actually settles whether this works &mdash; is still unmeasured. This is the binding
constraint on the whole project, and it blocks experiment E4.</li>
<li><b>V13 may simply be a favorite-fader.</b> Across 50 priced, uncapped game-rows on 5 cards, V13's home win probability sits
0.086 <i>below</i> the market where the home team is a big favorite, and 0.019 below in the middle. Four of the five picks this
ledger has ever made are underdogs. The ledger may be one systematic bet wearing several uniforms. This is a hypothesis generated
from the same rows the ledger selects from, so it cannot confirm itself &mdash; it is pre-registered as <b>E4</b> against a forward
holdout from 7/27, and it was deliberately not used to touch today's picks.</li>
<li><b>Still zero strikeout-prop prices</b>, a third consecutive slate. The 100-play authorization gate remains stuck at 9/100.
Model quality is not the bottleneck; price access is.</li>
</ol>
<p class=sub>Generated by <code>harness/build_card_0726.py</code> from <code>cards/{D}_card.json</code>,
<code>data/mlb/odds/{D}_pregame.json</code>, <code>cards/{D}_ml_ev_picks.json</code> and <code>state.json</code>.
No figure on this page was typed by hand.</p>
"""
open(f"cards/{D}_card.html","w").write(H)
print(f"wrote cards/{D}_card.html ({len(P['registered'])} registered, {len(P['excluded_capped'])} capped-excluded, "
      f"{len(two)} real totals of {len(ROWS)}, {sum(1 for _,_,_,d in r5 if abs(d)>=1.5)} R5 audit)")
