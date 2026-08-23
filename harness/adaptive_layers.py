#!/usr/bin/env python3
"""ADAPTIVE LAYERS — three speeds, and a list of things that never move on their own.

OWNER SPECIFICATION 2026-08-23:
    "Controlled adaptive learning, not a model that rewrites itself after every bad night."

    FAST   after every tier-1 settlement   team ratings, pitcher state, availability, uncertainty
    MEDIUM every 50-100 eligible games     calibration, recency weights, residual variance
    SLOW   formal model release            features, architecture, thresholds and action rules

    "Governance, evidence tiers, deadbands and wager authority should never adapt automatically."

THE POINT OF SEPARATING SPEEDS is that a system which can change anything at any time cannot be
audited, because no observation constrains it. Ratings that move nightly and thresholds that move
nightly look identical from the outside; only the second is a model chasing its losses. Binding each
quantity to a layer makes "the model changed" a checkable claim about WHICH quantity moved and
WHETHER it was allowed to.

THE NEVER-ADAPT LIST IS NOT A LAYER. It is not the slowest speed — it is outside the mechanism
entirely. Nothing on it changes without an owner decision, and no accumulation of evidence, no
promotion, and no drift alarm is a substitute for one. A drift alarm that could relax a deadband
would be a system that widens its own permissions exactly when it is performing worst.

THE TEMPORAL RULE, which no layer may violate:
    a result from game A may update the model for LATER games, never game A itself and never another
    game that has already started.
This is the same leakage rule that governs forecasts, applied to learning. A rating refreshed at
23:10Z may not be used by a game that began at 23:05Z, however much better the newer rating is.
"""
from __future__ import annotations

import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FAST = "FAST"
MEDIUM = "MEDIUM"
SLOW = "SLOW"
NEVER = "NEVER_ADAPTS_AUTOMATICALLY"

# ---------------------------------------------------------------------------------------------
# The register. Every adaptive quantity in the system belongs to exactly one layer. A quantity that
# is not in this register cannot be updated by the learning cycle at all: an unregistered quantity
# is an unaudited one, so the default is refusal, not permission.
# ---------------------------------------------------------------------------------------------
LAYERS = {
    # OWNER REASSIGNMENT 2026-08-23 (second specification). The first cut put team ratings and
    # pitcher posteriors in FAST and calibration in MEDIUM. The owner moved both a notch slower:
    # ratings and posteriors are MEDIUM, calibration and park effects are SLOW. The direction is
    # deliberate — the quantities that move a forecast the furthest now move the least often, and
    # only availability-type facts, which genuinely change day to day, update nightly.
    FAST: {
        "trigger": "every tier-1 settlement — availability-type facts only",
        "quantities": (
            "player_availability", "confirmed_inactives", "bullpen_workload",
            "bullpen_availability", "recent_lineup", "recent_minutes",
            "expected_innings_distribution", "expected_pitch_count_distribution",
            "empirical_uncertainty_by_information_class",
            "wnba_player_availability", "wnba_projected_minutes", "wnba_lineup_continuity",
            "wnba_rest_travel_state", "rest_travel_state", "roster_cuts",
            "expected_quarterback_rotation", "snap_shares",
        )},
    MEDIUM: {
        "trigger": "every 50-100 eligible games — ratings and posteriors",
        "quantities": (
            "expanding_home_prior", "team_offensive_strength", "team_defensive_strength",
            "recent_form_decayed", "recency_decay_weights", "starter_profile",
            "pitcher_posterior", "player_posterior", "residual_variance",
            "wnba_team_strength", "wnba_pace", "wnba_offensive_efficiency",
            "wnba_defensive_efficiency", "wnba_margin_residual_variance",
            "wnba_total_residual_variance", "depth_chart_quality",
        )},
    SLOW: {
        "trigger": "formal model release only — global coefficients, park effects, calibration",
        "quantities": (
            "global_coefficients", "park_effects", "park_residual_distribution",
            "weather_residual_distribution", "calibration_intercept", "calibration_slope",
            "wnba_winner_head_calibration", "wnba_home_court_state",
            "feature_set", "model_architecture", "action_thresholds", "action_rules",
            "trust_ladder_definition", "compression_gate_threshold",
            "coach_preseason_tendencies",
        )},
    NEVER: {
        "trigger": "owner decision only — no evidence, promotion or alarm substitutes for one",
        "quantities": (
            "evidence_tier_definitions", "temporal_leakage_rules", "timing_gates",
            "source_provenance_requirements", "same_book_devig_requirement",
            "ats_deadbands", "market_prices_as_predictive_features",
            "registered_forecast_bytes", "immutable_identities", "grading_definitions",
            "wager_authority", "promotion_standards",
        )},
}

