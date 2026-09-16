#!/usr/bin/env python3
"""GRADE LEDGER — the per-game ledger is canonical; every summary is REBUILT from it.

OWNER RULING 2026-08-23, ordered BEFORE item 2:
    "A baseline-offset model cannot be evaluated reliably if a re-settlement can replace a complete
     cohort with one new row."
    * Append-only per-game grade ledger remains canonical.
    * Daily/cohort summaries are always rebuilt from all active nonsuperseded ledger records.
    * already_graded_skipped may be an audit field but never substitutes for previously graded rows.
    * Summary artifact binds every included grade ID and hash.
    * Rebuilding the same cohort must reproduce identical statistics.
    * Partial summaries must be rejected.

THE DEFECT, EXACTLY. grade_slate.summarize() summarised `res["rows"]` — the rows graded in THIS
RUN. A forecast already in the ledger is skipped into `already_graded_skipped` and therefore never
reaches the summary. So when CHC@SEA settled late on 2026-08-21, the rebuild wrote
n=1 / brier .323761 over a cohort of 15 and moved the other 28 rows into an audit list.
data/mlb/analysis/2026-08-21_grades.json no longer reproduces its own headline .23062; that figure
survives only in a governance record and at commit 21514f2. A summary that shrinks when you re-run
it is not a summary of anything.

WHAT IS CANONICAL FOR WHAT.
  data/mlb/forecasts/grades.jsonl  — canonical for WHICH forecast was graded, WHEN, against WHAT
                                     evidence, and whether it was superseded or withdrawn.
  the bound card artifact          — canonical for the model probability, read back by HASH so a
                                     rewritten card can never silently change a historical score.
  data/backfill/.../results.csv    — canonical for the score itself (tier-1 governed).
  data/mlb/analysis/*_grades.json  — DERIVED. Rebuildable, and required to be reproducible.

Rebuilding a derived summary from canonical inputs is not a rewrite of history: the ledger is never
touched, and the gate re-derives every statistic and fails if the artifact disagrees.

ACTIVE-RECORD RESOLUTION. A record naming `supersedes_grade_id` retires its target. A record marked
`withdrawn` is itself inactive. A chain A <- B <- C leaves only C active. A forecast holding more
than one active grade is a CONFLICT and is refused — never silently resolved by recency, because
"take the newest" is how a bad correction quietly wins.
"""
from __future__ import annotations

MODULE_ID = "grade_ledger"

import glob
import hashlib
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRADES = os.path.join(BASE, "data/mlb/forecasts/grades.jsonl")
FORECASTS = os.path.join(BASE, "data/mlb/forecasts/forecasts.jsonl")
ANALYSIS_GLOB = os.path.join(BASE, "data/mlb/analysis/*_grades.json")
CONTRACT = "grade_summary_contract_v1"


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path):
        if line.strip():
            out.append(json.loads(line))
    return out


def cohort_of(fid):
    """P4-20260817-X -> v1 ; P4-20260817v2-X -> v2. Mirrors grade_slate.cohort_of."""
    parts = fid.split("-")
    if len(parts) < 2:
        return "v1"
    head = parts[1]
    return head[8:] if len(head) > 8 else "v1"


def resolve(records):
    """Partition the ledger into active / superseded / withdrawn, and surface conflicts.

    Returns {"active": {forecast_id: record}, "superseded": set, "withdrawn": set,
             "conflicts": [str], "by_grade_id": {...}}"""
    by_id, superseded, withdrawn, conflicts = {}, set(), set(), []
    for r in records:
        gid = r.get("grade_id")
        if not gid:
            conflicts.append(f"ledger record with no grade_id: {r.get('forecast_id')}")
            continue
        if gid in by_id:
            conflicts.append(f"duplicate grade_id {gid}")
            continue
        by_id[gid] = r
    for r in by_id.values():
        tgt = r.get("supersedes_grade_id")
        if tgt:
            superseded.add(tgt)
        if r.get("withdrawn"):
            withdrawn.add(r["grade_id"])
    active = {}
    for gid, r in by_id.items():
        if gid in superseded or gid in withdrawn:
            continue
        fid = r.get("forecast_id")
        if fid in active:
            conflicts.append(f"{fid}: two active grades ({active[fid]['grade_id']}, {gid}) — "
                             f"refusing to pick one by recency")
            continue
        active[fid] = r
    for tgt in superseded:
        if tgt not in by_id:
            conflicts.append(f"a record supersedes {tgt}, which is not in the ledger")
    return {"active": active, "superseded": superseded, "withdrawn": withdrawn,
            "conflicts": conflicts, "by_grade_id": by_id}


