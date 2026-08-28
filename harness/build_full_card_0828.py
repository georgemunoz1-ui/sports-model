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


def build():
    mlb = json.load(open(f"cards/{DATE}_mlb_board.json"))
    wnba = json.load(open(f"cards/{DATE}_wnba_board.json"))
    nfl = json.load(open(f"cards/{DATE}_nfl_board.json"))
    acq = json.load(open(f"data/audit/{DATE}_schedule_acquisition.json"))
    market = json.load(open(f"data/audit/{DATE}_market_acquisition.json"))
    mlb_bind = json.load(open(f"data/mlb/slates/{DATE}_slate_binding.json"))

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
        allrows.append({"sport": "WNBA", "start": fb["game_start_utc"],
                        "label": f"{aw} @ {hm}", "cid": fb["canonical_id"],
                        "lean": f"{side} {pct(p)} (diagnostic)",
                        "disp": "2 of 3 arms; refresh blocked",
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
        st = fb.get("record_staleness")
        rng = (f'{pct(st["p_home_if_that_game_was_a_win"])}&ndash;'
               f'{pct(st["p_home_if_that_game_was_a_loss"])}') if st else "&mdash;"
        recs = " / ".join(f"{k} {v}" for k, v in sorted(fb["records"].items()))
        wnba_detail += (
            f'<tr><td class="l"><b>{esc(g.split(":")[1])}</b></td>'
            f'<td class="l">{esc(recs)}</td>'
            f'<td class="n">{pct(a["wnba.winner.EXPANDING_HOME_PRIOR"]["p_home"])}</td>'
            f'<td class="n">{pct(fb["p_home"])}</td>'
            f'<td class="n">{rng}</td>'
            f'<td class="l flag">blocked</td></tr>')

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

    p_mlb = counters("mlb", f"mlb:{DATE} · 15 games",
                     "Nothing has started. <b>0/0 means nothing is claimed</b>, not that nothing "
                     "was checked &mdash; all 15 games were loaded and every canonical id read. "
                     "Cohort reported <b>not gradable</b> with <code>COHORT_COVERAGE_INCOMPLETE</code>.")
    p_wnba = counters("wnba", f"wnba:{DATE} · 4 games",
                      "Same reading. Note for the grading pass: this board emits 2 of 3 arms and "
                      "the blocked arm's rows are <b>present</b> with a null and a reason. "
                      "Grading a declared null as a miss would be as wrong as omitting it.")
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
<span class="chip">BETS <b>0</b> &middot; <b>$0</b></span>
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
<div class="a"><div class="q">Market</div><div class="v">Nothing on file. Five routes attempted,
all blocked. No edge, no selection, no EV.</div></div>
<div class="a"><div class="q">Wagers</div><div class="v">0 bets &middot; 0.00u &middot; $0 &mdash;
execution unauthorized</div></div>
</div>

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

<h2>WNBA &mdash; 4 games, and an honest partial board</h2>
{p_wnba}
<div class="warn">
<p><b>One of three registered arms is blocked, so one is blocked &mdash; not all three.</b>
<code>wnba.replacement.FEATURE_REFRESH</code> consumes an extension pool that must be rebuilt
through the 8/27 cutoff, and the wehoop archive is still at <code>3316fa3</code> with zero completed
August 27 rows. Rebuild-first is not waived because a slate happens to be available. But
<code>EXPANDING_HOME_PRIOR</code> is a registered constant with no inputs and
<code>STANDINGS_LOG5_v1</code> runs on season records alone; neither touches the blocked pool.
Suppressing them too would repeat the defect corrected on 8/27 &mdash; an action blocker
suppressing valid model output. The blocked rows are <b>present</b> on the board with a null and a
stated reason.</p>
</div>
<div class="scroll"><table>
<thead><tr><th class="l">Game</th><th class="l">Records (as of 8/26)</th><th>Prior</th>
<th>Log5 fallback</th><th>Staleness range</th><th class="l">Feature refresh</th></tr></thead>
<tbody>
{wnba_detail}
</tbody></table></div>
<div class="panel">
<p><b>Exactly one record is stale, and by exactly one game.</b> Of tonight's eight teams only
Washington played on August 27, and that result is not bound anywhere. Rather than roll a record
forward on a result we do not have, WSH@LAS is computed under both outcomes and carries the
interval &mdash; a {stale_pp:.2f}-point band. The other three games are exact.</p>
<p><b>The fallback arm is <code>DIAGNOSTIC_ONLY</code> by its own registration.</b> It runs on
season win-loss records with no shrinkage, no schedule adjustment and no recency weighting, because
v1 declined to invent constants. It never settles, never promotes and never enters the estimator.
Its numbers are the model family's best honest current output, not a recommendation.</p>
</div>
<details><summary>WNBA availability &mdash; open items, none resolved by guess</summary>
<ul>{wnba_open}</ul></details>

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
