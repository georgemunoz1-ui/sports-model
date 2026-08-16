#!/usr/bin/env python3
"""Per-game acquisition ledgers: append-only writes, successor selection, forbidden-state gate.

WHY (2026-08-16, owner directive): the 8/15 contaminated-capture incident was handled with a
DATE-LEVEL disposition ("defer the slate"), which let one poisoned observation blank fourteen clean
games. The structural fix is that acquisition state is per GAME, is append-only, and that
date-level states are a gate failure rather than a style choice.

Ledger layout
  data/<sport>/acquisition_ledger_<YYYY-MM-DD>.jsonl   MLB/WNBA acquisition queues
  data/nfl/results_ledger.jsonl                        NFL per-game result+grade states (all dates)

Row contract (minimum): date, game (or slot), state, recorded_utc. Optional: revision (default 1),
official_id, score_observed, detail, queue.

Successor rule: for a given (sport, date, game) the CURRENT state is the row with the highest
`revision`; every historical revision is retained and still validated. A successor never rewrites
its predecessor — that is what makes a correction auditable.

Forbidden states (date-level deferral, banned by owner ruling 2026-08-16):
    NOT_CAPTURED_DATE, DEFERRED_DATE, SLATE_QUARANTINED, DATE_DEFERRED, NOT_CAPTURED
A per-game quarantine is legal and REQUIRED to keep queue OPEN — quarantine never closes a game.

Modes: (default) summary | --gate exit 1 on violations | --selftest fixture battery
"""
from __future__ import annotations
import glob, json, os, sys, collections

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

FORBIDDEN_STATES = {"NOT_CAPTURED_DATE", "DEFERRED_DATE", "SLATE_QUARANTINED",
                    "DATE_DEFERRED", "NOT_CAPTURED"}
# Enumerated historical duplicate-revision exception. 2026-08-16: the 8/13 ledger was written with
# TWO revision-1 rows for MIL@LAD — one carrying the tier-3 score observation (5-4) evicted from
# results.csv, one carrying the tier-1 series-state winner proof. Both are true statements about
# different layers, but they are ambiguous as "current state", so a revision-2 consolidated row was
# appended. The rev-1 pair is retained (append-only) and named here rather than silently tolerated:
# any OTHER duplicate revision still fails the gate. Same pattern as the G2 grade-addendum whitelist.
KNOWN_DUP_REV = {("mlb", "2026-08-13", "MIL@LAD", 1)}
# a quarantined game MUST keep its queue open; closing it would lose the unresolved game
QUARANTINE_STATES = {"ECHO_QUARANTINED_AND_QUEUED", "QUARANTINED_CONFLICT"}
TERMINAL_STATES = {"GRADED_CORRECT", "GRADED_WRONG", "TIE_EXCLUDED", "FINAL_TIER1"}


def ledger_paths():
    paths = sorted(glob.glob("data/*/acquisition_ledger_*.jsonl"))
    if os.path.exists("data/nfl/results_ledger.jsonl"):
        paths.append("data/nfl/results_ledger.jsonl")
    return paths


def _sport_of(path):
    return path.split("/")[1]


def load(path):
    rows = []
    for i, line in enumerate(open(path), 1):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{i} is not valid JSON: {e}")
        r.setdefault("revision", 1)
        r["_path"] = path
        r["_line"] = i
        rows.append(r)
    return rows


def load_all():
    out = []
    for p in ledger_paths():
        out.extend(load(p))
    return out


def current_states(rows=None):
    """Newest successor per (sport, date, game). Historical revisions are retained, not dropped."""
    rows = rows if rows is not None else load_all()
    best = {}
    for r in rows:
        key = (_sport_of(r["_path"]), r.get("date"), r.get("game") or r.get("matchup") or f"slot{r.get('slot')}")
        prev = best.get(key)
        if prev is None or r.get("revision", 1) > prev.get("revision", 1):
            best[key] = r
    return best


def validate(rows=None):
    """Returns list of violation strings. Empty list == ledgers are structurally sound."""
    rows = rows if rows is not None else load_all()
    v = []
    seen = collections.Counter()
    for r in rows:
        where = f'{r["_path"]}:{r["_line"]}'
        if not r.get("date"):
            v.append(f"{where}: row has no date")
        ident = r.get("game") or r.get("matchup") or (f"slot{r['slot']}" if r.get("slot") else None)
        if not ident:
            v.append(f"{where}: row identifies no game (needs game, matchup, or slot)")
        if not r.get("recorded_utc"):
            v.append(f"{where}: row has no recorded_utc")
        state = r.get("state") or r.get("grade_state")
        if not state:
            v.append(f"{where}: row has no state/grade_state")
        elif state in FORBIDDEN_STATES:
            v.append(f"{where}: FORBIDDEN date-level state {state!r} (owner ruling: per-game only)")
        if state in QUARANTINE_STATES and r.get("queue") == "CLOSED":
            v.append(f"{where}: quarantined game has a CLOSED queue — quarantine must not close a game")
        key = (_sport_of(r["_path"]), r.get("date"), ident, r.get("revision", 1))
        seen[key] += 1
    for key, n in seen.items():
        if n > 1 and key not in KNOWN_DUP_REV:
            v.append(f"duplicate ledger revision {key[3]} for {key[0]} {key[1]} {key[2]} ({n} rows)")
    return v


