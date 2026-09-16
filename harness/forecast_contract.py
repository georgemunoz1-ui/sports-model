#!/usr/bin/env python3
"""FORECAST CONTRACT — a gate blocks an ACTION. It never deletes a FORECAST.

OWNER BINDING STANDARD 2026-08-23:

    Generate forecast -> Register and seal forecast -> Apply freshness/compression/evidence/action
    gates -> Render action status -> Grade the sealed forecast regardless of action status

    "A missing starter therefore becomes a registered CAP forecast. A stale state produces a
     frozen-state forecast. Neutral-site uncertainty produces an out-of-domain forecast.
     None becomes a blank row."

WHY THIS IS A REAL DEFECT AND NOT A PRESENTATION PREFERENCE. On 2026-08-22 this system produced
zero gradeable rows for six games because their gates fired, and the gates ran BEFORE registration.
The consequence is not that the card looked sparse — it is that the model was never scored on those
games. A model whose hardest rows silently vanish from its own record accumulates a scorebook made
only of the games it felt confident about, and every summary statistic computed from it is
conditioned on the model's own confidence. That is unfalsifiable by construction.

THE ORDERING IS THE CONTROL. Gates run on a SEALED forecast. Sealing produces a hash; a gate that
changes the sealed content is refused, not applied. So a gate can say "do not act on this" and can
never say "pretend this forecast was not made".

TWO STATUSES, NEVER ONE FIELD. forecast_status answers "was a forecast produced and registered".
action_status answers "may anything be done about it". Collapsing them is what allowed a blocked row
to become a blank row, and no code path here lets an action_status value suppress a forecast.
"""
from __future__ import annotations

MODULE_ID = "forecast_contract"

import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FORECAST_REGISTERED = "FORECAST_REGISTERED"
FORECAST_STATUSES = (FORECAST_REGISTERED,)   # there is exactly one: a forecast is always produced

# Action statuses. Every one of these is compatible with a fully registered, gradeable forecast.
PASS_REFERENCE_ONLY = "PASS_REFERENCE_ONLY"
NO_ACTION = "NO_ACTION"
BLOCKED_PREFIX = "BLOCKED_"
BET_PREFIX = "BET_"

# The three cases the owner names, and what each produces instead of a blank row.
FALLBACKS = {
    "MISSING_STARTER": "REGISTERED_CAP_FORECAST",
    "STALE_STATE": "FROZEN_STATE_FORECAST",
    "NEUTRAL_SITE_UNCERTAINTY": "OUT_OF_DOMAIN_FORECAST",
}

REQUIRED_FIELDS = (
    "game",
    "model_id",
    "training_cutoff_utc",
    "information_class",
    "resolved_information_dose",
    "simulation_seed",
    "simulation_trials",
    "winner_probability",
    "predicted_winner",
    "projected_away_score",
    "projected_home_score",
    "projected_total",
    "total_side",
    "p_over",
    "p_push",
    "p_under",
    "forecast_status",
    "action_status",
    "fallback_applied",
)
# ATS is required only where the sport has a spread estimand.
#: TARGETS AND THEIR DECISION AUTHORITY (owner directive 2026-08-24).
#: "Keep total forecasts mandatory and gradable while blocking them from decision authority."
#:
#: The total is the steadiest thing this system produces and that is exactly why it is dangerous: a
#: steady number invites action. It has never had an estimand that could support one. On 2026-08-23
#: every arm was graded against ITS OWN fair line, which scores ~50/50 by construction; the market
#: over/under is unavailable because no captured board clears the same-book bar; and the honest
#: comparator, the expanding league mean, beat every model arm. A target that cannot yet beat a
#: single league-average number, and has no independent line to be scored against, may be forecast
#: and graded and may not decide anything.
#:
#: Mandatory, gradable, and NEVER decision-bearing are three separate properties, and this table
#: keeps them separate rather than letting "we grade it" drift into "we can bet it".
TARGET_AUTHORITY = {
    "winner": "GATE_GOVERNED",
    "total": "NEVER_DECISION_BEARING",
    # margin joins the total under the same reasoning (owner directive 2026-08-24): it is a
    # mandatory gradable shadow output with no independent line to be scored against, so it is
    # forecast and graded and decides nothing.
    "margin": "NEVER_DECISION_BEARING",
    "ats": "GATE_GOVERNED",
}
TOTAL_DECISION_ATTEMPT = "TOTAL_MAY_NOT_CARRY_DECISION_AUTHORITY"