MEDIUM_MIN_GAMES = 50
MEDIUM_MAX_GAMES = 100

_INDEX = {q: layer for layer, spec in LAYERS.items() for q in spec["quantities"]}


def layer_of(quantity):
    """The layer a quantity belongs to, or None if it is not registered."""
    return _INDEX.get(quantity)


def may_update(quantity, layer, eligible_games_since_last=None):
    """(ok, reason) for a proposed automatic update.

    Refusal is the default. An unregistered quantity, a quantity proposed at the wrong speed, and
    anything on the never-adapt list are all refused with the reason named."""
    home = layer_of(quantity)
    if home is None:
        return False, (f"{quantity!r} is not in the adaptive register — an unregistered quantity is "
                       f"an unaudited one, so it cannot be updated automatically at any speed")
    if home == NEVER:
        return False, (f"{quantity!r} is on the never-adapt list. It changes by owner decision only; "
                       f"no accumulation of evidence, promotion or drift alarm substitutes for one")
    if layer != home:
        return False, (f"{quantity!r} belongs to the {home} layer and was proposed at {layer} — a "
                       f"quantity updated at the wrong speed is not the quantity that was audited")
    if home == MEDIUM:
        if eligible_games_since_last is None:
            return False, (f"{quantity!r} is a MEDIUM-layer quantity and no eligible-game count was "
                           f"supplied; the cadence is the control, so it must be stated")
        if eligible_games_since_last < MEDIUM_MIN_GAMES:
            return False, (f"{quantity!r} may update every {MEDIUM_MIN_GAMES}-{MEDIUM_MAX_GAMES} "
                           f"eligible games; only {eligible_games_since_last} have accrued. "
                           f"Recalibrating sooner is recalibrating on the last bad night")
    if home == SLOW:
        return False, (f"{quantity!r} is a SLOW-layer quantity and changes only at a formal model "
                       f"release, never inside the daily cycle")
    return True, f"{quantity!r} may update at {home}"


def release_update(quantity):
    """(ok, reason) for a change made as part of a FORMAL MODEL RELEASE rather than automatically."""
    home = layer_of(quantity)
    if home is None:
        return False, f"{quantity!r} is not in the adaptive register"
    if home == NEVER:
        return False, (f"{quantity!r} is on the never-adapt list — a model release is still not an "
                       f"owner decision about governance")
    return True, f"{quantity!r} may change at a formal release (home layer {home})"


# ---------------------------------------------------------------------------------------------
# THE TEMPORAL RULE
# ---------------------------------------------------------------------------------------------

def may_inform(source_game, target_game):
    """(ok, reason). May the SETTLED result of source_game update the model used for target_game?

    Requires both a settlement time and a target start time, and refuses when either is missing:
    a learning step that cannot prove it is not leaking is a learning step that is leaking."""
    st = source_game.get("settled_at_utc")
    ss = source_game.get("start_utc")
    ts = target_game.get("start_utc")
    if not st or not ts:
        return False, ("cannot establish ordering: a settlement time and a target start time are "
                       "both required, and an unprovable update is refused")
    if source_game.get("game_id") is not None and source_game.get("game_id") == target_game.get("game_id"):
        return False, ("a game's own result may never inform its own forecast — that is the "
                       "leakage the whole registry exists to prevent")
    if ts <= st:
        return False, (f"target starts {ts}, source settled {st}: a game that has already started "
                       f"cannot receive an update, however much better the newer state is")
    if ss and ts <= ss:
        return False, (f"target starts {ts}, source started {ss}: the two games overlap, so the "
                       f"source cannot be a completed input to the target")
    return True, f"source settled {st} precedes target start {ts}"


