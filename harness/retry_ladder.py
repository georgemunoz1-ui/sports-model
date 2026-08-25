#!/usr/bin/env python3
"""ACQUISITION RETRY LADDER — owner ruling 2026-08-23, on ACQUISITION_EXHAUSTED.

Exhaustion is not the end of a cycle; it is the start of a bounded, narrowing retry schedule.

  PRESERVE     partial evidence survives untouched. Exhaustion never discards what was acquired.
  SCHEDULE     retries at +30m, +2h, +12h from the exhaustion timestamp. Three, not endless.
  NARROW       each retry probes ONLY unresolved games and previously-failed TIER-1 routes. A route
               that already succeeded is not re-probed, and tier-2/3 routes are not retried at all
               because they can never produce a canonical settlement.
  APPEND       capability observations are NEVER overwritten. A later probe adds an observation; it
               does not erase the earlier one. "www.mlb.com was denied at 05:40Z and reachable at
               07:40Z" is two facts, and losing the first one hides the outage.
  GRADE LATE   settle and grade ONLY after tier-1 confirmation, whichever retry supplies it.
  EXPIRE       after the established 36h window an unresolved game becomes UNRESOLVED_SOURCE_GAP —
               a named, permanent disposition, not a silent disappearance and not a guess.
"""
from __future__ import annotations

MODULE_ID = "retry_ladder"

import datetime
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RETRY_OFFSETS_MIN = (30, 120, 720)          # +30m, +2h, +12h
EXPIRY_HOURS = 36                            # the established window
UNRESOLVED_SOURCE_GAP = "UNRESOLVED_SOURCE_GAP"
TIER1 = 1


