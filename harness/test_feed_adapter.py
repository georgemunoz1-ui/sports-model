"""FU-1 feed adapter tests — ET dates, probable-vs-confirmed gating, conflict surfacing,
and the offline 2026-08-28 binding fixture (15 games: 10 ESPN_GAMEID + 5 MLB_GAMEPK).

The binding test is OFFLINE by design: it reads cached fixtures under
data/feeds/fixtures/2026-08-28/. A live network pass is attempted only with --live.

2026-08-30, owner ruling. As delivered, the StatsAPI half of the 15/15 came from
mlb_statsapi_schedule.json, which carried the five REAL captured gamePks from the frozen 8/28
board with INVENTED scores — two of which flipped the winner against the genuine
mlb_statsapi_schedule_LIVE_capture.json sitting unused in the same directory. The fixture was
honestly labelled SYNTHETIC_CACHED_FIXTURE, so this was disclosure working; but a synthetic score
attached to a real provider id is one careless import away from a fabricated final, which is the
exact class of defect that published five bad finals on 2026-08-27. The label was the only thing
preventing it and nothing structural was.

So: the synthetic fixture's ids were moved into a reserved 999xxxxxx range and given a synthetic
counterparty board, and the headline 15/15 now binds against the GENUINE live capture. The
headline number is unchanged and is now entirely real, where a third of it used to be invented.
test_synthetic_fixture_cannot_bind_production_board is the structural guard the label was
standing in for.
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


#: the five games the 8/28 board carries as MLB_GAMEPK rather than ESPN_GAMEID. The ESPN
#: scoreboard fixture supplies the other ten, so these five are the StatsAPI half.
STATSAPI_HALF = ("824231", "823504", "823744", "823985", "824960")


def fixture_rows():
    """Result rows from the cached 2026-08-28 fixtures (10 ESPN + 5 StatsAPI finals).

    The StatsAPI half reads the LIVE_CAPTURE, not the synthetic fixture. Both are committed;
    only one of them contains real scores, and the headline binding claim must rest on that one.
    """
    espn_payload = json.load(open(os.path.join(FIXTURE_DIR, "espn_scoreboard_mlb.json")))
    live = json.load(open(os.path.join(FIXTURE_DIR, "mlb_statsapi_schedule_LIVE_capture.json")))
    assert live["_capture"]["label"] == "LIVE_CAPTURE", "the headline 15/15 must not rest on a fixture"
    trimmed = {"dates": [{"games": [g for d in live["dates"] for g in d["games"]
                                    if str(g["gamePk"]) in STATSAPI_HALF]}]}
    espn_recs = feed_espn.parse_scoreboard(espn_payload, "mlb", FETCHED)
    sa_recs = feed_mlb_statsapi.parse_schedule(trimmed, FETCHED)
    return feed_espn.result_rows(espn_recs) + feed_mlb_statsapi.result_rows(sa_recs)


def synthetic_rows_and_board():
    """The SYNTHETIC fixture and its SYNTHETIC counterparty board — logic only, no real ids."""
    payload = json.load(open(os.path.join(FIXTURE_DIR, "mlb_statsapi_schedule.json")))
    assert payload["_fixture"]["label"] == "SYNTHETIC_CACHED_FIXTURE"
    board = json.load(open(os.path.join(FIXTURE_DIR, "mlb_board_SYNTHETIC.json")))
    recs = feed_mlb_statsapi.parse_schedule(payload, FETCHED)
    return feed_mlb_statsapi.result_rows(recs), board


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


def test_synthetic_fixture_binds_against_synthetic_board():
    """The binding LOGIC, proved without a real provider id anywhere in the exercise."""
    rows, board = synthetic_rows_and_board()
    assert len(rows) == 5
    proof = result_binding_gate.binding_proof(rows, board, "mlb:2026-08-28-SYNTHETIC")
    assert proof["counters"]["RESULT_BINDING_PASS"] == "5/5", proof["counters"]
    assert proof["gradable"]


def test_synthetic_fixture_cannot_bind_production_board():
    """THE STRUCTURAL GUARD. A synthetic score must be incapable of binding a real board game.

    Before 2026-08-30 this test would have FAILED: the synthetic fixture carried the real
    captured gamePks, so its invented scores bound the frozen board cleanly — including two that
    named the wrong winner. Only the _fixture label stood between that and a published final.
    """
    rows, _ = synthetic_rows_and_board()
    proof = result_binding_gate.binding_proof(rows, board_0828(), "mlb:2026-08-28")
    assert proof["counters"]["RESULT_BINDING_PASS"] == "0/5", proof["counters"]
    assert not proof["gradable"]
    assert not proof["aggregate_verdict"]["aggregates_permitted"]


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
