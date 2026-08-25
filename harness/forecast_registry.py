#!/usr/bin/env python3
"""Append-only forecast registry + separate grade registry (owner-authorized 2026-07-28).

Two JSONL logs under data/mlb/forecasts/:
  forecasts.jsonl   one record per forecast (or per pointer to an existing immutable artifact)
  grades.jsonl      outcome/grade records, linked by immutable forecast_id — a grade NEVER
                    modifies the forecast row it grades

Append-only is enforced by a hash chain: head.json stores chain = sha256 folded over every line of
both files in order. Any mutation, deletion or reorder of an archived record breaks the chain and
fails healthcheck. Relabeling into a stronger cohort after outcomes is structurally impossible
without breaking the chain: records are immutable, forecast_ids are unique, and a re-issued id is a
duplicate-id failure.

Cohorts (fixed):
  PROMOTION_PROSPECTIVE   pregame, file-hashed at generation, complete inputs — the only cohort
                          that may ever carry promotion_eligible=true
  DIAGNOSTIC_PROSPECTIVE  pregame and contemporaneous, but data-deficient or shadow-classified
  RETROSPECTIVE_ARCHIVED  contemporaneous evidence exists (e.g. chat transcript) but the record
                          was archived after the fact; never prospective, never promotable
  POST_HOC_REPLAY         computed after outcomes existed; bookkeeping only

ledger_eligible is False on every record this module will accept: entering a betting ledger is a
separate, manual, owner-authorized act — no forecast auto-enters a ledger, ever.
"""

from __future__ import annotations

MODULE_ID = "forecast_registry"

import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "harness"))

DIR = "data/mlb/forecasts"
FORECASTS = f"{DIR}/forecasts.jsonl"
GRADES = f"{DIR}/grades.jsonl"
HEAD = f"{DIR}/head.json"

COHORTS = ("PROMOTION_PROSPECTIVE", "DIAGNOSTIC_PROSPECTIVE", "RETROSPECTIVE_ARCHIVED", "POST_HOC_REPLAY")

REQUIRED = ("forecast_id", "cohort", "provenance_class", "game_ref", "slate_date", "market",
            "generated_at_utc", "archived_at_utc", "model_id", "rng_policy", "input_vintage",
            "dq_flags", "promotion_eligible", "ledger_eligible", "diagnostic_grade_eligible",
            "provenance_limitations")

#: Result-shaped keys that must NEVER appear inside a forecast payload (results live in grades.jsonl).
FORBIDDEN_RESULT_KEYS = ("result", "outcome", "winner", "final", "final_score", "actual",
                         "settled", "pl", "pl_units", "won", "lost", "grade")


def _lines(path):
    return [l for l in open(path).read().splitlines() if l.strip()] if os.path.exists(path) else []


def chain_hash():
    h = hashlib.sha256(b"forecast-registry-v1")
    for path in (FORECASTS, GRADES):
        for ln in _lines(path):
            h = hashlib.sha256(h.digest() + ln.encode())
    return h.hexdigest()


def _write_head():
    os.makedirs(DIR, exist_ok=True)
    json.dump({"chain": chain_hash(),
               "n_forecasts": len(_lines(FORECASTS)), "n_grades": len(_lines(GRADES))},
              open(HEAD, "w"), indent=1)


def _registry():
    import model_registry
    return model_registry.REGISTRY


def _payload_result_keys(obj):
    hits = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                if k.lower() in FORBIDDEN_RESULT_KEYS:
                    hits.append(f"{path}/{k}")
                walk(v, f"{path}/{k}")
        elif isinstance(o, list):
            for v in o:
                walk(v, path)
    walk(obj, "payload")
    return hits


