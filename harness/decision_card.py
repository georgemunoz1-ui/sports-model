"""Decision Card + Audit Appendix — the reporting-layer successor to the single technical card
(owner spec, 2026-08-19). Two surfaces from the same immutable artifacts:

  1. Decision Card  — written for a bettor. Plain English only. One row per game.
  2. Audit Appendix — probabilities, EV, hashes, gates, internal statuses.

This module READS registered artifacts and unified-card lines; it never writes to them.
A render gate refuses any decision surface that leaks internal jargon, drops a team label,
detaches a probability from its exact line, or dresses a screen up as a recommendation.
"""

MODULE_ID = "decision_card"
import json, os, re, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FINAL_ACTIONS = ("BET", "WATCH", "PASS", "BLOCKED")
ACTION_ORDER = {a: i for i, a in enumerate(FINAL_ACTIONS)}

# Internal status -> plain English. Every status that can reach a decision row MUST have an entry;
# the render gate fails on any untranslated internal token in the decision surface.
TRANSLATE = {
    "QUALIFIED_PAPER_EDGE": "Qualified edge (paper) — passes every frozen gate",
    "PRICE_SENSITIVE": "Small paper edge — real only if this exact price is still available",
    "PRICE_SENSITIVE_WATCH": "Worth watching — modest edge at the quoted price, below the trust bar",
    "COMPRESSION_CONFLICT": "Market knows more — the market is far more confident than the model, and that pattern has beaten the model everywhere it's been tested",
    "AUDIT_REQUIRED—DIRECTION_FLIP": "Model and market disagree on the winner — an audit class that has historically lost; do not trust without review",
    "AUDIT_REQUIRED—NO_PROMOTE": "Model and market disagree on the winner — an audit class that has historically lost; do not trust without review",
    "AUDIT_REQUIRED—BOTH_SIDES_PLUS": "Both sides screened positive — impossible in a fair market, so the quotes themselves need auditing",
    "BLOCKED—STARTER_MISMATCH": "Blocked — conflicting starting-pitcher reports were never resolved",
    "BLOCKED—STARTER_MISMATCH (THREE_SOURCE_CONFLICT)": "Blocked — three sources named three different starting pitchers",
    "PRICE_DATA_BLOCKED": "Blocked — no betting prices existed when the forecast was built",
    "PERSONNEL_INCOMPLETE": "Blocked — starter or lineup information incomplete",
    "NO_VALUE": "No value at the quoted prices",
    "MARGIN_COMPRESSION_BLOCK": "Blocked — the spread model is known to understate blowouts, so an underdog spread read from it cannot be trusted",
    "ATS_DEADBAND_PASS": "Pass — the spread cushion is under the 2-point minimum; too small to act on, no rounding up",
    "ATS_DIAGNOSTIC_ONLY": "Paper tracking only — the spread model has no completed validation sample yet",
    "ATS_NO_SELECTION": "No spread read exists for this game",
    "OUT_OF_DOMAIN—NEUTRAL_SITE_HCA_UNMODELED": "Blocked permanently — this game is at a neutral site and the model applied a full home-court advantage it has not earned; the forecast is outside the model's domain",
    "BLOCKED—NO_PRICES_EXIST": "Blocked — no betting prices exist for this game yet, so nothing can be priced or acted on",
}

# Statuses that stay BLOCKED even after prices arrive (owner rule 2026-08-21).
PERMANENT_BLOCKS = ("OUT_OF_DOMAIN",)


def margin_display(team_home, team_away, margin_home):
    """Owner rule (2026-08-21): a predicted margin must name the team AND the direction in words,
    and must never be rendered in a form that reads as a betting spread. margin_home is
    (home points - away points): NEGATIVE means the HOME team is projected to LOSE. The fair home
    spread is the NEGATION, and is labeled as such."""
    if margin_home is None:
        return "no margin projected"
    if margin_home > 0:
        plain = f"{team_home} projected to win by {abs(margin_home):.2f}"
    elif margin_home < 0:
        plain = f"{team_home} projected to lose by {abs(margin_home):.2f}"
    else:
        plain = f"{team_home} and {team_away} projected level"
    return f"{plain} (fair spread {team_home} {-margin_home:+.2f})"


