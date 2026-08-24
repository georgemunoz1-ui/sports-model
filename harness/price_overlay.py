#!/usr/bin/env python3
"""PRICE OVERLAY — what a price may do to a frozen board, and the five things a selection needs.

OWNER CORRECTIONS 1, 2 AND 5 (2026-08-24).

1. SAY WHAT IS TRUE. I wrote "no prices exist for this slate." That is almost certainly false —
   sportsbooks priced these games. What is true is that no price entered the admissible evidence
   package. The difference matters: "no prices exist" is a claim about the world that I cannot
   support and that happens to flatter the gap; NO_ELIGIBLE_CAPTURED_PRICE_BOARD is a claim about
   MY evidence, which is the only thing I can actually check.

2. THE BOARD NEVER BECOMES A BETTING CARD. A later capture produces a SEPARATE overlay artifact with
   its own capture instant and its own hash, referencing the frozen board hash. It may not mutate a
   single probability, arm, dose or seal on the board it points at. A board that could turn into a
   card under a later capture is a board whose probabilities were never really frozen.

   And a price enables EVALUATION, not EXECUTION. Real-money authorization is a separate gate with a
   separate owner and it stays BLOCKED regardless of what any overlay computes. There is no path in
   this module that grants execution and there is no argument that produces one.

3. A PRICE ALONE IS NOT A SELECTION. Five things are required: model probability, price, EV,
   PER-GAME model uncertainty, and stated risk. The board carries cross-game dispersion, which is a
   property of the slate and explicitly NOT an uncertainty — so on today's board the fourth
   requirement is simply absent, and no overlay could issue a selection even with a full price sheet.
   Monte Carlo error is not model uncertainty either: it measures how well the simulation converged,
   not how wrong the model may be, and conflating them would let more draws masquerade as more
   knowledge. They are separate fields and this module refuses a selection that supplies one for the
   other.

API
  price_eligibility(boards)             -> which captured boards may inform market probability
  overlay_contract(overlay, board_hash) -> may this overlay attach to that frozen board?
  selection_ready(row)                  -> (bool, missing) against the five requirements
"""
from __future__ import annotations

import json
import os
import sys

# --- status vocabulary, exactly as the owner specified ---------------------------------------------
NO_ELIGIBLE_BOARD = "NO_ELIGIBLE_CAPTURED_PRICE_BOARD"
EV_NOT_COMPUTABLE = "EV_NOT_COMPUTABLE"
ACTION_AUTHORITY_NONE = "ACTION_AUTHORITY_NONE"
ELIGIBLE = "ELIGIBLE_CAPTURED_PRICE_BOARD"

# --- overlay contract ------------------------------------------------------------------------------
OVERLAY_OK = "OVERLAY_MAY_ATTACH"
OVERLAY_NO_BOARD_REF = "OVERLAY_DOES_NOT_REFERENCE_A_FROZEN_BOARD"
OVERLAY_BOARD_MISMATCH = "OVERLAY_REFERENCES_A_DIFFERENT_BOARD"
OVERLAY_NO_CAPTURE_INSTANT = "OVERLAY_HAS_NO_CAPTURE_INSTANT"
OVERLAY_NO_HASH = "OVERLAY_HAS_NO_HASH"
OVERLAY_WOULD_MUTATE = "OVERLAY_WOULD_MUTATE_THE_FROZEN_BOARD"
OVERLAY_CLAIMS_EXECUTION = "OVERLAY_CLAIMS_EXECUTION_AUTHORITY"

#: Fields that belong to the frozen board. An overlay carrying any of them is trying to rewrite it.
FROZEN_BOARD_FIELDS = ("p_home", "winner_probability", "projected_total", "projected_home_margin",
                       "arm", "resolved_information_dose", "information_class", "simulation_seed",
                       "simulation_trials", "evidence_sha256", "total_distribution")

