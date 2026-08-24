"""DECISION_VIEW — one row per game, and the decision before the evidence.

THE DEFECT THIS FIXES IS NOT ARITHMETIC. Every number on the 2026-08-24 board was right and the
page still failed its reader. It opened with what I had got wrong, then forecasts, then prices, then
a twenty-row two-sided EV table, and somewhere past all of that a reader could work out that the
answer was "bet nothing". The correction history is real evidence and it belongs in an appendix; a
person opening the page needs today's decision first.

FOUR QUESTIONS, DELIBERATELY SEPARATED. Conflating them is how a model talks itself into twelve
wagers because twelve games exist:

  PROJECTED_WINNER   who is most likely to win. A probability statement. Says nothing about price.
  BEST_VALUE_SIDE    the best price-relative opportunity. Often the OTHER team — WSH is the
                     projected winner at 56.66% and COL +169 is the better side, because the market
                     is charging more for WSH than the model thinks it is worth.
  ACTUAL_ACTION      what to do. BET, PASS or BLOCKED. This is the only column that authorizes
                     anything, and it is the only one a reader should act on.
  SHADOW_TOTAL       analytical direction only. Never a wager, whatever it says.

WATCHLIST, NOT HOLD. A blocked positive-EV opportunity goes on the WATCHLIST. "Hold" already means
the bookmaker's overround everywhere else in this repository, and an action status that collides
with a market quantity is a defect waiting to be quoted at someone.

BET IS THE GATED WORD. Five gates, all of which must pass, none of which may be waived by any of the
others: price freshness, model uncertainty, input integrity, real-money authorization, and stated
risk. A row that fails any of them is BLOCKED, and a BLOCKED row is never a selection — it may not
appear in the selections section, and its EV may not be summed into exposure.
"""

import sys

BET = "BET"
PASS = "PASS"
BLOCKED = "BLOCKED"
ACTIONS = (BET, PASS, BLOCKED)
DISPLAY = {BET: "BET", PASS: "NO BET", BLOCKED: "NO BET"}

WATCHLIST = "WATCHLIST"
#: the word this must never be, because it already names the bookmaker's overround
FORBIDDEN_STATUS_WORDS = ("HOLD", "LEAN_HOLD")

#: every gate BET must clear. Order is presentation only — all are required and none excuses another.
GATES = (
    ("PRICE_FRESHNESS", "a live executable quote re-checked inside the freshness window. A captured "
                        "board is evidence about the past, not an offer."),
    ("MODEL_UNCERTAINTY", "a per-game epistemic uncertainty from the registered estimand. Not "
                          "outcome noise, not dispersion, not Monte Carlo error."),
    ("INPUT_INTEGRITY", "the inputs the forecast was frozen on still hold — starters, lineups, "
                        "availability — and the prior pool is not provisional."),
    ("REALMONEY_AUTHORIZATION", "explicit human authorization. A separate gate that no model output "
                                "can satisfy on its own."),
    ("STATED_RISK", "a stake, a maximum playable price and a named downside, all written before the "
                    "bet rather than after it."),
)
GATE_NAMES = tuple(g for g, _ in GATES)

REQUIRED_FIELDS = (
    "game", "actual_action", "projected_winner", "projected_winner_probability",
    "best_value_side", "best_value_price", "raw_ev_per_100", "arm_agreement",
    "shadow_total", "primary_blocker", "quote_timestamp_utc", "stake",
)

ONE_ROW_PER_GAME = "DECISION_VIEW_ONE_ROW_PER_GAME"
DUPLICATE_GAME = "DUPLICATE_GAME_ROW"
MISSING_FIELD = "REQUIRED_FIELD_MISSING"
BLOCKED_AS_SELECTION = "BLOCKED_OPPORTUNITY_RENDERED_AS_SELECTION"
UNGATED_BET = "BET_RENDERED_WITHOUT_ALL_GATES_PASSING"
FORBIDDEN_WORD = "ACTION_STATUS_COLLIDES_WITH_MARKET_HOLD"
EV_IN_EXPOSURE = "BLOCKED_EV_SUMMED_INTO_EXPOSURE"
OK = "DECISION_VIEW_OK"
REFUSED = "DECISION_VIEW_REFUSED"


