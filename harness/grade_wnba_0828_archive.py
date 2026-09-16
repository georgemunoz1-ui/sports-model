"""ARCHIVE-BOUND grading of the 2026-08-28 WNBA cohort. The first genuinely bound cohort.

WHY THIS SUPERSEDES THE RELAY GRADING. data/audit/2026-08-28_relay_grading.json recorded these
same four games from an owner relay of bare scores. That relay carried NO result_date, so it could
not bind under the registered contract and was correctly refused 0/4, with an IDENTITY_MATCH 4/4
reported beside it as the weaker claim that actually held. The wehoop archive advanced to 8ffb87b
at 2026-08-29T06:32-04:00 and now carries all four games STATUS_FINAL with scores and an
observable date, so the full six-field contract can be satisfied for the first time.

The relayed scores turn out to be correct. That is worth stating precisely: it means the relay was
accurate, NOT that relaying was sufficient. An unverifiable claim that later proves true was still
unverifiable when it was made, and the 8/27 cycle published five fabricated finals that also looked
plausible at the time.

RESULT PROVENANCE IS THE NEW COMMIT, NOT THE PINNED ONE. harness/wnba_refresh_espn.COMMIT_PIN is
7a1c7eb and governs FEATURE extraction — what the model was allowed to know before tip. Results
come from 8ffb87b, which is strictly later. Those are different questions and conflating them
would either freeze results forever or let post-tip information leak into features.
"""
from __future__ import annotations

MODULE_ID = "grade_wnba_0828_archive"

import datetime as dt
import hashlib
import json
import math
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "harness"))

from result_binding_gate import binding_proof, guarded_aggregate, AggregateRefused  # noqa: E402
from postslate_binding_0828 import gate_board                                       # noqa: E402

SLATE = "2026-08-28"
WEHOOP = "/home/user/sportsdataverse/wehoop-wnba-raw"
RESULT_COMMIT = "8ffb87b"
BOARD = f"cards/{SLATE}_wnba_board_v2.json"
ARMS = ["wnba.replacement.FEATURE_REFRESH", "wnba.winner.EXPANDING_HOME_PRIOR",
        "wnba.fallback.STANDINGS_LOG5_v1"]


def archive_finals():
    """Read the four finals from the ADVANCED commit. Dates derived in ET, never sliced from UTC."""
    import pandas as pd
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
    tmp = "/tmp/_wehoop_result.parquet"
    with open(tmp, "wb") as fh:
        subprocess.run(["git", "-C", WEHOOP, "show",
                        f"{RESULT_COMMIT}:wnba/schedules/parquet/wnba_schedule_2026.parquet"],
                       stdout=fh, check=True)
    s = pd.read_parquet(tmp)
    et = pd.to_datetime(s["date"], utc=True).dt.tz_convert(ET).dt.date.astype(str)
    sub = s[(et == SLATE) & (s["status_type_completed"].fillna(False).astype(bool))]
    out = {}
    for _, r in sub.iterrows():
        out[f"ESPN_GAMEID:{r['game_id']}"] = {
            "away_score": int(r["away_score"]), "home_score": int(r["home_score"]),
            "result_date": SLATE,          # ET, derived — the UTC slice would split this cohort
            "utc_instant": str(r["date"]),
            "status": str(r["status_type_name"]),
        }
    sha = hashlib.sha256(open(tmp, "rb").read()).hexdigest()
    os.remove(tmp)
    return out, sha


