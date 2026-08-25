#!/usr/bin/env python3
"""Falsification battery for the forecast/grade registries — the ten owner-listed conditions,
each proven to FAIL. All fixtures are synthetic and in-memory/tempdir; real registries untouched.
"""

from __future__ import annotations

MODULE_ID = "test_forecast_registry"

import copy
import json
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "harness"))

import forecast_registry as FR

REG = {
    "m.seq":   {"source": "harness/daily_card.py", "hfa": 1.005, "seed": 722, "sims_per_game": 30000,
                "rng_policy": "sequential_slate_order"},
    "m.reset": {"source": "harness/daily_card.py", "hfa": 1.005, "seed": 722, "sims_per_game": 30000,
                "rng_policy": "per_game_reset_seed722"},
}


def ok_rec(fid="F1", cohort="DIAGNOSTIC_PROSPECTIVE", **kw):
    r = {"forecast_id": fid, "cohort": cohort, "provenance_class": "TEST",
         "game_ref": "UNRESOLVED:AZ@PIT:2026-07-28", "slate_date": "2026-07-28", "market": "ML",
         "generated_at_utc": "2026-07-28T18:07:46Z", "archived_at_utc": "2026-07-28T18:18:07Z",
         "model_id": "m.reset", "rng_policy": "per_game_reset_seed722",
         "input_vintage": {"results_csv": None}, "dq_flags": ["TEST"],
         "promotion_eligible": False, "ledger_eligible": False, "diagnostic_grade_eligible": True,
         "provenance_limitations": "synthetic test record", "original_file_hash": None}
    r.update(kw)
    return r


results = []


def t(name, fired):
    results.append((name, fired))
    print(f"  {'ok ' if fired else 'FAIL'} {name}")


def V(fs, gs=()):
    return FR.validate_records(list(fs), list(gs), registry=REG)


def main() -> int:
    print("== falsification: each condition must FAIL ==")
    # 1. mutation of an archived forecast -> chain break
    with tempfile.TemporaryDirectory() as td:
        oF, oG, oH, oD = FR.FORECASTS, FR.GRADES, FR.HEAD, FR.DIR
        try:
            FR.DIR = td
            FR.FORECASTS = f"{td}/forecasts.jsonl"
            FR.GRADES = f"{td}/grades.jsonl"
            FR.HEAD = f"{td}/head.json"
            open(FR.FORECASTS, "w").write(json.dumps(ok_rec()) + "\n")
            FR._write_head()
            good = json.load(open(FR.HEAD))["chain"] == FR.chain_hash()
            ln = open(FR.FORECASTS).read().replace("DIAGNOSTIC_PROSPECTIVE", "PROMOTION_PROSPECTIVE")
            open(FR.FORECASTS, "w").write(ln)
            broken = json.load(open(FR.HEAD))["chain"] != FR.chain_hash()
        finally:
            FR.FORECASTS, FR.GRADES, FR.HEAD, FR.DIR = oF, oG, oH, oD
    t("1 mutation of archived forecast breaks the hash chain", good and broken)
    # 2. duplicate forecast ID
    t("2 duplicate forecast_id", any("duplicate" in x for x in V([ok_rec(), ok_rec()])))
    # 3. missing provenance status
    r = ok_rec(); del r["provenance_limitations"]
    t("3 missing provenance field", any("missing required" in x for x in V([r])))
    # 4. retrospective record marked prospective
    t("4 retrospective marked prospective",
      any("marked prospective" in x for x in V([ok_rec(cohort="RETROSPECTIVE_ARCHIVED", prospective=True)])))
    # 5. diagnostic record counted toward promotion gate
    t("5 diagnostic record promotion_eligible",
      any("promotion" in x for x in V([ok_rec(promotion_eligible=True)])))
    # 6. forecast automatically entering the betting ledger
    t("6 ledger_eligible forecast", any("ledger" in x for x in V([ok_rec(ledger_eligible=True)])))
    # 7. grade without a matching forecast
    t("7 orphan grade", any("no matching forecast" in x
                            for x in V([ok_rec()], [{"grade_id": "G1", "forecast_id": "NOPE"}])))
    # 8. result fields written into the forecast payload
    t("8 result field in payload",
      any("result field" in x for x in V([ok_rec(payload={"hw": 0.51, "result": "WIN"})])))
    # 9. fabricated original-file hash
    t("9 fabricated original_file_hash",
      any("fabricated" in x for x in V([ok_rec(original_file_hash="ab" * 32,
                                               artifact_ref={"path": "does/not/exist.json"})])))
    # 10. sequential and per-game-reset sharing one model ID
    t("10 one model_id, two rng policies",
      any("may not share one identity" in x
          for x in V([ok_rec(fid="A", model_id="m.seq", rng_policy="sequential_slate_order"),
                      ok_rec(fid="B", model_id="m.seq", rng_policy="per_game_reset_seed722")])))
    print("== positive ==")
    t("11 clean synthetic record validates", not V([ok_rec()]))
    t("12 real registries verify (chain + rules)", FR.verify() == 0)

    bad = [n for n, fired in results if not fired]
    if bad:
        print(f"\nforecast_registry tests: FAIL {bad}")
        return 1
    print(f"\nforecast_registry tests: PASS ({len(results)} checks: 10 falsifications fired)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
