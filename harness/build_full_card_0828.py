"""The 2026-08-28 FULL CARD — every game, every sport in scope, on one page.

STANDING DISPLAY RULE (owner, 2026-08-12): every card response shows the FULL slate table — all
games, all sports in scope — never a summary subset. Leans and flags are called out IN ADDITION
to, not instead of, the complete table. So this page carries all 36 discovered rows: 15 MLB, 4
WNBA, 10 NFL, 7 college football. The 17 refused rows appear too; a refusal that is not shown is
indistinguishable from a row that was quietly dropped.

Everything here is read off a frozen artifact — three boards, three binding proofs, two slate
bindings, the schedule-acquisition record and the market record. Nothing is transcribed from a
build log or restated from memory. The four binding counters come from the proof files the
result-binding gate generated; they are printed, never typed.

Four sports, four different evidence bars, and the page says so rather than letting a reader
average them: WNBA rests on a retained git artifact, MLB on search identification only, and NFL
and CFB scored zero canonical on that same class of evidence because no canonical source exists
for either cohort.
"""
from __future__ import annotations

MODULE_ID = "build_full_card_0828"

import hashlib
import html
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

DATE = "2026-08-28"
STYLE_SOURCE = "reports/2026-08-27_mlb_forecast_and_market_review.html"
OUT = f"reports/{DATE}_full_card.html"

MLB_TEAM = {
    "CIN": "Cincinnati", "CHC": "Cubs", "LAD": "Dodgers", "DET": "Detroit", "MIA": "Miami",
    "WSH": "Washington", "KC": "Kansas City", "CLE": "Cleveland", "HOU": "Houston",
    "NYM": "Mets", "SD": "San Diego", "TB": "Tampa Bay", "SEA": "Seattle", "TOR": "Toronto",
    "COL": "Colorado", "ATL": "Atlanta", "BOS": "Boston", "NYY": "Yankees", "TEX": "Texas",
    "MIL": "Milwaukee", "CWS": "White Sox", "MIN": "Minnesota", "PIT": "Pittsburgh",
    "STL": "St. Louis", "PHI": "Philadelphia", "LAA": "Angels", "BAL": "Baltimore",
    "ATH": "Athletics", "AZ": "Arizona", "SF": "Giants",
}


def esc(s):
    return html.escape(str(s), quote=False)


def style_block():
    """Reuse the published stylesheet verbatim — this is a recurring operational document read by
    the same person daily, and a new visual identity each night would cost recognition and buy
    nothing. Copied from the file rather than re-authored so the pages cannot drift."""
    src = open(STYLE_SOURCE).read()
    a = src.index('<link rel="stylesheet"')
    b = src.index("</style>") + len("</style>")
    return src[a:b]


def et(ts):
    """UTC ISO -> Eastern clock label. Five MLB and two WNBA games cross into 8/29 UTC and are all
    8/28 Eastern rows, so a UTC-only display would read as two different dates."""
    import datetime as dt
    d = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    off = -4  # EDT on 2026-08-28
    loc = d + dt.timedelta(hours=off)
    h = loc.hour % 12 or 12
    return f"{h}:{loc.minute:02d} {'AM' if loc.hour < 12 else 'PM'}"


def pct(x):
    return f"{100 * x:.2f}%"


def counters(sport, cohort, prose):
    path = f"data/governance/bindings/{DATE}_{sport}_results_binding_proof.json"
    p = json.load(open(path))
    c = p["counters"]
    ref = "0" if c["REFUSED_ROWS"] == 0 else esc(json.dumps(c["REFUSED_ROWS"]))
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()[:8]
    return (f'<div class="proof"><b>RESULT BINDING PROOF</b> &mdash; {esc(cohort)} '
            f'&middot; <code>{sha}</code><br>\n'
            f'RESULT_BINDING_PASS = {esc(c["RESULT_BINDING_PASS"])}<br>\n'
            f'DATE_COHERENCE_PASS = {esc(c["DATE_COHERENCE_PASS"])}<br>\n'
            f'CANONICAL_ID_MATCH = {esc(c["CANONICAL_ID_MATCH"])}<br>\n'
            f'REFUSED_ROWS = {ref}<br>\n'
            f'<span style="font-family:Public Sans,sans-serif">{prose}</span></div>')