def delta_display(dpp, keyed=False):
    """Owner rule (2026-08-21): p_home(v2) - p_home(v1) is an OBSERVED delta containing starter
    information PLUS sequential-RNG coupling noise. It may be called a starter effect only when it
    comes from the keyed-seed reference harness."""
    if keyed:
        return f"keyed-seed reference starter effect {dpp:+.2f} points"
    return (f"observed change {dpp:+.2f} points versus the all-league-average version "
            f"(not yet separated from simulation coupling noise)")


def completeness_display(numerator, denominator, unit):
    """Owner rule (2026-08-21): print the exact numerator and denominator with the denominator
    NAMED. A bare percentage hides which denominator is in play (slots vs games)."""
    return f"{numerator} of {denominator} {unit} ({numerator / denominator * 100:.1f}% of {unit})"

# Tokens that must never appear untranslated in the bettor-facing surface.
FORBIDDEN_TOKENS = list(TRANSLATE.keys()) + [
    "PRICE_SENSITIVE", "COMPRESSION_CONFLICT", "AUDIT_REQUIRED", "BLOCKED—", "NO_VALUE",
    "PRICE_DATA_BLOCKED", "p_home", "hwp", "home_wp", "dq_flags", "cohort",
]

RECOMMENDATION_WORDS = re.compile(r"\b(bet this|play this|recommended|take (?:the )?[A-Z]|hammer|lock)\b")


def ml_screen_text(team, price, edge_pp):
    """Moneyline screen phrasing with its UNIT named (owner rule 2026-08-20: probability
    percentage points, never bare 'points' — ATS deltas are spread points and the two never
    share a sentence without units)."""
    sign = "+" if price > 0 else ""
    return (f"{team} {sign}{price} screens {edge_pp:+.1f} probability percentage points "
            f"above break-even (a screen only)")


def ats_read_text(team, line, delta_pts):
    """ATS read phrasing in SPREAD POINTS, always labeled paper."""
    sign = "+" if line > 0 else ""
    return (f"{team} {sign}{line} — registered paper spread read, cushion {delta_pts:+.2f} "
            f"spread points (tracked, never a bet)")


def final_action(governing, best_cons_edge_pp, wager_authority_yes=False):
    g = governing or ""
    if "BLOCKED" in g or "PRICE_DATA_BLOCKED" in g or g == "PERSONNEL_INCOMPLETE":
        return "BLOCKED"
    if g == "QUALIFIED_PAPER_EDGE" and wager_authority_yes:
        return "BET"
    if "AUDIT_REQUIRED" in g:
        return "WATCH"
    if g in ("PRICE_SENSITIVE", "PRICE_SENSITIVE_WATCH") and (best_cons_edge_pp or 0) >= 2.0:
        return "WATCH"
    return "PASS"