#: SAME-BOOK ELIGIBILITY, corrected 2026-08-24. I previously used an ABSOLUTE band of 3.5%-7.5%,
#: generalised from one observation of one market type. It is wrong, and it would have rejected a
#: genuine single-book DraftKings board: that board's ten MLB moneylines hold 1.637%-1.869%, because
#: a modern two-way MLB moneyline at a sharp book is far tighter than the 4-6% seen elsewhere.
#:
#: The test that actually discriminates one book from many is HOMOGENEITY WITHIN A MARKET TYPE, which
#: is the test that caught the 2026-08-23 board — that one was BIMODAL, eight rows at 4.5-4.8% and
#: seven at 1.6-2.0%, a 3.11pp spread that no single book produces. A real book's overround varies
#: only by the granularity of its price grid, which is a few tenths of a point.
#:
#: Two conditions, both absolute and neither fitted to a board:
#:   the spread within a market type stays under one percentage point of overround; and
#:   the level sits above the best-odds regime, which the 2026-08-03 ruling put at 0.4%-0.6%.
SAME_BOOK_MAX_OVERROUND_SPREAD_PP = 0.010
BEST_ODDS_CEILING = 0.010

# --- selection requirements ------------------------------------------------------------------------
SELECTION_REQUIREMENTS = ("model_probability", "price", "expected_value",
                          "model_uncertainty", "stated_risk")
MC_IS_NOT_UNCERTAINTY = "MONTE_CARLO_ERROR_SUPPLIED_AS_MODEL_UNCERTAINTY"

EXECUTION_BLOCKED = "EXECUTION_BLOCKED_REAL_MONEY_AUTHORIZATION_IS_A_SEPARATE_GATE"


def _num(x):
    if x is None or isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def market_homogeneity(overrounds):
    """(ok, detail) for one market type. A single book is homogeneous; a mixed board is not."""
    vals = [v for v in (_num(x) for x in (overrounds or [])) if v is not None]
    if len(vals) < 2:
        return None, {"n": len(vals), "reason": "fewer than two priced markets; homogeneity is "
                                                "undefined and is not assumed"}
    lo, hi = min(vals), max(vals)
    mean = sum(vals) / len(vals)
    spread = hi - lo
    detail = {"n": len(vals), "mean_overround": mean, "min": lo, "max": hi, "spread_pp": spread}
    if mean < BEST_ODDS_CEILING:
        detail["reason"] = (f"mean overround {mean:.4f} is at or below the best-odds regime "
                            f"({BEST_ODDS_CEILING}); a cross-book best-of board cannot support a "
                            f"de-vigged market probability")
        return False, detail
    if spread > SAME_BOOK_MAX_OVERROUND_SPREAD_PP:
        detail["reason"] = (f"overround spread {spread:.4f} exceeds "
                            f"{SAME_BOOK_MAX_OVERROUND_SPREAD_PP}; a single book varies only by its "
                            f"price grid, so this board holds more than one population")
        return False, detail
    return True, detail


def price_eligibility(boards):
    """Which captured boards may inform a market probability, and the honest status when none can."""
    graded = []
    for b in (boards or []):
        cap = b.get("captured_at_utc")
        start = b.get("first_start_utc")
        why = None
        ovs = b.get("overrounds")
        if ovs is None and _num(b.get("overround")) is not None:
            ovs = [b["overround"]]
        hom, detail = market_homogeneity(ovs)
        if hom is None:
            why = f"homogeneity undefined: {detail.get('reason')}"
        elif hom is False:
            why = detail.get("reason")
        elif not cap or not start or str(cap) >= str(start):
            why = "not captured before the first start"
        graded.append(dict(b, eligible=why is None, reason=why, homogeneity=detail))
    ok = [g for g in graded if g["eligible"]]
    return {
        "n_boards": len(graded),
        "n_eligible": len(ok),
        "graded": graded,
        "status": ELIGIBLE if ok else NO_ELIGIBLE_BOARD,
        "ev_status": "EV_COMPUTABLE" if ok else EV_NOT_COMPUTABLE,
        "action_authority": ACTION_AUTHORITY_NONE,
        "note": "a captured board that fails the band is not absent — it is present and inadmissible, "
                "and saying 'no prices exist' would be a claim about the world rather than about the "
                "evidence package",
    }