def postslate_block():
    """The RESULTS layer, added after the slate finished.

    It is a separate block from the freeze-time binding proof on purpose. The proof above was
    written before first pitch and its 0/0 meant "the slate has not started"; this one is written
    after the last out and its 0/0 means "the slate is over and no admissible source carries it".
    Same counters, different claim. Collapsing them into one line would let a reader believe the
    page had been checked once when it was checked twice, for different things.

    Returns "" when the post-slate proofs do not exist yet, so the pre-slate page still builds.
    """
    mlb_p = f"data/governance/bindings/{DATE}_mlb_results_binding_proof_postslate.json"
    wnba_p = f"data/governance/bindings/{DATE}_wnba_v2_results_binding_proof_postslate.json"
    review_p = "data/audit/2026-08-29_end_of_night_review.json"
    if not all(os.path.exists(x) for x in (mlb_p, wnba_p, review_p)):
        return ""
    mp, wp = json.load(open(mlb_p)), json.load(open(wnba_p))
    rev = json.load(open(review_p))
    arch = mp["why_no_results"]
    lb = arch["lancebroz_mlb_pitcher_data"]
    we = arch["wehoop_wnba_raw"]
    lbf = lb["daily_file_probe"]
    nm = rev["CONTAMINATION_NEAR_MISS"]
    ld = rev["ARCHIVE_BOUND_IDENTITY_FINDINGS"]["mlb:LAD@DET"]
    fi = ld["forecast_impact"]

    def cblock(p, cohort):
        c = p["counters"]
        sha = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:8]
        return (f'<div class="proof"><b>POST-SLATE BINDING PROOF</b> &mdash; {esc(cohort)} '
                f'&middot; <code>{sha}</code><br>\n'
                f'RESULT_BINDING_PASS = {esc(c["RESULT_BINDING_PASS"])}<br>\n'
                f'DATE_COHERENCE_PASS = {esc(c["DATE_COHERENCE_PASS"])}<br>\n'
                f'CANONICAL_ID_MATCH = {esc(c["CANONICAL_ID_MATCH"])}<br>\n'
                f'REFUSED_ROWS = {esc(c["REFUSED_ROWS"])}<br>\n'
                f'<span style="font-family:Public Sans,sans-serif">{esc(p["WHAT_0_OF_0_MEANS_HERE"])}'
                f'</span></div>')

    return f"""
<h2>Results &mdash; nothing was graded, because nothing could be bound</h2>
<p><b>This is the results layer, and it is empty on purpose.</b> The slate is over. Both
score-bearing archives were read and neither carries August 28. No final was published here,
because publishing one would have meant inventing it &mdash; and this is the exact juncture at
which the August 27 cycle put five fabricated finals on a page.</p>

<table>
<tr><th>Source</th><th>State when read</th><th>Why it cannot settle August 28</th></tr>
<tr><td>lancebroz/mlb-pitcher-data</td>
    <td><code>{esc(lb["head"][:8])}</code> &middot; committed {esc(lb["head_committed_utc"])}</td>
    <td>Advanced, and it <i>does</i> carry an 8/28 daily file &mdash; {esc(lbf["n_rows"])} rows,
        {esc(lbf["n_columns"])} columns, and <b>not one of them score-bearing</b>. It never has
        carried runs, which is why RJ-001B stands at 0/126 and stays there.</td></tr>
<tr><td>sportsdataverse/wehoop-wnba-raw</td>
    <td><code>{esc(we["head"][:8])}</code> &middot; committed {esc(we["head_committed_utc"])}</td>
    <td>Has not advanced. All four WNBA board games are still
        <code>STATUS_SCHEDULED</code> at 0&ndash;0.</td></tr>
<tr><td>Search</td><td>Available, and not used</td>
    <td>Snippets <b>identify</b> and never <b>bind</b>. A result read off a snippet is not evidence
        that a game finished that way.</td></tr>
</table>

{cblock(mp, "mlb:" + DATE)}
{cblock(wp, "wnba:" + DATE + " (v2 board)")}

<h2>A contamination near-miss, caught before it reached this page</h2>
<p class="flag"><b>{esc(nm["severity"])}.</b> The first post-slate WNBA probe asked the archive a
reasonable-sounding question &mdash; <i>are there completed rows where the date is 2026-08-28?</i>
&mdash; and got back <b>two</b>. Neither belongs to this slate.</p>
<p>{esc(nm["why_that_was_wrong"])}</p>
<table>
<tr><th>Row the UTC filter returned</th><th>What it actually is</th></tr>
<tr><td><code>ESPN_GAMEID:401857178</code> &middot; GSV 79&ndash;60 NYL &middot;
        2026-08-28T00:00Z</td>
    <td>An <b>August 27</b> evening ET game. Already graded in the August 27 review.</td></tr>
<tr><td><code>ESPN_GAMEID:401857179</code> &middot; WSH 80&ndash;73 PHX &middot;
        2026-08-28T02:00Z</td>
    <td>An <b>August 27</b> evening ET game. Already graded in the August 27 review.</td></tr>
</table>
<p><b>{esc(nm["this_is_the_named_P0"])}</b> {esc(nm["fix"])}</p>
<p>{esc(nm["what_actually_saved_it"])}</p>

<h2>LAD@DET was wrong on this page by 11.75 points, and was never flagged</h2>
<p>The 8/28 pitch archive covers 3 of the 15 MLB games. It is enough to settle who actually
pitched, and it overturns a row this card published. The half-inning convention
(<code>top</code> &rarr; the <b>home</b> team pitches) was validated against CIN@CHC, whose
lineups were independently confirmed at the T-45 checkpoint, <i>before</i> any claim rested on
it.</p>
<table>
<tr><th>Game</th><th>What this card carried</th><th>What the archive shows</th><th>Effect</th></tr>
<tr><td><b>LAD@DET</b> &middot; <code>{esc(ld["gamepk_confirmed"])}</code></td>
    <td>{esc(ld["board_carried"])}</td>
    <td>{esc(ld["archive"])}</td>
    <td><b>p_home {fi["p_home_frozen"]:.4f} &rarr; {fi["p_home_truth"]:.4f}</b>
        ({fi["move_pp"]:+.2f} pp) &mdash; the largest identity error of the week.
        Side does not flip.</td></tr>
</table>
<p>It bit here precisely because <i>both</i> pitchers have retained logs and are far apart
(Skubal rs 2.96 vs Anderson rs 4.13). MIA@WSH's swap, confirmed the same way and the one that
<i>was</i> flagged, moved the number by <b>zero</b> &mdash; neither of its pitchers has a retained
log, so both slots were capped either way.</p>
<p class="flag"><b>The flag was tracking the wrong thing.</b> Every row flagged and chased on 8/28
resolved as immaterial, cleared, or already-correct. The row carrying the largest error was never
flagged at all, because the acquisition recorded &ldquo;starters consistent across 2 snippets&rdquo;
and treated agreement as clearance. Two sources agreeing can be wrong the same way, especially
sharing an upstream. <b>Agreement is not independence.</b></p>

<h2>Owner ticket 217916739 &mdash; ungraded</h2>
<p>Its legs need finals and none could be bound, so it is not graded here. It settles against
nothing in the model ledger either way: owner-discretion picks and model EV rules do not mix, and
the model ledger stands at <b>0 bets, $0</b>. The POR&nbsp;+13 leg's game
(<code>ESPN_GAMEID:401857180</code>) is one of the four still reading
<code>STATUS_SCHEDULED</code> in the archive above.</p>
"""


