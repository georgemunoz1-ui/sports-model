#!/usr/bin/env python3
"""Build the Phase-4 slate input for a date from the frozen odds transcription + as-of data.

    python3 harness/build_p4_slate.py 2026-07-29

Reads : data/mlb/odds/{date}_gameboards.json  (frozen transcription; quote = view_a, book UNRESOLVED)
        results.csv (team form as-of, strict date < slate)
        pitchers.csv + pitcher logs via build_ml_asof.sp_asof_strict (SP form as-of)
        placeholder manifest (contamination flags travel with the row)
Writes: data/mlb/slates/{date}_p4_slate.json

Honest characteristics of what this produces (all surfaced per row, decided by the generator's
disposition engine, not here):
- gamePk: NONE available without statsapi -> incumbent V13 (seeded by gamePk) cannot run; rows
  carry the candidate + market only. Not patched with a substitute seed: that would be a new
  model identity, which Phase 4 froze.
- starters: odds-board-named ONLY -> never 'confirmed'.
- first_pitch_utc: board prints no timezone; ET is PRESUMED for the UTC conversion and recorded
  as an assumption. Under any US timezone reading, generation this morning is strictly pre-pitch.
- team form: normalized team labels (results.csv mixes full names and abbreviations), full-season
  as-of aggregates — the P2 feature SPEC. NOTE the firewall builder keys aggregates on RAW labels,
  which fragments team history after the label switch; that divergence is disclosed here and in
  the slate meta, not hidden. (Candidate coefficients were fit on pre-switch rows, where the two
  constructions agree.)
- team results: complete through 2026-07-28 by reconciliation EXCEPT ATL/NYM, whose 7/28 game has
  no captured result (header said 16 games, capture held 15 boxes) -> their rows are marked
  unreconciled and the generator demotes them.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import importlib.util
import json
import os
import sys
import unicodedata


def _fold(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

_sp = importlib.util.spec_from_file_location("bma", "harness/build_ml_asof.py")
bma = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(bma)

FULLNAME = {"AZ": "Arizona Diamondbacks", "ATL": "Atlanta Braves", "BAL": "Baltimore Orioles",
            "BOS": "Boston Red Sox", "CHC": "Chicago Cubs", "CWS": "Chicago White Sox",
            "CIN": "Cincinnati Reds", "CLE": "Cleveland Guardians", "COL": "Colorado Rockies",
            "DET": "Detroit Tigers", "HOU": "Houston Astros", "KC": "Kansas City Royals",
            "LAA": "Los Angeles Angels", "LAD": "Los Angeles Dodgers", "MIA": "Miami Marlins",
            "MIL": "Milwaukee Brewers", "MIN": "Minnesota Twins", "NYM": "New York Mets",
            "NYY": "New York Yankees", "ATH": "Athletics", "PHI": "Philadelphia Phillies",
            "PIT": "Pittsburgh Pirates", "SD": "San Diego Padres", "SEA": "Seattle Mariners",
            "SF": "San Francisco Giants", "STL": "St. Louis Cardinals", "TB": "Tampa Bay Rays",
            "TEX": "Texas Rangers", "TOR": "Toronto Blue Jays", "WSH": "Washington Nationals"}
TO_ABBR = {v: k for k, v in FULLNAME.items()}
TO_ABBR.update({"ARI": "AZ", "OAK": "ATH"})  # defensive aliases


def norm(t):
    return TO_ABBR.get(t, t)


def team_form(slate_date):
    rf, ra, gp = {}, {}, {}
    for r in csv.DictReader(open("data/backfill/mlb/2026/results.csv")):
        if r["status"] != "final" or r["total"] == "" or r["date"] >= slate_date:
            continue
        a, h = norm(r["away"]), norm(r["home"])
        asc, hsc = float(r["away_score"]), float(r["home_score"])
        for t, f, g in ((a, asc, hsc), (h, hsc, asc)):
            rf[t] = rf.get(t, 0) + f
            ra[t] = ra.get(t, 0) + g
            gp[t] = gp.get(t, 0) + 1
    return {t: {"rf_pg": round(rf[t] / gp[t], 3), "ra_pg": round(ra[t] / gp[t], 3),
                "games_before": gp[t]} for t in gp}


def et_to_utc(date_iso, verbatim):
    """'Jul 29 7:40pm' + ET ASSUMPTION -> UTC iso. The assumption is flagged in the slate meta."""
    t = verbatim.split()[-1]
    hh, mm = t[:-2].split(":")
    hh, mm = int(hh), int(mm)
    if t.endswith("pm") and hh != 12:
        hh += 12
    if t.endswith("am") and hh == 12:
        hh = 0
    d = dt.datetime.fromisoformat(date_iso) + dt.timedelta(hours=hh + 4, minutes=mm)  # EDT=UTC-4
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def tier(last_log_date, slate_date):
    if last_log_date is None:
        return "PROVISIONAL"
    days = (dt.date.fromisoformat(slate_date) - dt.date.fromisoformat(last_log_date)).days
    return "CURRENT" if days <= 7 else ("STALE_WARNING" if days <= 13 else "STALE_BLOCK")


def main(slate_date):
    boards = json.load(open(f"data/mlb/odds/{slate_date}_gameboards.json"))
    pids = {}
    for r in csv.DictReader(open("data/backfill/mlb/2026/pitchers.csv")):
        pids[_fold(r["name"])] = r["id"]
    ph = json.load(open("data/backfill/mlb/2026/pitcher_logs/_placeholders.json"))
    ph_by_pid = {}
    for r in ph["rows"]:
        ph_by_pid.setdefault(r["pitcher_id"], set()).add(r["date"])
    form = team_form(slate_date)
    # Team-results completeness is COMPUTED, not typed. CONTIGUITY, not just max date: an interior
    # HOLE (a date with zero finals inside the trailing window) silently drops a full day of games
    # from every team's as-of form, yet a pure max-date check would still pass once a LATER date is
    # backfilled. So reconciled requires (a) the latest final reaches D-1 AND (b) no interior hole
    # in [D-14 .. D-1]. History: the 7/29 finals never arrived; without this guard an 8/1+ slate
    # built after 7/31 finals landed would FALSELY report team results complete.
    _final_dates = {r["date"] for r in csv.DictReader(open("data/backfill/mlb/2026/results.csv"))
                    if r["status"] == "final" and r["total"] != "" and r["date"] < slate_date}
    complete_through = max(_final_dates)
    d1 = (dt.date.fromisoformat(slate_date) - dt.timedelta(days=1)).isoformat()
    _sd = dt.date.fromisoformat(slate_date)
    # INTERIOR hole only: a gameless date with a game-day on BOTH sides within the window. This
    # ignores the All-Star break (a leading gameless stretch, 7/13-7/15 in 2026) while catching a
    # true mid-season drop like the un-uploaded 7/29 finals (game-days 7/28 and 7/30 flank it).
    _win = [(_sd - dt.timedelta(days=k)).isoformat() for k in range(1, 15)]
    _present = [d for d in _win if d in _final_dates]
    result_holes = [d for d in _win if d not in _final_dates
                    and any(p < d for p in _present) and any(p > d for p in _present)]
    base_reconciled = (complete_through >= d1) and not result_holes
    exf = f"data/mlb/slates/{slate_date}_recon_exceptions.json"
    recon_exceptions = set(json.load(open(exf))) if os.path.exists(exf) else set()
    venue_by_home = {}
    for r in csv.DictReader(open("data/backfill/mlb/2026/results.csv")):
        if r.get("venue"):
            venue_by_home[norm(r["home"])] = r["venue"]
    park = json.load(open("data/backfill/mlb/2026/park_factors.json"))

    unmatched = []
    games = []
    for g in boards["games"]:
        a, h = g["away"], g["home"]
        st = g.get("starters_displayed") or g.get("starters_board")
        mlq = g["ml"]["view_a"] if "ml" in g else {"away": g["ml_away"], "home": g["ml_home"]}
        sp = {}
        for side, disp in (("away", st["away"]), ("home", st["home"])):
            name = disp.rsplit("(", 1)[0].strip()
            pid = pids.get(_fold(name))
            if pid is None:
                unmatched.append(name)
                sp[side] = {"pid": None, "name": name, "confirmed": False,
                            "staleness_tier": "PROVISIONAL", "stale_block_verified": False,
                            "no_log": True, "era": None, "gs": None, "k_pct": None, "bb_pct": None}
                continue
            feats, flags = bma.sp_asof_strict(pid, slate_date, ph_by_pid.get(pid, set()))
            last = feats["last_start_date"] if feats else None
            sp[side] = {"pid": int(pid), "name": name, "confirmed": False,
                        "staleness_tier": tier(last, slate_date), "stale_block_verified": False,
                        "no_log": feats is None,
                        "era": feats["era"] if feats else None,
                        "gs": feats["gs"] if feats else None,
                        "k_pct": feats["k_pct"] if feats else None,
                        "bb_pct": feats["bb_pct"] if feats else None,
                        "asof_flags": flags}
        recon = base_reconciled and not ({a, h} & recon_exceptions)
        pf = park.get(venue_by_home.get(h, ""), None)
        games.append({
            "gamePk": None, "slate_date": slate_date, "away": a, "home": h,
            "dh_game": g.get("dh_game"),
            "first_pitch_utc": g.get("first_pitch_utc") or et_to_utc(slate_date, g["time_verbatim"]),
            "first_pitch_verbatim": g.get("time_verbatim") or g.get("first_pitch_utc"),
            "team": {"away": form.get(a), "home": form.get(h)},
            "team_results_complete_through": complete_through,
            "team_results_reconciled": recon,
            "sp": sp, "park_factor": pf,
            "quote": {"book": None,
                      "ml_home": mlq["home"], "ml_away": mlq["away"],
                      "observed_at_utc": boards["observed_at_utc"],
                      "board_view": "view_a (single-book board; operator tab not visible -> book UNRESOLVED)"},
        })

    out = {"record_id": f"P4-SLATE-{slate_date}",
           "built_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "odds_source": {"path": f"data/mlb/odds/{slate_date}_gameboards.json",
                           "sha256": hashlib.sha256(open(f"data/mlb/odds/{slate_date}_gameboards.json", "rb").read()).hexdigest()},
           "assumptions": ["first-pitch times: board shows no TZ; ET presumed (EDT=UTC-4), robustly "
                           "pre-pitch under any US timezone at generation time",
                           "team form: normalized labels, full-season as-of (P2 spec); firewall's "
                           "raw-label keying diverges post-7/19 label switch — disclosed, not hidden"],
           "unmatched_starters": unmatched,
           "team_results_complete_through": complete_through,
           "team_results_holes_in_trailing_14d": result_holes,
           "games": games}
    path = f"data/mlb/slates/{slate_date}_p4_slate.json"
    json.dump(out, open(path, "w"), indent=1)
    print(f"{path}: {len(games)} games; unmatched starters: {unmatched or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "2026-07-29"))
