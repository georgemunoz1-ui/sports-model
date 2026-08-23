#!/usr/bin/env python3
"""THREE-ARM CARD — baseline, champion and challenger on every scheduled game, prices last.

OWNER SPECIFICATION 2026-08-23:
    * baseline: expanding prior / simple reference
    * champion: currently deployed sport-specific model
    * challenger: adaptive ratings, updated player availability and uncertainty
    * same schedule, cutoff, evidence and keyed seeds for all arms
    * every scheduled game receives all three forecasts
    * pregame starter/lineup/injury changes may fork a new cohort
    * prices update only the ACTION OVERLAY, not winner probabilities
    * post-start updates are counterfactual and prospectively ineligible
    * grade all arms separately by sport, estimand and information dose

PRICES ARE SEPARATED STRUCTURALLY, NOT BY DISCIPLINE. action_overlay() receives the SEALED forecast
and the prices, and returns ONLY action fields. It has no parameter through which a probability
could be returned and no path that writes one, and the seal is re-checked after it runs. This is the
same shape as the gate rule in forecast_contract: a thing that may say "do not act" must not be able
to say "and here is a different number".

WHY THAT MATTERS MORE THAN IT SOUNDS. Market prices are the single most predictive input available
and are permanently barred as features. A price that reaches a winner probability by any route —
directly, through a de-vig, through a "sanity adjustment" — destroys every downstream comparison,
because the model would then be scored against a benchmark it had already read. The barrier has to
be structural because the temptation is permanent.

EVERY ARM SHARES THE SCHEDULE, THE CUTOFF AND THE EVIDENCE. Not "should share" — the builder takes
ONE slate, ONE information cutoff and ONE evidence hash and stamps all three arms from them, so
there is no code path that could give two arms different inputs. Seeds are keyed per game and per
arm, so the arms are independent of each other and of slate composition.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forecast_contract as FC
import keyed_seed as KS

BASELINE = "BASELINE"
CHAMPION = "CHAMPION"
CHALLENGER = "CHALLENGER"
ARMS = (BASELINE, CHAMPION, CHALLENGER)

# Anything a price could arrive under. None of these may appear in a forecast row.
PRICE_FIELDS = ("ml_away", "ml_home", "moneyline", "price", "odds", "spread", "total_line_price",
                "close_ml_away", "close_ml_home", "implied", "no_vig", "devig", "overround",
                "book", "market_p_home")
# Fields the overlay is permitted to write. Nothing else.
OVERLAY_FIELDS = ("action_status", "action_reason", "market_number", "raw_edge_pp",
                  "empirical_edge_sd_pp", "conservative_edge_pp", "sigma", "passes_screen",
                  "overround_pct", "devig_basis", "price_captured_utc", "price_source")


def build_row(game, arm, p_home, projections, slate_date, model_id, simulation_version,
              information_class, information_fraction, named_cap_slots, verified_profile_slots,
              training_cutoff_utc, feature_cutoff_utc, evaluation_arm_id, sport,
              ats=None, fallback_applied=None, uncertainty=None,
              projected_score_null_reason=None):
    """One arm's forecast for one game, in the shape forecast_contract demands.

    Carries NO price field of any kind. The overlay adds those later, after sealing."""
    gid = game["game_id"]
    seed = KS.seed_for(model_id, slate_date, gid, simulation_version)
    row = {
        "game": gid, "sport": sport, "arm": arm,
        "evaluation_arm_id": evaluation_arm_id,
        "model_id": model_id,
        "training_cutoff_utc": training_cutoff_utc,
        "feature_cutoff_utc": feature_cutoff_utc,
        "information_class": information_class,
        "resolved_information_dose": information_fraction,
        "named_cap_slots": named_cap_slots,
        "verified_profile_slots": verified_profile_slots,
        "simulation_seed": seed,
        "simulation_trials": projections.get("trials"),
        "simulation_version": simulation_version,
        "winner_probability": max(float(p_home), 1.0 - float(p_home)),
        "p_home": float(p_home),
        "predicted_winner": game["home"] if p_home >= 0.5 else game["away"],
        "projected_away_score": projections.get("away"),
        "projected_home_score": projections.get("home"),
        "projected_total": projections.get("total"),
        "total_side": projections.get("total_side"),
        "p_over": projections.get("p_over"),
        "p_push": projections.get("p_push"),
        "p_under": projections.get("p_under"),
        "game_start_utc": game.get("start_utc"),
        "forecast_status": FC.FORECAST_REGISTERED,
        "action_status": FC.PASS_REFERENCE_ONLY,
        "fallback_applied": fallback_applied,
        "projected_score_null_reason": projected_score_null_reason,
    }
    if ats is not None:
        row["ats_selection"] = ats.get("selection")
        row["ats_cover_probability"] = ats.get("cover_probability")
    if uncertainty is not None:
        row["empirical_edge_sd_pp"] = uncertainty.get("empirical_edge_sd_pp")
        row["uncertainty_factors"] = uncertainty.get("factors_applied")
    return row


def assert_no_prices(rows):
    """(ok, failures). A forecast row carrying any price-shaped field is refused."""
    f = []
    for r in rows:
        for k in r:
            kl = str(k).lower()
            if kl in PRICE_FIELDS or any(kl.endswith("_" + p) or kl.startswith(p + "_")
                                         for p in ("ml", "odds", "price", "devig")):
                f.append(f"{r.get('game')}/{r.get('arm')}: forecast row carries price-shaped field "
                         f"{k!r} — prices never enter a winner probability")
    return (not f), f


def action_overlay(sealed_row, sealed_hash, prices, screen_fn=None):
    """(overlay, failures). Reads a SEALED forecast and prices; returns ONLY action fields.

    There is no parameter here through which a probability could be returned, and the seal is
    re-verified after the overlay is built."""
    f = []
    if FC.seal(sealed_row) != sealed_hash:
        f.append(f"{sealed_row.get('game')}: the row does not match its seal before the overlay ran")
    overlay = {}
    if not prices:
        overlay["action_status"] = FC.PASS_REFERENCE_ONLY
        overlay["action_reason"] = "no price captured for this game; nothing to screen"
        overlay["market_number"] = None
    else:
        overlay["market_number"] = prices.get("display")
        overlay["price_captured_utc"] = prices.get("captured_utc")
        overlay["price_source"] = prices.get("source")
        overlay["overround_pct"] = prices.get("overround_pct")
        overlay["devig_basis"] = prices.get("devig_basis")
        if screen_fn is not None:
            try:
                scr = screen_fn(sealed_row, prices) or {}
            except Exception as e:
                scr = {}
                f.append(f"{sealed_row.get('game')}: the action screen raised {type(e).__name__}: {e}")
            for k, v in scr.items():
                if k not in OVERLAY_FIELDS:
                    f.append(f"{sealed_row.get('game')}: the screen tried to write {k!r}, which is "
                             f"not an overlay field — the overlay may only set action fields")
                    continue
                overlay[k] = v
        overlay.setdefault("action_status", FC.PASS_REFERENCE_ONLY)
        overlay.setdefault("action_reason", "screened; no qualified action")
    # THE INVARIANT: applying the overlay must leave the sealed forecast byte-identical.
    merged = dict(sealed_row)
    merged.update(overlay)
    f.extend(FC.assert_only_action_changed(sealed_row, sealed_hash, merged))
    stray = [k for k in overlay if k not in OVERLAY_FIELDS]
    if stray:
        f.append(f"{sealed_row.get('game')}: overlay wrote non-action field(s) {stray}")
    return overlay, f


def build_card(slate, arm_specs, slate_date, information_cutoff_utc, evidence_sha256, sport):
    """(card, failures). ONE slate, ONE cutoff, ONE evidence hash, stamped onto all three arms.

    arm_specs: {arm: {"model_id":..., "simulation_version":..., "evaluation_arm_id":...,
                      "forecast": callable(game) -> (p_home, projections, extras)}}"""
    f = []
    missing = [a for a in ARMS if a not in arm_specs]
    if missing:
        return None, [f"a three-arm card needs every arm; missing {missing}"]
    rows, by_arm = [], {a: [] for a in ARMS}
    for game in slate:
        for arm in ARMS:
            spec = arm_specs[arm]
            try:
                p, proj, extra = spec["forecast"](game)
            except Exception as e:
                f.append(f"{game.get('game_id')}/{arm}: forecast raised {type(e).__name__}: {e} — "
                         f"every scheduled game must receive all three forecasts")
                continue
            row = build_row(
                game, arm, p, proj, slate_date, spec["model_id"], spec["simulation_version"],
                extra.get("information_class"), extra.get("information_fraction"),
                extra.get("named_cap_slots"), extra.get("verified_profile_slots"),
                spec.get("training_cutoff_utc", information_cutoff_utc), information_cutoff_utc,
                spec["evaluation_arm_id"], sport,
                ats=extra.get("ats"), fallback_applied=extra.get("fallback_applied"),
                uncertainty=extra.get("uncertainty"),
                projected_score_null_reason=extra.get("projected_score_null_reason"))
            row["evidence_sha256"] = evidence_sha256
            rows.append(row); by_arm[arm].append(row)
    # SAME SCHEDULE FOR EVERY ARM
    pops = {a: {r["game"] for r in by_arm[a]} for a in ARMS}
    ref = pops[BASELINE]
    for a in (CHAMPION, CHALLENGER):
        if pops[a] != ref:
            f.append(f"{a} covers a different game population than {BASELINE} "
                     f"({a}-only {sorted(pops[a] - ref)[:3]}, {BASELINE}-only {sorted(ref - pops[a])[:3]})")
    scheduled = {g["game_id"] for g in slate}
    if ref != scheduled:
        f.append(f"the card does not cover the scheduled slate; missing {sorted(scheduled - ref)[:4]}")
    # SAME CUTOFF AND EVIDENCE FOR EVERY ARM
    if len({r["feature_cutoff_utc"] for r in rows}) > 1:
        f.append("the arms used different information cutoffs")
    if len({r["evidence_sha256"] for r in rows}) > 1:
        f.append("the arms were built from different evidence")
    # NO PRICES ANYWHERE IN A FORECAST ROW
    ok_p, fp = assert_no_prices(rows)
    f.extend(fp)
    # KEYED SEEDS: distinct within an arm, and distinct ACROSS arms for the same game
    for a in ARMS:
        seeds = [r["simulation_seed"] for r in by_arm[a]]
        if len(set(seeds)) != len(seeds):
            f.append(f"{a}: two games share a simulation seed")
    for g in sorted(ref):
        per = {r["arm"]: r["simulation_seed"] for r in rows if r["game"] == g}
        if len(set(per.values())) != len(per):
            f.append(f"{g}: two arms share a simulation seed, so their draws are coupled")
    # THE CONTRACT
    for r in rows:
        ok_r, fr = FC.validate_row(r, sport)
        f.extend(fr)
    card = {
        "slate_date": slate_date, "sport": sport,
        "information_cutoff_utc": information_cutoff_utc,
        "evidence_sha256": evidence_sha256,
        "n_scheduled": len(slate), "n_rows": len(rows),
        "arms": {a: arm_specs[a]["evaluation_arm_id"] for a in ARMS},
        "rows": rows,
        "seals": {f'{r["game"]}|{r["arm"]}': FC.seal(r) for r in rows},
        "grading_keys": ["sport", "arm", "estimand", "information_class"],
        "grading_note": ("arms are graded separately by sport, estimand and information dose and "
                         "are never pooled"),
    }
    return card, f


def _mk_slate(n=3):
    return [{"game_id": f"A{i}@B{i}", "away": f"A{i}", "home": f"B{i}",
             "start_utc": f"2026-08-23T{17 + i:02d}:05:00Z"} for i in range(n)]


def _spec(arm, mid, aid, p=0.55):
    def fc(game, _p=p):
        return _p, {"away": 4.1, "home": 4.6, "total": 8.7, "total_side": "OVER",
                    "p_over": 0.6, "p_push": 0.0, "p_under": 0.4, "trials": 30000}, {
            "information_class": "PARTIAL_STARTER_INFORMATION", "information_fraction": 0.8,
            "named_cap_slots": 1, "verified_profile_slots": 24}
    return {"model_id": mid, "simulation_version": "v1", "evaluation_arm_id": aid, "forecast": fc}


def selftest():
    f = []
    SLATE, CUT, EV, D = _mk_slate(3), "2026-08-23T10:00:00Z", "e" * 64, "2026-08-23"
    specs = {BASELINE: _spec(BASELINE, "m.prior", "arm_b", 0.527),
             CHAMPION: _spec(CHAMPION, "m.v13", "arm_c", 0.55),
             CHALLENGER: _spec(CHALLENGER, "m.adaptive", "arm_x", 0.58)}
    card, ff = build_card(SLATE, specs, D, CUT, EV, "mlb")
    if ff:
        f.append(f"a valid three-arm card was rejected: {ff[:3]}")
    if card:
        if card["n_rows"] != 9:
            f.append(f"3 games x 3 arms should give 9 rows, got {card['n_rows']}")
        if card["grading_keys"] != ["sport", "arm", "estimand", "information_class"]:
            f.append("the card does not declare its non-pooled grading keys")

    # --- EVERY ARM IS REQUIRED --------------------------------------------------------------------
    for drop in ARMS:
        part = {k: v for k, v in specs.items() if k != drop}
        if build_card(SLATE, part, D, CUT, EV, "mlb")[0] is not None:
            f.append(f"a card missing the {drop} arm was built")

    # --- EVERY SCHEDULED GAME GETS ALL THREE ------------------------------------------------------
    def broken(game):
        if game["game_id"] == "A1@B1":
            raise RuntimeError("no starter")
        return 0.55, {"away": 4.0, "home": 4.5, "total": 8.5, "total_side": "OVER",
                      "p_over": 0.6, "p_push": 0.0, "p_under": 0.4, "trials": 100}, {
            "information_class": "PARTIAL_STARTER_INFORMATION", "information_fraction": 0.8,
            "named_cap_slots": 0, "verified_profile_slots": 6}
    bs = dict(specs); bs[CHALLENGER] = dict(specs[CHALLENGER], forecast=broken)
    c2, f2 = build_card(SLATE, bs, D, CUT, EV, "mlb")
    if not any("must receive all three forecasts" in x for x in f2):
        f.append("a game that failed to forecast on one arm was not reported")
    if not any("different game population" in x for x in f2):
        f.append("an arm covering fewer games than the baseline was not caught")

    # --- KEYED SEEDS ------------------------------------------------------------------------------
    if card:
        for g in {r["game"] for r in card["rows"]}:
            per = {r["arm"]: r["simulation_seed"] for r in card["rows"] if r["game"] == g}
            if len(set(per.values())) != 3:
                f.append(f"{g}: the three arms do not have three distinct seeds")
        # the SAME model on the SAME game must reproduce its seed
        s1 = KS.seed_for("m.v13", D, "A0@B0", "v1")
        row = next(r for r in card["rows"] if r["game"] == "A0@B0" and r["arm"] == CHAMPION)
        if row["simulation_seed"] != s1:
            f.append("the row seed is not the keyed seed")
    # two arms sharing a model_id would share seeds, and that must be caught
    same = dict(specs); same[CHALLENGER] = _spec(CHALLENGER, "m.v13", "arm_x", 0.58)
    if not any("share a simulation seed" in x for x in build_card(SLATE, same, D, CUT, EV, "mlb")[1]):
        f.append("two arms sharing a model_id produced identical seeds without being caught")

    # --- NO PRICES IN A FORECAST ROW ---------------------------------------------------------------
    for bad in ("ml_home", "close_ml_away", "market_p_home", "devig_basis", "book",
                "home_price", "odds_home"):
        ok_p, fp = assert_no_prices([{"game": "A@B", "arm": CHAMPION, bad: -110}])
        if ok_p:
            f.append(f"a forecast row carrying {bad!r} passed the price check")
    if not assert_no_prices([{"game": "A@B", "arm": CHAMPION, "p_home": 0.55,
                              "projected_total": 8.5}])[0]:
        f.append("a clean forecast row was flagged as carrying a price")

    # --- THE OVERLAY MAY ONLY WRITE ACTION FIELDS ---------------------------------------------------
    base = card["rows"][0]
    h = FC.seal(base)
    ov, fo = action_overlay(base, h, None)
    if fo:
        f.append(f"an unpriced overlay reported failures: {fo}")
    if ov.get("action_status") != FC.PASS_REFERENCE_ONLY or not ov.get("action_reason"):
        f.append("an unpriced game did not get a reasoned pass")
    PRICES = {"display": "B0 -140 / A0 +120", "captured_utc": "2026-08-23T12:00:00Z",
              "source": "book_x", "overround_pct": 4.6, "devig_basis": "same_book"}
    ov, fo = action_overlay(base, h, PRICES)
    if fo:
        f.append(f"a priced overlay reported failures: {fo}")
    if ov.get("market_number") != PRICES["display"]:
        f.append("the overlay did not carry the market number")
    # A SCREEN THAT TRIES TO WRITE A PROBABILITY IS REFUSED
    ov, fo = action_overlay(base, h, PRICES, screen_fn=lambda r, p: {"p_home": 0.99})
    if not any("not an overlay field" in x for x in fo):
        f.append("a screen that wrote p_home was not refused")
    if "p_home" in ov:
        f.append("a screen's probability write reached the overlay")
    ov, fo = action_overlay(base, h, PRICES,
                            screen_fn=lambda r, p: {"winner_probability": 0.99,
                                                    "projected_total": 99.0})
    if len([x for x in fo if "not an overlay field" in x]) < 2:
        f.append("a screen writing two forecast fields was only partly refused")
    # a legitimate screen result passes through
    ov, fo = action_overlay(base, h, PRICES,
                            screen_fn=lambda r, p: {"raw_edge_pp": 2.7, "sigma": 0.53,
                                                    "conservative_edge_pp": -5.8,
                                                    "passes_screen": False,
                                                    "action_status": "PASS_REFERENCE_ONLY"})
    if fo:
        f.append(f"a legitimate screen was refused: {fo}")
    if ov.get("conservative_edge_pp") != -5.8 or ov.get("passes_screen") is not False:
        f.append("a legitimate screen result did not reach the overlay")
    # a screen that RAISES is contained, not propagated
    ov, fo = action_overlay(base, h, PRICES, screen_fn=lambda r, p: 1 / 0)
    if not any("ZeroDivisionError" in x for x in fo):
        f.append("a screen that raised was not contained and reported")
    # applying a legitimate overlay must leave the seal intact
    merged = dict(base); merged.update(ov)
    if FC.assert_only_action_changed(base, h, merged):
        f.append("applying the overlay changed sealed forecast content")

    # --- A GAME MISSING FROM EVERY ARM ------------------------------------------------------------
    def skip_one(game):
        if game["game_id"] == "A2@B2":
            raise RuntimeError("no data for this game on any arm")
        return 0.55, {"away": 4.0, "home": 4.5, "total": 8.5, "total_side": "OVER",
                      "p_over": 0.6, "p_push": 0.0, "p_under": 0.4, "trials": 100}, {
            "information_class": "PARTIAL_STARTER_INFORMATION", "information_fraction": 0.8,
            "named_cap_slots": 0, "verified_profile_slots": 6}
    allskip = {a: dict(specs[a], forecast=skip_one) for a in ARMS}
    _, fsk = build_card(SLATE, allskip, D, CUT, EV, "mlb")
    if not any("does not cover the scheduled slate" in x for x in fsk):
        f.append("a game absent from EVERY arm did not trip the scheduled-slate check")

    # --- DUPLICATE GAME IDS COLLIDE SEEDS WITHIN AN ARM ---------------------------------------------
    dup = SLATE + [dict(SLATE[0])]
    _, fdup = build_card(dup, specs, D, CUT, EV, "mlb")
    if not any("share a simulation seed" in x for x in fdup):
        f.append("a duplicated game id produced two identical seeds within an arm without being "
                 "caught")

    # --- THE CONTRACT RUNS ON EVERY ROW --------------------------------------------------------------
    def badprobs(game):
        return 0.55, {"away": 4.0, "home": 4.5, "total": 8.5, "total_side": "OVER",
                      "p_over": 0.6, "p_push": 0.3, "p_under": 0.4, "trials": 100}, {
            "information_class": "PARTIAL_STARTER_INFORMATION", "information_fraction": 0.8,
            "named_cap_slots": 0, "verified_profile_slots": 6}
    bp = dict(specs); bp[CHAMPION] = dict(specs[CHAMPION], forecast=badprobs)
    _, fbp = build_card(SLATE, bp, D, CUT, EV, "mlb")
    if not any("over+push+under" in x for x in fbp):
        f.append("a row whose over/push/under do not sum to 1 reached the card unchecked — the "
                 "forecast contract is not being applied per row")

    # --- THE PRE-OVERLAY SEAL CHECK ------------------------------------------------------------------
    _, fseal = action_overlay(base, "0" * 64, PRICES)
    if not any("does not match its seal before the overlay ran" in x for x in fseal):
        f.append("an overlay ran against a row that does not match its seal")

    # --- A SCREEN RAISING ANY EXCEPTION IS CONTAINED --------------------------------------------------
    def boom(r, pr):
        raise KeyError("missing price field")
    ov_b, fb = action_overlay(base, h, PRICES, screen_fn=boom)
    if not any("KeyError" in x for x in fb):
        f.append("a screen raising a non-arithmetic exception was not contained and reported")
    if ov_b.get("market_number") != PRICES["display"]:
        f.append("a raising screen took the whole overlay down instead of being contained")

    print("three_arm_card selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("a card may be built with an arm missing",
     "    missing = [a for a in ARMS if a not in arm_specs]", "    missing = []"),
    ("a game that fails to forecast on one arm is silently dropped",
     '                f.append(f"{game.get(\'game_id\')}/{arm}: forecast raised {type(e).__name__}: {e} — "', "                pass  # ("),
    ("the arms may cover different game populations",
     "        if pops[a] != ref:", "        if False:"),
    ("the card need not cover the scheduled slate",
     "    if ref != scheduled:", "    if False:"),
    # NOT MUTANTS, deliberately. build_card takes ONE information_cutoff_utc and ONE
    # evidence_sha256 and stamps both onto every row, so no caller can give two arms different
    # inputs and no fixture can make these checks fire. They are defence in depth against a future
    # edit that threads per-arm cutoffs, and are recorded here rather than dressed up with mutants
    # that appear to kill (lesson 23 corollary).
    ("two arms sharing a seed on one game is not caught",
     "        if len(set(per.values())) != len(per):", "        if False:"),
    ("two games sharing a seed within an arm is not caught",
     "        if len(set(seeds)) != len(seeds):", "        if False:"),
    ("price-shaped fields are allowed into a forecast row",
     "            if kl in PRICE_FIELDS or any(kl.endswith(\"_\" + p) or kl.startswith(p + \"_\")",
     "            if False and (kl in PRICE_FIELDS or any(kl.endswith(\"_\" + p) or kl.startswith(p + \"_\")"),
    # NOT A MUTANT: build_row constructs rows from a fixed key list and has no path that emits a
    # price-shaped field, so the card-level sweep cannot be made to fire from the public API.
    # assert_no_prices itself is fully exercised above against seven price-shaped names; the
    # card-level call is defence in depth for future edits to build_row.
    ("the overlay may write any field it likes",
     "                if k not in OVERLAY_FIELDS:", "                if False:"),
    # NOT A MUTANT: the OVERLAY_FIELDS guard above rejects any non-action key before it reaches
    # `overlay`, so by the time the merged row is sealed nothing outside action fields can have
    # changed. The post-write seal check and the stray sweep are both unreachable from the public
    # API and are kept as redundant defence; forecast_contract.assert_only_action_changed is
    # independently mutation-tested there.
    ("the pre-overlay seal check is dropped",
     "    if FC.seal(sealed_row) != sealed_hash:", "    if False:"),
    ("a screen that raises takes the whole card down instead of being contained",
     "            except Exception as e:", "            except ZeroDivisionError as e:"),
    ("the contract is no longer applied to every row",
     "        ok_r, fr = FC.validate_row(r, sport)\n        f.extend(fr)", "        pass"),
    ("the card stops declaring that arms are never pooled",
     '        "grading_keys": ["sport", "arm", "estimand", "information_class"],',
     '        "grading_keys": [],'),
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