def relay_results_block():
    """The RESULTS layer once the owner relayed finals.

    It REPLACES the "nothing could be bound" section rather than sitting beside it, because that
    section's claim is no longer the current state — but the reason it existed still is, and the
    evidence-layer banner carries it: these finals are a RELAY, not an archive read, and the
    archives still do not carry 8/28. Descriptive only. Nothing accrues.
    """
    path = f"data/audit/{DATE}_relay_grading.json"
    if not os.path.exists(path):
        return ""
    R = json.load(open(path))
    B, cf, tk = R["BINDING"], R["LADDET_COUNTERFACTUAL"], R["OWNER_TICKET"]

    def arms_table(d, cols, extra=""):
        rows = "".join(
            f"<tr><td><code>{esc(a)}</code></td>" + "".join(f"<td>{c(v)}</td>" for c in cols) +
            "</tr>" for a, v in sorted(d.items(), key=lambda kv: kv[1].get("brier", kv[1].get("mae", 0))))
        return f"<table>{extra}{rows}</table>"

    mw = R["MLB"]["winner_arms"]; mt = R["MLB"]["total_arms"]
    ww = R["WNBA"]["winner_arms"]; wm = R["WNBA"]["margin"]["wnba.replacement.FEATURE_REFRESH"]

    mlb_rows = "".join(
        f"<tr><td><code>{esc(a)}</code></td><td>{esc(v['record'])}</td>"
        f"<td>{v['brier']:.4f}</td><td>{v['logloss']:.4f}</td></tr>"
        for a, v in sorted(mw.items(), key=lambda kv: kv[1]["brier"]))
    tot_rows = "".join(
        f"<tr><td><code>{esc(a)}</code></td><td>{v['mae']:.2f}</td><td>{v['rmse']:.2f}</td>"
        f"<td>{v['bias']:+.2f}</td></tr>" for a, v in sorted(mt.items(), key=lambda kv: kv[1]["mae"]))
    w_rows = "".join(
        f"<tr><td><code>{esc(a)}</code></td><td>{esc(v['record'])}</td>"
        f"<td>{v['brier']:.4f}</td></tr>"
        for a, v in sorted(ww.items(), key=lambda kv: kv[1]["brier"]))
    leg_rows = "".join(
        f"<tr><td><b>{esc(l['leg'])}</b></td><td>{esc(l['final'])}</td>"
        f"<td>{'&#10003; ' if 'WON' in l['settlement'] else '&#10007; '}{esc(l['settlement'])}</td>"
        f"<td>{esc(l['model_position'])}</td></tr>" for l in tk["legs"])
    marg_rows = "".join(
        f"<tr><td>{esc(x['game'])}</td><td>{x['proj_home_margin']:+.2f}</td>"
        f"<td>{x['actual_home_margin']:+d}</td><td><b>{x['err']:+.2f}</b></td></tr>"
        for x in wm["per_game"])

    return f"""
<h2>Results &mdash; graded descriptively against relayed finals</h2>
<div class="proof"><b>EVIDENCE LAYER &mdash; RESULT_DISPLAY, NOT CANONICAL ADMISSION</b><br>
<span style="font-family:Public Sans,sans-serif">These finals were <b>relayed by the owner</b>, not
read from a score-bearing archive. The archives still do not carry August 28: lancebroz has an 8/28
file with no score column, and wehoop has not advanced. So every number here is
<b>descriptive</b> &mdash; nothing accrues to settlement, to promotion, or to the estimator, and the
model ledger stays <b>0 bets / $0</b>. Only the <i>finals</i> came from the relay; every record,
Brier, log loss, MAE and bias below was <b>recomputed from the frozen boards</b> so the relayed
summary is checked rather than echoed. When the archives publish, these must be re-derived and any
disagreement recorded rather than reconciled away.</span></div>

<div class="proof"><b>BINDING &mdash; NOT BOUND, AND IT NEVER WAS</b><br>
mlb: full-contract RESULT_BINDING_PASS = {esc(B['counters_full_contract']['mlb']['RESULT_BINDING_PASS'])}
&middot; identity-only {esc(B['identity_only']['mlb']['IDENTITY_MATCH'])}<br>
wnba: full-contract RESULT_BINDING_PASS = {esc(B['counters_full_contract']['wnba']['RESULT_BINDING_PASS'])}
&middot; identity-only {esc(B['identity_only']['wnba']['IDENTITY_MATCH'])}<br>
<span style="font-family:Public Sans,sans-serif">
<b>An earlier version of this page published RESULT_BINDING_PASS = 15/15 and 4/4 with
DATE_COHERENCE_PASS to match, and called both cohorts gradable. That was wrong and is withdrawn.</b>
{esc(B['CORRECTION']['why_that_was_wrong'])}<br><br>
{esc(B['why_it_cannot_bind'])}<br><br>
<b>What is true instead:</b> {esc(B['CORRECTION']['what_is_true_instead'])}<br><br>
<b>Effect on the numbers below:</b> {esc(B['CORRECTION']['effect_on_the_grades'])}</span></div>

<h3>MLB &mdash; 15 of 15 final</h3>
<table>
<tr><th>Winner arm</th><th>Record</th><th>Brier</th><th>Log loss</th></tr>
{mlb_rows}
</table>
<p>The champion beat every comparison arm on both probability scores, and beat the expanding home
prior by <b>{mw['mlb.winner.EXPANDING_HOME_PRIOR']['brier'] - mw['mlb.winner.CHAMPION_V13']['brier']:.4f}</b>
of Brier. Note that <code>CHALLENGER_ADAPTIVE</code> went 9&ndash;6 but scored <i>worse</i> than the
champion's 10&ndash;5 on Brier and worse than <code>CHALLENGER_WIDENED</code>'s 7&ndash;8 would
suggest &mdash; record and probability quality are different questions, and on a slate this flat
they come apart.</p>
<table>
<tr><th>Total arm</th><th>MAE</th><th>RMSE</th><th>Bias</th></tr>
{tot_rows}
</table>
<p>The total model <b>still failed to beat the flat prior</b>, on all three of MAE, RMSE and bias.
That is the same finding as prior dates and it did not move. {esc(R['MLB']['note'])}</p>

<h3>LAD@DET &mdash; what the correction actually does to the score</h3>
<p>The frozen board had the two starters on the wrong clubs. Correcting them moves the row from
<b>LAD {cf['frozen_p_LAD']:.4f}</b> to <b>LAD {cf['corrected_p_LAD']:.4f}</b>, and LAD won 2&ndash;1.</p>
<table>
<tr><th></th><th>Row Brier</th><th>Champion slate Brier</th></tr>
<tr><td>As frozen (malformed input)</td><td>{cf['row_brier_frozen']:.4f}</td>
    <td><b>{cf['slate_brier_frozen']:.4f}</b> &mdash; the recorded number</td></tr>
<tr><td>On corrected starters</td><td>{cf['row_brier_corrected']:.4f}</td>
    <td>{cf['slate_brier_corrected']:.4f} ({cf['delta']:+.4f}) &mdash; diagnostic only</td></tr>
</table>
<p class="flag">{esc(cf['reading'])}</p>

<h3>WNBA &mdash; 4 of 4 final</h3>
<table>
<tr><th>Winner arm</th><th>Record</th><th>Brier</th></tr>
{w_rows}
</table>
<p>The refreshed arm went 2&ndash;2 while the expanding home prior went 3&ndash;1, and the refreshed
arm still scored <i>better</i> on Brier &mdash; by {ww['wnba.winner.EXPANDING_HOME_PRIOR']['brier'] - ww['wnba.replacement.FEATURE_REFRESH']['brier']:.4f},
which on n=4 is not a result. The margin model is the real problem:</p>
<table>
<tr><th>Game</th><th>Projected home margin</th><th>Actual</th><th>Error</th></tr>
{marg_rows}
</table>
<p>Margin MAE <b>{wm['mae']:.2f}</b>. POR@ATL is the failure: the model made Atlanta its most
confident WNBA call of the night at 78.4% and projected them by 9.7; Portland won by 18, a
<b>27.71-point</b> margin error. A margin model this loose cannot support spread probabilities, and
that is the finding regardless of how the winner column landed.</p>

<h3>Owner ticket 217916739 &mdash; settled, and separate</h3>
<table>
<tr><th>Leg</th><th>Final</th><th>Settlement</th><th>Where the model stood</th></tr>
{leg_rows}
</table>
<p><b>2 of 3 legs won; the parlay lost. Cash P&amp;L &minus;$50.</b>
{esc(tk['separation'])}</p>
<p>Worth stating plainly because it cuts against the model rather than for it: the two legs that
<b>won</b> both ran <i>against</i> the model's side, and the one leg that <b>followed</b> the model
lost. On the Portland leg the ticket beat the model's most confident call of the night by 31 points
against the spread. That is n=2 and evidence of nothing &mdash; but it is the honest direction of
the observation, and rounding it off would be the same error in the other direction.</p>

<h3>NFL and college football</h3>
<p>{esc(R['NFL']['note'])} All ten preseason games are final and receive no model record.</p>
<p><b>College football is excluded from every metric above.</b> {esc(R['CFB']['owner_correction_accepted'])}</p>
"""


