#!/usr/bin/env python3
"""SOURCE ARTIFACT GATE — a hash of my own transcription is not the identity of a source.

OWNER DIRECTIVE 2026-08-24: "Downgrade OWNER_RELAY evidence to provisional until an immutable
addendum identifies the exact Tier-1 source artifact."

THE DISTINCTION THIS TURNS ON, AND WHY I MISSED IT. When the owner relayed the 8/23 scoreboard I
wrote data/mlb/evidence/2026-08-23_owner_relay_finals.json, hashed it, and bound fifteen canonical
rows and fifteen grades to that hash. Every one of those bindings verifies. None of them means what
a tier-1 binding is supposed to mean.

A hash over my own transcription proves EXACTLY ONE THING: that I have not altered the transcription
since writing it. It is tamper-evidence on my own record. It says nothing about whether the numbers
came from an official scoreboard, because the artifact it commits to IS MY RECORD, not the
scoreboard. "MLB scoreboard" names a CLASS OF SOURCE; a tier-1 binding needs the ARTIFACT — the
specific feed, page or box that was read, identified precisely enough that another party could go
and check it.

So the gate is not "does this row cite a hashed file". Almost every relayed row does, which is why
an artifact-existence check passes 112 of 123 owner-family rows and learns nothing. The gate is:

    does the cited evidence record IDENTIFY THE SOURCE ARTIFACT IT TRANSCRIBES?

A record that names a retrievable official artifact (an endpoint, a game feed, a box page, a
captured official document) can be checked by someone else. A record that names a class ("official
scoreboard", "owner board", "relay") cannot, however well hashed.

WHAT FAILING MEANS, AND WHAT IT DOES NOT. Failing does not mean the scores are wrong. The 8/23
scores reproduce the owner's own summary statistics exactly and are almost certainly correct.
Failing means the row may not claim FINAL, may not populate canonical results, and may not back a
promotion-grade grade — it rests at PROVISIONAL, which is a legitimate state and not an accusation.
An immutable addendum naming the artifact promotes it, and that is a cheap, ordinary act.

TRANSCRIPTION-QUALITY EVIDENCE IS STILL EVIDENCE. A record whose internal arithmetic reproduces the
relayer's own stated summary (as the 8/23 relay does: home 10-5 and mean total 9.40 both recompute
from the fifteen rows) is better evidence than one that does not, and this module reports that
separately. It is a consistency check on the transcription. It is not a source.

API
  identifies_source_artifact(record) -> (bool, reason)
  audit_rows(rows, evidence_loader) -> per-row verdicts and the table-wide blast radius
  required_addendum_fields()        -> what an addendum must carry to promote a row
"""
from __future__ import annotations

MODULE_ID = "source_artifact_gate"

import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ARTIFACT_IDENTIFIED = "SOURCE_ARTIFACT_IDENTIFIED"
CLASS_ONLY = "SOURCE_NAMED_BY_CLASS_NOT_ARTIFACT"
NOT_RETAINED = "SOURCE_NAMED_ARTIFACT_NOT_RETAINED"
NO_RECORD = "NO_EVIDENCE_RECORD"
UNREADABLE = "EVIDENCE_RECORD_UNREADABLE"

# A source artifact is retrievable. These are the shapes that make it so.
ARTIFACT_FIELDS = ("source_artifact", "source_url", "source_endpoint", "official_artifact",
                   "source_artifact_uri", "game_feed", "box_url")

# Words that name a CLASS of source. On their own they identify nothing.
CLASS_WORDS = ("scoreboard", "official scoreboard", "results", "board", "relay", "owner board",
               "owner relay", "paste", "screenshot", "summary")

# An OFFICIAL ENDPOINT named in a row's source string. These rows are not owner relays: the source
# is authoritative and specific. What is missing is the retained payload — the fetch happened while a
# rail existed and nothing was kept, so the claim cannot be re-verified from this repository. That is
# a DIFFERENT defect from "the source is a class, not an artifact", and it has a different remedy:
# re-fetching the same endpoint restores it, whereas only the owner can resupply a relay.
OFFICIAL_ENDPOINT_MARKERS = ("statsapi", "savant", "mlb.com", "baseballsavant", "wnba_stats",
                             "wnba.com", "nfl.com")