def filter_targets(source_game, targets):
    """The targets a settled result is permitted to update, and the refusals with their reasons."""
    ok, bad = [], []
    for t in targets:
        good, why = may_inform(source_game, t)
        (ok if good else bad).append(dict(t, reason=why) if not good else t)
    return ok, bad


# ---------------------------------------------------------------------------------------------
# THE SAFE DAILY LEARNING CYCLE — nine steps, in order, each with a precondition.
# ---------------------------------------------------------------------------------------------
CYCLE = (
    ("acquire_tier1_final", "a tier-1 final exists for the game"),
    ("validate_identity", "date, teams, game id, venue and FINAL status all validated"),
    ("settle_immutable_forecast", "the forecast is settled without being altered"),
    ("append_outcome", "the outcome is APPENDED; the forecast is never rewritten"),
    ("build_asof_snapshot_for_future_games_only", "a new as-of snapshot is built for LATER games"),
    ("update_adaptive_ratings", "FAST-layer quantities update"),
    ("generate_challenger", "a challenger model is generated"),
    ("evaluate_against_champion_and_baseline", "paired evaluation on identical games"),
    ("hold_challenger_shadow_only", "the challenger stays shadow-only until promotion gates pass"),
)
CYCLE_ORDER = {name: i for i, (name, _) in enumerate(CYCLE)}


def cycle_gate(completed_steps, proposed_step):
    """(ok, reason). Steps run in order and none may be skipped.

    Order is not bureaucracy here: updating ratings BEFORE the outcome is appended means learning
    from a result the registry has no record of, and generating a challenger before the as-of
    snapshot means learning from a snapshot that already contains the target game."""
    if proposed_step not in CYCLE_ORDER:
        return False, f"{proposed_step!r} is not a step in the learning cycle"
    i = CYCLE_ORDER[proposed_step]
    done = {s for s in completed_steps if s in CYCLE_ORDER}
    missing = [n for n, _ in CYCLE[:i] if n not in done]
    if missing:
        return False, f"{proposed_step!r} proposed with earlier step(s) not completed: {missing}"
    return True, f"{proposed_step!r} may run"


