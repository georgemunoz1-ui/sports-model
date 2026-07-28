#!/usr/bin/env python3
"""Prove that the 2026-07-28 kprops._parse rewrite is a no-op on the frozen KSIM inputs.

Why this exists. `engine/kprops.py` is one of the four hashes published in the KSIM-2026-07-27
lineage manifest. Editing it necessarily breaks that hash, and the published value must never be
rewritten -- it records what produced the frozen board. So the change has to be justified instead:
this test reconstructs the freeze-time parser straight out of git and shows the new one agrees.

Two claims, both mechanical:
  1. `_parse` returns byte-identical output on EVERY pitcher log currently on disk.
  2. Every frozen Phase-1 `E_K` and `gs` reproduces at the precision the artifact stores.

Claim 1 is the strong one: it covers all 310 logs, not just the 23 in the cohort.

    python3 harness/test_parse_equivalence.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "engine"))

FREEZE_COMMIT = "6d4a7c0"  # the Phase-1 freeze
ARTIFACT = "data/mlb/props/simulated/2026-07-27_KSIM_phase1.json"


def freeze_time_parse():
    """Pull the freeze-time _parse out of git rather than pasting a copy that could drift."""
    src = subprocess.run(["git", "show", f"{FREEZE_COMMIT}:engine/kprops.py"],
                         capture_output=True, text=True, check=True).stdout
    m = re.search(r"def _parse\(path\):\n(?:.*\n)*?    rows\.sort\(\); return rows", src)
    if not m:
        raise SystemExit(f"could not recover _parse from {FREEZE_COMMIT}")
    ns: dict = {}
    exec(m.group(0), ns)
    return ns["_parse"]


def main() -> int:
    import kprops

    old = freeze_time_parse()
    fails = []

    logs = [f for f in sorted(os.listdir(kprops.LOGS))
            if f.endswith(".txt") and f[0] not in "_." and not f.startswith("README")]
    for f in logs:
        p = os.path.join(kprops.LOGS, f)
        if old(p) != kprops._parse(p):
            fails.append(f"_parse differs on {f}")
    print(f"claim 1: _parse identical on {len(logs)} logs, {len([x for x in fails])} differ")

    art = json.load(open(ARTIFACT))
    ids = kprops._ids()
    n_ok = 0
    for r in art["rows"]:
        got = kprops.proj(r["pitcher"], ids)
        if got is None:
            fails.append(f"proj() returned None for {r['pitcher']}")
            continue
        ek, gs = got
        if round(ek, 3) != r["E_K"] or gs != r["gs"]:
            fails.append(f"{r['pitcher']}: E_K {round(ek,3)} vs frozen {r['E_K']}, gs {gs} vs {r['gs']}")
        else:
            n_ok += 1
    print(f"claim 2: {n_ok}/{len(art['rows'])} frozen E_K/gs reproduced at stored precision")

    # The new parser must also actually handle width 8, or the fix is untested.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write("2026-07-21|TOR|5.0|2|7|1|22|1\n")   # date|opp|IP|ER|SO|BB|TBF|GS
        tmp = fh.name
    got = kprops._parse(tmp)
    os.unlink(tmp)
    if got != [("2026-07-21", 7.0, 22.0, True)]:
        fails.append(f"width-8 layout parsed wrong: {got}")
    else:
        print("claim 3: width-8 forward layout parses to (date, SO=7, TBF=22, start=True)")

    # And an unknown width must raise rather than guess.
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write("2026-07-21|5.0|2\n")
        tmp = fh.name
    try:
        kprops._parse(tmp)
        fails.append("unknown width did not raise")
    except ValueError:
        print("claim 4: unknown width raises ValueError instead of silently skipping")
    finally:
        os.unlink(tmp)

    if fails:
        print(f"\nFAIL - {len(fails)} problem(s)")
        for f in fails[:10]:
            print("  " + f)
        return 1
    print("\nparse equivalence: PASS - the rewrite is a no-op on every input on disk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
