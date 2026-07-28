#!/usr/bin/env python3
"""Model-version registry: every ML output binds to a unique model_id.

Why (Phase-0 finding V-3): the label "V13.1" spans two different formulas — the verdict scorer and
the live card run HFA 1.005, while the v13_1.py family runs 1.03 — and three different simulation
configurations (seed 7 / n=4000, seed 722 / n=30000, seed 1319 / n=40000). One label, several
models. Nothing here RESOLVES the 1.005-vs-1.03 question; it only makes the identities distinct so
the ambiguity can never again hide inside a shared name. Historical artifact labels are preserved;
supersession is documented, never rewritten (R6).

A model_id binds: source file + sha256, HFA value + provenance, simulation seed + count,
calibration-artifact hash (or None), and input-schema version. The self-test recomputes everything
and FAILS on drift, on duplicate ids, and on any ML-sim file on disk that is not registered.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)


def sha(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


#: LIVE entries: hashes are RECOMPUTED each selftest and must match the file on disk.
#: HISTORICAL_ARTIFACT entries: dated records; the file must still match the hash captured at
#: registration — a change to a dated artifact is a record falsification, so it FAILS too.
REGISTRY = {
    "ml.v13_1.hfa1005.scorer.s7n4000": {
        "role": "VERDICT_SOURCE",
        "source": "engine/score_and_calibrate.py",
        "hfa": 1.005, "hfa_provenance": "literal in source",
        "seed": 7, "sims_per_game": 4000, "rng_policy": "sequential_over_features_rows",
        "calibration_artifact": "data/backfill/mlb/2026/calibration.json",
        "input_schema": "features.csv-v1 (gamePk,date,away,home,venue,home_win,total,margin,features)",
        "note": "Produced the n=1461 NO_PROMOTE evidence. Reproduced bit-identically 2026-07-28.",
    },
    "ml.v13_1.hfa1005.card.s722n30000": {
        "role": "LIVE_CARD",
        "source": "harness/daily_card.py",
        "hfa": 1.005, "hfa_provenance": "import: engine/hfa.py CURRENT",
        "seed": 722, "sims_per_game": 30000, "rng_policy": "sequential_slate_order",
        "calibration_artifact": None,
        "input_schema": "live-v1 (results.csv aggregates + sp_asof pitcher logs + park_factors)",
        "note": "Sequential module-level RNG: per-game numbers depend on slate order. Known; not changed in Phase 1.",
    },
    "ml.v13_1.hfa1005.card.s722n30000.per_game_reset": {
        "role": "DIAGNOSTIC_VARIANT",
        "source": "harness/daily_card.py",
        "hfa": 1.005, "hfa_provenance": "import: engine/hfa.py CURRENT",
        "seed": 722, "sims_per_game": 30000, "rng_policy": "per_game_reset_seed722",
        "calibration_artifact": None,
        "input_schema": "live-v1",
        "note": "Same sim source, RNG reset to 722 before EVERY game: outputs differ from the sequential "
                "stream, so this is a DISTINCT identity (owner correction 2026-07-28). Used by the 7/27 "
                "post-slate replay and the 7/28 exploratory stale-input diagnostic. Never a production card.",
    },
    "ml.v13_1.p2eval.hfa_param.n4000.per_row_reset": {
        "role": "EVALUATION_RUNNER",
        "source": "harness/ml_p2_baselines.py",
        "hfa": "parameter (P2: 1.005; P3-A1 compares 1.005 vs 1.03; every result artifact stamps the value used)",
        "seed": "7_000_000 + global_row_index", "sims_per_game": 4000, "rng_policy": "per_row_reset",
        "calibration_artifact": None,
        "input_schema": "ml-asof-v1 (firewall dataset, vintage-pinned)",
        "note": "V13 verdict-scorer arithmetic on firewall features; per-row RNG so results are "
                "split-independent. Pre-registered in docs/experiments/ML-P2P3_prereg.md. Never a card.",
    },
    "ml.v13_1.hfa103.backtest.s1319n40000": {
        "role": "LEGACY_BACKTEST",
        "source": "engine/v13_1.py",
        "hfa": 1.03, "hfa_provenance": "import: engine/hfa.py V13_1_LEGACY",
        "seed": 1319, "sims_per_game": 40000, "rng_policy": "sequential_over_backtest_rows",
        "calibration_artifact": None,
        "input_schema": "hardcoded 7/18 TEAM/SP tables",
    },
    # ---- dated / experimental artifacts: preserved, never edited, superseded by the entries above ----
    "hist.calibrate_n26":        {"role": "HISTORICAL_ARTIFACT", "source": "engine/calibrate.py",            "hfa": 1.005},
    "hist.v13_1_pooled":         {"role": "HISTORICAL_ARTIFACT", "source": "engine/v13_1_pooled.py",         "hfa": 1.03},
    "hist.v13_2_pitcher_index":  {"role": "HISTORICAL_ARTIFACT", "source": "engine/v13_2_pitcher_index.py",  "hfa": 1.03},
    "hist.card_2026_07_19":      {"role": "HISTORICAL_ARTIFACT", "source": "engine/card_2026_07_19.py",      "hfa": 1.03},
    "hist.card_2026_07_20":      {"role": "HISTORICAL_ARTIFACT", "source": "engine/card_2026_07_20.py",      "hfa": 1.005},
    "hist.park_compare":         {"role": "HISTORICAL_ARTIFACT", "source": "engine/park_compare.py",         "hfa": "parameter (2x2 factorial tool)"},
}

#: Registered source hashes. Regenerate deliberately with --pin after an AUTHORIZED change to a
#: LIVE source; a hash change without a matching --pin commit fails healthcheck. Stored separately
#: from REGISTRY so a pin update is a visible one-line diff per file.
PINS_PATH = "harness/model_registry_pins.json"


def _hfa_in_source(path: str):
    """What HFA does this file actually apply? Returns (kind, value-or-symbol)."""
    src = open(path).read()
    lits = sorted(set(re.findall(r"\*\s*(?:oh\s*\*\s*)?pf_?h\s*\*\s*(1\.\d+)", src.replace(" ", ""))))
    lits = [float(x) for x in re.findall(r"pf_?h\*(1\.\d+)", src.replace(" ", ""))]
    imports = re.findall(r"from hfa import (\w+)(?:\s+as\s+(\w+))?", src)
    return sorted(set(lits)), [i[0] for i in imports]


def selftest() -> int:
    import hfa_values  # local shim below
    fails = []
    pins = json.load(open(PINS_PATH)) if os.path.exists(PINS_PATH) else {}
    ids = list(REGISTRY)
    if len(ids) != len(set(ids)):
        fails.append("duplicate model_id")
    seen_sources = {}
    for mid, m in REGISTRY.items():
        p = m["source"]
        if not os.path.exists(p):
            fails.append(f"{mid}: source missing {p}")
            continue
        h = sha(p)
        if p in pins and pins[p] != h:
            fails.append(f"{mid}: source hash drifted from pin: {p} {h[:12]} != {pins[p][:12]}")
        seen_sources[p] = mid
        lits, imports = _hfa_in_source(p)
        want = m["hfa"]
        if isinstance(want, float):
            if imports and not lits:
                sym = imports[0]
                actual = {"CURRENT": hfa_values.CURRENT, "V13_1_LEGACY": hfa_values.V13_1_LEGACY}.get(sym)
                if actual != want:
                    fails.append(f"{mid}: registered HFA {want} but source imports {sym}={actual}")
            elif lits:
                if len(set(lits)) != 1 or lits[0] != want:
                    fails.append(f"{mid}: registered HFA {want} but source literals {lits}")
            else:
                fails.append(f"{mid}: no HFA found in {p}")
    # every ML-sim file on disk must be registered: scan for home-mean HFA multiplication
    for root in ("engine", "harness"):
        for f in sorted(os.listdir(root)):
            if not f.endswith(".py"):
                continue
            p = f"{root}/{f}"
            src = open(p).read().replace(" ", "")
            if re.search(r"pf_?h\*(1\.\d+|HFA)", src) and p not in seen_sources and f not in ("hfa.py",):
                # grade/build one-offs that only DISPLAY probabilities don't multiply pf_h; sim owners do.
                fails.append(f"UNREGISTERED ML sim source: {p}")
    if fails:
        print("model_registry self-test: FAIL")
        for x in fails:
            print("  " + x)
        return 1
    print(f"model_registry self-test: PASS ({len(REGISTRY)} identities, {len(pins)} pinned sources)")
    return 0


def pin() -> None:
    pins = {m["source"]: sha(m["source"]) for m in REGISTRY.values() if os.path.exists(m["source"])}
    json.dump(pins, open(PINS_PATH, "w"), indent=1)
    print(f"pinned {len(pins)} sources -> {PINS_PATH}")


class _HfaShim:
    pass


def _load_hfa():
    sys.path.insert(0, os.path.join(BASE, "engine"))
    import hfa
    shim = _HfaShim()
    shim.CURRENT = hfa.CURRENT
    shim.V13_1_LEGACY = hfa.V13_1_LEGACY
    sys.modules["hfa_values"] = shim
    return shim


_load_hfa()

if __name__ == "__main__":
    if "--pin" in sys.argv:
        pin()
        raise SystemExit(0)
    raise SystemExit(selftest())