def selftest():
    f = []
    # --- the register --------------------------------------------------------------------------
    # The owner's 2026-08-23 assignment, quantity by quantity. These are the ONLY speeds these
    # quantities may run at, and the reassignment moved ratings/posteriors slower and calibration
    # slower still.
    for q, want in (("player_availability", FAST), ("bullpen_workload", FAST),
                    ("recent_minutes", FAST), ("recent_lineup", FAST),
                    ("empirical_uncertainty_by_information_class", FAST),
                    ("team_offensive_strength", MEDIUM), ("team_defensive_strength", MEDIUM),
                    ("starter_profile", MEDIUM), ("pitcher_posterior", MEDIUM),
                    ("expanding_home_prior", MEDIUM), ("residual_variance", MEDIUM),
                    ("recency_decay_weights", MEDIUM),
                    ("calibration_slope", SLOW), ("calibration_intercept", SLOW),
                    ("park_effects", SLOW), ("global_coefficients", SLOW),
                    ("feature_set", SLOW), ("action_thresholds", SLOW),
                    ("timing_gates", NEVER), ("immutable_identities", NEVER),
                    ("ats_deadbands", NEVER), ("wager_authority", NEVER),
                    ("market_prices_as_predictive_features", NEVER),
                    ("evidence_tier_definitions", NEVER), ("promotion_standards", NEVER),
                    ("registered_forecast_bytes", NEVER), ("grading_definitions", NEVER),
                    ("temporal_leakage_rules", NEVER), ("source_provenance_requirements", NEVER),
                    ("same_book_devig_requirement", NEVER)):
        if layer_of(q) != want:
            f.append(f"{q} is registered at {layer_of(q)}, expected {want}")
    # every quantity belongs to exactly one layer
    seen = {}
    for layer, spec in LAYERS.items():
        for q in spec["quantities"]:
            if q in seen:
                f.append(f"{q} appears in both {seen[q]} and {layer}")
            seen[q] = layer

    # --- NOTHING on the never-adapt list may move, by any route ----------------------------------
    for q in LAYERS[NEVER]["quantities"]:
        for layer in (FAST, MEDIUM, SLOW):
            ok, why = may_update(q, layer, eligible_games_since_last=10 ** 6)
            if ok:
                f.append(f"{q} was allowed to update at {layer} — it is on the never-adapt list")
        ok, why = release_update(q)
        if ok:
            f.append(f"{q} was allowed to change at a formal release — a release is not an owner "
                     f"decision about governance")
    # ...including with an enormous sample behind it
    ok, _ = may_update("ats_deadbands", MEDIUM, eligible_games_since_last=10 ** 9)
    if ok:
        f.append("a billion games unlocked the ATS deadbands")
    # ISOLATION. Proposing a never-adapt quantity AT the NEVER layer passes the layer-match check,
    # so only the never-adapt guard itself can refuse it (lesson 24: overlapping rules prove the
    # stricter one and decorate the other).
    for q in LAYERS[NEVER]["quantities"]:
        if may_update(q, NEVER, eligible_games_since_last=10 ** 6)[0]:
            f.append(f"{q} was permitted when proposed at its own NEVER layer — only the "
                     f"never-adapt guard can catch this")
    # ISOLATION. An unregistered quantity with no declared layer: the layer-match check cannot fire
    # because there is nothing to mismatch, so only the registration check can refuse it.
    if may_update("some_new_knob", None, 500)[0]:
        f.append("an unregistered quantity with no declared layer was permitted — only the "
                 "registration check can catch this")

    # --- speed enforcement ------------------------------------------------------------------------
    if not may_update("player_availability", FAST)[0]:
        f.append("a FAST quantity was refused at FAST")
    if may_update("player_availability", MEDIUM, 100)[0]:
        f.append("a FAST quantity was accepted at MEDIUM — the wrong speed is the wrong quantity")
    # RATINGS ARE NO LONGER NIGHTLY. This is the substance of the owner's reassignment: a team
    # rating that moves after every settlement is a rating that chases the last result.
    if may_update("team_offensive_strength", FAST)[0]:
        f.append("TEAM RATINGS were accepted at FAST — they move at MEDIUM now, so one night "
                 "cannot move them")
    if may_update("pitcher_posterior", FAST)[0]:
        f.append("a PITCHER POSTERIOR was accepted at FAST")
    if not may_update("team_offensive_strength", MEDIUM, 50)[0]:
        f.append("team ratings were refused at MEDIUM with a full cadence")
    if may_update("team_offensive_strength", MEDIUM, 49)[0]:
        f.append("team ratings updated after 49 eligible games; the floor is 50")
    # CALIBRATION IS NOW SLOW — it moves at a formal release, not on a cadence at all.
    for layer, n in ((FAST, None), (MEDIUM, 500), (MEDIUM, 50)):
        if may_update("calibration_slope", layer, n)[0]:
            f.append(f"CALIBRATION was accepted at {layer} with n={n} — it is a SLOW quantity now "
                     f"and changes only at a formal model release")
    if not release_update("calibration_slope")[0]:
        f.append("calibration was refused at a formal release, where it now belongs")
    if may_update("park_effects", MEDIUM, 500)[0]:
        f.append("PARK EFFECTS were accepted at MEDIUM; they are SLOW")
    if may_update("residual_variance", MEDIUM)[0]:
        f.append("a MEDIUM update was accepted with NO game count supplied")
    if may_update("feature_set", SLOW)[0]:
        f.append("a SLOW quantity was accepted inside the automatic path")
    if not release_update("feature_set")[0]:
        f.append("a SLOW quantity was refused at a formal release")
    if not release_update("calibration_slope")[0]:
        f.append("a MEDIUM quantity was refused at a formal release")
    # an unregistered quantity is refused everywhere
    for layer in (FAST, MEDIUM, SLOW):
        if may_update("some_new_knob", layer, 500)[0]:
            f.append(f"an UNREGISTERED quantity was accepted at {layer}")
    if release_update("some_new_knob")[0]:
        f.append("an unregistered quantity was accepted at a formal release")

    # --- the temporal rule --------------------------------------------------------------------
    src = {"game_id": "A", "start_utc": "2026-08-22T23:05:00Z", "settled_at_utc": "2026-08-23T02:10:00Z"}
    later = {"game_id": "B", "start_utc": "2026-08-23T23:05:00Z"}
    started = {"game_id": "C", "start_utc": "2026-08-22T23:05:00Z"}
    if not may_inform(src, later)[0]:
        f.append(f"a settled result was refused for a game the next day: {may_inform(src, later)[1]}")
    if may_inform(src, src)[0]:
        f.append("a game's own result was allowed to inform its own forecast")
    if may_inform(src, started)[0]:
        f.append("a result was allowed to update a game that had ALREADY STARTED")
    # a game starting exactly at the settlement instant is not later
    if may_inform(src, {"game_id": "D", "start_utc": src["settled_at_utc"]})[0]:
        f.append("a game starting exactly at the settlement instant was treated as later")
    # ISOLATION for the self-reference rule. A postponed game keeps its game_id and acquires a LATER
    # start time, so the ordering checks all pass and only the identity check can refuse it.
    if may_inform(src, {"game_id": "A", "start_utc": "2026-08-23T23:05:00Z"})[0]:
        f.append("a rescheduled game with the SAME game_id was allowed to learn from its own "
                 "earlier settlement — only the identity check can catch this")
    # ISOLATION for the overlap rule. A MIS-STAMPED settlement time earlier than its own start is
    # the only way a concurrent game can pass the settlement-ordering check; the overlap rule is the
    # guard against exactly that corruption, and nothing else catches it.
    corrupt = {"game_id": "E", "start_utc": "2026-08-22T23:05:00Z",
               "settled_at_utc": "2026-08-22T20:00:00Z"}
    if may_inform(corrupt, {"game_id": "F", "start_utc": "2026-08-22T22:00:00Z"})[0]:
        f.append("a game settled BEFORE its own start time was allowed to inform a game already "
                 "under way — only the overlap rule can catch this")
    # missing times are refused, never assumed
    if may_inform({"game_id": "A"}, later)[0]:
        f.append("an update with no settlement time was permitted")
    if may_inform(src, {"game_id": "B"})[0]:
        f.append("an update to a target with no start time was permitted")
    okt, badt = filter_targets(src, [later, started, src])
    if len(okt) != 1 or okt[0]["game_id"] != "B" or len(badt) != 2:
        f.append(f"filter_targets partitioned wrongly: {len(okt)} allowed, {len(badt)} refused")
    if badt and not all("reason" in b for b in badt):
        f.append("a refused target carried no reason")

    # --- the nine-step cycle ----------------------------------------------------------------------
    names = [n for n, _ in CYCLE]
    if len(names) != 9:
        f.append(f"the learning cycle has {len(names)} steps, not 9")
    done = []
    for n in names:
        ok, why = cycle_gate(done, n)
        if not ok:
            f.append(f"in-order step {n} was refused: {why}")
        done.append(n)
    # the two orderings that matter most
    if cycle_gate(["acquire_tier1_final", "validate_identity", "settle_immutable_forecast"],
                  "update_adaptive_ratings")[0]:
        f.append("ratings updated BEFORE the outcome was appended — learning from a result the "
                 "registry has no record of")
    if cycle_gate(names[:5], "evaluate_against_champion_and_baseline")[0]:
        f.append("evaluation ran before a challenger was generated")
    if cycle_gate([], "hold_challenger_shadow_only")[0]:
        f.append("the final step ran with nothing before it")
    if cycle_gate(names, "retrain_everything")[0]:
        f.append("an unknown step was accepted into the cycle")
    # the snapshot step must precede rating updates, not follow them
    if CYCLE_ORDER["build_asof_snapshot_for_future_games_only"] > CYCLE_ORDER["update_adaptive_ratings"]:
        f.append("the as-of snapshot is built AFTER ratings update; the snapshot would contain the "
                 "target game")
    if CYCLE_ORDER["append_outcome"] < CYCLE_ORDER["settle_immutable_forecast"]:
        f.append("the outcome is appended before the forecast is settled")

    print("adaptive_layers selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("the never-adapt list becomes just another layer",
     '    if home == NEVER:\n        return False, (f"{quantity!r} is on the never-adapt list.',
     '    if False:\n        return False, (f"{quantity!r} is on the never-adapt list.'),
    ("a formal release may change governance",
     '        return False, (f"{quantity!r} is on the never-adapt list — a model release is still not an "',
     '        pass; _unused = (f"{quantity!r} release "'),
    ("an unregistered quantity defaults to PERMITTED instead of refused",
     "    if home is None:\n        return False, (f\"{quantity!r} is not in the adaptive register",
     "    if False:\n        return False, (f\"{quantity!r} is not in the adaptive register"),
    ("layer membership is no longer enforced, so calibration may move nightly",
     "    if layer != home:", "    if False:"),
    ("the MEDIUM cadence floor is removed",
     "        if eligible_games_since_last < MEDIUM_MIN_GAMES:", "        if False:"),
    ("the MEDIUM cadence floor is lowered to a single game",
     "MEDIUM_MIN_GAMES = 50", "MEDIUM_MIN_GAMES = 1"),
    ("a MEDIUM update no longer has to state its game count",
     "        if eligible_games_since_last is None:", "        if False:"),
    ("SLOW quantities become updatable inside the daily cycle",
     '    if home == SLOW:\n        return False, (f"{quantity!r} is a SLOW-layer quantity', "    if False:\n        return False, (f\"{quantity!r} is a SLOW-layer quantity"),
    ("a game may inform its own forecast",
     '    if source_game.get("game_id") is not None and source_game.get("game_id") == target_game.get("game_id"):',
     "    if False:"),
    ("a game that has already started may still receive an update",
     "    if ts <= st:", "    if False:"),
    ("the start-time boundary becomes inclusive, so a game starting at settlement counts as later",
     "    if ts <= st:", "    if ts < st:"),
    ("overlapping games are treated as sequential",
     "    if ss and ts <= ss:", "    if False:"),
    ("a missing timestamp is assumed safe instead of refused",
     "    if not st or not ts:", "    if False:"),
    ("filter_targets puts refusals in the permitted list",
     "        (ok if good else bad).append(dict(t, reason=why) if not good else t)",
     "        (ok).append(t)"),
    ("cycle steps may run out of order",
     "    missing = [n for n, _ in CYCLE[:i] if n not in done]", "    missing = []"),
    ("an unknown step is accepted into the cycle",
     "    if proposed_step not in CYCLE_ORDER:", "    if False:"),
    ("ratings update before the outcome is appended",
     '    ("append_outcome", "the outcome is APPENDED; the forecast is never rewritten"),\n    ("build_asof_snapshot_for_future_games_only", "a new as-of snapshot is built for LATER games"),\n    ("update_adaptive_ratings", "FAST-layer quantities update"),',
     '    ("update_adaptive_ratings", "FAST-layer quantities update"),\n    ("append_outcome", "the outcome is APPENDED; the forecast is never rewritten"),\n    ("build_asof_snapshot_for_future_games_only", "a new as-of snapshot is built for LATER games"),'),
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
    if "--register" in sys.argv:
        for layer in (FAST, MEDIUM, SLOW, NEVER):
            print(f"\n{layer}  ({LAYERS[layer]['trigger']})")
            for q in LAYERS[layer]["quantities"]:
                print(f"    {q}")
        sys.exit(0)
    print(__doc__)
