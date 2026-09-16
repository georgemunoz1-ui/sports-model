#!/usr/bin/env python3
"""EVALUATION ARM IDENTITY — one model_id can carry several arms, and each needs its own identity.

OWNER RULING 2026-08-23:
    "The same model parameters can retain one model_id, but V13_ALL_CAP_INPUTS and the
     starter-informed configuration need distinct immutable evaluation_arm_id values binding
     model_id, input_policy_id, feature-manifest hash, CAP/substitution policy, simulation
     configuration and training-cutoff policy.

     If those policies were not frozen before the first game, the 30-game comparison is a
     RETROSPECTIVE INPUT-POLICY ABLATION, not prospective challenger evidence."

WHY model_id IS NOT ENOUGH. Every forecast in the 2026-08-19 and 2026-08-21 cohort carries
model_id ml.v13_1.hfa1005.card.s722n30000 — the same frozen parameters. What differs between the
arms is which INPUTS were allowed in, and that difference is the entire experiment. An identity that
cannot distinguish the two arms cannot bind either of them, and a comparison between two things that
share an identity is not a comparison between two registered arms.

THE FREEZE TEST IS THE POINT. An arm identity created after the games were played describes a choice
made with the results visible, whatever it says about itself. So the identity carries its own
registration instant and the cohort carries its first game, and prospectivity is DERIVED from the
two rather than claimed. There is no field an author can set to assert it.
"""
from __future__ import annotations

MODULE_ID = "evaluation_arm"

import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BOUND_POLICIES = ("model_id", "input_policy_id", "feature_manifest_sha256",
                  "cap_substitution_policy_id", "simulation_config_id",
                  "training_cutoff_policy_id")

PROSPECTIVE = "PROSPECTIVE_CHALLENGER_EVIDENCE"
RETROSPECTIVE = "RETROSPECTIVE_INPUT_POLICY_ABLATION"
UNDETERMINED = "PROSPECTIVITY_UNDETERMINED"


def arm_id(policies, registered_utc):
    """A deterministic immutable identity over the SIX bound policies plus its registration instant.

    The registration instant is inside the hash on purpose: an arm re-registered later is a
    different arm, and must not be able to inherit an earlier arm's prospectivity."""
    missing = [k for k in BOUND_POLICIES if not policies.get(k)]
    if missing:
        raise ValueError(f"an evaluation arm must bind every policy; missing {missing}")
    if not registered_utc:
        raise ValueError("an evaluation arm must carry its registration instant")
    payload = {k: policies[k] for k in BOUND_POLICIES}
    payload["registered_utc"] = registered_utc
    return "arm_" + hashlib.sha256(json.dumps(payload, sort_keys=True,
                                              separators=(",", ":")).encode()).hexdigest()[:24]


def register_arm(name, policies, registered_utc):
    """(record, failures). Refuses an incomplete binding rather than registering a partial arm."""
    try:
        aid = arm_id(policies, registered_utc)
    except ValueError as e:
        return None, [str(e)]
    return {"evaluation_arm_id": aid, "arm_name": name, "registered_utc": registered_utc,
            **{k: policies[k] for k in BOUND_POLICIES}}, []


def prospectivity(arm_record, cohort_first_game_start_utc):
    """(status, reason). DERIVED from the two instants. Nothing an author writes can assert it."""
    if arm_record is None or not arm_record.get("registered_utc"):
        return UNDETERMINED, "the arm carries no registration instant"
    if not cohort_first_game_start_utc:
        return UNDETERMINED, "the cohort's first game start is unknown"
    reg = arm_record["registered_utc"]
    if reg < cohort_first_game_start_utc:
        return PROSPECTIVE, (f"arm registered {reg}, before the cohort's first game started "
                             f"{cohort_first_game_start_utc}")
    return RETROSPECTIVE, (f"arm registered {reg}, at or after the cohort's first game started "
                           f"{cohort_first_game_start_utc}: the policy was fixed with results "
                           f"visible, so this is an input-policy ablation and not prospective "
                           f"challenger evidence")


