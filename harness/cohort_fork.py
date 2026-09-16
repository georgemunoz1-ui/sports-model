#!/usr/bin/env python3
"""COHORT FORK — a pregame change forks a new cohort; a post-start change is a counterfactual.

OWNER SPECIFICATION 2026-08-23 (three-arm requirement):
    * Pregame starter/lineup/injury changes MAY FORK A NEW COHORT.
    * Post-start updates are COUNTERFACTUAL and PROSPECTIVELY INELIGIBLE.

THE TWO RULES ARE OPPOSITES AND THE CLOCK IS WHAT SEPARATES THEM. Before first pitch, new
information is legitimately available to a forecaster, so a revised forecast is a real forecast —
but it is a DIFFERENT forecast, and letting it overwrite the original would silently convert a
registered prediction into whatever the last update said. So it forks: the original cohort stays
registered and gradeable, and the revision registers beside it as its own cohort with its own
identity. Both get graded. Neither is deleted.

After first pitch, a "revision" is not a forecast at all. It is a statement about what the model
would have said had it known something it did not know. That is a counterfactual, and counterfactuals
are PROSPECTIVELY INELIGIBLE: they may be recorded for study and may never enter a prospective
score, a promotion sample, or a paired comparison. The failure mode this prevents is the most
tempting one in the whole system — regenerating a card at 23:00Z with the confirmed lineups and
scoring it as though it had been made at 10:00Z.

WHAT COUNTS AS A FORKABLE CHANGE. A change to the INFORMATION the forecast consumed: a starter
change, a lineup or availability change, an injury or inactive designation, a venue change. A change
to the MODEL is not a fork — that is a new arm, and it goes through evaluation_arm. A change to
PRICES is neither: prices never touch a winner probability, so a price move forks nothing.
"""
from __future__ import annotations

MODULE_ID = "cohort_fork"

import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Information changes that may fork a cohort.
FORKABLE = ("STARTER_CHANGE", "LINEUP_CHANGE", "AVAILABILITY_CHANGE", "INJURY_DESIGNATION",
            "INACTIVE_DESIGNATION", "VENUE_CHANGE", "NEUTRAL_SITE_DESIGNATION")
# Changes that are NOT forks.
NOT_A_FORK = {
    "PRICE_MOVE": ("prices never enter a winner probability, so a price move changes the action "
                   "overlay and forks nothing"),
    "MODEL_CHANGE": ("a change to the model is a NEW ARM, registered through evaluation_arm, not a "
                     "fork of this one"),
    "FEATURE_SET_CHANGE": ("a feature-set change is a SLOW-layer act at a formal model release and "
                           "is a new arm, not a fork"),
    "COSMETIC": "a presentation change is not an information change",
}

FORK_REGISTERED = "FORK_REGISTERED_NEW_COHORT"
NO_FORK = "NO_FORK"
COUNTERFACTUAL = "COUNTERFACTUAL_PROSPECTIVELY_INELIGIBLE"
REFUSED = "REFUSED"


def classify_change(change_type, change_utc, game_start_utc):
    """(status, reason). The clock decides, and a missing clock refuses rather than assumes."""
    if change_type in NOT_A_FORK:
        return NO_FORK, f"{change_type}: {NOT_A_FORK[change_type]}"
    if change_type not in FORKABLE:
        return REFUSED, (f"{change_type!r} is not a recognised change type; an unrecognised change "
                         f"cannot be classified and is refused rather than guessed")
    if not change_utc or not game_start_utc:
        return REFUSED, ("both the change instant and the game start are required; a change whose "
                         "timing cannot be established is refused, never assumed pregame")
    if change_utc < game_start_utc:
        return FORK_REGISTERED, (f"{change_type} at {change_utc}, before first pitch "
                                 f"{game_start_utc}: a new cohort forks and the original stays "
                                 f"registered and gradeable")
    return COUNTERFACTUAL, (f"{change_type} at {change_utc}, at or after first pitch "
                            f"{game_start_utc}: this is a statement about what the model would have "
                            f"said had it known something it did not know. Recordable for study, "
                            f"PROSPECTIVELY INELIGIBLE for any score, promotion sample or paired "
                            f"comparison.")


