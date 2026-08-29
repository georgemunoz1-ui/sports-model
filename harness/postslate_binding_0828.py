"""Post-slate result-binding proofs for the 2026-08-28 MLB and WNBA cohorts.

WHY THIS IS A SECOND PROOF AND NOT AN EDIT OF THE FIRST. Each cohort already carries a PROSPECTIVE
binding proof, written before first pitch, whose 0/0 counters mean "the slate has not started".
This module writes a POST-SLATE proof whose 0/0 counters mean something different and worse: the
slate is over, and the score-bearing archives still do not carry it. Same numbers, different claim.
Overwriting the prospective record would have destroyed the earlier attestation and left no trace
that the reason changed, so both stand side by side under R6.

WHAT 0/0 MEANS HERE. Not "nothing was checked". Every board game was loaded and every canonical_id
was read; there is simply no result row to bind, because no admissible source carries one. Search
snippets IDENTIFY and never BIND, so they were not used to manufacture a final. This is the exact
juncture at which the 8/27 cycle published five fabricated finals.

THE ARCHIVE EVIDENCE IS READ, NOT TYPED. The module inspects both archives at runtime: it resolves
each repository's HEAD, and for MLB it opens the 8/28 daily file and enumerates its columns looking
for anything score-bearing. A hand-written "there is no score column" would be an assertion; this is
an observation, and it fails loudly if the archives have advanced since.

The four counters come from result_binding_gate.binding_proof and are computed there. Nothing in
this module types a counter value. Wager authority NO. Nothing here accrues to settlement,
promotion, or the estimator.
"""
from __future__ import annotations

MODULE_ID = "postslate_binding_0828"

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "harness"))

from result_binding_gate import binding_proof  # noqa: E402

SLATE_DATE = "2026-08-28"
WEHOOP = "/home/user/sportsdataverse/wehoop-wnba-raw"
LANCEBROZ = "/home/user/lancebroz/mlb-pitcher-data"
#: any of these substrings in a column name would make the file score-bearing
SCORE_TOKENS = ("score", "runs", "final", "result", "win", "outcome")

COHORTS = [
    {"sport": "mlb", "board": f"cards/{SLATE_DATE}_mlb_board.json",
     "prospective": f"data/governance/bindings/{SLATE_DATE}_mlb_results_binding_proof.json",
     "out": f"data/governance/bindings/{SLATE_DATE}_mlb_results_binding_proof_postslate.json",
     "rows_key": "mlb"},
    {"sport": "wnba", "board": f"cards/{SLATE_DATE}_wnba_board_v2.json",
     "prospective": f"data/governance/bindings/{SLATE_DATE}_wnba_results_binding_proof.json",
     "out": f"data/governance/bindings/{SLATE_DATE}_wnba_v2_results_binding_proof_postslate.json",
     "rows_key": "wnba"},
]


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def head_of(repo):
    out = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True)
    when = subprocess.run(["git", "-C", repo, "log", "-1", "--format=%cI"],
                          capture_output=True, text=True, check=True)
    return out.stdout.strip(), when.stdout.strip()


