"""The 2026-08-28 WNBA board — partial by design, and precise about which part is missing.

WHY THIS BOARD EXISTS AT ALL. It was nearly not built. The registered arm
wnba.replacement.FEATURE_REFRESH needs the extension pool rebuilt through the 2026-08-27 cutoff,
and the wehoop archive has not published the 8/27 boxes (still at 3316fa3, committed 8/27 06:34
ET, with zero completed 8/27 rows). Rebuild-first is a real rule and it is not waived.

But "one arm's input is stale" is not "the board cannot be built". Three arms are registered and
only ONE of them consumes the feature pool:

    wnba.winner.EXPANDING_HOME_PRIOR    a registered constant; no inputs at all; NEVER blockable
    wnba.fallback.STANDINGS_LOG5_v1     season win-loss records only; self-contained by design
    wnba.replacement.FEATURE_REFRESH    consumes the extension pool -> genuinely blocked

Suppressing all three because one is blocked is the exact defect the owner named on 2026-08-27:
action blockers suppressing valid model output. A blocker suppresses what it actually reaches.
So two arms are emitted with their real numbers and the third is emitted as an explicit null
carrying its reason, which is a different object from a missing row.

THE ONE-GAME STALENESS, MEASURED RATHER THAN WAVED AT. The records come from the 8/28 scheduled
rows of the same parquet, so they are current through 8/26. Of tonight's eight teams exactly one
— the Washington Mystics — played on 8/27 (at Phoenix), so exactly one record is stale by exactly
one game, and its result is not bound anywhere. Rather than assert a record we do not have, the
WSH@LAS row is computed under BOTH outcomes and carries the resulting interval. The other three
games are unaffected and are exact.

GRADE. Schedule is ESPN_SINGLE_FAMILY_GIT_ARTIFACT (wehoop mirrors ESPN, so the corroborating
ESPN URLs are the same family and add no independent source). Fallback output is
DIAGNOSTIC_ONLY_ACTION_BLOCKED by its own registration: it never settles, never promotes, never
enters the estimator. Availability is SEARCH_IDENTIFIED_UNCONFIRMED and binds nothing.
"""
from __future__ import annotations

MODULE_ID = "build_board_wnba_0828"

import datetime as dt
import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wnba_standings_fallback as FB

SLATE_DATE = "2026-08-28"
SLATE_BINDING = f"data/wnba/slates/{SLATE_DATE}_slate_binding.json"
PARQUET = ("/home/user/sportsdataverse/wehoop-wnba-raw/wnba/schedules/parquet/"
           "wnba_schedule_2026.parquet")
WEHOOP_COMMIT = "3316fa3c116a3d6ce2549699bd65a47d0e6773d5"
EARLIEST_START_UTC = "2026-08-28T23:30:00Z"

HOME_PRIOR = 0.536585   # wnba.winner.EXPANDING_HOME_PRIOR, 21-game provisional

ABBR = {"Portland Fire": "POR", "Atlanta Dream": "ATL", "Connecticut Sun": "CON",
        "Indiana Fever": "IND", "Toronto Tempo": "TOR", "Las Vegas Aces": "LV",
        "Washington Mystics": "WSH", "Los Angeles Sparks": "LAS"}

#: Teams that played on 2026-08-27 and whose record is therefore one game stale in this parquet.
#: Derived below from the parquet itself, never hand-asserted; this is only the expected answer.
STALE_EXPECTED = {"Washington Mystics"}


