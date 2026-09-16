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

MODULE_ID = "decision_view"

import re
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


# --- v1.0 FINAL DECISION VOCABULARY -----------------------------------------------------------
#: Section 1. The NORMAL vocabulary is BET or PASS. BLOCKED survives below as an INTERNAL status
#: that drives the watchlist, but it may never be a game's FINAL published decision when its cause
#: is one of the internal work-queue conditions. That is the whole change: "we could not find out"
#: is a task with a deadline, not an answer.
NORMAL_FINAL = (BET, PASS)
EXCEPTION = "EXCEPTION"
SYSTEM_FAILURE = "SYSTEM_FAILURE"
FINAL_DECISIONS = (BET, PASS, EXCEPTION, SYSTEM_FAILURE)

#: Section 11. The closed set of states that can legitimately prevent a normal decision. These are
#: INCIDENTS — not ordinary passes, and not evidence that searching was optional.
EXCEPTIONAL_STATES = (
    "GAME_ALREADY_LIVE",
    "GAME_POSTPONED_OR_CANCELLED",
    "MARKET_SUSPENDED",
    "CONFLICTING_AUTHORITATIVE_IDENTITIES",
    "MATERIAL_CHANGE_TOO_LATE_TO_ANCHOR",
    "INTEGRITY_OR_CHRONOLOGY_FAILURE",
    "NO_VALIDATED_MODEL_OR_FALLBACK_FOR_STATE",
)

#: Section 1's forbidden endings. Each is an internal work queue.
WORK_QUEUE_ENDINGS = (
    "BLOCKED_INFORMATION_UNAVAILABLE", "PERSONNEL_UNVERIFIED", "PRICE_MISSING",
    "STARTER_UNCONFIRMED", "UNCERTAINTY_PIPELINE_DEFECT", "LINEUP_UNAVAILABLE",
    "SLATE_UNAVAILABLE", "SOURCE_ARTIFACT_NOT_RETAINED", "PRICE_STALE",
    "MODEL_UNCERTAINTY", "PRICE_FRESHNESS", "INPUT_INTEGRITY",
    "PENDING_FEATURE_REFRESH", "FEATURE_STALENESS",
)

# =================================================================================================
# SYSTEM WORK STATUS (owner render rule, 2026-08-25). The page section that lists open work must
# classify every item; "what someone should eventually do" is not a state. No unresolved condition
# may roll into another slate as unchanged prose — it is an ACTIVE_INCIDENT with a job behind it,
# or it is RESOLVED / EXPIRED / NOT_APPLICABLE.
WORK_STATUS_CLASSES = ("RESOLVED", "ACTIVE_INCIDENT", "EXPIRED", "NOT_APPLICABLE")
ACTIVE_INCIDENT_FIELDS = ("job_id", "owner", "last_attempt_utc", "next_attempt_utc",
                          "deadline_utc", "progress")
UNKNOWN_WORK_CLASS = "WORK_ITEM_WITH_UNKNOWN_CLASS"
INCIDENT_FIELD_MISSING = "ACTIVE_INCIDENT_MISSING_REQUIRED_FIELD"
PROGRESS_NOT_MEASURABLE = "ACTIVE_INCIDENT_PROGRESS_NOT_MEASURABLE"

_PROGRESS = re.compile(r"^\d+/\d+")


def work_status_gate(items):
    """items: [{"item","class",...}]. Every ACTIVE_INCIDENT carries a job id, an owner, last and
    next attempts, a deadline and measurable progress ("done/total ...")."""
    problems = []
    for it in items or []:
        cls = it.get("class")
        if cls not in WORK_STATUS_CLASSES:
            problems.append({"code": UNKNOWN_WORK_CLASS, "item": it.get("item"), "class": cls})
            continue
        if cls == "ACTIVE_INCIDENT":
            missing = [k for k in ACTIVE_INCIDENT_FIELDS if not it.get(k)]
            if missing:
                problems.append({"code": INCIDENT_FIELD_MISSING, "item": it.get("item"),
                                 "missing": missing})
            elif not _PROGRESS.match(str(it.get("progress"))):
                problems.append({"code": PROGRESS_NOT_MEASURABLE, "item": it.get("item"),
                                 "progress": it.get("progress")})
    return {"status": "WORK_STATUS_OK" if not problems else "WORK_STATUS_REFUSED",
            "n_problems": len(problems), "problems": problems}

