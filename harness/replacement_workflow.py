"""Section 5 and 6: a material change generates a replacement, it does not end the game.

THE OLD BEHAVIOUR THIS REPLACES. On 2026-08-24 two games had an official TBD at lock and a named
starter afterwards. Both were blocked. That was defensible under the old contract and it is wrong
under v1.0: the correct response to new information is a NEW FORECAST under a preregistered
identity, not the absence of a decision.

WHAT MAKES IT SAFE. The original is immutable, the replacement is a separate identity with its own
hashes and generation time, both are graded in their registered roles, and the replacement must be
remotely anchored BEFORE actual start or it does not qualify. That last condition is what stops
"replacement forecast" from becoming a licence to revise a number after watching the market.

AND WHY FALLBACKS MUST BE PREREGISTERED. A fallback invented after seeing the market is not a
fallback, it is a discretionary adjustment wearing a model's name. The registry is frozen before the
slate and every mode has a distinct identity, so the report can say which one ran.
"""

MODULE_ID = "replacement_workflow"

import hashlib
import json
import sys

MATERIAL_CHANGES = (
    "CONFIRMED_STARTER_REPLACING_OFFICIAL_TBD",
    "PITCHER_SCRATCH",
    "STARTING_LINEUP_CHANGE",
    "PLAYER_RULED_IN_OR_OUT",
    "MINUTES_RESTRICTION",
    "VENUE_CHANGE",
    "SIGNIFICANT_WEATHER_CHANGE",
    "GAME_TIME_CHANGE",
)

#: preregistered fallback modes, frozen before the slate. Distinct identities, by construction.
FALLBACK_REGISTRY = {
    "mlb.fallback.FULL_STARTER": "both probable starters confirmed; the normal mode",
    "mlb.fallback.ONE_STARTER_PARTIAL": "one side's starter confirmed, the other unknown",
    "mlb.fallback.OFFICIAL_TBD": "the league itself publishes TBD; no starter identity is assumed",
    "mlb.replacement.CONFIRMED_LINEUP": "a confirmed starter or lineup arrives after lock",
    "wnba.fallback.FULL_AVAILABILITY": "all rostered players verified available",
    "wnba.fallback.PLAYER_OUT_ADJUSTMENT": "a named player is confirmed out",
    "wnba.fallback.UNCERTAIN_AVAILABILITY_CONSERVATIVE": "availability unverified; the conservative "
                                                         "mode, which must not be more confident "
                                                         "than the verified one",
}

REPLACED = "REPLACEMENT_FORECAST_GENERATED"
TOO_LATE = "MATERIAL_CHANGE_TOO_LATE_TO_ANCHOR"
UNREGISTERED = "REFUSED_UNREGISTERED_REPLACEMENT_IDENTITY"
NOT_MATERIAL = "CHANGE_NOT_ON_THE_PREREGISTERED_MATERIAL_LIST"
OVERWRITE = "REFUSED_SILENT_OVERWRITE_OF_ORIGINAL_FORECAST"
IMPROVISED = "REFUSED_IMPROVISED_FALLBACK_NOT_IN_REGISTRY"


def _hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def is_material(change):
    return str(change) in MATERIAL_CHANGES


def select_fallback(identity):
    """A fallback must come from the frozen registry. Improvisation is refused by name."""
    if identity in FALLBACK_REGISTRY:
        return {"identity": identity, "description": FALLBACK_REGISTRY[identity],
                "preregistered": True}, None
    return None, (f"{IMPROVISED}: {identity!r} is not in the frozen registry. A mode invented after "
                  f"seeing the market is a discretionary adjustment wearing a model's name.")