def _num(x):
    if x is None or isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def decide(gates, has_positive_value):
    """(action, blocker). BET only when every gate passes; otherwise BLOCKED or PASS.

    The distinction that matters: a row with NO positive-value side is a PASS — the market and the
    model agree and there is nothing here. A row WITH a positive-value side that cannot be acted on
    is BLOCKED, and the difference between those two is the difference between "nothing to see" and
    "something we cannot reach". Collapsing them hides every blocker in the portfolio.
    """
    failed = [g for g in GATE_NAMES if not (gates or {}).get(g)]
    if not failed:
        return (BET, None) if has_positive_value else (PASS, None)
    if not has_positive_value:
        # gates fail, but there is nothing to act on anyway. PASS is the honest label: reporting it
        # as BLOCKED would inflate the blocked count with rows nobody wanted.
        return PASS, None
    return BLOCKED, failed[0]


def row(game, projected_winner, projected_winner_probability, best_value_side, best_value_price,
        raw_ev_per_100, arm_agreement, arm_total, shadow_total, gates, quote_timestamp_utc,
        blocker_detail=None, sport="mlb"):
    """One game's decision row. Stake is DERIVED from the action and is never carried in."""
    ev = _num(raw_ev_per_100)
    has_value = ev is not None and ev > 0
    action, gate_blocker = decide(gates, has_value)
    return {
        "game": game, "sport": sport,
        "actual_action": action,
        "action_display": DISPLAY[action],
        "projected_winner": projected_winner,
        "projected_winner_probability": _num(projected_winner_probability),
        "best_value_side": best_value_side if has_value else None,
        "best_value_price": best_value_price if has_value else None,
        "raw_ev_per_100": ev if has_value else None,
        "arm_agreement": f"{arm_agreement}/{arm_total}" if arm_agreement is not None else "N/A",
        "shadow_total": shadow_total,
        "shadow_total_authority": "NEVER_DECISION_BEARING",
        "primary_blocker": (blocker_detail or gate_blocker) if action == BLOCKED else None,
        "quote_timestamp_utc": quote_timestamp_utc,
        "quote_kind": "CAPTURED_NOT_EXECUTABLE",
        "stake": 0.0 if action != BET else None,
        "gates": {g: bool((gates or {}).get(g)) for g in GATE_NAMES},
        "watchlist": action == BLOCKED and has_value,
    }


def summary(rows, unit_size_usd=100.0):
    """The block that sits above the board. Exposure counts BET rows only, by construction."""
    rows = list(rows or [])
    bets = [r for r in rows if r["actual_action"] == BET]
    blocked = [r for r in rows if r["actual_action"] == BLOCKED]
    passes = [r for r in rows if r["actual_action"] == PASS]
    units = sum(_num(r.get("stake")) or 0.0 for r in bets)
    return {
        "recommended_bets": len(bets),
        "total_exposure_units": units,
        "total_exposure_usd": units * unit_size_usd,
        "blocked_value_opportunities": len(blocked),
        "pure_market_passes": len(passes),
        "fresh_price_check": "REQUIRED",
        "execution": "BLOCKED" if not bets else "AUTHORIZED",
        "n_games": len(rows),
        "exposure_note": "exposure sums BET rows only. A blocked opportunity's EV is not exposure "
                         "and is never added here — that is how a watchlist turns into a portfolio.",
    }


def watchlist(rows):
    """Blocked positive-EV rows, ranked. Explicitly NOT selections and never called HOLD."""
    out = [r for r in rows or [] if r.get("watchlist")]
    out.sort(key=lambda r: -(r["raw_ev_per_100"] or 0.0))
    return {"status": WATCHLIST, "n": len(out),
            "not_selections": "every row here is a positive raw EV that CANNOT be wagered. Ranking "
                              "them orders the blockers, not the bets.",
            "rows": out}


def selections(rows):
    """Actionable bets only. A BLOCKED row reaching this function is a contract violation."""
    return [r for r in rows or [] if r["actual_action"] == BET]


