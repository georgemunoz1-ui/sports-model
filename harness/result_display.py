"""RESULT_DISPLAY and CANONICAL_EVIDENCE_ADMISSION are separate layers — owner ruling 2026-08-25.

THE DEFECT THIS FIXES. On 2026-08-25 I reported the 8/24 cohort as "12 games registered and
unsettled — nothing gradable" while the owner was looking at eleven finals on the public scoreboard.
Both statements were true in their own layer and I had collapsed the layers: canonical admission
(what may settle a ledger, feed a prior, or enter an estimator) was allowed to decide what the
reader was SHOWN. Missing provenance blocked the results card itself, so the card lied by omission
about games the whole world could see.

The rule, verbatim from the ruling:

    Missing canonical provenance may block settlement, promotion and estimator input; it may never
    hide an available score from the visible results card.

TWO LAYERS, TWO QUESTIONS:

  RESULT_DISPLAY              "what happened, as best we can currently see?" Admits OWNER_RELAY and
                              tier-3 scores, labelled with their grade. A shown score is a report,
                              not a settlement.
  CANONICAL_EVIDENCE_ADMISSION "what may change a ledger, a prior, a promotion count or an
                              estimator?" Requires a retained artifact: game id, retrieval
                              timestamp, content hash. Unchanged by this ruling.

The gate in this module enforces BOTH failure modes: a display row may not claim canonical effect,
and an available score may not be withheld from display on provenance grounds. Hiding and
laundering are the two ways to break the wall, and each has its own refusal.
"""

MODULE_ID = "result_display"

import sys

DISPLAY_OK = "RESULT_DISPLAY_OK"
DISPLAY_REFUSED = "RESULT_DISPLAY_REFUSED"

#: grades a display row may carry. Every row must say how good its score is.
DISPLAY_GRADES = ("CANONICAL_TIER1", "PROVISIONAL_TIER3", "OWNER_RELAY", "LIVE_UNOFFICIAL")
#: grades that may ALSO enter the canonical layer
CANONICAL_GRADES = ("CANONICAL_TIER1",)

#: canonical effects a non-canonical row must never claim
CANONICAL_EFFECTS = ("settles_ledger", "enters_prior_pool", "counts_toward_promotion",
                     "enters_estimator", "grades_officially")

HIDDEN = "AVAILABLE_SCORE_HIDDEN_FROM_DISPLAY"
LAUNDERED = "NON_CANONICAL_SCORE_CLAIMS_CANONICAL_EFFECT"
UNGRADED = "DISPLAY_ROW_WITHOUT_A_SOURCE_GRADE"
LIVE_AS_FINAL = "LIVE_GAME_DISPLAYED_AS_FINAL"


def display_gate(available_scores, display_rows):
    """Both directions: nothing available is hidden; nothing shown claims more than its grade."""
    problems = []
    shown = {r.get("game") for r in display_rows or []}
    for g, info in (available_scores or {}).items():
        if g not in shown:
            problems.append({"code": HIDDEN, "game": g, "grade": info.get("grade"),
                             "note": "missing canonical provenance blocks settlement, promotion "
                                     "and estimator input; it may never hide an available score "
                                     "from the visible results card"})
    for r in display_rows or []:
        grade = r.get("source_grade")
        if grade not in DISPLAY_GRADES:
            problems.append({"code": UNGRADED, "game": r.get("game"), "grade": grade})
            continue
        if grade not in CANONICAL_GRADES:
            claimed = [e for e in CANONICAL_EFFECTS if r.get(e)]
            if claimed:
                problems.append({"code": LAUNDERED, "game": r.get("game"), "grade": grade,
                                 "claims": claimed,
                                 "note": "a shown score is a report, not a settlement; canonical "
                                         "effect still requires a retained artifact"})
        if r.get("status") == "LIVE" and r.get("displayed_as_final"):
            problems.append({"code": LIVE_AS_FINAL, "game": r.get("game")})
    return {"status": DISPLAY_OK if not problems else DISPLAY_REFUSED,
            "n_problems": len(problems), "problems": problems}


