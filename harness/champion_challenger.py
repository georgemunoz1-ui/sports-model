#!/usr/bin/env python3
"""CHAMPION / CHALLENGER — three arms, one game population, one information cutoff.

OWNER SPECIFICATION 2026-08-23. Every game registers simultaneously:
    BASELINE   the expanding prior
    CHAMPION   the current frozen model
    CHALLENGER the adaptive candidate
"All three must use the same game population and information cutoff."

WHY SIMULTANEITY IS THE WHOLE CONTROL. If the three arms are registered at different moments, or on
different game sets, then any difference between them is a difference in what they were allowed to
see. That is not a hypothetical: the 29-vs-30 game discrepancy earlier today came from cohorts built
at different times on different slates, and 2026-08-18 had to be dropped from a head-to-head
entirely because its two cohorts covered 9 and 15 games. An unpaired comparison reports a slate
difference as a model difference.

SO REGISTRATION IS ALL-OR-NOTHING. A slate registers three complete arms or it registers none. There
is no partial registration, no "the challenger will catch up tomorrow", and no arm that quietly
covers a different set of games.

THE CHALLENGER IS SHADOW-ONLY BY CONSTRUCTION. Its action authority is NONE at registration and this
module has no path that sets it otherwise. Promotion is a separate, gated act that happens elsewhere
and only after the paired-evaluation criteria pass at the required sample size.
"""
from __future__ import annotations

MODULE_ID = "champion_challenger"

import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASELINE = "BASELINE"
CHAMPION = "CHAMPION"
CHALLENGER = "CHALLENGER"
ARMS = (BASELINE, CHAMPION, CHALLENGER)

NONE = "NONE"
GATE_GOVERNED = "GATE_GOVERNED"

# The challenger never carries action authority at registration, whatever else is true of it.
ARM_ACTION_AUTHORITY = {BASELINE: NONE, CHAMPION: GATE_GOVERNED, CHALLENGER: NONE}


def _hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def validate(arms):
    """(ok, failures) for a proposed simultaneous registration.

    arms: {arm_name: {"model_id":..., "information_cutoff_utc":..., "games": {game_id: record}}}"""
    f = []
    missing = [a for a in ARMS if a not in arms]
    if missing:
        f.append(f"registration is all-or-nothing and these arms are absent: {missing}")
        return False, f
    extra = [a for a in arms if a not in ARMS]
    if extra:
        f.append(f"unrecognised arm(s) {extra}: the structure is exactly {list(ARMS)}")
    pops = {a: set((arms[a].get("games") or {})) for a in ARMS}
    ref = pops[BASELINE]
    if not ref:
        f.append("the baseline arm registered no games")
    for a in (CHAMPION, CHALLENGER):
        if pops[a] != ref:
            only_a = sorted(pops[a] - ref)[:4]
            only_b = sorted(ref - pops[a])[:4]
            f.append(f"{a} does not cover the same game population as {BASELINE} "
                     f"({a}-only {only_a}, {BASELINE}-only {only_b}) — an unpaired comparison "
                     f"reports a slate difference as a model difference")
    cutoffs = {a: arms[a].get("information_cutoff_utc") for a in ARMS}
    if any(c is None for c in cutoffs.values()):
        f.append(f"every arm must state its information cutoff: {cutoffs}")
    elif len(set(cutoffs.values())) != 1:
        f.append(f"the arms used different information cutoffs {cutoffs} — any difference between "
                 f"them is then a difference in what they were allowed to see")
    ids = {a: arms[a].get("model_id") for a in ARMS}
    if any(not v for v in ids.values()):
        f.append(f"every arm must carry a model_id: {ids}")
    elif len(set(ids.values())) != len(ARMS):
        f.append(f"two arms share a model_id {ids}: three arms must be three identities")
    for a in ARMS:
        want = ARM_ACTION_AUTHORITY[a]
        got = arms[a].get("action_authority", want)
        if got != want:
            f.append(f"{a} registered with action_authority {got!r}; it must be {want!r}")
    # every game record in every arm must carry a probability
    for a in ARMS:
        for gid, rec in sorted((arms[a].get("games") or {}).items()):
            p = (rec or {}).get("p_home")
            if p is None or not isinstance(p, (int, float)) or isinstance(p, bool) \
                    or not (0.0 < float(p) < 1.0):
                f.append(f"{a}/{gid}: p_home {p!r} is not a probability strictly inside (0,1)")
    return (not f), f