# Marks that a value is retrievable rather than descriptive.
_RETRIEVABLE = re.compile(r"(https?://|/api/|\.mlb\.com|statsapi|gamePk\s*=?\s*\d|/gameday/|"
                          r"/boxscore|game_id\s*=?\s*\d)", re.I)


def _looks_retrievable(v):
    return isinstance(v, str) and bool(_RETRIEVABLE.search(v))


def source_named_not_retained(row):
    """Does this ROW name an official endpoint while retaining no payload?

    Separated from identifies_source_artifact, which judges the evidence RECORD. This judges the
    row's own source string, because for 92% of the canonical pool there is no evidence record at
    all — the source names statsapi and nothing was kept.
    """
    src = (row or {}).get("source") or ""
    ep = (row or {}).get("evidence_path") or ""
    sh = (row or {}).get("evidence_sha256") or ""
    named = any(m in src.lower() for m in OFFICIAL_ENDPOINT_MARKERS)
    retained = bool(ep and sh)
    return bool(named and not retained)


def identifies_source_artifact(record):
    """Does this evidence record name a retrievable official artifact, or only a class of source?"""
    if record is None:
        return False, NO_RECORD
    if not isinstance(record, dict):
        return False, UNREADABLE
    for k in ARTIFACT_FIELDS:
        v = record.get(k)
        if _looks_retrievable(v):
            return True, ARTIFACT_IDENTIFIED
        if isinstance(v, list) and any(_looks_retrievable(x) for x in v):
            return True, ARTIFACT_IDENTIFIED
    # per-game artifacts count too
    for g in (record.get("games") or []):
        if isinstance(g, dict) and any(_looks_retrievable(g.get(k)) for k in ARTIFACT_FIELDS):
            return True, ARTIFACT_IDENTIFIED
    return False, CLASS_ONLY


def internal_consistency(record):
    """Does the transcription reproduce the relayer's own stated summary? Evidence quality, not source."""
    chk = record.get("arithmetic_check") if isinstance(record, dict) else None
    if not isinstance(chk, dict):
        return None
    ok = (chk.get("home_record_recomputed") == chk.get("owner_stated")
          or chk.get("mean_total_recomputed") == chk.get("owner_stated"))
    return {"present": True, "reproduces_relayer_summary": bool(ok),
            "note": "a consistency check on the transcription; NOT a source and never promotes a row"}


def _load(path):
    p = path if os.path.isabs(path) else os.path.join(BASE, path)
    if not path or not os.path.exists(p):
        return None
    if not p.endswith(".json"):
        return {"_non_json": True}          # a raw capture; judged by its own fields, which it has none of
    try:
        return json.load(open(p))
    except Exception:
        return None


def audit_rows(rows, loader=_load, owner_only=True):
    """Per-row verdicts plus the blast radius, so the scale of a downgrade is visible before it runs."""
    per, cache = [], {}
    for r in rows:
        src = (r.get("source") or "")
        if owner_only and "owner" not in src.lower():
            continue
        ep = r.get("evidence_path") or ""
        if ep not in cache:
            cache[ep] = loader(ep)
        ok, why = identifies_source_artifact(cache[ep])
        if not ok and source_named_not_retained(r):
            why = NOT_RETAINED
        per.append({"game_id": r.get("game_id"), "date": r.get("date"), "source": src,
                    "evidence_path": ep, "identifies_artifact": ok, "reason": why,
                    "claims_final": r.get("result_status") == "FINAL",
                    "tier": r.get("source_tier")})
    failing = [p for p in per if not p["identifies_artifact"]]
    not_retained = [p for p in failing if p["reason"] == NOT_RETAINED]
    would_downgrade = [p for p in failing if p["claims_final"]]
    dates = sorted({p["date"] for p in would_downgrade})
    return {
        "n_owner_rows": len(per),
        "n_failing_artifact_identification": len(failing),
        "n_source_named_artifact_not_retained": len(not_retained),
        "remedy_split": {
            NOT_RETAINED: "re-fetch the named endpoint and retain the payload; possible without the "
                          "owner once any rail exists",
            CLASS_ONLY: "only the party who read the source can identify it",
        },
        "n_currently_claiming_FINAL": len(would_downgrade),
        "affected_dates": dates,
        "n_affected_dates": len(dates),
        "by_date": {d: sum(1 for p in would_downgrade if p["date"] == d) for d in dates},
        "per_row": per,
        "rule": "a hash over a self-authored transcription is tamper-evidence on that record, not "
                "the identity of the source it transcribes",
    }


