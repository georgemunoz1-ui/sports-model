#!/usr/bin/env python3
"""P1B firewall test battery: TEN negative fixtures prove each gate CAN fail; FIVE positive tests
prove the build is deterministic, ordered, non-mutating and market-free. All fixtures are synthetic
or in-memory deepcopies — no repo data is modified.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "harness"))

import build_ml_asof as B
import model_registry as MR

results = []


def t(name, ok, detail=""):
    results.append((name, ok))
    print(f"  {'ok ' if ok else 'FAIL'} {name}{(' — ' + detail) if detail and not ok else ''}")


def main() -> int:
    print("building baseline (in memory, twice, for fixtures + determinism)...")
    rows1, exc1 = B.build()
    rows2, exc2 = B.build()
    n_finals = len(rows1)

    print("== NEGATIVE FIXTURES (each gate must fire) ==")
    # 1. future-dated observation
    r = copy.deepcopy(rows1[:200]); bad = copy.deepcopy(r[150])
    bad["team"]["home"]["last_obs_date"] = "2027-01-01"
    v = B.validate([bad], 1, [])
    t("1 future-dated observation -> FAIL", any("FUTURE-DATED" in x for x in v))
    # 2. same-day observation without timestamp proof
    bad = copy.deepcopy(r[150]); bad["team"]["away"]["last_obs_date"] = bad["slate_date"]
    v = B.validate([bad], 1, [])
    t("2 same-day observation lacking timestamps -> FAIL", any("same-day" in x for x in v))
    # 3. unknown record width
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "999999.txt")
        open(p, "w").write("2026-05-01|5.0|2|4|1\n")  # width 5
        old = B.LOGS
        try:
            B.LOGS = td
            try:
                B.log_rows("999999"); fired = False
            except ValueError:
                fired = True
        finally:
            B.LOGS = old
    t("3 unknown record width -> raises", fired)
    # 4. unmanifested/unflagged placeholder
    syn = copy.deepcopy(r[150])
    syn["sp"]["home"] = {"pid": "678022", "name": "X", "era": 3.0, "gs": 5, "k_pct": 20.0, "bb_pct": 5.0,
                         "last_start_date": "2026-07-21"}
    syn["slate_date"] = "2026-07-25"
    syn["flags"]["sp_flags"]["home"] = {"placeholder_in_window": False}
    v = B.validate([syn], 1, [], ph_map={"678022": {"2026-07-21"}})
    t("4 placeholder in window but UNFLAGGED -> FAIL", any("UNFLAGGED" in x for x in v))
    # 5. duplicate gamePk
    v = B.validate([r[0], copy.deepcopy(r[0])], 2, [])
    t("5 duplicate gamePk -> FAIL", any("duplicate" in x for x in v))
    # 6. missing source/vintage hash in manifest
    m = json.load(open("data/mlb/ml_asof/manifest.json")); m2 = dict(m); del m2["vintage_sha256"]
    m3 = dict(m); m3["source_hashes"] = {k: v_ for k, v_ in m["source_hashes"].items() if k != "results"}
    t("6 missing vintage/source hash -> FAIL",
      bool(B.manifest_check(m2)) and bool(B.manifest_check(m3)) and not B.manifest_check(m))
    # 7. unresolved starter presented as executable
    bad = copy.deepcopy(next(x for x in rows1 if "UNRESOLVED" in str(x["starter_status"])))
    bad["executable_eligible"] = True
    v = B.validate([bad], 1, [{"gamePk": bad["gamePk"]}])
    t("7 unresolved starter marked executable -> FAIL", any("executable" in x for x in v))
    # 8. model source-hash mismatch (registry pin drift)
    with tempfile.TemporaryDirectory() as td:
        pp = os.path.join(td, "pins.json")
        pins = json.load(open(MR.PINS_PATH)); pins["harness/daily_card.py"] = "0" * 64
        json.dump(pins, open(pp, "w"))
        old = MR.PINS_PATH
        try:
            MR.PINS_PATH = pp
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = MR.selftest()
        finally:
            MR.PINS_PATH = old
    t("8 model_id/source-hash mismatch -> registry FAIL", rc == 1)
    # 9. HFA mismatch under one model ID
    old_hfa = MR.REGISTRY["ml.v13_1.hfa1005.card.s722n30000"]["hfa"]
    try:
        MR.REGISTRY["ml.v13_1.hfa1005.card.s722n30000"]["hfa"] = 1.06
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = MR.selftest()
    finally:
        MR.REGISTRY["ml.v13_1.hfa1005.card.s722n30000"]["hfa"] = old_hfa
    t("9 HFA mismatch under one model_id -> registry FAIL", rc == 1)
    # 10. silent exclusion without an exclusion record
    v = B.validate(rows1[:-1], n_finals, exc1)
    t("10 dropped row without reconciliation -> FAIL", any("silent exclusion" in x for x in v))

    print("== POSITIVE TESTS ==")
    b1, b2 = B.dataset_bytes(rows1), B.dataset_bytes(rows2)
    t("11 deterministic rebuild (two builds byte-identical)", b1 == b2)
    t("12 identical hashes from identical inputs",
      hashlib.sha256(b1).hexdigest() == hashlib.sha256(b2).hexdigest())
    keys = [(x["slate_date"], x["gamePk"]) for x in rows1]
    t("13 stable row ordering (slate_date, gamePk)", keys == sorted(keys))
    pre = {p: B.sha(p) for p in B.SOURCES.values()}
    B.build()
    t("14 zero mutation of source data", all(B.sha(p) == h for p, h in pre.items()))
    t("15 no market odds in predictive features",
      not B.assert_no_market_fields(rows1) and not any("market token" in x for x in B.validate(rows1, n_finals, exc1)))

    bad = [n for n, ok in results if not ok]
    if bad:
        print(f"\nml_firewall tests: FAIL ({len(bad)}): {bad}")
        return 1
    print(f"\nml_firewall tests: PASS ({len(results)} checks: 10 negative fixtures fired, 5 positives hold)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