def register(arms, slate_date, registered_utc):
    """Build the simultaneous registration record, or refuse. Never partially registers."""
    ok, f = validate(arms)
    if not ok:
        return None, f
    games = sorted(arms[BASELINE]["games"])
    rows = []
    for gid in games:
        row = {"game_id": gid}
        for a in ARMS:
            row[a] = {"p_home": float(arms[a]["games"][gid]["p_home"]),
                      "model_id": arms[a]["model_id"],
                      "action_authority": ARM_ACTION_AUTHORITY[a]}
        rows.append(row)
    rec = {
        "record_id": f"CCB-{slate_date}",
        "slate_date": slate_date,
        "registered_utc": registered_utc,
        "information_cutoff_utc": arms[BASELINE]["information_cutoff_utc"],
        "arms": {a: {"model_id": arms[a]["model_id"],
                     "action_authority": ARM_ACTION_AUTHORITY[a]} for a in ARMS},
        "n_games": len(games),
        "game_population": games,
        "rows": rows,
        "challenger_status": "SHADOW_ONLY — promotion is a separate gated act and is not performed "
                             "by this module",
    }
    rec["population_hash"] = _hash(games)
    rec["registration_hash"] = _hash(rows)
    return rec, []


def paired_rows(record, arm_a=BASELINE, arm_b=CHALLENGER, outcomes=None):
    """Rows for paired evaluation between two arms, over the registered population only.

    Refuses to emit a row whose outcome is unknown, rather than dropping it silently: a comparison
    that quietly narrows its own population is the failure this whole module exists to prevent."""
    outcomes = outcomes or {}
    rows, unresolved = [], []
    for r in record["rows"]:
        gid = r["game_id"]
        y = outcomes.get(gid)
        if y is None:
            unresolved.append(gid)
            continue
        rows.append({"game_id": gid, "slate_date": record["slate_date"],
                     "p_home_prior": r[arm_a]["p_home"],
                     "p_home_challenger": r[arm_b]["p_home"],
                     "home_win": int(y)})
    return rows, unresolved


