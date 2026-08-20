"""Decision Card + Audit Appendix — the reporting-layer successor to the single technical card
(owner spec, 2026-08-19). Two surfaces from the same immutable artifacts:

  1. Decision Card  — written for a bettor. Plain English only. One row per game.
  2. Audit Appendix — probabilities, EV, hashes, gates, internal statuses.

This module READS registered artifacts and unified-card lines; it never writes to them.
A render gate refuses any decision surface that leaks internal jargon, drops a team label,
detaches a probability from its exact line, or dresses a screen up as a recommendation.
"""
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
}

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
    return (not fails), fails


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


def render_md(date, rows, banner, vintage_note):
    L = [f"# Decision Card — {date}", "", f"**{banner}**", "", vintage_note, ""]
    section = {"BET": "## Qualified bets", "WATCH": "## Watchlist",
               "PASS": "## Passes", "BLOCKED": "## Blocked / data conflicts"}
    cur = None
    for r in rows:
        if r["final_action"] != cur:
            cur = r["final_action"]
            L += [section[cur], ""]
        w = r["predicted_winner"]
        ps = r.get("projected_score")
        score = " – ".join(f"{t} {ps[t]}" for t in r["teams"]) if ps else "n/a"
        tr = r.get("best_total_read")
        total = f"{tr['side']} {tr['line']} ({tr['prob']:.1%})" if tr else "none"
        # THE FOUR-FIELD LEAD (owner rule): winner | side read | total read | action — first line, every game.
        L += [f"### {r['game']} — {r['start']}",
              f"**Predicted winner:** {w['team']} {w['win_prob']:.1%} ({w['other_team']} {w['other_prob']:.1%})"
              f" | **Best side read:** {side_read_display(r)}"
              f" | **Best total read:** {total}"
              f" | **Action: {action_display(r)}**",
              f"- Projected score: {score}",
              f"- Trust: {r['trust_label']}",
              f"- Why: {r['reason']}", ""]
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


if __name__ == "__main__":
    sys.exit(1 if selftest() else 0)
