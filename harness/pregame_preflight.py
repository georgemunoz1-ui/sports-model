#!/usr/bin/env python3
"""Are the pregame inputs on disk in time to produce a gradeable card? Fail LOUDLY and EARLY if not.

OWNER, 2026-08-17: "the larger problem remains: no 8/18 slate or prices means another potential day
without usable, gradeable betting output. The capture rail must deliver an official gamePk schedule,
starters/lineups, and timestamped prices before first pitch; model gates cannot compensate for
absent pregame inputs."

That is the correct diagnosis and it names this repository's actual failure mode. Every gate built
here so far checks the QUALITY of data that arrived. None of them fires when data simply never
arrives — which is exactly what happened on 2026-08-16 (no card in any sport, detected at 23:26Z
after all 18 first pitches) and what a missing 8/18 slate would repeat. A silent absence has cost
more gradeable output than any data-quality defect has.

So this gate inverts the polarity. It does not ask "is what we have good?" It asks, for a named
date: are the THREE pregame inputs present, and how long is left before they stop being acquirable?

    SCHEDULE   data/mlb/schedule/official_manifest_{date}.json   official gamePk set
               Without it the slate is unverified: harness/tier1_board_gate.py can only report
               COMPLETE_BY_ROSTER_PARTITION, never a confirmed count.
    STARTERS   data/mlb/slates/{date}_slate*.psv                 gamePk|away|home|utc|away SP|home SP
               TBD starters are ACCEPTED but COUNTED — the 8/17 v1-vs-v2 contrast measured starter
               resolution moving probabilities ~5x more than form freshness, so a TBD-heavy slate is
               a materially weaker card and the count says so.
    PRICES     data/mlb/odds/{date}_*.json                       timestamped two-sided quotes
               Without prices there is no break-even, no edge, no selection, and nothing to grade
               against a market. The 8/17 card has none, which is why its edge column is null.

DEADLINE, not just presence. Each input is scored against the slate's EARLIEST first pitch, taken
from the slate file itself. An input that arrives after first pitch is not late, it is useless: a
post-start price cannot price a pregame forecast and a post-start starter is a box score. The gate
reports minutes remaining and fails while there is still time to act, rather than confirming a loss
afterwards.

DELIBERATELY NOT DONE HERE: fetching. Outbound HTTPS is 403 at the org egress proxy and is not
routed around. This gate makes an absence loud and timed; it cannot make data appear. That is the
honest division — a gate that pretended to acquire would be the same silent failure with extra steps.

Usage: python3 harness/pregame_preflight.py [--date YYYY-MM-DD] [--gate] [--selftest]
"""
from __future__ import annotations
import argparse, datetime as dt, glob, hashlib, json, os, re, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
OUT = "data/audit/pregame_preflight.json"

# How long before first pitch each input must exist to be useful. Prices move until the last minute,
# so their deadline is tightest; a schedule that arrives 15 minutes out has already cost the day.
DEADLINES_MIN_BEFORE_FIRST_PITCH = {"schedule": 240, "starters": 180, "prices": 90}


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


#: Slate times are UTC but the slate DATE is the US local date, so a late West-coast start rolls
#: past midnight UTC and appears as e.g. 00:05Z. Sorting those as strings makes 00:05Z the "earliest"
#: game, which is wrong by nearly a full day — on the 8/17 slate it moved first pitch from 17:40Z to
#: 00:05Z and turned a live pregame check into "523 minutes past first pitch". Caught by this
#: module's selftest. Anything before this hour is treated as belonging to the following UTC day.
NEXT_DAY_BEFORE_HOUR_UTC = 10


def _parse_slate(path, date):
    """gamePk|Away|Home|utcTime|AwaySP|HomeSP — returns (rows, earliest_first_pitch_datetime_or_None).

    Times are resolved to absolute UTC datetimes before comparison, with a day rollover for
    post-midnight starts, so the earliest game is the earliest in TIME rather than in string order."""
    rows, stamps = [], []
    d0 = dt.datetime.fromisoformat(date).replace(tzinfo=dt.timezone.utc)
    for ln in open(path):
        p = ln.strip().split("|")
        if len(p) < 6:
            continue
        rows.append({"gamePk": p[0], "away": p[1], "home": p[2], "utc": p[3],
                     "away_sp": p[4], "home_sp": p[5]})
        if re.fullmatch(r"\d{2}:\d{2}Z", p[3] or ""):
            h, m = int(p[3][:2]), int(p[3][3:5])
            when = d0.replace(hour=h, minute=m)
            if h < NEXT_DAY_BEFORE_HOUR_UTC:
                when += dt.timedelta(days=1)
            stamps.append(when)
    return rows, (min(stamps) if stamps else None)