def fork_cohort(parent_cohort_id, change_type, change_utc, game_start_utc, changed_games,
                new_evidence_sha256=None):
    """(record, failures). Builds the forked cohort, or refuses.

    The parent is never modified: a fork ADDS a cohort, and the original remains exactly as
    registered (R3/R6)."""
    status, why = classify_change(change_type, change_utc, game_start_utc)
    if status != FORK_REGISTERED:
        return None, [f"{status}: {why}"]
    if not parent_cohort_id:
        return None, ["a fork must name the cohort it forks from"]
    if not changed_games:
        return None, ["a fork with no changed game is a relabelling, not a fork"]
    payload = {"parent": parent_cohort_id, "change_type": change_type, "change_utc": change_utc,
               "changed_games": sorted(changed_games),
               "new_evidence_sha256": new_evidence_sha256}
    cid = "cohort_" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
    return {
        "cohort_id": cid,
        "parent_cohort_id": parent_cohort_id,
        "forked_utc": change_utc,
        "fork_reason": change_type,
        "changed_games": sorted(changed_games),
        "new_evidence_sha256": new_evidence_sha256,
        "parent_status": "REGISTERED_AND_GRADEABLE_UNCHANGED",
        "both_cohorts_graded": True,
        "note": ("The parent cohort is not superseded, retracted or rewritten. Both cohorts are "
                 "graded separately; a fork adds a forecast, it never replaces one."),
    }, []


def eligibility(cohort_record):
    """(prospectively_eligible, reason) for any cohort — original or forked."""
    if cohort_record is None:
        return False, "no cohort record"
    if cohort_record.get("counterfactual"):
        return False, ("marked counterfactual: prospectively ineligible for any score, promotion "
                       "sample or paired comparison")
    fu, gs = cohort_record.get("forked_utc"), cohort_record.get("earliest_game_start_utc")
    if fu and gs and not (fu < gs):
        return False, (f"the cohort was created at {fu}, at or after its earliest game start {gs}: "
                       f"prospectively ineligible")
    return True, "prospectively eligible"


def record_counterfactual(parent_cohort_id, change_type, change_utc, game_start_utc, changed_games,
                          reason=None):
    """A post-start revision, RECORDED and permanently marked ineligible.

    It is recorded rather than discarded because 'what would the model have said' is a useful
    diagnostic — and it is marked at creation, in the same object, so no downstream consumer can
    pick it up without seeing the mark."""
    status, why = classify_change(change_type, change_utc, game_start_utc)
    if status != COUNTERFACTUAL:
        return None, [f"this is not a post-start change ({status}: {why})"]
    return {
        "counterfactual": True,
        "prospectively_eligible": False,
        "parent_cohort_id": parent_cohort_id,
        "change_type": change_type,
        "change_utc": change_utc,
        "game_start_utc": game_start_utc,
        "changed_games": sorted(changed_games or []),
        "reason": reason,
        "why_ineligible": why,
        "permitted_uses": ["diagnostic study", "attribution analysis"],
        "forbidden_uses": ["prospective score", "promotion sample", "paired comparison",
                           "any published record", "any action"],
    }, []


