"""STATE COHERENCE — a page may not assert two states that cannot both be true.

EVERY PAIR BELOW SHIPPED AT LEAST ONCE. This gate exists because each of these contradictions
survived every other check: the render contract audits labels and tokens, the decision gates audit
rows, the manifest audits identities — and none of them reads the page as a set of CLAIMS that must
be mutually consistent. A page that says PENDING_OWNER_RELAY beside a captured price artifact is
not wrong in any label; it is wrong as a whole.

The six registered incoherence pairs (owner directive 2026-08-25):

    PENDING_OWNER_RELAY        while a captured price artifact exists for the slate
    FORECAST_ONLY_NO_MARKET_GRADE  while a complete market board is on file
    NO_LOG                     while game-log rows for that pitcher are retained or relayed
    TBD                        after a later starter identity is known, without replacement status
    "Decision Board" title     while the system is SYSTEM_NOT_DECISION_READY
    component acceptance totals shown without the COMBINED figure
"""

from __future__ import annotations

MODULE_ID = "state_coherence"

import re
import sys

OK = "STATE_COHERENT"
REFUSED = "STATE_INCOHERENT"

RULES = (
    ("RELAY_PENDING_WITH_CAPTURED_PRICES",
     "the page says PENDING_OWNER_RELAY while a captured price artifact exists"),
    ("NO_MARKET_GRADE_WITH_COMPLETE_BOARD",
     "the page says FORECAST_ONLY_NO_MARKET_GRADE while a complete market board is on file"),
    ("NO_LOG_WITH_RETAINED_LOGS",
     "a pitcher is called NO_LOG while log rows for them are retained or relayed"),
    ("TBD_WITHOUT_REPLACEMENT_STATUS",
     "a starter is shown TBD after a later identity is known, with no replacement status"),
    ("DECISION_TITLE_WHILE_NOT_READY",
     "the document titles itself a Decision Board while SYSTEM_NOT_DECISION_READY"),
    ("COMPONENT_TOTALS_WITHOUT_COMBINED",
     "acceptance component totals are shown without the COMBINED figure"),
)


def check(page_text, facts):
    """facts: {"captured_price_artifact": bool, "complete_market_board": bool,
               "pitchers_with_logs": [names], "resolved_late_starters": [names],
               "system_not_decision_ready": bool, "combined_acceptance": "16/16"|None}
    The FACTS come from the records, never from the page — the page is the thing on trial."""
    t = page_text
    problems = []
    if facts.get("captured_price_artifact") and "PENDING_OWNER_RELAY" in t:
        problems.append({"code": "RELAY_PENDING_WITH_CAPTURED_PRICES"})
    if facts.get("complete_market_board") and "FORECAST_ONLY_NO_MARKET_GRADE" in t:
        problems.append({"code": "NO_MARKET_GRADE_WITH_COMPLETE_BOARD"})
    for name in facts.get("pitchers_with_logs") or []:
        # NO_LOG within ~120 chars of the pitcher's name is a claim about that pitcher
        for m in re.finditer(re.escape(name), t):
            lo, hi = max(0, m.start() - 120), m.end() + 120
            if "NO_LOG" in t[lo:hi] or "no pitcher log" in t[lo:hi]:
                problems.append({"code": "NO_LOG_WITH_RETAINED_LOGS", "pitcher": name})
                break
    for name in facts.get("resolved_late_starters") or []:
        if name not in t:
            continue
        for m in re.finditer(re.escape(name), t):
            lo, hi = max(0, m.start() - 200), m.end() + 200
            seg = t[lo:hi]
            if "TBD" in seg and "REPLACEMENT" not in seg.upper():
                problems.append({"code": "TBD_WITHOUT_REPLACEMENT_STATUS", "starter": name})
                break
    if facts.get("system_not_decision_ready"):
        m = re.search(r"<title>([^<]*)</title>", t)
        if m and "decision board" in m.group(1).lower():
            problems.append({"code": "DECISION_TITLE_WHILE_NOT_READY", "title": m.group(1)})
    comb = facts.get("combined_acceptance")
    if comb:
        has_components = bool(re.search(r"12\s*/\s*12", t)) and bool(re.search(r"4\s*/\s*4", t))
        if has_components and f"COMBINED {comb}" not in t and f"combined {comb}" not in t:
            problems.append({"code": "COMPONENT_TOTALS_WITHOUT_COMBINED", "expected": comb})
    return {"status": OK if not problems else REFUSED,
            "n_problems": len(problems), "problems": problems}