def overlay_contract(overlay, frozen_board_hash):
    """(ok, status, problems). May this overlay attach to that frozen board without changing it?"""
    p = []
    o = overlay or {}
    if not o.get("board_sha256"):
        p.append(OVERLAY_NO_BOARD_REF)
    elif o["board_sha256"] != frozen_board_hash:
        p.append(f"{OVERLAY_BOARD_MISMATCH}: references {o['board_sha256'][:16]} but the frozen "
                 f"board hashes to {str(frozen_board_hash)[:16]}")
    if not o.get("captured_at_utc"):
        p.append(OVERLAY_NO_CAPTURE_INSTANT)
    if not o.get("overlay_sha256"):
        p.append(OVERLAY_NO_HASH)
    for row in (o.get("rows") or []):
        for k in FROZEN_BOARD_FIELDS:
            if k in row:
                p.append(f"{OVERLAY_WOULD_MUTATE}: row carries {k}, which belongs to the board")
                break
    if o.get("execution_authority") not in (None, "NONE", False):
        p.append(f"{OVERLAY_CLAIMS_EXECUTION}: {o.get('execution_authority')!r}")
    return (not p), (OVERLAY_OK if not p else "OVERLAY_REFUSED"), p


def selection_ready(row):
    """(bool, missing). The five requirements, with Monte Carlo error refused as a stand-in."""
    r = row or {}
    missing = [k for k in SELECTION_REQUIREMENTS
               if r.get(k) is None or (isinstance(r.get(k), str) and not r[k].strip())]
    if r.get("model_uncertainty") is None and r.get("monte_carlo_sd_pp") is not None:
        missing.append(MC_IS_NOT_UNCERTAINTY)
    if (r.get("model_uncertainty") is not None
            and r.get("model_uncertainty") == r.get("monte_carlo_sd_pp")):
        missing.append(MC_IS_NOT_UNCERTAINTY)
    return (not missing), sorted(set(missing))


def evaluation_not_execution():
    return {"a_price_board_enables": "EVALUATION — EV, calibration against a market, and grading",
            "a_price_board_never_enables": "EXECUTION",
            "real_money_authorization": EXECUTION_BLOCKED,
            "why": "the two gates have different owners. No computation on this side can satisfy the "
                   "other, and there is no code path here that tries."}