def build():
    board = json.load(open(BOARD))
    gb = gate_board(board, "wnba")
    finals, src_sha = archive_finals()

    rows, unmatched = [], []
    for game, info in gb["games"].items():
        cid = info["game_pk"]
        f = finals.get(cid)
        if f is None:
            unmatched.append((game, cid))
            continue
        rows.append({
            "sport": "wnba", "game_pk": cid,
            "scheduled_date": SLATE, "result_date": f["result_date"],
            "away": info["away"], "home": info["home"],
            "away_score": f["away_score"], "home_score": f["home_score"],
        })

    proof = binding_proof(rows, gb, f"wnba:{SLATE}")
    proof.update({
        "result_source": {
            "repo": "github.com/sportsdataverse/wehoop-wnba-raw",
            "result_commit": RESULT_COMMIT,
            "feature_commit_pin": "7a1c7eb (governs EXTRACTION, not results — different question)",
            "schedule_sha256": src_sha,
            "date_derivation": "ET via zoneinfo from the UTC instant; the UTC date slice would "
                               "place TOR@LV and WSH@LAS on 8/29 and split this cohort",
        },
        "supersedes": {
            "record": "data/audit/2026-08-28_relay_grading.json",
            "why": ("that record graded an owner relay of bare scores which carried no result_date "
                    "and therefore could not bind: 0/4 refused, IDENTITY_MATCH 4/4 reported beside "
                    "it. The archive now supplies the missing field."),
            "relay_scores_agreed": True,
            "reading": ("the relay was ACCURATE, not sufficient. A claim that later proves true "
                        "was still unverifiable when made; the 8/27 cycle's five fabricated finals "
                        "were plausible too."),
        },
        "unmatched_board_games": unmatched,
    })

    try:
        guard = guarded_aggregate(proof, "wnba arm statistics")
    except AggregateRefused as e:
        guard = {"permitted": False, "error": str(e)}
        return {"REFUSED": str(e), "proof": proof}, None

    by = {}
    for r in board["wnba"]["rows"]:
        by.setdefault(r["arm"], {})[r["game"]] = r
    key = {g: info["game_pk"] for g, info in gb["games"].items()}

    graded = {}
    for arm in ARMS:
        n = w = 0
        bs, ls, per = [], [], []
        for g, row in by.get(arm, {}).items():
            p = row.get("p_home")
            f = finals.get(key[g])
            if p is None or f is None:
                per.append({"game": g, "p_home": None,
                            "excluded": "arm emitted no forecast for this game"})
                continue
            y = 1 if f["home_score"] > f["away_score"] else 0
            n += 1
            hit = (p >= 0.5) == (y == 1)
            w += hit
            b = (p - y) ** 2
            pp = min(max(p, 1e-12), 1 - 1e-12)
            l = -(y * math.log(pp) + (1 - y) * math.log(1 - pp))
            bs.append(b); ls.append(l)
            per.append({"game": g, "p_home": round(p, 6), "home_won": bool(y),
                        "correct": bool(hit), "brier": round(b, 6),
                        "final": f"{f['away_score']}-{f['home_score']}"})
        graded[arm] = ({"n": n, "record": f"{w}-{n - w}", "brier": round(sum(bs) / n, 6),
                        "logloss": round(sum(ls) / n, 6), "per_game": per} if n else
                       {"n": 0, "note": "arm emitted no gradable forecast", "per_game": per})

    fr = by.get("wnba.replacement.FEATURE_REFRESH", {})
    merr = []
    for g, row in fr.items():
        m, f = row.get("margin_home"), finals.get(key[g])
        if m is not None and f:
            merr.append({"game": g, "proj": m, "actual": f["home_score"] - f["away_score"],
                         "err": round(m - (f["home_score"] - f["away_score"]), 4)})
    e = [x["err"] for x in merr]
    margin = {"n": len(e), "mae": round(sum(abs(v) for v in e) / len(e), 4),
              "rmse": round(math.sqrt(sum(v * v for v in e) / len(e)), 4),
              "bias": round(sum(e) / len(e), 4), "per_game": merr} if e else None

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec = {"schema": "ops.archive_grading.v1", "record_id": f"ARCHIVE-GRADING-WNBA-{SLATE}",
           "created_utc": now, "cohort": f"wnba:{SLATE}", "board": BOARD,
           "EVIDENCE_LAYER": {"layer": "CANONICAL_EVIDENCE_ADMISSION",
                              "is_archive_bound": True,
                              "accrual": "this cohort IS admissible; it bound on all six fields"},
           "BINDING": proof, "AGGREGATE_GUARD": guard,
           "ARMS": graded, "MARGIN": margin,
           "LEDGER": {"n_bets": 0, "units": 0.0, "wager_authority": "NO"}}
    out = f"data/audit/{SLATE}_wnba_archive_grading.json"
    blob = json.dumps(rec, indent=1, sort_keys=True)
    rec["record_sha256"] = hashlib.sha256(blob.encode()).hexdigest()
    with open(out, "w") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
    return rec, out


if __name__ == "__main__":
    rec, out = build()
    if out is None:
        print("REFUSED:", rec["REFUSED"]); sys.exit(1)
    c = rec["BINDING"]["counters"]
    print("WROTE", out, "|", rec["record_sha256"][:12])
    print(f"  RESULT_BINDING_PASS = {c['RESULT_BINDING_PASS']}   "
          f"DATE_COHERENCE_PASS = {c['DATE_COHERENCE_PASS']}")
    print(f"  CANONICAL_ID_MATCH  = {c['CANONICAL_ID_MATCH']}   REFUSED_ROWS = {c['REFUSED_ROWS']}")
    print(f"  gradable = {rec['BINDING']['gradable']}")
    print()
    for a, d in sorted(rec["ARMS"].items(), key=lambda kv: kv[1].get("brier", 9)):
        if d["n"]:
            print(f"  {a:<38} {d['record']:<5} Brier {d['brier']:.4f}  LogLoss {d['logloss']:.4f}")
        else:
            print(f"  {a:<38} {d['note']}")
    m = rec["MARGIN"]
    if m:
        print(f"\n  margin n={m['n']} MAE {m['mae']:.2f} RMSE {m['rmse']:.2f} bias {m['bias']:+.2f}")