def distinct(arms):
    """(ok, failures). Every arm in a comparison must carry a DIFFERENT identity."""
    f = []
    seen = {}
    for a in arms:
        aid = (a or {}).get("evaluation_arm_id")
        if not aid:
            f.append(f"{(a or {}).get('arm_name')}: no evaluation_arm_id")
            continue
        if aid in seen:
            f.append(f"{a.get('arm_name')} and {seen[aid]} share evaluation_arm_id {aid} — two arms "
                     f"that share an identity are not two arms")
        seen[aid] = a.get("arm_name")
    # a shared model_id is FINE; a shared full policy binding is not
    return (not f), f


def label_comparison(arm_records, cohort_first_game_start_utc):
    """The label a comparison must carry. RETROSPECTIVE if ANY arm was registered late."""
    ok, f = distinct(arm_records)
    stats = {}
    worst = PROSPECTIVE
    for a in arm_records:
        st, why = prospectivity(a, cohort_first_game_start_utc)
        stats[(a or {}).get("arm_name")] = {"status": st, "reason": why}
        if st == UNDETERMINED:
            worst = UNDETERMINED
        elif st == RETROSPECTIVE and worst != UNDETERMINED:
            worst = RETROSPECTIVE
    return {"comparison_label": worst, "identities_distinct": ok, "identity_failures": f,
            "per_arm": stats,
            "note": ("A comparison is only prospective challenger evidence when EVERY arm was "
                     "registered before the cohort's first game. One late arm makes the whole "
                     "comparison an ablation.")}