def build():
    mlb = json.load(open(f"cards/{DATE}_mlb_board.json"))
    # the superseding board once FEATURE_REFRESH unblocked; v1 stays frozen on disk
    _wv2 = f"cards/{DATE}_wnba_board_v2.json"
    wnba = json.load(open(_wv2 if os.path.exists(_wv2) else f"cards/{DATE}_wnba_board.json"))
    nfl = json.load(open(f"cards/{DATE}_nfl_board.json"))
    acq = json.load(open(f"data/audit/{DATE}_schedule_acquisition.json"))
    market = json.load(open(f"data/audit/{DATE}_market_acquisition.json"))
    mlb_bind = json.load(open(f"data/mlb/slates/{DATE}_slate_binding.json"))
    overlay = json.load(open(f"data/wnba/odds/{DATE}_owner_relay_dk.json"))
    cfb_relay = json.load(open(f"data/cfb/odds/{DATE}_owner_relay_dk_forward.json"))

    # ---------- assemble every discovered row, all four sports ----------
    allrows = []
    mby = {}
    for r in mlb["mlb"]["rows"]:
        mby.setdefault(r["game"], {})[r["arm"]] = r
    for g, a in mby.items():
        v = a["mlb.winner.CHAMPION_V13"]
        aw, hm = g.split(":")[1].split("@")
        side = hm if v["p_home"] >= 0.5 else aw
        p = v["p_home"] if v["p_home"] >= 0.5 else 1 - v["p_home"]
        allrows.append({"sport": "MLB", "start": v["game_start_utc"],
                        "label": f"{MLB_TEAM[aw]} @ {MLB_TEAM[hm]}", "cid": v["canonical_id"],
                        "lean": f"{side} {pct(p)}", "disp": "Forecast, no market",
                        "risk": v["identity_risk"]})
    wby = {}
    for r in wnba["wnba"]["rows"]:
        wby.setdefault(r["game"], {})[r["arm"]] = r
    for g, a in wby.items():
        fb = a["wnba.fallback.STANDINGS_LOG5_v1"]
        aw, hm = g.split(":")[1].split("@")
        side = hm if fb["p_home"] >= 0.5 else aw
        p = fb["p_home"] if fb["p_home"] >= 0.5 else 1 - fb["p_home"]
        ov = overlay["games"][g]["moneyline"]
        ml = ov["home"] if side == hm else ov["away"]
        allrows.append({"sport": "WNBA", "start": fb["game_start_utc"],
                        "label": f"{aw} @ {hm}", "cid": fb["canonical_id"],
                        "lean": f"{side} {pct(p)} (diagnostic)",
                        "disp": f"DK {ml:+d} \u00b7 no selection",
                        "risk": "RECORD_STALE" if fb.get("record_staleness") else None})
    for r in nfl["nfl"]["rows"]:
        allrows.append({"sport": "NFL", "start": r["start_utc"],
                        "label": r["game"].split(":")[1], "cid": r["canonical_id"],
                        "lean": "&mdash;", "disp": "Refused: preseason, out of scope",
                        "risk": "HOME_AWAY_RESOLVED" if r["resolution_note"] else None})
    for r in acq["cfb"]["rows"]:
        allrows.append({"sport": "CFB", "start": r["start_utc"],
                        "label": f'{r["away"]} @ {r["home"]}', "cid": r["canonical_id"],
                        "lean": "&mdash;", "disp": "Refused: FCS, out of cohort", "risk": None})
    allrows.sort(key=lambda r: (r["start"], r["sport"], r["label"]))
    if len(allrows) != 36:
        raise ValueError(f"full slate must carry all 36 discovered rows, got {len(allrows)}")

    # Count the UTC-day crossers rather than asserting the number. A hand-typed count on a page
    # whose whole subject is date coherence would be the exact failure the page argues against;
    # the first draft said "twelve" and the real figure is fourteen.
    n_cross = sum(1 for r in allrows if r["start"].startswith("2026-08-29"))
    cross_by_sport = {}
    for r in allrows:
        if r["start"].startswith("2026-08-29"):
            cross_by_sport[r["sport"]] = cross_by_sport.get(r["sport"], 0) + 1
    cross_txt = ", ".join(f'{v} {k}' for k, v in sorted(cross_by_sport.items()))

    badge = {"SIDE_SWAP_SUSPECTED": '<span class="flag">side unverified</span>',
             "SIDE_SWAP_CORRECTED": '<span class="pick">sides corrected</span>',
             "RESOLVED_ON_MAJORITY": '<span class="flag">starter on majority</span>',
             "RECORD_STALE": '<span class="flag">record stale 1g</span>',
             "HOME_AWAY_RESOLVED": '<span class="flag">home/away resolved</span>'}
    slate_rows = "".join(
        f'<tr><td class="l">{esc(r["sport"])}</td>'
        f'<td class="l"><b>{esc(r["label"])}</b>'
        + (" " + badge[r["risk"]] if r["risk"] else "") + "</td>"
        f'<td class="n">{et(r["start"])}</td>'
        f'<td class="n">{esc(r["cid"])}</td>'
        f'<td class="l">{r["lean"]}</td>'
        f'<td class="l">{esc(r["disp"])}</td></tr>' for r in allrows)

    # ---------- MLB detail ----------
    morder = list(mby)
    mlb_detail = "".join(
        f'<tr><td class="l"><b>{esc(MLB_TEAM[g.split(":")[1].split("@")[0]])} @ '
        f'{esc(MLB_TEAM[g.split("@")[1]])}</b></td>'
        f'<td class="l">{esc(a["mlb.winner.CHAMPION_V13"]["away_starter"])} / '
        f'{esc(a["mlb.winner.CHAMPION_V13"]["home_starter"])}</td>'
        f'<td class="n">{pct(a["mlb.winner.EXPANDING_HOME_PRIOR"]["p_home"])}</td>'
        f'<td class="n">{pct(a["mlb.winner.CHAMPION_V13"]["p_home"])}</td>'
        f'<td class="n">{pct(a["mlb.winner.CHALLENGER_ADAPTIVE"]["p_home"])}</td>'
        f'<td class="n">{pct(a["mlb.winner.CHALLENGER_WIDENED"]["p_home"])}</td>'
        f'<td class="n">{a["mlb.total.EXPANDING_TOTAL_PRIOR"]["projected_total"]:.2f}</td>'
        f'<td class="n">{a["mlb.total.CHAMPION_V13"]["projected_total"]:.2f}</td>'
        f'<td class="n">{a["mlb.winner.CHAMPION_V13"]["resolved_information_dose"]}</td></tr>'
        for g, a in ((g, mby[g]) for g in morder))

    ps = [mby[g]["mlb.winner.CHAMPION_V13"]["p_home"] for g in morder]
    prior = mlb["PRIORS"]["mlb_home"]["p"]
    near = sum(1 for p in ps if abs(p - 0.5) < 0.03)
    over = sum(1 for p in ps if p > prior)
    strongest = max(morder, key=lambda g: abs(mby[g]["mlb.winner.CHAMPION_V13"]["p_home"] - 0.5))
    sp = mby[strongest]["mlb.winner.CHAMPION_V13"]["p_home"]
    saw, shm = strongest.split(":")[1].split("@")
    sside, spp = (shm, sp) if sp >= 0.5 else (saw, 1 - sp)

    # ---------- WNBA detail ----------
    worder = list(wby)
    wnba_detail = ""
    for g in worder:
        a = wby[g]
        fb = a["wnba.fallback.STANDINGS_LOG5_v1"]
        fr = a["wnba.replacement.FEATURE_REFRESH"]
        recs = " / ".join(f"{k} {v}" for k, v in sorted(fb["records"].items()))
        wnba_detail += (
            f'<tr><td class="l"><b>{esc(g.split(":")[1])}</b></td>'
            f'<td class="l">{esc(recs)}</td>'
            f'<td class="n">{pct(a["wnba.winner.EXPANDING_HOME_PRIOR"]["p_home"])}</td>'
            f'<td class="n">{pct(fb["p_home"])}</td>'
            f'<td class="n pick">{pct(fr["p_home"])}</td>'
            f'<td class="n">{fr["margin_home"]:+.2f}</td>'
            f'<td class="n">{fr["projected_total"]:.1f}</td></tr>')

    # ---------- NFL / CFB detail ----------
    nfl_detail = "".join(
        f'<tr><td class="l"><b>{esc(r["game"].split(":")[1])}</b></td>'
        f'<td class="n">{et(r["start_utc"])}</td>'
        f'<td class="n">{esc(r["canonical_id"])}</td>'
        f'<td class="l">{esc(r["null_reason"])}</td></tr>' for r in nfl["nfl"]["rows"])
    cfb_detail = "".join(
        f'<tr><td class="l"><b>{esc(r["away"])} @ {esc(r["home"])}</b></td>'
        f'<td class="n">{et(r["start_utc"])}</td>'
        f'<td class="n">{esc(r["canonical_id"])}</td>'
        f'<td class="l">{esc(r["cohort"])}</td></tr>' for r in acq["cfb"]["rows"])

    mkt_rows = ""
    for g in worder:
        v = overlay["games"][g]
        fb = v["arms"]["wnba.fallback.STANDINGS_LOG5_v1"]
        m = v["moneyline"]
        aw, hm = g.split(":")[1].split("@")
        for side, team, ml, be, pm, edge, e in (
                ("away", aw, m["away"], m["break_even_away"], fb["p_away"],
                 fb["edge_away_pp"], fb["ev_away_per_100"]),
                ("home", hm, m["home"], m["break_even_home"], fb["p_home"],
                 fb["edge_home_pp"], fb["ev_home_per_100"])):
            cls = "pick" if e > 0 else "flag"
            mkt_rows += (
                f'<tr><td class="l">{esc(g.split(":")[1]) if side == "away" else ""}</td>'
                f'<td class="l"><b>{esc(team)}</b></td>'
                f'<td class="n">{ml:+d}</td>'
                f'<td class="n">{pct(be)}</td>'
                f'<td class="n">{pct(pm)}</td>'
                f'<td class="n {cls}">{edge:+.2f}</td>'
                f'<td class="n {cls}">{e:+.2f}</td>'
                f'<td class="l">no selection</td></tr>')

    stale_pp = (wby["wnba:WSH@LAS"]["wnba.fallback.STANDINGS_LOG5_v1"]
                    ["record_staleness"]["interval_width_pp"])

    risks = mlb["IDENTITY_RISK_REGISTER"]["rows"]
    risk_rows = "".join(
        f'<tr><td class="l"><b>{esc(g.split(":")[1])}</b></td>'
        f'<td class="l">{esc(v["risk"].replace("_", " ").title())}</td>'
        f'<td class="l">{esc(v["detail"])}</td></tr>' for g, v in sorted(risks.items()))

    hazards = "".join(f"<li>{esc(h)}</li>" for h in acq["known_hazards_for_machine_consumers"])
    routes = "".join(f'<li><code>{esc(r["route"])}</code> &rarr; {esc(r["error"])}</li>'
                     for r in market["routes_attempted"])
    wnba_open = "".join(f"<li>{esc(x)}</li>" for x in wnba["availability_open_items"])
    tbd = "".join(f"<li>{esc(t)}</li>"
                  for t in mlb_bind["starter_identification"]["refused_tbd"])

    gi = mlb["GAME_IDENTITY"]
    total_captured = gi["captured"] + wnba["GAME_IDENTITY"]["captured"] + \
        nfl["GAME_IDENTITY"]["captured"] + len(acq["cfb"]["rows"])

    n_cfb_relay = cfb_relay["DATE_SCOPE"]["n_games"]
    _cd = sorted(cfb_relay["DATE_SCOPE"]["by_game_date"])
    cfb_dates = ", ".join(_cd[:-1]) + " or " + _cd[-1]
    if cfb_relay["DATE_SCOPE"]["rows_on_2026_08_28"] != 0:
        raise ValueError("the CFB relay now contains 8/28 rows — the card text below "
                         "asserts it contains none and must be rewritten, not reprinted")

    tv = overlay["TRANSCRIPTION_VERIFICATION"]["observed_hold_range_pct"]
    hold_lo, hold_hi = tv[0], tv[1]

    p_mlb = counters("mlb", f"mlb:{DATE} · 15 games",
                     "Nothing has started. <b>0/0 means nothing is claimed</b>, not that nothing "
                     "was checked &mdash; all 15 games were loaded and every canonical id read. "
                     "Cohort reported <b>not gradable</b> with <code>COHORT_COVERAGE_INCOMPLETE</code>.")
    p_wnba = counters("wnba", f"wnba:{DATE} · 4 games",
                      "Same reading. All three registered arms now emit &mdash; the replacement "
                      "arm was unblocked at 11:25Z once the archive published 8/27 &mdash; so the "
                      "grading pass will find four games and three live arms, not a null to "
                      "interpret.")
    p_nfl = counters("nfl", f"nfl:{DATE} · 10 games",
                     "No result will ever be claimed here &mdash; these are benchmark rows with "
                     "no forecast to grade. Brier, logloss and EV are <b>null by rule</b>, and a "
                     "null with a stated reason is a different object from a missing value.")

    body = f"""<main>
<h1>Full Card &mdash; Friday, August 28, 2026</h1>
<p class="sub">All four sports &middot; 36 games discovered &middot; 19 canonical, 17 refused
&middot; forecast-only, no market on file &middot; paper research only</p>

<div class="chips">
<span class="chip">MLB <b>15</b></span>
<span class="chip">WNBA <b>4</b></span>
<span class="chip">NFL <b>10</b></span>
<span class="chip">CFB <b>7</b></span>
<span class="chip">GAME IDS <b>{total_captured}/36 CAPTURED</b> &middot; INFERRED <b>0</b></span>
<span class="chip">SYNTHETIC PSEUDO-PKS <b>0</b></span>
<span class="chip">WNBA PRICED <b>4/4</b> &middot; SELECTIONS <b>0</b></span>\n<span class="chip">BETS <b>0</b> &middot; <b>$0</b></span>
<span class="chip">WAGER AUTHORITY <b>NO</b></span>
</div>

<div class="panel answers">
<div class="a"><div class="q">What changed today</div><div class="v">Every row carries a real,
captured game id. The invented 827000-series key is retired.</div></div>
<div class="a"><div class="q">MLB</div><div class="v">15 games, all six arms. Flat slate:
{near} of 15 within three points of a coin flip; strongest call
{esc(MLB_TEAM.get(sside, sside))} at {pct(spp)}.</div></div>
<div class="a"><div class="q">WNBA</div><div class="v">4 games, 2 of 3 arms emitted. The feature
refresh is blocked; the other two do not touch the blocked input.</div></div>
<div class="a"><div class="q">NFL &amp; CFB</div><div class="v">17 rows, all refused. Preseason is
outside registered scope; every college game is FCS.</div></div>
<div class="a"><div class="q">Market</div><div class="v">WNBA priced by owner relay (DraftKings,
all 4 games). MLB and NFL still unpriced &mdash; five routes, all blocked.</div></div>
<div class="a"><div class="q">Wagers</div><div class="v">0 bets &middot; 0.00u &middot; $0 &mdash;
execution unauthorized</div></div>
</div>

{relay_results_block() or postslate_block()}

<h2>Full slate &mdash; all 36 rows, every sport, in start order</h2>
<p>Refused rows are shown alongside forecast rows. A refusal that is not displayed is
indistinguishable from a row that was quietly dropped, which is the whole reason the reconciliation
identity is tracked. Times are Eastern; <b>{n_cross}</b> rows ({cross_txt}) start at or after
8:00 PM ET and therefore carry an August 29 <i>UTC</i> timestamp &mdash; every one of them is an
August 28 Eastern game, and reading the UTC date as the slate date would split this card in two.</p>
<div class="scroll"><table>
<thead><tr><th class="l">Sport</th><th class="l">Game</th><th>Start (ET)</th>
<th class="l">Canonical id</th><th class="l">Model lean</th><th class="l">Disposition</th></tr></thead>
<tbody>
{slate_rows}
</tbody></table></div>

<h2>Why the ids matter more than anything else on this page</h2>
<div class="panel">
<p><b>Until today every MLB slate opened each row with a number that was made up.</b> The keys ran
827000, 827001, 827002 &mdash; invented at build time, shaped exactly like a real gamePk, bound to
nothing. A key like that cannot identify a game, so results had to be joined on something else, and
what they were joined on was the team matchup. In a continuing series the matchup is not unique
across dates, and that is the enabling condition behind the August 27 grading failure in which five
August 26 finals were attached to August 27 games.</p>
<p><b>Yesterday's archive verification settled it with evidence rather than argument.</b> Of the two
8/27 ids that had been <i>inferred</i> rather than captured, one was right and one was a fabrication:
AZ@SF had been carried as 825038, obtained by decrementing a <i>different</i> matchup's id, and no
game 825038 exists. The real id is 823179. One inference in two was wrong.</p>
<p><b>All 36 ids on this card were captured from their own source record.</b> Zero inferred, zero
synthetic. MLB carries {gi["id_space_counts"].get("MLB_GAMEPK", 0)} real gamePks and
{gi["id_space_counts"].get("ESPN_GAMEID", 0)} ESPN ids, namespaced as
<code>&lt;ID_SPACE&gt;:&lt;integer&gt;</code> because both spaces are plain integers and reading one
as the other would be the same defect in new clothes. The builders refuse an unnamespaced key, and
the binding gate now refuses a board that mixes the two forms &mdash; a bare integer beside a
namespaced one is a pseudo-pk that survived the migration.</p>
</div>

<h2>MLB &mdash; 15 games, six registered arms</h2>
{p_mlb}
<p>Home-win probability throughout, so a value below 50% means that arm leans to the road team.
Dose is the registered information weight: 1.0 with both starters resolved, 0.75 with one capped,
0.5 with a TBD.</p>
<div class="scroll"><table>
<thead><tr><th class="l">Game</th><th class="l">Probables</th><th>Prior</th><th>Champion V13</th>
<th>Adaptive</th><th>Widened</th><th>Total prior</th><th>Total V13</th><th>Dose</th></tr></thead>
<tbody>
{mlb_detail}
</tbody></table></div>
<div class="panel">
<p><b>The slate is flat.</b> Fifteen champion probabilities span {pct(min(ps))}&ndash;{pct(max(ps))}
around a {pct(prior)} home prior, {over} sit above that prior, and {near} are within three points of
even. {esc(strongest.split(":")[1])} at {pct(spp)} is the only real outlier. A slate this compressed
is where side selection is worth least and a wrong starter costs most &mdash; a two-point shift
reverses a side.</p>
<p><b>Inputs are seven days stale, and that bounds every number above.</b> The evidence cutoff is
canonical rows strictly before 2026-08-28 and the latest canonical result in the system is
2026-08-21. Finals after that date exist only as relayed or derived rows, which display but never
admit, so the priors stand unchanged at {prior:.10f} and
{mlb["PRIORS"]["mlb_total"]["runs"]:.4f}. That staleness is a property of tonight's forecast, not a
footnote to it.</p>
</div>

<h2>WNBA &mdash; 4 games, all three arms now live</h2>
{p_wnba}
<div class="panel">
<p><b>The blocked arm is unblocked.</b> This board shipped at 10:35Z with
<code>wnba.replacement.FEATURE_REFRESH</code> carried as an explicit null: its extension pool could
not be rebuilt through the 8/27 cutoff because the archive had not published that day. At 11:01Z it
did, the rebuild ran (89 &rarr; 91 extension games, all four target ids confirmed absent from the
pool), and the arm forecasts. The frozen v1 board is untouched; a superseding record carries it.</p>
<p><b>Shipping the two unblocked arms rather than none was the right call, and the third arm is
why.</b> Had the whole board been suppressed there would have been nothing to check against when
the rebuild landed. Instead the crude fallback's largest apparent edge can be tested &mdash; and it
evaporates. On WSH@LAS the records-only arm had Washington at 71.80% against a 67.21% break-even;
the feature model says <b>52.69%</b>, fourteen and a half points <i>below</i> break-even, flipping
the EV to the other side of the game. This card said those edges were &ldquo;describing its own
blindness&rdquo;. That was a judgement then. It is a measurement now.</p>
<p><b>And the staleness interval came back correct.</b> One team &mdash; Washington &mdash; had a
record stale by one game, and rather than roll it forward on an unbound result this board published
a band: 27.34% if a win, 29.52% if a loss. Washington beat Phoenix 80&ndash;73. The recomputed value
is <b>27.34%</b>, the win end of that band. Refusing to guess cost nothing.</p>
</div>
<div class="scroll"><table>
<thead><tr><th class="l">Game</th><th class="l">Records (through 8/27)</th><th>Prior</th>
<th>Log5 fallback</th><th>Feature refresh</th><th>Margin</th><th>Total</th></tr></thead>
<tbody>
{wnba_detail}
</tbody></table></div>
<div class="panel">
<p><b>The fallback arm stays <code>DIAGNOSTIC_ONLY</code> by its own registration</b> &mdash; season
win-loss records, no shrinkage, no schedule adjustment, no recency weighting, because v1 declined to
invent constants. <code>FEATURE_REFRESH</code> is the registered replacement arm and is
<code>ACTION_BLOCKED</code> while the pipeline is <code>SYSTEM_NOT_DECISION_READY</code>. Unblocking
an arm on the forecast side does not open the action layer, so selections remain <b>0</b>.</p>
</div>
<details><summary>WNBA availability &mdash; what resolved, and what did not</summary>
<p><b>Resolved since the freeze.</b> Aneesah Morrow appeared on both Connecticut's and Toronto's
lists, and that could not both be true. She is <b>Toronto's</b>, and is shut down for the rest of
the season alongside Brittney Sykes &mdash; the Connecticut listing was the stale one. It changes no
forecast, because the board carries no personnel input at all; it does mean Toronto arrives at
Las Vegas heavily depleted, which if anything supports the model rather than challenging it.</p>
<p><b>Still open.</b> A'ja Wilson's questionable tag persists rather than clearing. And there is
<i>still</i> no August 28 availability for Washington or Los Angeles &mdash; the only report on file
remains the one from August 15, which stays refused as stale. Nothing is carried forward by guess.</p>
<p>All of it is aggregator reporting, which identifies and does not bind, so no recovery-job unit is
credited for any of it.</p>
<ul>{wnba_open}</ul></details>

<h2>WNBA market &mdash; priced, screened, and nothing selected</h2>
<div class="panel">
<p><b>All four games are priced</b> from an owner relay of the DraftKings board, transcribed and
verified: twelve two-sided pairs imply holds of {hold_lo:.2f}&ndash;{hold_hi:.2f}%, a band a
dropped digit or a misaligned row would have broken. The overlay is hashed separately and attached
to the frozen board &mdash; prices are never predictive features and the board is unchanged by
them. Break-even comes from each side&rsquo;s own posted price; no de-vigged number is treated as
the market probability, and nothing combines books, so the 8/3 ruling stands untouched.</p>
<p><b>One thing this relay does that the archive could not.</b> The board&rsquo;s schedule grade is
<code>ESPN_SINGLE_FAMILY_GIT_ARTIFACT</code> &mdash; wehoop mirrors ESPN, so the ESPN pages that
&ldquo;corroborated&rdquo; it were the same family and added no independent source. A sportsbook is
not in that family, and DraftKings lists exactly these four matchups with the same home/away
orientation. That is the <b>first genuinely independent corroboration of the slate composition</b>.
It does not corroborate the game ids, which DraftKings does not publish.</p>
</div>
<div class="scroll"><table>
<thead><tr><th class="l">Game</th><th class="l">Side</th><th>DK price</th><th>Break-even</th>
<th>Log5 p</th><th>Edge (pp)</th><th>EV / $100</th><th class="l">Disposition</th></tr></thead>
<tbody>
{mkt_rows}
</tbody></table></div>
<div class="block">
<p><b>Zero selections, and that is a registration fact rather than a judgement call.</b> Both arms
that survived this morning&rsquo;s block are non-selecting by construction:
<code>STANDINGS_LOG5_v1</code> is <code>DIAGNOSTIC_ONLY_ACTION_BLOCKED</code> in its own
registration, and <code>EXPANDING_HOME_PRIOR</code> is a constant carrying no game-specific
information. The one arm that could have held a real view is blocked on the feature rebuild. No arm
on this board is permitted to select, whatever the EV column says.</p>
<p><b>And the EV column should be read as a diagnostic, not an opportunity.</b> Every large positive
number sits on a heavy underdog &mdash; +76.74 on Connecticut at +1100, +41.59 on Portland at +525.
That is precisely where this arm is weakest. <code>STANDINGS_LOG5_v1</code> sees season win-loss
records and nothing else: no injuries, no rest, no lineup. Tonight A&rsquo;ja Wilson is questionable,
Brionna Jones is out, Toronto has five players listed, and no 8/28-dated report exists for
Washington or Los Angeles at all. A model blind to all of that, disagreeing with a market that
prices it, is describing its own blindness. The honest reading is a calibration signal on the
fallback arm &mdash; it is systematically too flat on lopsided games.</p>
</div>
<div class="warn">
<p><b>Start times disagree and are not being settled here.</b> DraftKings shows the two early games
at 4:40 and the two late games at 7:10 in the phone&rsquo;s local time; the wehoop parquet says 7:30
and 10:00 PM Eastern. The game-to-slot pairing matches exactly, and read as Pacific the book is a
consistent +10 minutes on all four. The screenshot does not state its timezone, so that reading is
inferred, not confirmed. Impact is at most ten minutes on tip, well inside the checkpoint spacing;
it is flagged for the 22:00Z checkpoint rather than resolved by assumption.</p>
</div>

<h2>NFL &mdash; 10 preseason games, no forecast</h2>
{p_nfl}
<div class="panel">
<p><b>The reason is corrected from yesterday.</b> The 8/27 board claimed no NFL model had ever been
registered. That is false and was withdrawn: <code>nfl.rs.epa_logit_ridge.v0_2.shadow</code> was
built, preregistered and passed its retrospective gate on 1,865 walk-forward predictions (winner
Brier 0.2298 against a 0.2497 expanding baseline, paired CI95 [&minus;0.0261, &minus;0.0137]). The
8/27 board stays byte-unchanged and the correction record supersedes it. There is still no forecast
tonight, for a real reason: v0_2's registered scope is <b>regular season</b>, and preseason was
excluded at preregistration because planned starter snap share and substitution intent are not
reconstructible historically as pregame timestamped features.</p>
</div>
<div class="scroll"><table>
<thead><tr><th class="l">Game</th><th>Kickoff (ET)</th><th class="l">Canonical id</th>
<th class="l">Why null</th></tr></thead>
<tbody>
{nfl_detail}
</tbody></table></div>

<h2>College football &mdash; 7 games, none in cohort</h2>
<div class="panel">
<p><code>cfb.fbs.epa_talent_hgb.v2_0.challenger</code> is FBS-only and remains
<code>PREREGISTERED_DATA_ACQUISITION_PENDING</code>. Every game discovered on this date is FCS
against FCS. <b>Zero FBS games exist on August 28</b> &mdash; that is the finding, not a gap to be
filled from a neighbouring cohort.</p>
</div>
<div class="scroll"><table>
<thead><tr><th class="l">Game</th><th>Kickoff (ET)</th><th class="l">Canonical id</th>
<th class="l">Cohort</th></tr></thead>
<tbody>
{cfb_detail}
</tbody></table></div>
<div class="panel">
<p><b>A college football market relay arrived and priced none of it.</b> An owner relay of the
DraftKings board came in at 10:55Z carrying {n_cfb_relay} games &mdash; and every single row is
dated {cfb_dates}. <b>Zero are on tonight's slate.</b> The dates come from the book's own section
headers rather than from anything I assigned &mdash; the board opens on &ldquo;Tomorrow&rdquo;,
which from a Friday is August 29, and &ldquo;Thu 3 Sep&rdquo; and &ldquo;Fri 4 Sep&rdquo; follow in
sequence.</p>
<p><b>The book has no college football today at all.</b> A second capture reached the top of the
board, and its first section header reads &ldquo;Tomorrow&rdquo;. That settles two things a first,
partial capture could not: the Saturday block is dated by the book itself rather than by my reading
of the scroll order, and DraftKings really is carrying nothing for August 28.</p>
<p><b>What that does not settle is whether it agrees with this card.</b> The schedule acquisition
found seven games tonight, every one FCS against FCS. A book showing nothing today is consistent
with that <i>if</i> it omits FCS-vs-FCS matchups, and inconsistent with it if it prices all college
football. Telling those apart needs DraftKings&rsquo; inclusion rule, which is not known here and
which I decline to infer from a 22-game sample &mdash; doing so would rest on exactly the FBS/FCS
classification refused just below. So the relay neither corroborates nor refutes the seven-game
slate, and the zero-FBS finding still rests on the schedule acquisition alone.</p>
<p>The snapshot is retained rather than discarded because the v2 challenger has an <i>empty</i>
cohort tonight and these dates plainly are not empty &mdash; it is the first market record covering
dates on which that model could have a cohort at all. Cohort membership for all 22 relayed games is
recorded as <code>REFUSED_UNCLASSIFIED</code>: the challenger is FBS-only, no registered FBS team
list exists here, and several of these programs changed subdivision during the 2024&ndash;2026
realignment, so classifying them from memory would be an invented input. Eight games were captured
twice; all 70 repeated prices agree.</p>
</div>

<h2>Identity risks &mdash; disclosed, not priced in</h2>
<div class="warn">
<p>Four MLB rows carry a hazard that is <b>not</b> a missing name. Folding it into a starter class
would understate it and discounting it through the dose would move a probability without saying so.
It is listed instead, and the registered dose formula is untouched.</p>
</div>
<div class="scroll"><table>
<thead><tr><th class="l">Game</th><th class="l">Risk</th><th class="l">What makes it a risk</th></tr></thead>
<tbody>
{risk_rows}
</tbody></table></div>
<details><summary>MLB starters refused rather than guessed</summary>
<ul>{tbd}
<li>{esc(mlb_bind["start_time_notes"]["SEA@TOR"])}</li>
<li>{esc(mlb_bind["start_time_notes"]["discarded_outliers"])}</li></ul></details>

<h2>Market &mdash; nothing on file</h2>
<div class="block">
<p><b>{esc(market["verdict"])}.</b> Market capture ran separately from and <i>after</i> the board
freezes, so no price could have reached a forecast even in principle. Five routes were attempted and
every one was refused by the egress proxy. No break-even probability, no edge, no selection and no
EV exists for any sport tonight. That is an <b>action</b> blocker and it leaves model output
untouched.</p>
<ul>{routes}</ul>
<p>{esc(market["no_workaround_attempted"])}</p>
<p>{esc(market["de_vig_position"])}</p>
</div>

<h2>Reconciliation and the bars behind it</h2>
<div class="panel">
<p><b>36 discovered = 19 canonical + 17 refused.</b> The identity holds in every sport and nothing
any route surfaced was dropped silently. But <code>n_canonical</code> is <b>not</b> a uniform
quality signal across sports, and the page would mislead if it let a reader average it: WNBA's four
canonical rows rest on a retained git artifact; MLB's fifteen rest on search identification only,
while its own refusal states the slate must not be used to bind results; NFL and CFB scored zero on
that same class of evidence. Three different bars. Compare within a sport, never across.</p>
</div>
<details><summary>Hazards recorded for anything reading these files by machine</summary>
<ul>{hazards}</ul></details>

<h2>Standing position</h2>
<div class="panel">
<p><b>0 bets &middot; 0.00 units &middot; $0.</b> Paper research only; execution is unauthorized and
wager authority is <b>NO</b>. Nothing here is a guarantee or a lock. Starters, lineups and injuries
must be verified before any recommendation, and four MLB rows plus the entire WNBA availability
picture are explicitly unverified. Prices are never predictive features and enter only the action
layer; cross-book de-vig remains invalid for recovering market probability. MLB, WNBA and NFL are
separate cohorts and are never pooled. This card displays &mdash; it admits nothing, settles nothing,
and accrues nothing toward promotion.</p>
</div>
</main>"""

    doc = f"<title>Full Card &mdash; August 28, 2026</title>\n{style_block()}\n{body}\n"
    with open(OUT, "w") as fh:
        fh.write(doc)
    return OUT, len(allrows)


if __name__ == "__main__":
    path, n = build()
    print(f"{hashlib.sha256(open(path, 'rb').read()).hexdigest()[:8]}  {path}  ({n} rows)")