def required_addendum_fields():
    return {
        "purpose": "promote a PROVISIONAL owner-relay row to FINAL by identifying its source artifact",
        "must_carry": ["the specific retrievable artifact per game or per slate — a feed endpoint, "
                       "a gamePk, a box page, or a captured official document",
                       "the instant it was retrieved",
                       "who retrieved it"],
        "must_not_be": ["a class of source ('official scoreboard', 'owner board')",
                        "a hash of the transcription itself, which proves only that I did not "
                        "alter my own record"],
        "immutability": "the addendum is its own file. The evidence record it promotes is hash-cited "
                        "by result rows and grades and may never be edited — the 2026-08-21 late "
                        "final established that shape and it holds here.",
    }


# =================================================================================================
def selftest():
    f = []

    # --- the 8/23 record's own shape: hashed, internally consistent, and NOT a source ------------
    relay = {"source_family": "OWNER_RELAY", "received_from": "owner message: official MLB scoreboard",
             "arithmetic_check": {"home_record_recomputed": "10-5", "owner_stated": "10-5"},
             "games": [{"away": "TOR", "home": "NYY", "away_score": 3, "home_score": 8}]}
    ok, why = identifies_source_artifact(relay)
    if ok or why != CLASS_ONLY:
        f.append(f"a relay naming only a class must fail, got {ok} {why}")
    ic = internal_consistency(relay)
    if not ic or not ic["reproduces_relayer_summary"]:
        f.append("internal consistency must be reported when the record carries the check")
    if ic and "NOT a source" not in ic["note"]:
        f.append("internal consistency must say it is not a source")

    # --- a record that DOES identify an artifact -------------------------------------------------
    for good in ({"source_url": "https://statsapi.mlb.com/api/v1.1/game/823509/feed/live"},
                 {"source_artifact": "https://www.mlb.com/gameday/823509/final/box"},
                 {"games": [{"source_endpoint": "/api/v1.1/game/823509/feed/live"}]},
                 {"source_artifact": ["https://statsapi.mlb.com/api/v1/schedule?date=2026-08-23"]}):
        o, w = identifies_source_artifact(good)
        if not o:
            f.append(f"a retrievable artifact must pass: {good} -> {w}")

    # --- a plausible-looking value that is still only a class ------------------------------------
    for bad in ({"source_artifact": "official MLB scoreboard"},
                {"source_url": "the owner's board"},
                {"source_artifact": "WNBA results"},
                {"source_artifact": ""},
                {"source_artifact": None}):
        o, w = identifies_source_artifact(bad)
        if o:
            f.append(f"a class name must not pass as an artifact: {bad}")
    if identifies_source_artifact(None) != (False, NO_RECORD):
        f.append("a missing record identifies nothing and must not pass")
    if identifies_source_artifact("a string")[1] != UNREADABLE:
        f.append("a non-dict record is UNREADABLE")
    if internal_consistency({"no": "check"}) is not None:
        f.append("no arithmetic_check means no consistency claim, not a passing one")

    # --- an official endpoint named with nothing retained is its OWN grade -----------------------
    if not source_named_not_retained({"source": "statsapi", "evidence_path": "", "evidence_sha256": ""}):
        f.append("a statsapi row with no retained payload must grade as NOT_RETAINED")
    if source_named_not_retained({"source": "statsapi", "evidence_path": "e.json",
                                  "evidence_sha256": "abc"}):
        f.append("a named endpoint WITH a retained hashed payload is not NOT_RETAINED")
    if source_named_not_retained({"source": "owner relay official scoreboard",
                                  "evidence_path": "", "evidence_sha256": ""}):
        f.append("an owner relay names no endpoint and must not grade as NOT_RETAINED")
    # a path with no hash is NOT a retained artifact: nothing pins its content, so the row grades
    # NOT_RETAINED exactly as one with no path at all
    if not source_named_not_retained({"source": "statsapi", "evidence_path": "e.json",
                                      "evidence_sha256": ""}):
        f.append("a path without a hash is not a retained artifact and must grade NOT_RETAINED")
    for bad in (None, {}, {"source": None}):
        if source_named_not_retained(bad):
            f.append(f"{bad!r} must not grade as NOT_RETAINED")

    # --- the audit reports blast radius, not just a boolean --------------------------------------
    rows = [{"game_id": "a", "date": "2026-08-23", "source": "owner relay official scoreboard",
             "evidence_path": "relay.json", "result_status": "FINAL", "source_tier": "1"},
            {"game_id": "b", "date": "2026-08-23", "source": "owner relay official scoreboard",
             "evidence_path": "relay.json", "result_status": "FINAL", "source_tier": "1"},
            {"game_id": "c", "date": "2026-08-21", "source": "owner relay official scoreboard",
             "evidence_path": "good.json", "result_status": "FINAL", "source_tier": "1"},
            {"game_id": "d", "date": "2026-08-20", "source": "tier1 web finals",
             "evidence_path": "good.json", "result_status": "FINAL", "source_tier": "1"}]
    loader = lambda p: relay if p == "relay.json" else {"source_url": "https://statsapi.mlb.com/api/v1/x"}
    a = audit_rows(rows, loader)
    if a["n_owner_rows"] != 3:
        f.append(f"non-owner rows must be excluded by default, got {a['n_owner_rows']}")
    if a["n_currently_claiming_FINAL"] != 2:
        f.append(f"exactly two rows should be downgraded, got {a['n_currently_claiming_FINAL']}")
    if a["affected_dates"] != ["2026-08-23"]:
        f.append(f"only the failing date is affected, got {a['affected_dates']}")
    if a["by_date"].get("2026-08-23") != 2:
        f.append("the per-date count must be reported")
    # the two failing classes are counted separately, because they have different remedies
    mixed = rows + [{"game_id": "s1", "date": "2026-04-01", "source": "statsapi",
                     "evidence_path": "", "evidence_sha256": "", "result_status": "FINAL",
                     "source_tier": "1"}]
    # the loader must return None for a row with NO evidence path — that is the real shape of 96%
    # of the canonical pool, and a loader that invents a record for it would hide the whole finding
    strict = lambda p: None if not p else loader(p)
    ma = audit_rows(mixed, strict, owner_only=False)
    if ma["n_source_named_artifact_not_retained"] != 1:
        f.append(f"a named-but-unretained row must be counted separately, got "
                 f"{ma['n_source_named_artifact_not_retained']}")
    if NOT_RETAINED not in ma["remedy_split"] or CLASS_ONLY not in ma["remedy_split"]:
        f.append("the audit must state the different remedy for each failing class")
    if ma["remedy_split"][NOT_RETAINED] == ma["remedy_split"][CLASS_ONLY]:
        f.append("the two remedies must not be the same string")
    # and each must say the thing that distinguishes it: one is re-fetchable without the owner,
    # the other is only resupplyable by whoever read the source
    if "re-fetch" not in ma["remedy_split"][NOT_RETAINED]:
        f.append("the NOT_RETAINED remedy must say the endpoint can be re-fetched")
    if "only the party who read the source" not in ma["remedy_split"][CLASS_ONLY]:
        f.append("the CLASS_ONLY remedy must say only the reader can identify it")

    everything = audit_rows(rows, loader, owner_only=False)
    if everything["n_owner_rows"] != 4:
        f.append("owner_only=False must audit every row")
    # a row that already rests at PROVISIONAL is not counted as a NEW downgrade
    prov = audit_rows([dict(rows[0], result_status="PROVISIONAL")], loader)
    if prov["n_currently_claiming_FINAL"] != 0:
        f.append("an already-provisional row is not a new downgrade")
    if prov["n_failing_artifact_identification"] != 1:
        f.append("but it still fails artifact identification and must be counted as such")

    # --- the addendum spec forbids the mistake that caused this ----------------------------------
    spec = required_addendum_fields()
    if not any("hash of the transcription" in x for x in spec["must_not_be"]):
        f.append("the addendum spec must forbid a transcription hash standing in for a source")

    for x in f:
        print("FAIL:", x)
    if not f:
        print("source_artifact_gate selftest: OK")
    return f