def replace(original, change, changed_input, source, replacement_identity, new_probability,
            generated_at_utc, game_start_utc, anchored_at_utc=None):
    """Generate a replacement forecast. The original is returned untouched, always."""
    if not is_material(change):
        return None, f"{NOT_MATERIAL}: {change!r}"
    reg, err = select_fallback(replacement_identity)
    if err:
        return None, f"{UNREGISTERED}: {err}"
    if not (changed_input and source):
        return None, "REFUSED_CHANGE_WITHOUT_A_RECORDED_INPUT_AND_SOURCE"
    if anchored_at_utc is None or str(anchored_at_utc) >= str(game_start_utc):
        return None, (f"{TOO_LATE}: a replacement must be remotely anchored BEFORE actual start "
                      f"(anchor={anchored_at_utc}, start={game_start_utc}). Without that, "
                      f"'replacement forecast' becomes a licence to revise a number late.")
    inp = {"change": change, "changed_input": changed_input, "source": source}
    rep = {
        "role": "REPLACEMENT",
        "identity": replacement_identity,
        "supersedes_identity": original.get("identity"),
        "original_forecast_sha256": _hash(original),
        "material_change": change,
        "changed_input": changed_input,
        "source": source,
        "p_home": new_probability,
        "input_sha256": _hash(inp),
        "forecast_sha256": _hash({"identity": replacement_identity, "p_home": new_probability,
                                  "input": inp}),
        "generated_at_utc": generated_at_utc,
        "anchored_at_utc": anchored_at_utc,
        "anchor_grade": "REMOTE_OBSERVED",
        "graded_separately_from_original": True,
    }
    if rep["forecast_sha256"] == rep["original_forecast_sha256"]:
        return None, f"{OVERWRITE}: the replacement hashes identically to the original"
    return {"status": REPLACED, "original": original, "replacement": rep,
            "use_in_overlay": replacement_identity,
            "note": "the original is unchanged and is graded in its registered role. The newest "
                    "valid PREGAME identity is what the overlay uses."}, None


def newest_valid_pregame(identities):
    """identities: [{"identity","anchored_at_utc","game_start_utc"}]. Newest anchored BEFORE start."""
    ok = [i for i in (identities or [])
          if i.get("anchored_at_utc") and str(i["anchored_at_utc"]) < str(i.get("game_start_utc"))]
    if not ok:
        return None
    return max(ok, key=lambda i: str(i["anchored_at_utc"]))


# =================================================================================================
# COUPLED RESELECTION. Discovered 2026-08-25: three replacement forecasts were generated, anchored
# and re-screened — but the overlay kept screening the PRE-replacement priced side. When the
# replacement probability crossed 50%, "the model's side" changed, and screening the abandoned
# side's price reported PASS_NEGATIVE_EV for a game whose active side had positive raw EV
# (BOS@MIA: BOS −14.96 shown while MIA +130 was +16.25). Probability, chosen side, that side's
# price, the EV and the disposition are ONE update, never five.
SIDE_RETAINED = "SIDE_RETENTION_AFTER_CROSSOVER"
SIDE_NOT_ARGMAX = "SIDE_NOT_ARGMAX"
PRICE_SIDE_MISMATCH = "PRICE_SIDE_MISMATCH"
EV_NOT_RECOMPUTED = "EV_NOT_RECOMPUTED_FULL_PRECISION"
DISPOSITION_STALE = "DISPOSITION_STALE"
EV_TOLERANCE = 0.005   # half a cent per $100: an EV recomputed from a ROUNDED probability fails


def _raw_ev(p, american):
    b = float(american) if float(american) > 0 else 100.0 * 100.0 / -float(american)
    return p * b - (1.0 - p) * 100.0


def side_reselection_gate(original_p_home, replacement_p_home, home, away, row):
    """row: {"side","price_side","price","ev","disposition"[, "conservative_ev"]}. Returns
    (ok, problems). The active side is the argmax of the NEWEST valid pregame probability;
    the price, EV and disposition must all belong to that side, at full precision."""
    problems = []
    model_side = home if replacement_p_home > 0.5 else away
    crossed = (float(original_p_home) > 0.5) != (float(replacement_p_home) > 0.5)
    if row.get("side") != model_side:
        problems.append({"code": SIDE_RETAINED if crossed else SIDE_NOT_ARGMAX,
                         "expected_side": model_side, "row_side": row.get("side")})
        return False, problems
    if row.get("price_side") != row.get("side"):
        problems.append({"code": PRICE_SIDE_MISMATCH,
                         "side": row.get("side"), "price_side": row.get("price_side")})
        return False, problems
    p_side = replacement_p_home if row.get("side") == home else 1.0 - replacement_p_home
    want = _raw_ev(p_side, row.get("price"))
    if abs(want - float(row.get("ev"))) > EV_TOLERANCE:
        problems.append({"code": EV_NOT_RECOMPUTED, "expected_ev": round(want, 4),
                         "row_ev": row.get("ev")})
        return False, problems
    cons = row.get("conservative_ev")
    if cons is None:
        want_disp = "PENDING_UNCERTAINTY" if want > 0 else "PASS_NEGATIVE_EV"
    else:
        want_disp = ("BET" if float(cons) > 0 else "PASS_NEGATIVE_EV") if want > 0 else "PASS_NEGATIVE_EV"
    if row.get("disposition") != want_disp:
        problems.append({"code": DISPOSITION_STALE, "expected": want_disp,
                         "row_disposition": row.get("disposition")})
    return (not problems), problems


