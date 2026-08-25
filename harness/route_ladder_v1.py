"""The v1.0 seven-rung ROUTE ladder (Pregame Decision Readiness section 2). A blocked rail ADVANCES; it never concludes.

THE RULE THIS ENCODES. "statsapi is blocked" is a fact about my access. "The starter is unknown" is
a claim about the world. Turning the first into the second is the single failure this module exists
to prevent, and it is the failure that produced a slate of blocked rows on 2026-08-24 and 08-25.

    OFFICIAL_API -> OFFICIAL_LEAGUE_PAGE -> OFFICIAL_TEAM_PAGE_OR_STATUS -> DIRECT_SPORTSBOOK
      -> NAMED_AGGREGATOR -> WEB_SEARCH_OPEN -> OWNER_RELAY

Two things the ladder is strict about:

TERMINATION. attempt() may return EXHAUSTED only when every authorized rung has been tried for the
field in question. A run that stops at rung 2 with rungs 3-7 untried is INCOMPLETE, and INCOMPLETE
is a defect in the acquisition, never a statement about the data.

AUTHORITY. A rung's output is only as authoritative as the rung. WEB_SEARCH_OPEN may IDENTIFY an
artifact or report a PROVISIONAL status; it may not supply an authoritative field while a route
capable of supplying one remains untried. That is the snippet rule from section 2, made executable:
a search result naming "Athletics 4, Astros 3" identifies a game and does not confirm a score.
"""

MODULE_ID = "route_ladder_v1"

import sys

RUNGS = (
    ("OFFICIAL_API", "AUTHORITATIVE", "the league's own machine interface — statsapi, stats.wnba"),
    ("OFFICIAL_LEAGUE_PAGE", "AUTHORITATIVE", "the league's own published page for the game"),
    ("OFFICIAL_TEAM_PAGE_OR_STATUS", "AUTHORITATIVE", "the club's own page or status post — often "
                                                      "the first place a scratch or lineup appears"),
    ("DIRECT_SPORTSBOOK", "AUTHORITATIVE_FOR_PRICE", "the named book itself; the only rung that is "
                                                     "authoritative for a price"),
    ("NAMED_AGGREGATOR", "CORROBORATING", "a named aggregator displaying an identified book"),
    ("WEB_SEARCH_OPEN", "IDENTIFYING_ONLY", "may identify an artifact or report a PROVISIONAL "
                                            "status; never an authoritative field on its own"),
    ("OWNER_RELAY", "PROVISIONAL", "a human relays what they can see. Last rung, and its output is "
                                   "provisional until an artifact is retained"),
)
RUNG_NAMES = tuple(r for r, _, _ in RUNGS)
AUTHORITY = {r: a for r, a, _ in RUNGS}

#: which rungs may supply an AUTHORITATIVE value for which kind of field
PRICE_AUTHORITATIVE = ("DIRECT_SPORTSBOOK",)
FACT_AUTHORITATIVE = ("OFFICIAL_API", "OFFICIAL_LEAGUE_PAGE", "OFFICIAL_TEAM_PAGE_OR_STATUS")

EXHAUSTED = "LADDER_EXHAUSTED_NO_ROUTE_REMAINS"
INCOMPLETE = "LADDER_INCOMPLETE_AUTHORIZED_ROUTE_UNTRIED"
ACQUIRED = "ACQUIRED"
OUT_OF_ORDER = "RUNGS_ATTEMPTED_OUT_OF_ORDER"
SNIPPET_AS_AUTHORITY = "SEARCH_SNIPPET_USED_AS_AUTHORITATIVE_FIELD"
SKIPPED = "AUTHORIZED_RUNG_SKIPPED"

#: a rail failure. Any of these ADVANCES the ladder.
RAIL_FAILURES = ("EGRESS_BLOCKED", "TIMEOUT", "HTTP_403", "HTTP_404", "HTTP_429", "HTTP_5XX",
                 "EMPTY_RESPONSE", "RETURNED_TITLES_ONLY", "NOT_ATTEMPTED_BY_POLICY",
                 "NOTHING_RELAYED")