def load_rows():
    import pandas as pd
    df = pd.read_parquet(PARQUET)
    df["et"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert("America/New_York")
    done = df[df["status_type_completed"] == True]          # noqa: E712
    latest_done = str(done["et"].dt.date.max())
    # Teams whose record is stale are those that HAD A GAME on 8/27, whether or not the archive
    # recorded its outcome. Deriving this from COMPLETED rows returns the empty set here — the
    # archive has zero completed 8/27 rows, which is the very reason this board is partial — and
    # would have silently reported "no stale records" on a slate that has one. Scheduled rows are
    # the correct source for the question "did this team play".
    played_0827 = set()
    for _, r in df[df["et"].dt.date.astype(str) == "2026-08-27"].iterrows():
        played_0827 |= {r["away_display_name"], r["home_display_name"]}
    slate = df[df["et"].dt.date.astype(str) == SLATE_DATE]
    out = []
    for _, r in slate.iterrows():
        def rec(side):
            for d in r[f"{side}_records"]:
                if d.get("type") == "total":
                    w, l = d["summary"].split("-")
                    return int(w), int(l)
            raise ValueError(f"no total record for {side} in game {r['id']}")
        out.append({"id": int(r["id"]), "away": r["away_display_name"],
                    "home": r["home_display_name"], "start_utc": str(r["date"]),
                    "away_rec": rec("away"), "home_rec": rec("home")})
    return out, latest_done, played_0827


def freeze(out_path=f"cards/{SLATE_DATE}_wnba_board.json"):
    binding = json.load(open(SLATE_BINDING))
    starts = {r["canonical_id"].split(":")[1]: r["start_utc"] for r in binding["rows"]}
    notes = {r["canonical_id"].split(":")[1]: r["notes"] for r in binding["rows"]}

    games, latest_done, played_0827 = load_rows()
    if len(games) != 4:
        raise ValueError(f"expected 4 WNBA games on {SLATE_DATE}, parquet gave {len(games)}")
    if latest_done >= SLATE_DATE:
        raise ValueError(f"parquet reports completed games on {latest_done} — this board assumes "
                         "the archive has NOT advanced; re-check before trusting the block reason")

    tonight = {g["away"] for g in games} | {g["home"] for g in games}
    stale = sorted(tonight & played_0827)
    if set(stale) != STALE_EXPECTED:
        raise ValueError(f"stale-record set changed: expected {sorted(STALE_EXPECTED)}, got "
                         f"{stale}. The archive moved or the slate did; re-derive before freezing.")

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for g in games:
        gid = f"wnba:{ABBR[g['away']]}@{ABBR[g['home']]}"
        cid = f"ESPN_GAMEID:{g['id']}"
        start = starts.get(str(g["id"]), g["start_utc"])
        base = {"game": gid, "sport": "wnba", "away": g["away"], "home": g["home"],
                "canonical_id": cid, "id_space": "ESPN_GAMEID", "id_grade": "CAPTURED",
                "game_start_utc": start,
                "schedule_grade": "ESPN_SINGLE_FAMILY_GIT_ARTIFACT",
                "lineups": "PERSONNEL_UNVERIFIED",
                "availability_grade": "SEARCH_IDENTIFIED_UNCONFIRMED",
                "action_status": "NO_RETAINED_MARKET_ARTIFACT",
                "forecast_status": "FORECAST_REGISTERED"}

        # --- arm 1: registered constant. No input, so nothing can block it.
        rows.append(dict(base, arm="wnba.winner.EXPANDING_HOME_PRIOR", target="winner",
                         p_home=HOME_PRIOR, output_grade="REGISTERED_PRIOR",
                         input_dependency="NONE"))

        # --- arm 2: log5 on season records.
        hw, hl = g["home_rec"]
        aw, al = g["away_rec"]
        p, parts = FB.p_home(hw, hl, aw, al)
        if p is None:
            raise ValueError(f"{gid}: fallback refused with {parts}")
        row = dict(base, arm=FB.IDENTITY, target="winner", p_home=p,
                   records={ABBR[g["home"]]: f"{hw}-{hl}", ABBR[g["away"]]: f"{aw}-{al}"},
                   records_asof="2026-08-26 (latest completed date in the parquet)",
                   output_grade=FB.OUTPUT_GRADE, input_grade="WEHOOP_GIT_ARTIFACT_RECORDS",
                   input_dependency="SEASON_RECORDS_ONLY", log5=parts["log5"])

        # the one stale record, bounded rather than assumed
        if g["home"] in stale or g["away"] in stale:
            side = "home" if g["home"] in stale else "away"
            lo, _ = (FB.p_home(hw + 1, hl, aw, al) if side == "home"
                     else FB.p_home(hw, hl, aw + 1, al))
            hi, _ = (FB.p_home(hw, hl + 1, aw, al) if side == "home"
                     else FB.p_home(hw, hl, aw, al + 1))
            row["record_staleness"] = {
                "team": ABBR[g[side]], "side": side,
                "detail": f"{g[side]} played on 2026-08-27 (at Phoenix) and that result is not in "
                          "this parquet and is not bound anywhere, so its record is stale by "
                          "exactly one game.",
                "p_home_if_that_game_was_a_win": round(lo, 6),
                "p_home_if_that_game_was_a_loss": round(hi, 6),
                "interval_width_pp": round(100 * abs(hi - lo), 3),
                "reported_value_uses": "the parquet record as-is; the interval bounds the error "
                                       "rather than picking an outcome we do not have",
            }
        rows.append(row)

        # --- arm 3: blocked. An explicit null with a reason, NOT a missing row.
        rows.append(dict(base, arm="wnba.replacement.FEATURE_REFRESH", target="winner",
                         p_home=None, margin_home=None, projected_total=None,
                         forecast_status="BLOCKED_PENDING_FEATURE_REBUILD",
                         null_reason="EXTENSION_POOL_NOT_REBUILT_THROUGH_2026-08-27",
                         blocked_detail=(
                             "this arm consumes the extension pool, which must be rebuilt through "
                             "the 8/27 cutoff before it may forecast. The wehoop archive is still "
                             f"at {WEHOOP_COMMIT[:7]} (committed 8/27 06:34 ET) and carries ZERO "
                             "completed 2026-08-27 rows, so the rebuild cannot run. Rebuild-first "
                             "is not waived because a slate happens to be available."),
                         input_dependency="EXTENSION_POOL_THROUGH_CUTOFF"))

    emitted = sum(1 for r in rows if r["p_home"] is not None)
    blocked = sum(1 for r in rows if r["p_home"] is None)
    if emitted != 8 or blocked != 4:
        raise ValueError(f"expected 8 emitted and 4 blocked arm-rows, got {emitted}/{blocked}")

    def cohort_hash(rows_):
        return hashlib.sha256(json.dumps(rows_, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()

    board = {
        "record_id": f"BOARD-{SLATE_DATE}-WNBA",
        "slate_date": SLATE_DATE,
        "sport": "wnba",
        "builder": "harness/build_board_wnba_0828.py (COMMITTED)",
        "forecast_anchor_utc": now,
        "earliest_start_utc": EARLIEST_START_UTC,
        "chronology_status": ("ANCHOR_PRECEDES_EARLIEST_START"
                              if now < EARLIEST_START_UTC else "ANCHOR_AFTER_EARLIEST_START"),
        "cohort": "WNBA — never pooled with MLB or NFL",
        "n_games": len(games),
        "PARTIAL_BOARD": {
            "emitted_arms": ["wnba.winner.EXPANDING_HOME_PRIOR",
                             "wnba.fallback.STANDINGS_LOG5_v1"],
            "blocked_arms": ["wnba.replacement.FEATURE_REFRESH"],
            "arm_rows_emitted": emitted, "arm_rows_blocked": blocked,
            "why_partial_and_not_absent": (
                "One registered arm is genuinely blocked: FEATURE_REFRESH consumes an extension "
                "pool that must be rebuilt through the 2026-08-27 cutoff, and the archive has not "
                "published 8/27. The other two arms do not touch that pool — EXPANDING_HOME_PRIOR "
                "is a registered constant with no inputs and STANDINGS_LOG5_v1 runs on season "
                "records alone. Suppressing all three because one is blocked would be the defect "
                "the owner named on 2026-08-27: an action blocker suppressing valid model output. "
                "A blocker suppresses what it actually reaches, and this one reaches one arm."),
            "blocked_is_a_null_not_a_gap": (
                "the FEATURE_REFRESH rows are present on the board with p_home null and a stated "
                "null_reason. A null with a reason is a different object from a missing row."),
        },
        "model_identity": ["wnba.winner.EXPANDING_HOME_PRIOR",
                           "wnba.fallback.STANDINGS_LOG5_v1 (DIAGNOSTIC_ONLY, action-blocked)",
                           "wnba.replacement.FEATURE_REFRESH (BLOCKED)"],
        "PRIORS": {"wnba_home": {"p": HOME_PRIOR, "n": 21,
                                 "note": "registered provisional prior; single source of truth, "
                                         "read from wnba_standings_fallback"}},
        "INPUTS": {
            "schedule_repo": "github.com/sportsdataverse/wehoop-wnba-raw",
            "commit": WEHOOP_COMMIT,
            "parquet": "wnba/schedules/parquet/wnba_schedule_2026.parquet",
            "latest_completed_date_in_parquet": latest_done,
            "completed_rows_on_2026-08-27": 0,
            "records_asof": latest_done,
            "single_family_caveat": ("wehoop is an ESPN mirror, so ESPN URLs corroborating these "
                                     "ids are the same family and add no independent source"),
        },
        "RECORD_STALENESS": {
            "teams_playing_tonight_that_played_2026-08-27": stale,
            "n_stale_of_8": len(stale),
            "handling": ("the affected game is computed under BOTH outcomes and carries the "
                         "interval; the reported value uses the parquet record as-is. No record "
                         "was rolled forward on an unbound result."),
            "unaffected_games": [f"wnba:{ABBR[g['away']]}@{ABBR[g['home']]}" for g in games
                                 if g["home"] not in stale and g["away"] not in stale],
        },
        "GAME_IDENTITY": {
            "field": "canonical_id", "form": "ESPN_GAMEID:<integer>",
            "captured": len(games), "inferred": 0, "synthetic_pseudo_pks": 0,
            "inference_refused": ("all four ids sit on a contiguous run 401857180-401857183 and "
                                  "the surrounding parquet rows continue it — exactly the shape "
                                  "that invites the 8/27 P0. Each id was read from its own "
                                  "parquet row."),
            "normalization": ("the acquisition emitted these as BARE integers, which are "
                              "indistinguishable from an MLB gamePk; namespaced before any "
                              "artifact was written"),
        },
        "availability_open_items": binding["availability_open_items"],
        "action_authority": ("NONE — NO_RETAINED_MARKET_ARTIFACT and the fallback arm is "
                             "DIAGNOSTIC_ONLY by registration. No selection, no EV, no wager."),
        "SEPARATION": "MLB, WNBA and NFL are separate cohorts on separate boards, never pooled",
        "LEDGERS": {"model_authorized_wagers_usd": 0, "n_bets": 0, "units": 0.0},
        "cohort_hashes": {"wnba": cohort_hash(rows)},
        "wnba": {"cohort_id": f"wnba:{SLATE_DATE}", "n_games": len(games), "rows": rows},
        "notes_by_game": {f"ESPN_GAMEID:{g['id']}": notes.get(str(g["id"])) for g in games},
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(board, fh, indent=1, sort_keys=True)
    return board


if __name__ == "__main__":
    b = freeze()
    print("FROZEN", b["record_id"], "| wnba", b["cohort_hashes"]["wnba"][:8],
          "|", b["chronology_status"])
    print("arms emitted", b["PARTIAL_BOARD"]["arm_rows_emitted"],
          "/ blocked", b["PARTIAL_BOARD"]["arm_rows_blocked"])
    for r in b["wnba"]["rows"]:
        if r["arm"] == "wnba.fallback.STANDINGS_LOG5_v1":
            st = r.get("record_staleness")
            tail = (f"  [stale {st['team']}: {100*st['p_home_if_that_game_was_a_win']:.2f}"
                    f"-{100*st['p_home_if_that_game_was_a_loss']:.2f}%]") if st else ""
            print(f"  {r['game']:<14} {r['canonical_id']:<22} log5 p_home {r['p_home']:.4f} "
                  f"{r['records']}{tail}")