def render_gate(rows, decision_text, wager_authority_yes=False):
    """The six owner-required refusals, applied to structured rows AND the rendered text."""
    fails = []
    for r in rows:
        tag = r.get("game", "?")
        # 6. every row carries an explicit final action
        if r.get("final_action") not in FINAL_ACTIONS:
            fails.append(f"{tag}: missing or invalid final_action")
        # BET is impossible while wager authority is NO
        if r.get("final_action") == "BET" and not wager_authority_yes:
            fails.append(f"{tag}: BET emitted while wager authority is NO")
        # 1. winner must be a named team with its probability — never bare 'home'
        w = r.get("predicted_winner") or {}
        if not w.get("team") or w.get("team", "").lower() in ("home", "away"):
            fails.append(f"{tag}: predicted winner is not a named team")
        if w.get("win_prob") is None:
            fails.append(f"{tag}: winner probability missing")
        # 2. projected score must be labeled by team
        ps = r.get("projected_score")
        if ps is not None:
            teams = set(r.get("teams") or [])
            if set(ps.keys()) != teams or len(teams) != 2:
                fails.append(f"{tag}: projected score lacks proper team labels")
        # 3. any O/U probability must carry its exact line
        tr = r.get("best_total_read")
        if tr is not None:
            if tr.get("line") is None or tr.get("prob") is None or tr.get("side") not in ("Over", "Under"):
                fails.append(f"{tag}: total read lacks side, exact line, or probability")
        # 4. a screened price is a screen, not a recommendation
        pr = r.get("best_price_read")
        if pr is not None:
            if pr.get("kind") != "screen":
                fails.append(f"{tag}: price read not marked as a screen")
            if RECOMMENDATION_WORDS.search(pr.get("text", "")):
                fails.append(f"{tag}: screened price phrased as a recommendation")
        # 5. plain-English label present, no internal token as the label
        lbl = r.get("trust_label") or ""
        if not lbl:
            fails.append(f"{tag}: missing plain-English trust label")
        if any(t in lbl for t in TRANSLATE):
            fails.append(f"{tag}: internal status used as the trust label")
        # 8. OUT_OF_DOMAIN is a PERMANENT block (owner rule 2026-08-21): it must force BLOCKED
        # and must not become actionable when prices arrive.
        gov = r.get("governing_status") or ""
        if any(p in gov for p in PERMANENT_BLOCKS) and r.get("final_action") != "BLOCKED":
            fails.append(f"{tag}: {gov} must force final_action BLOCKED, permanently")
        # 9. a displayed margin must name team + direction in words and must not read as a spread
        md = r.get("margin_text")
        if md is not None:
            if "projected to" not in md and "projected level" not in md:
                fails.append(f"{tag}: margin shown without naming the team and direction in words")
            if "fair spread" not in md:
                fails.append(f"{tag}: margin shown without its explicitly labeled fair spread")
        # 12. STARTER DISPLAY (owner rule 2026-08-23). "The Decision Card should render
        #     'Jobe — CAP profile', not merely 'Jobe'." A slot whose FEATURE PROFILE is the
        #     league-average CAP must say so wherever its name appears: 42 slots across the card
        #     history printed a pitcher's name while feeding CAP stats, and every reader took the
        #     name as information.
        for side in ("away_starter", "home_starter"):
            sl = r.get(side)
            if not isinstance(sl, dict):
                continue
            disp, prof, txt = sl.get("displayed_starter"), sl.get("feature_profile"), sl.get("text")
            if prof is None or txt is None:
                fails.append(f"{tag}: {side} carries no feature_profile/text — displayed identity "
                             f"and the profile that entered the model must both be stated")
                continue
            if prof == "LEAGUE_AVERAGE_CAP" and "CAP profile" not in txt:
                fails.append(f"{tag}: {side} renders {txt!r} for a LEAGUE_AVERAGE_CAP slot — a "
                             f"name without its profile reads as starter information it is not")
            if prof == "PITCHER_SPECIFIC_THIN" and "thin profile" not in txt:
                fails.append(f"{tag}: {side} renders a thin profile as a settled one")
            if disp and txt == disp and prof != "PITCHER_SPECIFIC":
                fails.append(f"{tag}: {side} renders the bare name {disp!r} for a {prof} slot")
            if decision_text and txt not in decision_text:
                fails.append(f"{tag}: {side} rendered text {txt!r} does not appear on the card")
        # 13. an ALL_CAP_BASELINE row is a baseline cohort and can never be an action
        if r.get("information_class") == "ALL_CAP_BASELINE":
            if r.get("final_action") == "BET":
                fails.append(f"{tag}: BET emitted on an ALL_CAP_BASELINE row (ACTION_AUTHORITY=NONE)")
            if decision_text and "ALL_CAP_BASELINE — ACTION_AUTHORITY = NONE" not in decision_text:
                fails.append(f"{tag}: an ALL_CAP_BASELINE row rendered without the baseline banner")
        # 10. a v1->v2 delta may only be called a starter effect if keyed-seed sourced
        dt = r.get("delta_text")
        if dt is not None and "starter effect" in dt and "keyed-seed" not in dt:
            fails.append(f"{tag}: observed delta labeled a causal 'starter effect' without the keyed-seed reference")
        # 7. four-field lead (owner rule 2026-08-20): winner | side read | total read | action,
        # with every non-BET action rendered as an explicit NO BET
        if decision_text and r.get("final_action") in FINAL_ACTIONS:
            if f"**Action: {action_display(r)}**" not in decision_text:
                fails.append(f"{tag}: four-field lead missing or action not rendered as "
                             f"'{action_display(r)}'")
    # text-level checks on the bettor surface
    if re.search(r"\bhome win\b", decision_text, re.I):
        fails.append("decision text says 'home win' without naming the team")
    for tok in FORBIDDEN_TOKENS:
        if tok in decision_text:
            fails.append(f"decision text leaks internal token: {tok}")
    # 11. completeness percentages must name their denominator (owner rule 2026-08-21)
    import re as _re
    for m in _re.finditer(r"(\d{1,3}(?:\.\d)?)% resolved", decision_text):
        fails.append(f"completeness percentage '{m.group(0)}' printed without a named denominator "
                     f"- use completeness_display(numerator, denominator, unit)")
    return (not fails), fails


