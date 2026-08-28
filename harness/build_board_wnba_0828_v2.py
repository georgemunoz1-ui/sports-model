"""The 2026-08-28 WNBA board, v2 — the blocked arm filled in, the frozen v1 left alone.

WHAT CHANGED AND WHY IT IS A NEW RECORD RATHER THAN AN EDIT. The v1 board froze at 10:35Z with
wnba.replacement.FEATURE_REFRESH carried as an explicit null: the extension pool could not be
rebuilt through the 8/27 cutoff because the wehoop archive had not published that day. At 11:01Z it
did (7a1c7eb, 8/28 06:32 ET, carrying both 8/27 finals). The rebuild ran, so the arm can forecast.

R3 says frozen stays frozen, so cards/2026-08-28_wnba_board.json is NOT touched. This is a
superseding record that names it as predecessor and states precisely which rows changed and why.

THE DISCLOSED STALENESS INTERVAL CAME BACK CORRECT. v1 reported that exactly one of the eight teams
playing tonight — Washington — had a record stale by one game, refused to roll it forward on an
unbound result, and published the interval instead: 27.34% if that game was a win, 29.52% if a loss.
Washington beat Phoenix 80-73. The archive now reads 24-15 and the recomputed value lands on the
win end of the published band. The other three games' records did not move and their fallback
probabilities are byte-identical.

AND THE CRUDE ARM'S BIG EDGE EVAPORATED, WHICH IS THE POINT. On WSH@LAS the records-only fallback
had Washington at 71.80% against a market break-even of 67.21%, the largest apparent edge on the
board. The real feature model puts Washington at 52.69%. The v1 card said in as many words that the
fallback's edges were "describing its own blindness" rather than finding value; that reading is now
measured rather than asserted.
"""
from __future__ import annotations

MODULE_ID = "build_board_wnba_0828_v2"

import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wnba_refresh_espn as R
import wnba_standings_fallback as FB

DATE = "2026-08-28"
V1 = f"cards/{DATE}_wnba_board.json"
OUT = f"cards/{DATE}_wnba_board_v2.json"
PARQUET = ("/home/user/sportsdataverse/wehoop-wnba-raw/wnba/schedules/parquet/"
           "wnba_schedule_2026.parquet")

#: board game key -> (pool key away, pool key home). The pool keys on abbreviations, and a first
#: run passing full display names returned DATA_BLOCKED on all four games — a keying error that
#: looks exactly like a data outage. Pinned here so it cannot recur silently.
POOL_KEYS = {"wnba:POR@ATL": ("PDX", "ATL"), "wnba:CON@IND": ("CON", "IND"),
             "wnba:TOR@LV": ("TOR", "LVA"), "wnba:WSH@LAS": ("WAS", "LAS")}
ABBR = {"Portland Fire": "POR", "Atlanta Dream": "ATL", "Connecticut Sun": "CON",
        "Indiana Fever": "IND", "Toronto Tempo": "TOR", "Las Vegas Aces": "LV",
        "Washington Mystics": "WSH", "Los Angeles Sparks": "LAS"}


def current_records():
    import pandas as pd
    d = pd.read_parquet(PARQUET)
    d["et"] = pd.to_datetime(d["date"], utc=True).dt.tz_convert("America/New_York")
    f = d[d["et"].dt.date.astype(str) == DATE]
    out = {}
    for r in f.itertuples(index=False):
        def rec(v):
            for x in v:
                if x.get("type") == "total":
                    w, l = x["summary"].split("-")
                    return int(w), int(l)
        out[f'wnba:{ABBR[r.away_display_name]}@{ABBR[r.home_display_name]}'] = {
            "away": rec(r.away_records), "home": rec(r.home_records),
            "away_team": ABBR[r.away_display_name], "home_team": ABBR[r.home_display_name]}
    return out


