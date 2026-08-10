#!/usr/bin/env python3
"""Machine-readable provenance for outcome labels (results.csv).

WHY (2026-08-10): every hard control in this system guarded MODEL IDENTITY and FORECAST PROVENANCE —
the hash chain, the freeze gates, the byte-identical ml_asof rebuild — and none guarded the OUTCOME
LABEL, which is the single input all of them are scored against. `source` was a free-text cell that
zero consumers read, so a row transcribed from a search snippet was byte-indistinguishable from an
official box score. On 2026-08-08 that let 4 of 15 rows (3 reversed winners) be graded as authoritative.

This module makes the tier machine-readable and gives the health gate something it can actually fail on.

  TIER 1  official API / owner-supplied primary record (statsapi, box dump, savant box paste, board)
          -> may carry result_status FINAL and back a graded forecast
  TIER 2  reputable outlet recap, aggregator paste
  TIER 3  search snippet
          -> tiers 2-3 are PROVISIONAL: usable for continuity and freshness, never authoritative

PROVISIONAL is a legitimate resting state, not a failure. Making it *visible* removes the incentive
that produced this incident: the freshness gate pressured the dataset to look current while the
sanctioned statsapi path was egress-blocked, so the agent improvised and wrote snippets as finals.
"""

from __future__ import annotations

import csv
import hashlib
import os

RESULTS = "data/backfill/mlb/2026/results.csv"
PROV_COLS = ["source_tier", "result_status", "evidence_path", "evidence_sha256"]

#: substring -> tier. First match wins, so order matters (most specific first).
TIER_RULES = [
    ("owner_box_dump", 1), ("box_dump", 1),
    ("statsapi+box_paste", 1), ("statsapi", 1),
    ("savant_box_paste", 1), ("owner_board_paste", 1),
    ("aggregator_paste", 2), ("corrected_2026-08-07", 2), ("multi_agent_verified", 3),
    ("websearch", 3), ("aggregator", 2),
]


def tier_of(source: str) -> int:
    """Classify a free-text source string. Unknown -> 3 (most conservative)."""
    s = (source or "").lower()
    for frag, tier in TIER_RULES:
        if frag.lower() in s:
            return tier
    return 3


def status_for(tier: int) -> str:
    return "FINAL" if tier == 1 else "PROVISIONAL"


def sha256_file(path: str):
    if not path or not os.path.exists(path):
        return None
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def audit_rows(rows):
    """Return (problems, stats) for provenance integrity.

    Failures are limited to claims that are *checkable and false*:
      - result_status FINAL on a non-tier-1 row (an unearned authority claim)
      - an evidence_path that does not exist on disk
      - an evidence_sha256 that does not match the file it names (a fabricated hash)
    A tier-2/3 row marked PROVISIONAL is correct and never a problem.
    """
    problems = []
    stats = {"FINAL": 0, "PROVISIONAL": 0, "tier1": 0, "tier2": 0, "tier3": 0, "evidence_bound": 0}
    for r in rows:
        if r.get("status") != "final":
            continue
        try:
            tier = int(r.get("source_tier") or 0)
        except ValueError:
            tier = 0
        st = r.get("result_status") or ""
        stats[f"tier{tier}"] = stats.get(f"tier{tier}", 0) + 1
        if st in stats:
            stats[st] += 1
        if st == "FINAL" and tier != 1:
            problems.append(f"{r['game_id']}: result_status=FINAL but source_tier={tier} "
                            f"(only tier-1 may be FINAL)")
        ep = r.get("evidence_path") or ""
        es = r.get("evidence_sha256") or ""
        if ep:
            if not os.path.exists(ep):
                problems.append(f"{r['game_id']}: evidence_path does not exist: {ep}")
            else:
                stats["evidence_bound"] += 1
                actual = sha256_file(ep)
                if es and actual != es:
                    problems.append(f"{r['game_id']}: evidence_sha256 does not match {ep} "
                                    f"(fabricated or stale hash)")
        elif es:
            problems.append(f"{r['game_id']}: evidence_sha256 set with no evidence_path")
    return problems, stats


def load(path: str = RESULTS):
    with open(path) as f:
        return list(csv.DictReader(f))


def migrate(path: str = RESULTS, dry_run: bool = False):
    """Add the provenance columns and back-fill them from the existing `source` text."""
    with open(path) as f:
        rd = csv.DictReader(f)
        rows = list(rd)
        cols = list(rd.fieldnames)
    added = [c for c in PROV_COLS if c not in cols]
    for c in PROV_COLS:
        if c not in cols:
            cols.append(c)
    changed = 0
    for r in rows:
        if r.get("source_tier"):
            continue
        t = tier_of(r.get("source", ""))
        r["source_tier"] = str(t)
        r["result_status"] = status_for(t) if r.get("status") == "final" else ""
        r.setdefault("evidence_path", "")
        r.setdefault("evidence_sha256", "")
        changed += 1
    if not dry_run:
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in cols})
    return added, changed, rows


def selftest():
    fails = []
    if tier_of("statsapi") != 1:
        fails.append("statsapi must be tier 1")
    if tier_of("websearch_multi_source(ESPN/MLB.com)") != 3:
        fails.append("websearch must be tier 3")
    # "multi_agent_verified" is still a search channel -> tier 3, not promoted by agent count
    if tier_of("websearch_multi_agent_verified") != 3:
        fails.append("multi-agent websearch must remain tier 3")
    if tier_of("owner_box_dump(tier1) sha256:abc") != 1:
        fails.append("box dump must be tier 1")
    if tier_of("something never seen") != 3:
        fails.append("unknown source must default to tier 3 (conservative)")
    if status_for(1) != "FINAL" or status_for(3) != "PROVISIONAL":
        fails.append("status mapping")
    # a FINAL claim on tier 3 must be a problem
    p, _ = audit_rows([{"status": "final", "game_id": "g1", "source_tier": "3",
                        "result_status": "FINAL"}])
    if not any("only tier-1 may be FINAL" in x for x in p):
        fails.append("unearned FINAL not flagged")
    # a PROVISIONAL tier-3 row is fine
    p, _ = audit_rows([{"status": "final", "game_id": "g2", "source_tier": "3",
                        "result_status": "PROVISIONAL"}])
    if p:
        fails.append("PROVISIONAL tier-3 row wrongly flagged")
    # fabricated hash must be caught
    p, _ = audit_rows([{"status": "final", "game_id": "g3", "source_tier": "1",
                        "result_status": "FINAL", "evidence_path": __file__,
                        "evidence_sha256": "0" * 64}])
    if not any("does not match" in x for x in p):
        fails.append("fabricated evidence hash not flagged")
    # missing evidence file must be caught
    p, _ = audit_rows([{"status": "final", "game_id": "g4", "source_tier": "1",
                        "result_status": "FINAL", "evidence_path": "does/not/exist.json"}])
    if not any("does not exist" in x for x in p):
        fails.append("missing evidence file not flagged")
    if fails:
        print("result_provenance selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("result_provenance selftest: PASS (tier mapping incl. conservative default, FINAL-requires-"
          "tier1, PROVISIONAL allowed, fabricated/missing evidence caught)")
    return 0


if __name__ == "__main__":
    import sys
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(base)
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    if "--migrate" in sys.argv:
        added, changed, rows = migrate(dry_run="--dry-run" in sys.argv)
        print(f"columns added: {added or 'none'}; rows back-filled: {changed}")
    probs, stats = audit_rows(load())
    print("provenance stats:", stats)
    print("problems:", len(probs))
    for p in probs[:20]:
        print("  ! " + p)
    raise SystemExit(1 if probs else 0)