#: Row fields that would give a total decision authority. Presence of any is a structural refusal.
TOTAL_DECISION_FIELDS = ("total_action_status", "total_selection", "total_stake_u",
                         "total_bet", "total_authorized", "ou_selection", "ou_stake_u")

ATS_FIELDS = ("ats_selection", "ats_cover_probability")
ATS_SPORTS = ("wnba", "nfl", "nba", "ncaab", "ncaaf")

SEALED_KEYS = tuple(k for k in REQUIRED_FIELDS if k not in ("action_status",)) + ATS_FIELDS


def seal(row):
    """Hash the FORECAST content, deliberately excluding action_status.

    action_status is rendered after the gates run, so it cannot be part of what the gates are
    checked against. Everything else is frozen at seal time."""
    payload = {k: row.get(k) for k in SEALED_KEYS if k in row}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def validate_row(row, sport=None):
    """(ok, failures) for one emitted forecast row."""
    f = []
    sport = (sport or row.get("sport") or "").lower()
    for k in REQUIRED_FIELDS:
        if k not in row:
            f.append(f"{row.get('game', '?')}: required field {k} is absent")
    if sport in ATS_SPORTS:
        for k in ATS_FIELDS:
            if k not in row:
                f.append(f"{row.get('game', '?')}: {sport} carries a spread estimand and {k} is absent")
    fs = row.get("forecast_status")
    if fs is not None and fs not in FORECAST_STATUSES:
        f.append(f"{row.get('game', '?')}: forecast_status {fs!r} is not {FORECAST_REGISTERED} — a "
                 f"forecast is produced unconditionally, so there is no other value")
    # THE CORE RULE: no action status may leave the forecast fields empty.
    p = row.get("winner_probability")
    if p is None or not isinstance(p, (int, float)) or isinstance(p, bool) or not (0.0 < float(p) < 1.0):
        f.append(f"{row.get('game', '?')}: winner_probability {p!r} is not a probability in (0,1) — "
                 f"a blocked row is still a forecast row")
    # A NULL WITH A STATED REASON IS A FIRST-CLASS VALUE; A BARE NULL IS NOT.
    # V13 forecasts a winner and a total and does not forecast per-team scores. Forcing it to emit
    # one would be fabricating a number to satisfy a schema, which is worse than the gap. So a
    # projected score may be null ONLY when the row states why — the same R1 convention the market
    # fields already follow. The projected TOTAL has no such exemption: every arm here forecasts a
    # total, and a null there would be a missing forecast rather than an absent estimand.
    for k in ("projected_away_score", "projected_home_score"):
        v = row.get(k)
        if v is None:
            if not row.get("projected_score_null_reason"):
                f.append(f"{row.get('game', '?')}: {k} is null with no projected_score_null_reason; "
                         f"a bare null is a missing forecast, a null with a stated reason is an "
                         f"absent estimand")
        elif isinstance(v, bool) or not isinstance(v, (int, float)):
            f.append(f"{row.get('game', '?')}: {k} is {v!r}; a gate blocks an action, not a projection")
    tv = row.get("projected_total")
    if tv is None or isinstance(tv, bool) or not isinstance(tv, (int, float)):
        f.append(f"{row.get('game', '?')}: projected_total is {tv!r}; every arm on this card "
                 f"forecasts a total, so a null here is a missing forecast")
    # MANDATORY AND GRADABLE, NEVER DECISION-BEARING. The total must be present (above) and must be
    # gradeable (it flows through gradeable() like any other field) and must not acquire an action.
    for k in TOTAL_DECISION_FIELDS:
        if row.get(k) not in (None, "", "NONE"):
            f.append(f"{row.get('game', '?')}: {TOTAL_DECISION_ATTEMPT} — field {k}={row.get(k)!r}. "
                     f"The total is forecast and graded; it decides nothing. "
                     f"TARGET_AUTHORITY['total'] is {TARGET_AUTHORITY['total']} and there is no "
                     f"path in this module that changes it.")
    if row.get("total_side") is not None and str(row.get("action_status", "")).startswith(BET_PREFIX):
        f.append(f"{row.get('game', '?')}: {TOTAL_DECISION_ATTEMPT} — a row carrying a total side "
                 f"may not also carry a BET action status")
    probs = [row.get("p_over"), row.get("p_push"), row.get("p_under")]
    if any(x is None or isinstance(x, bool) or not isinstance(x, (int, float)) for x in probs):
        f.append(f"{row.get('game', '?')}: over/push/under probabilities incomplete {probs}")
    elif abs(sum(float(x) for x in probs) - 1.0) > 1e-6:
        f.append(f"{row.get('game', '?')}: over+push+under = {sum(float(x) for x in probs):.6f}, not 1")
    if not row.get("model_id"):
        f.append(f"{row.get('game', '?')}: model_id is empty; an immutable identity is required")
    if row.get("information_class") is None:
        f.append(f"{row.get('game', '?')}: information_class absent")
    dose = row.get("resolved_information_dose")
    if dose is not None and not (isinstance(dose, (int, float)) and 0.0 <= float(dose) <= 1.0):
        f.append(f"{row.get('game', '?')}: resolved_information_dose {dose!r} is not a fraction")
    if row.get("simulation_seed") is None or row.get("simulation_trials") is None:
        f.append(f"{row.get('game', '?')}: simulation seed and trial count are both required")
    # a BLOCKED or non-acting row must NAME its reason, and a fallback must name what it produced
    a = row.get("action_status") or ""
    if a.startswith(BLOCKED_PREFIX) and len(a) <= len(BLOCKED_PREFIX):
        f.append(f"{row.get('game', '?')}: action_status is a bare {BLOCKED_PREFIX!r} with no reason")
    fb = row.get("fallback_applied")
    if fb not in (None, "NONE") and fb not in FALLBACKS.values() and fb not in FALLBACKS:
        f.append(f"{row.get('game', '?')}: fallback_applied {fb!r} is not one of the declared "
                 f"fallbacks {sorted(set(FALLBACKS) | set(FALLBACKS.values()))}")
    return (not f), f


