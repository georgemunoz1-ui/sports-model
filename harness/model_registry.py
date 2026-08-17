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
    # MEASUREMENT ONLY — emits no forecast, registers nothing, and its output never reaches a card,
    # a ledger or the gate. It exists to SEPARATE the true parameter effect from RNG-coupling noise in
    # an ALREADY-FROZEN artifact (see docs/experiments/2026-08-17_MECHANISM_CLOSEOUT.json). It is
    # registered because it contains a verbatim transcription of the V13 sim math, and an unregistered
    # copy of that math is exactly how a shadow model gets born. Its correctness condition is stricter
    # than a model's: `--verify-math` must reproduce the registered v3 card probabilities EXACTLY.
    "ml.v13_1.hfa1005.noisestudy.measurement": {
        "role": "MEASUREMENT_NON_FORECASTING",
        "source": "harness/rng_noise_study.py",
        "hfa": 1.005, "hfa_provenance": "import: engine/hfa.py CURRENT",
        "seed": None, "sims_per_game": None,
        "rng_policy": "per_game_keyed_seeds (sha256 of game|replicate) — deliberately NOT the frozen "
                      "sequential-slate policy, because removing stream-position coupling is the point",
        "calibration_artifact": None,
        "input_schema": "same as the live card; reads registered card artifacts + results.csv states",
        "emits_forecasts": False,
        "note": ("Transcription verified against the frozen card by --verify-math, which caught three "
                 "real transcription bugs before any number was believed: an omitted trailing "
                 "rng.poisson that shifts downstream RNG, use of the rounded rather than raw park "
                 "factor, and a reduced ABBR map that split franchises with legacy full-name rows."),
    },
    # MEASUREMENT ONLY — the companion to the noise study, and its corrective. The noise study
    # measures how far a frozen artifact's output MOVES when an input is swapped; this measures
    # whether that movement is in the right direction, out of sample. Registered because it runs V13
    # arithmetic over the whole frozen feature window, but it contains NO copied sim math: v13_sim,
    # load_rows and _sp are imported from harness/run_v13_historical.py, which is separately pinned.
    "ml.v13_1.form_ablation.measurement": {
        "role": "MEASUREMENT_NON_FORECASTING",
        "source": "harness/form_oof_ablation.py",
        # not a float: this module applies no HFA of its own. It has zero sim lines; the 1.005 comes
        # from engine/hfa.py via the imported v13_sim, whose own registered entry asserts it.
        "hfa": "inherited (no HFA term in this source; imports v13_sim from harness/run_v13_historical.py)",
        "seed": "722 + int(gamePk) — identical in every arm (common random numbers)",
        "sims_per_game": "parameter (200000 for the registered run; stamped in the artifact)",
        "rng_policy": "per_game_seed_722_plus_gamePk, shared across arms",
        "calibration_artifact": None,
        "input_schema": "features.csv-v1 (frozen as-of backfill through 2026-07-19; NO look-ahead)",
        "emits_forecasts": False,
        "note": ("Three arms over one frozen feature file: FULL (as-of form), STALE (each team's own "
                 "snapshot lagged >= N days, read off the same file so look-ahead is not representable), "
                 "NO_FORM (form inputs None -> v13_sim's existing LG_RPG fallback). Out-of-sample by "
                 "construction: V13 fits nothing, so there is no train/test split to leak across. "
                 "Inference is a date-block bootstrap over slate dates plus Holm over the primary "
                 "family. Answers the owner's 2026-08-17 caution: useful, not merely active."),
    },
    # MEASUREMENT ONLY — attributes a card-to-card probability change to the specific data that
    # caused it, by rebuilding intermediate form states from DATE FILTERS over the canonical results
    # file (never mutating it). Registered because it replays V13 card probabilities; it holds no
    # copied sim math (sim_p/team_form/raw_pf are imported from the pinned rng_noise_study). Its
    # correctness condition is a refusal gate: the reconstructed states must reproduce the REGISTERED
    # v2 and v3 cards exactly or it emits nothing.
    "ml.v13_1.form_refresh_diff.measurement": {
        "role": "MEASUREMENT_NON_FORECASTING",
        "source": "harness/form_refresh_diff.py",
        "hfa": "inherited (no HFA term in this source; imports sim_p from harness/rng_noise_study.py)",
        "seed": "722 for the frozen-n card replay; sha256(game|replicate) for the paired high-n arm",
        "sims_per_game": "30000 (frozen replay) and 2000000 (reference estimate)",
        "rng_policy": "sequential_slate_order for the card replay (matches the frozen card exactly); "
                      "per_game_keyed_seeds shared across arms for the paired contrast",
        "calibration_artifact": None,
        "input_schema": "registered card artifacts + date-filtered results.csv",
        "emits_forecasts": False,
        "note": ("Separates the 2026-08-13 interior-hole repair from the 2026-08-15/16 refresh, which "
                 "the registered v2->v3 contrast bundles together (one intake applied all 39 rows). "
                 "Reports each per-game delta twice: at the frozen n, and as a high-precision "
                 "reference estimate with a Monte-Carlo CI and Holm correction."),
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
    "ml.d_logistic_2f.p4.cfg132523ac": {
        "role": "P4_CHALLENGER",
        "source": "harness/ml_p4_forward.py",
        "hfa": "n/a (logistic; no simulation)",
        "seed": "n/a (deterministic)", "sims_per_game": 0, "rng_policy": "deterministic_closed_form",
        "calibration_artifact": "data/mlb/ml_asof/p3_candidate_config.json",
        "input_schema": "p4-forward-v1 (as-of team form + shrunk SP ERA diff)",
        "note": "FROZEN candidate d_logistic_2f, config sha256 132523ac86695b851fd8e4c88815da0416a"
                "79421e76ba0cce1c9bce24dfe096b (canonical: sha256 of sort_keys json.dumps; the "
                "artifact's file-byte sha256 eede422d0659e485... is pinned too). The generator "
                "verifies BOTH before every run and refuses on either mismatch. No refit during "
                "Phase 4 (owner override 2026-07-28).",
    },
    "ml.v13_1.p4fwd.hfa1005.n4000.rng_gamePk": {
        "role": "P4_INCUMBENT_REFERENCE",
        "source": "harness/ml_p4_forward.py",
        "hfa": "parameter fixed 1.005 for P4 (stamped per record)",
        "seed": "int(gamePk)", "sims_per_game": 4000, "rng_policy": "per_game_seed_gamePk",
        "calibration_artifact": None,
        "input_schema": "p4-forward-v1",
        "note": "V13 verdict-scorer arithmetic, forward RNG keyed to gamePk: deterministic and "
                "slate-order independent. Distinct identity from every prior V13 stream. "
                "Delegates the arithmetic to harness/ml_p2_baselines.v13_row (itself pinned) via "
                "_gidx = gamePk - 7_000_000, so seed = int(gamePk) with zero copied formula lines; "
                "bit-identity proven in the ml_p4_forward selftest.",
    },
    "ml.v13_1.hist_replay.hfa1005.n30000.rng_gamePk": {
        "role": "HISTORICAL_REPLAY_RUNNER",
        "source": "harness/run_v13_historical.py",
        "hfa": 1.005, "hfa_provenance": "import: engine/hfa.py CURRENT",
        "seed": "722 + int(gamePk)", "sims_per_game": 30000, "rng_policy": "per_game_seed_722_plus_gamePk",
        "calibration_artifact": None,
        "input_schema": "features.csv-v1 (frozen as-of backfill through 2026-07-19; NO look-ahead)",
        "note": "Date-safe V13 Monte Carlo replay over the FROZEN as-of features (owner spec "
                "2026-08-04): reads ONLY features.csv, never loops daily_card.py over historical "
                "dates (that reads every final on disk -> look-ahead leakage). Per-game seed = "
                "722 + int(gamePk), so results are row-order and parallelism invariant. sims/game is "
                "configurable (--sims-per-game, default 30000; also validated at 100000). Emits full "
                "ML/RL/totals distributions + MC SE + projected score; scores the totals distribution "
                "at the REALIZED total as a PIT check (no market total line in the frozen features). "
                "The d_logistic_2f candidate is computed ONCE per row here, deterministic, never "
                "simulated. Same-book market benchmark is null on this window (only 7/24-7/25 closes "
                "on file, after the 7/19 feature freeze). Diagnostic runner; never a production card.",
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
    "wnba.rs.ff7_logit_ridge.v1_0.shadow": {
        "role": "WNBA_SHADOW_DIAGNOSTIC",
        "source": "harness/wnba_model_v1.py",
        "hfa": None, "hfa_provenance": "logistic intercept (fitted, not a constant)",
        "seed": None, "sims_per_game": None, "rng_policy": "deterministic (no simulation layer)",
        "calibration_artifact": "data/wnba/model/2026-08-12_v1_walkforward.json",
        "input_schema": "staged-parquet-v1 (official-plus-one reconciled team rows, 2017-2026)",
        "note": "Preregistered 2026-08-12 (docs/experiments/2026-08-12_WNBA_V1_PREREG.json). "
                "All three targets VALIDATED_VS_BASELINE under date-block bootstrap + Holm. "
                "FIREWALLED: no output reaches the MLB gate, forecasts or ledger.",
    },
}
#: Registered source hashes, as an APPEND-ONLY ledger of authorized generator implementation
#: versions (schema model_registry_pins-v2). Owner instruction 2026-08-17: "Keep the source re-pin
#: append-only as a new generator implementation/version; never replace the historical pin."
#:
#: WHY the v1 flat map was wrong: it stored one sha per path and --pin REWROTE it, so authorizing an
#: I/O fix to harness/daily_card.py on 2026-08-17 silently erased the pin f9cad5d3... that 200+
#: registered forecasts bind as the implementation which produced them. Those bindings were then
#: unresolvable against the registry — the record still said "produced by f9cad5d3" but nothing on
#: file agreed that f9cad5d3 had ever been authorized. Git preserved it; the governance artifact did
#: not, and a gate that depends on `git log` to know its own history is not a gate.
#:
#: v2 keeps an ordered `versions` list per source. A re-pin APPENDS. `current` is always
#: versions[-1].sha256 and is the only version permitted on disk; every earlier version stays
#: readable forever so historical bindings resolve. The five daily_card versions below were
#: reconstructed from the v1 file's own git history, so the migration lost nothing.
PINS_PATH = "harness/model_registry_pins.json"


def load_pins() -> dict:
    """path -> ordered list of authorized implementation versions. Reads v2; tolerates a v1 map."""
    if not os.path.exists(PINS_PATH):
        return {}
    d = json.load(open(PINS_PATH))
    if d.get("schema") == "model_registry_pins-v2":
        return {p: e["versions"] for p, e in d["sources"].items()}
    # legacy flat map: one unlabelled version per path
    return {p: [{"impl_version": 1, "sha256": s, "authorized_utc": None, "note": "legacy v1 pin"}]
            for p, s in d.items() if isinstance(s, str)}


def authorized_source_hash(path: str, sha256: str):
    """Which authorized implementation version is this sha? None if it was never authorized.

    This is what makes the ledger append-only in a load-bearing way rather than a decorative one: a
    forecast record that binds a SUPERSEDED generator sha is still correctly bound, and this resolves
    it instead of reporting drift."""
    for v in load_pins().get(path, []):
        if v["sha256"] == sha256:
            return v
    return None


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
    pins = load_pins()
    fails += _append_only_check(pins)
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
        if p in pins:
            cur = pins[p][-1]
            if cur["sha256"] != h:
                prior = authorized_source_hash(p, h)
                if prior:
                    fails.append(f"{mid}: {p} on disk is impl v{prior['impl_version']} "
                                 f"({h[:12]}), a SUPERSEDED implementation — the current authorized "
                                 f"version is v{cur['impl_version']} ({cur['sha256'][:12]}). A revert is "
                                 f"an authorized change like any other: append it, do not roll back to it.")
                else:
                    fails.append(f"{mid}: source hash drifted from pin: {p} {h[:12]} != "
                                 f"{cur['sha256'][:12]} (never an authorized version)")
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


def _append_only_check(pins: dict) -> list:
    """Internal consistency + a real append-only assertion against the committed ledger.

    Consistency is checked unconditionally. The history-shrink check compares against HEAD via git;
    if git is unavailable it is SKIPPED, and that is stated rather than silently passing."""
    fails = []
    for p, vs in pins.items():
        shas = [v["sha256"] for v in vs]
        if len(shas) != len(set(shas)):
            fails.append(f"pins {p}: a sha appears twice — versions must be distinct and ordered")
        if [v["impl_version"] for v in vs] != list(range(1, len(vs) + 1)):
            fails.append(f"pins {p}: impl_version must run 1..N in order")
    if os.path.exists(PINS_PATH):
        d = json.load(open(PINS_PATH))
        if d.get("schema") == "model_registry_pins-v2":
            for p, e in d["sources"].items():
                if e["current"] != e["versions"][-1]["sha256"]:
                    fails.append(f"pins {p}: `current` disagrees with versions[-1] — the ledger is incoherent")
    try:
        import subprocess
        head = subprocess.run(["git", "show", f"HEAD:{PINS_PATH}"], capture_output=True, text=True, timeout=20)
        if head.returncode == 0:
            old = json.loads(head.stdout)
            was = ({p: [v["sha256"] for v in e["versions"]] for p, e in old["sources"].items()}
                   if old.get("schema") == "model_registry_pins-v2"
                   else {p: [s] for p, s in old.items() if isinstance(s, str)})
            for p, shas in was.items():
                have = {v["sha256"] for v in pins.get(p, [])}
                lost = [s for s in shas if s not in have]
                if lost:
                    fails.append(f"pins {p}: APPEND-ONLY VIOLATION — {len(lost)} committed version(s) "
                                 f"dropped ({', '.join(s[:12] for s in lost)}). Registered forecasts bind "
                                 f"these; they may never be removed.")
    except Exception:
        pass  # no git / detached tree: the consistency checks above still ran
    return fails


def pin(path: str, note: str, record: str = None) -> int:
    """APPEND the current on-disk sha of `path` as a new authorized implementation version.

    There is deliberately no bulk re-pin: the destructive v1 behaviour was `--pin` with no argument,
    which rewrote every source's single pin at once and is how the daily_card history was lost."""
    if not os.path.exists(path):
        print(f"REFUSED: {path} does not exist")
        return 1
    if path not in {m["source"] for m in REGISTRY.values()}:
        print(f"REFUSED: {path} is not the source of any registered model_id")
        return 1
    h = sha(path)
    d = (json.load(open(PINS_PATH)) if os.path.exists(PINS_PATH)
         else {"schema": "model_registry_pins-v2", "policy": "APPEND-ONLY", "sources": {}})
    if d.get("schema") != "model_registry_pins-v2":
        print("REFUSED: pins file is not v2; migrate before appending")
        return 1
    e = d["sources"].setdefault(path, {"current": None, "versions": []})
    for v in e["versions"]:
        if v["sha256"] == h:
            print(f"REFUSED: {path} already registered as impl v{v['impl_version']} ({h[:12]}). "
                  f"Nothing to append — the disk contents are unchanged from an authorized version.")
            return 1
    if not note:
        print("REFUSED: --note is mandatory. A pin with no stated authority is indistinguishable "
              "from drift that someone blessed.")
        return 1
    e["versions"].append({"impl_version": len(e["versions"]) + 1, "sha256": h,
                          "authorized_utc": _utc_now(), "pin_commit": None,
                          "note": note, **({"record": record} if record else {})})
    e["current"] = h
    json.dump(d, open(PINS_PATH, "w"), indent=1)
    print(f"appended {path} impl v{e['versions'][-1]['impl_version']} = {h[:16]} "
          f"({len(e['versions'])} authorized versions retained)")
    return 0


def _utc_now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        i = sys.argv.index("--pin")
        if i + 1 >= len(sys.argv) or sys.argv[i + 1].startswith("--"):
            print("REFUSED: bulk re-pin is removed. Usage:\n"
                  "  --pin <source-path> --note '<what changed and under whose authority>' "
                  "[--record <path/to/audit.json>]\n"
                  "Pins are append-only: a new authorized build becomes a NEW implementation version; "
                  "the historical pin is never replaced.")
            raise SystemExit(1)
        _note = sys.argv[sys.argv.index("--note") + 1] if "--note" in sys.argv else None
        _rec = sys.argv[sys.argv.index("--record") + 1] if "--record" in sys.argv else None
        raise SystemExit(pin(sys.argv[i + 1], _note, _rec))
    raise SystemExit(selftest())