# =================================================================================================
def selftest():
    f = []
    ORIG = {"identity": "mlb.winner.CHAMPION_V13", "game": "mlb:TEX@CWS", "p_home": 0.5340}
    ORIG_SNAPSHOT = json.dumps(ORIG, sort_keys=True)

    if len(MATERIAL_CHANGES) != 8:
        f.append("section 5 names eight material change kinds")
    for c in ("CONFIRMED_STARTER_REPLACING_OFFICIAL_TBD", "PITCHER_SCRATCH",
              "STARTING_LINEUP_CHANGE", "PLAYER_RULED_IN_OR_OUT", "MINUTES_RESTRICTION",
              "VENUE_CHANGE", "SIGNIFICANT_WEATHER_CHANGE", "GAME_TIME_CHANGE"):
        if not is_material(c):
            f.append(f"{c} must be material")
    if is_material("A_BEAT_WRITER_HAS_A_FEELING"):
        f.append("an unlisted change must not be material")

    # THE CORE CASE: the exact 8/24 situation now produces a replacement, not a block
    got, err = replace(ORIG, "CONFIRMED_STARTER_REPLACING_OFFICIAL_TBD",
                       "CWS starter: TBD -> Jose Urquidy", "OFFICIAL_TEAM_PAGE_OR_STATUS",
                       "mlb.replacement.CONFIRMED_LINEUP", 0.5121,
                       "2026-08-24T23:00:00Z", "2026-08-24T23:40:00Z", "2026-08-24T23:10:00Z")
    if err or not got:
        f.append(f"a confirmed starter after an official TBD must generate a replacement: {err}")
    else:
        if got["status"] != REPLACED:
            f.append("the status must say a replacement was generated")
        if got["original"] != ORIG or json.dumps(ORIG, sort_keys=True) != ORIG_SNAPSHOT:
            f.append("the original forecast must be returned byte-identical and unmutated")
        rep = got["replacement"]
        for k in ("identity", "input_sha256", "forecast_sha256", "generated_at_utc",
                  "anchored_at_utc", "original_forecast_sha256"):
            if not rep.get(k):
                f.append(f"the replacement must carry {k}")
        if rep["identity"] == ORIG["identity"]:
            f.append("the replacement must have a DISTINCT identity")
        if rep["forecast_sha256"] == rep["original_forecast_sha256"]:
            f.append("the replacement must hash differently from the original")
        if not rep["graded_separately_from_original"]:
            f.append("original and replacement are graded separately")
        if got["use_in_overlay"] != "mlb.replacement.CONFIRMED_LINEUP":
            f.append("the overlay must use the newest valid pregame identity")

    # an unregistered identity is refused — no improvisation
    _, e2 = replace(ORIG, "PITCHER_SCRATCH", "x", "y", "mlb.replacement.SOMETHING_I_JUST_MADE_UP",
                    0.5, "2026-08-24T23:00:00Z", "2026-08-24T23:40:00Z", "2026-08-24T23:10:00Z")
    if not e2 or UNREGISTERED not in e2:
        f.append("an unregistered replacement identity must be refused")
    _, e2b = select_fallback("mlb.fallback.INVENTED_AFTER_SEEING_THE_MARKET")
    if not e2b or IMPROVISED not in e2b:
        f.append("an improvised fallback must be refused by name")
    for ident in ("mlb.fallback.FULL_STARTER", "mlb.fallback.ONE_STARTER_PARTIAL",
                  "mlb.fallback.OFFICIAL_TBD", "wnba.fallback.FULL_AVAILABILITY",
                  "wnba.fallback.PLAYER_OUT_ADJUSTMENT",
                  "wnba.fallback.UNCERTAIN_AVAILABILITY_CONSERVATIVE"):
        got_fb, e = select_fallback(ident)
        if e or not got_fb["preregistered"]:
            f.append(f"{ident} must be in the frozen registry")
    if len(set(FALLBACK_REGISTRY)) != len(FALLBACK_REGISTRY):
        f.append("fallback identities must be distinct")

    # a change with no recorded input or source is refused
    for bad in (("", "src"), ("inp", "")):
        _, e3 = replace(ORIG, "PITCHER_SCRATCH", bad[0], bad[1],
                        "mlb.replacement.CONFIRMED_LINEUP", 0.5,
                        "2026-08-24T23:00:00Z", "2026-08-24T23:40:00Z", "2026-08-24T23:10:00Z")
        if not e3:
            f.append(f"a change without input+source must be refused: {bad}")

    # TOO LATE: not anchored, or anchored at/after start
    for anchor in (None, "2026-08-24T23:40:00Z", "2026-08-25T00:10:00Z"):
        _, e4 = replace(ORIG, "PITCHER_SCRATCH", "inp", "src",
                        "mlb.replacement.CONFIRMED_LINEUP", 0.5,
                        "2026-08-24T23:00:00Z", "2026-08-24T23:40:00Z", anchor)
        if not e4 or TOO_LATE not in e4:
            f.append(f"an unanchored or late replacement must be refused (anchor={anchor})")

    # newest valid pregame identity
    ids = [{"identity": "A", "anchored_at_utc": "2026-08-24T10:00:00Z",
            "game_start_utc": "2026-08-24T23:40:00Z"},
           {"identity": "B", "anchored_at_utc": "2026-08-24T23:10:00Z",
            "game_start_utc": "2026-08-24T23:40:00Z"},
           {"identity": "C_TOO_LATE", "anchored_at_utc": "2026-08-25T00:00:00Z",
            "game_start_utc": "2026-08-24T23:40:00Z"}]
    n = newest_valid_pregame(ids)
    if not n or n["identity"] != "B":
        f.append(f"the newest PREGAME-anchored identity must win, got {n}")
    if newest_valid_pregame([ids[2]]) is not None:
        f.append("a post-start anchor is not a valid pregame identity at any recency")
    if newest_valid_pregame([]) is not None:
        f.append("no identities means none is valid")

    # coupled reselection — fixtures are the real 2026-08-25 cases
    P0_MIA, P1_MIA = 0.4753, 0.5054333333333333
    good = {"side": "MIA", "price_side": "MIA", "price": 130, "ev": 16.2497,
            "disposition": "PENDING_UNCERTAINTY"}
    ok, pr = side_reselection_gate(P0_MIA, P1_MIA, "MIA", "BOS", good)
    if not ok:
        f.append(f"the corrected BOS@MIA row must pass, got {pr}")
    retained = {"side": "BOS", "price_side": "BOS", "price": -139, "ev": -14.96,
                "disposition": "PASS_NEGATIVE_EV"}
    ok, pr = side_reselection_gate(P0_MIA, P1_MIA, "MIA", "BOS", retained)
    if ok or pr[0]["code"] != SIDE_RETAINED:
        f.append(f"retaining the abandoned side after a 50% crossing must refuse with "
                 f"{SIDE_RETAINED}, got {pr}")
    ok, pr = side_reselection_gate(0.5477, 0.5453333333333333, "WSH", "COL",
                                   {"side": "COL", "price_side": "COL", "price": 120,
                                    "ev": 0.0, "disposition": "PASS_NEGATIVE_EV"})
    if ok or pr[0]["code"] != SIDE_NOT_ARGMAX:
        f.append(f"a wrong side with no crossing is {SIDE_NOT_ARGMAX}, got {pr}")
    ok, pr = side_reselection_gate(P0_MIA, P1_MIA, "MIA", "BOS",
                                   dict(good, price_side="BOS"))
    if ok or pr[0]["code"] != PRICE_SIDE_MISMATCH:
        f.append(f"a price belonging to the other side must refuse, got {pr}")
    ok, pr = side_reselection_gate(P0_MIA, P1_MIA, "MIA", "BOS", dict(good, ev=16.2420))
    if ok or pr[0]["code"] != EV_NOT_RECOMPUTED:
        f.append(f"an EV from the ROUNDED probability (16.2420 vs 16.2497) must refuse, got {pr}")
    ok, pr = side_reselection_gate(P0_MIA, P1_MIA, "MIA", "BOS",
                                   dict(good, disposition="PASS_NEGATIVE_EV"))
    if ok or pr[0]["code"] != DISPOSITION_STALE:
        f.append(f"positive raw EV with a PASS disposition must refuse, got {pr}")
    ok, pr = side_reselection_gate(0.5090666666666667, 0.4861333333333333, "STL", "BAL",
                                   {"side": "BAL", "price_side": "BAL", "price": 116,
                                    "ev": 10.9952, "disposition": "PENDING_UNCERTAINTY"})
    if not ok:
        f.append(f"the corrected BAL@STL row must pass, got {pr}")
    ok, pr = side_reselection_gate(0.5477, 0.5453333333333333, "WSH", "COL",
                                   {"side": "WSH", "price_side": "WSH", "price": -147,
                                    "ev": -8.3692, "disposition": "PASS_NEGATIVE_EV"})
    if not ok:
        f.append(f"the unchanged COL@WSH row must pass, got {pr}")
    ok, pr = side_reselection_gate(P0_MIA, P1_MIA, "MIA", "BOS",
                                   dict(good, conservative_ev=1.0))
    if ok or pr[0]["code"] != DISPOSITION_STALE:
        f.append("once conservative EV exists and is positive, PENDING_UNCERTAINTY is stale")

    print("replacement_workflow selftest:", "OK" if not f else "FAIL")
    for x in f:
        print("   -", x)
    return not f