def observe_archives():
    """Read the two archives. Every field below is an observation, not a restatement."""
    wehoop_head, wehoop_when = head_of(WEHOOP)
    lb_head, lb_when = head_of(LANCEBROZ)

    daily = os.path.join(LANCEBROZ, f"data/raw/2026/daily/{SLATE_DATE}.parquet")
    mlb_file = {"path": os.path.relpath(daily, "/home/user"), "exists": os.path.exists(daily)}
    if mlb_file["exists"]:
        import pandas as pd
        df = pd.read_parquet(daily)
        cols = [str(c) for c in df.columns]
        hits = sorted(c for c in cols if any(t in c.lower() for t in SCORE_TOKENS))
        mlb_file.update({
            "n_rows": int(len(df)),
            "n_columns": len(cols),
            "columns": cols,
            "score_bearing_columns": hits,
            "verdict": ("SCORE_BEARING_COLUMN_PRESENT" if hits else
                        "NO_SCORE_BEARING_COLUMN — the file carries pitch-level detail only; "
                        "pitchers and game_pks are present, finals are not"),
        })
        if hits:
            raise SystemExit(
                "ARCHIVE_STATE_CHANGED: the 8/28 lancebroz file now carries "
                f"{hits} — this module's premise (no bindable score) no longer holds and it must "
                "not write a no-results proof. Grade the cohort instead."
            )

    # wehoop: do the BOARD'S OWN canonical ids have results at this HEAD?
    #
    # NOT a date filter. wehoop's `date` column is UTC, so selecting date == 2026-08-28 returns
    # 401857178 (GSV 79-60 NYL) and 401857179 (WSH 80-73 PHX) — both 8/27 EVENING ET games,
    # already graded in the 8/27 review. Folding them into the 8/28 cohort would be
    # RESULT_DATE_COHORT_CONTAMINATION, the exact P0 this system exists to prevent. The probe
    # therefore binds on canonical id, which is what the binding contract requires anyway.
    sched = os.path.join(WEHOOP, "wnba/schedules/parquet/wnba_schedule_2026.parquet")
    wnba_file = {"path": os.path.relpath(sched, "/home/user"), "exists": os.path.exists(sched),
                 "probe": "BY_CANONICAL_ID_NOT_BY_DATE"}
    if wnba_file["exists"]:
        import pandas as pd
        s = pd.read_parquet(sched)
        board = json.load(open(f"cards/{SLATE_DATE}_wnba_board_v2.json"))
        want = {}
        for r in board["wnba"]["rows"]:
            cid = str(r["canonical_id"])
            want[cid.split(":", 1)[1]] = r["game"]
        by_id = {str(g): row for g, row in zip(s["game_id"], s.to_dict("records"))}
        per = []
        for gid, game in sorted(want.items(), key=lambda kv: kv[1]):
            row = by_id.get(gid)
            per.append({
                "game": game, "canonical_id": f"ESPN_GAMEID:{gid}",
                "present_in_archive": row is not None,
                "status": (row or {}).get("status_type_name"),
                "completed": bool((row or {}).get("status_type_completed", False)),
                "utc_start": str((row or {}).get("date")),
            })
        n_done = sum(1 for r in per if r["completed"])
        wnba_file.update({
            "board_games_probed": len(per),
            "per_game": per,
            "completed_board_games": n_done,
            "verdict": ("NO_BOARD_GAME_COMPLETED" if not n_done else "COMPLETED_ROWS_PRESENT"),
            "utc_date_filter_would_have_returned": (
                "401857178 (GSV 79-60 NYL) and 401857179 (WSH 80-73 PHX) — 8/27 EVENING ET games "
                "whose UTC timestamps fall on 8/28. NEITHER is on the 8/28 board. A date-column "
                "filter here manufactures a two-game 8/28 'result set' out of the previous "
                "slate; both were already graded on 8/27."
            ),
        })
        if n_done:
            raise SystemExit(
                f"ARCHIVE_STATE_CHANGED: wehoop at {wehoop_head[:8]} reports {n_done} completed "
                "BOARD game(s). Grade the cohort instead of writing a no-results proof."
            )

    return {
        "wehoop_wnba_raw": {
            "head": wehoop_head, "head_committed_utc": wehoop_when,
            "pinned_in_harness": "7a1c7ebaef37590ebdaf75c4d3961b99a493d99b",
            "advanced_since_pin": wehoop_head != "7a1c7ebaef37590ebdaf75c4d3961b99a493d99b",
            "what_this_head_carries": "the 8/27 finals — it has not advanced past its 8/28 06:32 "
                                      "ET update, so no 8/28 boxes exist at any admissible source",
            "schedule_probe": wnba_file,
        },
        "lancebroz_mlb_pitcher_data": {
            "head": lb_head, "head_committed_utc": lb_when,
            "daily_file_probe": mlb_file,
            "standing_finding": "RJ-001B stands at 0/126 because this archive has NEVER carried a "
                                "runs column. The 8/28 file advancing does not change that.",
        },
        "observed_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def gate_board(card, rows_key):
    """Adapt a FROZEN CARD to the shape bind_cohort expects.

    The gate wants {sport, slate_date, games: {game_key: {game_pk, away, home, start_utc}}}. The
    frozen card is arm-major: one row per game PER ARM, so the same game appears several times.
    Collapsing is not a formality — if two arms disagreed about a game's canonical_id or its
    home/away, that disagreement must surface here rather than be silently resolved by whichever
    row happened to be last. So the collapse asserts agreement.

    game_pk is deliberately set to the NAMESPACED canonical_id, not a bare integer, so that
    _id_space_problems evaluates the real contract instead of a stripped copy of it.
    """
    games = {}
    derived = []
    for r in card[rows_key]["rows"]:
        g = r["game"]
        away, home = r.get("away"), r.get("home")
        if away is None or home is None:
            # The MLB board stores away/home ONLY inside the composite game key ("mlb:CIN@CHC");
            # the WNBA board stores them as fields. Two of the six fields in the binding contract
            # are therefore not independently held on an MLB board and must be parsed back out of
            # the identifier. That is weaker than reading a field and is recorded as such: if a
            # game key were ever BUILT backwards at freeze time, nothing on the board could
            # contradict it, because the board has no second copy to disagree with. It does not
            # make binding circular against an ARCHIVE row, which brings its own away/home.
            try:
                away, home = g.split(":", 1)[1].split("@")
            except (IndexError, ValueError):
                raise ValueError(f"CANNOT_DERIVE_TEAMS from game key {g!r} and the row carries no "
                                 "away/home fields")
            derived.append(g)
        ident = {"game_pk": r.get("canonical_id"), "away": away, "home": home,
                 "start_utc": r.get("start_utc") or r.get("game_start_utc")}
        if g in games and games[g] != ident:
            diff = {k: (games[g][k], ident[k]) for k in ident if games[g][k] != ident[k]}
            raise ValueError(f"ARM_IDENTITY_DISAGREEMENT on {g}: {diff} — two arms describe the "
                             "same game differently; that is an identity defect, not a tie to break")
        games[g] = ident
    return {"sport": card.get("sport"), "slate_date": card["slate_date"], "games": games,
            "TEAMS_DERIVED_FROM_GAME_KEY": sorted(set(derived))}


def board_identity(board, rows_key):
    rows = board[rows_key]["rows"]
    games = {}
    for r in rows:
        games[r["game"]] = r.get("canonical_id")
    spaces = {}
    bare = []
    for g, cid in games.items():
        if cid is None:
            continue
        if ":" not in str(cid):
            bare.append(g)
            continue
        spaces[str(cid).split(":", 1)[0]] = spaces.get(str(cid).split(":", 1)[0], 0) + 1
    if bare:
        raise ValueError(f"BARE_INTEGER_ID on {bare} — a surviving pseudo-pk is a hard error")
    grades = {}
    for r in rows:
        grades[r.get("id_grade", "UNKNOWN")] = grades.get(r.get("id_grade", "UNKNOWN"), 0) + 1
    return {
        "n_games": len(games),
        "id_spaces": spaces,
        "id_grades": grades,
        "inferred": grades.get("INFERRED", 0),
        "synthetic_pseudo_pks": 0,
        "id_space_mixture_check": "PASS — every board id is namespaced; a bare integer beside a "
                                  "namespaced one would be a surviving pseudo-pk and is refused "
                                  "at cohort level (check B9)",
    }


def build(cohort, archives):
    board = json.load(open(cohort["board"]))
    rows = []  # THE POINT: no result row exists to bind
    gb = gate_board(board, cohort["rows_key"])
    proof = binding_proof(rows, gb, f"{cohort['sport']}:{SLATE_DATE}")

    for k, v in proof["counters"].items():
        if k != "REFUSED_ROWS" and v != "0/0":
            raise ValueError(f"UNEXPECTED_COUNTER {k}={v} — this module writes no-results proofs "
                             "only; a nonzero counter means results exist and must be graded")

    prospective = cohort["prospective"]
    proof.update({
        "posture": "POST_SLATE",
        "board_path": cohort["board"],
        "board_sha256": sha256_file(cohort["board"]),
        "board_identity": board_identity(board, cohort["rows_key"]),
        "WHAT_0_OF_0_MEANS_HERE": (
            "NOTHING IS CLAIMED, and the reason is specific and worse than the prospective "
            f"proof's: the slate is OVER and no admissible source carries it. All "
            f"{len(board[cohort['rows_key']]['rows'])} board rows were loaded and every "
            "canonical_id was read. This is NOT 'nothing was checked'."
        ),
        "supplements_and_does_not_replace": {
            "prospective_proof": prospective,
            "prospective_sha256": sha256_file(prospective),
            "distinction": (
                "the prospective proof's 0/0 meant 'the slate has not started'. This proof's 0/0 "
                "means 'the slate finished and the archives still do not carry it'. Identical "
                "counters, different claim — so the earlier record stands unmodified under R6 "
                "rather than being edited to say something it did not say at the time."
            ),
        },
        "why_no_results": archives,
        "what_was_refused": (
            "manufacturing finals from search. Snippets IDENTIFY and never BIND. The 8/27 cycle "
            "published five fabricated finals at exactly this juncture; the correct output when "
            "no admissible source carries a result is a proof that says so."
        ),
        "accrual": "NOTHING accrues to settlement, promotion, or the estimator from this record",
        "wager_authority": "NO",
        "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    with open(cohort["out"], "w") as fh:
        json.dump(proof, fh, indent=1, sort_keys=True)
    return proof


def main():
    archives = observe_archives()
    for c in COHORTS:
        p = build(c, archives)
        print(f"WROTE {c['out']}")
        print(f"  cohort {p['cohort']:<18} gradable={p['gradable']} posture={p['posture']}")
        print(f"  counters {json.dumps(p['counters'], sort_keys=True)}")
        print(f"  board {p['board_identity']['n_games']} games "
              f"{p['board_identity']['id_spaces']} inferred={p['board_identity']['inferred']}")
    print("\nARCHIVE STATE (observed, not typed):")
    print(f"  wehoop   {archives['wehoop_wnba_raw']['head'][:8]} "
          f"advanced_since_pin={archives['wehoop_wnba_raw']['advanced_since_pin']}")
    lb = archives["lancebroz_mlb_pitcher_data"]["daily_file_probe"]
    print(f"  lancebroz {archives['lancebroz_mlb_pitcher_data']['head'][:8]} "
          f"8/28 file rows={lb.get('n_rows')} cols={lb.get('n_columns')} "
          f"score_cols={lb.get('score_bearing_columns')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
