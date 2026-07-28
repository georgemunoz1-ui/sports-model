#!/usr/bin/env python3
"""VERIFIER A — FROZEN_LINEAGE. What actually generated KSIM-2026-07-27 Phase 1.

This verifier answers exactly one question: **do the published lineage hashes still describe the
freeze commit?** It therefore reads every input out of git at the freeze commit, NOT from the
working tree, and it compares against the published values EXACTLY.

It will NEVER accept a successor hash. An earlier version enrolled successor hashes here so that a
legitimate engine edit would not fail; that was wrong. Enrolment inside this check would weaken the
provenance assertion into "the engine is either what produced Phase 1, or something we have decided
is close enough" -- which is not a provenance statement at all. Whether the CURRENT implementation
agrees with the frozen one is a different question, answered by VERIFIER B
(harness/test_parse_equivalence.py). B can never change what this file asserts.

    python3 harness/verify_lineage.py

Two canonical composite forms are emitted because the published one is imperfect and cannot be
changed without invalidating a hash already in the record:

  v1  ''.join(f'{pid}:{sha256}') over pids sorted as STRINGS, utf-8, NO separator. This is what was
      published. Ambiguous in principle -- concatenating variable-length fields with no delimiter is
      not injective -- but pid and sha256 are fixed-width here, so it is well defined for this
      manifest. Kept verbatim because the value is already cited in the addendum and a commit message.
  v2  '\\n'.join(f'{pid}  {sha256}') + '\\n'. Delimited, greppable. Use this for future manifests.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

#: The Phase-1 freeze. Every input below is read AT THIS COMMIT.
FREEZE_COMMIT = "6d4a7c0"

ARTIFACT = "data/mlb/props/simulated/2026-07-27_KSIM_phase1.json"
LOGS = "data/backfill/mlb/2026/pitcher_logs"
PITCHERS = "data/backfill/mlb/2026/pitchers.csv"
ENGINE = "engine/kprops.py"

#: published in docs/experiments/KSIM-2026-07-27_protocol_addendum.md. NEVER REWRITTEN.
PUBLISHED = {
    "kprops_py": "72a30c2650b6c4dc6b2b6c2f8a57f1848b1e139909cf0ad7b0120441f7411b56",
    "pitchers_csv": "a350ff454f247019e56bd39c6a6e2d393f0ffc5999cb079fb88be55a5e98d6a7",
    "composite_v1": "806e5cd2f0a7964900b421069b1bfe596ccc71e885dfa6bb30fb0a55bcd53f20",
    "phase1": "7f827fd0014e5835ec3bf3572bbe1ff36dce452d5e0a55b735d04fe665c12d2f",
}


def blob(path: str) -> bytes:
    """The file's bytes AT THE FREEZE COMMIT. Never the working tree."""
    r = subprocess.run(["git", "show", f"{FREEZE_COMMIT}:{path}"], capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"cannot read {path} at {FREEZE_COMMIT}: {r.stderr.decode()[:200]}")
    return r.stdout


def sha256_blob(path: str) -> str:
    return hashlib.sha256(blob(path)).hexdigest()


def log_hashes() -> dict[str, str]:
    """The 23 pitcher logs the frozen board used, keyed by pitcher_id, read at the freeze commit."""
    art = json.loads(blob(ARTIFACT))
    pids = sorted({r["pitcher_id"] for r in art["rows"]})  # STRING sort, as published
    return {pid: sha256_blob(f"{LOGS}/{pid}.txt") for pid in pids}


def composite_v1(logs: dict[str, str]) -> str:
    return hashlib.sha256("".join(f"{k}:{v}" for k, v in sorted(logs.items())).encode()).hexdigest()


def composite_v2(logs: dict[str, str]) -> str:
    return hashlib.sha256(("\n".join(f"{k}  {v}" for k, v in sorted(logs.items())) + "\n").encode()).hexdigest()


def main() -> int:
    logs = log_hashes()
    got = {
        "phase1": sha256_blob(ARTIFACT),
        "kprops_py": sha256_blob(ENGINE),
        "pitchers_csv": sha256_blob(PITCHERS),
        "composite_v1": composite_v1(logs),
    }
    print("VERIFIER A - FROZEN_LINEAGE")
    print(f"all inputs read from git at {FREEZE_COMMIT}; successor hashes are NEVER accepted here")
    print(f"python {sys.version.split()[0]}   logs hashed: {len(logs)}")
    print(f"{'item':<16}{'status':<8}{'sha256'}")
    fails = 0
    for k, v in got.items():
        ok = v == PUBLISHED[k]
        fails += (not ok)
        print(f"{k:<16}{'OK' if ok else 'FAIL':<8}{v}")
        if not ok:
            print(f"{'':<24}published {PUBLISHED[k]}")
    print(f"{'composite_v2':<16}{'-':<8}{composite_v2(logs)}   (delimited form, for future manifests)")
    print()
    if fails:
        print(f"FAIL - {fails} item(s) differ. The freeze commit no longer matches what was published; "
              "the provenance record is broken.")
    else:
        print("VERIFIED - the published hashes describe the freeze commit exactly.")
        print("NOTE: this says nothing about the CURRENT engine. For that, run VERIFIER B: "
              "python3 harness/test_parse_equivalence.py")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