def selftest():
    f = []
    POL = {"model_id": "ml.v13_1.hfa1005.card.s722n30000", "input_policy_id": "ALL_CAP_INPUTS",
           "feature_manifest_sha256": "a" * 64, "cap_substitution_policy_id": "CAP_LEAGUE_AVG_V1",
           "simulation_config_id": "s722n30000", "training_cutoff_policy_id": "ASOF_PREV_DAY_V1"}
    cap, ff = register_arm("V13_ALL_CAP_INPUTS", POL, "2026-08-10T00:00:00Z")
    if ff:
        f.append(f"a complete arm was refused: {ff}")
    sp, _ = register_arm("V13_STARTER_INFORMED",
                         dict(POL, input_policy_id="STARTER_INFORMED"), "2026-08-10T00:00:00Z")

    # --- EVERY POLICY MUST BE BOUND ------------------------------------------------------------
    for k in BOUND_POLICIES:
        r, ff2 = register_arm("x", {kk: v for kk, v in POL.items() if kk != k},
                              "2026-08-10T00:00:00Z")
        if r is not None or not any(k in x for x in ff2):
            f.append(f"an arm missing {k} was registered")
    if register_arm("x", POL, None)[0] is not None:
        f.append("an arm with no registration instant was registered")
    if len(BOUND_POLICIES) != 6:
        f.append(f"{len(BOUND_POLICIES)} policies are bound, the ruling names six")

    # --- A SHARED model_id IS FINE; A SHARED IDENTITY IS NOT ------------------------------------
    if cap["model_id"] != sp["model_id"]:
        f.append("the fixture does not exercise a shared model_id")
    if cap["evaluation_arm_id"] == sp["evaluation_arm_id"]:
        f.append("two arms differing only in input policy received the SAME identity — that is the "
                 "whole defect this module exists for")
    ok, ff3 = distinct([cap, sp])
    if not ok:
        f.append(f"two genuinely distinct arms were rejected: {ff3}")
    same, _ = register_arm("DUPLICATE", POL, "2026-08-10T00:00:00Z")
    ok, ff3 = distinct([cap, same])
    if ok or not any("not two arms" in x for x in ff3):
        f.append("two arms with identical policy bindings were accepted as distinct")
    if distinct([cap, {"arm_name": "no_id"}])[0]:
        f.append("an arm with no identity was accepted")
    # every bound policy must move the identity
    for k in BOUND_POLICIES:
        alt, _ = register_arm("alt", dict(POL, **{k: "DIFFERENT"}), "2026-08-10T00:00:00Z")
        if alt["evaluation_arm_id"] == cap["evaluation_arm_id"]:
            f.append(f"changing {k} did not change the arm identity")
    # re-registering LATER is a different arm and cannot inherit prospectivity
    later, _ = register_arm("V13_ALL_CAP_INPUTS", POL, "2026-09-01T00:00:00Z")
    if later["evaluation_arm_id"] == cap["evaluation_arm_id"]:
        f.append("an arm re-registered later kept its earlier identity")

    # --- PROSPECTIVITY IS DERIVED, NOT ASSERTED ---------------------------------------------------
    FIRST = "2026-08-19T17:05:00Z"
    if prospectivity(cap, FIRST)[0] != PROSPECTIVE:
        f.append("an arm registered nine days early was not called prospective")
    if prospectivity(later, FIRST)[0] != RETROSPECTIVE:
        f.append("an arm registered after the cohort was not called retrospective")
    st, why = prospectivity(later, FIRST)
    if "input-policy ablation" not in why:
        f.append("the retrospective verdict does not name what it actually is")
    # registered EXACTLY at first pitch is not before it
    at, _ = register_arm("x", POL, FIRST)
    if prospectivity(at, FIRST)[0] != RETROSPECTIVE:
        f.append("an arm registered exactly at first pitch was called prospective")
    if prospectivity(None, FIRST)[0] != UNDETERMINED:
        f.append("a missing arm record was not undetermined")
    if prospectivity(cap, None)[0] != UNDETERMINED:
        f.append("an unknown cohort start was not undetermined")
    # NO FIELD AN AUTHOR CAN SET ASSERTS IT
    liar = dict(cap, prospective=True, is_prospective="YES", registered_utc="2026-09-01T00:00:00Z")
    if prospectivity(liar, FIRST)[0] != RETROSPECTIVE:
        f.append("an arm claiming prospectivity in a field overrode the derived verdict")

    # --- ONE LATE ARM MAKES THE WHOLE COMPARISON AN ABLATION ---------------------------------------
    lab = label_comparison([cap, sp], FIRST)
    if lab["comparison_label"] != PROSPECTIVE or not lab["identities_distinct"]:
        f.append(f"two early distinct arms did not label prospective: {lab}")
    lab2 = label_comparison([cap, dict(sp, registered_utc="2026-08-25T00:00:00Z")], FIRST)
    if lab2["comparison_label"] != RETROSPECTIVE:
        f.append("a comparison with ONE late arm was still called prospective")
    if "One late arm makes the whole comparison an ablation" not in lab2["note"]:
        f.append("the label does not state the one-late-arm rule")
    lab3 = label_comparison([cap, dict(sp, registered_utc=None)], FIRST)
    if lab3["comparison_label"] != UNDETERMINED:
        f.append("a comparison containing an arm with no registration instant was graded")
    lab4 = label_comparison([cap, same], FIRST)
    if lab4["identities_distinct"]:
        f.append("a comparison between two identical identities was accepted")

    print("evaluation_arm selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("an arm may omit a bound policy",
     "    missing = [k for k in BOUND_POLICIES if not policies.get(k)]", "    missing = []"),
    ("an arm may be registered with no instant",
     "    if not registered_utc:", "    if False:"),
    ("the input policy stops entering the identity, so both arms collapse to one",
     '    payload = {k: policies[k] for k in BOUND_POLICIES}',
     '    payload = {k: policies[k] for k in BOUND_POLICIES if k == "model_id"}'),
    ("the registration instant leaves the identity, so a re-registered arm inherits the old one",
     '    payload["registered_utc"] = registered_utc', "    pass"),
    ("two arms sharing a full policy binding are accepted as distinct",
     "        if aid in seen:", "        if False:"),
    ("an arm with no identity is accepted into a comparison",
     "        if not aid:", "        if False:"),
    ("prospectivity is granted at or after first pitch",
     "    if reg < cohort_first_game_start_utc:", "    if reg <= cohort_first_game_start_utc:"),
    ("prospectivity is granted unconditionally",
     "    if reg < cohort_first_game_start_utc:", "    if True:"),
    ("a missing registration instant is treated as prospective",
     '    if arm_record is None or not arm_record.get("registered_utc"):', "    if False:"),
    ("an unknown cohort start is treated as prospective",
     "    if not cohort_first_game_start_utc:", "    if False:"),
    ("the retrospective verdict stops naming what it is",
     'f"visible, so this is an input-policy ablation and not prospective "', 'f"visible. "'),
    ("one late arm no longer taints the comparison",
     "        elif st == RETROSPECTIVE and worst != UNDETERMINED:", "        elif False:"),
    ("an undetermined arm no longer taints the comparison",
     "        if st == UNDETERMINED:", "        if False:"),
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
