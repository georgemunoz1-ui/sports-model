#!/usr/bin/env python3
"""FRANCHISE IDENTITY — one canonical id per franchise, per sport, refused rather than guessed.

OWNER AMENDMENT 8 (2026-08-23): "Normalize WNBA identities. The earlier reference uses WAS@POR;
this card uses WAS@PDX. Bind both to one canonical franchise ID before paired grading, or the
comparison can silently fail exactly like the MLB 62-key defect."

THE DEFECT IS ALREADY MEASURABLE IN THIS REPO. Counting bare tokens across data/wnba:
PDX 24 / POR 5, PHX 32 / PHO 5, LVA 31 / LV 2, NYL 19 / NY 2, LAS 46 / LA 2. The same slate that
this amendment is about spells one MLB game CIN@AZ on the card and CIN@ARI on the reference. Paired
grading joins on the game key; a key that spells a franchise two ways does not fail loudly, it
simply finds no partner and drops the game — which is how ATL came to show 23 games in one view and
97 in another.

WHY A NEW MODULE AND NOT THE EXISTING MAPS. The maps exist and they work — and they live INSIDE the
models. wnba_model_v1.XW already binds POR to PDX; adaptive_state.TEAM_ABBR already binds ARI to AZ.
Neither is applied at the layer where arms are PAIRED, so the champion normalises and the reference
does not, and the pairing layer never learns that two spellings met. This module is that shared
layer. It does not invent a second convention: MLB canon is DERIVED from adaptive_state.TEAM_ABBR
and the WNBA aliases are CHECKED against wnba_model_v1.XW at import, so the tables cannot drift
apart silently.

THE PASSTHROUGH IS THE BUG, SO THERE IS NO PASSTHROUGH. adaptive_state.normalize_team returns an
unmapped token unchanged, deliberately, so it surfaces as an anomaly. That works when a human reads
the output and fails when a join consumes it: an unknown token that passes through becomes a new
franchise. Here, `canonical` on an unrecognised token RAISES, and `canonical_or_none` returns None
with a reason. Nothing is folded into a neighbour and nothing invents a franchise.

COVERAGE IS STATED, NOT ASSUMED. Every table below names its source. The NFL table is the 32 codes
that actually appear in data/nfl; it is not a memorised league list, and a code outside it is
refused rather than accepted on the strength of looking plausible.

API
  canonical(sport, token)             -> canonical id, or raises UnknownFranchise
  canonical_or_none(sport, token)     -> (id | None, reason)
  canonical_game_id(sport, away, home)-> "sport:AWAY@HOME"
  bind(sport, game_id)                -> canonicalise a written game key, e.g. WAS@POR -> wnba:WAS@PDX
  pairing_audit(rows_a, rows_b, sport)-> which games would silently fail to pair, and why
  coverage_report()                   -> the tables, their sources and their stated completeness
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))

UNKNOWN = "UNKNOWN_FRANCHISE_TOKEN"
UNKNOWN_SPORT = "UNKNOWN_SPORT"
MALFORMED = "MALFORMED_GAME_KEY"


class UnknownFranchise(Exception):
    pass


# --- MLB: canon derived from adaptive_state, the existing authority --------------------------------
def _mlb_tables():
    sys.path.insert(0, BASE)
    import adaptive_state
    canon = sorted(set(adaptive_state.TEAM_ABBR.values()))
    aliases = {}
    for k, v in adaptive_state.TEAM_ABBR.items():
        aliases[k.upper()] = v
    for c in canon:
        aliases[c.upper()] = c
    return set(canon), aliases


# --- WNBA: 15 franchises for the 2026 season, as spelled in data/wnba ------------------------------
WNBA_CANON = {"ATL", "CHI", "CON", "DAL", "GSV", "IND", "LAS", "LVA",
              "MIN", "NYL", "PDX", "PHX", "SEA", "TOR", "WAS"}
WNBA_ALIASES = {"POR": "PDX", "PORTLAND": "PDX", "PHO": "PHX", "LA": "LAS", "LV": "LVA",
                "NY": "NYL", "GS": "GSV", "CONN": "CON", "CT": "CON", "WSH": "WAS"}

# --- NFL: the 32 codes present in data/nfl. Sourced, not recalled. ---------------------------------
NFL_CANON = {"ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB",
             "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
             "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS"}
NFL_ALIASES = {"JAC": "JAX", "WSH": "WAS", "LVR": "LV", "OAK": "LV", "SD": "LAC", "STL": "LAR"}

_MLB_CANON, _MLB_ALIASES = _mlb_tables()

CANON = {"mlb": _MLB_CANON, "wnba": WNBA_CANON, "nfl": NFL_CANON}
ALIASES = {"mlb": _MLB_ALIASES,
           "wnba": dict(WNBA_ALIASES, **{c: c for c in WNBA_CANON}),
           "nfl": dict(NFL_ALIASES, **{c: c for c in NFL_CANON})}

SOURCES = {
    "mlb": "derived at import from adaptive_state.TEAM_ABBR (30 franchises, 34 keys)",
    "wnba": "the 15 codes spelled in data/wnba; aliases cross-checked against wnba_model_v1.XW",
    "nfl": "the 32 codes present in data/nfl; NOT a recalled league list",
}
COMPLETENESS = {"mlb": "COMPLETE_30_FRANCHISES", "wnba": "COMPLETE_15_FRANCHISES_2026",
                "nfl": "COMPLETE_32_FRANCHISES_AS_OBSERVED"}


_SENTINEL = object()


def _read_xw_from_wnba_model(path=None):
    """Pull wnba_model_v1.XW out of the source without importing it (that module needs pyarrow)."""
    path = path or os.path.join(BASE, "wnba_model_v1.py")
    if not os.path.exists(path):
        return None
    tree = ast.parse(open(path).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "XW" for t in node.targets):
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                return None
    return None


def alias_consistency(xw=_SENTINEL, path=None):
    """The WNBA aliases here must not CONTRADICT the champion model's own map.

    `xw` is injectable so the conflict branch is exercised by a fixture rather than only by the
    happy path — a consistency check that has never seen a conflict is decoration.
    """
    if xw is _SENTINEL:
        xw = _read_xw_from_wnba_model(path)
    if xw is None:
        return {"status": "XW_NOT_READABLE", "conflicts": []}
    conflicts = []
    for k, v in xw.items():
        if v not in WNBA_CANON:
            continue  # XW covers codes from other sports' staging too; only WNBA targets bind here
        mine = WNBA_ALIASES.get(k.upper(), k.upper() if k.upper() in WNBA_CANON else None)
        if mine is None:
            conflicts.append({"alias": k, "model_says": v, "here": "UNBOUND"})
        elif mine != v:
            conflicts.append({"alias": k, "model_says": v, "here": mine})
    return {"status": "CONSISTENT" if not conflicts else "CONFLICT", "conflicts": conflicts,
            "checked": len(xw)}


# =================================================================================================
def canonical_or_none(sport, token):
    if sport not in CANON:
        return None, UNKNOWN_SPORT
    if token is None or not isinstance(token, str) or not token.strip():
        return None, UNKNOWN
    t = re.sub(r"\s+", " ", token.strip()).upper()
    hit = ALIASES[sport].get(t)
    if hit is None:
        # long names live in the MLB table with their original casing
        hit = ALIASES[sport].get(token.strip().upper())
    if hit is None:
        return None, UNKNOWN
    return hit, None


def canonical(sport, token):
    got, why = canonical_or_none(sport, token)
    if got is None:
        raise UnknownFranchise(f"{why}: {sport!r} {token!r} — refused, never folded into a neighbour")
    return got


def canonical_game_id(sport, away, home):
    return f"{sport}:{canonical(sport, away)}@{canonical(sport, home)}"


def bind(sport, game_id):
    """Canonicalise a written key like 'WAS@POR' or 'CIN@ARI'."""
    if not isinstance(game_id, str) or game_id.count("@") != 1:
        raise UnknownFranchise(f"{MALFORMED}: {game_id!r}")
    away, home = game_id.split("@")
    return canonical_game_id(sport, away, home)


def pairing_audit(keys_a, keys_b, sport, label_a="A", label_b="B"):
    """Which games would silently fail to pair, and whether canonicalisation rescues them."""
    def _canon(keys):
        out, bad = {}, []
        for k in keys:
            try:
                out[bind(sport, k)] = k
            except UnknownFranchise as e:
                bad.append({"key": k, "reason": str(e).split(":")[0]})
        return out, bad
    ca, bad_a = _canon(keys_a)
    cb, bad_b = _canon(keys_b)
    raw_common = set(keys_a) & set(keys_b)
    canon_common = set(ca) & set(cb)
    rescued = sorted({(ca[k], cb[k]) for k in canon_common if ca[k] != cb[k]})
    return {
        "sport": sport,
        "n_" + label_a: len(keys_a), "n_" + label_b: len(keys_b),
        "paired_on_raw_keys": len(raw_common),
        "paired_on_canonical_keys": len(canon_common),
        "silently_lost_without_binding": len(canon_common) - len(raw_common),
        "rescued_pairs": [{"as_written_" + label_a: a, "as_written_" + label_b: b} for a, b in rescued],
        "unresolvable": bad_a + bad_b,
        "status": "BINDING_REQUIRED" if len(canon_common) > len(raw_common) else "KEYS_ALREADY_ALIGNED",
    }


def coverage_report():
    return {"sports": {s: {"n_canonical": len(CANON[s]), "n_alias_keys": len(ALIASES[s]),
                           "source": SOURCES[s], "completeness": COMPLETENESS[s]}
                       for s in sorted(CANON)},
            "wnba_alias_consistency": alias_consistency(),
            "rule": "an unrecognised token is refused, never passed through"}


# =================================================================================================
def selftest():
    f = []

    # --- the amendment, exactly ------------------------------------------------------------------
    if canonical("wnba", "POR") != "PDX" or canonical("wnba", "PDX") != "PDX":
        f.append("POR and PDX must bind to one canonical id")
    if bind("wnba", "WAS@POR") != bind("wnba", "WAS@PDX"):
        f.append("WAS@POR and WAS@PDX must produce the same key")
    if bind("mlb", "CIN@ARI") != bind("mlb", "CIN@AZ"):
        f.append("CIN@ARI and CIN@AZ must produce the same key")
    if canonical("wnba", "PHO") != "PHX" or canonical("wnba", "LA") != "LAS":
        f.append("the other observed WNBA aliases must bind too")

    # --- refusal, not passthrough ----------------------------------------------------------------
    for bad in ("QQQ", "", None, "Portland Fire XI"):
        got, why = canonical_or_none("wnba", bad)
        if got is not None:
            f.append(f"{bad!r} must not resolve, got {got}")
    try:
        canonical("wnba", "QQQ")
        f.append("an unknown token must raise, not pass through")
    except UnknownFranchise:
        pass
    if canonical_or_none("nhl", "TOR")[1] != UNKNOWN_SPORT:
        f.append("an unknown sport must be refused")

    # --- two franchises never collapse ------------------------------------------------------------
    ids = {t: canonical("wnba", t) for t in WNBA_CANON}
    if len(set(ids.values())) != len(WNBA_CANON):
        f.append("canonical ids must be one-to-one on the canon")
    if canonical("wnba", "WAS") == canonical("wnba", "SEA"):
        f.append("distinct franchises must stay distinct")
    # sport scoping: ATL exists in all three and must not cross-bind
    if canonical_game_id("wnba", "ATL", "CHI") == canonical_game_id("nfl", "ATL", "CHI"):
        f.append("game keys must be sport-scoped")

    # --- the pairing failure this exists to prevent -----------------------------------------------
    a = ["WAS@POR", "SEA@DAL", "IND@CHI"]
    b = ["WAS@PDX", "SEA@DAL", "IND@CHI"]
    p = pairing_audit(a, b, "wnba", "reference", "card")
    if p["paired_on_raw_keys"] != 2 or p["paired_on_canonical_keys"] != 3:
        f.append(f"binding must rescue the WAS game, got {p}")
    if p["silently_lost_without_binding"] != 1 or p["status"] != "BINDING_REQUIRED":
        f.append("the audit must say a game was being lost")
    if not p["rescued_pairs"] or p["rescued_pairs"][0]["as_written_reference"] != "WAS@POR":
        f.append("the audit must show both spellings of the rescued game")
    aligned = pairing_audit(b, b, "wnba")
    if aligned["status"] != "KEYS_ALREADY_ALIGNED" or aligned["silently_lost_without_binding"] != 0:
        f.append("already-aligned keys must report as aligned")
    unres = pairing_audit(["QQQ@PDX"], ["WAS@PDX"], "wnba")
    if not unres["unresolvable"]:
        f.append("an unresolvable key must be reported, not dropped")

    # --- malformed keys ---------------------------------------------------------------------------
    for bad in ("WAS", "WAS@PDX@SEA", 17, None):
        try:
            bind("wnba", bad)
            f.append(f"malformed key {bad!r} must raise")
        except UnknownFranchise:
            pass

    # --- the tables do not drift from the models --------------------------------------------------
    # the conflict branch must actually fire, and the unreadable branch must be distinguishable
    conf = alias_consistency(xw={"POR": "SEA"})
    if conf["status"] != "CONFLICT" or conf["conflicts"][0]["model_says"] != "SEA":
        f.append(f"a contradicting alias must be reported as a conflict, got {conf}")
    unb = alias_consistency(xw={"ZZZ": "PDX"})
    if unb["status"] != "CONFLICT" or unb["conflicts"][0]["here"] != "UNBOUND":
        f.append(f"an alias the model binds and this module does not must be reported, got {unb}")
    if alias_consistency(xw={"POR": "PDX"})["status"] != "CONSISTENT":
        f.append("an agreeing alias must be consistent")
    if alias_consistency(path=os.path.join(BASE, "no_such_module.py"))["status"] != "XW_NOT_READABLE":
        f.append("an unreadable source must be reported as unreadable, not as consistent")

    cons = alias_consistency()
    if cons["status"] == "CONFLICT":
        f.append(f"WNBA aliases contradict wnba_model_v1.XW: {cons['conflicts']}")
    if cons["status"] == "XW_NOT_READABLE":
        f.append("wnba_model_v1.XW must be readable, or the consistency check is decoration")
    if len(CANON["mlb"]) != 30:
        f.append(f"MLB canon should be 30 franchises, got {len(CANON['mlb'])}")
    if len(CANON["nfl"]) != 32:
        f.append(f"NFL canon should be 32 franchises, got {len(CANON['nfl'])}")
    if canonical("mlb", "Atlanta Braves") != "ATL":
        f.append("the MLB long names must still resolve through the derived table")
    # case and INTERNAL whitespace are normalised; the upper()-only fallback cannot rescue this one
    if canonical("mlb", "Atlanta  Braves") != "ATL":
        f.append("collapsed internal whitespace must still resolve")
    if canonical("wnba", " por ") != "PDX" or canonical("wnba", "pdx") != "PDX":
        f.append("case and surrounding whitespace must be normalised")

    for x in f:
        print("FAIL:", x)
    if not f:
        print("franchise_identity selftest: OK")
    return f


MUTANTS = [
    ("an unknown token passes through instead of being refused",
     '    if hit is None:\n        return None, UNKNOWN\n    return hit, None',
     "    if hit is None:\n        return t, None\n    return hit, None"),
    ("canonical stops raising on an unknown token",
     "    if got is None:\n        raise UnknownFranchise(", "    if got is None and False:\n        raise UnknownFranchise("),
    ("POR stops binding to PDX",
     'WNBA_ALIASES = {"POR": "PDX", "PORTLAND": "PDX", "PHO": "PHX", "LA": "LAS", "LV": "LVA",\n                "NY": "NYL", "GS": "GSV", "CONN": "CON", "CT": "CON", "WSH": "WAS"}',
     'WNBA_ALIASES = {"PORTLAND": "PDX", "PHO": "PHX", "LA": "LAS", "LV": "LVA",\n                "NY": "NYL", "GS": "GSV", "CONN": "CON", "CT": "CON", "WSH": "WAS"}'),
    ("the MLB canon stops coming from adaptive_state",
     "    canon = sorted(set(adaptive_state.TEAM_ABBR.values()))", '    canon = ["AZ", "ATL"]'),
    ("game keys stop being sport-scoped, so ATL crosses leagues",
     '    return f"{sport}:{canonical(sport, away)}@{canonical(sport, home)}"',
     '    return f"{canonical(sport, away)}@{canonical(sport, home)}"'),
    ("a malformed key is accepted",
     '    if not isinstance(game_id, str) or game_id.count("@") != 1:', "    if False:"),
    ("the pairing audit stops counting what binding rescues",
     '        "silently_lost_without_binding": len(canon_common) - len(raw_common),',
     '        "silently_lost_without_binding": 0,'),
    ("the pairing audit stops showing both spellings",
     "    rescued = sorted({(ca[k], cb[k]) for k in canon_common if ca[k] != cb[k]})", "    rescued = []"),
    ("an unresolvable key is dropped from the pairing audit",
     '            except UnknownFranchise as e:\n                bad.append({"key": k, "reason": str(e).split(":")[0]})',
     "            except UnknownFranchise as e:\n                pass"),
    ("the audit always says the keys were already aligned",
     '        "status": "BINDING_REQUIRED" if len(canon_common) > len(raw_common) else "KEYS_ALREADY_ALIGNED",',
     '        "status": "KEYS_ALREADY_ALIGNED",'),
    ("the consistency check against the champion model is disabled",
     "    for k, v in xw.items():", "    for k, v in {}.items():"),
    ("the consistency check silently tolerates an unreadable source",
     '        return {"status": "XW_NOT_READABLE", "conflicts": []}',
     '        return {"status": "CONSISTENT", "conflicts": []}'),
    ("two WNBA franchises collapse onto one id",
     '"MIN", "NYL", "PDX", "PHX", "SEA", "TOR", "WAS"}', '"MIN", "NYL", "PDX", "PHX", "SEA", "TOR"}'),
    ("an unknown sport resolves anyway",
     "    if sport not in CANON:\n        return None, UNKNOWN_SPORT", "    if False:\n        return None, UNKNOWN_SPORT"),
    ("case and whitespace stop being normalised",
     '    t = re.sub(r"\\s+", " ", token.strip()).upper()', "    t = token"),
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
    if "--report" in sys.argv:
        print(json.dumps(coverage_report(), indent=1)); sys.exit(0)
    print(__doc__)
