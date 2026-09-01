#!/usr/bin/env python3
"""VERIFIER B — SUCCESSOR_EQUIVALENCE. Does the CURRENT engine agree with the FROZEN one?

This is a separate question from provenance, and it is deliberately kept in a separate file.
VERIFIER A (harness/verify_lineage.py) asserts what generated Phase 1 and never accepts a successor
hash. **Nothing here can change that assertion.** All this file does is record the successor hash and
the evidence for equivalence.

Six checks:

  1. UNROUNDED E[K] equivalence. The frozen engine is loaded as a whole module out of the freeze
     commit and run against the current one on identical inputs, comparing raw floats. Agreement
     after rounding to the artifact's 3 dp is only artifact reproduction; this is the stronger claim.
  2. `_parse` output identical on every log on disk.
  3. Explicit LAYOUT FIXTURES for every supported width, because the 310 logs on disk contain only
     widths 7 and 10 -- they do not exercise the newly added 8-field layout at all.
  4. Malformed / unknown widths must FAIL rather than be silently skipped.
  5. README_NOTE.txt is excluded from the log set.
  6. The ER/BB placeholder manifest is enforced.

    python3 harness/test_parse_equivalence.py
"""

from __future__ import annotations

MODULE_ID = "test_parse_equivalence"

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "engine"))

FREEZE_COMMIT = "6d4a7c0"
ARTIFACT = "data/mlb/props/simulated/2026-07-27_KSIM_phase1.json"
FROZEN_ENGINE_SHA = "72a30c2650b6c4dc6b2b6c2f8a57f1848b1e139909cf0ad7b0120441f7411b56"