MUTANTS = [
    ("a replacement may use an unregistered identity",
     "    reg, err = select_fallback(replacement_identity)\n    if err:", "    if False:"),
    ("an improvised fallback is accepted",
     "    if identity in FALLBACK_REGISTRY:", "    if True:"),
    ("a replacement anchored after first pitch is accepted",
     '    if anchored_at_utc is None or str(anchored_at_utc) >= str(game_start_utc):', "    if False:"),
    ("an unanchored replacement is accepted",
     "    if anchored_at_utc is None or", "    if False and"),
    ("the replacement reuses the original identity",
     '        "identity": replacement_identity,\n        "supersedes_identity": original.get("identity"),',
     '        "identity": original.get("identity"),\n        "supersedes_identity": original.get("identity"),'),
    ("the original forecast is mutated in place",
     "    return {\"status\": REPLACED, \"original\": original,",
     "    original.update({'p_home': new_probability});     return {\"status\": REPLACED, \"original\": original,"),
    ("a change with no recorded source is accepted",
     "    if not (changed_input and source):", "    if False:"),
    ("an unlisted change is treated as material",
     "    return str(change) in MATERIAL_CHANGES", "    return True"),
    ("a material change kind is dropped from the list",
     '    "MINUTES_RESTRICTION",\n', ""),
    ("a fallback mode is dropped from the registry",
     '    "wnba.fallback.UNCERTAIN_AVAILABILITY_CONSERVATIVE": "availability unverified; the conservative "\n                                                         "mode, which must not be more confident "\n                                                         "than the verified one",\n',
     ""),
    ("a post-start anchor counts as a valid pregame identity",
     '          if i.get("anchored_at_utc") and str(i["anchored_at_utc"]) < str(i.get("game_start_utc"))]',
     '          if i.get("anchored_at_utc")]'),
    ("original and replacement stop being graded separately",
     '        "graded_separately_from_original": True,',
     '        "graded_separately_from_original": False,'),
    ("the active side is chosen from the ORIGINAL probability",
     "    model_side = home if replacement_p_home > 0.5 else away",
     "    model_side = home if float(original_p_home) > 0.5 else away"),
    ("the crossing test inverts",
     '    crossed = (float(original_p_home) > 0.5) != (float(replacement_p_home) > 0.5)',
     '    crossed = (float(original_p_home) > 0.5) == (float(replacement_p_home) > 0.5)'),
    ("a price belonging to the other side is accepted",
     '    if row.get("price_side") != row.get("side"):',
     "    if False:"),
    ("the EV tolerance widens until rounded-probability EVs pass",
     "EV_TOLERANCE = 0.005",
     "EV_TOLERANCE = 0.05"),
    ("EV is recomputed from the abandoned side's probability",
     '    p_side = replacement_p_home if row.get("side") == home else 1.0 - replacement_p_home',
     '    p_side = float(original_p_home) if row.get("side") == home else 1.0 - float(original_p_home)'),
    ("a stale disposition is accepted",
     '    if row.get("disposition") != want_disp:',
     "    if False:"),
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
