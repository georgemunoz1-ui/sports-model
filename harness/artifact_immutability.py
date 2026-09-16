#!/usr/bin/env python3
"""Registered forecast artifacts must still hash to what was registered. Enforced, not assumed.

WHY (2026-08-17): an adversarial verification pass found, by mtime forensics, that
cards/2026-08-17_card.json — the REGISTERED v1 cohort artifact — was written on disk during the v3
build, 25.9 ms after card_v3.json. Root cause: harness/daily_card.py:120 hardcodes its output to
`cards/{date}_card.json` with no version suffix and no write guard, so ANY card build for a date
clobbers the v1 arm for that date. The content survived on that occasion because the operator kept a
pre-build copy and restored it, and git confirms the blob never changed — but immutability held by
discipline rather than by enforcement, and a build that failed to restore would silently destroy a
registered arm while the forecast records still pointed at its path.

This module closes that gap: for every forecast record carrying artifact_ref.path +
original_file_hash, recompute the file's sha256 and compare. A mismatch is a GATE FAILURE — it means
a registered artifact was rewritten and the cohort it represents can no longer be trusted.

Known, enumerated exception (documented 2026-08-16 in the evidence-binding correction record): 13
RETRO grade records bind data/mlb/box/2026-07-26_and_07-28_extract.json to the sha256 of its
UPSTREAM paste file. That is a path/hash MISPAIRING in an append-only ledger, not a rewritten
artifact, and it lives in grades.jsonl which this module does not read. Forecast-side RETRO records
carry original_file_hash: null and are skipped as unbound rather than counted as clean.

Usage: python3 harness/artifact_immutability.py [--gate] [--selftest]
"""
from __future__ import annotations

MODULE_ID = "artifact_immutability"
import hashlib, json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
FORECASTS = "data/mlb/forecasts/forecasts.jsonl"


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check(forecasts_path=FORECASTS):
    if not os.path.exists(forecasts_path):
        return {"checked": 0, "clean": 0, "mismatches": [], "missing": [], "unbound": 0}
    seen, mismatches, missing, unbound, clean = {}, [], [], 0, 0
    for line in open(forecasts_path):
        if not line.strip():
            continue
        r = json.loads(line)
        path = (r.get("artifact_ref") or {}).get("path")
        want = r.get("original_file_hash")
        if not path or not want:
            unbound += 1
            continue
        # one filesystem read per distinct (path, expected) pair; many records share an artifact
        key = (path, want)
        if key in seen:
            if seen[key] == "MISMATCH":
                mismatches.append(f'{r["forecast_id"]}: {path}')
            elif seen[key] == "MISSING":
                missing.append(f'{r["forecast_id"]}: {path}')
            else:
                clean += 1
            continue
        if not os.path.exists(path):
            seen[key] = "MISSING"
            missing.append(f'{r["forecast_id"]}: {path}')
            continue
        actual = _sha(path)
        if actual != want:
            seen[key] = "MISMATCH"
            mismatches.append(f'{r["forecast_id"]}: {path} registered {want[:16]} but disk has {actual[:16]}')
        else:
            seen[key] = "OK"
            clean += 1
    return {"checked": clean + len(mismatches) + len(missing), "clean": clean,
            "mismatches": mismatches, "missing": missing, "unbound": unbound,
            "distinct_artifacts": len(seen)}


def selftest():
    import tempfile
    fails = []
    live = check()
    if live["mismatches"]:
        fails.append(f"live registry has {len(live['mismatches'])} rewritten artifact(s): {live['mismatches'][:2]}")
    with tempfile.TemporaryDirectory() as td:
        art = os.path.join(td, "card.json")
        open(art, "w").write('{"rows":[1]}')
        good = _sha(art)
        fp = os.path.join(td, "f.jsonl")
        with open(fp, "w") as f:
            f.write(json.dumps({"forecast_id": "A", "artifact_ref": {"path": art},
                                "original_file_hash": good}) + "\n")
        if check(fp)["clean"] != 1:
            fails.append("matching artifact not counted clean")
        # falsification: rewrite the artifact -> must be caught
        open(art, "w").write('{"rows":[1,2]}')
        if not check(fp)["mismatches"]:
            fails.append("REWRITTEN artifact was NOT caught — the gate is inert")
        # falsification: delete it -> must be reported missing, not silently clean
        os.remove(art)
        r = check(fp)
        if not r["missing"] or r["clean"]:
            fails.append("deleted artifact was not reported missing")
    if fails:
        print("artifact_immutability selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print(f"artifact_immutability selftest: PASS (rewritten and deleted artifacts both caught; "
          f"live: {live['clean']}/{live['checked']} bound records match, {live['unbound']} unbound)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    r = check()
    print(f"registered artifacts: {r['clean']}/{r['checked']} records match their registered hash "
          f"({r['distinct_artifacts']} distinct files, {r['unbound']} records carry no binding)")
    for m in r["mismatches"][:10]:
        print("  ! REWRITTEN " + m)
    for m in r["missing"][:10]:
        print("  ! MISSING   " + m)
    raise SystemExit(1 if ("--gate" in sys.argv and (r["mismatches"] or r["missing"])) else 0)