def append_state(path, row):
    """Append-only write. Refuses to emit a revision that already exists for that game."""
    required = {"date", "state", "recorded_utc"}
    missing = required - set(row)
    if missing:
        raise ValueError(f"append_state refused: missing {sorted(missing)}")
    if not (row.get("game") or row.get("matchup") or row.get("slot")):
        raise ValueError("append_state refused: row identifies no game")
    if row.get("state") in FORBIDDEN_STATES:
        raise ValueError(f"append_state refused: forbidden date-level state {row['state']!r}")
    rev = row.setdefault("revision", 1)
    ident = row.get("game") or row.get("matchup") or f"slot{row.get('slot')}"
    if os.path.exists(path):
        for r in load(path):
            r_ident = r.get("game") or r.get("matchup") or f"slot{r.get('slot')}"
            if r_ident == ident and r.get("date") == row["date"] and r.get("revision", 1) == rev:
                raise ValueError(f"append_state refused: revision {rev} already exists for "
                                 f"{row['date']} {ident} — successors must increment revision")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps({k: v for k, v in row.items() if not k.startswith("_")}) + "\n")
    return True


def summary():
    rows = load_all()
    cur = current_states(rows)
    by_sport = collections.Counter(k[0] for k in cur)
    by_state = collections.Counter((r.get("state") or r.get("grade_state")) for r in cur.values())
    open_q = sum(1 for r in cur.values() if r.get("queue") == "OPEN")
    return {"files": len(ledger_paths()), "rows_total": len(rows), "games_current": len(cur),
            "by_sport": dict(by_sport), "by_state": dict(by_state), "open_queue": open_q}


def selftest():
    import tempfile
    fails = []
    v = validate()
    if v:
        fails.append(f"live ledgers have {len(v)} violation(s): {v[:3]}")
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "acquisition_ledger_2026-01-01.jsonl")
        append_state(p, {"date": "2026-01-01", "game": "A@B", "state": "UNRESOLVED_QUEUED",
                         "recorded_utc": "2026-01-01T00:00:00Z", "queue": "OPEN"})
        # duplicate revision must be refused
        try:
            append_state(p, {"date": "2026-01-01", "game": "A@B", "state": "FINAL_TIER1",
                             "recorded_utc": "2026-01-01T01:00:00Z"})
            fails.append("duplicate revision-1 append was NOT refused")
        except ValueError:
            pass
        # successor with revision 2 is accepted and wins selection
        append_state(p, {"date": "2026-01-01", "game": "A@B", "state": "FINAL_TIER1", "revision": 2,
                         "recorded_utc": "2026-01-01T02:00:00Z"})
        rows = load(p)
        if len(rows) != 2:
            fails.append(f"append-only broken: expected 2 retained rows, got {len(rows)}")
        best = max(rows, key=lambda r: r["revision"])
        if best["state"] != "FINAL_TIER1":
            fails.append("successor selection did not pick the highest revision")
        # forbidden date-level state must be refused at write time AND flagged at read time
        try:
            append_state(p, {"date": "2026-01-01", "game": "C@D", "state": "NOT_CAPTURED",
                             "recorded_utc": "2026-01-01T03:00:00Z"})
            fails.append("forbidden date-level state was NOT refused on write")
        except ValueError:
            pass
        with open(p, "a") as f:
            f.write(json.dumps({"date": "2026-01-01", "game": "E@F", "state": "SLATE_QUARANTINED",
                                "recorded_utc": "2026-01-01T04:00:00Z"}) + "\n")
        smuggled = [x for x in validate(load(p)) if "FORBIDDEN" in x]
        if not smuggled:
            fails.append("hand-written forbidden state was NOT caught by validate()")
        # quarantine with a closed queue must be caught
        with open(p, "a") as f:
            f.write(json.dumps({"date": "2026-01-01", "game": "G@H", "state": "ECHO_QUARANTINED_AND_QUEUED",
                                "recorded_utc": "2026-01-01T05:00:00Z", "queue": "CLOSED"}) + "\n")
        if not [x for x in validate(load(p)) if "CLOSED queue" in x]:
            fails.append("quarantine-with-closed-queue was NOT caught")
    if fails:
        print("acquisition_ledger selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("acquisition_ledger selftest: PASS (append-only enforced, duplicate revision refused, "
          "successor selection correct, date-level states refused on write and caught on read, "
          "quarantine cannot close a queue)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    viol = validate()
    s = summary()
    print(f"ledgers: {s['files']} files, {s['rows_total']} rows, {s['games_current']} current game states "
          f"{s['by_sport']}, open queue {s['open_queue']}")
    for k, n in sorted(s["by_state"].items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {n}")
    if viol:
        print(f"VIOLATIONS: {len(viol)}")
        for x in viol[:20]:
            print("  ! " + x)
    raise SystemExit(1 if (viol and "--gate" in sys.argv) else 0)