# =================================================================================================
def selftest():
    f = []
    B = "a" * 64

    # --- 1: absent is not the same as inadmissible ------------------------------------------------
    DK_MLB = [0.018688, 0.018688, 0.017143, 0.017857, 0.017262,
              0.016372, 0.017966, 0.016744, 0.016744, 0.017821]   # the real 2026-08-24 board
    BIMODAL_0823 = [0.0456, 0.0462, 0.0460, 0.0453, 0.0451, 0.0462, 0.0468, 0.0475,
                    0.0164, 0.0174, 0.0167, 0.0171, 0.0195, 0.0179, 0.0192]
    BEST_ODDS = [0.0045, 0.0052, 0.0048, 0.0050]

    none_captured = price_eligibility([])
    if none_captured["status"] != NO_ELIGIBLE_BOARD or none_captured["ev_status"] != EV_NOT_COMPUTABLE:
        f.append("no captured board must report NO_ELIGIBLE_CAPTURED_PRICE_BOARD and EV_NOT_COMPUTABLE")
    if none_captured["action_authority"] != ACTION_AUTHORITY_NONE:
        f.append("action authority must be NONE with no eligible board")

    # THE CORRECTION: a genuine single-book MLB board holds under 2% and MUST be eligible. An
    # absolute 3.5% floor would have rejected the owner's real DraftKings board.
    real = price_eligibility([{"overrounds": DK_MLB, "captured_at_utc": "2026-08-24T16:41:27Z",
                               "first_start_utc": "2026-08-24T22:40:00Z"}])
    if real["status"] != ELIGIBLE:
        f.append(f"the real single-book MLB board must be eligible, got {real['graded'][0]['reason']}")
    if real["ev_status"] != "EV_COMPUTABLE":
        f.append("an eligible board makes EV computable")
    if real["action_authority"] != ACTION_AUTHORITY_NONE:
        f.append("even an ELIGIBLE board confers no action authority by itself")

    # the 8/23 bimodal board must still fail — that is the case the homogeneity test exists for
    bim = price_eligibility([{"overrounds": BIMODAL_0823, "captured_at_utc": "2026-08-23T15:00:00Z",
                              "first_start_utc": "2026-08-23T17:35:00Z"}])
    if bim["status"] != NO_ELIGIBLE_BOARD:
        f.append("the bimodal 8/23 board must remain ineligible")
    if "more than one population" not in (bim["graded"][0]["reason"] or ""):
        f.append("the bimodal refusal must say the board holds more than one population")
    if bim["n_boards"] != 1:
        f.append("an inadmissible board must still be COUNTED as captured, not reported as absent")

    # a cross-book best-of board is tight AND homogeneous, so only the LEVEL test catches it
    bo = price_eligibility([{"overrounds": BEST_ODDS, "captured_at_utc": "2026-08-24T16:00:00Z",
                             "first_start_utc": "2026-08-24T22:40:00Z"}])
    if bo["status"] != NO_ELIGIBLE_BOARD:
        f.append("a best-odds board must be ineligible")
    if "best-odds regime" not in (bo["graded"][0]["reason"] or ""):
        f.append("the best-odds refusal must name the regime, not the spread")

    # a single market cannot be tested for homogeneity, and that is reported rather than assumed
    one = price_eligibility([{"overrounds": [0.0177], "captured_at_utc": "2026-08-24T16:00:00Z",
                              "first_start_utc": "2026-08-24T22:40:00Z"}])
    if one["status"] != NO_ELIGIBLE_BOARD or "undefined" not in (one["graded"][0]["reason"] or ""):
        f.append("one priced market cannot establish homogeneity and must not be assumed eligible")

    late = price_eligibility([{"overrounds": DK_MLB, "captured_at_utc": "2026-08-24T23:00:00Z",
                               "first_start_utc": "2026-08-24T22:40:00Z"}])
    if late["status"] != NO_ELIGIBLE_BOARD:
        f.append("a board captured after the first start is not eligible")

    # and the WNBA half of the same capture is a DIFFERENT market type with a legitimately wider
    # hold; grouping them together would manufacture a bimodal board out of two honest ones
    wn = price_eligibility([{"overrounds": [0.04268, 0.04762], "captured_at_utc": "2026-08-24T16:41:27Z",
                             "first_start_utc": "2026-08-25T00:00:00Z"}])
    if wn["status"] != ELIGIBLE:
        f.append(f"the WNBA board must be eligible in its own market type, got {wn['graded'][0]['reason']}")
    pooled = price_eligibility([{"overrounds": DK_MLB + [0.04268, 0.04762],
                                 "captured_at_utc": "2026-08-24T16:41:27Z",
                                 "first_start_utc": "2026-08-24T22:40:00Z"}])
    if pooled["status"] != NO_ELIGIBLE_BOARD:
        f.append("pooling two market types must fail homogeneity — they must be graded separately")

    # --- 2: the overlay may not rewrite the board -------------------------------------------------
    ok_overlay = {"board_sha256": B, "captured_at_utc": "2026-08-24T20:00:00Z",
                  "overlay_sha256": "b" * 64,
                  "rows": [{"game": "mlb:BOS@MIA", "price_home": -120, "ev": 0.012}]}
    ok, st, pr = overlay_contract(ok_overlay, B)
    if not ok or st != OVERLAY_OK:
        f.append(f"a well-formed overlay must attach, got {st} {pr}")
    for k in ("p_home", "arm", "resolved_information_dose", "simulation_seed", "total_distribution"):
        bad = {**ok_overlay, "rows": [{"game": "x", k: 1}]}
        ok2, _, pr2 = overlay_contract(bad, B)
        if ok2 or not any(OVERLAY_WOULD_MUTATE in x for x in pr2):
            f.append(f"an overlay carrying {k} must be refused as a mutation")
    ok3, _, pr3 = overlay_contract({**ok_overlay, "board_sha256": "c" * 64}, B)
    if ok3 or not any(OVERLAY_BOARD_MISMATCH in x for x in pr3):
        f.append("an overlay pointing at a different board must be refused")
    for drop, code in (("board_sha256", OVERLAY_NO_BOARD_REF),
                       ("captured_at_utc", OVERLAY_NO_CAPTURE_INSTANT),
                       ("overlay_sha256", OVERLAY_NO_HASH)):
        d = {k: v for k, v in ok_overlay.items() if k != drop}
        ok4, _, pr4 = overlay_contract(d, B)
        if ok4 or code not in pr4:
            f.append(f"an overlay missing {drop} must be refused with {code}")
    ok5, _, pr5 = overlay_contract({**ok_overlay, "execution_authority": "GRANTED"}, B)
    if ok5 or not any(OVERLAY_CLAIMS_EXECUTION in x for x in pr5):
        f.append("an overlay claiming execution authority must be refused")
    if "BLOCKED" not in evaluation_not_execution()["real_money_authorization"]:
        f.append("a price board must never be described as enabling execution")

    # --- 5: five requirements, and Monte Carlo error is not one of them ---------------------------
    full = {"model_probability": 0.52, "price": -120, "expected_value": 0.011,
            "model_uncertainty": 0.031, "stated_risk": "0.5u paper"}
    ok6, miss = selection_ready(full)
    if not ok6 or miss:
        f.append(f"a complete row must be selection-ready, got {miss}")
    # NAMED explicitly, not iterated over SELECTION_REQUIREMENTS: a loop over the list under test
    # cannot fail when the list is shortened, which guards nothing (lesson 24).
    for k in ("model_probability", "price", "expected_value", "model_uncertainty", "stated_risk"):
        if k not in SELECTION_REQUIREMENTS:
            f.append(f"{k} must be a stated selection requirement")
        part = {kk: vv for kk, vv in full.items() if kk != k}
        ok7, miss7 = selection_ready(part)
        if ok7 or k not in miss7:
            f.append(f"a row missing {k} must not be selection-ready")
    # today's board shape: uncertainty absent, Monte Carlo error present
    mc_only = {"model_probability": 0.52, "price": -120, "expected_value": 0.011,
               "stated_risk": "0.5u paper", "monte_carlo_sd_pp": 0.158}
    ok8, miss8 = selection_ready(mc_only)
    if ok8 or MC_IS_NOT_UNCERTAINTY not in miss8:
        f.append("Monte Carlo error must not substitute for model uncertainty")
    # nor may they be set to the same number and called two fields
    same = dict(full, model_uncertainty=0.158, monte_carlo_sd_pp=0.158)
    ok9, miss9 = selection_ready(same)
    if ok9 or MC_IS_NOT_UNCERTAINTY not in miss9:
        f.append("identical values in both fields is the same conflation wearing two names")
    # an empty string is not a stated risk
    if selection_ready(dict(full, stated_risk="  "))[0]:
        f.append("a blank stated risk is not a stated risk")

    for x in f:
        print("FAIL:", x)
    if not f:
        print("price_overlay selftest: OK")
    return f


