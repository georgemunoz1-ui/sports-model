"""Single source of truth for the K-prop authorization gate counter.

Why this file exists. `decision_policy_version` was added to state.json on 2026-07-27 and
the prospective gate was set to 0/100 by hand. That was declarative only: the gate string
is REWRITTEN by harness/ingest_kquote.py every time a play is registered, from
`record_w + record_l`, which counts every settled row regardless of the policy that
produced it. The hand-set 0/100 would have been silently clobbered back to 9/100 on the
next --register run. This module makes the counter computed rather than asserted, and
healthcheck fails if the stored string and the computed one disagree.

The three numbers, kept strictly separate:

  prospective   plays graded under the CURRENT policy. This is the gate. Starts at 0.
  historical    every settled play ever, whatever produced it. Audit trail, never
                re-graded, never retro-dropped (R6). Currently 9.
  retrospective how many historical plays the current guards would have admitted.
                EXPLORATORY ONLY. Never gate progress. See the docstring on
                retrospective_compatibility for what it can and cannot see.

Historical rows carry no policy tag and none is invented for them (R1: absence is
recorded as absence). An untagged row is simply not a current-policy row.
"""

from __future__ import annotations

import json
import os

GATE_N = 100
SETTLED = ("WIN", "LOSS")


def _short_line() -> float:
    """The current intake guard's threshold, read from the module that enforces it.

    Imported lazily and not at module scope: ingest_kquote imports this module to write
    the gate line, so a module-level import here is a cycle -- and because SHORT_LINE is
    defined *below* that import in ingest_kquote, the cycle fails at load time rather than
    degrading quietly. Read it here instead of redefining it, so the guard and the
    statistic that reports on the guard can never drift apart.
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ingest_kquote import SHORT_LINE
    return float(SHORT_LINE)


def current_policy(state: dict) -> str:
    """The policy version the prospective gate is counting."""
    return state["decision_policy_version"]["current"]


def settled_rows(state: dict) -> list[dict]:
    """Graded rows that actually settled. A VOID returns the stake and decides nothing."""
    return [r for r in state["ledgers"]["kprops_paper"]["graded"] if r.get("result") in SETTLED]


def prospective_rows(state: dict) -> list[dict]:
    """Settled rows produced by the current policy. These are the only gate progress."""
    cur = current_policy(state)
    return [r for r in settled_rows(state) if r.get("decision_policy_version") == cur]


def untagged_rows(state: dict) -> list[dict]:
    """Settled rows with no policy tag -- everything graded before the tag existed."""
    return [r for r in settled_rows(state) if r.get("decision_policy_version") is None]


def retrospective_compatibility(state: dict) -> dict:
    """How many untagged historical rows the CURRENT guards would have admitted.

    EXPLORATORY ONLY, and narrower than it looks. The only current criterion that can be
    checked against a stored row is the short-line hold, because a stored row carries its
    posted line. The rest of the selector -- EV>0, edge>=0.04, |proj-line|>=0.8 -- depends
    on E[K] as it stood before that start, and recomputing it now would read a pitcher log
    that already contains the start being priced. That is the R2 look-ahead leak that
    resolve_ek() exists to block, so it is not attempted here.

    So this is a SHORT-LINE-GUARD-ONLY figure. It is not "8 of 9 plays are still valid";
    it is "8 of 9 clear the one guard that can be checked without cheating". It is never
    gate progress: those rows were selected under rules that no longer exist, and choosing
    which to keep would be done with their results already known.
    """
    short_line = _short_line()
    rows = untagged_rows(state)
    passes = [r for r in rows if float(r["line"]) > short_line]
    blocked = [r for r in rows if float(r["line"]) <= short_line]
    return {
        "status": "EXPLORATORY - never gate progress",
        "checkable_criterion": "short-line intake guard only (posted line > %.1f K)" % short_line,
        "not_checked": "EV>0, edge>=0.04, |proj-line|>=0.8 -- all need as-of E[K], and recomputing "
                       "it now would read a log containing the start being priced (R2).",
        "n_untagged_settled": len(rows),
        "n_pass": len(passes),
        "n_blocked": len(blocked),
        "blocked_rows": ["%s %s %.1f" % (r["pitcher"], r.get("side", ""), float(r["line"])) for r in blocked],
        "statistic": "%d of %d" % (len(passes), len(rows)),
    }


def gate_counts(state: dict) -> dict:
    """Everything the gate needs, computed from the ledger."""
    L = state["ledgers"]["kprops_paper"]
    settled = settled_rows(state)
    prospective = prospective_rows(state)
    cur = current_policy(state)
    pending = L.get("plays_pending", [])
    return {
        "policy_version": cur,
        "prospective_graded": len(prospective),
        "prospective_target": GATE_N,
        "prospective_units": round(sum(float(r.get("pl", 0.0)) for r in prospective), 2),
        "historical_settled": len(settled),
        "historical_record": "%d-%d" % (L["record_w"], L["record_l"]),
        "historical_units": L["units"],
        "untagged_settled": len(untagged_rows(state)),
        "pending": len(pending),
        "pending_under_current_policy": sum(1 for p in pending if p.get("decision_policy_version") == cur),
        "retrospective_compatibility": retrospective_compatibility(state),
    }


def progress_string(state: dict) -> str:
    """The canonical gate progress line. ingest_kquote and healthcheck both use this."""
    c = gate_counts(state)
    s = "%d/%d graded under %s" % (c["prospective_graded"], c["prospective_target"], c["policy_version"])
    if c["pending"]:
        s += " (+%d pending, %d under current policy)" % (c["pending"], c["pending_under_current_policy"])
    s += " [historical audit: %d settled, %s, %+.2fu, untagged]" % (
        c["historical_settled"], c["historical_record"], c["historical_units"])
    return s


def _load(path: str = "state.json") -> dict:
    return json.load(open(path))


def _selftest() -> None:
    """Assertions that must hold on the real ledger, not on a fixture."""
    S = _load()
    c = gate_counts(S)
    cur = current_policy(S)

    # 1. the gate counts only current-policy rows, and there are none yet
    assert c["prospective_graded"] == 0, "expected 0 prospective, got %d" % c["prospective_graded"]

    # 2. the historical audit is preserved in full and is NOT the gate
    assert c["historical_settled"] == 9, "historical settled changed: %d" % c["historical_settled"]
    assert c["historical_record"] == "4-5", c["historical_record"]
    assert abs(c["historical_units"] - (-1.61)) < 1e-9, c["historical_units"]
    assert c["untagged_settled"] == 9, "expected all 9 historical rows untagged"
    assert c["prospective_graded"] != c["historical_settled"], "gate must not equal the audit trail"

    # 3. VOID is excluded from settled counts
    graded_rows = S["ledgers"]["kprops_paper"]["graded"]
    assert len(graded_rows) == 10 and len(settled_rows(S)) == 9, "void must not count as settled"

    # 4. the retrospective statistic is 8 of 9 and is flagged exploratory
    r = c["retrospective_compatibility"]
    assert r["statistic"] == "8 of 9", r["statistic"]
    assert r["n_blocked"] == 1 and "Buehler" in r["blocked_rows"][0], r["blocked_rows"]
    assert r["status"].startswith("EXPLORATORY")

    # 5. no historical row was given an invented policy tag
    assert all(r.get("decision_policy_version") is None for r in untagged_rows(S))

    # 6. the string stored in state.json matches the computed one
    stored = S["gates"]["kprops_go_live"]["progress"]
    assert stored == progress_string(S), "stored gate string has drifted:\n  stored:   %s\n  computed: %s" % (
        stored, progress_string(S))

    print("policy_gate self-test: PASS")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        S = _load()
        c = gate_counts(S)
        print(progress_string(S))
        print()
        print(json.dumps(c, indent=2))