def render_gate(rows, rendered_selections=None, rendered_exposure_units=None):
    """Enforce the binding render directive over a built decision view."""
    problems, seen = [], {}
    rows = list(rows or [])
    for r in rows:
        g = r.get("game")
        seen[g] = seen.get(g, 0) + 1
        for fld in REQUIRED_FIELDS:
            if fld not in r:
                problems.append({"code": MISSING_FIELD, "game": g, "field": fld})
        act = r.get("actual_action")
        if act not in ACTIONS:
            problems.append({"code": "UNKNOWN_ACTION", "game": g, "action": act})
            continue
        if any(w in str(act).upper() for w in FORBIDDEN_STATUS_WORDS):
            problems.append({"code": FORBIDDEN_WORD, "game": g, "action": act,
                             "note": "HOLD already names the bookmaker's overround; use WATCHLIST"})
        if act == BET and not all(r.get("gates", {}).get(x) for x in GATE_NAMES):
            problems.append({"code": UNGATED_BET, "game": g,
                             "failed": [x for x in GATE_NAMES if not r.get("gates", {}).get(x)]})
        if act == BLOCKED and not r.get("primary_blocker"):
            problems.append({"code": "BLOCKED_WITHOUT_A_NAMED_BLOCKER", "game": g})
        if act != BET and _num(r.get("stake")):
            problems.append({"code": "STAKE_ON_A_NON_BET_ROW", "game": g, "stake": r.get("stake")})
    for g, n in sorted(seen.items()):
        if n > 1:
            problems.append({"code": DUPLICATE_GAME, "game": g, "n_rows": n,
                             "note": ONE_ROW_PER_GAME})
    for r in (rendered_selections or []):
        if r.get("actual_action") != BET:
            problems.append({"code": BLOCKED_AS_SELECTION, "game": r.get("game"),
                             "action": r.get("actual_action")})
    if rendered_exposure_units is not None:
        real = sum(_num(r.get("stake")) or 0.0 for r in rows if r["actual_action"] == BET)
        if abs(float(rendered_exposure_units) - real) > 1e-9:
            problems.append({"code": EV_IN_EXPOSURE, "rendered": rendered_exposure_units,
                             "actual": real})
    return {"status": OK if not problems else REFUSED, "n_problems": len(problems),
            "problems": problems}


