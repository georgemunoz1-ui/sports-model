"""FU-1 feed adapter tests — ET dates, probable-vs-confirmed gating, conflict surfacing,
and the offline 2026-08-28 binding fixture (15 games: 10 ESPN_GAMEID + 5 MLB_GAMEPK).

The binding test is OFFLINE by design: it reads cached fixtures under
data/feeds/fixtures/2026-08-28/ (committed, labelled SYNTHETIC scores; ids are the real CAPTURED
ids from the frozen 8/28 MLB board). A live network pass is attempted only with --live.
"""
from __future__ import annotations

MODULE_ID = "test_feed_adapter"

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import feed_espn
import feed_mlb_statsapi
import feed_sweep
import result_binding_gate

FIXTURE_DIR = os.path.join(REPO, "data", "feeds", "fixtures", "2026-08-28")
BOARD_PATH = os.path.join(REPO, "cards", "2026-08-28_mlb_board.json")

FETCHED = "2026-08-30T00:00:00Z"


# ------------------------------------------------------------------ helpers

def board_0828():
    """The binding-gate board view of the frozen 8/28 MLB board (read-only; never modified).

    Each game's canonical_id from the frozen board becomes the board game_pk — namespace intact.
    """
    doc = json.load(open(BOARD_PATH))
    games = {}
    seen = set()
    for row in doc["mlb"]["rows"]:
        g = row["game"]
        if g in seen:
            continue
        seen.add(g)
        games[g] = {"game_pk": row["canonical_id"],
                    "away": g.split(":")[1].split("@")[0],
                    "home": g.split("@")[1],
                    "start_utc": row["game_start_utc"]}
    return {"sport": "mlb", "slate_date": "2026-08-28", "games": games}


def fixture_rows():
    """Result rows from the cached 2026-08-28 fixtures (10 ESPN + 5 StatsAPI finals)."""
    espn_payload = json.load(open(os.path.join(FIXTURE_DIR, "espn_scoreboard_mlb.json")))
    sa_payload = json.load(open(os.path.join(FIXTURE_DIR, "mlb_statsapi_schedule.json")))
    espn_recs = feed_espn.parse_scoreboard(espn_payload, "mlb", FETCHED)
    sa_recs = feed_mlb_statsapi.parse_schedule(sa_payload, FETCHED)
    return feed_espn.result_rows(espn_recs) + feed_mlb_statsapi.result_rows(sa_recs)


# ------------------------------------------------------------------ tests

def test_et_date_derivation_crosses_utc_midnight():
    # 00:10Z on 8/29 is 8:10pm ET on 8/28 — the known UTC_SLICE_BUG class
    assert feed_espn.et_date_of("2026-08-29T00:10:00Z") == "2026-08-28"
    assert feed_espn.et_date_of("2026-08-29T02:15:00Z") == "2026-08-28"
    assert feed_espn.et_date_of("2026-08-28T18:20:00Z") == "2026-08-28"
    # winter (EST) late-night crossing
    assert feed_espn.et_date_of("2026-01-15T02:30:00Z") == "2026-01-14"
    # DST midnight boundary
    assert feed_espn.et_date_of("2026-07-01T03:59:00Z") == "2026-06-30"