def starter_fragment(name, stats):
    """The three facts a Decision Card row must carry for one starter slot: what is DISPLAYED,
    whether that identity is verified, and what PROFILE actually entered the model."""
    import information_class as IC
    disp, ident, prof = IC.slot_identity(name, stats)
    return {"displayed_starter": disp, "identity_status": ident, "feature_profile": prof,
            "text": IC.render_slot(name, stats)}


def sort_rows(rows):
    return sorted(rows, key=lambda r: (ACTION_ORDER[r["final_action"]],
                                       -(r.get("sort_edge") or -99)))


def action_display(r):
    """Owner rule (2026-08-20): a theoretical screen must never read as a recommendation, so
    every non-BET action is rendered as an explicit NO BET with its flavor."""
    fa = r["final_action"]
    if fa == "BET":
        return "BET (qualified)"
    return {"WATCH": "NO BET — watch only", "PASS": "NO BET — pass",
            "BLOCKED": "NO BET — blocked"}[fa]


def side_read_display(r):
    """Best side/spread read, labeled a screen; if the screened team opposes the model winner,
    say CONFLICTING READ explicitly (opposite teams are not a contradiction — one answers 'who
    wins', the other 'which price looks cheap')."""
    pr = r.get("best_price_read")
    if not pr:
        return "none"
    txt = pr["text"]
    st = pr.get("team")
    if st and st != r["predicted_winner"]["team"]:
        txt = f"CONFLICTING READ — {txt} (opposite the model's pick)"
    return txt


def fair_number_display(row):
    """The FAIR NUMBER column (owner card spec 2026-08-22): what the model itself says the line
    should be. For a margin-bearing sport that is the negated predicted home margin; for a
    moneyline-only row it is the model's fair price expressed as a probability. Never a spread
    lifted from a book."""
    if row.get("fair_number") is not None:
        return row["fair_number"]
    mh = row.get("margin_home")
    if mh is not None:
        h = row["teams"][1]
        return f"{h} {-mh:+.2f}"
    w = row.get("predicted_winner") or {}
    if w.get("win_prob") is not None:
        return f"{w['team']} {w['win_prob']:.1%} fair"
    return "none"


def market_number_display(row):
    """The MARKET NUMBER column. Null-with-reason is a first-class value here: a blank market
    column has always meant 'no price was captured', and that must stay visible rather than being
    silently rendered as an empty cell."""
    m = row.get("market_number")
    if m:
        return m
    return f"none — {row.get('market_null_reason', 'no price captured')}"


FIVE_FIELD_HEADER = "| Game | Model prediction | Fair number | Market number | Action |"


def render_md(date, rows, banner, vintage_note):
    """FIVE-FIELD CARD (owner spec 2026-08-22): the bettor surface leads with exactly
    Game | Model prediction | Fair number | Market number | Action.
    Everything else - Brier components, CAP attribution, evidence hashes, governance tokens -
    moves to the audit appendix. The controls are NOT weakened: render_gate still runs over the
    full structured rows, so a row missing a team label, a line-bound total, or a final action
    still refuses to render even though those fields no longer appear in the lead table."""
    L = [f"# Decision Card — {date}", "", f"**{banner}**", "", vintage_note, ""]
    section = {"BET": "## Qualified bets", "WATCH": "## Watchlist",
               "PASS": "## Passes", "BLOCKED": "## Blocked / data conflicts"}
    cur = None
    for r in rows:
        if r["final_action"] != cur:
            cur = r["final_action"]
            L += [section[cur], "", FIVE_FIELD_HEADER, "|---|---|---|---|---|"]
        w = r["predicted_winner"]
        pred = f"{w['team']} {w['win_prob']:.1%} ({w['other_team']} {w['other_prob']:.1%})"
        L.append(f"| **{r['game']}** {r['start']} | {pred} | {fair_number_display(r)} "
                 f"| {market_number_display(r)} | **{action_display(r)}** |")
    L += ["", "*Reasons, trust labels, projected scores, starter states, deltas and all governance "
          "detail are in the audit appendix — the controls still run over every row.*", ""]
    for r in rows:
        L.append(f"- **{r['game']}** — {r['trust_label']} — {r['reason']}")
    return "\n".join(L)


