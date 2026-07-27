#!/usr/bin/env python3
"""Recompute the KSIM-2026-07-27 input-lineage hashes from the files on disk.

Exists so the composite hash published in the protocol addendum is REPRODUCIBLE rather than
asserted. Run it and compare; it recomputes from the pitcher logs the frozen board actually
used, in a documented canonical order.

    python3 harness/verify_lineage.py

Two canonical forms are emitted because the published one is imperfect and cannot be changed
without invalidating a hash already in the record:

  v1  ''.join(f'{pid}:{sha256}')  over pids sorted as STRINGS, utf-8, NO separator.
      This is what was published. It is ambiguous in principle -- concatenating
      variable-length fields with no delimiter is not injective in general -- but pid and
      sha256 are both fixed-width here, so it is well defined for this manifest. Kept
      verbatim because the value is already cited in the addendum and a commit message.

  v2  '\\n'.join(f'{pid}  {sha256}') + '\\n'.  Delimited, greppable, diffable. Use this for
      any future manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACT = os.path.join(BASE, "data/mlb/props/simulated/2026-07-27_KSIM_phase1.json")
LOGS = os.path.join(BASE, "data/backfill/mlb/2026/pitcher_logs")
PITCHERS = os.path.join(BASE, "data/backfill/mlb/2026/pitchers.csv")
ENGINE = os.path.join(BASE, "engine/kprops.py")

#: published in docs/experiments/KSIM-2026-07-27_protocol_addendum.md
PUBLISHED = {
    "kprops_py": "72a30c2650b6c4dc6b2b6c2f8a57f1848b1e139909cf0ad7b0120441f7411b56",
    "pitchers_csv": "a350ff454f247019e56bd39c6a6e2d393f0ffc5999cb079fb88be55a5e98d6a7",
    "composite_v1": "806e5cd2f0a7964900b421069b1bfe596ccc71e885dfa6bb30fb0a55bcd53f20",
    "phase1": "7f827fd0014e5835ec3bf3572bbe1ff36dce452d5e0a55b735d04fe665c12d2f",
}


def sha256_file(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def log_hashes() -> dict[str, str]:
    """The 23 pitcher logs the frozen board actually used, keyed by pitcher_id."""
    art = json.load(open(ARTIFACT))
    pids = sorted({r["pitcher_id"] for r in art["rows"]})  # STRING sort, as published
    return {pid: sha256_file(os.path.join(LOGS, f"{pid}.txt")) for pid in pids}


def composite_v1(logs: dict[str, str]) -> str:
    return hashlib.sha256("".join(f"{k}:{v}" for k, v in sorted(logs.items())).encode()).hexdigest()


def composite_v2(logs: dict[str, str]) -> str:
    return hashlib.sha256(("\n".join(f"{k}  {v}" for k, v in sorted(logs.items())) + "\n").encode()).hexdigest()


def main() -> int:
    logs = log_hashes()
    got = {
        "phase1": sha256_file(ARTIFACT),
        "kprops_py": sha256_file(ENGINE),
        "pitchers_csv": sha256_file(PITCHERS),
        "composite_v1": composite_v1(logs),
    }
    print(f"python {sys.version.split()[0]}   logs hashed: {len(logs)}")
    print(f"{'item':<16}{'status':<8}{'sha256'}")
    fails = 0
    for k, v in got.items():
        ok = v == PUBLISHED[k]
        fails += (not ok)
        print(f"{k:<16}{'OK' if ok else 'FAIL':<8}{v}")
        if not ok:
            print(f"{'':<24}expected {PUBLISHED[k]}")
    print(f"{'composite_v2':<16}{'-':<8}{composite_v2(logs)}   (delimited form, for future manifests)")
    print()
    print("VERIFIED - lineage reproduces the published hashes" if not fails
          else f"MISMATCH - {fails} item(s) differ; the lineage has moved since the freeze")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