def selftest():
    f = []
    START = "2026-08-23T17:05:00Z"
    PRE, POST = "2026-08-23T14:30:00Z", "2026-08-23T19:40:00Z"

    # --- PREGAME INFORMATION CHANGES FORK -------------------------------------------------------
    for ct in FORKABLE:
        st, why = classify_change(ct, PRE, START)
        if st != FORK_REGISTERED:
            f.append(f"a pregame {ct} did not fork: {st}")
        if "stays\n" not in why and "stays registered" not in why:
            f.append(f"the {ct} fork does not say the original stays registered")
    # --- POST-START CHANGES ARE COUNTERFACTUALS --------------------------------------------------
    for ct in FORKABLE:
        st, why = classify_change(ct, POST, START)
        if st != COUNTERFACTUAL:
            f.append(f"a post-start {ct} was not marked counterfactual: {st}")
        if "PROSPECTIVELY INELIGIBLE" not in why:
            f.append(f"the post-start {ct} verdict does not state ineligibility")
    # THE BOUNDARY: exactly at first pitch is NOT pregame
    if classify_change("STARTER_CHANGE", START, START)[0] != COUNTERFACTUAL:
        f.append("a change exactly at first pitch was treated as pregame")
    if classify_change("STARTER_CHANGE", "2026-08-23T17:04:59Z", START)[0] != FORK_REGISTERED:
        f.append("a change one second before first pitch was refused")

    # --- WHAT IS NOT A FORK -----------------------------------------------------------------------
    for ct, frag in (("PRICE_MOVE", "never enter a winner probability"),
                     ("MODEL_CHANGE", "NEW ARM"),
                     ("FEATURE_SET_CHANGE", "new arm, not a fork"),
                     ("COSMETIC", "not an information change")):
        st, why = classify_change(ct, PRE, START)
        if st != NO_FORK:
            f.append(f"{ct} was treated as a fork: {st}")
        if frag not in why:
            f.append(f"the {ct} refusal does not explain itself: {why}")
    # a price move AFTER first pitch is still not a fork and still not a counterfactual
    if classify_change("PRICE_MOVE", POST, START)[0] != NO_FORK:
        f.append("a post-start price move was misclassified")
    # an unrecognised change is REFUSED, not guessed
    st, why = classify_change("SOMETHING_NEW", PRE, START)
    if st != REFUSED or "refused rather than guessed" not in why:
        f.append(f"an unrecognised change type was classified anyway: {st}")
    # missing timing is refused, never assumed pregame
    for kw in ({"change_utc": None}, {"game_start_utc": None}):
        args = {"change_type": "STARTER_CHANGE", "change_utc": PRE, "game_start_utc": START}
        args.update(kw)
        st, why = classify_change(**args)
        if st != REFUSED:
            f.append(f"a change with {kw} was classified as {st}")
        if "never assumed pregame" not in why:
            f.append("the timing refusal does not say it will not assume pregame")

    # --- FORKING --------------------------------------------------------------------------------
    rec, ff = fork_cohort("cohort_parent", "STARTER_CHANGE", PRE, START, ["STL@PHI"], "abc123")
    if ff:
        f.append(f"a legitimate pregame fork was refused: {ff}")
    else:
        if rec["parent_cohort_id"] != "cohort_parent":
            f.append("the fork lost its parent")
        if rec["parent_status"] != "REGISTERED_AND_GRADEABLE_UNCHANGED":
            f.append("the fork did not preserve the parent's status")
        if not rec["both_cohorts_graded"]:
            f.append("the fork does not grade both cohorts")
        if "never replaces one" not in rec["note"]:
            f.append("the fork note does not say the parent is not replaced")
    # the cohort id must depend on WHAT changed
    r2, _ = fork_cohort("cohort_parent", "STARTER_CHANGE", PRE, START, ["TOR@NYY"], "abc123")
    if r2["cohort_id"] == rec["cohort_id"]:
        f.append("two forks over different games share a cohort id")
    r3, _ = fork_cohort("cohort_parent", "LINEUP_CHANGE", PRE, START, ["STL@PHI"], "abc123")
    if r3["cohort_id"] == rec["cohort_id"]:
        f.append("two forks for different reasons share a cohort id")
    r4, _ = fork_cohort("cohort_parent", "STARTER_CHANGE", PRE, START, ["STL@PHI"], "DIFFERENT")
    if r4["cohort_id"] == rec["cohort_id"]:
        f.append("the cohort id ignores the new evidence hash")
    # POST-START MAY NOT FORK
    r5, ff5 = fork_cohort("cohort_parent", "STARTER_CHANGE", POST, START, ["STL@PHI"])
    if r5 is not None or not any(COUNTERFACTUAL in x for x in ff5):
        f.append("a post-start change was allowed to fork a cohort")
    # a fork with no changed game is a relabelling
    if fork_cohort("cohort_parent", "STARTER_CHANGE", PRE, START, [])[0] is not None:
        f.append("a fork with no changed game was registered")
    if fork_cohort(None, "STARTER_CHANGE", PRE, START, ["A@B"])[0] is not None:
        f.append("a fork with no parent was registered")

    # --- COUNTERFACTUAL RECORDING ------------------------------------------------------------------
    cf, cff = record_counterfactual("cohort_parent", "LINEUP_CHANGE", POST, START, ["STL@PHI"],
                                    "confirmed lineups posted after first pitch")
    if cff:
        f.append(f"a legitimate counterfactual was refused: {cff}")
    else:
        if cf.get("prospectively_eligible") is not False or cf.get("counterfactual") is not True:
            f.append("a counterfactual was not marked ineligible at creation")
        for forbidden in ("prospective score", "promotion sample", "paired comparison"):
            if forbidden not in cf["forbidden_uses"]:
                f.append(f"the counterfactual does not forbid use in a {forbidden}")
        if "diagnostic study" not in cf["permitted_uses"]:
            f.append("the counterfactual forbids even diagnostic use, which is over-strict")
    # a PREGAME change may not be recorded as a counterfactual
    if record_counterfactual("p", "STARTER_CHANGE", PRE, START, ["A@B"])[0] is not None:
        f.append("a pregame change was recorded as a counterfactual")

    # --- ELIGIBILITY ---------------------------------------------------------------------------------
    okE, why = eligibility({"forked_utc": PRE, "earliest_game_start_utc": START})
    if not okE:
        f.append(f"a pregame fork was ruled ineligible: {why}")
    if eligibility({"counterfactual": True})[0]:
        f.append("a counterfactual was ruled prospectively eligible")
    if eligibility({"forked_utc": POST, "earliest_game_start_utc": START})[0]:
        f.append("a cohort created after its earliest game start was ruled eligible")
    if eligibility({"forked_utc": START, "earliest_game_start_utc": START})[0]:
        f.append("a cohort created exactly at first pitch was ruled eligible")
    if eligibility(None)[0]:
        f.append("a missing cohort record was ruled eligible")

    print("cohort_fork selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("a post-start change forks a cohort instead of becoming a counterfactual",
     "    if change_utc < game_start_utc:", "    if True:"),
    ("the first-pitch boundary becomes inclusive",
     "    if change_utc < game_start_utc:", "    if change_utc <= game_start_utc:"),
    ("a change with no timing is assumed pregame",
     "    if not change_utc or not game_start_utc:", "    if False:"),
    ("an unrecognised change type is treated as forkable",
     "    if change_type not in FORKABLE:", "    if False:"),
    ("a PRICE MOVE forks a cohort",
     "    if change_type in NOT_A_FORK:", "    if False:"),
    ("a model change is treated as a fork rather than a new arm",
     '    "MODEL_CHANGE": ("a change to the model is a NEW ARM, registered through evaluation_arm, not a "\n                     "fork of this one"),', ""),
    ("a post-start change may fork after all",
     "    if status != FORK_REGISTERED:\n        return None, [f\"{status}: {why}\"]",
     "    if False:\n        return None, [f\"{status}: {why}\"]"),
    ("the fork silently supersedes its parent",
     '        "parent_status": "REGISTERED_AND_GRADEABLE_UNCHANGED",',
     '        "parent_status": "SUPERSEDED",'),
    ("only one of the two cohorts is graded",
     '        "both_cohorts_graded": True,', '        "both_cohorts_graded": False,'),
    ("the cohort id ignores which games changed",
     '    payload = {"parent": parent_cohort_id, "change_type": change_type, "change_utc": change_utc,\n               "changed_games": sorted(changed_games),',
     '    payload = {"parent": parent_cohort_id, "change_type": change_type, "change_utc": change_utc,\n               "changed_games": [],'),
    ("a fork with no changed game is registered",
     "    if not changed_games:", "    if False:"),
    ("a fork with no parent is registered",
     "    if not parent_cohort_id:", "    if False:"),
    ("a counterfactual is created prospectively ELIGIBLE",
     '        "prospectively_eligible": False,', '        "prospectively_eligible": True,'),
    ("a counterfactual no longer forbids use in a promotion sample",
     '        "forbidden_uses": ["prospective score", "promotion sample", "paired comparison",\n                           "any published record", "any action"],',
     '        "forbidden_uses": [],'),
    ("a pregame change may be recorded as a counterfactual",
     "    if status != COUNTERFACTUAL:\n        return None, [f\"this is not a post-start change",
     "    if False:\n        return None, [f\"this is not a post-start change"),
    ("eligibility ignores the counterfactual mark",
     '    if cohort_record.get("counterfactual"):', "    if False:"),
    ("eligibility ignores a cohort created after its own games started",
     "    if fu and gs and not (fu < gs):", "    if False:"),
    ("a missing cohort record is ruled eligible",
     "    if cohort_record is None:", "    if False:"),
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
