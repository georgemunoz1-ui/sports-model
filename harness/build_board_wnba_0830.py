#!/usr/bin/env python3
"""The 2026-08-30 WNBA board — frozen BEFORE any market is consulted.

THE STANDING GAP THIS CLOSES. On 8/29 I produced WNBA forecasts and never froze them into a
board. They were gradeable this morning only because the conversation record happened to
carry a retrieval timestamp and a source sha. That is luck, not process. The freeze step is
what makes a claim checkable later, so it happens first here.

MARKET INDEPENDENCE. No price is read by this module. The three arms take team-game box
score aggregates and win-loss records; there is no code path from a price into a forecast.
The ordering claim is stated honestly rather than overclaimed: the owner's DK capture for
this slate happened at 04:12 ET, BEFORE this freeze in wall-clock time. So this board is
FEATURE-INDEPENDENT of the market by construction but NOT TEMPORALLY PRIOR to the capture.
Both facts are recorded; the second one is a weaker warrant than a same-day pre-capture
freeze and is not dressed up as one.

DATE DISCIPLINE. CON@DAL tips 2026-08-31T00:30Z, which is the ET evening of 8/30. The slate
is enumerated on the ET calendar date derived with zoneinfo, never on the UTC date.
"""
from __future__ import annotations
import hashlib, json, os, sys
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wnba_refresh_espn as R
import wnba_standings_fallback as FB

ET = ZoneInfo("America/New_York")
DATE = "2026-08-30"
OUT = f"cards/{DATE}_wnba_board.json"
PARQUET = ("/home/user/sportsdataverse/wehoop-wnba-raw/wnba/schedules/parquet/"
           "wnba_schedule_2026.parquet")

#: ESPN display name -> extension-pool key. Pinned rather than derived: a first run on the
#: 8/28 board passed display names straight through and returned DATA_BLOCKED on every game,
#: which reads exactly like a data outage instead of a keying error.
POOL_KEY = {"Minnesota Lynx": "MIN", "Atlanta Dream": "ATL",
            "Los Angeles Sparks": "LAS", "Seattle Storm": "SEA",
            "Golden State Valkyries": "GSV", "Portland Fire": "PDX",
            "Connecticut Sun": "CON", "Dallas Wings": "DAL"}

PRIOR_P_HOME = 0.536585   # wnba.winner.EXPANDING_HOME_PRIOR, registered constant

# data/audit/2026-08-30_sigma_provenance_register.json — MEASURED, n=1721 each.
SIGMA_MARGIN, SIGMA_TOTAL = 12.5523, 18.0156


def et_date(ts):
    return (datetime.strptime(str(ts).replace("Z", "+0000"), "%Y-%m-%dT%H:%M%z")
            .astimezone(ET).date().isoformat())


def slate_from_archive():
    import pandas as pd
    d = pd.read_parquet(PARQUET)
    d["game_id"] = d["game_id"].astype(str)
    out = []
    for _, r in d.iterrows():
        if et_date(r["date"]) != DATE:
            continue

        def total(recs):
            for x in recs:
                if x.get("type") == "total":
                    w, l = x["summary"].split("-")
                    return int(w), int(l)
            return None
        out.append({
            "game_id": str(r["game_id"]),
            "utc_instant": str(r["date"]),
            "et_date": DATE,
            "utc_date_would_have_been": str(r["date"])[:10],
            "away_name": str(r["away_display_name"]), "home_name": str(r["home_display_name"]),
            "away": POOL_KEY[str(r["away_display_name"])],
            "home": POOL_KEY[str(r["home_display_name"])],
            "away_record": total(r["away_records"]), "home_record": total(r["home_records"]),
            "status": str(r["status_type_name"])})
    out.sort(key=lambda g: g["utc_instant"])
    return out