def brier(p, y):
    return (p - y) ** 2


def logloss(p, y, eps=1e-6):
    p = min(max(p, eps), 1 - eps)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _sha_file(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _row_tail(r):
    return f'{r["away"]}@{r["home"]}' + ("-G" + r["gamePk"][2:] if str(r.get("gamePk", "")).startswith("DH") else "")


def p_home_of(forecast, card_loader=None):
    """Model probability for a forecast, read back from the artifact it was REGISTERED AGAINST and
    verified by hash. A card that no longer hashes to what was registered cannot supply a
    historical probability (R3) — the rebuild refuses rather than reading the new bytes."""
    ref = forecast.get("artifact_ref") or {}
    path = ref.get("path")
    if not path:
        return None, f"{forecast.get('forecast_id')}: forecast binds no artifact path"
    want = (forecast.get("input_bindings") or {}).get("card_artifact_sha256") \
        or forecast.get("original_file_hash")
    if card_loader is not None:
        card, got = card_loader(path)
    else:
        ap = os.path.join(BASE, path)
        if not os.path.exists(ap):
            return None, f"{forecast.get('forecast_id')}: bound artifact {path} is missing"
        card, got = json.load(open(ap)), _sha_file(ap)
    if want and got != want:
        return None, (f"{forecast.get('forecast_id')}: bound artifact {path} hashes {got[:12]} but "
                      f"was registered as {want[:12]} — refusing to read a rewritten card (R3)")
    tail = forecast["forecast_id"].split("-", 2)[2]
    row = next((r for r in (card.get("rows") or []) if _row_tail(r) == tail), None)
    if row is None:
        return None, f"{forecast.get('forecast_id')}: no row with tail {tail} in {path}"
    try:
        return float(row["v13"]["home_wp"]), None
    except (KeyError, TypeError, ValueError):
        return None, f"{forecast.get('forecast_id')}: row {tail} carries no v13.home_wp"


def cohort_input_hash(bound):
    """Stable hash over the EXACT inputs a cohort statistic was computed from. Sorted, so the hash
    depends on the set of graded games and their values, never on run order."""
    payload = sorted((b["grade_id"], b["forecast_id"], f'{b["p_home"]:.10f}', int(b["home_win"]))
                     for b in bound)
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def rebuild(date, cohort, records=None, forecasts=None, card_loader=None):
    """Rebuild ONE cohort's statistics from EVERY active ledger record for that date and cohort.

    This never consults a previous summary, and never asks which rows were graded in this run."""
    records = _read_jsonl(GRADES) if records is None else records
    forecasts = _read_jsonl(FORECASTS) if forecasts is None else forecasts
    res = resolve(records)
    fc_by_id = {}
    for f in forecasts:
        fid = f.get("forecast_id")
        if fid and fid not in fc_by_id:
            fc_by_id[fid] = f
    bound, errors = [], list(res["conflicts"])
    for fid, grec in sorted(res["active"].items()):
        f = fc_by_id.get(fid)
        if f is None or f.get("slate_date") != date or cohort_of(fid) != cohort:
            continue
        if grec.get("home_win") is None:
            errors.append(f"{fid}: active grade {grec['grade_id']} carries home_win=null")
            continue
        p, err = p_home_of(f, card_loader=card_loader)
        if err:
            errors.append(err)
            continue
        y = int(grec["home_win"])
        bound.append({"grade_id": grec["grade_id"], "forecast_id": fid, "p_home": p, "home_win": y,
                      "correct": int((p >= .5) == (y == 1)),
                      "brier": round(brier(p, y), 6), "logloss": round(logloss(p, y), 6)})
    n = len(bound)
    return {
        "date": date, "cohort": cohort, "contract": CONTRACT,
        "n": n,
        "correct": sum(b["correct"] for b in bound),
        "accuracy": round(sum(b["correct"] for b in bound) / n, 6) if n else None,
        "brier": round(sum(brier(b["p_home"], b["home_win"]) for b in bound) / n, 6) if n else None,
        "logloss": round(sum(logloss(b["p_home"], b["home_win"]) for b in bound) / n, 6) if n else None,
        "bound_grades": sorted(bound, key=lambda b: b["forecast_id"]),
        "cohort_input_sha256": cohort_input_hash(bound),
        "rebuild_errors": errors,
    }


def active_cohort_ids(date, cohort, records=None, forecasts=None):
    """The grade_ids that MUST appear in a complete summary for this cohort."""
    records = _read_jsonl(GRADES) if records is None else records
    forecasts = _read_jsonl(FORECASTS) if forecasts is None else forecasts
    fdates = {}
    for f in forecasts:
        fdates.setdefault(f.get("forecast_id"), f.get("slate_date"))
    out = set()
    for fid, g in resolve(records)["active"].items():
        if fdates.get(fid) == date and cohort_of(fid) == cohort and g.get("home_win") is not None:
            out.add(g["grade_id"])
    return out


PARTIAL_SUMMARY = "PARTIAL_SUMMARY"
STALE_BINDING = "STALE_BINDING"
STATISTIC_DRIFT = "STATISTIC_DRIFT"
UNBOUND_SUMMARY = "UNBOUND_SUMMARY"
SKIPPED_SUBSTITUTION = "SKIPPED_SUBSTITUTION"


def verify(artifact, date, cohort, records=None, forecasts=None, card_loader=None):
    """(ok, failures) for ONE cohort block of a summary artifact.

    An artifact may only claim a cohort statistic if it binds every active grade behind it and
    reproduces every number from them."""
    fails = []
    block = (artifact.get("summary") or {}).get(cohort)
    if block is None:
        return True, []
    truth = rebuild(date, cohort, records=records, forecasts=forecasts, card_loader=card_loader)
    bound_ids = set(block.get("bound_grade_ids") or [])
    active = active_cohort_ids(date, cohort, records=records, forecasts=forecasts)
    if not bound_ids:
        fails.append(f"{UNBOUND_SUMMARY}: {date}/{cohort} states n={block.get('n')} but binds no "
                     f"grade ids; the statistic cannot be traced to the ledger")
    missing = active - bound_ids
    if missing:
        fails.append(f"{PARTIAL_SUMMARY}: {date}/{cohort} omits {len(missing)} active grade(s) "
                     f"{sorted(missing)[:4]}")
    stale = bound_ids - active
    if stale:
        fails.append(f"{STALE_BINDING}: {date}/{cohort} binds {len(stale)} grade(s) that are "
                     f"superseded, withdrawn or not in this cohort {sorted(stale)[:4]}")
    # THE 2026-08-21 DEFECT, named directly: a run that skipped previously graded forecasts and then
    # reported a summary smaller than the cohort. already_graded_skipped is an audit field only.
    skipped = artifact.get("already_graded_skipped") or []
    if skipped and block.get("n") is not None and block["n"] < len(active):
        fails.append(f"{SKIPPED_SUBSTITUTION}: {date}/{cohort} reports n={block['n']} against "
                     f"{len(active)} active grades while listing {len(skipped)} as "
                     f"already_graded_skipped — skipped rows were substituted for graded ones")
    for k in ("n", "correct", "brier", "logloss", "accuracy"):
        if k in block and block[k] is not None and truth.get(k) is not None:
            a, b = block[k], truth[k]
            same = (a == b) if isinstance(a, int) and isinstance(b, int) else abs(float(a) - float(b)) < 5e-6
            if not same:
                fails.append(f"{STATISTIC_DRIFT}: {date}/{cohort} {k}={a} but the ledger rebuilds "
                             f"to {b}")
    h = block.get("cohort_input_sha256")
    if h and h != truth["cohort_input_sha256"]:
        fails.append(f"{STATISTIC_DRIFT}: {date}/{cohort} input hash {h[:12]} but the ledger "
                     f"rebuilds to {truth['cohort_input_sha256'][:12]}")
    return (not fails), fails


def gate(paths=None, records=None, forecasts=None, card_loader=None, strict_only=True):
    """(ok, failures, legacy). Verifies every summary artifact that has adopted the contract.

    strict_only keeps pre-contract artifacts out of the FAIL set — they are listed as legacy so the
    backlog is visible rather than silently tolerated — EXCEPT for the one check that needs no
    binding at all: a summary smaller than its own cohort. That is the defect this module exists
    for and it is failed wherever it appears."""
    fails, legacy = [], []
    for p in sorted(paths if paths is not None else glob.glob(ANALYSIS_GLOB)):
        try:
            art = json.load(open(p))
        except (OSError, ValueError) as e:
            fails.append(f"{os.path.basename(p)}: unreadable ({type(e).__name__})")
            continue
        date = art.get("date") or os.path.basename(p)[:10]
        adopted = art.get("contract") == CONTRACT
        for cohort in sorted((art.get("summary") or {})):
            if adopted or not strict_only:
                ok, ff = verify(art, date, cohort, records, forecasts, card_loader)
                fails.extend(f"{os.path.basename(p)}: {x}" for x in ff)
            else:
                legacy.append(f"{os.path.basename(p)}/{cohort}: pre-contract summary, not bound")
                block = art["summary"][cohort]
                active = active_cohort_ids(date, cohort, records=records, forecasts=forecasts)
                skipped = art.get("already_graded_skipped") or []
                if skipped and block.get("n") is not None and active and block["n"] < len(active):
                    fails.append(f"{os.path.basename(p)}: {SKIPPED_SUBSTITUTION}: {cohort} reports "
                                 f"n={block['n']} against {len(active)} active grades while "
                                 f"listing {len(skipped)} as already_graded_skipped")
    return (not fails), fails, legacy


def _fixture_world():
    """Two-game v1 cohort on 2026-01-01, plus the machinery to fake the bound card artifact."""
    card = {"rows": [{"away": "AAA", "home": "BBB", "gamePk": "1", "v13": {"home_wp": 0.60}},
                     {"away": "CCC", "home": "DDD", "gamePk": "2", "v13": {"home_wp": 0.40}}]}
    CARD_SHA = "cardsha"
    forecasts = [
        {"forecast_id": "P4-20260101-AAA@BBB", "slate_date": "2026-01-01",
         "artifact_ref": {"path": "cards/2026-01-01_card.json"},
         "input_bindings": {"card_artifact_sha256": CARD_SHA}},
        {"forecast_id": "P4-20260101-CCC@DDD", "slate_date": "2026-01-01",
         "artifact_ref": {"path": "cards/2026-01-01_card.json"},
         "input_bindings": {"card_artifact_sha256": CARD_SHA}},
    ]
    grades = [
        {"grade_id": "G-AAA", "forecast_id": "P4-20260101-AAA@BBB",
         "graded_at_utc": "2026-01-02T00:00:00Z", "home_win": 1},
        {"grade_id": "G-CCC", "forecast_id": "P4-20260101-CCC@DDD",
         "graded_at_utc": "2026-01-03T00:00:00Z", "home_win": 0},
    ]
    loader = lambda path, _c=card, _s=CARD_SHA: (_c, _s)
    return card, forecasts, grades, loader


def selftest():
    f = []
    card, FC, GR, loader = _fixture_world()
    kw = dict(records=GR, forecasts=FC, card_loader=loader)

    # 1. THE DEFECT. A rebuild triggered by ONE late settlement must still summarise the WHOLE
    #    cohort, not the one row this run touched.
    t = rebuild("2026-01-01", "v1", **kw)
    if t["n"] != 2:
        f.append(f"rebuild summarised n={t['n']}; the cohort has 2 active grades — a re-settlement "
                 f"would again replace a complete cohort with one row")
    if t["correct"] != 2:
        f.append(f"rebuild scored correct={t['correct']}, expected 2 (p .60 -> home win, "
                 f".40 -> away win)")
    if abs(t["brier"] - ((0.4 ** 2 + 0.4 ** 2) / 2)) > 1e-9:
        f.append(f"rebuilt brier {t['brier']} is not the mean of the per-game briers")
    if len(t["bound_grades"]) != 2:
        f.append("rebuild did not bind every grade it counted")

    # 2. DETERMINISM: same inputs, identical statistics AND identical input hash, whatever the
    #    ledger's physical order.
    t2 = rebuild("2026-01-01", "v1", records=list(reversed(GR)), forecasts=FC, card_loader=loader)
    if (t2["n"], t2["brier"], t2["cohort_input_sha256"]) != (t["n"], t["brier"], t["cohort_input_sha256"]):
        f.append("rebuilding the same cohort from a reordered ledger produced different statistics")
    if rebuild("2026-01-01", "v1", **kw)["cohort_input_sha256"] != t["cohort_input_sha256"]:
        f.append("two identical rebuilds produced different input hashes")

    # 3. SUPERSESSION: a chain resolves to the last link only.
    chain = GR + [{"grade_id": "G2-AAA", "forecast_id": "P4-20260101-AAA@BBB",
                   "supersedes_grade_id": "G-AAA", "home_win": 0},
                  {"grade_id": "G3-AAA", "forecast_id": "P4-20260101-AAA@BBB",
                   "supersedes_grade_id": "G2-AAA", "home_win": 1}]
    r = resolve(chain)
    if r["conflicts"]:
        f.append(f"a legitimate supersession chain reported conflicts: {r['conflicts']}")
    if r["active"].get("P4-20260101-AAA@BBB", {}).get("grade_id") != "G3-AAA":
        f.append(f"chain A<-B<-C did not resolve to C: "
                 f"{r['active'].get('P4-20260101-AAA@BBB', {}).get('grade_id')}")
    t3 = rebuild("2026-01-01", "v1", records=chain, forecasts=FC, card_loader=loader)
    if t3["n"] != 2:
        f.append(f"a superseded cohort rebuilt to n={t3['n']}, expected 2 — supersession must "
                 f"REPLACE a grade, not add or drop one")

    # 4. WITHDRAWAL leaves the forecast UNGRADED, not silently reverted to the withdrawn grade.
    wd = GR + [{"grade_id": "W-G-CCC", "forecast_id": "P4-20260101-CCC@DDD",
                "supersedes_grade_id": "G-CCC", "home_win": None, "withdrawn": True}]
    r = resolve(wd)
    if "P4-20260101-CCC@DDD" in r["active"]:
        f.append("a withdrawn grade left its forecast ACTIVE")
    t4 = rebuild("2026-01-01", "v1", records=wd, forecasts=FC, card_loader=loader)
    if t4["n"] != 1:
        f.append(f"after a withdrawal the cohort rebuilt to n={t4['n']}, expected 1")

    # 5. TWO ACTIVE GRADES for one forecast is a CONFLICT, never resolved by recency.
    dbl = GR + [{"grade_id": "G-AAA-2", "forecast_id": "P4-20260101-AAA@BBB",
                 "graded_at_utc": "2026-06-01T00:00:00Z", "home_win": 0}]
    r = resolve(dbl)
    if not any("two active grades" in c for c in r["conflicts"]):
        f.append("two active grades for one forecast were silently resolved instead of refused")
    if not rebuild("2026-01-01", "v1", records=dbl, forecasts=FC,
                   card_loader=loader)["rebuild_errors"]:
        f.append("a rebuild over a conflicted ledger reported no errors")
    # a duplicate grade_id is also a conflict
    if not any("duplicate grade_id" in c for c in resolve(GR + [dict(GR[0])])["conflicts"]):
        f.append("a duplicate grade_id was accepted")
    # superseding something that is not in the ledger is a conflict
    if not any("not in the ledger" in c for c in
               resolve(GR + [{"grade_id": "G-X", "forecast_id": "P4-20260101-AAA@BBB",
                              "supersedes_grade_id": "G-NOPE", "home_win": 1}])["conflicts"]):
        f.append("a record superseding an unknown grade_id was accepted")

    # 6. R3: a card that no longer hashes to what was registered cannot supply a probability.
    bad_loader = lambda path, _c=card: (_c, "DIFFERENT")
    t6 = rebuild("2026-01-01", "v1", records=GR, forecasts=FC, card_loader=bad_loader)
    if t6["n"] != 0 or not any("refusing to read a rewritten card" in e for e in t6["rebuild_errors"]):
        f.append(f"a rewritten card was read anyway: n={t6['n']} errors={t6['rebuild_errors']}")

    # 7. an active grade carrying home_win=null is an error, not a silent zero
    nul = [dict(GR[0], home_win=None), GR[1]]
    t7 = rebuild("2026-01-01", "v1", records=nul, forecasts=FC, card_loader=loader)
    if t7["n"] != 1 or not any("home_win=null" in e for e in t7["rebuild_errors"]):
        f.append(f"a null home_win was not reported: n={t7['n']} errors={t7['rebuild_errors']}")

    # ---- verification of a summary ARTIFACT --------------------------------------------------
    good = {"date": "2026-01-01", "contract": CONTRACT,
            "summary": {"v1": {"n": 2, "correct": 2, "brier": t["brier"], "logloss": t["logloss"],
                               "accuracy": t["accuracy"],
                               "bound_grade_ids": ["G-AAA", "G-CCC"],
                               "cohort_input_sha256": t["cohort_input_sha256"]}}}
    ok, ff = verify(good, "2026-01-01", "v1", **kw)
    if not ok:
        f.append(f"a correct, fully bound summary was rejected: {ff}")

    # 8. PARTIAL SUMMARIES MUST BE REJECTED
    part = json.loads(json.dumps(good))
    part["summary"]["v1"].update(n=1, correct=1, brier=0.16, accuracy=1.0,
                                 logloss=rebuild("2026-01-01", "v1", **kw)["logloss"],
                                 bound_grade_ids=["G-AAA"],
                                 cohort_input_sha256=cohort_input_hash(
                                     [b for b in t["bound_grades"] if b["grade_id"] == "G-AAA"]))
    ok, ff = verify(part, "2026-01-01", "v1", **kw)
    if ok or not any(PARTIAL_SUMMARY in x for x in ff):
        f.append(f"a summary omitting an active grade was accepted: {ff}")

    # 9. THE 2026-08-21 SHAPE: n shrinks and the missing rows appear in already_graded_skipped
    skip = json.loads(json.dumps(part))
    skip["already_graded_skipped"] = ["P4-20260101-CCC@DDD"]
    ok, ff = verify(skip, "2026-01-01", "v1", **kw)
    if not any(SKIPPED_SUBSTITUTION in x for x in ff):
        f.append("a summary that substituted already_graded_skipped for graded rows was not named")

    # 10. an UNBOUND summary cannot be traced and is refused
    unb = json.loads(json.dumps(good))
    unb["summary"]["v1"].pop("bound_grade_ids")
    unb["summary"]["v1"].pop("cohort_input_sha256")
    ok, ff = verify(unb, "2026-01-01", "v1", **kw)
    if ok or not any(UNBOUND_SUMMARY in x for x in ff):
        f.append(f"a summary binding no grade ids was accepted: {ff}")

    # 11. STALE BINDING: binding a superseded grade
    st = json.loads(json.dumps(good))
    st["summary"]["v1"]["bound_grade_ids"] = ["G-AAA", "G-CCC", "G-GONE"]
    ok, ff = verify(st, "2026-01-01", "v1", **kw)
    if ok or not any(STALE_BINDING in x for x in ff):
        f.append(f"a summary binding a non-active grade was accepted: {ff}")

    # 12. STATISTIC DRIFT: the numbers must be reproduced, not merely accompanied by ids
    dr = json.loads(json.dumps(good))
    dr["summary"]["v1"]["brier"] = 0.1
    ok, ff = verify(dr, "2026-01-01", "v1", **kw)
    if ok or not any(STATISTIC_DRIFT in x for x in ff):
        f.append(f"a summary whose brier disagrees with the ledger was accepted: {ff}")
    dr2 = json.loads(json.dumps(good))
    dr2["summary"]["v1"]["cohort_input_sha256"] = "0" * 64
    ok, ff = verify(dr2, "2026-01-01", "v1", **kw)
    if ok or not any(STATISTIC_DRIFT in x for x in ff):
        f.append("a summary whose input hash disagrees with the ledger was accepted")
    # ...and the hash must actually depend on the values, not just the ids
    flipped = [dict(b, home_win=1 - b["home_win"]) for b in t["bound_grades"]]
    if cohort_input_hash(flipped) == t["cohort_input_sha256"]:
        f.append("the input hash does not change when the graded outcomes change")

    # 13. the GATE fails a pre-contract artifact that shrank, and does not fail one that did not
    legacy_shrunk = {"date": "2026-01-01", "already_graded_skipped": ["P4-20260101-CCC@DDD"],
                     "summary": {"v1": {"n": 1, "brier": 0.16}}}
    legacy_ok = {"date": "2026-01-01", "summary": {"v1": {"n": 2, "brier": t["brier"]}}}
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        pa = os.path.join(td, "2026-01-01_grades.json")
        json.dump(legacy_shrunk, open(pa, "w"))
        ok, ff, lg = gate(paths=[pa], **kw)
        if ok or not any(SKIPPED_SUBSTITUTION in x for x in ff):
            f.append(f"the gate passed a pre-contract summary that shrank below its cohort: {ff}")
        json.dump(legacy_ok, open(pa, "w"))
        ok, ff, lg = gate(paths=[pa], **kw)
        if not ok:
            f.append(f"the gate failed an intact pre-contract summary: {ff}")
        if not lg:
            f.append("the gate did not list a pre-contract summary as legacy backlog")
        json.dump(good, open(pa, "w"))
        ok, ff, lg = gate(paths=[pa], **kw)
        if not ok:
            f.append(f"the gate failed a contract-adopted, correct summary: {ff}")
        if lg:
            f.append("a contract-adopted summary was still listed as legacy")

    print("grade_ledger selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("supersession ignored — a corrected grade and its predecessor both stay active",
     "        if gid in superseded or gid in withdrawn:", "        if gid in withdrawn:"),
    ("withdrawal ignored — a withdrawn grade still scores",
     "        if gid in superseded or gid in withdrawn:", "        if gid in superseded:"),
    ("two active grades resolved by recency instead of refused",
     '            conflicts.append(f"{fid}: two active grades ({active[fid][\'grade_id\']}, {gid}) — "',
     '            active[fid] = r; conflicts.append(f"{fid}: silently overwritten ({gid}) — "'),
    ("duplicate grade_id accepted", '            conflicts.append(f"duplicate grade_id {gid}")',
     "            pass"),
    ("a record superseding an unknown grade_id is accepted",
     "    for tgt in superseded:", "    for tgt in ():"),
    ("the cohort input hash ignores the graded OUTCOMES",
     '    payload = sorted((b["grade_id"], b["forecast_id"], f\'{b["p_home"]:.10f}\', int(b["home_win"]))',
     '    payload = sorted((b["grade_id"], b["forecast_id"], f\'{b["p_home"]:.10f}\')'),
    ("the cohort input hash depends on ledger ORDER, so a reorder looks like a change",
     "    payload = sorted((", "    payload = ((("),
    ("registered card hash no longer checked — a rewritten card supplies history",
     "    if want and got != want:", "    if False:"),
    ("a null home_win is coerced to a loss instead of reported",
     '        if grec.get("home_win") is None:', "        if False:"),
    ("partial summaries accepted", "    missing = active - bound_ids", "    missing = set()"),
    ("stale bindings accepted", "    stale = bound_ids - active", "    stale = set()"),
    ("unbound summaries accepted", "    if not bound_ids:", "    if False:"),
    ("already_graded_skipped substitution no longer named",
     '    if skipped and block.get("n") is not None and block["n"] < len(active):',
     "    if False:"),
    ("statistic drift tolerance widened until nothing drifts",
     "            same = (a == b) if isinstance(a, int) and isinstance(b, int) else abs(float(a) - float(b)) < 5e-6",
     "            same = True"),
    ("input-hash comparison dropped", '    if h and h != truth["cohort_input_sha256"]:',
     "    if False:"),
    ("the gate stops failing pre-contract summaries that shrank below their cohort",
     '                if skipped and block.get("n") is not None and active and block["n"] < len(active):',
     "                if False:"),
    ("the gate stops listing the pre-contract backlog",
     '                legacy.append(f"{os.path.basename(p)}/{cohort}: pre-contract summary, not bound")',
     "                pass"),
    ("brier averaged over the WRONG denominator",
     '        "brier": round(sum(brier(b["p_home"], b["home_win"]) for b in bound) / n, 6) if n else None,',
     '        "brier": round(sum(brier(b["p_home"], b["home_win"]) for b in bound) / (n + 1), 6) if n else None,'),
]