def _dt(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def _s(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def schedule(exhausted_at):
    """The three retry times. Bounded by construction — there is no fourth."""
    base = _dt(exhausted_at)
    return [{"attempt": i + 1, "offset_minutes": m, "due_utc": _s(base + datetime.timedelta(minutes=m))}
            for i, m in enumerate(RETRY_OFFSETS_MIN)]


def expiry(exhausted_at):
    return _s(_dt(exhausted_at) + datetime.timedelta(hours=EXPIRY_HOURS))


def is_expired(exhausted_at, now):
    return _dt(now) >= _dt(expiry(exhausted_at))


def retry_scope(manifest, unresolved_games, resolved_games=()):
    """What the NEXT retry probes: only failed TIER-1 routes, only unresolved games.

    Deliberately excludes: routes that already succeeded (nothing to gain), and tier-2/3 routes
    (they can never produce a canonical settlement, so retrying them cannot change the outcome that
    matters). Narrowing is the point — a retry that re-probes everything is just the first sweep
    again, and it burns the budget that the +12h attempt needs."""
    seen, routes = set(), []
    for r in manifest:
        key = (r.get("host"), r.get("route"), r.get("tool"))
        if key in seen:
            continue
        if r.get("evidence_tier") != TIER1:
            continue
        if r.get("network_status") in ("HTTP_2XX", "HTTP_3XX"):
            continue
        seen.add(key)
        routes.append({"host": r["host"], "route": r["route"], "tool": r["tool"],
                       "prior_status": r["network_status"], "prior_checked_utc": r.get("checked_utc")})
    games = [g for g in unresolved_games if g not in set(resolved_games)]
    return {"routes": routes, "games": games,
            "excluded_reachable_routes": sum(1 for r in manifest
                                             if r.get("network_status") in ("HTTP_2XX", "HTTP_3XX")),
            "excluded_non_tier1_routes": sum(1 for r in manifest if r.get("evidence_tier") != TIER1)}


def append_observation(manifest, observation):
    """APPEND-ONLY. A new observation is added; the prior one for the same key is never edited.

    Overwriting would erase the outage itself — the very thing a retry ladder exists to document."""
    out = list(manifest)
    prior = [r for r in out
             if (r.get("host"), r.get("route"), r.get("tool"))
             == (observation.get("host"), observation.get("route"), observation.get("tool"))]
    obs = dict(observation)
    obs["supersedes_none"] = True
    obs["prior_observation_count"] = len(prior)
    if prior:
        obs["prior_statuses"] = [p.get("network_status") for p in prior]
    out.append(obs)
    return out


def disposition(game, exhausted_at, now, tier1_confirmed=False):
    """The state of one unresolved game at time `now`."""
    if tier1_confirmed:
        return {"game": game, "state": "TIER1_CONFIRMED",
                "may_grade": True,
                "reason": "tier-1 confirmation supplied; canonical settlement is permitted"}
    if is_expired(exhausted_at, now):
        return {"game": game, "state": UNRESOLVED_SOURCE_GAP, "may_grade": False,
                "reason": (f"no tier-1 confirmation within {EXPIRY_HOURS}h of acquisition "
                           f"exhaustion at {exhausted_at}. This is a NAMED PERMANENT DISPOSITION: "
                           f"the game is not graded, not guessed, and not silently dropped. The "
                           f"forecast stands unsettled and the gap is on the record."),
                "expired_at": expiry(exhausted_at)}
    return {"game": game, "state": "PENDING_TIER1_CONFIRMATION", "may_grade": False,
            "reason": "retry ladder still open", "expires_utc": expiry(exhausted_at)}


def plan(exhausted_at, manifest, unresolved_games, now=None):
    """The whole follow-up plan. Pure; writes nothing."""
    now = now or _s(datetime.datetime.utcnow())
    sched = schedule(exhausted_at)
    return {"exhausted_at_utc": exhausted_at, "now_utc": now,
            "retry_schedule": sched,
            "next_due_utc": next((s["due_utc"] for s in sched if s["due_utc"] > now), None),
            "all_retries_spent": all(s["due_utc"] <= now for s in sched),
            "expiry_utc": expiry(exhausted_at),
            "expired": is_expired(exhausted_at, now),
            "scope": retry_scope(manifest, unresolved_games),
            "dispositions": [disposition(g, exhausted_at, now) for g in unresolved_games],
            "evidence_preserved": True,
            "grading_permitted": False,
            "grading_rule": "settle and grade ONLY after tier-1 confirmation"}


def selftest():
    f = []
    T0 = "2026-08-23T05:45:00Z"
    s = schedule(T0)
    if [x["offset_minutes"] for x in s] != [30, 120, 720]:
        f.append(f"retry offsets wrong: {[x['offset_minutes'] for x in s]}")
    if len(s) != 3:
        f.append(f"retry count is {len(s)}, must be exactly 3 — the ladder is bounded")
    if [x["due_utc"] for x in s] != ["2026-08-23T06:15:00Z", "2026-08-23T07:45:00Z",
                                     "2026-08-23T17:45:00Z"]:
        f.append(f"retry due times wrong: {[x['due_utc'] for x in s]}")
    if expiry(T0) != "2026-08-24T17:45:00Z":
        f.append(f"36h expiry wrong: {expiry(T0)}")

    # ---- expiry boundary
    if is_expired(T0, "2026-08-24T17:44:59Z"):
        f.append("expired one second early")
    if not is_expired(T0, "2026-08-24T17:45:00Z"):
        f.append("did not expire exactly at the 36h boundary")

    # ---- scope NARROWS: only failed tier-1 routes
    man = [
        {"host": "www.mlb.com", "route": "/scores/x", "tool": "curl", "evidence_tier": 1,
         "network_status": "HTTP_403_ORG_PROXY", "checked_utc": T0},
        {"host": "statsapi.mlb.com", "route": "/api/v1/schedule", "tool": "curl",
         "evidence_tier": 1, "network_status": "TIMEOUT", "checked_utc": T0},
        {"host": "api.github.com", "route": "/rate_limit", "tool": "curl", "evidence_tier": 3,
         "network_status": "HTTP_2XX", "checked_utc": T0},
        {"host": "www.espn.com", "route": "/mlb/scoreboard", "tool": "curl", "evidence_tier": 2,
         "network_status": "HTTP_403_ORG_PROXY", "checked_utc": T0},
        {"host": "ok.tier1.com", "route": "/api", "tool": "curl", "evidence_tier": 1,
         "network_status": "HTTP_2XX", "checked_utc": T0},
    ]
    sc = retry_scope(man, ["CIN@AZ", "ATL@PHX"])
    hosts = {r["host"] for r in sc["routes"]}
    if hosts != {"www.mlb.com", "statsapi.mlb.com"}:
        f.append(f"scope wrong: {hosts} — must be failed TIER-1 routes only")
    if "api.github.com" in hosts or "www.espn.com" in hosts:
        f.append("a non-tier-1 route entered the retry scope; it can never produce a canonical "
                 "settlement, so retrying it cannot change the outcome that matters")
    if "ok.tier1.com" in hosts:
        f.append("an already-REACHABLE tier-1 route was scheduled for retry — nothing to gain")
    if sc["games"] != ["CIN@AZ", "ATL@PHX"]:
        f.append(f"unresolved games wrong: {sc['games']}")
    if retry_scope(man, ["CIN@AZ", "ATL@PHX"], resolved_games=["CIN@AZ"])["games"] != ["ATL@PHX"]:
        f.append("a game resolved between retries was probed again")

    # ---- observations are APPEND-ONLY
    obs = {"host": "www.mlb.com", "route": "/scores/x", "tool": "curl",
           "network_status": "HTTP_2XX", "checked_utc": "2026-08-23T06:15:00Z"}
    m2 = append_observation(man, obs)
    if len(m2) != len(man) + 1:
        f.append("append_observation did not append")
    if len(m2) - len([r for r in m2 if r.get("network_status") == "HTTP_403_ORG_PROXY"]) != len(m2) - 2:
        pass
    priors = [r for r in m2 if r["host"] == "www.mlb.com"]
    if len(priors) != 2:
        f.append(f"the earlier www.mlb.com observation was overwritten: {len(priors)} records")
    if priors[0]["network_status"] != "HTTP_403_ORG_PROXY":
        f.append("the ORIGINAL observation was mutated — losing the outage hides the very thing "
                 "the retry ladder documents")
    if m2[-1].get("prior_observation_count") != 1:
        f.append("the new observation does not record how many priors it follows")

    # ---- dispositions
    d = disposition("CIN@AZ", T0, "2026-08-23T06:00:00Z")
    if d["state"] != "PENDING_TIER1_CONFIRMATION" or d["may_grade"]:
        f.append(f"in-window game wrong: {d}")
    d = disposition("CIN@AZ", T0, "2026-08-25T00:00:00Z")
    if d["state"] != UNRESOLVED_SOURCE_GAP or d["may_grade"]:
        f.append(f"expired game wrong: {d}")
    if "not graded, not guessed, and not silently dropped" not in d["reason"]:
        f.append("the expiry disposition does not state that the gap is named rather than hidden")
    d = disposition("CIN@AZ", T0, "2026-08-25T00:00:00Z", tier1_confirmed=True)
    if d["state"] != "TIER1_CONFIRMED" or not d["may_grade"]:
        f.append("tier-1 confirmation did not permit grading")
    # tier-1 confirmation beats expiry: a late official result still settles
    if disposition("X", T0, "2026-09-01T00:00:00Z", tier1_confirmed=True)["may_grade"] is not True:
        f.append("a tier-1 confirmation arriving after expiry was refused; expiry bounds GUESSING, "
                 "not the acceptance of real official evidence")

    # ---- the plan never permits grading on its own
    p = plan(T0, man, ["CIN@AZ"], now="2026-08-23T06:00:00Z")
    if p["grading_permitted"]:
        f.append("the plan permitted grading without tier-1 confirmation")
    if not p["evidence_preserved"]:
        f.append("the plan did not preserve partial evidence")
    if p["next_due_utc"] != "2026-08-23T06:15:00Z":
        f.append(f"next due wrong: {p['next_due_utc']}")
    if p["all_retries_spent"]:
        f.append("retries reported spent while one is still due")
    p2 = plan(T0, man, ["CIN@AZ"], now="2026-08-24T00:00:00Z")
    if not p2["all_retries_spent"] or p2["next_due_utc"] is not None:
        f.append("retries not reported spent after the last one passed")

    print("retry_ladder selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("retry offsets changed", "RETRY_OFFSETS_MIN = (30, 120, 720)", "RETRY_OFFSETS_MIN = (30, 120, 240)"),
    ("a fourth retry added", "RETRY_OFFSETS_MIN = (30, 120, 720)", "RETRY_OFFSETS_MIN = (30, 120, 720, 1440)"),
    ("expiry window changed", "EXPIRY_HOURS = 36", "EXPIRY_HOURS = 72"),
    ("expiry boundary off by one", "    return _dt(now) >= _dt(expiry(exhausted_at))", "    return _dt(now) > _dt(expiry(exhausted_at))"),
    ("scope no longer narrows to tier 1", '        if r.get("evidence_tier") != TIER1:\n            continue', "        if False:\n            continue"),
    ("already-reachable routes retried", '        if r.get("network_status") in ("HTTP_2XX", "HTTP_3XX"):\n            continue', "        if False:\n            continue"),
    ("resolved games probed again", "    games = [g for g in unresolved_games if g not in set(resolved_games)]", "    games = list(unresolved_games)"),
    ("observations overwritten instead of appended", "    out = list(manifest)\n    prior = [r for r in out", "    out = [r for r in manifest if (r.get('host'), r.get('route'), r.get('tool')) != (observation.get('host'), observation.get('route'), observation.get('tool'))]\n    prior = [r for r in out"),
    ("prior observation count dropped", '    obs["prior_observation_count"] = len(prior)', '    obs["prior_observation_count"] = 0'),
    ("expired game silently graded", '    if is_expired(exhausted_at, now):\n        return {"game": game, "state": UNRESOLVED_SOURCE_GAP, "may_grade": False,', '    if is_expired(exhausted_at, now):\n        return {"game": game, "state": UNRESOLVED_SOURCE_GAP, "may_grade": True,'),
    ("pending game may grade", '    return {"game": game, "state": "PENDING_TIER1_CONFIRMATION", "may_grade": False,', '    return {"game": game, "state": "PENDING_TIER1_CONFIRMATION", "may_grade": True,'),
    ("tier-1 confirmation no longer permits grading", '    if tier1_confirmed:\n        return {"game": game, "state": "TIER1_CONFIRMED",\n                "may_grade": True,', '    if tier1_confirmed:\n        return {"game": game, "state": "TIER1_CONFIRMED",\n                "may_grade": False,'),
    ("expiry blocks a late tier-1 confirmation", "    if tier1_confirmed:", "    if tier1_confirmed and not is_expired(exhausted_at, now):"),
    ("plan claims grading is permitted", '"grading_permitted": False,', '"grading_permitted": True,'),
    ("plan drops evidence preservation", '"evidence_preserved": True,', '"evidence_preserved": False,'),
]


def mutation_suite(verbose=True):
    import subprocess, tempfile
    src = open(os.path.abspath(__file__)).read()
    i = src.index("MUTANTS = ["); j = src.index("\ndef mutation_suite", i)
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
        with tempfile.NamedTemporaryFile("w", suffix="_m.py", delete=False,
                                         dir=os.path.dirname(os.path.abspath(__file__))) as fh:
            fh.write(mut); p = fh.name
        try:
            r = subprocess.run([sys.executable, p, "--selftest"], capture_output=True,
                               text=True, timeout=60)
            killed = r.returncode != 0
        except subprocess.TimeoutExpired:
            killed = True
        finally:
            os.unlink(p)
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
    print(__doc__)
