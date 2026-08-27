#!/usr/bin/env python3
"""MLB PROVENANCE BINDING from the statsapi pitch archive on GitHub — RJ-001's actual work.

The `lancebroz/mlb-pitcher-data` repository stores DAILY statsapi-derived pitch-level parquet
files in-tree (game_pk, teams, full play record per game), updated by GitHub Actions — the HEAD
commit at binding time landed ~40 minutes before retrieval. A row in results.csv binds when its
game_pk appears in its date's parquet WITH matching home/away teams: the artifact then supplies
the evidence path (repo@commit:path) and content hash the row has been missing since ingestion.

WHAT THIS DOES AND DOES NOT DO. It fills ONLY the empty evidence_path/evidence_sha256 columns —
scores, tiers, statuses and every other field stay byte-identical (a pitch archive proves a
game's identity and play record; it does not independently verify a final score, so no tier is
upgraded here). Rows that fail the identity check are left untouched and reported. The prior
file is preserved via git history and a sidecar backup.
"""
from __future__ import annotations

MODULE_ID = "mlb_provenance_bind"

import csv
import hashlib
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))

RAW = "/home/user/lancebroz/mlb-pitcher-data"
RESULTS = "data/backfill/mlb/2026/results.csv"
BACKUP = "data/backfill/mlb/2026/results_pre_rj001_bind.csv"


# variant team codes seen in older canonical rows; folded AFTER the full-name map
VARIANT = {"OAK": "ATH", "ARI": "AZ"}


def bind():
    import pyarrow.parquet as pq
    from adaptive_challenger import _abbr as _abbr0

    def _abbr(t):
        a = _abbr0(t)
        return VARIANT.get(a, a)
    head = subprocess.run(["git", "-C", RAW, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    rows = list(csv.DictReader(open(RESULTS)))
    fields = rows[0].keys()
    cache = {}

    def day(date):
        """Build (or load) the LOCAL evidence extract for a date: a compact JSON carrying every
        game's identity plus the upstream artifact's provenance, hashed and committed. The
        provenance gate stats local paths, so the row's evidence is the extract; the extract
        names the upstream parquet by repo, commit, path and sha256."""
        if date not in cache:
            p = f"{RAW}/data/raw/2026/daily/{date}.parquet"
            if not os.path.exists(p):
                cache[date] = (None, None, None)
                return cache[date]
            ext_dir = "data/backfill/mlb/2026/evidence"
            ext_path = f"{ext_dir}/daily_extract_{date}.json"
            if not os.path.exists(ext_path):
                import json as _json
                t = pq.read_table(p, columns=["game_pk", "home_team", "away_team",
                                              "pitcher_id"]).to_pydict()
                games = {}
                for i in range(len(t["game_pk"])):
                    g = games.setdefault(int(t["game_pk"][i]),
                                         {"home": str(t["home_team"][i]),
                                          "away": str(t["away_team"][i]),
                                          "n_pitches": 0, "pitcher_ids": set()})
                    g["n_pitches"] += 1
                    g["pitcher_ids"].add(int(t["pitcher_id"][i]))
                for g in games.values():
                    g["pitcher_ids"] = sorted(g["pitcher_ids"])
                os.makedirs(ext_dir, exist_ok=True)
                with open(ext_path, "w") as fh:
                    _json.dump({"schema": "ops.evidence_extract.v1", "date": date,
                                "upstream": {"repo": "github.com/lancebroz/mlb-pitcher-data",
                                             "commit": head,
                                             "path": f"data/raw/2026/daily/{date}.parquet",
                                             "sha256": hashlib.sha256(
                                                 open(p, "rb").read()).hexdigest()},
                                "games": {str(k): v for k, v in sorted(games.items())}},
                               fh, indent=1, sort_keys=True)
            import json as _json
            ext = _json.load(open(ext_path))
            games = {int(k): (v["home"], v["away"]) for k, v in ext["games"].items()}
            cache[date] = (games,
                           hashlib.sha256(open(ext_path, "rb").read()).hexdigest(),
                           ext_path)
        return cache[date]

    bound = already = nofile = nopk = mismatch = 0
    unmatched = []
    for r in rows:
        if r["evidence_sha256"]:
            already += 1
            continue
        games, sha, uri = day(r["date"])
        if games is None:
            nofile += 1
            unmatched.append((r["game_id"], f"NO_ARTIFACT_FOR_{r['date']}"))
            continue
        want = (_abbr(r["home"]), _abbr(r["away"]))
        try:
            pk = int(r["game_id"].rsplit(":", 1)[1])
        except (ValueError, IndexError):
            pk = None
        if pk is not None and pk in games:
            if games[pk] != want:
                mismatch += 1
                unmatched.append((r["game_id"], f"TEAM_MISMATCH {games[pk]}"))
                continue
        else:
            # tier-3 rows carry synthetic box ids with no pk; a UNIQUE same-day teams match in
            # the artifact identifies the game (doubleheaders make two — then refuse)
            cands = [k for k, ha in games.items() if ha == want]
            if len(cands) != 1:
                nopk += 1
                unmatched.append((r["game_id"],
                                  "PK_NOT_IN_ARTIFACT" if not cands else "DOUBLEHEADER_AMBIGUOUS"))
                continue
        r["evidence_path"] = uri
        r["evidence_sha256"] = sha
        bound += 1
    return rows, fields, {"commit": head, "bound": bound, "already": already,
                          "no_artifact": nofile, "pk_missing": nopk,
                          "team_mismatch": mismatch, "unmatched": unmatched}


def run():
    rows, fields, rep = bind()
    if not os.path.exists(BACKUP):
        shutil.copy(RESULTS, BACKUP)
    with open(RESULTS, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return rep


if __name__ == "__main__":
    rep = run()
    print(f"bound {rep['bound']} | already-evidenced {rep['already']} | "
          f"no-artifact {rep['no_artifact']} | pk-missing {rep['pk_missing']} | "
          f"team-mismatch {rep['team_mismatch']} | commit {rep['commit'][:12]}")
    for g, why in rep["unmatched"][:12]:
        print("  UNMATCHED", g, why)