def check(date, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    rep = {"date": date, "checked_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "inputs": {}}

    # ---- STARTERS / SLATE ----
    slates = sorted(glob.glob(f"data/mlb/slates/{date}_slate*.psv"))
    slate_rows, fp_dt = [], None
    if slates:
        slate_rows, fp_dt = _parse_slate(slates[-1], date)
    tbd = sum(1 for r in slate_rows if "TBD" in (r["away_sp"], r["home_sp"]))
    both_tbd = sum(1 for r in slate_rows if r["away_sp"] == "TBD" and r["home_sp"] == "TBD")
    rep["inputs"]["starters"] = {
        "present": bool(slates), "files": slates, "sha256": {p: _sha(p) for p in slates},
        "games": len(slate_rows),
        "games_with_a_TBD_starter": tbd, "games_with_BOTH_starters_TBD": both_tbd,
        "resolution_pct": (round(100 * (len(slate_rows) - tbd) / len(slate_rows), 1)
                           if slate_rows else None),
        "note": ("TBD starters are accepted but counted: starter resolution moved 8/17 probabilities "
                 "~5x more than form freshness, so a TBD-heavy slate is a materially weaker card."),
        "consequence_if_absent": ("no slate means no card at all, and no first pitch to time the other "
                                  "inputs against. This is the 2026-08-16 failure exactly."),
    }

    # ---- SCHEDULE MANIFEST ----
    man = f"data/mlb/schedule/official_manifest_{date}.json"
    ok = os.path.exists(man)
    d = json.load(open(man)) if ok else {}
    rep["inputs"]["schedule"] = {
        "present": ok, "path": man, "sha256": _sha(man) if ok else None,
        "gamePks": len(d.get("gamePks", [])) if ok else 0,
        "captured_at_utc": d.get("captured_at_utc"), "source": d.get("source"),
        "consequence_if_absent": ("the slate count is unverified — tier1_board_gate can only report "
                                  "COMPLETE_BY_ROSTER_PARTITION, never a confirmed game count"),
    }

    # ---- PRICES ----
    odds = sorted(glob.glob(f"data/mlb/odds/{date}_*.json"))
    rep["inputs"]["prices"] = {
        "present": bool(odds), "files": odds, "sha256": {p: _sha(p) for p in odds},
        "consequence_if_absent": ("no break-even probability, no edge, no selection, and nothing to "
                                  "grade against a market. Model output is forecast-only."),
    }

    # ---- TIMING ----
    mins_left = round((fp_dt - now).total_seconds() / 60) if fp_dt else None
    rep["first_pitch_utc"] = fp_dt.strftime("%Y-%m-%dT%H:%MZ") if fp_dt else None
    rep["minutes_to_first_pitch"] = mins_left
    rep["past_first_pitch"] = (mins_left is not None and mins_left < 0)

    missing, at_risk = [], []
    for k, dl in DEADLINES_MIN_BEFORE_FIRST_PITCH.items():
        e = rep["inputs"][k]
        e["deadline_min_before_first_pitch"] = dl
        if e["present"]:
            e["status"] = "PRESENT"
        elif mins_left is None:
            e["status"] = "MISSING_NO_SLATE_TO_TIME_AGAINST"
            missing.append(k)
        elif mins_left < 0:
            e["status"] = "MISSING_AND_UNRECOVERABLE (past first pitch)"
            missing.append(k)
        elif mins_left < dl:
            e["status"] = f"MISSING_PAST_DEADLINE ({mins_left}m left, needed {dl}m out)"
            missing.append(k)
        else:
            e["status"] = f"MISSING_BUT_RECOVERABLE ({mins_left - dl}m of slack)"
            at_risk.append(k)

    rep["missing_past_deadline"] = missing
    rep["missing_but_recoverable"] = at_risk
    rep["CARD_IS_PRODUCIBLE"] = rep["inputs"]["starters"]["present"] and not rep["past_first_pitch"]
    rep["CARD_WOULD_BE_GRADEABLE_VS_MARKET"] = rep["inputs"]["prices"]["present"]
    # Two DISTINCT states, deliberately not collapsed into one boolean:
    #   ALL_INPUTS_PRESENT — the day is fully equipped. Nothing missing, whatever the clock says.
    #   GATE_FAIL          — something is missing AND the window to get it has closed. This is the
    #                        actionable one; a gate keyed to mere absence would fail every morning
    #                        and be ignored by lunchtime, which is how the 8/16 rail died.
    rep["ALL_INPUTS_PRESENT"] = all(rep["inputs"][k]["present"] for k in DEADLINES_MIN_BEFORE_FIRST_PITCH)
    rep["GATE_FAIL"] = bool(missing)
    rep["PASS"] = not missing
    rep["verdict"] = (
        "READY" if rep["ALL_INPUTS_PRESENT"] else
        "NO_CARD_POSSIBLE" if (not rep["inputs"]["starters"]["present"] and rep["past_first_pitch"]) else
        "FORECAST_ONLY_NO_MARKET_GRADE" if (rep["inputs"]["starters"]["present"]
                                            and not rep["inputs"]["prices"]["present"]) else
        "INPUTS_MISSING")
    return rep


def run(date, gate=False, write=True):
    rep = check(date)
    if write:
        os.makedirs("data/audit", exist_ok=True)
        json.dump(rep, open(OUT, "w"), indent=1)
    return rep


def selftest():
    import tempfile
    fails = []
    now = dt.datetime(2026, 8, 18, 6, 0, tzinfo=dt.timezone.utc)
    # a date with nothing on disk, checked well before a hypothetical first pitch
    r = check("2099-01-01", now=now)
    if r["ALL_INPUTS_PRESENT"] or r["verdict"] == "READY":
        fails.append("a date with no inputs at all reported READY")
    if r["inputs"]["schedule"]["present"] or r["inputs"]["prices"]["present"]:
        fails.append("phantom inputs reported present for an empty date")
    # the live 8/17 case: slate present, prices absent -> must be FORECAST_ONLY, not READY
    r17 = check("2026-08-17", now=dt.datetime(2026, 8, 17, 8, 0, tzinfo=dt.timezone.utc))
    if not r17["inputs"]["starters"]["present"]:
        fails.append("8/17 slate not detected")
    if r17["inputs"]["prices"]["present"]:
        fails.append("8/17 prices reported present — they do not exist")
    if r17["verdict"] != "FORECAST_ONLY_NO_MARKET_GRADE":
        fails.append(f"8/17 verdict should be FORECAST_ONLY_NO_MARKET_GRADE, got {r17['verdict']}")
    if r17["CARD_WOULD_BE_GRADEABLE_VS_MARKET"]:
        fails.append("8/17 reported gradeable against a market with no prices on file")
    # timing: past first pitch must be unrecoverable, not merely late
    late = check("2026-08-17", now=dt.datetime(2026, 8, 18, 6, 0, tzinfo=dt.timezone.utc))
    if not late["past_first_pitch"]:
        fails.append("a check run after first pitch did not report past_first_pitch")
    if "UNRECOVERABLE" not in late["inputs"]["prices"]["status"]:
        fails.append("a missing input past first pitch was not marked unrecoverable")
    # deadline logic: an input missing with slack is RECOVERABLE, without slack is PAST_DEADLINE
    early = check("2026-08-17", now=dt.datetime(2026, 8, 17, 0, 0, tzinfo=dt.timezone.utc))
    if "RECOVERABLE" not in early["inputs"]["prices"]["status"]:
        fails.append("a missing price 17h before first pitch was not marked recoverable")
    tight = check("2026-08-17", now=dt.datetime(2026, 8, 17, 17, 0, tzinfo=dt.timezone.utc))
    if "PAST_DEADLINE" not in tight["inputs"]["prices"]["status"]:
        fails.append("a missing price 40m before first pitch was not marked past deadline")
    # the day-rollover: the 8/17 slate's earliest game is 17:40Z, NOT the 00:05Z next-day start
    if not (r17["first_pitch_utc"] or "").endswith("17:40Z"):
        fails.append(f"first pitch resolved to {r17['first_pitch_utc']}, expected 2026-08-17T17:40Z — "
                     f"a post-midnight start is sorting ahead of the real opener")
    if r17["past_first_pitch"]:
        fails.append("8/17 checked at 08:00Z reported past first pitch")
    # TBD accounting must be real, not assumed
    if r17["inputs"]["starters"]["resolution_pct"] is None:
        fails.append("starter resolution not computed for a present slate")
    if fails:
        print("pregame_preflight selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("pregame_preflight selftest: PASS (day-rollover fixed so a 00:05Z game no longer sorts "
          "ahead of the 17:40Z opener; empty date never READY; 8/17 correctly "
          "FORECAST_ONLY_NO_MARKET_GRADE with prices absent; past-first-pitch marked unrecoverable; "
          "deadline slack distinguishes recoverable from past-deadline)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=(dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).strftime("%Y-%m-%d"))
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    r = run(a.date, a.gate)
    print(f'PREGAME PREFLIGHT {r["date"]}  ->  {r["verdict"]}')
    print(f'  first pitch {r["first_pitch_utc"] or "UNKNOWN (no slate)"}   '
          f'minutes remaining {r["minutes_to_first_pitch"] if r["minutes_to_first_pitch"] is not None else "n/a"}')
    for k in ("schedule", "starters", "prices"):
        e = r["inputs"][k]
        extra = ""
        if k == "starters" and e["present"]:
            extra = (f'  {e["games"]} games, {e["games_with_a_TBD_starter"]} with a TBD '
                     f'({e["resolution_pct"]}% resolved)')
        if k == "schedule" and e["present"]:
            extra = f'  {e["gamePks"]} gamePks'
        print(f'  {k:<9} {e["status"]}{extra}')
        if not e["present"]:
            print(f'            -> {e["consequence_if_absent"]}')
    print(f'  card producible: {r["CARD_IS_PRODUCIBLE"]}   '
          f'gradeable vs market: {r["CARD_WOULD_BE_GRADEABLE_VS_MARKET"]}   '
          f'all inputs present: {r["ALL_INPUTS_PRESENT"]}')
    if r["missing_past_deadline"]:
        print(f'  ! PAST DEADLINE, no longer recoverable: {", ".join(r["missing_past_deadline"])}')
    if r["missing_but_recoverable"]:
        print(f'  -> still acquirable: {", ".join(r["missing_but_recoverable"])}')
    raise SystemExit(1 if (a.gate and not r["PASS"]) else 0)
