#!/usr/bin/env python3
"""KEYED SIMULATION SEEDS — one game's simulation cannot move because another game changed.

OWNER SPECIFICATION (development program item 4, restated in the three-arm requirement as
"keyed simulation seeds"):

    seed = hash(model_id, slate_date, game_id, simulation_version)

WHY THE GLOBAL SEQUENTIAL RNG IS A DEFECT. V13 draws from one global stream in slate order. That
makes every game's simulation depend on every earlier game's draw count, so ADDING A GAME to a slate,
REORDERING it, or changing one game's inning count shifts the random numbers for every game after
it. The measured consequence is already recorded in this repository: a v1-to-v2 delta is not a
starter effect but "starter information PLUS sequential-RNG coupling noise", and the decision card
refuses to call such a delta causal without a keyed-seed reference precisely because of this.

WITH A KEYED SEED, THE COUPLING DISAPPEARS. Each game draws from its own stream, so the difference
between two arms on one game is attributable to the two arms and nothing else. That is what makes a
paired comparison mean what it says.

THE KEY IS THE FOUR FIELDS AND NOTHING ELSE. Not the slate size, not the game's position, not the
wall clock. Two arms that differ in model_id get different streams — which is correct, because they
are different models — while the SAME arm re-run on the same game gets the identical stream, which
is what makes a rebuild reproducible.
"""
from __future__ import annotations

MODULE_ID = "keyed_seed"

import hashlib
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SEED_BITS = 63          # positive, fits a numpy SeedSequence and a Python int seed
KEY_FIELDS = ("model_id", "slate_date", "game_id", "simulation_version")


def seed_for(model_id, slate_date, game_id, simulation_version):
    """Deterministic per-game seed. Every field is required; a missing one is refused, not defaulted.

    Defaulting a missing key field would silently collapse distinct games onto one stream, which is
    the exact coupling this module exists to remove."""
    vals = {"model_id": model_id, "slate_date": slate_date, "game_id": game_id,
            "simulation_version": simulation_version}
    missing = [k for k in KEY_FIELDS if vals.get(k) in (None, "")]
    if missing:
        raise ValueError(f"a keyed seed requires every field; missing {missing}. Defaulting one "
                         f"would collapse distinct games onto a shared stream.")
    payload = "\x1f".join(str(vals[k]) for k in KEY_FIELDS)
    h = hashlib.sha256(payload.encode()).digest()
    return int.from_bytes(h[:8], "big") >> (64 - SEED_BITS)


def seed_manifest(model_id, slate_date, game_ids, simulation_version):
    """Every game's seed for one arm, plus a hash over the whole set so it is bindable."""
    # NOTE: the comprehension deliberately preserves INPUT order. The hash below is what makes the
    # manifest order-independent, and an earlier version sorted in both places — which made the
    # hash's own sort redundant and unprovable.
    seeds = {g: seed_for(model_id, slate_date, g, simulation_version) for g in game_ids}
    digest = hashlib.sha256(
        "\x1e".join(f"{g}={s}" for g, s in sorted(seeds.items())).encode()).hexdigest()
    return {"model_id": model_id, "slate_date": slate_date,
            "simulation_version": simulation_version,
            "n_games": len(seeds), "seeds": seeds, "seed_manifest_sha256": digest,
            "policy": "keyed_per_game: sha256(model_id, slate_date, game_id, simulation_version)"}


def independence_from_seeds(seeds, manifest_sha=None):
    """The independence verdict over an explicit {game_id: seed} mapping.

    Extracted so the verdict can be exercised against a FORCED collision. sha256 will not collide in
    a fixture, so a report built only from real seeds can never demonstrate that the check works."""
    vals = list(seeds.values())
    collisions = len(vals) - len(set(vals))
    return {"n_games": len(seeds), "distinct_seeds": len(set(vals)),
            "collisions": collisions,
            "independent": collisions == 0,
            "seed_manifest_sha256": manifest_sha,
            "note": ("each game draws from its own stream, so adding, removing or reordering a game "
                     "cannot move any other game's simulation")}


def independence_report(model_id, slate_date, game_ids, simulation_version):
    """Positive evidence that no two games in the slate share a stream."""
    m = seed_manifest(model_id, slate_date, game_ids, simulation_version)
    return independence_from_seeds(m["seeds"], m["seed_manifest_sha256"])


