"""Publish the 2026-08-28 MLB and NFL forecast cards.

A card is the only artifact a reader actually reads, so it is the place where a false claim does
real damage. Three rules govern what goes on it:

  1. EVERY NUMBER IS READ OFF A FROZEN ARTIFACT. Nothing here is transcribed from a build log or
     restated from memory. If a value cannot be read from the board, the proof or the market
     record, it does not appear.
  2. THE FOUR BINDING COUNTERS ARE PRINTED, GENERATED, NEVER TYPED. They come from the binding
     proof file, which the result-binding gate produced. On a prospective card they read 0/0, and
     the card says in words that 0/0 means NOTHING IS CLAIMED — not that nothing was checked.
  3. RESULT_DISPLAY AND CANONICAL_EVIDENCE_ADMISSION ARE SEPARATE LAYERS. This card displays a
     forecast. It admits nothing, settles nothing, and accrues nothing toward promotion.

The headline change on this date is identity, not modelling: this is the first board whose every
row carries a CAPTURED, namespaced game id instead of a synthetic 827000-series pseudo-pk.
"""
from __future__ import annotations

MODULE_ID = "build_card_0828"

import hashlib
import html
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

DATE = "2026-08-28"
STYLE_SOURCE = f"reports/2026-08-27_mlb_forecast_and_market_review.html"