def mutation_suite(verbose=True):
    import subprocess as _sp, tempfile as _tf
    src = open(os.path.abspath(__file__)).read()
    i = src.index("MUTANTS = [")
    j = src.index("\ndef mutation_suite", i)
    head, block, tail = src[:i], src[i:j], src[j:]
    surv, unapp = [], []
    for name, old, new in MUTANTS:
        where = "head" if old in head else ("tail" if old in tail else None)
        if where is None:
            unapp.append(f"{name}: pattern not found"); continue
        mut = (head.replace(old, new, 1) + block + tail) if where == "head" \
            else (head + block + tail.replace(old, new, 1))
        if mut == src:
            unapp.append(f"{name}: no-op"); continue
        with _tf.NamedTemporaryFile("w", suffix="_mutant.py", delete=False,
                                    dir=os.path.dirname(os.path.abspath(__file__))) as fh:
            fh.write(mut); path = fh.name
        try:
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True, timeout=180)
            killed = pr.returncode != 0
        except _sp.TimeoutExpired:
            killed = True
        finally:
            os.unlink(path)
        if verbose:
            print(f"  {'KILLED  ' if killed else 'SURVIVED'}  {name}")
        if not killed:
            surv.append(name)
    for u in unapp:
        print(f"  UNAPPLIED  {u}")
    print(f"mutation suite: {len(MUTANTS)-len(surv)-len(unapp)}/{len(MUTANTS)} killed"
          f"{'' if not (surv or unapp) else '  — SURVIVORS MEAN DECORATIVE FIXTURES'}")
    return surv + unapp


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    if "--mutants" in sys.argv:
        sys.exit(1 if mutation_suite() else 0)
    if "--gate" in sys.argv:
        ok, ff, lg = gate()
        print(f"grade-summary gate: {'PASS' if ok else f'FAIL ({len(ff)})'}; "
              f"{len(lg)} pre-contract cohort summary/ies not yet bound")
        for x in ff:
            print("  ! " + x)
        sys.exit(0 if ok else 1)
    if "--rebuild" in sys.argv:
        d = sys.argv[sys.argv.index("--rebuild") + 1]
        c = sys.argv[sys.argv.index("--cohort") + 1] if "--cohort" in sys.argv else "v1"
        print(json.dumps({k: v for k, v in rebuild(d, c).items() if k != "bound_grades"}, indent=1))
        sys.exit(0)
    print(__doc__)