def validate_records(forecasts, grades, registry=None, artifact_hash_reader=None):
    """Pure rule engine — the falsification tests attack THIS. Returns a list of violations."""
    reg = registry if registry is not None else _registry()
    read_sha = artifact_hash_reader or (lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
                                        if os.path.exists(p) else None)
    v = []
    seen = set()
    for r in forecasts:
        fid = r.get("forecast_id", "<missing>")
        for k in REQUIRED:
            if k not in r:
                v.append(f"{fid}: missing required field {k}")
        if fid in seen:
            v.append(f"duplicate forecast_id {fid}")
        seen.add(fid)
        if r.get("cohort") not in COHORTS:
            v.append(f"{fid}: unknown cohort {r.get('cohort')}")
        if r.get("promotion_eligible") and r.get("cohort") != "PROMOTION_PROSPECTIVE":
            v.append(f"{fid}: {r.get('cohort')} record marked promotion_eligible — diagnostic/retrospective "
                     "records can never count toward the promotion gate")
        if r.get("cohort") in ("RETROSPECTIVE_ARCHIVED", "POST_HOC_REPLAY") and r.get("prospective"):
            v.append(f"{fid}: retrospective record marked prospective")
        if r.get("ledger_eligible"):
            v.append(f"{fid}: ledger_eligible=true — no forecast may automatically enter a betting ledger")
        if "payload" in r:
            for hit in _payload_result_keys(r["payload"]):
                v.append(f"{fid}: result field inside forecast payload: {hit}")
        # original-file hash: null is honest when no file existed; a non-null hash must be REAL
        ofh = r.get("original_file_hash")
        ar = r.get("artifact_ref")
        if ofh is not None:
            path = (ar or {}).get("path")
            actual = read_sha(path) if path else None
            if actual is None:
                v.append(f"{fid}: original_file_hash set but no artifact exists at {path!r} — fabricated hash")
            elif actual != ofh:
                v.append(f"{fid}: original_file_hash does not match artifact on disk — fabricated or stale")
        mid = r.get("model_id")
        if mid is not None:
            if mid not in reg:
                v.append(f"{fid}: model_id {mid} not in model registry")
            else:
                want = reg[mid].get("rng_policy")
                if want is not None and r.get("rng_policy") != want:
                    v.append(f"{fid}: rng_policy {r.get('rng_policy')!r} != registry {want!r} for {mid}")
    # one model_id may not cover two RNG computations
    combos = {}
    for mid, m in reg.items():
        key = (m.get("source"), str(m.get("hfa")), m.get("seed"), m.get("sims_per_game"))
        combos.setdefault(mid, key)
    pol = {}
    for mid, m in reg.items():
        if m.get("rng_policy") is None:
            continue
        if mid in pol and pol[mid] != m["rng_policy"]:
            v.append(f"registry: model_id {mid} carries two rng policies")
        pol[mid] = m["rng_policy"]
    by_id_policy = {}
    for r in forecasts:
        mid = r.get("model_id")
        if mid is None:
            continue
        p = r.get("rng_policy")
        if mid in by_id_policy and by_id_policy[mid] != p:
            v.append(f"model_id {mid} used with two different rng policies "
                     f"({by_id_policy[mid]!r} vs {p!r}) — sequential and per-game-reset may not share one identity")
        by_id_policy.setdefault(mid, p)
    for g in grades:
        gf = g.get("forecast_id")
        if gf not in seen:
            v.append(f"grade {g.get('grade_id','?')}: no matching forecast {gf}")
    return v


def append_forecast(rec):
    probs = validate_records(_load(FORECASTS) + [rec], _load(GRADES))
    if probs:
        raise ValueError("refused append:\n  " + "\n  ".join(probs[:8]))
    os.makedirs(DIR, exist_ok=True)
    open(FORECASTS, "a").write(json.dumps(rec, separators=(",", ":")) + "\n")
    _write_head()


def append_grade(rec):
    probs = validate_records(_load(FORECASTS), _load(GRADES) + [rec])
    if probs:
        raise ValueError("refused append:\n  " + "\n  ".join(probs[:8]))
    os.makedirs(DIR, exist_ok=True)
    open(GRADES, "a").write(json.dumps(rec, separators=(",", ":")) + "\n")
    _write_head()


def _load(path):
    return [json.loads(l) for l in _lines(path)]


def verify() -> int:
    """Chain + rules over the real registries. Exit 0 clean."""
    fails = []
    if os.path.exists(HEAD):
        head = json.load(open(HEAD))
        if head["chain"] != chain_hash():
            fails.append("HASH CHAIN BROKEN: an archived record was mutated, deleted or reordered")
        if head["n_forecasts"] != len(_lines(FORECASTS)) or head["n_grades"] != len(_lines(GRADES)):
            fails.append("head counts disagree with files")
    elif os.path.exists(FORECASTS) or os.path.exists(GRADES):
        fails.append("registries exist but head.json missing")
    fails += validate_records(_load(FORECASTS), _load(GRADES))
    if fails:
        print("forecast_registry verify: FAIL")
        for f in fails[:10]:
            print("  " + f)
        return 1
    print(f"forecast_registry verify: PASS ({len(_lines(FORECASTS))} forecasts, "
          f"{len(_lines(GRADES))} grades, chain intact)")
    return 0


if __name__ == "__main__":
    raise SystemExit(verify())