def load_frozen_engine():
    """Load engine/kprops.py AS IT WAS at the freeze commit, as a real module.

    Not a regex-extracted function: the whole module, so proj()/_ids()/_parse() are the frozen
    versions and the comparison covers the actual projection path rather than one helper.
    """
    src = subprocess.run(["git", "show", f"{FREEZE_COMMIT}:engine/kprops.py"],
                         capture_output=True, check=True).stdout
    got = hashlib.sha256(src).hexdigest()
    if got != FROZEN_ENGINE_SHA:
        raise SystemExit(f"frozen engine blob hash {got} != published {FROZEN_ENGINE_SHA}")
    with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False) as fh:
        fh.write(src)
        path = fh.name
    spec = importlib.util.spec_from_file_location("kprops_frozen", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    os.unlink(path)
    # kprops derives BASE from __file__, which is the temp path here, so data lookups would resolve
    # against '/'. Repoint at the real tree: both engines must read the SAME inputs, or the
    # comparison is meaningless. Only these two path constants are touched — no logic is patched.
    mod.BASE = BASE
    mod.LOGS = os.path.join(BASE, "data/backfill/mlb/2026/pitcher_logs")
    return mod, got


def fixture(text: str):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write(text)
        return fh.name


def main() -> int:
    import kprops
    frozen, frozen_sha = load_frozen_engine()
    cur_sha = hashlib.sha256(open("engine/kprops.py", "rb").read()).hexdigest()
    fails: list[str] = []

    print("VERIFIER B - SUCCESSOR_EQUIVALENCE")
    print(f"frozen  engine ({FREEZE_COMMIT}): {frozen_sha}")
    print(f"current engine              : {cur_sha}")
    print(f"successor: {'YES' if cur_sha != frozen_sha else 'NO - identical'}")
    print("this file records equivalence evidence; it does NOT alter the Phase-1 provenance statement\n")

    # --- 1. unrounded E[K] equivalence, whole-module ---
    art = json.load(open(ARTIFACT))
    ids_new, ids_old = kprops._ids(), frozen._ids()
    n_exact = 0
    worst = 0.0
    for r in art["rows"]:
        a = frozen.proj(r["pitcher"], ids_old)
        b = kprops.proj(r["pitcher"], ids_new)
        if a is None or b is None:
            fails.append(f"proj() None for {r['pitcher']} (frozen={a}, current={b})")
            continue
        if a[0] != b[0] or a[1] != b[1]:
            worst = max(worst, abs(a[0] - b[0]))
            fails.append(f"{r['pitcher']}: UNROUNDED {a[0]!r} vs {b[0]!r}, gs {a[1]} vs {b[1]}")
        else:
            n_exact += 1
    print(f"1. unrounded E[K]/gs bit-identical on {n_exact}/{len(art['rows'])} frozen rows"
          + (f" (worst delta {worst:.3e})" if worst else " (exact float equality, not rounded)"))

    # --- 2. _parse over every real log ---
    logs = [f for f in sorted(os.listdir(kprops.LOGS))
            if f.endswith(".txt") and f[0] not in "_." and not f.startswith("README")]
    n_diff = sum(1 for f in logs
                 if frozen._parse(os.path.join(kprops.LOGS, f)) != kprops._parse(os.path.join(kprops.LOGS, f)))
    if n_diff:
        fails.append(f"_parse differs on {n_diff} logs")
    print(f"2. _parse identical on {len(logs)} logs on disk, {n_diff} differ")

    # --- 3. layout fixtures: disk holds only widths 7 and 10, so 8 is otherwise UNTESTED ---
    LAYOUTS = [
        ("width 7  date|IP|ER|SO|BB|TBF|GS",
         "2026-07-21|5.0|2|7|1|22|1\n", [("2026-07-21", 7.0, 22.0, True)]),
        ("width 8  date|opp|IP|ER|SO|BB|TBF|GS",
         "2026-07-21|TOR|5.0|2|7|1|22|1\n", [("2026-07-21", 7.0, 22.0, True)]),
        ("width 10 wide (SO=6 TBF=8 GS=9)",
         "2026-07-21|x|y|z|5.0|2|7|1|22|1\n", [("2026-07-21", 7.0, 22.0, True)]),
        ("width 7  relief row (GS=0)",
         "2026-07-21|1.0|0|2|0|5|0\n", [("2026-07-21", 2.0, 5.0, False)]),
        ("width 8  relief row (GS=0)",
         "2026-07-21|TOR|1.0|0|2|0|5|0\n", [("2026-07-21", 2.0, 5.0, False)]),
    ]
    on_disk = set()
    for f in logs:
        for ln in open(os.path.join(kprops.LOGS, f)):
            if ln.strip():
                on_disk.add(len(ln.strip().split("|")))
    print(f"3. layout fixtures (widths present on disk: {sorted(on_disk)} -- "
          f"width 8 is NOT among them, so only these fixtures test it)")
    for label, text, want in LAYOUTS:
        p = fixture(text)
        try:
            got = kprops._parse(p)
            ok = got == want
            if not ok:
                fails.append(f"{label}: got {got}, want {want}")
            print(f"   {'ok ' if ok else 'FAIL'} {label}")
        finally:
            os.unlink(p)

    # --- 4. malformed widths must fail loudly ---
    print("4. malformed widths must raise, not be silently skipped")
    for label, text in [("width 3", "2026-07-21|5.0|2\n"),
                        ("width 6", "2026-07-21|5.0|2|7|1|22\n"),
                        ("width 9", "2026-07-21|a|b|c|d|e|f|g|h\n"),
                        ("width 11", "|".join(["x"] * 11) + "\n")]:
        p = fixture(text)
        try:
            kprops._parse(p)
            fails.append(f"{label} did not raise")
            print(f"   FAIL {label} silently accepted")
        except ValueError:
            print(f"   ok  {label} raises ValueError")
        finally:
            os.unlink(p)

    # --- 5. README_NOTE.txt exclusion ---
    note = os.path.join(kprops.LOGS, "README_NOTE.txt")
    excluded = os.path.exists(note) and "README_NOTE.txt" not in logs
    if os.path.exists(note) and not excluded:
        fails.append("README_NOTE.txt is being treated as a pitcher log")
    print(f"5. README_NOTE.txt present={os.path.exists(note)}, excluded from log set={excluded}")
    if os.path.exists(note):
        try:
            kprops._parse(note)
            fails.append("README_NOTE.txt parsed as a log instead of raising")
            print("   FAIL README_NOTE.txt parsed without error — exclusion is the ONLY thing protecting it")
        except ValueError:
            print("   ok  README_NOTE.txt would raise if ever passed to _parse (belt and braces)")

    # --- 6. placeholder manifest enforcement ---
    pm = json.load(open(os.path.join(kprops.LOGS, "_placeholders.json")))
    drift = 0
    for r in pm["rows"]:
        got = None
        for ln in open(os.path.join(kprops.LOGS, f"{r['pitcher_id']}.txt")):
            p = ln.strip().split("|")
            if p and p[0] == r["date"]:
                got = p
                break
        # 2026-09-01: check the fields EACH ROW declares placeholder (field_indices), not a
        # hardcoded ER+BB pair — the lancebroz batch placeholds ER only; its BB is genuine.
        if got is None or any(float(got[i]) != 0.0 for i in r.get("field_indices", [2, 4])):
            drift += 1
            fails.append(f"placeholder drift: {r['pitcher_id']} {r['date']}")
    print(f"6. ER/BB placeholder manifest: {len(pm['rows'])} rows, {drift} drift")

    if fails:
        print(f"\nFAIL - {len(fails)} problem(s)")
        for f in fails[:12]:
            print("  " + f)
        return 1
    print("\nsuccessor equivalence: PASS")
    print("SCOPE: this shows the current implementation reproduces the frozen one on these inputs and "
          "fixtures. It does NOT re-authorise the frozen lineage — see VERIFIER A.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