WORK_QUEUE_AS_DECISION = "WORK_QUEUE_CONDITION_PUBLISHED_AS_A_FINAL_DECISION"
UNKNOWN_EXCEPTION = "EXCEPTION_STATE_NOT_ON_THE_SECTION_11_LIST"
EXCEPTION_WITHOUT_STATE = "EXCEPTION_WITHOUT_A_NAMED_STATE"
FAILURE_WITHOUT_INCIDENT = "SYSTEM_FAILURE_WITHOUT_AN_INCIDENT_RECORD"
FORCED_WAGER = "WAGER_FORCED_ON_NON_POSITIVE_CONSERVATIVE_EV"

#: Section 9. Every field the published row must carry.
ROW_CONTRACT_V1 = (
    "game", "final_decision", "recommended_side", "recommended_market", "current_price",
    "playable_price_boundary", "model_probability", "breakeven_probability", "novig_probability",
    "raw_ev_per_100", "conservative_ev_per_100", "projected_winner", "projected_margin",
    "projected_total", "arm_agreement", "personnel_verification", "lineup_verification",
    "quote_timestamp_utc", "quote_age_seconds", "recommended_units", "recommended_dollars",
    "primary_reason",
)
UNIT_SIZE_USD = 100.0


MISSING_GAME = "SCHEDULED_GAME_HAS_NO_DECISION_ROW"
EXTRA_GAME = "DECISION_ROW_FOR_AN_UNSCHEDULED_GAME"


def slate_coverage_gate(scheduled_games, rows):
    """Section 1: EVERY scheduled game receives a decision. Silence is not a decision.

    The failure this catches is quieter than a wrong number: a game that simply is not on the page.
    Nothing else notices, because every row that IS present can be perfectly correct. Coverage has
    to be checked against the SCHEDULE, not against the rows, or the rows define their own universe.
    """
    sched = list(scheduled_games or [])
    have = [r.get("game") for r in rows or []]
    problems = [{"code": MISSING_GAME, "game": g} for g in sched if g not in have]
    problems += [{"code": EXTRA_GAME, "game": g} for g in have if g not in sched]
    return {"status": OK if not problems else REFUSED, "n_problems": len(problems),
            "n_scheduled": len(sched), "n_rows": len(have), "problems": problems}


def is_work_queue_ending(reason):
    """True when a reason is an internal work item that may not end a game."""
    r = str(reason or "")
    return any(w in r for w in WORK_QUEUE_ENDINGS)


def final_decision(action, exception_state=None, incident=None):
    """Map an internal action to a v1.0 FINAL decision, or refuse."""
    if action == BET:
        return BET, None
    if action == PASS:
        return PASS, None
    if action == EXCEPTION:
        if not exception_state:
            return None, EXCEPTION_WITHOUT_STATE
        if exception_state not in EXCEPTIONAL_STATES:
            return None, f"{UNKNOWN_EXCEPTION}: {exception_state}"
        return EXCEPTION, None
    if action == SYSTEM_FAILURE:
        if not incident:
            return None, FAILURE_WITHOUT_INCIDENT
        return SYSTEM_FAILURE, None
    return None, f"NOT_A_FINAL_DECISION: {action}"


def final_decision_gate(rows, past_freeze=True):
    """Section 1 + 10 + 11, enforced over a published board."""
    problems = []
    for r in rows or []:
        fd = r.get("final_decision", r.get("actual_action"))
        reason = r.get("primary_reason", r.get("primary_blocker"))
        if fd not in FINAL_DECISIONS:
            problems.append({"code": WORK_QUEUE_AS_DECISION, "game": r.get("game"),
                             "published": fd,
                             "note": "the normal final vocabulary is BET or PASS; anything else "
                                     "must be a named section 11 exception or a SYSTEM_FAILURE "
                                     "carrying an incident record"})
            continue
        if fd in NORMAL_FINAL and past_freeze and is_work_queue_ending(reason):
            problems.append({"code": WORK_QUEUE_AS_DECISION, "game": r.get("game"),
                             "published": fd, "reason": reason,
                             "note": "an internal work queue may not be the stated reason for a "
                                     "normal decision after the freeze. Resolve it, raise a "
                                     "section 11 exception, or declare SYSTEM_FAILURE."})
        _, err = final_decision(fd, r.get("exception_state"), r.get("incident"))
        if err:
            problems.append({"code": err, "game": r.get("game")})
        if fd == BET:
            cev = _num(r.get("conservative_ev_per_100"))
            if cev is None or cev <= 0:
                problems.append({"code": FORCED_WAGER, "game": r.get("game"),
                                 "conservative_ev_per_100": cev,
                                 "note": "a wager may not be forced where uncertainty-adjusted EV "
                                         "is non-positive or unavailable"})
    return {"status": OK if not problems else REFUSED, "n_problems": len(problems),
            "problems": problems}


