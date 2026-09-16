#!/usr/bin/env python3
"""VERIFIER B — SUCCESSOR_EQUIVALENCE. Does the CURRENT engine agree with the FROZEN one?

This is a separate question from provenance, and it is deliberately kept in a separate file.
VERIFIER A (harness/verify_lineage.py) asserts what generated Phase 1 and never accepts a successor
hash. **Nothing here can change that assertion.** All this file does is record successor-code
compatibility against the exact frozen input corpus plus current-format parser safety.

WHY THE FROZEN CORPUS MATTERS. The old verifier ran both engines against the mutable CURRENT pitcher
logs. Once official forward rows were appended/backfilled, a changed projection was inevitable even
when the engine code remained semantically equivalent. That mixed two questions: "did the code
change behavior?" and "did the input corpus improve?". Successor equivalence is a code-lineage test,
so projection equivalence must use the exact input files visible at the freeze commit. Operational
parser safety is tested separately on the current logs and current 8-field forward format.

Checks:
  1. Materialize the frozen pitcher-id map and pitcher-log corpus from FREEZE_COMMIT.
  2. UNROUNDED E[K] equivalence: frozen and current engines run on those identical frozen inputs.
  3. `_parse` output identical between engines on every frozen log.
  4. Current parser successfully parses every current on-disk log, including real 8-field rows.
  5. Explicit layout fixtures for all supported widths (7, 8, 10).
  6. Malformed / unknown widths must FAIL rather than be silently skipped.
  7. README_NOTE.txt is excluded and the current placeholder manifest is enforced.

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
LOG_REL = "data/backfill/mlb/2026/pitcher_logs"
PITCHERS_REL = "data/backfill/mlb/2026/pitchers.csv"


def _git_bytes(path: str) -> bytes:
    r = subprocess.run(["git", "show", f"{FREEZE_COMMIT}:{path}"], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"cannot materialize frozen input {path}: {r.stderr.decode(errors='replace')[:200]}")
    return r.stdout


def materialize_frozen_inputs(tmp_root: str) -> str:
    """Write exactly the pitcher map/log files visible at the freeze commit into tmp_root."""
    pitchers_path = os.path.join(tmp_root, PITCHERS_REL)
    os.makedirs(os.path.dirname(pitchers_path), exist_ok=True)
    with open(pitchers_path, "wb") as fh:
        fh.write(_git_bytes(PITCHERS_REL))

    ls = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", FREEZE_COMMIT, LOG_REL],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    n = 0
    for rel in ls:
        base = os.path.basename(rel)
        if not rel.endswith(".txt") or base.startswith(("_", ".", "README")):
            continue
        out = os.path.join(tmp_root, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as fh:
            fh.write(_git_bytes(rel))
        n += 1
    if n == 0:
        raise RuntimeError("frozen input materialization produced zero pitcher logs")
    return os.path.join(tmp_root, LOG_REL)


def load_frozen_engine():
    """Load engine/kprops.py AS IT WAS at the freeze commit, as a real module."""
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

    cur_base, cur_logs = kprops.BASE, kprops.LOGS
    with tempfile.TemporaryDirectory(prefix="kprops-freeze-") as td:
        frozen_logs = materialize_frozen_inputs(td)
        # Both modules read the SAME frozen pitcher map and log bytes for code-equivalence checks.
        kprops.BASE = td
        kprops.LOGS = frozen_logs
        frozen.BASE = td
        frozen.LOGS = frozen_logs

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
                fails.append(f"{r['pitcher']}: FROZEN-CORPUS UNROUNDED {a[0]!r} vs {b[0]!r}, "
                             f"gs {a[1]} vs {b[1]}")
            else:
                n_exact += 1
        print(f"1. frozen-corpus unrounded E[K]/gs bit-identical on {n_exact}/{len(art['rows'])} rows"
              + (f" (worst delta {worst:.3e})" if worst else " (exact float equality)"))

        frozen_files = [f for f in sorted(os.listdir(frozen_logs))
                        if f.endswith(".txt") and f[0] not in "_." and not f.startswith("README")]
        n_diff = sum(1 for f in frozen_files
                     if frozen._parse(os.path.join(frozen_logs, f)) !=
                        kprops._parse(os.path.join(frozen_logs, f)))
        if n_diff:
            fails.append(f"_parse differs on {n_diff} frozen logs")
        print(f"2. _parse identical on {len(frozen_files)} frozen logs, {n_diff} differ")

    # Restore the live tree before current-format safety checks.
    kprops.BASE, kprops.LOGS = cur_base, cur_logs
    logs = [f for f in sorted(os.listdir(kprops.LOGS))
            if f.endswith(".txt") and f[0] not in "_." and not f.startswith("README")]
    on_disk = set()
    current_parse_fail = []
    for f in logs:
        path = os.path.join(kprops.LOGS, f)
        try:
            kprops._parse(path)
        except Exception as e:
            current_parse_fail.append(f"{f}: {e}")
        for ln in open(path):
            if ln.strip():
                on_disk.add(len(ln.strip().split("|")))
    if current_parse_fail:
        fails.extend(f"current log parse failure: {x}" for x in current_parse_fail[:10])
    print(f"3. current parser accepted {len(logs)}/{len(logs)} live logs; widths present={sorted(on_disk)}")
    if 8 not in on_disk:
        fails.append("current corpus has no 8-field forward rows; official forward-format path is unexercised")

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
    print("4. explicit current-layout fixtures")
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

    print("5. malformed widths must raise, not be silently skipped")
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

    note = os.path.join(kprops.LOGS, "README_NOTE.txt")
    excluded = os.path.exists(note) and "README_NOTE.txt" not in logs
    if os.path.exists(note) and not excluded:
        fails.append("README_NOTE.txt is being treated as a pitcher log")
    print(f"6. README_NOTE.txt present={os.path.exists(note)}, excluded from log set={excluded}")
    if os.path.exists(note):
        try:
            kprops._parse(note)
            fails.append("README_NOTE.txt parsed as a log instead of raising")
        except ValueError:
            pass

    pm = json.load(open(os.path.join(kprops.LOGS, "_placeholders.json")))
    drift = 0
    for r in pm["rows"]:
        got = None
        for ln in open(os.path.join(kprops.LOGS, f"{r['pitcher_id']}.txt")):
            p = ln.strip().split("|")
            if p and p[0] == r["date"]:
                got = p
                break
        if got is None or any(float(got[i]) != 0.0 for i in r.get("field_indices", [2, 4])):
            drift += 1
            fails.append(f"placeholder drift: {r['pitcher_id']} {r['date']}")
    print(f"7. ER/BB placeholder manifest: {len(pm['rows'])} rows, {drift} drift")

    if fails:
        print(f"\nFAIL - {len(fails)} problem(s)")
        for f in fails[:12]:
            print("  " + f)
        return 1
    print("\nsuccessor equivalence: PASS")
    print("SCOPE: current code reproduces the frozen engine on the exact frozen input corpus, while "
          "the current parser separately accepts the current forward-format corpus. This does NOT "
          "re-authorise the frozen lineage — see VERIFIER A.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