def is_rail_failure(result):
    return str(result) in RAIL_FAILURES


def attempt(field, attempts, authorized=RUNG_NAMES, kind="fact"):
    """Grade one field's acquisition run.

    attempts: [{"rung": str, "result": str, "value": any, "artifact_sha256": str|None}, ...]
    Returns the acquired value with its authority, or a refusal that says which routes remain.
    """
    authorized = [r for r in RUNG_NAMES if r in set(authorized)]
    tried, order, out = [], [], None
    for a in attempts or []:
        rung = a.get("rung")
        if rung not in RUNG_NAMES:
            return {"field": field, "status": "UNKNOWN_RUNG", "rung": rung}
        tried.append(rung)
        order.append(RUNG_NAMES.index(rung))
    if order != sorted(order):
        return {"field": field, "status": OUT_OF_ORDER, "tried": tried,
                "note": "the ladder is ordered by authority; trying a weaker rung first and "
                        "stopping there would accept a weaker answer than was available"}

    good = [a for a in (attempts or [])
            if not is_rail_failure(a.get("result")) and a.get("value") is not None]
    need = PRICE_AUTHORITATIVE if kind == "price" else FACT_AUTHORITATIVE
    for a in good:
        rung = a["rung"]
        auth = AUTHORITY[rung]
        if rung in need:
            return {"field": field, "status": ACQUIRED, "rung": rung, "authority": auth,
                    "value": a["value"], "artifact_sha256": a.get("artifact_sha256")}
        # a non-authoritative rung answered. It may stand ONLY if nothing stronger is left.
        remaining = [r for r in authorized
                     if RUNG_NAMES.index(r) < RUNG_NAMES.index(rung) and r not in tried] + \
                    [r for r in authorized
                     if RUNG_NAMES.index(r) > RUNG_NAMES.index(rung) and r not in tried
                     and r in need]
        if remaining:
            return {"field": field, "status": SNIPPET_AS_AUTHORITY if auth == "IDENTIFYING_ONLY"
                    else INCOMPLETE, "rung": rung, "authority": auth,
                    "routes_untried": remaining,
                    "note": f"{rung} answered at authority {auth} while {remaining} remain untried. "
                            f"A weaker answer may not stand in front of a stronger untried route."}
        out = {"field": field, "status": ACQUIRED, "rung": rung, "authority": auth,
               "value": a["value"], "artifact_sha256": a.get("artifact_sha256"),
               "caveat": f"acquired at {auth}, not {'/'.join(need)}"}
        return out

    untried = [r for r in authorized if r not in tried]
    if untried:
        return {"field": field, "status": INCOMPLETE, "routes_untried": untried, "tried": tried,
                "note": "a rail failure ADVANCES the ladder. Acquisition may not terminate while an "
                        "authorized route is untried, and a blocked rail is never a finding about "
                        "the world."}
    return {"field": field, "status": EXHAUSTED, "tried": tried, "routes_untried": [],
            "note": "every authorized rung attempted and none supplied the field. This is an "
                    "ACQUISITION INCIDENT, not a property of the game."}