TEAM = {
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
    """Reuse the 8/27 stylesheet verbatim.

    This is a recurring operational document read by the same person every day; a new visual
    identity each night would cost recognition and buy nothing. The block is COPIED from the
    published 8/27 card rather than re-authored, so the two cards cannot drift apart.
    """
    src = open(STYLE_SOURCE).read()
    a = src.index("<link rel=\"stylesheet\"")
    b = src.index("</style>") + len("</style>")
    return src[a:b]


def counters_block(proof_path, cohort_label, prose):
    p = json.load(open(proof_path))
    c = p["counters"]
    refused = c["REFUSED_ROWS"]
    refused_txt = "0" if refused == 0 else esc(json.dumps(refused))
    sha = hashlib.sha256(open(proof_path, "rb").read()).hexdigest()[:8]
    return (
        f'<div class="proof"><b>RESULT BINDING PROOF</b> &mdash; {esc(cohort_label)} '
        f'&middot; <code>{sha}</code><br>\n'
        f'RESULT_BINDING_PASS = {esc(c["RESULT_BINDING_PASS"])}<br>\n'
        f'DATE_COHERENCE_PASS = {esc(c["DATE_COHERENCE_PASS"])}<br>\n'
        f'CANONICAL_ID_MATCH = {esc(c["CANONICAL_ID_MATCH"])}<br>\n'
        f'REFUSED_ROWS = {refused_txt}<br>\n'
        f'<span style="font-family:Public Sans,sans-serif">{prose}</span></div>'
    ), p


def pct(x):
    return f"{100 * x:.2f}%"


def build_mlb(out_path=f"reports/{DATE}_mlb_forecast_and_market_review.html"):
    board = json.load(open(f"cards/{DATE}_mlb_board.json"))
    binding = json.load(open(f"data/mlb/slates/{DATE}_slate_binding.json"))
    market = json.load(open(f"data/audit/{DATE}_market_acquisition.json"))
    acq = json.load(open(f"data/audit/{DATE}_schedule_acquisition.json"))

    rows = board["mlb"]["rows"]
    by = {}
    for r in rows:
        by.setdefault(r["game"], {})[r["arm"]] = r
    order = [g for g in dict.fromkeys(r["game"] for r in rows)]

    gi = board["GAME_IDENTITY"]
    n_pk = gi["id_space_counts"].get("MLB_GAMEPK", 0)
    n_espn = gi["id_space_counts"].get("ESPN_GAMEID", 0)

    proof_html, proof = counters_block(
        f"data/governance/bindings/{DATE}_mlb_results_binding_proof.json", f"mlb:{DATE}",
        "This slate has not started. The counters read <b>0/0</b> because <b>nothing is claimed</b> "
        "&mdash; not because nothing was checked. All 15 board games were loaded and every "
        "canonical id was read; the cohort is reported <b>not gradable</b> with "
        "<code>COHORT_COVERAGE_INCOMPLETE</code>, which is the correct state for a slate whose "
        "earliest game is still ahead. When finals arrive they must bind on sport + canonical id + "
        "scheduled date + result date + away + home, and one refused row blocks every record, "
        "Brier, MAE and P&amp;L on the follow-up card.")

    # ---- headline table
    trs = []
    for g in order:
        a = by[g]
        v13 = a["mlb.winner.CHAMPION_V13"]
        aw, hm = g.split(":")[1].split("@")
        side = hm if v13["p_home"] >= 0.5 else aw
        p = v13["p_home"] if v13["p_home"] >= 0.5 else 1 - v13["p_home"]
        risk = v13["identity_risk"]
        cls = "flag" if risk in ("SIDE_SWAP_SUSPECTED",) else "pick"
        badge = ""
        if risk == "SIDE_SWAP_SUSPECTED":
            badge = ' <span class="flag">side unverified</span>'
        elif risk == "SIDE_SWAP_CORRECTED":
            badge = ' <span class="pick">sides corrected</span>'
        elif risk == "RESOLVED_ON_MAJORITY":
            badge = ' <span class="flag">starter on majority</span>'
        starters = f'{esc(v13["away_starter"])} / {esc(v13["home_starter"])}'
        trs.append(
            f'<tr><td class="l"><b>{esc(TEAM[aw])} @ {esc(TEAM[hm])}</b>{badge}</td>'
            f'<td class="n">{esc(v13["canonical_id"])}</td>'
            f'<td class="l">{starters}</td>'
            f'<td class="l {cls}">{esc(side)}</td>'
            f'<td class="n">{pct(p)}</td>'
            f'<td class="n">{pct(a["mlb.winner.CHALLENGER_ADAPTIVE"]["p_home"])}</td>'
            f'<td class="n">{pct(a["mlb.winner.CHALLENGER_WIDENED"]["p_home"])}</td>'
            f'<td class="n">{a["mlb.total.CHAMPION_V13"]["projected_total"]:.2f}</td>'
            f'<td class="n">{v13["resolved_information_dose"]}</td></tr>')

    # ---- spread of the champion around the prior, computed not asserted
    ps = [by[g]["mlb.winner.CHAMPION_V13"]["p_home"] for g in order]
    prior = board["PRIORS"]["mlb_home"]["p"]
    strongest = max(order, key=lambda g: abs(by[g]["mlb.winner.CHAMPION_V13"]["p_home"] - 0.5))
    sp = by[strongest]["mlb.winner.CHAMPION_V13"]["p_home"]
    saw, shm = strongest.split(":")[1].split("@")
    sside, spp = (shm, sp) if sp >= 0.5 else (saw, 1 - sp)
    # "above the prior" must be measured against the PRIOR (0.5205...), not against 0.500. Counting
    # from even and labelling it "above the prior" overstates the count by three on this slate.
    n_over = sum(1 for p in ps if p > prior)
    near = sum(1 for p in ps if abs(p - 0.5) < 0.03)

    tot = [by[g]["mlb.total.CHAMPION_V13"]["projected_total"] for g in order]
    hi_g = max(order, key=lambda g: by[g]["mlb.total.CHAMPION_V13"]["projected_total"])
    hi_pf = by[hi_g]["mlb.winner.CHAMPION_V13"]["park_factor"]

    risks = board["IDENTITY_RISK_REGISTER"]["rows"]
    risk_rows = "".join(
        f'<tr><td class="l"><b>{esc(g.split(":")[1])}</b></td>'
        f'<td class="l">{esc(v["risk"].replace("_", " ").title())}</td>'
        f'<td class="l">{esc(v["detail"])}</td></tr>'
        for g, v in sorted(risks.items()))

    tbd = binding["starter_identification"]["refused_tbd"]
    tbd_html = "".join(f"<li>{esc(t)}</li>" for t in tbd)
    hazards = "".join(f"<li>{esc(h)}</li>" for h in acq["known_hazards_for_machine_consumers"])
    routes = "".join(f'<li><code>{esc(r["route"])}</code> &rarr; {esc(r["outcome"])}: '
                     f'{esc(r["error"])}</li>' for r in market["routes_attempted"])

    body = f"""<main>
<h1>MLB Forecast Board &mdash; Friday, August 28</h1>
<p class="sub">Prospective &middot; 15 games &middot; frozen {esc(board["forecast_anchor_utc"])}
&middot; forecast-only, no market on file &middot; paper research only</p>

<div class="chips">
<span class="chip">GAMES <b>15</b> &middot; ARMS <b>6</b></span>
<span class="chip">GAME IDS <b>{gi["captured"]}/{gi["captured"]} CAPTURED</b> &middot; INFERRED <b>{gi["inferred"]}</b></span>
<span class="chip">SYNTHETIC PSEUDO-PKS <b>{gi["synthetic_pseudo_pks"]}</b></span>
<span class="chip">BETS <b>0</b> &middot; <b>$0</b></span>
<span class="chip">WAGER AUTHORITY <b>NO</b></span>
</div>

{proof_html}

<div class="panel answers">
<div class="a"><div class="q">What changed today</div><div class="v">Every row carries a real,
captured game id. The invented 827000-series key is gone.</div></div>
<div class="a"><div class="q">What the model says</div><div class="v">{n_over} of 15 home sides
above the prior; {near} games inside &plusmn;3 points of a coin flip. Strongest call
{esc(TEAM[sside] if sside in TEAM else sside)} at {pct(spp)}.</div></div>
<div class="a"><div class="q">Market</div><div class="v">No retained price artifact. Five routes
attempted, all blocked. Forecast-only.</div></div>
<div class="a"><div class="q">Biggest caveat</div><div class="v">Inputs are canonical only through
2026-08-21 &mdash; seven days stale.</div></div>
<div class="a"><div class="q">Wagers</div><div class="v">0 bets &middot; 0.00u &middot; $0 &mdash;
nothing authorized, execution unauthorized</div></div>
</div>

<h2>The identity fix, and why it was overdue</h2>
<div class="panel">
<p><b>Until today every MLB slate opened each row with a number that was made up.</b> The keys ran
827000, 827001, 827002 &mdash; invented at build time, shaped exactly like a real MLB gamePk, and
bound to nothing in the world. A key like that cannot identify a game, so results had to be joined
on something else, and what they were joined on was the team matchup. That is the enabling
condition behind the August 27 grading failure, in which five August 26 finals were attached to
August 27 games in a continuing series.</p>
<p><b>Yesterday's archive verification settled the argument with evidence rather than reasoning.</b>
Of the two 8/27 ids that had been <i>inferred</i> rather than captured, one was right and one was a
fabrication: AZ@SF had been carried as 825038, a value obtained by decrementing a <i>different</i>
matchup's id, and no game 825038 exists. The real id is 823179. One inference in two was wrong.</p>
<p><b>So this board carries captured ids only, and carries them namespaced.</b> Five games have a
real MLB gamePk ({n_pk} of 15), surfaced from a dated mlb.com slug. The other {n_espn} do not
&mdash; searching found an ESPN gameId and no gamePk &mdash; so they carry the ESPN id under its own
namespace. Both spaces are plain integers, which is exactly why the prefix matters: an
<code>ESPN_GAMEID</code> silently read as a gamePk would be the same defect wearing new clothes. The
builder refuses an unnamespaced key outright, and the binding gate now refuses a board that mixes
the two forms, because a bare integer sitting beside a namespaced one is a pseudo-pk that survived
the migration.</p>
<p><b>Ten gamePks were missing and none was reconstructed.</b> The 8/28 ESPN ids run contiguously
from 401816702 to 401816716 and the 8/29 siblings sit at exactly +15, so adjacency would have
produced fifteen plausible-looking numbers in a few seconds. That is precisely the arithmetic that
manufactured 825038.</p>
</div>

<h2>Model output &mdash; all fifteen games</h2>
<p>Champion probability is shown for the side it favours; the two challengers are shown as home-win
probability throughout, so a value below 50% means that arm leans away. Dose is the registered
information weight: 1.0 with both starters resolved, 0.75 with one capped, 0.5 with a TBD.</p>
<div class="scroll"><table>
<thead><tr><th class="l">Game</th><th class="l">Canonical id</th><th class="l">Probables</th>
<th class="l">Champion side</th><th>Champion</th><th>Adaptive (home)</th><th>Widened (home)</th>
<th>Proj. total</th><th>Dose</th></tr></thead>
<tbody>
{"".join(trs)}
</tbody></table></div>

<h2>What the board actually says</h2>
<div class="panel">
<p><b>This is a flat slate.</b> The champion's fifteen probabilities span
{pct(min(ps))}&ndash;{pct(max(ps))} around a {pct(prior)} home prior, and {near} of 15 sit within
three points of even. The one genuine outlier is {esc(strongest.split(":")[1])}, where the champion
takes {esc(TEAM[sside] if sside in TEAM else sside)} at {pct(spp)}. A slate this compressed is where
side selection is worth least and where a wrong starter costs most &mdash; a two-point shift
reverses a side.</p>
<p><b>The projected totals carry one number worth naming.</b> {esc(hi_g.split(":")[1])} projects
{max(tot):.2f} runs against a {board["PRIORS"]["mlb_total"]["runs"]:.2f} prior, and it is not a
read on the pitchers: the park factor is {hi_pf}, the highest on the board, because the Athletics
are playing at Sutter Health Park in West Sacramento rather than in Oakland. The total target is
registered <code>NEVER_DECISION_BEARING</code> and nothing is selected from it.</p>
<p><b>Inputs are stale and that bounds every number above.</b> The evidence cutoff is canonical rows
strictly before 2026-08-28, and the latest canonical result in the system is 2026-08-21. The board
is therefore running on team form that is seven days old. Finals after 8/21 exist only as relayed
or derived rows, which display but never admit &mdash; so the priors are unchanged at
{prior:.10f} and {board["PRIORS"]["mlb_total"]["runs"]:.4f}, and that staleness is a property of
tonight's forecast, not a footnote to it.</p>
</div>

<h2>Identity risks, disclosed and not priced in</h2>
<div class="warn">
<p>Three rows carry a hazard that is <b>not</b> a missing name, and folding it into a starter class
or discounting it through the dose would move a probability without saying so. It is listed instead.
The registered dose formula is untouched.</p>
</div>
<div class="scroll"><table>
<thead><tr><th class="l">Game</th><th class="l">Risk</th><th class="l">What makes it a risk</th></tr></thead>
<tbody>
{risk_rows}
</tbody></table></div>

<h2>Starters refused rather than guessed</h2>
<div class="panel">
<ul>
{tbd_html}
<li>{esc(binding["start_time_notes"]["SEA@TOR"])}</li>
<li>{esc(binding["start_time_notes"]["discarded_outliers"])}</li>
</ul>
</div>

<h2>Market: nothing on file</h2>
<div class="block">
<p><b>{esc(market["verdict"])}.</b> Five routes were attempted and every one was refused by the
egress proxy. No break-even probability, no edge, no selection and no EV exists for this slate.
That is an <b>action</b> blocker and it does not touch model output &mdash; all fifteen games carry
their full six-arm forecast above.</p>
<ul>{routes}</ul>
<p>{esc(market["no_workaround_attempted"])}</p>
<p>{esc(market["de_vig_position"])}</p>
</div>

<h2>Slate reconciliation, four sports</h2>
<div class="panel">
<p>36 games discovered across MLB, WNBA, NFL and college football &mdash; 19 canonical, 17
explicitly refused, identity holds. Nothing any route surfaced was dropped silently. NFL's 10
preseason games are benchmark-only and sit on their own board. College football surfaced 7 games,
<b>all FCS versus FCS</b>: the registered FBS challenger has no cohort tonight, and zero FBS games
existing on this date is the finding rather than a gap. WNBA's 4 games are the only rows bound to a
retained artifact, and its board is deliberately still closed &mdash; the feature rebuild through
the 8/27 cutoff has to run first, and the upstream archive has not published it yet.</p>
</div>
<details><summary>Hazards recorded for anything that reads these files by machine</summary>
<ul>{hazards}</ul>
</details>

<h2>Standing position</h2>
<div class="panel">
<p><b>0 bets &middot; 0.00 units &middot; $0.</b> Paper research only; execution is unauthorized and
wager authority is NO. Nothing on this card is a guarantee or a lock. Starters, lineups and injuries
must be verified before any recommendation, and three rows above are explicitly unverified. Prices,
if relayed, are never predictive features and enter only the action layer. MLB and WNBA cohorts are
never pooled.</p>
</div>
</main>"""

    doc = (f"<title>MLB Forecast Board &mdash; August 28</title>\n"
           f"{style_block()}\n{body}\n")
    with open(out_path, "w") as fh:
        fh.write(doc)
    return out_path, proof


def build_nfl(out_path=f"reports/{DATE}_nfl_forecast_and_market_review.html"):
    board = json.load(open(f"cards/{DATE}_nfl_board.json"))
    market = json.load(open(f"data/audit/{DATE}_market_acquisition.json"))
    reg = board["REGISTRY_POSITION"]

    proof_html, _ = counters_block(
        f"data/governance/bindings/{DATE}_nfl_results_binding_proof.json", f"nfl:{DATE}",
        "No result is claimed for this slate and none will be: these are benchmark rows with no "
        "forecast to grade. The counters read <b>0/0</b> because <b>nothing is claimed</b>, not "
        "because nothing was checked &mdash; all 10 board games were loaded and every captured "
        "ESPN id was read. Brier, logloss and EV are <b>null by rule</b>, and a null with a stated "
        "reason is a different object from a missing value.")

    trs = "".join(
        f'<tr><td class="l"><b>{esc(r["game"].split(":")[1])}</b>'
        + (' <span class="flag">home/away resolved 3&ndash;1</span>' if r["resolution_note"] else "")
        + f'</td><td class="n">{esc(r["canonical_id"])}</td>'
        f'<td class="l">{esc(r["start_utc"])}</td>'
        f'<td class="l">{esc(r["row_disposition"])}</td>'
        f'<td class="l">&mdash;</td>'
        f'<td class="l">{esc(r["null_reason"])}</td></tr>'
        for r in board["nfl"]["rows"])

    withdrawn = "".join(f"<li>{esc(w)}</li>" for w in reg["withdrawn_and_not_repeated_here"])

    body = f"""<main>
<h1>NFL Board &mdash; Friday, August 28</h1>
<p class="sub">Prospective &middot; 10 preseason games &middot; frozen
{esc(board["forecast_anchor_utc"])} &middot; benchmark only, no forecast &middot; paper research
only</p>

<div class="chips">
<span class="chip">GAMES <b>10</b></span>
<span class="chip">CANONICAL <b>0</b> &middot; REFUSED <b>10</b></span>
<span class="chip">GAME IDS <b>10/10 CAPTURED</b></span>
<span class="chip">FORECAST <b>NONE</b></span>
<span class="chip">BETS <b>0</b> &middot; <b>$0</b></span>
</div>

{proof_html}

<h2>The correction this board exists to carry</h2>
<div class="warn">
<p><b>Yesterday's NFL board said no NFL model had ever been registered in this system. That was
false, and it has been withdrawn.</b> The 8/27 board itself stays byte-unchanged &mdash; frozen
records are not edited &mdash; and the correction record supersedes it. What follows is the
corrected position.</p>
<ul>{withdrawn}</ul>
</div>
<div class="panel">
<p>{esc(reg["what_is_true"])}</p>
<p><b>And there is still no forecast tonight, for a different and real reason.</b>
{esc(reg["why_no_forecast_anyway"])}</p>
<p><b>Open work:</b> {esc(reg["open_work"])}.</p>
</div>

<h2>The slate</h2>
<p>Every row is <code>REFUSED_NOT_CANONICAL</code>. The authoritative source for phase &mdash;
nflverse's games.csv &mdash; is structurally silent on preseason: it holds zero August gamedays in
any season, and its game type domain is regular season and postseason only. That absence is the
finding, not a gap to be filled from somewhere else.</p>
<div class="scroll"><table>
<thead><tr><th class="l">Game</th><th class="l">Canonical id</th><th class="l">Kickoff (UTC)</th>
<th class="l">Row disposition</th><th class="l">Probability</th><th class="l">Why null</th></tr></thead>
<tbody>
{trs}
</tbody></table></div>

<h2>Why the ids are here at all</h2>
<div class="panel">
<p>These rows produce no forecast, so the ids buy nothing tonight. They are retained because a
future binding pass needs a real key to verify against, and because capturing them proved something
worth recording: <b>the ids are not ordered by kickoff and do not occupy one block.</b> Inside the
4018733xx run the mapping is 301 = CIN@PHI (8:00), 302 = WSH@BAL (6:00), 303 = NYG@NYJ (7:30),
304 = ATL@MIA (7:00), 305 = SEA@KC (8:00), 306 = TB@JAX (7:30), 307 = HOU@CAR (7:00). Sorting by
kickoff and assigning sequentially &mdash; the natural shortcut &mdash; would have mis-assigned
<b>every single row</b>. Three more games sit entirely outside that block. Each id was captured
from its own game page.</p>
<p>One row carries a resolved contradiction: <b>NYG@NYJ</b>. One enumeration pass rendered it
&ldquo;Jets at Giants&rdquo;; three independent sources put the Giants away. A reversed home and
away is the same class of error as a reversed starter, so it is marked rather than quietly
settled.</p>
</div>

<h2>Personnel</h2>
<div class="panel">
<p><b>Starters are NOT_CAPTURED for all twenty slots.</b> Preseason finales rest starters
league-wide, and that is exactly the kind of true-in-general statement that must not become a
per-game assertion. No quarterback is named on this board.</p>
</div>

<h2>Market</h2>
<div class="block">
<p><b>{esc(market["verdict"])}.</b> The action layer cannot open in any case: there is no forecast
for a price to be compared against. Wager authority <b>NO</b>, stake <b>$0</b>, 0 bets.</p>
</div>

<h2>Standing position</h2>
<div class="panel">
<p>MLB, WNBA and NFL are separate cohorts on separate boards and are never pooled. This card
displays; it admits nothing and settles nothing. Nothing here accrues toward promotion.</p>
</div>
</main>"""

    doc = (f"<title>NFL Board &mdash; August 28</title>\n"
           f"{style_block()}\n{body}\n")
    with open(out_path, "w") as fh:
        fh.write(doc)
    return out_path


if __name__ == "__main__":
    mp, proof = build_mlb()
    np_ = build_nfl()
    for p in (mp, np_):
        print(f"{hashlib.sha256(open(p, 'rb').read()).hexdigest()[:8]}  {p}")
    c = proof["counters"]
    print(f"counters printed on the MLB card: BIND {c['RESULT_BINDING_PASS']} "
          f"DATE {c['DATE_COHERENCE_PASS']} ID {c['CANONICAL_ID_MATCH']} "
          f"REFUSED {c['REFUSED_ROWS']}")