# =================================================================================================
def selftest():
    f = []
    ALL = {g: True for g in GATE_NAMES}
    NONE_ = {g: False for g in GATE_NAMES}

    # the four questions must be able to disagree, which is the whole reason they are separate
    wsh = row("mlb:COL@WSH", "WSH", 0.5666, "COL", 169, 16.58, 3, 3, "Over 8", NONE_,
              "2026-08-24T16:41:27Z", blocker_detail="MODEL_UNCERTAINTY")
    if wsh["projected_winner"] == wsh["best_value_side"]:
        f.append("fixture is wrong: this row exists to show the winner and the value side differ")
    if wsh["actual_action"] != BLOCKED:
        f.append(f"a positive-EV row with no gates passing must be BLOCKED, got {wsh['actual_action']}")
    if wsh["stake"] != 0.0:
        f.append("a non-BET row must carry zero stake")
    if not wsh["watchlist"]:
        f.append("a blocked positive-EV row belongs on the watchlist")

    # PASS vs BLOCKED: no positive value is a PASS even with every gate failing
    gsv = row("wnba:GSV@MIN", "MIN", 0.6837, None, None, None, None, None, "Over 160.5", NONE_,
              "2026-08-24T16:41:27Z", sport="wnba")
    if gsv["actual_action"] != PASS:
        f.append(f"a row with no positive value is a PASS, not a BLOCK, got {gsv['actual_action']}")
    if gsv["primary_blocker"] is not None:
        f.append("a PASS row has no blocker: nothing was blocked")
    if gsv["watchlist"]:
        f.append("a PASS row is not on the watchlist")
    if gsv["actual_action"] == wsh["actual_action"]:
        f.append("PASS and BLOCKED must be distinguishable; collapsing them hides every blocker")
    if DISPLAY[gsv["actual_action"]] != DISPLAY[wsh["actual_action"]]:
        f.append("both must still DISPLAY as NO BET; the distinction is in the status, not the verb")

    # a NEGATIVE-EV best-available side must not be rendered as a "best value side". The caller
    # legitimately knows which side is least bad; the board must not dress that up as an opportunity.
    least_bad = row("wnba:GSV@MIN", "MIN", 0.6837, "MIN", -218, -0.27, None, None, "Over 160.5",
                    NONE_, "2026-08-24T16:41:27Z", sport="wnba")
    if least_bad["best_value_side"] is not None or least_bad["best_value_price"] is not None:
        f.append("a negative-EV side must not be published as the best VALUE side")
    if least_bad["raw_ev_per_100"] is not None:
        f.append("a negative raw EV must not be published in the value column")
    if least_bad["actual_action"] != PASS:
        f.append("a row whose best available side is negative-EV is a PASS")
    if least_bad["watchlist"]:
        f.append("a negative-EV row is not a blocked opportunity")

    # BET requires EVERY gate. Each one alone must be able to stop it.
    for missing in GATE_NAMES:
        g = dict(ALL, **{missing: False})
        r = row("mlb:X@Y", "Y", 0.55, "X", 120, 5.0, 3, 3, "Over 8", g, "2026-08-24T16:41:27Z")
        if r["actual_action"] == BET:
            f.append(f"{missing} alone must be able to stop a BET")
        if r["primary_blocker"] != missing:
            f.append(f"the blocker must name the failed gate, got {r['primary_blocker']}")
    allpass = row("mlb:X@Y", "Y", 0.55, "X", 120, 5.0, 3, 3, "Over 8", ALL, "2026-08-24T16:41:27Z")
    if allpass["actual_action"] != BET:
        f.append("every gate passing on a positive-EV row must produce a BET")
    if len(GATE_NAMES) < 5:
        f.append("the directive names five gates")

    # the summary must not launder blocked EV into exposure
    rows = [wsh, gsv]
    s = summary(rows)
    if s["recommended_bets"] != 0 or s["total_exposure_units"] != 0.0:
        f.append("no BET rows means zero bets and zero exposure")
    if s["blocked_value_opportunities"] != 1 or s["pure_market_passes"] != 1:
        f.append(f"the summary must separate blocked from passed, got {s}")
    if s["execution"] != "BLOCKED":
        f.append("execution is BLOCKED while nothing is a BET")
    if s["fresh_price_check"] != "REQUIRED":
        f.append("a captured board always requires a fresh check before action")

    # the render gate: a blocked row may never be rendered as a selection
    bad = render_gate(rows, rendered_selections=[wsh])
    if not any(p["code"] == BLOCKED_AS_SELECTION for p in bad["problems"]):
        f.append("rendering a BLOCKED row as a selection must be refused")
    if selections(rows):
        f.append("selections() must return nothing when nothing is a BET")
    good = render_gate(rows, rendered_selections=selections(rows), rendered_exposure_units=0.0)
    if good["status"] != OK:
        f.append(f"a correct decision view must pass, got {good['problems']}")

    # one row per game
    dup = render_gate(rows + [wsh])
    if not any(p["code"] == DUPLICATE_GAME for p in dup["problems"]):
        f.append("two rows for one game must be refused")

    # a BET whose gates do not all pass must be refused at render even if built by hand
    forged = dict(allpass, gates=dict(ALL, STATED_RISK=False))
    if not any(p["code"] == UNGATED_BET for p in render_gate([forged])["problems"]):
        f.append("a hand-forged BET with a failing gate must be caught at render")

    # exposure that does not match the BET rows must be refused
    if not any(p["code"] == EV_IN_EXPOSURE
               for p in render_gate(rows, rendered_exposure_units=16.58)["problems"]):
        f.append("summing a blocked row's EV into exposure must be refused")

    # WATCHLIST, never HOLD
    if WATCHLIST != "WATCHLIST":
        f.append("the blocked-opportunity list is called WATCHLIST")
    for a in ACTIONS:
        if any(w in a.upper() for w in FORBIDDEN_STATUS_WORDS):
            f.append(f"action {a} collides with the bookmaker's hold")
    w = watchlist(rows)
    if w["n"] != 1 or w["rows"][0]["game"] != "mlb:COL@WSH":
        f.append("the watchlist holds exactly the blocked positive-EV rows")
    if w["status"] != WATCHLIST:
        f.append("the watchlist must be labelled WATCHLIST")
    # ranked by EV, descending
    two = row("mlb:A@B", "B", 0.52, "A", 150, 3.0, 2, 3, "Under 9", NONE_, "2026-08-24T16:41:27Z",
              blocker_detail="MODEL_UNCERTAINTY")
    order = [r["game"] for r in watchlist([two, wsh])["rows"]]
    if order != ["mlb:COL@WSH", "mlb:A@B"]:
        f.append(f"the watchlist ranks by EV descending, got {order}")

    # a missing required field must be caught
    if not any(p["code"] == MISSING_FIELD
               for p in render_gate([{k: v for k, v in wsh.items() if k != "quote_timestamp_utc"}])
               ["problems"]):
        f.append("a missing required field must be refused")

    print("decision_view selftest:", "OK" if not f else "FAIL")
    for x in f:
        print("   -", x)
    return not f