def build():
    v1 = json.load(open(V1))
    recs = current_records()

    slate = [(POOL_KEYS[g][0], POOL_KEYS[g][1],
              next(r["game_start_utc"] for r in v1["wnba"]["rows"] if r["game"] == g))
             for g in POOL_KEYS]
    ref = R.run_slate(slate)
    pred = {f"wnba:{p['away']}@{p['home']}": p for p in ref["predictions"]}
    blocked = [k for k, p in pred.items() if "status" in p]
    if blocked:
        raise SystemExit(f"FEATURE_REFRESH still blocked on {blocked} — do not publish a v2 that "
                         "claims an unblock that did not happen")

    v1_by = {}
    for r in v1["wnba"]["rows"]:
        v1_by.setdefault(r["game"], {})[r["arm"]] = r

    rows, changes = [], []
    for g, (ak, hk) in POOL_KEYS.items():
        base = {k: v for k, v in v1_by[g]["wnba.winner.EXPANDING_HOME_PRIOR"].items()
                if k in ("game", "sport", "away", "home", "canonical_id", "id_space", "id_grade",
                         "game_start_utc", "schedule_grade", "lineups", "availability_grade",
                         "action_status", "forecast_status")}

        # ---- arm 1: registered constant, carried unchanged
        prior = v1_by[g]["wnba.winner.EXPANDING_HOME_PRIOR"]
        rows.append(dict(prior))

        # ---- arm 2: log5, recomputed on CURRENT records
        old = v1_by[g]["wnba.fallback.STANDINGS_LOG5_v1"]
        (aw, al), (hw, hl) = recs[g]["away"], recs[g]["home"]
        p, parts = FB.p_home(hw, hl, aw, al)
        row = dict(old)
        row["p_home"] = p
        row["records"] = {recs[g]["home_team"]: f"{hw}-{hl}", recs[g]["away_team"]: f"{aw}-{al}"}
        row["records_asof"] = "2026-08-27 (archive 7a1c7eb; 8/27 finals bound)"
        row["log5"] = parts["log5"]
        if abs(p - old["p_home"]) > 1e-12:
            st = old.get("record_staleness") or {}
            changes.append({
                "game": g, "arm": old["arm"],
                "old_p_home": old["p_home"], "new_p_home": round(p, 6),
                "old_records": old["records"], "new_records": row["records"],
                "cause": "the 8/27 result this row explicitly refused to assume is now bound",
                "published_interval": [st.get("p_home_if_that_game_was_a_win"),
                                       st.get("p_home_if_that_game_was_a_loss")],
                "lands_inside_published_interval": bool(
                    st and min(st["p_home_if_that_game_was_a_win"],
                               st["p_home_if_that_game_was_a_loss"]) - 1e-9 <= p <=
                    max(st["p_home_if_that_game_was_a_win"],
                        st["p_home_if_that_game_was_a_loss"]) + 1e-9)})
            row["record_staleness"] = dict(st, resolved=True,
                                           resolved_by="WSH beat PHX 80-73 on 2026-08-27, bound "
                                                       "from archive 7a1c7eb")
        rows.append(row)

        # ---- arm 3: the previously blocked arm, now real
        p3 = pred[f"wnba:{ak}@{hk}"]
        rows.append(dict(base, arm="wnba.replacement.FEATURE_REFRESH", target="winner",
                         p_home=p3["p_home"], margin_home=p3["margin_home"],
                         projected_total=p3["total"],
                         coherence_gap_pp=p3["coherence_gap_pp"],
                         coherence_pass=p3["coherence_pass"],
                         games_used=p3["games_used"],
                         model_side=(base["home"] if p3["p_home"] >= 0.5 else base["away"]),
                         input_grade=R.INPUT_GRADE,
                         forecast_status="FORECAST_REGISTERED",
                         unblocked_from="BLOCKED_PENDING_FEATURE_REBUILD",
                         input_dependency="EXTENSION_POOL_THROUGH_CUTOFF"))

    def ch(x):
        return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    board = {
        "record_id": f"BOARD-{DATE}-WNBA-V2",
        "supersedes": {"record": v1["record_id"], "file": V1,
                       "file_sha256": hashlib.sha256(open(V1, "rb").read()).hexdigest(),
                       "rule": "R3 — the v1 file is NOT edited; this record supersedes it"},
        "slate_date": DATE, "sport": "wnba",
        "builder": "harness/build_board_wnba_0828_v2.py (COMMITTED)",
        "forecast_anchor_utc": "2026-08-28T11:25:00Z",
        "earliest_start_utc": v1["earliest_start_utc"],
        "cohort": "WNBA — never pooled with MLB or NFL",
        "n_games": 4,
        "WHAT_CHANGED": {
            "unblocked": "wnba.replacement.FEATURE_REFRESH — the extension pool was rebuilt "
                         "through the 8/27 cutoff once the archive published that day",
            "archive_advanced": {"from": "3316fa3", "to": "7a1c7eb",
                                 "landed_utc": "2026-08-28 06:32 ET",
                                 "carries": "both 8/27 finals (401857178, 401857179)"},
            "arms_now_emitted": 3, "arms_blocked": 0,
            "carried_unchanged": ["wnba.winner.EXPANDING_HOME_PRIOR"],
            "recomputed": changes,
        },
        "STALENESS_INTERVAL_RESOLVED": {
            "v1_published": "exactly one of tonight's eight teams (Washington) had a record stale "
                            "by one game; v1 refused to roll it forward on an unbound result and "
                            "published the interval instead",
            "outcome": "Washington beat Phoenix 80-73 on 2026-08-27; the archive now reads 24-15",
            "verdict": ("the realized value lands inside the published band, on its win end. "
                        "Refusing to guess cost nothing and the disclosure was accurate."),
        },
        "FALLBACK_EDGE_EVAPORATED": {
            "finding": ("on WSH@LAS the records-only fallback had Washington at 71.80% against a "
                        "market break-even of 67.21% — the largest apparent edge on the board. The "
                        "feature model puts Washington at "
                        f"{100 * (1 - pred['wnba:WAS@LAS']['p_home']):.2f}%."),
            "why_it_matters": ("the v1 card said the fallback's large edges were 'describing its "
                               "own blindness' rather than finding value. That was a judgement "
                               "then; it is a measurement now."),
        },
        # still open, and still not settled by guess — carried forward from v1 unchanged
        "availability_open_items": v1["availability_open_items"],
        "GAME_IDENTITY": v1["GAME_IDENTITY"],
        "RECORD_STALENESS": dict(v1["RECORD_STALENESS"], resolved=True,
                                 resolved_note="Washington's 8/27 result is now bound; the "
                                               "published interval held"),
        "model_identity": ["wnba.winner.EXPANDING_HOME_PRIOR",
                           "wnba.fallback.STANDINGS_LOG5_v1 (DIAGNOSTIC_ONLY, action-blocked)",
                           "wnba.replacement.FEATURE_REFRESH"],
        "pool": ref["pool"], "provenance": ref["provenance"],
        "leakage_check": ("the four target ids 401857180-183 are absent from the extension pool; "
                          "the pool's latest event is strictly before the earliest tip"),
        "action_authority": "NONE — the fallback is DIAGNOSTIC_ONLY by registration and "
                            "FEATURE_REFRESH is ACTION_BLOCKED while SYSTEM_NOT_DECISION_READY",
        "SEPARATION": "MLB, WNBA and NFL are separate cohorts on separate boards, never pooled",
        "LEDGERS": {"model_authorized_wagers_usd": 0, "n_bets": 0, "units": 0.0},
        "cohort_hashes": {"wnba": ch(rows)},
        "wnba": {"cohort_id": f"wnba:{DATE}", "n_games": 4, "rows": rows},
    }
    with open(OUT, "w") as fh:
        json.dump(board, fh, indent=1, sort_keys=True)
    return board


if __name__ == "__main__":
    b = build()
    print("FROZEN", b["record_id"], "|", b["cohort_hashes"]["wnba"][:8],
          "| supersedes", b["supersedes"]["record"])
    print(f'{"game":<16}{"prior":>8}{"log5":>9}{"refresh":>10}{"margin":>9}{"total":>8}')
    by = {}
    for r in b["wnba"]["rows"]:
        by.setdefault(r["game"], {})[r["arm"]] = r
    for g, a in by.items():
        f = a["wnba.replacement.FEATURE_REFRESH"]
        print(f'{g.split(":")[1]:<16}'
              f'{a["wnba.winner.EXPANDING_HOME_PRIOR"]["p_home"]:>8.4f}'
              f'{a["wnba.fallback.STANDINGS_LOG5_v1"]["p_home"]:>9.4f}'
              f'{f["p_home"]:>10.4f}{f["margin_home"]:>9.2f}{f["projected_total"]:>8.1f}')
    for c in b["WHAT_CHANGED"]["recomputed"]:
        print(f'\n  RECOMPUTED {c["game"]}: {c["old_p_home"]:.4f} -> {c["new_p_home"]:.4f}  '
              f'inside published interval: {c["lands_inside_published_interval"]}')