# ---------------------------------------------------------------------------------------------
# THE PIPELINE. Five stages, and the gates run on SEALED content.
# ---------------------------------------------------------------------------------------------
STAGES = ("GENERATE_FORECAST", "REGISTER_AND_SEAL", "APPLY_GATES", "RENDER_ACTION_STATUS",
          "GRADE_REGARDLESS_OF_ACTION_STATUS")
STAGE_ORDER = {s: i for i, s in enumerate(STAGES)}


def pipeline_gate(completed, proposed):
    """(ok, reason). Stages run in order; none may be skipped.

    The ordering IS the control: gates that ran before registration are how six games disappeared
    from the 2026-08-22 record entirely."""
    if proposed not in STAGE_ORDER:
        return False, f"{proposed!r} is not a stage of the forecast pipeline"
    i = STAGE_ORDER[proposed]
    done = {s for s in completed if s in STAGE_ORDER}
    missing = [s for s in STAGES[:i] if s not in done]
    if missing:
        return False, (f"{proposed!r} proposed with earlier stage(s) incomplete: {missing}. Gates "
                       f"that run before registration delete forecasts instead of blocking actions")
    return True, f"{proposed!r} may run"


def apply_gates(sealed_row, sealed_hash, gate_results):
    """Run gates against a SEALED forecast and render an action status.

    gate_results: [{"gate":..., "blocks": bool, "reason":...}]. Returns (row, failures).
    A gate that would alter sealed content is REFUSED, not applied."""
    fails = []
    row = dict(sealed_row)
    if seal(row) != sealed_hash:
        fails.append("the row does not match its seal before any gate ran")
    blocking = [g for g in gate_results if g.get("blocks")]
    if blocking:
        reasons = "_".join(str(g.get("reason", "UNSPECIFIED")).upper().replace(" ", "_")
                           for g in blocking)
        row["action_status"] = f"{BLOCKED_PREFIX}{reasons}"
    else:
        row["action_status"] = row.get("action_status") or PASS_REFERENCE_ONLY
    row["gates_applied"] = [g.get("gate") for g in gate_results]
    row["blocking_gates"] = [g.get("gate") for g in blocking]
    # THE INVARIANT: gates may only have touched action_status. Anything else is a rewritten forecast.
    fails.extend(assert_only_action_changed(sealed_row, sealed_hash, row))
    return row, fails


def assert_only_action_changed(sealed_row, sealed_hash, gated_row):
    """The post-gate invariant, callable on its own.

    Separated from the pre-gate seal check because the two catch different bugs and a single
    fixture cannot tell them apart: the pre-check catches a row that never matched its seal, this
    catches a GATE IMPLEMENTATION that mutates content while running. Only this one can see a gate
    that nulls a probability on its way to blocking a row — which is precisely how a blocked row
    became a blank row on 2026-08-22."""
    if seal(gated_row) == sealed_hash:
        return []
    changed = [k for k in SEALED_KEYS if sealed_row.get(k) != gated_row.get(k)]
    return [f"a gate altered SEALED forecast content {changed} — a gate blocks an action, "
            f"it does not rewrite or delete a forecast"]