def row_contract_gate(rows):
    """Section 9: every published row carries every field, and a BET shows units AND dollars."""
    problems = []
    for r in rows or []:
        for fld in ROW_CONTRACT_V1:
            if fld not in r:
                problems.append({"code": MISSING_FIELD, "game": r.get("game"), "field": fld})
        if r.get("final_decision") == BET:
            u, d = _num(r.get("recommended_units")), _num(r.get("recommended_dollars"))
            if not u or not d:
                problems.append({"code": "WAGER_WITHOUT_UNITS_AND_DOLLARS", "game": r.get("game")})
            elif abs(d - u * UNIT_SIZE_USD) > 1e-9:
                problems.append({"code": "UNITS_AND_DOLLARS_DISAGREE", "game": r.get("game"),
                                 "units": u, "dollars": d, "unit_size": UNIT_SIZE_USD})
            if r.get("playable_price_boundary") in (None, ""):
                problems.append({"code": "WAGER_WITHOUT_A_PLAYABLE_PRICE_BOUNDARY",
                                 "game": r.get("game")})
    return {"status": OK if not problems else REFUSED, "n_problems": len(problems),
            "problems": problems}


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

    # --- v1.0: slate coverage. Every scheduled game gets a row. -----------------------------------
    SCHED = ["mlb:A@B", "mlb:C@D", "wnba:E@F"]
    full_rows = [{"game": g} for g in SCHED]
    if slate_coverage_gate(SCHED, full_rows)["status"] != OK:
        f.append("a board covering every scheduled game must pass")
    for drop in SCHED:
        part = [r for r in full_rows if r["game"] != drop]
        cov = slate_coverage_gate(SCHED, part)
        if cov["status"] != REFUSED:
            f.append(f"a board missing {drop} must be refused")
        elif not any(p["code"] == MISSING_GAME and p["game"] == drop for p in cov["problems"]):
            f.append(f"the missing game {drop} must be named")
    extra = slate_coverage_gate(SCHED, full_rows + [{"game": "mlb:PHANTOM@GAME"}])
    if extra["status"] != REFUSED or not any(p["code"] == EXTRA_GAME for p in extra["problems"]):
        f.append("a row for an unscheduled game must be refused — the 8/13 phantom-game defect")
    if slate_coverage_gate(SCHED, [])["n_problems"] != 3:
        f.append("an empty board must report every scheduled game as missing")
    if slate_coverage_gate([], [{"game": "x"}])["status"] != REFUSED:
        f.append("rows without a schedule cannot define their own universe")

    # --- v1.0: the final decision vocabulary -----------------------------------------------------
    if set(NORMAL_FINAL) != {BET, PASS}:
        f.append("the normal final vocabulary is BET and PASS")
    if len(EXCEPTIONAL_STATES) != 7:
        f.append("section 11 names seven exceptional states")

    def frow(**kw):
        base = {"game": "mlb:A@B", "final_decision": PASS, "primary_reason": "negative EV",
                "conservative_ev_per_100": None}
        base.update(kw); return base

    # THE HEADLINE RULE: a work-queue condition may not be a game's stated reason after the freeze
    for wq in ("UNCERTAINTY_PIPELINE_DEFECT", "PERSONNEL_UNVERIFIED", "STARTER_UNCONFIRMED",
               "PRICE_MISSING", "BLOCKED_INFORMATION_UNAVAILABLE", "LINEUP_UNAVAILABLE"):
        g = final_decision_gate([frow(primary_reason=wq)])
        if not any(p["code"] == WORK_QUEUE_AS_DECISION for p in g["problems"]):
            f.append(f"{wq} must not be publishable as a final reason after the freeze")
        # ...and BEFORE the freeze it is a legitimate open work item, not a violation
        if final_decision_gate([frow(primary_reason=wq)], past_freeze=False)["problems"]:
            f.append(f"{wq} before the freeze is an open work item, not a violation")
    if not is_work_queue_ending("UNCERTAINTY_PIPELINE_DEFECT"):
        f.append("the uncertainty defect is an internal work queue")
    if is_work_queue_ending("negative expected value at this price"):
        f.append("a genuine economic reason is not a work queue")

    # BLOCKED is no longer a FINAL decision at all — and it must be refused BY THE VOCABULARY,
    # not incidentally by some later check. Asserting only "refused" would let BLOCKED back into
    # FINAL_DECISIONS without any fixture noticing.
    bl = final_decision_gate([frow(final_decision=BLOCKED)])
    if bl["status"] != REFUSED:
        f.append("BLOCKED may not be published as a final decision")
    elif not any(p["code"] == WORK_QUEUE_AS_DECISION and p.get("published") == BLOCKED
                 for p in bl["problems"]):
        f.append(f"BLOCKED must be refused by the final-decision vocabulary, got {bl['problems']}")
    if BLOCKED in FINAL_DECISIONS:
        f.append("BLOCKED must not be in the final decision vocabulary")

    # exceptions must be named from the closed list
    ex = final_decision_gate([frow(final_decision=EXCEPTION,
                                   exception_state="GAME_ALREADY_LIVE")])
    if ex["status"] != OK:
        f.append(f"a named section 11 exception is publishable, got {ex['problems']}")
    # each refusal must come from ITS OWN guard: a missing state and an unlisted state are
    # different defects and a single catch-all would hide the loss of either
    for bad, want in ((None, EXCEPTION_WITHOUT_STATE), ("", EXCEPTION_WITHOUT_STATE),
                      ("I_DID_NOT_LOOK", UNKNOWN_EXCEPTION),
                      ("UNCERTAINTY_PIPELINE_DEFECT", UNKNOWN_EXCEPTION)):
        b = final_decision_gate([frow(final_decision=EXCEPTION, exception_state=bad)])
        if b["status"] != REFUSED:
            f.append(f"exception state {bad!r} must be refused")
        elif not any(want in str(p.get("code", "")) for p in b["problems"]):
            f.append(f"exception state {bad!r} must be refused by {want}, got {b['problems']}")
    for st in EXCEPTIONAL_STATES:
        if final_decision_gate([frow(final_decision=EXCEPTION, exception_state=st)])["status"] != OK:
            f.append(f"{st} is a legitimate section 11 exception")

    # SYSTEM_FAILURE needs an incident record
    if final_decision_gate([frow(final_decision=SYSTEM_FAILURE)])["status"] != REFUSED:
        f.append("SYSTEM_FAILURE without an incident record must be refused")
    if final_decision_gate([frow(final_decision=SYSTEM_FAILURE,
                                 incident={"missing_field": "starter"})])["status"] != OK:
        f.append("SYSTEM_FAILURE with an incident record is publishable")

    # NO FORCED WAGERS: a BET needs positive CONSERVATIVE EV, not positive raw EV
    for cev in (None, 0.0, -1.0):
        b = final_decision_gate([frow(final_decision=BET, primary_reason="edge",
                                      conservative_ev_per_100=cev)])
        if not any(p["code"] == FORCED_WAGER for p in b["problems"]):
            f.append(f"a BET at conservative EV {cev} must be refused as a forced wager")
    if final_decision_gate([frow(final_decision=BET, primary_reason="edge",
                                 conservative_ev_per_100=3.0)])["status"] != OK:
        f.append("a BET with positive conservative EV is publishable")

    # --- section 9 row contract ------------------------------------------------------------------
    full = {k: "x" for k in ROW_CONTRACT_V1}
    full.update(game="mlb:A@B", final_decision=PASS)
    if row_contract_gate([full])["status"] != OK:
        f.append(f"a complete row must pass, got {row_contract_gate([full])['problems']}")
    for fld in ROW_CONTRACT_V1:
        part = {k: v for k, v in full.items() if k != fld}
        if not any(p["code"] == MISSING_FIELD and p["field"] == fld
                   for p in row_contract_gate([part])["problems"]):
            f.append(f"a row missing {fld} must be refused")
    # a wager shows BOTH units and dollars, and they must agree at the $100 unit
    bet = dict(full, final_decision=BET, recommended_units=1.0, recommended_dollars=100.0,
               playable_price_boundary="-115")
    if row_contract_gate([bet])["status"] != OK:
        f.append(f"a complete wager row must pass, got {row_contract_gate([bet])['problems']}")
    if row_contract_gate([dict(bet, recommended_dollars=50.0)])["status"] != REFUSED:
        f.append("units and dollars must agree at the $100 unit size")
    if row_contract_gate([dict(bet, recommended_units=None)])["status"] != REFUSED:
        f.append("a wager must show units")
    if row_contract_gate([dict(bet, playable_price_boundary=None)])["status"] != REFUSED:
        f.append("a wager must carry a playable price boundary")
    if UNIT_SIZE_USD != 100.0:
        f.append("unit size is $100")

    # a stale-feature condition is work, not an ending
    if "PENDING_FEATURE_REFRESH" not in WORK_QUEUE_ENDINGS:
        f.append("PENDING_FEATURE_REFRESH must be a work-queue condition, never a game ending")

    # system work status: four classes, incidents fully specified
    good_items = [
        {"item": "price board", "class": "RESOLVED"},
        {"item": "8/24 starter changes", "class": "EXPIRED"},
        {"item": "tier-1 provenance", "class": "ACTIVE_INCIDENT", "job_id": "RJ-001-PROVENANCE",
         "owner": "acquisition", "last_attempt_utc": "2026-08-25T21:56:00Z",
         "next_attempt_utc": "2026-08-26T04:00:00Z", "deadline_utc": "2026-09-01T00:00:00Z",
         "progress": "0/123 rows"},
    ]
    ws = work_status_gate(good_items)
    if ws["status"] != "WORK_STATUS_OK":
        f.append(f"a fully classified work list must pass, got {ws}")
    ws = work_status_gate([{"item": "someday fix the estimator", "class": "SOMEDAY"}])
    if ws["status"] != "WORK_STATUS_REFUSED" or ws["problems"][0]["code"] != UNKNOWN_WORK_CLASS:
        f.append("'someday' is not a work-status class")
    ws = work_status_gate([{"item": "x", "class": None}])
    if ws["status"] != "WORK_STATUS_REFUSED":
        f.append("unclassified prose must be refused")
    bare = {"item": "wnba features", "class": "ACTIVE_INCIDENT", "job_id": "RJ-005",
            "owner": "wnba_features", "last_attempt_utc": "t", "next_attempt_utc": "t",
            "deadline_utc": "t", "progress": "0/17 units"}
    for k in ACTIVE_INCIDENT_FIELDS:
        broken = dict(bare); broken.pop(k)
        ws = work_status_gate([broken])
        if ws["status"] != "WORK_STATUS_REFUSED" or ws["problems"][0]["code"] != INCIDENT_FIELD_MISSING:
            f.append(f"an ACTIVE_INCIDENT without {k} must be refused")
    ws = work_status_gate([dict(bare, progress="ongoing")])
    if ws["status"] != "WORK_STATUS_REFUSED" or ws["problems"][0]["code"] != PROGRESS_NOT_MEASURABLE:
        f.append("'ongoing' is not measurable progress")

    print("decision_view selftest:", "OK" if not f else "FAIL")
    for x in f:
        print("   -", x)
    return not f