# =================================================================================================
def selftest():
    """route_ladder_v1 fixtures. Named for THIS module, so a clobbering rename is visible."""
    f = []
    if len(RUNGS) != 7:
        f.append("the v1.0 ladder has seven rungs")
    if RUNG_NAMES[0] != "OFFICIAL_API" or RUNG_NAMES[-1] != "OWNER_RELAY":
        f.append("the ladder runs OFFICIAL_API first and OWNER_RELAY last")

    B = lambda r: {"rung": r, "result": "EGRESS_BLOCKED", "value": None}

    # a blocked rung ADVANCES: stopping at rung 1 is INCOMPLETE, not "unavailable"
    one = attempt("starter", [B("OFFICIAL_API")])
    if one["status"] != INCOMPLETE:
        f.append(f"a single blocked rung must be INCOMPLETE, got {one['status']}")
    if len(one["routes_untried"]) != 6:
        f.append(f"six routes must remain untried, got {one['routes_untried']}")

    # blocked all the way down is EXHAUSTED — an incident, and only then
    allb = attempt("starter", [B(r) for r in RUNG_NAMES])
    if allb["status"] != EXHAUSTED:
        f.append(f"all seven blocked must be EXHAUSTED, got {allb['status']}")
    if allb["routes_untried"]:
        f.append("EXHAUSTED means nothing remains")
    if "ACQUISITION INCIDENT" not in allb["note"]:
        f.append("exhaustion must be called an incident, not a property of the game")
    if allb["status"] == one["status"]:
        f.append("INCOMPLETE and EXHAUSTED must be distinguishable")

    # an official rung answering is authoritative and stops the ladder
    ok = attempt("starter", [B("OFFICIAL_API"),
                             {"rung": "OFFICIAL_LEAGUE_PAGE", "result": "OK", "value": "Wheeler",
                              "artifact_sha256": "abc"}])
    if ok["status"] != ACQUIRED or ok["authority"] != "AUTHORITATIVE":
        f.append(f"an official page answering must be AUTHORITATIVE ACQUIRED, got {ok}")

    # THE SNIPPET RULE: search answering while official rungs are untried may not stand
    snip = attempt("starter", [B("OFFICIAL_API"),
                              {"rung": "WEB_SEARCH_OPEN", "result": "OK", "value": "Wheeler"}])
    if snip["status"] != SNIPPET_AS_AUTHORITY:
        f.append(f"a snippet answering with official routes untried must refuse, got {snip['status']}")
    if "OFFICIAL_LEAGUE_PAGE" not in snip.get("routes_untried", []):
        f.append("the refusal must name the stronger routes still available")
    # ...but once every stronger route is exhausted it may stand, WITH its caveat
    snip2 = attempt("starter", [B("OFFICIAL_API"), B("OFFICIAL_LEAGUE_PAGE"),
                                B("OFFICIAL_TEAM_PAGE_OR_STATUS"), B("DIRECT_SPORTSBOOK"),
                                B("NAMED_AGGREGATOR"),
                                {"rung": "WEB_SEARCH_OPEN", "result": "OK", "value": "Wheeler"}])
    if snip2["status"] != ACQUIRED:
        f.append(f"a snippet may stand once nothing stronger remains, got {snip2['status']}")
    if "caveat" not in snip2 or snip2["authority"] != "IDENTIFYING_ONLY":
        f.append("a snippet that stands must carry its authority and a caveat")

    # PRICE authority is narrower: only the book itself
    agg = attempt("price", [B("OFFICIAL_API"), B("OFFICIAL_LEAGUE_PAGE"),
                            B("OFFICIAL_TEAM_PAGE_OR_STATUS"),
                            {"rung": "NAMED_AGGREGATOR", "result": "OK", "value": -124}],
                  kind="price")
    if agg["status"] != INCOMPLETE:
        f.append(f"an aggregator price with the book untried must refuse, got {agg['status']}")
    if "DIRECT_SPORTSBOOK" not in agg.get("routes_untried", []):
        f.append("the price refusal must name the book as the untried authoritative route")
    book = attempt("price", [B("OFFICIAL_API"), B("OFFICIAL_LEAGUE_PAGE"),
                             B("OFFICIAL_TEAM_PAGE_OR_STATUS"),
                             {"rung": "DIRECT_SPORTSBOOK", "result": "OK", "value": -124}],
                   kind="price")
    if book["status"] != ACQUIRED or book["authority"] != "AUTHORITATIVE_FOR_PRICE":
        f.append(f"the book itself must be authoritative for a price, got {book}")

    # every rail failure advances. NAMED EXPLICITLY, not looped over RAIL_FAILURES — a fixture that
    # iterates the list under test cannot notice an entry being deleted from it.
    for r in ("EGRESS_BLOCKED", "TIMEOUT", "HTTP_403", "HTTP_404", "HTTP_429", "HTTP_5XX",
              "EMPTY_RESPONSE", "RETURNED_TITLES_ONLY", "NOT_ATTEMPTED_BY_POLICY",
              "NOTHING_RELAYED"):
        if not is_rail_failure(r):
            f.append(f"{r} must be recognised as a rail failure")
        got = attempt("x", [{"rung": "OFFICIAL_API", "result": r, "value": None}])
        if got["status"] != INCOMPLETE:
            f.append(f"rail failure {r} must advance the ladder, got {got['status']}")
    # RETURNED_TITLES_ONLY and NOTHING_RELAYED are the two this repository actually met, and both
    # were once described as findings about the world rather than as rail failures.
    if not (is_rail_failure("RETURNED_TITLES_ONLY") and is_rail_failure("NOTHING_RELAYED")):
        f.append("a titles-only search and an empty relay are rail failures, not answers")
    if is_rail_failure("OK"):
        f.append("a success must not be read as a rail failure")

    # rungs must be attempted in authority order
    oo = attempt("starter", [{"rung": "WEB_SEARCH_OPEN", "result": "EGRESS_BLOCKED", "value": None},
                             B("OFFICIAL_API")])
    if oo["status"] != OUT_OF_ORDER:
        f.append(f"out-of-order attempts must be refused, got {oo['status']}")

    print("route_ladder_v1 selftest:", "OK" if not f else "FAIL")
    for x in f:
        print("   -", x)
    return not f