def gradeable(row):
    """(ok, reason). Every registered forecast is gradeable, whatever its action status."""
    if row.get("forecast_status") != FORECAST_REGISTERED:
        return False, f"forecast_status is {row.get('forecast_status')!r}"
    ok, f = validate_row(row, row.get("sport"))
    if not ok:
        return False, f"the row is incomplete: {f[0]}"
    return True, ("gradeable on every target it carries, the total included; action_status "
                  f"{row.get('action_status')!r} governs action only, and the total target is "
                  f"{TARGET_AUTHORITY['total']} regardless of it")


def validate_card(rows, scheduled_games, sport=None):
    """(ok, failures) for a whole card. THE NO-BLANK-ROW RULE lives here: every SCHEDULED game must
    appear, and appear complete. A game that was gated out of existence fails."""
    f = []
    by_game = {}
    for r in rows:
        g = r.get("game")
        if g in by_game:
            f.append(f"{g}: appears twice on one card")
        by_game[g] = r
    for g in scheduled_games:
        if g not in by_game:
            f.append(f"{g}: SCHEDULED but emitted no row — none becomes a blank row; a gate blocks "
                     f"an action, it does not remove a game from the card")
            continue
        ok, ff = validate_row(by_game[g], sport or by_game[g].get("sport"))
        f.extend(ff)
    for g in by_game:
        if g not in scheduled_games:
            f.append(f"{g}: emitted a row but is not on the scheduled slate")
    return (not f), f


def coverage(rows, scheduled_games):
    """The one-line summary the owner's self-test reports."""
    ok, f = validate_card(rows, scheduled_games)
    n_block = sum(1 for r in rows if str(r.get("action_status", "")).startswith(BLOCKED_PREFIX))
    n_grade = sum(1 for r in rows if gradeable(r)[0])
    return {"scheduled": len(scheduled_games), "emitted": len(rows), "gradeable": n_grade,
            "action_blocked": n_block, "contract_ok": ok, "failures": f,
            "verdict": (f"PASS — {n_grade}/{len(scheduled_games)} games forecasted"
                        if ok and n_grade == len(scheduled_games)
                        else f"FAIL — {n_grade}/{len(scheduled_games)} gradeable, {len(f)} failure(s)")}


def _row(game="A@B", **kw):
    r = {"game": game, "sport": "mlb", "model_id": "m.v1", "training_cutoff_utc": "2026-08-22T00:00:00Z",
         "information_class": "PARTIAL_STARTER_INFORMATION", "resolved_information_dose": 0.8,
         "simulation_seed": 20260823, "simulation_trials": 100000,
         "winner_probability": 0.55, "predicted_winner": "B",
         "projected_away_score": 4.1, "projected_home_score": 4.6, "projected_total": 8.7,
         "total_side": "OVER", "p_over": 0.6, "p_push": 0.0, "p_under": 0.4,
         "forecast_status": FORECAST_REGISTERED, "action_status": PASS_REFERENCE_ONLY,
         "fallback_applied": None}
    r.update(kw)
    return r