MUTANTS = [
    ("BET stops requiring every gate",
     "    failed = [g for g in GATE_NAMES if not (gates or {}).get(g)]",
     "    failed = [g for g in GATE_NAMES[:1] if not (gates or {}).get(g)]"),
    ("a blocked row is allowed into the selections section",
     '        if r.get("actual_action") != BET:', "        if False:"),
    ("selections() returns blocked rows too",
     '    return [r for r in rows or [] if r["actual_action"] == BET]',
     "    return list(rows or [])"),
    ("PASS and BLOCKED collapse, hiding every blocker",
     "    if not has_positive_value:\n        # gates fail, but there is nothing to act on anyway.",
     "    if True:\n        # gates fail, but there is nothing to act on anyway."),
    ("a blocked row's EV is summed into exposure",
     '    units = sum(_num(r.get("stake")) or 0.0 for r in bets)',
     '    units = sum(abs(_num(r.get("raw_ev_per_100")) or 0.0) for r in rows)'),
    ("a non-BET row is given a stake",
     '        "stake": 0.0 if action != BET else None,', '        "stake": 1.0,'),
    ("the blocker stops naming which gate failed",
     '        "primary_blocker": (blocker_detail or gate_blocker) if action == BLOCKED else None,',
     '        "primary_blocker": None,'),
    ("two rows for one game stop being refused",
     "        if n > 1:", "        if False:"),
    ("a hand-forged BET passes the render gate",
     '        if act == BET and not all(r.get("gates", {}).get(x) for x in GATE_NAMES):',
     "        if False:"),
    ("the watchlist stops ranking by EV",
     '    out.sort(key=lambda r: -(r["raw_ev_per_100"] or 0.0))', "    pass"),
    ("the watchlist admits rows that were never blocked",
     '    out = [r for r in rows or [] if r.get("watchlist")]', "    out = list(rows or [])"),
    ("the action status is renamed to something that collides with the bookmaker's hold",
     'BLOCKED = "BLOCKED"', 'BLOCKED = "LEAN_HOLD"'),
    ("a required field may go missing",
     "            if fld not in r:", "            if False:"),
    ("the fresh-price check stops being required",
     '        "fresh_price_check": "REQUIRED",', '        "fresh_price_check": "DONE",'),
    ("the best value side is shown even when no side has positive value",
     '        "best_value_side": best_value_side if has_value else None,',
     '        "best_value_side": best_value_side,'),
]


def mutation_suite():
    src = open(__file__).read()
    killed = 0
    for name, old, new in MUTANTS:
        if old not in src:
            print("  UNAPPLIED ", name + ": pattern not found")
            continue
        ns = {"__file__": __file__, "__name__": "mutant"}
        try:
            exec(compile(src.replace(old, new, 1), "<mutant>", "exec"), ns)
            ok = ns["selftest"]()
        except Exception:
            ok = False
        print(("  KILLED    " if not ok else "  SURVIVED  ") + name)
        killed += not ok
    print(f"mutation suite: {killed}/{len(MUTANTS)} killed"
          + ("" if killed == len(MUTANTS) else "  — SURVIVORS MEAN DECORATIVE FIXTURES"))
    return killed == len(MUTANTS)


if __name__ == "__main__":
    if "--mutants" in sys.argv:
        sys.exit(0 if mutation_suite() else 1)
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    print(__doc__)