MUTANTS = [
    ("an inadmissible board is reported as no board at all",
     "        graded.append(dict(b, eligible=why is None, reason=why, homogeneity=detail))",
     "        pass"),
    ("the homogeneity test stops running",
     "    if spread > SAME_BOOK_MAX_OVERROUND_SPREAD_PP:", "    if False:"),
    ("the spread ceiling is widened until the bimodal board passes",
     "SAME_BOOK_MAX_OVERROUND_SPREAD_PP = 0.010", "SAME_BOOK_MAX_OVERROUND_SPREAD_PP = 0.100"),
    ("the best-odds level test stops running",
     "    if mean < BEST_ODDS_CEILING:", "    if False:"),
    ("a single market is assumed homogeneous",
     '        return None, {"n": len(vals), "reason": "fewer than two priced markets; homogeneity is "\n                                                "undefined and is not assumed"}',
     '        return True, {"n": len(vals), "reason": "assumed"}'),
    ("the bimodal refusal stops naming the population problem",
     '                            f"price grid, so this board holds more than one population")',
     '                            f"price grid.")'),
    ("a board captured after the start is eligible",
     '        elif not cap or not start or str(cap) >= str(start):', "        elif False:"),
    ("an eligible board is reported as conferring action authority",
     '        "action_authority": ACTION_AUTHORITY_NONE,', '        "action_authority": "GATE_GOVERNED" if ok else ACTION_AUTHORITY_NONE,'),
    ("EV is called computable with no eligible board",
     '        "ev_status": "EV_COMPUTABLE" if ok else EV_NOT_COMPUTABLE,', '        "ev_status": "EV_COMPUTABLE",'),
    ("an overlay may carry board fields",
     "            if k in row:", "            if False:"),
    ("the mutation list is emptied",
     'FROZEN_BOARD_FIELDS = ("p_home", "winner_probability", "projected_total", "projected_home_margin",\n                       "arm", "resolved_information_dose", "information_class", "simulation_seed",\n                       "simulation_trials", "evidence_sha256", "total_distribution")',
     "FROZEN_BOARD_FIELDS = ()"),
    ("an overlay may point at a different board",
     '    elif o["board_sha256"] != frozen_board_hash:', "    elif False:"),
    ("an overlay needs no capture instant",
     '    if not o.get("captured_at_utc"):', "    if False:"),
    ("an overlay needs no hash of its own",
     '    if not o.get("overlay_sha256"):', "    if False:"),
    ("an overlay may claim execution authority",
     '    if o.get("execution_authority") not in (None, "NONE", False):', "    if False:"),
    ("Monte Carlo error substitutes for model uncertainty",
     '    if r.get("model_uncertainty") is None and r.get("monte_carlo_sd_pp") is not None:\n        missing.append(MC_IS_NOT_UNCERTAINTY)',
     "    if False:\n        missing.append(MC_IS_NOT_UNCERTAINTY)"),
    ("the two fields may hold the same number",
     '    if (r.get("model_uncertainty") is not None\n            and r.get("model_uncertainty") == r.get("monte_carlo_sd_pp")):\n        missing.append(MC_IS_NOT_UNCERTAINTY)',
     "    if False:\n        missing.append(MC_IS_NOT_UNCERTAINTY)"),
    ("the five requirements shrink to four",
     'SELECTION_REQUIREMENTS = ("model_probability", "price", "expected_value",\n                          "model_uncertainty", "stated_risk")',
     'SELECTION_REQUIREMENTS = ("model_probability", "price", "expected_value", "stated_risk")'),
    ("a blank string satisfies a requirement",
     '    missing = [k for k in SELECTION_REQUIREMENTS\n               if r.get(k) is None or (isinstance(r.get(k), str) and not r[k].strip())]',
     "    missing = [k for k in SELECTION_REQUIREMENTS if r.get(k) is None]"),
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