def selftest():
    f = []
    ok, ff = validate_row(_row())
    if not ok:
        f.append(f"a complete row was rejected: {ff}")

    # --- EVERY REQUIRED FIELD IS REQUIRED ---------------------------------------------------------
    for k in REQUIRED_FIELDS:
        r = _row()
        r.pop(k)
        if validate_row(r)[0]:
            f.append(f"a row missing {k} was accepted")
    # ATS only where the sport has a spread estimand
    if not validate_row(_row(sport="mlb"), "mlb")[0]:
        f.append("MLB was required to carry an ATS estimand")
    for sp in ATS_SPORTS:
        if validate_row(_row(sport=sp), sp)[0]:
            f.append(f"{sp} was accepted with no ATS selection or cover probability")
        if not validate_row(_row(sport=sp, ats_selection="B -3.5",
                                 ats_cover_probability=0.58), sp)[0]:
            f.append(f"{sp} with a complete ATS estimand was rejected")

    # --- THE CORE RULE: A BLOCKED ROW IS STILL A COMPLETE FORECAST ---------------------------------
    for status in ("BLOCKED_DOG_COMPRESSION", "BLOCKED_STALE_STATE_NO_INJURY_BYTES",
                   "BLOCKED_NEUTRAL_SITE_PARK_UNMODELED", NO_ACTION, PASS_REFERENCE_ONLY):
        r = _row(action_status=status)
        okr, ffr = validate_row(r)
        if not okr:
            f.append(f"a row with action_status {status} was rejected as a forecast: {ffr}")
        g, why = gradeable(r)
        if not g:
            f.append(f"a row with action_status {status} was not gradeable: {why}")
    # NULL PROJECTED SCORES: permitted with a reason, refused bare
    bare = _row(projected_away_score=None, projected_home_score=None)
    if validate_row(bare)[0]:
        f.append("a row with bare null projected scores was accepted")
    reasoned = _row(projected_away_score=None, projected_home_score=None,
                    projected_score_null_reason="this model forecasts a winner and a total and "
                                                "does not forecast per-team scores")
    okn, ffn = validate_row(reasoned)
    if not okn:
        f.append(f"a null projected score WITH a stated reason was refused: {ffn}")
    if not gradeable(reasoned)[0]:
        f.append("a row with reasoned null projected scores was not gradeable")
    # the projected TOTAL has no such exemption
    if validate_row(_row(projected_total=None,
                         projected_score_null_reason="stated"))[0]:
        f.append("a null projected_total was excused by the projected-score reason")
    # a NON-NUMERIC projected score is not a null and is not excused by any reason
    for bad in ("4.1", True, [], {}):
        if validate_row(_row(projected_away_score=bad,
                             projected_score_null_reason="stated"))[0]:
            f.append(f"projected_away_score={bad!r} was accepted as a projection")
    # a BLOCKED row that lost its numbers is exactly the 2026-08-22 defect
    for k in ("winner_probability", "projected_total"):
        r = _row(action_status="BLOCKED_DOG_COMPRESSION", **{k: None})
        if validate_row(r)[0]:
            f.append(f"a BLOCKED row with {k}=None was accepted — that is the 2026-08-22 defect: a "
                     f"gate emptied a forecast instead of blocking an action")
        if gradeable(r)[0]:
            f.append(f"a BLOCKED row with {k}=None was called gradeable")
    # a bare BLOCKED_ with no reason
    if validate_row(_row(action_status=BLOCKED_PREFIX))[0]:
        f.append("a bare BLOCKED_ with no reason was accepted")
    # forecast_status has exactly one legal value
    for bad in ("SUPPRESSED", "BLOCKED", "NOT_PRODUCED", "", None):
        if bad is None:
            continue
        if validate_row(_row(forecast_status=bad))[0]:
            f.append(f"forecast_status {bad!r} was accepted")

    # --- probabilities ------------------------------------------------------------------------------
    for bad in (0.0, 1.0, -0.2, 1.4, None, "0.5", True):
        if validate_row(_row(winner_probability=bad))[0]:
            f.append(f"winner_probability {bad!r} was accepted")
    if validate_row(_row(p_over=0.6, p_push=0.1, p_under=0.4))[0]:
        f.append("over+push+under = 1.1 was accepted")
    if not validate_row(_row(p_over=0.45, p_push=0.12, p_under=0.43))[0]:
        f.append("a whole-number total with real push mass was rejected")
    if validate_row(_row(resolved_information_dose=1.4))[0]:
        f.append("an information dose above 1 was accepted")
    if validate_row(_row(model_id=""))[0]:
        f.append("an empty model_id was accepted")
    if validate_row(_row(fallback_applied="SOMETHING_ELSE"))[0]:
        f.append("an undeclared fallback was accepted")
    for fb in list(FALLBACKS) + list(FALLBACKS.values()):
        if not validate_row(_row(fallback_applied=fb))[0]:
            f.append(f"the declared fallback {fb} was rejected")

    # --- THE OWNER'S THREE CASES PRODUCE FORECASTS, NOT BLANKS ---------------------------------------
    cases = (("MISSING_STARTER", "REGISTERED_CAP_FORECAST", "ALL_CAP_BASELINE", 0.0),
             ("STALE_STATE", "FROZEN_STATE_FORECAST", "PARTIAL_STARTER_INFORMATION", 0.7),
             ("NEUTRAL_SITE_UNCERTAINTY", "OUT_OF_DOMAIN_FORECAST", "PARTIAL_STARTER_INFORMATION", 0.8))
    for cause, produced, cls, dose in cases:
        r = _row(action_status=f"{BLOCKED_PREFIX}{cause}", fallback_applied=produced,
                 information_class=cls, resolved_information_dose=dose)
        okr, ffr = validate_row(r)
        if not okr:
            f.append(f"the {cause} case did not produce a valid forecast: {ffr}")
        if not gradeable(r)[0]:
            f.append(f"the {cause} case produced a forecast that was not gradeable")
        if FALLBACKS[cause] != produced:
            f.append(f"{cause} is declared to produce {FALLBACKS[cause]}, not {produced}")

    # --- SEALING: gates may touch action_status and NOTHING else -------------------------------------
    base = _row()
    h = seal(base)
    if seal(dict(base, action_status="BLOCKED_ANYTHING")) != h:
        f.append("the seal covers action_status, so a gate could never render one without "
                 "breaking its own seal")
    if seal(dict(base, winner_probability=0.56)) == h:
        f.append("the seal does not cover the winner probability")
    if seal(dict(base, projected_total=9.9)) == h:
        f.append("the seal does not cover the projected total")
    if seal(dict(base, model_id="other")) == h:
        f.append("the seal does not cover the model identity")
    row, ffg = apply_gates(base, h, [{"gate": "compression", "blocks": True,
                                      "reason": "dog compression"}])
    if ffg:
        f.append(f"a legitimate blocking gate reported seal failures: {ffg}")
    if not row["action_status"].startswith(BLOCKED_PREFIX) or "DOG_COMPRESSION" not in row["action_status"]:
        f.append(f"the blocking gate did not render its reason: {row['action_status']}")
    if row["winner_probability"] != base["winner_probability"]:
        f.append("a gate changed the winner probability")
    if not gradeable(row)[0]:
        f.append("a gated row stopped being gradeable")
    # a non-blocking gate leaves the row acting
    row2, _ = apply_gates(base, h, [{"gate": "freshness", "blocks": False}])
    if row2["action_status"].startswith(BLOCKED_PREFIX):
        f.append("a non-blocking gate blocked the row")
    # A GATE THAT REWRITES THE FORECAST IS REFUSED
    # ISOLATION for the PRE-gate check. Its message is distinct from the post-gate invariant's, and
    # only the pre-check can report that the row was already wrong BEFORE any gate ran — which is a
    # different fault (a bad seal, or a row edited between sealing and gating) from a gate that
    # mutates. Both fire on this input; the pre-check is proven by requiring ITS message.
    tampered = dict(base)
    _, ff2 = apply_gates(tampered, seal(dict(base, winner_probability=0.99)), [])
    if not ff2:
        f.append("a row that does not match its seal was accepted")
    elif not any("before any gate ran" in x for x in ff2):
        f.append(f"a pre-existing seal mismatch was reported only as a gate mutation, which "
                 f"misattributes the fault: {ff2}")
    # ISOLATION. The pre-gate check catches a row that never matched its seal; only the POST-gate
    # invariant catches a gate implementation that mutated content on its way to blocking a row.
    mutated = dict(base, action_status="BLOCKED_X", winner_probability=None)
    ff3 = assert_only_action_changed(base, h, mutated)
    if not ff3 or not any("altered SEALED forecast content" in x for x in ff3):
        f.append(f"a gate that nulled the winner probability while blocking was not caught: {ff3}")
    if "winner_probability" not in ff3[0]:
        f.append(f"the post-gate invariant did not name the field that changed: {ff3[0]}")
    # a gate that touched ONLY action_status passes the same invariant
    if assert_only_action_changed(base, h, dict(base, action_status="BLOCKED_X",
                                                gates_applied=["g"], blocking_gates=["g"])):
        f.append("the post-gate invariant fired on a gate that touched only action_status")

    # --- PIPELINE ORDER --------------------------------------------------------------------------------
    done = []
    for s in STAGES:
        okp, why = pipeline_gate(done, s)
        if not okp:
            f.append(f"in-order stage {s} was refused: {why}")
        done.append(s)
    if pipeline_gate(["GENERATE_FORECAST"], "APPLY_GATES")[0]:
        f.append("gates ran before the forecast was registered and sealed — the ordering that "
                 "removed six games from the 2026-08-22 record")
    if pipeline_gate(["GENERATE_FORECAST", "REGISTER_AND_SEAL", "APPLY_GATES"],
                     "GRADE_REGARDLESS_OF_ACTION_STATUS")[0]:
        f.append("grading ran before an action status was rendered")
    if pipeline_gate([], "GRADE_REGARDLESS_OF_ACTION_STATUS")[0]:
        f.append("grading ran with nothing before it")
    if pipeline_gate(list(STAGES), "SUPPRESS_ROW")[0]:
        f.append("an unknown stage was accepted into the pipeline")

    # --- CARD LEVEL: NO BLANK ROWS ---------------------------------------------------------------------
    sched = ["A@B", "C@D", "E@F"]
    rows = [_row("A@B"), _row("C@D", action_status="BLOCKED_STALE_STATE"), _row("E@F")]
    okc, ffc = validate_card(rows, sched)
    if not okc:
        f.append(f"a complete card was rejected: {ffc}")
    cov = coverage(rows, sched)
    if cov["verdict"] != "PASS — 3/3 games forecasted" or cov["action_blocked"] != 1:
        f.append(f"coverage summary wrong: {cov['verdict']} / blocked {cov['action_blocked']}")
    # THE DEFECT: a scheduled game that emitted no row
    okc, ffc = validate_card(rows[:2], sched)
    if okc or not any("none becomes a blank row" in x for x in ffc):
        f.append("a scheduled game with no emitted row was accepted")
    if coverage(rows[:2], sched)["verdict"].startswith("PASS"):
        f.append("coverage reported PASS with a game missing from the card")
    # a row for a game that is not on the slate
    if validate_card(rows + [_row("G@H")], sched)[0]:
        f.append("a row for an unscheduled game was accepted")
    # a duplicated game
    if validate_card(rows + [_row("A@B")], sched)[0]:
        f.append("a game appearing twice on one card was accepted")

    # --- totals: mandatory, gradable, never decision-bearing (owner directive 2026-08-24) --------
    if TARGET_AUTHORITY["total"] != "NEVER_DECISION_BEARING":
        f.append("the total target must be NEVER_DECISION_BEARING")
    if TARGET_AUTHORITY["winner"] == TARGET_AUTHORITY["total"]:
        f.append("winner and total must not share a decision authority")
    _r = _row()
    ok0, _ = validate_row(_r, _r.get("sport"))
    if not ok0:
        f.append("fixture is wrong: the base row must validate before the total rules are tested")
    # still MANDATORY
    ok1, f1 = validate_row(dict(_r, projected_total=None), _r.get("sport"))
    if ok1 or not any("missing forecast" in x for x in f1):
        f.append("a null projected_total must still be a missing forecast")
    # still GRADABLE
    g_ok, g_why = gradeable(_r)
    if not g_ok or "total" not in g_why:
        f.append(f"a complete row must be gradeable on the total too, got {g_why}")
    # but NEVER DECISION-BEARING
    # NAMED explicitly, not iterated over TOTAL_DECISION_FIELDS: a loop over the list under test
    # cannot fail when the list is emptied, which is a fixture that guards nothing (lesson 24).
    for bad_field in ("total_action_status", "total_selection", "total_stake_u", "total_bet",
                      "total_authorized", "ou_selection", "ou_stake_u"):
        if bad_field not in TOTAL_DECISION_FIELDS:
            f.append(f"{bad_field} must be on the refused-decision list")
        ok2, f2 = validate_row(dict(_r, **{bad_field: "OVER 8.5"}), _r.get("sport"))
        if ok2 or not any(TOTAL_DECISION_ATTEMPT in x for x in f2):
            f.append(f"{bad_field} must be refused as a decision on the total")
    # a total side alongside a BET action is refused even though each alone is fine
    ok3, f3 = validate_row(dict(_r, total_side="OVER", action_status="BET_ML_HOME"), _r.get("sport"))
    if ok3 or not any(TOTAL_DECISION_ATTEMPT in x for x in f3):
        f.append("a total side on a BET row must be refused")
    ok4, _ = validate_row(dict(_r, total_side="OVER"), _r.get("sport"))
    if not ok4:
        f.append("a total side on a reference-only row is fine and must still validate")

    print("forecast_contract selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("the total acquires decision authority",
     'TARGET_AUTHORITY = {\n    "winner": "GATE_GOVERNED",\n    "total": "NEVER_DECISION_BEARING",',
     'TARGET_AUTHORITY = {\n    "winner": "GATE_GOVERNED",\n    "total": "GATE_GOVERNED",'),
    ("decision fields on the total stop being refused",
     "        if row.get(k) not in (None, \"\", \"NONE\"):", "        if False:"),
    ("the decision-field list is emptied",
     'TOTAL_DECISION_FIELDS = ("total_action_status", "total_selection", "total_stake_u",\n                         "total_bet", "total_authorized", "ou_selection", "ou_stake_u")',
     "TOTAL_DECISION_FIELDS = ()"),
    ("a total side may ride along with a BET action",
     '    if row.get("total_side") is not None and str(row.get("action_status", "")).startswith(BET_PREFIX):',
     "    if False:"),
    ("the total stops being mandatory",
     "    if tv is None or isinstance(tv, bool) or not isinstance(tv, (int, float)):", "    if False:"),
    ("a required field stops being required",
     "    for k in REQUIRED_FIELDS:\n        if k not in row:", "    for k in ():\n        if k not in row:"),
    ("ATS is no longer required for a spread sport",
     "    if sport in ATS_SPORTS:", "    if False:"),
    ("ATS is demanded of MLB, which has no spread estimand here",
     "    if sport in ATS_SPORTS:", "    if True:"),
    ("a BLOCKED row may carry an empty winner probability — the 2026-08-22 defect",
     "    if p is None or not isinstance(p, (int, float)) or isinstance(p, bool) or not (0.0 < float(p) < 1.0):",
     "    if False:"),
    ("a bare null projected score is accepted",
     '            if not row.get("projected_score_null_reason"):', "            if False:"),
    ("a null projected TOTAL is excused like a projected score",
     "    if tv is None or isinstance(tv, bool) or not isinstance(tv, (int, float)):",
     "    if False:"),
    ("a non-numeric projected score is accepted",
     "        elif isinstance(v, bool) or not isinstance(v, (int, float)):", "        elif False:"),
    ("over/push/under need not sum to one",
     "    elif abs(sum(float(x) for x in probs) - 1.0) > 1e-6:", "    elif False:"),
    ("push mass is assumed zero, so a whole-number total is rejected",
     "    elif abs(sum(float(x) for x in probs) - 1.0) > 1e-6:",
     '    elif abs(float(row.get("p_push") or 0.0)) > 1e-9:'),
    ("forecast_status accepts a suppressed value",
     "    if fs is not None and fs not in FORECAST_STATUSES:", "    if False:"),
    ("SUPPRESSED becomes a legal forecast status",
     'FORECAST_STATUSES = (FORECAST_REGISTERED,)', 'FORECAST_STATUSES = (FORECAST_REGISTERED, "SUPPRESSED")'),
    ("a bare BLOCKED_ with no reason is accepted",
     "    if a.startswith(BLOCKED_PREFIX) and len(a) <= len(BLOCKED_PREFIX):", "    if False:"),
    ("an undeclared fallback is accepted",
     "    if fb not in (None, \"NONE\") and fb not in FALLBACKS.values() and fb not in FALLBACKS:",
     "    if False:"),
    ("the seal covers action_status, so no gate could render one",
     '    payload = {k: row.get(k) for k in SEALED_KEYS if k in row}',
     '    payload = {k: row.get(k) for k in list(SEALED_KEYS) + ["action_status"] if k in row}'),
    ("the seal stops covering the forecast values",
     "SEALED_KEYS = tuple(k for k in REQUIRED_FIELDS if k not in (\"action_status\",)) + ATS_FIELDS",
     'SEALED_KEYS = ("game",)'),
    ("a gate may rewrite sealed forecast content",
     "    if seal(gated_row) == sealed_hash:\n        return []",
     "    if True:\n        return []"),
    ("the pre-gate seal check is dropped",
     '    if seal(row) != sealed_hash:\n        fails.append("the row does not match its seal before any gate ran")',
     '    if False:\n        fails.append("the row does not match its seal before any gate ran")'),
    ("a blocking gate no longer renders its reason",
     '        row["action_status"] = f"{BLOCKED_PREFIX}{reasons}"',
     '        row["action_status"] = BLOCKED_PREFIX'),
    ("a blocking gate suppresses the row instead of blocking the action",
     '        row["action_status"] = f"{BLOCKED_PREFIX}{reasons}"',
     '        row["action_status"] = f"{BLOCKED_PREFIX}{reasons}"; row["winner_probability"] = None'),
    ("a blocked row stops being gradeable",
     '    if row.get("forecast_status") != FORECAST_REGISTERED:',
     '    if str(row.get("action_status", "")).startswith(BLOCKED_PREFIX):'),
    ("pipeline stages may run out of order",
     "    missing = [s for s in STAGES[:i] if s not in done]", "    missing = []"),
    ("an unknown pipeline stage is accepted",
     "    if proposed not in STAGE_ORDER:", "    if False:"),
    ("gates are moved BEFORE registration",
     'STAGES = ("GENERATE_FORECAST", "REGISTER_AND_SEAL", "APPLY_GATES",',
     'STAGES = ("GENERATE_FORECAST", "APPLY_GATES", "REGISTER_AND_SEAL",'),
    ("a scheduled game may emit no row at all",
     "        if g not in by_game:", "        if False:"),
    ("a row for an unscheduled game is accepted",
     "        if g not in scheduled_games:", "        if False:"),
    ("a duplicated game on one card is accepted",
     "        if g in by_game:", "        if False:"),
    ("coverage reports PASS while games are missing",
     "                        if ok and n_grade == len(scheduled_games)", "                        if True"),
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
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    if "--mutants" in sys.argv:
        sys.exit(1 if mutation_suite() else 0)
    print(__doc__)