def test_probable_never_mints_confirmed():
    sched = {"dates": [{"games": [{
        "gamePk": 1, "gameDate": "2026-08-28T23:00:00Z",
        "status": {"detailedState": "Scheduled", "statusCode": "S"},
        "teams": {"away": {"team": {"name": "Boston Red Sox"}},
                  "home": {"team": {"name": "New York Yankees"}}},
        "probablePitchers": {"away": {"fullName": "A"}, "home": {"fullName": "B"}}}]}]}
    rec = feed_mlb_statsapi.parse_schedule(sched, FETCHED)[0]
    gated = feed_mlb_statsapi.confirmed_starter_or_probable(rec, None)
    assert gated["away"]["grade"] == "IDENTIFIED_UNCONFIRMED"
    assert gated["home"]["grade"] == "IDENTIFIED_UNCONFIRMED"
    # a boxscore without gamesStarted does not confirm either
    bs = {"teams": {"away": {"players": {"p": {"person": {"fullName": "A", "id": 1},
                                              "stats": {"pitching": {}}}}},
                    "home": {"players": {}}}, "info": []}
    parsed = feed_mlb_statsapi.parse_boxscore_starters(bs, 1, FETCHED)
    gated2 = feed_mlb_statsapi.confirmed_starter_or_probable(rec, parsed)
    assert gated2["away"]["grade"] == "IDENTIFIED_UNCONFIRMED"
    # only gamesStarted in a live/final boxscore confirms
    bs2 = {"teams": {"away": {"players": {"p": {"person": {"fullName": "A", "id": 1},
                                               "stats": {"pitching": {"gamesStarted": 1}}}}},
                     "home": {"players": {}}}, "info": []}
    gated3 = feed_mlb_statsapi.confirmed_starter_or_probable(
        rec, feed_mlb_statsapi.parse_boxscore_starters(bs2, 1, FETCHED))
    assert gated3["away"]["grade"] == "CONFIRMED"
    assert gated3["home"]["grade"] == "IDENTIFIED_UNCONFIRMED"  # probable stays probable


def test_cross_feed_conflict_surfaced_not_resolved():
    espn_recs = feed_espn.parse_scoreboard({"events": [
        {"id": "9", "date": "2026-08-28T23:10Z",
         "status": {"type": {"name": "STATUS_FINAL", "completed": True}},
         "competitions": [{"competitors": [
             {"homeAway": "away", "team": {"abbreviation": "HOU"}, "score": "4"},
             {"homeAway": "home", "team": {"abbreviation": "NYM"}, "score": "2"}]}]}]},
        "mlb", FETCHED)
    sa_recs = feed_mlb_statsapi.parse_schedule({"dates": [{"games": [{
        "gamePk": 9, "gameDate": "2026-08-28T23:10:00Z",
        "status": {"detailedState": "Final", "statusCode": "F"},
        "teams": {"away": {"team": {"name": "Houston Astros"}, "score": 9},
                  "home": {"team": {"name": "New York Mets"}, "score": 9}}}]}]}, FETCHED)
    lines, conflicts = feed_sweep.reconcile_mlb(espn_recs, sa_recs)
    assert any(c["kind"] == "SCORE_DISAGREEMENT" for c in conflicts), conflicts
    # and a game present on only one feed is a CONFLICT too, not a silent drop
    _, c2 = feed_sweep.reconcile_mlb(espn_recs, [])
    assert any(c["kind"] == "MISSING_FROM_STATSAPI" for c in c2)


def test_0828_cohort_binds_15_of_15_offline_fixture():
    """THE FU-1 target: the 8/28 MLB cohort binds 15/15 from feed-produced result rows."""
    board = board_0828()
    assert len(board["games"]) == 15
    rows = fixture_rows()
    assert len(rows) == 15, f"fixtures must produce 15 result rows, got {len(rows)}"
    proof = result_binding_gate.binding_proof(rows, board, "mlb:2026-08-28")
    assert proof["counters"]["RESULT_BINDING_PASS"] == "15/15", proof["counters"]
    assert proof["counters"]["DATE_COHERENCE_PASS"] == "15/15", proof["counters"]
    assert proof["counters"]["CANONICAL_ID_MATCH"] == "15/15", proof["counters"]
    assert proof["gradable"], proof["cohort_problems"]
    assert proof["aggregate_verdict"]["aggregates_permitted"]
    # and the guarded aggregate path permits the statistic without an override
    out = result_binding_gate.guarded_aggregate(proof, "winner_record")
    assert out["permitted"] and not out.get("cohort_did_not_bind")


def test_result_rows_carry_provenance_stamps():
    for row in fixture_rows():
        assert row["source"] in ("espn_scoreboard_api", "mlb_statsapi")
        assert row["fetched_utc"]
        assert ":" in row["game_pk"]  # namespace is load-bearing


if __name__ == "__main__":
    # runnable without pytest, healthcheck-style
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    bad = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok {fn.__name__}")
        except Exception as e:
            bad += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"test_feed_adapter selftest: {'OK' if not bad else 'FAIL'} "
          f"({len(fns) - bad}/{len(fns)})")
    sys.exit(1 if bad else 0)