def selftest():
    f = []
    CUT = "2026-08-22T22:00:00Z"

    def arm(mid, games, cutoff=CUT, **kw):
        return dict({"model_id": mid, "information_cutoff_utc": cutoff,
                     "games": {g: {"p_home": p} for g, p in games.items()}}, **kw)

    G = {"A@B": 0.53, "C@D": 0.48, "E@F": 0.61}
    good = {BASELINE: arm("mlb.prior.v1", {k: 0.527 for k in G}),
            CHAMPION: arm("ml.v13_1.card.s722n30000", G),
            CHALLENGER: arm("mlb.baseline_offset.v0_1", {k: v + 0.01 for k, v in G.items()})}
    rec, ff = register(good, "2026-08-22", "2026-08-22T21:00:00Z")
    if rec is None:
        f.append(f"a valid three-arm registration was refused: {ff}")
    else:
        if rec["n_games"] != 3 or len(rec["rows"]) != 3:
            f.append("the registration did not cover every game")
        if set(rec["arms"]) != set(ARMS):
            f.append("the registration does not carry all three arms")
        if rec["arms"][CHALLENGER]["action_authority"] != NONE:
            f.append("the CHALLENGER registered with action authority")
        if rec["arms"][BASELINE]["action_authority"] != NONE:
            f.append("the BASELINE registered with action authority")
        if "SHADOW_ONLY" not in rec["challenger_status"]:
            f.append("the challenger is not declared shadow-only")

    # --- ALL OR NOTHING ---------------------------------------------------------------------------
    for drop in ARMS:
        part = {k: v for k, v in good.items() if k != drop}
        r, ff = register(part, "2026-08-22", "x")
        if r is not None:
            f.append(f"a registration missing the {drop} arm succeeded")
        elif not any("all-or-nothing" in x for x in ff):
            f.append(f"a missing {drop} arm was refused without naming the all-or-nothing rule")

    # --- SAME GAME POPULATION ---------------------------------------------------------------------
    short = dict(good)
    short[CHALLENGER] = arm("mlb.baseline_offset.v0_1", {"A@B": 0.54, "C@D": 0.49})
    r, ff = register(short, "2026-08-22", "x")
    if r is not None:
        f.append("the challenger was registered on FEWER games than the baseline")
    elif not any("slate difference as a model difference" in x for x in ff):
        f.append("a population mismatch was refused without naming why it matters")
    wide = dict(good)
    wide[CHAMPION] = arm("ml.v13_1.card.s722n30000", dict(G, **{"G@H": 0.50}))
    if register(wide, "2026-08-22", "x")[0] is not None:
        f.append("the champion was registered on MORE games than the baseline")
    # the 2026-08-18 shape exactly: 9 games against 15
    nine = {f"g{i}@h{i}": 0.5 for i in range(9)}
    fifteen = {f"g{i}@h{i}": 0.5 for i in range(15)}
    shape = {BASELINE: arm("b", nine), CHAMPION: arm("c", fifteen), CHALLENGER: arm("d", fifteen)}
    if register(shape, "2026-08-18", "x")[0] is not None:
        f.append("the real 2026-08-18 shape (9 games against 15) was accepted")

    # --- SAME INFORMATION CUTOFF -------------------------------------------------------------------
    late = dict(good)
    late[CHALLENGER] = arm("mlb.baseline_offset.v0_1", {k: v + 0.01 for k, v in G.items()},
                           cutoff="2026-08-22T23:30:00Z")
    r, ff = register(late, "2026-08-22", "x")
    if r is not None:
        f.append("an arm with a LATER information cutoff was registered alongside the others")
    elif not any("allowed to see" in x for x in ff):
        f.append("a cutoff mismatch was refused without naming the reason")
    nocut = dict(good)
    nocut[CHAMPION] = {"model_id": "c", "games": {g: {"p_home": p} for g, p in G.items()}}
    if register(nocut, "2026-08-22", "x")[0] is not None:
        f.append("an arm with NO stated information cutoff was accepted")
    # ISOLATION: when EVERY arm omits the cutoff they agree with each other, so the mismatch check
    # cannot fire and only the presence check can refuse it.
    allnone = {a: {"model_id": f"m{i}", "games": {g: {"p_home": 0.5} for g in G}}
               for i, a in enumerate(ARMS)}
    r, ff = register(allnone, "2026-08-22", "x")
    if r is not None:
        f.append("a registration where NO arm stated an information cutoff was accepted — only the "
                 "presence check can catch this")
    # ISOLATION: three EMPTY arms have identical (empty) populations, so the matching check cannot
    # fire and only the empty-baseline check can refuse it.
    allempty = {a: arm(f"m{i}", {}) for i, a in enumerate(ARMS)}
    r, ff = register(allempty, "2026-08-22", "x")
    if r is not None:
        f.append("a registration of three EMPTY arms was accepted — only the empty-baseline check "
                 "can catch this")

    # --- THREE ARMS ARE THREE IDENTITIES ------------------------------------------------------------
    same = dict(good)
    same[CHALLENGER] = arm("ml.v13_1.card.s722n30000", {k: v + 0.01 for k, v in G.items()})
    if register(same, "2026-08-22", "x")[0] is not None:
        f.append("the challenger reused the champion's model_id")
    noid = dict(good)
    noid[BASELINE] = {"information_cutoff_utc": CUT, "model_id": "",
                      "games": {g: {"p_home": 0.5} for g in G}}
    if register(noid, "2026-08-22", "x")[0] is not None:
        f.append("an arm with no model_id was accepted")

    # --- THE CHALLENGER CANNOT REGISTER WITH AUTHORITY, BY ANY ROUTE ---------------------------------
    forced = dict(good)
    forced[CHALLENGER] = arm("mlb.baseline_offset.v0_1", {k: v + 0.01 for k, v in G.items()},
                             action_authority=GATE_GOVERNED)
    r, ff = register(forced, "2026-08-22", "x")
    if r is not None:
        f.append("a challenger explicitly asking for action authority was registered")
    elif not any("action_authority" in x for x in ff):
        f.append("the refusal did not name the action-authority violation")
    for a in ARMS:
        if a == CHAMPION:
            continue
        if ARM_ACTION_AUTHORITY[a] != NONE:
            f.append(f"{a} carries action authority in the arm table")

    # --- probabilities --------------------------------------------------------------------------------
    for bad in (0.0, 1.0, -0.1, 1.5, None, "0.5", True):
        b = dict(good)
        b[CHAMPION] = arm("ml.v13_1.card.s722n30000", dict(G, **{"A@B": bad}))
        if register(b, "2026-08-22", "x")[0] is not None:
            f.append(f"an arm registered p_home={bad!r}")

    # --- PAIRED ROWS ---------------------------------------------------------------------------------
    rows, unres = paired_rows(rec, BASELINE, CHALLENGER,
                              outcomes={"A@B": 1, "C@D": 0, "E@F": 1})
    if len(rows) != 3 or unres:
        f.append(f"paired rows over a fully settled slate gave {len(rows)} rows, {unres} unresolved")
    if rows and (rows[0]["p_home_prior"] != 0.527 or abs(rows[0]["p_home_challenger"] - 0.54) > 1e-9):
        f.append(f"paired rows drew from the wrong arms: {rows[0]}")
    # an unsettled game is REPORTED, never silently dropped
    rows, unres = paired_rows(rec, BASELINE, CHALLENGER, outcomes={"A@B": 1})
    if len(rows) != 1 or unres != ["C@D", "E@F"]:
        f.append(f"unresolved games were not reported: {len(rows)} rows, unresolved {unres}")
    # champion-vs-challenger is available too
    rows, _ = paired_rows(rec, CHAMPION, CHALLENGER, outcomes={"A@B": 1, "C@D": 0, "E@F": 1})
    if rows and abs(rows[0]["p_home_prior"] - 0.53) > 1e-9:
        f.append("a champion-vs-challenger pairing did not draw the champion probability")

    # --- hashes bind the population and the values ------------------------------------------------------
    rec2, _ = register(good, "2026-08-22", "2026-08-22T21:00:00Z")
    if rec2["registration_hash"] != rec["registration_hash"]:
        f.append("two identical registrations produced different hashes")
    alt = dict(good)
    alt[CHALLENGER] = arm("mlb.baseline_offset.v0_1", {k: v + 0.02 for k, v in G.items()})
    rec3, _ = register(alt, "2026-08-22", "2026-08-22T21:00:00Z")
    if rec3["registration_hash"] == rec["registration_hash"]:
        f.append("the registration hash does not change when a probability changes")
    if rec3["population_hash"] != rec["population_hash"]:
        f.append("the population hash changed when only a probability changed")

    print("champion_challenger selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("registration succeeds with an arm missing",
     "    missing = [a for a in ARMS if a not in arms]", "    missing = []"),
    ("the game populations need not match",
     "        if pops[a] != ref:", "        if False:"),
    ("population matching becomes one-directional, so a short challenger passes",
     "        if pops[a] != ref:", "        if not pops[a] >= ref:"),
    ("the arms may use different information cutoffs",
     "    elif len(set(cutoffs.values())) != 1:", "    elif False:"),
    ("an arm may omit its information cutoff",
     "    if any(c is None for c in cutoffs.values()):", "    if False:"),
    ("two arms may share one model identity",
     "    elif len(set(ids.values())) != len(ARMS):", "    elif False:"),
    ("the challenger may register with action authority",
     "        if got != want:", "        if False:"),
    ("the challenger is given action authority in the arm table",
     "ARM_ACTION_AUTHORITY = {BASELINE: NONE, CHAMPION: GATE_GOVERNED, CHALLENGER: NONE}",
     "ARM_ACTION_AUTHORITY = {BASELINE: NONE, CHAMPION: GATE_GOVERNED, CHALLENGER: GATE_GOVERNED}"),
    ("a degenerate probability is accepted",
     "            if p is None or not isinstance(p, (int, float)) or isinstance(p, bool) \\\n                    or not (0.0 < float(p) < 1.0):",
     "            if False:"),
    ("register partially writes instead of refusing",
     "    if not ok:\n        return None, f", "    if False:\n        return None, f"),
    ("unresolved games are silently dropped instead of reported",
     "        if y is None:\n            unresolved.append(gid)\n            continue",
     "        if y is None:\n            continue"),
    ("the challenger stops being declared shadow-only",
     '        "challenger_status": "SHADOW_ONLY', '        "challenger_status": "READY'),
    ("the registration hash ignores the probabilities",
     '    rec["registration_hash"] = _hash(rows)', '    rec["registration_hash"] = _hash(games)'),
    ("an empty baseline arm is accepted", "    if not ref:", "    if False:"),
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