def selftest():
    fails = []
    ok_row = {
        "game": "A@B", "teams": ["A", "B"], "start": "22:40Z",
        "predicted_winner": {"team": "B", "win_prob": .55, "other_team": "A", "other_prob": .45},
        "projected_score": {"A": 4.1, "B": 4.9},
        "best_price_read": {"kind": "screen", "text": "A +130 screens +3.4 points above break-even"},
        "best_total_read": {"side": "Under", "line": 8.5, "prob": .64},
        "trust_label": "Worth watching — modest edge at the quoted price, below the trust bar",
        "final_action": "WATCH", "reason": "test", "sort_edge": 2.9}
    CLEAN = "clean text **Action: NO BET — watch only** more text"
    ok, f = render_gate([ok_row], CLEAN, False)
    if not ok:
        fails.append(f"gate rejected a valid row: {f}")
    if render_gate([ok_row], "text with no four-field action lead", False)[0]:
        fails.append("gate passed a decision text missing the NO BET action rendering")
    # owner rules 2026-08-21
    if render_gate([ok_row], CLEAN + " starters 80.0% resolved", False)[0]:
        fails.append("gate passed a completeness percentage with no named denominator")
    perm = dict(ok_row, governing_status="OUT_OF_DOMAIN—NEUTRAL_SITE_HCA_UNMODELED", final_action="PASS")
    if render_gate([perm], CLEAN.replace("watch only", "pass"), False)[0]:
        fails.append("gate let an OUT_OF_DOMAIN row escape a permanent BLOCK")
    bad_margin = dict(ok_row, margin_text="B -7.23")
    if render_gate([bad_margin], CLEAN, False)[0]:
        fails.append("gate passed a bare margin that reads as a betting spread")
    good_margin = dict(ok_row, margin_text=margin_display("B", "A", -7.23))
    if not render_gate([good_margin], CLEAN, False)[0]:
        fails.append("gate rejected a correctly worded margin display")
    if "lose by 7.23" not in margin_display("B", "A", -7.23) or "fair spread B +7.23" not in margin_display("B", "A", -7.23):
        fails.append(f"margin_display wrong: {margin_display('B','A',-7.23)}")
    # OWNER RULE 2026-08-23: displayed identity vs the profile that entered the model.
    CAP = {"era": 4.20, "gs": 0, "k": 22.0, "bb": 8.5}
    REAL = {"era": 3.11, "gs": 20, "k": 16.2, "bb": 5.9}
    THIN = {"era": 2.00, "gs": 1, "k": 18.0, "bb": 4.0}
    jobe = starter_fragment("Jackson Jobe", CAP)
    if jobe["text"] != "Jackson Jobe — CAP profile":
        fails.append(f"starter_fragment rendered {jobe['text']!r} for a named CAP slot")
    if jobe["identity_status"] != "NAMED_UNVERIFIED" or jobe["feature_profile"] != "LEAGUE_AVERAGE_CAP":
        fails.append(f"starter_fragment mislabeled the Jobe case: {jobe}")
    capped_row = dict(ok_row, away_starter=jobe, home_starter=starter_fragment("McGreevy", REAL))
    TXT = CLEAN + " Jackson Jobe — CAP profile / McGreevy"
    if not render_gate([capped_row], TXT, False)[0]:
        fails.append(f"gate rejected a correctly rendered CAP slot: {render_gate([capped_row], TXT, False)[1]}")
    # THE DEFECT: the bare name
    bare = dict(capped_row, away_starter=dict(jobe, text="Jackson Jobe"))
    if render_gate([bare], CLEAN + " Jackson Jobe / McGreevy", False)[0]:
        fails.append("gate passed a bare pitcher name for a LEAGUE_AVERAGE_CAP slot")
    # ISOLATION. The bare-name rule and the CAP-profile rule overlap on the fixture above, so each
    # needs a case only IT can catch (lesson 24: a fixture exercising two rules proves the stricter
    # one and decorates the other).
    dressed = dict(capped_row, away_starter=dict(jobe, text="Jackson Jobe (probable)"))
    if render_gate([dressed], CLEAN + " Jackson Jobe (probable) / McGreevy", False)[0]:
        fails.append("gate passed a decorated name that still never states the CAP profile — only "
                     "the CAP-profile rule can catch this")
    unread = dict(capped_row, away_starter={"displayed_starter": "Ghost",
                                            "identity_status": "NAMED_UNVERIFIED",
                                            "feature_profile": "UNREADABLE", "text": "Ghost"})
    if render_gate([unread], CLEAN + " Ghost / McGreevy", False)[0]:
        fails.append("gate passed a bare name on an UNREADABLE-profile slot — only the bare-name "
                     "rule can catch this")
    # a slot that states no profile at all
    noprof = dict(capped_row, away_starter={"displayed_starter": "Jackson Jobe"})
    if render_gate([noprof], TXT, False)[0]:
        fails.append("gate passed a starter slot carrying no feature_profile")
    # a thin profile dressed as a settled one
    thin_bad = dict(capped_row,
                    away_starter=dict(starter_fragment("Rookie", THIN), text="Rookie (spot start)"))
    if render_gate([thin_bad], CLEAN + " Rookie (spot start) / McGreevy", False)[0]:
        fails.append("gate passed a thin profile rendered as a settled one")
    # the rendered text must actually reach the card
    if render_gate([capped_row], CLEAN + " McGreevy", False)[0]:
        fails.append("gate passed a row whose starter text never appears on the card")
    # an ALL_CAP_BASELINE row can never be an action and must carry the banner
    BAN = "ALL_CAP_BASELINE — ACTION_AUTHORITY = NONE"
    base_row = dict(capped_row, information_class="ALL_CAP_BASELINE")
    if render_gate([base_row], TXT, False)[0]:
        fails.append("gate passed an ALL_CAP_BASELINE row with no baseline banner on the card")
    if not render_gate([base_row], TXT + " " + BAN, False)[0]:
        fails.append(f"gate rejected a correctly bannered baseline row: "
                     f"{render_gate([base_row], TXT + ' ' + BAN, False)[1]}")
    bet_base = dict(base_row, final_action="BET")
    if render_gate([bet_base], TXT + " " + BAN + " **Action: BET (qualified)**", True)[0]:
        fails.append("gate passed a BET on an ALL_CAP_BASELINE row")
    bad_delta = dict(ok_row, delta_text="starter effect +8.10 points")
    if render_gate([bad_delta], CLEAN, False)[0]:
        fails.append("gate passed an observed delta labeled a causal starter effect")
    ok_delta = dict(ok_row, delta_text=delta_display(8.10))
    if not render_gate([ok_delta], CLEAN, False)[0]:
        fails.append("gate rejected a correctly labeled observed delta")
    if completeness_display(26, 30, "starter slots") != "26 of 30 starter slots (86.7% of starter slots)":
        fails.append(f"completeness_display wrong: {completeness_display(26,30,'starter slots')}")
    # five-field card fixtures (owner spec 2026-08-21/22)
    if fair_number_display({"teams": ["A", "B"], "margin_home": -7.23}) != "B +7.23":
        fails.append("fair number must be the NEGATED home margin")
    if fair_number_display({"teams": ["A", "B"], "margin_home": 3.55}) != "B -3.55":
        fails.append("fair number sign wrong for a home favorite")
    mn = market_number_display({"market_number": None, "market_null_reason": "no prices acquired"})
    if "none" not in mn or "no prices acquired" not in mn:
        fails.append("a missing market number must render null-WITH-REASON, not blank")
    md = render_md("2026-01-01", [ok_row], "b", "v")
    if FIVE_FIELD_HEADER not in md:
        fails.append("five-field header missing from the rendered card")
    for leaked in ("Projected score:", "Best side read:"):
        if leaked in md:
            fails.append(f"lead table still carries a demoted field: {leaked}")
    if "test" not in md:
        fails.append("reason dropped entirely — it must move to the appendix, not vanish")
    bad = dict(ok_row); bad["predicted_winner"] = {"team": "home", "win_prob": .55,
                                                  "other_team": "A", "other_prob": .45}
    if render_gate([bad], "clean", False)[0]:
        fails.append("gate passed a bare 'home' winner")
    bad = dict(ok_row); bad["projected_score"] = {"home": 4.1, "away": 4.9}
    if render_gate([bad], "clean", False)[0]:
        fails.append("gate passed an unlabeled projected score")
    bad = dict(ok_row); bad["best_total_read"] = {"side": "Under", "line": None, "prob": .64}
    if render_gate([bad], "clean", False)[0]:
        fails.append("gate passed a total probability without its exact line")
    bad = dict(ok_row); bad["best_price_read"] = {"kind": "screen", "text": "bet this now"}
    if render_gate([bad], "clean", False)[0]:
        fails.append("gate passed a screen phrased as a recommendation")
    bad = dict(ok_row); bad["trust_label"] = "PRICE_SENSITIVE"
    if render_gate([bad], "clean", False)[0]:
        fails.append("gate passed an internal status as the trust label")
    bad = dict(ok_row); bad.pop("final_action")
    if render_gate([bad], "clean", False)[0]:
        fails.append("gate passed a row with no final action")
    bad = dict(ok_row); bad["final_action"] = "BET"
    if render_gate([bad], "clean", False)[0]:
        fails.append("gate passed BET while wager authority is NO")
    if render_gate([ok_row], "the home win probability is", False)[0]:
        fails.append("gate passed 'home win' in decision text")
    if render_gate([ok_row], "status: COMPRESSION_CONFLICT", False)[0]:
        fails.append("gate passed a leaked internal token in decision text")
    print("decision_card selftest:", "PASS" if not fails else f"FAIL {fails}")
    return fails