# =================================================================================================
def selftest():
    f = []
    AVAIL = {"mlb:BOS@MIA": {"grade": "OWNER_RELAY"}, "mlb:PIT@SD": {"grade": "LIVE_UNOFFICIAL"}}
    good = [{"game": "mlb:BOS@MIA", "source_grade": "OWNER_RELAY", "status": "FINAL"},
            {"game": "mlb:PIT@SD", "source_grade": "LIVE_UNOFFICIAL", "status": "LIVE"}]
    if display_gate(AVAIL, good)["status"] != DISPLAY_OK:
        f.append(f"a complete, honestly-graded card must pass: {display_gate(AVAIL, good)}")

    # THE RULING'S CORE CASE: an available score withheld on provenance grounds is refused
    hid = display_gate(AVAIL, good[:1])
    if hid["status"] != DISPLAY_REFUSED or not any(p["code"] == HIDDEN for p in hid["problems"]):
        f.append("withholding an available score must be refused")
    if not any(p["game"] == "mlb:PIT@SD" for p in hid["problems"]):
        f.append("the hidden game must be named")
    if "never hide" not in str(hid["problems"]):
        f.append("the refusal must state the ruling")

    # ...and the OTHER direction: a relayed score may not claim canonical effect. The five effects
    # are NAMED EXPLICITLY, not looped from CANONICAL_EFFECTS — a fixture that iterates the list
    # under test cannot notice an entry being deleted from it.
    for eff in ("settles_ledger", "enters_prior_pool", "counts_toward_promotion",
                "enters_estimator", "grades_officially"):
        bad = [dict(good[0], **{eff: True})]
        got = display_gate({"mlb:BOS@MIA": AVAIL["mlb:BOS@MIA"]}, bad)
        if not any(p["code"] == LAUNDERED and eff in p["claims"] for p in got["problems"]):
            f.append(f"an OWNER_RELAY row claiming {eff} must be refused")
    # a genuinely canonical row MAY claim them
    can = [{"game": "x", "source_grade": "CANONICAL_TIER1", "status": "FINAL",
            "settles_ledger": True}]
    if display_gate({"x": {"grade": "CANONICAL_TIER1"}}, can)["status"] != DISPLAY_OK:
        f.append("a tier-1 row may carry canonical effect")

    # a row must say how good its score is
    if not any(p["code"] == UNGRADED for p in
               display_gate({}, [{"game": "y", "status": "FINAL"}])["problems"]):
        f.append("an ungraded display row must be refused")
    # a live game shown as final is a lie of a different kind
    if not any(p["code"] == LIVE_AS_FINAL for p in
               display_gate({}, [{"game": "z", "source_grade": "LIVE_UNOFFICIAL",
                                  "status": "LIVE", "displayed_as_final": True}])["problems"]):
        f.append("a live game displayed as final must be refused")

    print("result_display selftest:", "OK" if not f else "FAIL")
    for x in f:
        print("   -", x)
    return not f


MUTANTS = [
    ("an available score may be hidden from the card again",
     "        if g not in shown:", "        if False:"),
    ("a relayed score may settle the ledger",
     "            claimed = [e for e in CANONICAL_EFFECTS if r.get(e)]",
     "            claimed = []"),
    ("every grade becomes canonical",
     'CANONICAL_GRADES = ("CANONICAL_TIER1",)',
     'CANONICAL_GRADES = ("CANONICAL_TIER1", "OWNER_RELAY", "PROVISIONAL_TIER3", "LIVE_UNOFFICIAL")'),
    ("a display row no longer needs a source grade",
     "        if grade not in DISPLAY_GRADES:", "        if False:"),
    ("a live game may be displayed as final",
     '        if r.get("status") == "LIVE" and r.get("displayed_as_final"):', "        if False:"),
    ("the hidden-score refusal stops stating the ruling",
     '"note": "missing canonical provenance blocks settlement, promotion "\n                                     "and estimator input; it may never hide an available score "\n                                     "from the visible results card"',
     '"note": "missing"'),
    ("a canonical effect is dropped from the protected list",
     '"counts_toward_promotion",\n                     "enters_estimator",', '"enters_estimator",'),
]


def mutation_suite():
    src = open(__file__).read()
    import io as _io, contextlib as _cl
    _b = _io.StringIO()
    with _cl.redirect_stdout(_b):
        _base = selftest()
    if not _base:
        print("  BASELINE_FAILING  the unmutated selftest does not pass")
        print(_b.getvalue().strip())
        return False
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