MUTANTS = [
    ("a stale-feature condition ends a game again",
     '    "PENDING_FEATURE_REFRESH", "FEATURE_STALENESS",\n)',
     ")"),
    ("unknown work classes are accepted",
     "        if cls not in WORK_STATUS_CLASSES:",
     "        if False:"),
    ("an incident may omit its required fields",
     "            missing = [k for k in ACTIVE_INCIDENT_FIELDS if not it.get(k)]",
     "            missing = []"),
    ("unmeasurable progress is accepted",
     '            elif not _PROGRESS.match(str(it.get("progress"))):',
     "            elif False:"),
    ("a scheduled game may be dropped from the board without notice",
     '    problems = [{"code": MISSING_GAME, "game": g} for g in sched if g not in have]',
     "    problems = []"),
    ("a phantom game may be carded",
     '    problems += [{"code": EXTRA_GAME, "game": g} for g in have if g not in sched]', "    pass"),
    ("coverage is checked against the rows instead of the schedule",
     "    problems = [{\"code\": MISSING_GAME, \"game\": g} for g in sched if g not in have]",
     "    problems = [{\"code\": MISSING_GAME, \"game\": g} for g in have if g not in have]"),
    ("a work-queue condition may end a game as a normal decision",
     "        if fd in NORMAL_FINAL and past_freeze and is_work_queue_ending(reason):",
     "        if False:"),
    ("the uncertainty defect drops off the work-queue list",
     '    "STARTER_UNCONFIRMED", "UNCERTAINTY_PIPELINE_DEFECT", "LINEUP_UNAVAILABLE",',
     '    "STARTER_UNCONFIRMED", "LINEUP_UNAVAILABLE",'),
    ("a work-queue reason is a violation even before the freeze",
     "        if fd in NORMAL_FINAL and past_freeze and", "        if fd in NORMAL_FINAL and"),
    ("BLOCKED becomes publishable as a final decision",
     "FINAL_DECISIONS = (BET, PASS, EXCEPTION, SYSTEM_FAILURE)",
     "FINAL_DECISIONS = (BET, PASS, EXCEPTION, SYSTEM_FAILURE, BLOCKED)"),
    ("an unlisted exception state is accepted",
     "        if exception_state not in EXCEPTIONAL_STATES:", "        if False:"),
    ("an exception needs no state at all",
     "        if not exception_state:\n            return None, EXCEPTION_WITHOUT_STATE",
     "        if False:\n            return None, EXCEPTION_WITHOUT_STATE"),
    ("SYSTEM_FAILURE stops needing an incident record",
     "        if not incident:\n            return None, FAILURE_WITHOUT_INCIDENT",
     "        if False:\n            return None, FAILURE_WITHOUT_INCIDENT"),
    ("a wager is forced on non-positive conservative EV",
     "            if cev is None or cev <= 0:", "            if False:"),
    ("a wager is authorized on RAW EV instead of conservative EV",
     '            cev = _num(r.get("conservative_ev_per_100"))',
     '            cev = _num(r.get("raw_ev_per_100"))'),
    ("a required section 9 field may go missing",
     "        for fld in ROW_CONTRACT_V1:\n            if fld not in r:", "        for fld in []:\n            if fld not in r:"),
    ("a wager may show units without dollars",
     "            if not u or not d:", "            if False:"),
    ("units and dollars stop being reconciled at the unit size",
     "            elif abs(d - u * UNIT_SIZE_USD) > 1e-9:", "            elif False:"),
    ("a wager may go out without a playable price boundary",
     '            if r.get("playable_price_boundary") in (None, ""):', "            if False:"),
    ("an exceptional state is dropped from the section 11 list",
     '    "MARKET_SUSPENDED",\n', ""),
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
    # BASELINE FIRST. A failing selftest makes every mutant look killed, so a broken fixture reports
    # a perfect score. Caught 2026-08-25 when module_manifest printed 11/11 while its own selftest
    # was failing.
    import io as _io, contextlib as _cl
    _b = _io.StringIO()
    with _cl.redirect_stdout(_b):
        _base = selftest()
    if not _base:
        print("  BASELINE_FAILING  the unmutated selftest does not pass; every 'kill' below is "
              "meaningless until it does")
        print(_b.getvalue().strip())
        return False
    # a mutant whose pattern occurs only inside the MUTANTS literal edits its OWN definition,
    # applies cleanly, changes no behaviour and reports SURVIVED. Caught 2026-08-25 after a rename.
    body = src[:src.index("MUTANTS = [")]
    killed = 0
    for name, old, new in MUTANTS:
        if old not in src:
            print("  UNAPPLIED ", name + ": pattern not found")
            continue
        if old not in body:
            print("  SELF_TARGETED ", name + ": pattern occurs only inside the MUTANTS list")
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
