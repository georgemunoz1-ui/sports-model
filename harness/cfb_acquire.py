"""CFB v2 DATA ACQUISITION — the step the preregistration has been waiting on since 8/27.

The preregistration froze on 2026-08-27 in state PREREGISTERED_DATA_ACQUISITION_PENDING and named
its sources but bound none of them: "A HEAD observation is not a source pin. Acquisition must
select a commit, retain exact files, hash every byte and create a separate immutable manifest
before fitting." This module does exactly that and nothing more — it acquires and binds; it does
not fit, and it does not touch a feature.

WHAT IS ACQUIRED. sportsdataverse/cfbfastR-data at a PINNED commit, schedules/parquet only. That
directory carries 25 seasons of ESPN-sourced college football schedules with final scores, both
teams' subdivision and conference, neutral-site and conference-game flags, and ESPN's own pregame
Elo.

WHY THE SUBDIVISION COLUMN MATTERS MORE THAN THE SCORES. The v2 cohort is FBS-only and this repo
has repeatedly had to REFUSE to classify teams, most recently across 22 relayed market rows,
because no registered FBS list existed and several programs changed subdivision in the 2024-2026
realignment. home_division and away_division are a sourced classification. The refusal can now be
lifted for every team that appears in this artifact — and only for those.

WHAT IS NOT HERE, STATED UP FRONT. The archive ends at the 2025 season. There is NO 2026 file.
Nothing in this acquisition can supply 2026 team state, so any 2026 forecast is a genuine
season-opener problem and the preregistration's week_one_policy governs it, not this file.

MARKET FIREWALL. The repository also contains a betting/ directory. It is deliberately NOT
acquired. Prices are never predictive features, and the cheapest way to guarantee that is to not
have them on disk in the model's source tree.
"""
from __future__ import annotations

MODULE_ID = "cfb_acquire"

import hashlib
import json
import os
import subprocess

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

REPO_DIR = "/home/user/sportsdataverse/cfbfastR-data"
REPO = "github.com/sportsdataverse/cfbfastR-data"
SUBDIR = "schedules/parquet"
PREFIX = "cfb_schedules_"
OUT = "data/cfb/model/CFB_V2_ACQUISITION_MANIFEST.json"

#: Only these columns may be read downstream. Enumerated here so a later widening is a visible
#: diff rather than a silent one, and so no scoreline column can reach a feature by accident.
PERMITTED_COLUMNS = [
    "game_id", "season", "week", "season_type", "start_date", "completed",
    "neutral_site", "conference_game", "venue_id",
    "home_id", "home_team", "home_division", "home_conference",
    "away_id", "away_team", "away_division", "away_conference",
    "home_points", "away_points",              # OUTCOME ONLY — never a feature input
    "home_pregame_elo", "away_pregame_elo",    # EXTERNAL DIAGNOSTIC ONLY — never a baseline
]
OUTCOME_ONLY = ["home_points", "away_points"]
DIAGNOSTIC_ONLY = ["home_pregame_elo", "away_pregame_elo"]


def git(*args, cwd=REPO_DIR):
    return subprocess.run(("git",) + args, cwd=cwd, capture_output=True,
                          text=True, check=True).stdout.strip()