# =================================================================================================
def selftest():
    f = []
    FACTS = {"captured_price_artifact": True, "complete_market_board": True,
             "pitchers_with_logs": ["Jackson Jobe"], "resolved_late_starters": ["Tyler Phillips"],
             "system_not_decision_ready": True, "combined_acceptance": "16/16"}
    CLEAN = ("<title>August 25 Forecast &amp; Market Review</title> MARKET_CAPTURED_CURRENT "
             "Jackson Jobe SMALL_SAMPLE_FALLBACK ... Tyler Phillips REPLACEMENT registered over an "
             "official TBD ... acceptance 12/12 and 4/4, COMBINED 16/16")
    r = check(CLEAN, FACTS)
    if r["status"] != OK:
        f.append(f"a coherent page must pass: {r['problems']}")

    # each of the six pairs must be individually refused, BY ITS OWN CODE
    cases = [
        ("PENDING_OWNER_RELAY on prices", CLEAN + " prices PENDING_OWNER_RELAY",
         "RELAY_PENDING_WITH_CAPTURED_PRICES"),
        ("no-market grade with a board", CLEAN + " FORECAST_ONLY_NO_MARKET_GRADE",
         "NO_MARKET_GRADE_WITH_COMPLETE_BOARD"),
        ("NO_LOG beside a logged pitcher", CLEAN + " Jackson Jobe NO_LOG on file",
         "NO_LOG_WITH_RETAINED_LOGS"),
        ("TBD after resolution, no replacement", CLEAN.replace(
            "Tyler Phillips REPLACEMENT registered over an official TBD",
            "home starter TBD (Tyler Phillips)"), "TBD_WITHOUT_REPLACEMENT_STATUS"),
        ("Decision Board title while not ready", CLEAN.replace(
            "August 25 Forecast &amp; Market Review", "August 25 Decision Board"),
         "DECISION_TITLE_WHILE_NOT_READY"),
        ("components without combined", CLEAN.replace(", COMBINED 16/16", ""),
         "COMPONENT_TOTALS_WITHOUT_COMBINED"),
    ]
    for name, text, code in cases:
        got = check(text, FACTS)
        if got["status"] != REFUSED or not any(p["code"] == code for p in got["problems"]):
            f.append(f"{name} must be refused by {code}, got {got['problems']}")

    # the facts gate the rules: with no captured artifact, PENDING_OWNER_RELAY is legitimate
    relay_ok = check("prices PENDING_OWNER_RELAY", dict(FACTS, captured_price_artifact=False,
                     complete_market_board=False, system_not_decision_ready=False,
                     combined_acceptance=None, pitchers_with_logs=[], resolved_late_starters=[]))
    if relay_ok["status"] != OK:
        f.append("PENDING_OWNER_RELAY with no captured artifact is a legitimate state")
    # a ready system may title itself a decision board
    ready = check("<title>August 26 Decision Board</title>",
                  dict(FACTS, system_not_decision_ready=False, captured_price_artifact=False,
                       complete_market_board=False, combined_acceptance=None,
                       pitchers_with_logs=[], resolved_late_starters=[]))
    if ready["status"] != OK:
        f.append("a decision-ready system may use the Decision Board title")
    # NO_LOG far from any named pitcher is not a claim about them
    far = check("Jackson Jobe pitched well." + " x" * 200 + " NO_LOG for an unrelated file",
                dict(FACTS, captured_price_artifact=False, complete_market_board=False,
                     system_not_decision_ready=False, combined_acceptance=None,
                     resolved_late_starters=[]))
    if far["status"] != OK:
        f.append("NO_LOG distant from the pitcher's name is not a claim about that pitcher")

    print("state_coherence selftest:", "OK" if not f else "FAIL")
    for x in f:
        print("   -", x)
    return not f


MUTANTS = [
    ("captured prices stop contradicting PENDING_OWNER_RELAY",
     '    if facts.get("captured_price_artifact") and "PENDING_OWNER_RELAY" in t:', "    if False:"),
    ("a complete board stops contradicting the no-market grade",
     '    if facts.get("complete_market_board") and "FORECAST_ONLY_NO_MARKET_GRADE" in t:',
     "    if False:"),
    ("NO_LOG beside a logged pitcher is allowed",
     '            if "NO_LOG" in t[lo:hi] or "no pitcher log" in t[lo:hi]:', "            if False:"),
    ("a stale TBD needs no replacement status",
     '            if "TBD" in seg and "REPLACEMENT" not in seg.upper():', "            if False:"),
    ("the Decision Board title is allowed while not ready",
     '        if m and "decision board" in m.group(1).lower():', "        if False:"),
    ("component totals no longer need the combined figure",
     '        if has_components and f"COMBINED {comb}" not in t and f"combined {comb}" not in t:',
     "        if False:"),
    ("the facts stop gating the rules, so a legitimate relay state is refused",
     '    if facts.get("captured_price_artifact") and "PENDING_OWNER_RELAY" in t:',
     '    if "PENDING_OWNER_RELAY" in t:'),
    ("proximity stops mattering, so any NO_LOG anywhere indicts every pitcher",
     "            lo, hi = max(0, m.start() - 120), m.end() + 120",
     "            lo, hi = 0, len(t)"),
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