MUTANTS = [
    ("a named endpoint with no retained payload is graded as a class-only failure",
     '        if not ok and source_named_not_retained(r):\n            why = NOT_RETAINED', "        if False:\n            why = NOT_RETAINED"),
    ("an unretained payload counts as retained",
     "    retained = bool(ep and sh)", "    retained = bool(ep or sh)"),
    ("every source counts as an official endpoint",
     "    named = any(m in src.lower() for m in OFFICIAL_ENDPOINT_MARKERS)", "    named = True"),
    ("the two failing classes are pooled into one count",
     '        "n_source_named_artifact_not_retained": len(not_retained),', '        "n_source_named_artifact_not_retained": 0,'),
    ("the differing remedies stop being stated",
     '            CLASS_ONLY: "only the party who read the source can identify it",',
     '            CLASS_ONLY: "re-fetch the named endpoint and retain the payload; possible without the ",'),
    ("a class name passes as a source artifact",
     "    return False, CLASS_ONLY", "    return True, ARTIFACT_IDENTIFIED"),
    ("any non-empty value passes as an artifact",
     "        if _looks_retrievable(v):", "        if v:"),
    ("the retrievability pattern stops requiring a locator",
     '_RETRIEVABLE = re.compile(r"(https?://|/api/|\\.mlb\\.com|statsapi|gamePk\\s*=?\\s*\\d|/gameday/|"\n                          r"/boxscore|game_id\\s*=?\\s*\\d)", re.I)',
     '_RETRIEVABLE = re.compile(r".", re.I)'),
    ("per-game artifacts stop being checked",
     '    for g in (record.get("games") or []):', "    for g in []:"),
    ("a missing evidence record is treated as identifying its source",
     "    if record is None:\n        return False, NO_RECORD", "    if record is None:\n        return True, NO_RECORD"),
    ("internal consistency is allowed to stand in for a source",
     '    return {"present": True, "reproduces_relayer_summary": bool(ok),\n            "note": "a consistency check on the transcription; NOT a source and never promotes a row"}',
     '    return {"present": True, "reproduces_relayer_summary": bool(ok),\n            "note": "good enough"}'),
    ("a record with no arithmetic check reports a passing consistency",
     "    if not isinstance(chk, dict):\n        return None", '    if not isinstance(chk, dict):\n        return {"present": True, "reproduces_relayer_summary": True, "note": "NOT a source"}'),
    ("the audit stops reporting how many rows it would downgrade",
     '        "n_currently_claiming_FINAL": len(would_downgrade),', '        "n_currently_claiming_FINAL": 0,'),
    ("the audit stops reporting which dates are affected",
     '    dates = sorted({p["date"] for p in would_downgrade})', "    dates = []"),
    ("already-provisional rows are counted as new downgrades",
     '    would_downgrade = [p for p in failing if p["claims_final"]]', "    would_downgrade = failing"),
    ("the owner-only filter swallows every row",
     '        if owner_only and "owner" not in src.lower():', "        if owner_only:"),
    ("the owner-only filter stops filtering",
     '        if owner_only and "owner" not in src.lower():', "        if False:"),
    ("the addendum spec stops forbidding a transcription hash",
     '        "must_not_be": ["a class of source (\'official scoreboard\', \'owner board\')",\n                        "a hash of the transcription itself, which proves only that I did not "\n                        "alter my own record"],',
     '        "must_not_be": [],'),
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
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True, timeout=120)
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
    if "--audit" in sys.argv:
        import csv as _csv
        rows = list(_csv.DictReader(open(os.path.join(BASE, "data/backfill/mlb/2026/results.csv"))))
        a = audit_rows(rows)
        print(json.dumps({k: v for k, v in a.items() if k != "per_row"}, indent=1))
        sys.exit(0)
    print(__doc__)