MUTANTS = [
    ("a blocked first rung terminates the ladder instead of advancing",
     "    untried = [r for r in authorized if r not in tried]\n    if untried:",
     "    untried = []\n    if untried:"),
    ("a search snippet becomes an authoritative field",
     '        if remaining:\n            return {"field": field, "status": SNIPPET_AS_AUTHORITY if auth == "IDENTIFYING_ONLY"',
     '        if False:\n            return {"field": field, "status": SNIPPET_AS_AUTHORITY if auth == "IDENTIFYING_ONLY"'),
    ("an aggregator becomes authoritative for a price",
     'PRICE_AUTHORITATIVE = ("DIRECT_SPORTSBOOK",)',
     'PRICE_AUTHORITATIVE = ("DIRECT_SPORTSBOOK", "NAMED_AGGREGATOR")'),
    ("INCOMPLETE and EXHAUSTED collapse into one status",
     'EXHAUSTED = "LADDER_EXHAUSTED_NO_ROUTE_REMAINS"',
     'EXHAUSTED = "LADDER_INCOMPLETE_AUTHORIZED_ROUTE_UNTRIED"'),
    ("exhaustion stops being called an incident",
     '"ACQUISITION INCIDENT, not a property of the game."', '"unavailable field."'),
    ("a titles-only search stops counting as a rail failure",
     '"EMPTY_RESPONSE", "RETURNED_TITLES_ONLY", "NOT_ATTEMPTED_BY_POLICY",',
     '"EMPTY_RESPONSE", "NOT_ATTEMPTED_BY_POLICY",'),
    ("an empty owner relay stops counting as a rail failure",
     '"NOTHING_RELAYED")', '")'),
    ("a rail failure stops advancing the ladder",
     '                 "EMPTY_RESPONSE", "RETURNED_TITLES_ONLY", "NOT_ATTEMPTED_BY_POLICY",\n                 "NOTHING_RELAYED")',
     '                 )'),
    ("rungs may be attempted in any order",
     "    if order != sorted(order):", "    if False:"),
    ("the ladder loses a rung",
     '    ("OFFICIAL_TEAM_PAGE_OR_STATUS", "AUTHORITATIVE", "the club\'s own page or status post — often "\n                                                      "the first place a scratch or lineup appears"),',
     ""),
    ("the refusal stops naming which routes remain",
     '        return {"field": field, "status": INCOMPLETE, "routes_untried": untried, "tried": tried,',
     '        return {"field": field, "status": INCOMPLETE, "routes_untried": [], "tried": tried,'),
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