MUTANTS = [
    ("a LEAGUE_AVERAGE_CAP slot may render without stating its profile",
     '            if prof == "LEAGUE_AVERAGE_CAP" and "CAP profile" not in txt:', "            if False:"),
    ("a bare pitcher name is accepted for any profile",
     '            if disp and txt == disp and prof != "PITCHER_SPECIFIC":', "            if False:"),
    ("a thin profile may render as a settled one",
     '            if prof == "PITCHER_SPECIFIC_THIN" and "thin profile" not in txt:', "            if False:"),
    ("a starter slot may omit its feature_profile entirely",
     "            if prof is None or txt is None:", "            if prof is None and False:"),
    ("the rendered starter text need not appear on the card",
     "            if decision_text and txt not in decision_text:", "            if False:"),
    ("BET permitted on an ALL_CAP_BASELINE row",
     '            if r.get("final_action") == "BET":', "            if False:"),
    ("an ALL_CAP_BASELINE row may render without the baseline banner",
     '            if decision_text and "ALL_CAP_BASELINE — ACTION_AUTHORITY = NONE" not in decision_text:',
     "            if False:"),
    ("starter_fragment reports the displayed name as a verified profile",
     "    disp, ident, prof = IC.slot_identity(name, stats)",
     "    disp, ident, prof = IC.slot_identity(name, stats); prof = 'PITCHER_SPECIFIC'"),
]