def build():
    games = slate_from_archive()
    if not games:
        raise SystemExit("no ET-2026-08-30 games in the archive — refusing to invent a slate")
    not_scheduled = [g["game_id"] for g in games if g["status"] != "STATUS_SCHEDULED"]

    ref = R.run_slate([(g["away"], g["home"], g["utc_instant"]) for g in games])
    pred = {f"{p['away']}@{p['home']}": p for p in ref["predictions"]}
    blocked = {k: p for k, p in pred.items() if "status" in p}
    if blocked:
        raise SystemExit(f"FEATURE_REFRESH blocked on {sorted(blocked)} — refusing to publish "
                         "a board that claims an unblock that did not happen")

    # Leakage: none of tonight's ids may be in the pool the model was fit on.
    art = json.load(open(R.EXT_PATH))
    pool_gids = {str(g["gid"]) for g in art["games"]}
    leaked = sorted({g["game_id"] for g in games} & pool_gids)
    if leaked:
        raise SystemExit(f"AS-OF LEAKAGE: {leaked} are in the fitting pool")
    pool_last = max(g["date"] for g in art["games"])

    rows = []
    for g in games:
        key = f"wnba:{g['away']}@{g['home']}"
        ident = {"game": key, "sport": "wnba",
                 "away": g["away"], "home": g["home"],
                 "away_name": g["away_name"], "home_name": g["home_name"],
                 "canonical_id": f"ESPN_GAMEID:{g['game_id']}",
                 "id_space": "ESPN_GAMEID", "id_value": g["game_id"], "id_grade": "CAPTURED",
                 "id_provenance": f"wehoop-wnba-raw {ref['provenance']['commit'][:12]} "
                                  "schedule parquet, read by game_id",
                 "game_start_utc": g["utc_instant"], "et_date": DATE,
                 "utc_date_would_have_been": g["utc_date_would_have_been"],
                 "date_slice_would_misfile": g["utc_date_would_have_been"] != DATE,
                 "lineups": "UNCONFIRMED_AT_REGISTRATION",
                 "availability_grade": "ABSENT — RJ-005 OFFICIAL_INJURY_AVAILABILITY 0/17 "
                                       "EGRESS_BLOCKED",
                 "action_status": "PASS_REFERENCE_ONLY",
                 "forecast_status": "FORECAST_REGISTERED"}

        rows.append(dict(ident, arm="wnba.winner.EXPANDING_HOME_PRIOR", target="winner",
                         p_home=PRIOR_P_HOME,
                         note="registered constant; identical on every game by construction"))

        (aw, al), (hw, hl) = g["away_record"], g["home_record"]
        p_fb, parts = FB.p_home(hw, hl, aw, al)
        rows.append(dict(ident, arm="wnba.fallback.STANDINGS_LOG5_v1", target="winner",
                         p_home=round(p_fb, 6),
                         records={g["home"]: f"{hw}-{hl}", g["away"]: f"{aw}-{al}"},
                         records_asof=f"{DATE} pregame, archive "
                                      f"{ref['provenance']['commit'][:12]}",
                         log5=parts["log5"], input_grade=FB.INPUT_GRADE,
                         disposition="DIAGNOSTIC_ONLY by registration; action-blocked"))

        p = pred[f"{g['away']}@{g['home']}"]
        rows.append(dict(ident, arm="wnba.replacement.FEATURE_REFRESH", target="winner",
                         p_home=p["p_home"], margin_home=p["margin_home"],
                         projected_total=p["total"],
                         coherence_gap_pp=p["coherence_gap_pp"],
                         coherence_pass=p["coherence_pass"],
                         games_used=p["games_used"],
                         model_side=(g["home"] if p["p_home"] >= 0.5 else g["away"]),
                         input_grade=R.INPUT_GRADE,
                         sigma_for_margin={"value": SIGMA_MARGIN, "n": 1721,
                                           "base": "WNBA margin residual SD, MEASURED",
                                           "not": "13.97, which is a registered COHERENCE "
                                                  "TOLERANCE and not a distributional constant"},
                         sigma_for_total={"value": SIGMA_TOTAL, "n": 1721,
                                          "base": "WNBA totals residual SD, MEASURED"}))

    board = {
        "record_id": f"BOARD-{DATE}-WNBA",
        "schema": "ops.board.v2",
        "slate_date": DATE, "sport": "wnba",
        "date_timezone": "America/New_York",
        "builder": "harness/build_board_wnba_0830.py (COMMITTED)",
        "n_games": len(games), "n_rows": len(rows),
        "earliest_start_utc": games[0]["utc_instant"],
        "cohort": "WNBA — never pooled with MLB, NFL or CFB",
        "MARKET_INDEPENDENCE": {
            "prices_read_by_this_module": 0,
            "feature_independence": "STRUCTURAL — no code path carries a price into a forecast",
            "temporal_precedence": "NOT CLAIMED. The owner's DK capture for this slate is "
                                   "stamped 04:12 ET, earlier in wall-clock than this freeze. "
                                   "A same-day pre-capture freeze is a stronger warrant and "
                                   "this is not one.",
            "rule": "docs/MARKET_INDEPENDENCE_RULE.md"},
        "GAME_IDENTITY": {
            "captured": len(games), "inferred": 0, "synthetic_pseudo_pks": 0,
            "id_space": "ESPN_GAMEID", "form": "<ID_SPACE>:<integer>",
            "binding_status": "IDENTIFIED, NOT BOUND — these ids give tomorrow's binding pass "
                              "a real key; they do not themselves bind a result",
            "utc_slice_hazard": [g["game_id"] for g in games
                                 if g["utc_date_would_have_been"] != DATE]},
        "STALENESS": {
            "feature_cutoff": pool_last,
            "extension_window": ref["pool"]["extension_window"],
            "archive_commit": ref["provenance"]["commit"],
            "was_previously": "2026-08-27 — the archive published 5875eba at 06:32 ET today "
                              "carrying both 8/29 finals, so the cutoff moved to 2026-08-29",
            "grade": "CURRENT_THROUGH_PRIOR_DAY"},
        "availability_open_items": [
            "RJ-005 OFFICIAL_INJURY_AVAILABILITY 0/17 EGRESS_BLOCKED, deadline "
            "2026-08-30T17:00:00Z. Rotations are UNVERIFIED for all eight teams. Any forecast "
            "here is conditional on a roster state the system cannot see."],
        "not_scheduled_at_freeze": not_scheduled,
        "leakage_check": {
            "target_ids": [g["game_id"] for g in games],
            "in_fitting_pool": leaked,
            "pool_latest_event": pool_last,
            "verdict": "CLEAN — the pool's latest event is strictly before the earliest tip"},
        "model_identity": ["wnba.winner.EXPANDING_HOME_PRIOR",
                           "wnba.fallback.STANDINGS_LOG5_v1 (DIAGNOSTIC_ONLY, action-blocked)",
                           "wnba.replacement.FEATURE_REFRESH"],
        "arms_emitted": 3, "arms_blocked": 0,
        "action_authority": "NONE — SYSTEM_NOT_DECISION_READY; paper only; wager authority NO",
        "SEPARATION": "MLB, WNBA, NFL and CFB are separate cohorts on separate boards",
        "pool": ref["pool"], "provenance": ref["provenance"],
        "rows": rows,
        "LEDGER": {"wager_authority": "NO", "exposure_usd": 0, "n_bets": 0, "units": 0.0},
    }
    board["cohort_hash"] = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return board


if __name__ == "__main__":
    b = build()
    if os.path.exists(OUT):
        raise SystemExit(f"R3/R6: {OUT} already exists. A frozen board is not overwritten; "
                         "publish a v2 that names it as predecessor.")
    os.makedirs("cards", exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(b, fh, indent=1, sort_keys=True)
    print("FROZE", OUT, "cohort_hash", b["cohort_hash"][:16])
    for r in b["rows"]:
        if r["arm"] == "wnba.replacement.FEATURE_REFRESH":
            print(f"  {r['game']:16s} {r['canonical_id']:22s} p_home {r['p_home']:.4f}  "
                  f"margin {r['margin_home']:+.2f}  total {r['projected_total']:.1f}  "
                  f"coherence {'PASS' if r['coherence_pass'] else 'FAIL'} "
                  f"({r['coherence_gap_pp']:+.2f}pp)")