def selftest():
    f = []
    M, D, V = "ml.v13_1.hfa1005.card.s722n30000", "2026-08-23", "v13_1"
    s1 = seed_for(M, D, "STL@PHI", V)

    # --- DETERMINISM ---------------------------------------------------------------------------
    if seed_for(M, D, "STL@PHI", V) != s1:
        f.append("the same key produced two different seeds")
    if not (0 <= s1 < 2 ** SEED_BITS):
        f.append(f"seed {s1} is outside the declared {SEED_BITS}-bit positive range")

    # --- EVERY KEY FIELD MOVES THE SEED ------------------------------------------------------------
    if seed_for(M, D, "TOR@NYY", V) == s1:
        f.append("two different GAMES share a seed")
    if seed_for(M, "2026-08-24", "STL@PHI", V) == s1:
        f.append("two different SLATE DATES share a seed")
    if seed_for("other.model", D, "STL@PHI", V) == s1:
        f.append("two different MODELS share a seed — arms would draw the same stream")
    if seed_for(M, D, "STL@PHI", "v13_2") == s1:
        f.append("two different SIMULATION VERSIONS share a seed")

    # --- INDEPENDENCE FROM SLATE COMPOSITION: THE WHOLE POINT ---------------------------------------
    slate_a = ["STL@PHI", "TOR@NYY", "TB@BAL"]
    slate_b = ["TB@BAL", "TOR@NYY", "STL@PHI"]                 # reordered
    slate_c = slate_a + ["EXTRA@GAME"]                          # a game added
    slate_d = ["TOR@NYY", "TB@BAL"]                             # a game removed
    base = {g: seed_for(M, D, g, V) for g in slate_a}
    for label, sl in (("reordered", slate_b), ("game added", slate_c), ("game removed", slate_d)):
        for g in sl:
            if g in base and seed_for(M, D, g, V) != base[g]:
                f.append(f"{label}: game {g} changed its seed — the streams are still coupled to "
                         f"slate composition, which is the defect this module removes")

    # --- MISSING FIELDS ARE REFUSED, NEVER DEFAULTED -------------------------------------------------
    for kw in ({"model_id": None}, {"slate_date": None}, {"game_id": None},
               {"simulation_version": None}, {"game_id": ""}, {"model_id": ""}):
        args = {"model_id": M, "slate_date": D, "game_id": "A@B", "simulation_version": V}
        args.update(kw)
        try:
            seed_for(**args)
            f.append(f"a seed was produced with {kw} — defaulting collapses games onto one stream")
        except ValueError as e:
            if "collapse" not in str(e):
                f.append("the refusal does not say why defaulting is dangerous")

    # --- MANIFEST ------------------------------------------------------------------------------------
    m = seed_manifest(M, D, slate_a, V)
    if m["n_games"] != 3 or len(m["seeds"]) != 3:
        f.append("the manifest lost a game")
    if seed_manifest(M, D, slate_b, V)["seed_manifest_sha256"] != m["seed_manifest_sha256"]:
        f.append("the manifest hash depends on slate ORDER; it must depend only on the set")
    if seed_manifest(M, D, slate_c, V)["seed_manifest_sha256"] == m["seed_manifest_sha256"]:
        f.append("the manifest hash did not change when a game was added")
    if seed_manifest("other", D, slate_a, V)["seed_manifest_sha256"] == m["seed_manifest_sha256"]:
        f.append("the manifest hash did not change with the model")

    # --- INDEPENDENCE REPORT --------------------------------------------------------------------------
    r = independence_report(M, D, [f"G{i}@H{i}" for i in range(200)], V)
    if not r["independent"] or r["collisions"] != 0:
        f.append(f"seed collisions across 200 games: {r['collisions']}")
    if r["distinct_seeds"] != 200:
        f.append("the independence report miscounted distinct streams")
    if "cannot move any other game" not in r["note"]:
        f.append("the independence report does not state the property it establishes")
    # a duplicated game id is NOT a collision claim — the set collapses, and that must be visible
    r2 = independence_report(M, D, ["A@B", "A@B", "C@D"], V)
    if r2["n_games"] != 2:
        f.append("a duplicated game id was counted twice in the manifest")
    # A FORCED COLLISION. sha256 will not collide in a fixture, so the verdict is exercised against
    # an explicit mapping — otherwise "independent: True" is never distinguishable from a hardcoded
    # True.
    col = independence_from_seeds({"A@B": 7, "C@D": 7, "E@F": 9})
    if col["independent"] or col["collisions"] != 1:
        f.append(f"two games sharing a seed were reported independent: {col}")
    if col["distinct_seeds"] != 2:
        f.append("the collision report miscounted distinct streams")
    if not independence_from_seeds({"A@B": 1, "C@D": 2})["independent"]:
        f.append("two distinct seeds were reported as colliding")

    print("keyed_seed selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("the seed ignores the game, so every game on a slate shares one stream",
     '    payload = "\\x1f".join(str(vals[k]) for k in KEY_FIELDS)',
     '    payload = "\\x1f".join(str(vals[k]) for k in ("model_id", "slate_date", "simulation_version"))'),
    ("the seed ignores the model, so two arms draw the identical stream",
     '    payload = "\\x1f".join(str(vals[k]) for k in KEY_FIELDS)',
     '    payload = "\\x1f".join(str(vals[k]) for k in ("slate_date", "game_id", "simulation_version"))'),
    ("the seed ignores the slate date",
     'KEY_FIELDS = ("model_id", "slate_date", "game_id", "simulation_version")',
     'KEY_FIELDS = ("model_id", "game_id", "simulation_version")'),
    ("a missing key field is defaulted instead of refused",
     "    if missing:", "    if False:"),
    ("an empty string key field is accepted",
     '    missing = [k for k in KEY_FIELDS if vals.get(k) in (None, "")]',
     "    missing = [k for k in KEY_FIELDS if vals.get(k) is None]"),
    ("the refusal stops explaining the collapse risk",
     'f"would collapse distinct games onto a shared stream.")', 'f"is required.")'),
    # NOT A MUTANT, deliberately. seed_for's SIGNATURE makes slate-composition dependence
    # structurally impossible: the slate is not a parameter, so there is nothing a mutant could make
    # the seed depend on. The property is enforced by the interface rather than by a check, and the
    # reordered/added/removed fixtures above confirm it end to end. Saying so beats inventing a
    # mutant that appears to kill (lesson 23 corollary).
    ("the manifest hash depends on slate order",
     '        "\\x1e".join(f"{g}={s}" for g, s in sorted(seeds.items())).encode()).hexdigest()',
     '        "\\x1e".join(f"{g}={s}" for g, s in seeds.items()).encode()).hexdigest()'),
    ("the seed range is unbounded and can go negative",
     '    return int.from_bytes(h[:8], "big") >> (64 - SEED_BITS)',
     '    return int.from_bytes(h[:8], "big", signed=True)'),
    ("the independence report claims independence without checking",
     '            "independent": collisions == 0,', '            "independent": True,'),
    ("the collision count is computed over the wrong set",
     "    collisions = len(vals) - len(set(vals))", "    collisions = 0"),
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