def mutation_suite(verbose=True):
    import subprocess as _sp, tempfile as _tf
    src = open(os.path.abspath(__file__)).read()
    i = src.index("MUTANTS = [")
    j = src.index("\ndef mutation_suite", i)
    head, block, tail = src[:i], src[i:j], src[j:]
    surv, unapp = [], []
    for name, old, new in MUTANTS:
        where = "head" if old in head else ("tail" if old in tail else None)
        if where is None:
            unapp.append(f"{name}: pattern not found"); continue
        mut = (head.replace(old, new, 1) + block + tail) if where == "head" \
            else (head + block + tail.replace(old, new, 1))
        if mut == src:
            unapp.append(f"{name}: no-op"); continue
        with _tf.NamedTemporaryFile("w", suffix="_mutant.py", delete=False,
                                    dir=os.path.dirname(os.path.abspath(__file__))) as fh:
            fh.write(mut); path = fh.name
        try:
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True, timeout=120)
            killed = pr.returncode != 0
        except _sp.TimeoutExpired:
            killed = True
        finally:
            os.unlink(path)
        if verbose:
            print(f"  {'KILLED  ' if killed else 'SURVIVED'}  {name}")
        if not killed:
            surv.append(name)
    for u in unapp:
        print(f"  UNAPPLIED  {u}")
    print(f"mutation suite: {len(MUTANTS)-len(surv)-len(unapp)}/{len(MUTANTS)} killed"
          f"{'' if not (surv or unapp) else '  — SURVIVORS MEAN DECORATIVE FIXTURES'}")
    return surv + unapp


if __name__ == "__main__":
    if "--mutants" in sys.argv:
        sys.exit(1 if mutation_suite() else 0)
    sys.exit(1 if selftest() else 0)