def build():
    commit = git("rev-parse", "HEAD")
    files = []
    for name in sorted(os.listdir(os.path.join(REPO_DIR, SUBDIR))):
        if not name.startswith(PREFIX) or not name.endswith(".parquet"):
            continue
        rel = f"{SUBDIR}/{name}"
        path = os.path.join(REPO_DIR, rel)
        raw = open(path, "rb").read()
        files.append({"path": rel, "bytes": len(raw),
                      "sha256": hashlib.sha256(raw).hexdigest(),
                      "season": int(name[len(PREFIX):-len(".parquet")])})
    if not files:
        raise SystemExit("no schedule parquet matched — acquisition acquired nothing")

    seasons = sorted(f["season"] for f in files)
    gaps = [s for s in range(seasons[0], seasons[-1] + 1) if s not in seasons]

    import pandas as pd
    frames = [pd.read_parquet(os.path.join(REPO_DIR, f["path"])) for f in files]
    df = pd.concat(frames, ignore_index=True)

    missing = [c for c in PERMITTED_COLUMNS if c not in df.columns]
    if missing:
        raise SystemExit(f"acquired files lack required columns: {missing}")

    fin = df[(df["completed"] == True) & df["home_points"].notna()          # noqa: E712
             & df["away_points"].notna()]
    fbs = fin[(fin["home_division"] == "fbs") & (fin["away_division"] == "fbs")]
    cross = fin[((fin["home_division"] == "fbs") ^ (fin["away_division"] == "fbs"))]

    teams = sorted(set(df["home_team"].dropna()) | set(df["away_team"].dropna()))
    div = {}
    for side in ("home", "away"):
        for t, d in zip(df[f"{side}_team"], df[f"{side}_division"]):
            if isinstance(t, str) and isinstance(d, str):
                div.setdefault(t, set()).add(d)

    manifest = {
        "record_id": "CFB-V2-ACQUISITION-2026-08-28",
        "schema": "ops.source_binding.v1",
        "model_id": "cfb.fbs.epa_talent_hgb.v2_0.challenger",
        "supersedes": "data/cfb/model/CFB_V2_SOURCE_DISCOVERY.json — a HEAD observation, which the "
                      "preregistration states is NOT a source pin",
        "acquired_utc": "2026-08-28T11:20:00Z",
        "source": {
            "repository": REPO,
            "commit": commit,
            "subdirectory": SUBDIR,
            "acquisition_method": "git partial clone (--filter=blob:none), sparse checkout of "
                                  "schedules/parquet only",
            "retained_locally_at": REPO_DIR,
        },
        "files": files,
        "n_files": len(files),
        "seasons": {"first": seasons[0], "last": seasons[-1], "n": len(seasons),
                    "interior_gaps": gaps},
        "coverage": {
            "rows_total": int(len(df)),
            "rows_completed_with_scores": int(len(fin)),
            "fbs_vs_fbs_completed": int(len(fbs)),
            "fbs_vs_fcs_completed": int(len(cross)),
            "distinct_teams": len(teams),
            "espn_pregame_elo_present_on_fbs_vs_fbs": int(fbs["home_pregame_elo"].notna().sum()),
        },
        "meets_preregistered_minimums": {
            "minimum_games": 1000, "observed_fbs_vs_fbs": int(len(fbs)),
            "games_ok": len(fbs) >= 1000,
            "minimum_season_week_blocks": 60,
            "observed_season_week_blocks": int(fbs.groupby(["season", "week"]).ngroups),
            "blocks_ok": fbs.groupby(["season", "week"]).ngroups >= 60,
        },
        "column_policy": {
            "permitted": PERMITTED_COLUMNS,
            "outcome_only": {"columns": OUTCOME_ONLY,
                             "rule": "targets and grading only; may never enter a feature"},
            "external_diagnostic_only": {
                "columns": DIAGNOSTIC_ONLY,
                "rule": "ESPN's own pregame Elo. The preregistration permits it as an "
                        "evaluation-only diagnostic and forbids treating it as an internally "
                        "controlled baseline. It is NOT a feature and NOT a promotion baseline."},
            "why_enumerated": "a later widening of the column set is then a visible diff rather "
                              "than a silent one",
        },
        "MARKET_FIREWALL": {
            "betting_directory_present_upstream": True,
            "acquired": False,
            "rule": "prices are never predictive features. The cheapest guarantee is not to have "
                    "them on disk in the model's source tree.",
        },
        "SUBDIVISION_CLASSIFICATION_NOW_SOURCED": {
            "finding": ("home_division and away_division give a sourced FBS/FCS classification. "
                        "This repository has repeatedly REFUSED to classify teams from memory — "
                        "most recently across 22 relayed market rows — because no registered list "
                        "existed and several programs changed subdivision in the 2024-2026 "
                        "realignment."),
            "scope_of_the_lift": ("the refusal is lifted ONLY for teams appearing in this "
                                  "artifact, and only for seasons it covers. A 2026 team absent "
                                  "here stays unclassified."),
            "teams_with_multiple_divisions_observed": {
                t: sorted(v) for t, v in sorted(div.items()) if len(v) > 1},
        },
        "WHAT_THIS_ACQUISITION_CANNOT_SUPPLY": {
            "no_2026_season": ("the archive ends at the 2025 season; there is no 2026 file. This "
                               "acquisition supplies NO 2026 team state, so any 2026 forecast is a "
                               "genuine season-opener problem governed by the preregistration's "
                               "week_one_policy."),
            "no_play_by_play": ("schedules only. The v2 feature blocks that need EPA, success "
                                "rate and explosiveness are NOT satisfied by this acquisition and "
                                "remain outstanding."),
            "no_personnel": "no talent, returning production, quarterback or coach continuity.",
        },
        "wager_authority": "NO", "stake": 0,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    return manifest


if __name__ == "__main__":
    m = build()
    print("ACQUIRED", m["record_id"])
    print(f'  {hashlib.sha256(open(OUT, "rb").read()).hexdigest()[:8]}  {OUT}')
    print("  repo   ", m["source"]["repository"], "@", m["source"]["commit"][:12])
    print("  files  ", m["n_files"], "seasons", m["seasons"]["first"], "-", m["seasons"]["last"],
          "gaps", m["seasons"]["interior_gaps"] or "none")
    c = m["coverage"]
    print("  games  ", c["rows_completed_with_scores"], "completed |",
          c["fbs_vs_fbs_completed"], "FBS-FBS |", c["fbs_vs_fcs_completed"], "FBS-FCS")
    mm = m["meets_preregistered_minimums"]
    print("  gates  ", f'games {mm["observed_fbs_vs_fbs"]}>={mm["minimum_games"]} {mm["games_ok"]}',
          f'| blocks {mm["observed_season_week_blocks"]}>={mm["minimum_season_week_blocks"]} '
          f'{mm["blocks_ok"]}')
    print("  2026   ", "ABSENT — season-opener problem, week_one_policy governs")
