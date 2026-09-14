#!/usr/bin/env python3
"""Leakage-safe NFL regular-season feature construction.

This module has no downloader and no market-data input.  It accepts immutable local
schedule/results and play-by-play files that have already been bound to a source
manifest.  Team state is frozen at the start of each NFL week; every update from a
week is applied only after all games in that week have been featurized.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


MODEL_ID = "nfl.rs.epa_logit_ridge.v0_2.shadow"
MIN_SEASON = 2015
EWMA_ALPHA = 0.25
OFFSEASON_RETENTION = 0.55
WP_LOW = 0.15
WP_HIGH = 0.85

GAMES_REQUIRED = {
    "game_id", "season", "week", "game_type", "gameday", "home_team",
    "away_team", "home_score", "away_score", "location", "roof", "temp",
    "wind", "home_rest", "away_rest",
}
PBP_REQUIRED = {
    "game_id", "play_id", "season", "week", "season_type", "posteam",
    "defteam", "down", "play_type", "epa", "success", "yards_gained",
    "pass_attempt", "rush_attempt", "qb_kneel", "qb_spike", "no_play",
    "wp", "game_seconds_remaining", "sack", "interception",
    "fumble_lost",
}

MARKET_TOKENS = (
    "spread", "moneyline", "money_line", "odds", "price", "implied",
    "closing_line", "open_line", "total_line", "market_prob",
)

MODEL_FEATURES = [
    "epa_matchup_edge",
    "success_matchup_edge",
    "explosive_matchup_edge",
    "protection_matchup_edge",
    "neutral_pass_rate_diff",
    "pace_seconds_sum",
    "point_differential_diff",
    "rest_days_diff",
    "neutral_site",
    "roof_indoor",
    "temperature_f",
    "wind_mph",
    "state_experience_min_log",
    "state_experience_diff_log",
    "rest_missing",
    "location_missing",
    "roof_missing",
    "weather_missing",
]

IDENTITY_COLUMNS = [
    "game_id", "season", "week", "gameday", "away_team", "home_team",
]
TARGET_COLUMNS = ["home_win", "home_margin", "total_points"]

TEAM_ALIASES = {
    "JAC": "JAX",
    "LAR": "LA",
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LA",
    "WSH": "WAS",
}


class DataContractError(ValueError):
    """Input bytes or columns do not satisfy the frozen contract."""


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(
    path: str | Path,
    *,
    usecols: set[str] | None = None,
) -> pd.DataFrame:
    path = Path(path)
    if not path.is_file():
        raise DataContractError(f"input file does not exist: {path}")
    if not (path.name.endswith(".csv") or path.name.endswith(".csv.gz")):
        raise DataContractError(f"only CSV/CSV.GZ inputs are allowed: {path.name}")
    # nflverse PBP files contain hundreds of columns.  The frozen model uses only
    # the contract-bound subset, so selecting it at parse time keeps a multi-season
    # build within ordinary workstation memory without changing any model input.
    if usecols is not None:
        header = pd.read_csv(path, nrows=0).columns
        missing = sorted(usecols - set(header))
        if missing:
            raise DataContractError(f"{path.name} missing required columns: {missing}")
    return pd.read_csv(path, usecols=sorted(usecols) if usecols else None, low_memory=False)


def validate_source_manifest(
    manifest_path: str | Path,
    games_path: str | Path,
    pbp_paths: Sequence[str | Path],
) -> dict:
    """Verify provenance and SHA-256 before any source byte is parsed."""
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise DataContractError("source manifest must contain a non-empty files list")

    required = {"role", "filename", "sha256", "source_method", "retrieved_utc", "evidence"}
    allowed_methods = {"WebFetch", "USER_ATTACHMENT"}
    keyed: dict[tuple[str, str], dict] = {}
    for i, record in enumerate(records):
        if not isinstance(record, dict) or not required.issubset(record):
            missing = sorted(required - set(record if isinstance(record, dict) else {}))
            raise DataContractError(f"source manifest record {i} missing fields: {missing}")
        if record["source_method"] not in allowed_methods:
            raise DataContractError(
                f"source manifest record {i} has disallowed acquisition method "
                f"{record['source_method']!r}"
            )
        if not str(record["retrieved_utc"]).strip() or not str(record["evidence"]).strip():
            raise DataContractError(f"source manifest record {i} has blank time/evidence")
        key = (str(record["role"]), str(record["filename"]))
        if key in keyed:
            raise DataContractError(f"duplicate source manifest identity: {key}")
        keyed[key] = record

    supplied = [("games", Path(games_path))] + [("pbp", Path(p)) for p in pbp_paths]
    if not pbp_paths:
        raise DataContractError("at least one PBP file is required")
    used: set[tuple[str, str]] = set()
    for role, path in supplied:
        key = (role, path.name)
        if key not in keyed:
            raise DataContractError(f"source manifest has no {role} record for {path.name}")
        actual = sha256_file(path)
        expected = str(keyed[key]["sha256"]).lower()
        if actual != expected:
            raise DataContractError(
                f"source hash mismatch for {path.name}: {actual} != {expected}"
            )
        used.add(key)
    extras = set(keyed) - used
    if extras:
        raise DataContractError(f"source manifest contains unused file records: {sorted(extras)}")
    return manifest


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise DataContractError(f"{label} missing required columns: {missing}")


def load_local_inputs(
    games_path: str | Path,
    pbp_paths: Sequence[str | Path],
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Load and validate local input tables; no network access is implemented."""
    games = _read_csv(games_path, usecols=GAMES_REQUIRED)
    _require_columns(games, GAMES_REQUIRED, "games")
    pbp_parts = []
    schema_adapters: list[dict[str, object]] = []
    for path in pbp_paths:
        path = Path(path)
        if not path.is_file():
            raise DataContractError(f"input file does not exist: {path}")
        if not (path.name.endswith(".csv") or path.name.endswith(".csv.gz")):
            raise DataContractError(f"only CSV/CSV.GZ inputs are allowed: {path.name}")
        header = set(pd.read_csv(path, nrows=0).columns)
        source_columns = PBP_REQUIRED if "no_play" in header else PBP_REQUIRED - {"no_play"}
        part = _read_csv(path, usecols=source_columns)
        if "no_play" not in part.columns:
            # Current nflverse PBP encodes nullified plays as play_type=no_play
            # and no longer emits the legacy indicator column.  Reconstructing
            # that indicator is a lossless schema adapter, not a model feature.
            part["no_play"] = (
                part["play_type"].astype("string").str.lower() == "no_play"
            ).fillna(False).astype("int8")
            schema_adapters.append({
                "filename": path.name,
                "adapter": "no_play := 1[lower(play_type) == 'no_play']",
                "derived_true_rows": int(part["no_play"].sum()),
            })
        _require_columns(part, PBP_REQUIRED, f"PBP {Path(path).name}")
        pbp_parts.append(part)
    if not pbp_parts:
        raise DataContractError("at least one PBP file is required")
    pbp = pd.concat(pbp_parts, ignore_index=True, sort=False)

    for frame, columns in (
        (games, ["season", "week", "home_score", "away_score", "temp", "wind", "home_rest", "away_rest"]),
        (pbp, ["play_id", "season", "week", "down", "epa", "success", "yards_gained",
               "pass_attempt", "rush_attempt", "qb_kneel", "qb_spike", "no_play",
               "wp", "game_seconds_remaining", "sack", "interception", "fumble_lost"]),
    ):
        for column in columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    games = games[(games["game_type"].astype(str).str.upper() == "REG") &
                  (games["season"] >= MIN_SEASON)].copy()
    pbp = pbp[(pbp["season_type"].astype(str).str.upper() == "REG") &
              (pbp["season"] >= MIN_SEASON)].copy()
    if games.empty:
        raise DataContractError("no regular-season games remain after filtering")
    if pbp.empty:
        raise DataContractError("no regular-season PBP remains after filtering")

    if games["game_id"].isna().any() or games["game_id"].duplicated().any():
        raise DataContractError("games.game_id must be non-null and unique")
    if pbp[["game_id", "play_id"]].isna().any(axis=None):
        raise DataContractError("PBP game_id/play_id cannot be null")
    if pbp.duplicated(["game_id", "play_id"]).any():
        raise DataContractError("PBP contains duplicate (game_id, play_id)")

    known_games = set(games["game_id"].astype(str))
    pbp = pbp[pbp["game_id"].astype(str).isin(known_games)].copy()
    if pbp.empty:
        raise DataContractError("no PBP rows match the supplied regular-season games")

    completed = games["home_score"].notna() & games["away_score"].notna()
    pbp_game_ids = set(pbp["game_id"].astype(str))
    missing_completed = sorted(
        set(games.loc[completed, "game_id"].astype(str)) - pbp_game_ids
    )
    if missing_completed:
        preview = missing_completed[:10]
        raise DataContractError(
            f"{len(missing_completed)} completed regular-season games have no PBP; "
            f"first identities: {preview}"
        )

    mismatch = pbp.merge(
        games[["game_id", "season", "week"]], on="game_id", how="left", suffixes=("_pbp", "_game")
    )
    mismatch = mismatch[
        (mismatch["season_pbp"] != mismatch["season_game"]) |
        (mismatch["week_pbp"] != mismatch["week_game"])
    ]
    if not mismatch.empty:
        raise DataContractError("PBP season/week disagrees with games table")

    alias_counts: dict[str, int] = {}
    for frame, columns in (
        (games, ["home_team", "away_team"]),
        (pbp, ["posteam", "defteam"]),
    ):
        for column in columns:
            raw = frame[column].astype("string").str.upper()
            for old, new in TEAM_ALIASES.items():
                count = int((raw == old).sum())
                if count:
                    alias_counts[f"{old}->{new}"] = alias_counts.get(f"{old}->{new}", 0) + count
            frame[column] = raw.replace(TEAM_ALIASES)

    audit = {
        "games_loaded": int(len(games)),
        "pbp_rows_loaded": int(len(pbp)),
        "games_seasons": [int(x) for x in sorted(games["season"].dropna().unique())],
        "pbp_seasons": [int(x) for x in sorted(pbp["season"].dropna().unique())],
        "completed_games_with_pbp": int(completed.sum()),
        "completed_games_without_pbp": 0,
        "team_alias_replacements": alias_counts,
        "source_schema_adapters": schema_adapters,
    }
    return games, pbp, audit


@dataclass
class TeamState:
    off_epa: float = 0.0
    def_epa: float = 0.0
    off_success: float = 0.0
    def_success: float = 0.0
    off_explosive: float = 0.0
    def_explosive: float = 0.0
    off_protection: float = 0.0
    def_havoc: float = 0.0
    neutral_pass_rate: float = 0.0
    pace_seconds: float = 0.0
    point_differential: float = 0.0
    effective_plays: float = 0.0
    weeks_observed: int = 0
    _extra: dict = field(default_factory=dict, repr=False)

    def shrink_offseason(self) -> None:
        for name in (
            "off_epa", "def_epa", "off_success", "def_success", "off_explosive",
            "def_explosive", "off_protection", "def_havoc", "neutral_pass_rate",
            "pace_seconds", "point_differential",
        ):
            setattr(self, name, getattr(self, name) * OFFSEASON_RETENTION)
        self.effective_plays *= OFFSEASON_RETENTION

    def update(self, observation: Mapping[str, float], plays: float) -> None:
        for name, value in observation.items():
            if name in {"effective_plays", "weeks_observed"} or not np.isfinite(value):
                continue
            old = getattr(self, name)
            setattr(self, name, (1.0 - EWMA_ALPHA) * old + EWMA_ALPHA * float(value))
        self.effective_plays += float(max(0.0, plays))
        self.weeks_observed += 1


def _qualifying_plays(pbp: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    base = pbp.copy()
    mask = (
        base["down"].isin([1, 2]) &
        base["play_type"].astype(str).str.lower().isin(["run", "pass"]) &
        (base["qb_kneel"].fillna(0) == 0) &
        (base["qb_spike"].fillna(0) == 0) &
        (base["no_play"].fillna(0) == 0) &
        base["wp"].between(WP_LOW, WP_HIGH, inclusive="both") &
        base["posteam"].notna() & base["defteam"].notna()
    )
    required_metrics = ["epa", "success", "yards_gained", "wp"]
    structural = base[mask].copy()
    null_metric_rows = int(structural[required_metrics].isna().any(axis=1).sum())
    plays = structural.dropna(subset=required_metrics).copy()
    plays["is_pass"] = (plays["play_type"].astype(str).str.lower() == "pass").astype(float)
    plays["explosive"] = np.where(
        plays["is_pass"] == 1.0,
        plays["yards_gained"] >= 20.0,
        plays["yards_gained"] >= 10.0,
    ).astype(float)
    plays["havoc"] = (
        (plays["sack"].fillna(0) > 0) |
        (plays["interception"].fillna(0) > 0) |
        (plays["fumble_lost"].fillna(0) > 0)
    ).astype(float)

    plays.sort_values(["game_id", "play_id"], inplace=True)
    same_possession = (
        (plays["game_id"] == plays["game_id"].shift(1)) &
        (plays["posteam"] == plays["posteam"].shift(1))
    )
    elapsed = plays["game_seconds_remaining"].shift(1) - plays["game_seconds_remaining"]
    plays["snap_seconds"] = elapsed.where(same_possession & elapsed.between(0, 45), np.nan)
    audit = {
        "pbp_rows_considered": int(len(base)),
        "qualifying_plays": int(len(plays)),
        "qualifying_rows_excluded_for_null_metric": null_metric_rows,
    }
    if plays.empty:
        raise DataContractError("no plays satisfy the frozen early-down neutral-state filter")
    return plays, audit


def _safe_float(value) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return math.nan
    return out if math.isfinite(out) else math.nan


def _context_features(game: pd.Series) -> dict[str, float]:
    home_rest = _safe_float(game["home_rest"])
    away_rest = _safe_float(game["away_rest"])
    location = str(game["location"]).strip().lower() if pd.notna(game["location"]) else ""
    roof = str(game["roof"]).strip().lower() if pd.notna(game["roof"]) else ""
    indoor_values = {"dome", "closed", "indoor", "indoors"}
    outdoor_values = {"outdoors", "outdoor", "open"}
    if roof in indoor_values:
        roof_indoor = 1.0
    elif roof in outdoor_values:
        roof_indoor = 0.0
    else:
        roof_indoor = math.nan
    neutral_site = 1.0 if location in {"neutral", "neutral site"} else (0.0 if location else math.nan)
    temp = _safe_float(game["temp"])
    wind = _safe_float(game["wind"])
    return {
        "rest_days_diff": home_rest - away_rest if np.isfinite(home_rest) and np.isfinite(away_rest) else math.nan,
        "neutral_site": neutral_site,
        "roof_indoor": roof_indoor,
        "temperature_f": temp,
        "wind_mph": wind,
        "rest_missing": float(not (np.isfinite(home_rest) and np.isfinite(away_rest))),
        "location_missing": float(not location),
        "roof_missing": float(not roof),
        "weather_missing": float(not (np.isfinite(temp) and np.isfinite(wind))),
    }


def _feature_row(game: pd.Series, home: TeamState, away: TeamState) -> dict:
    home_epa = home.off_epa - away.def_epa
    away_epa = away.off_epa - home.def_epa
    home_success = home.off_success - away.def_success
    away_success = away.off_success - home.def_success
    home_explosive = home.off_explosive - away.def_explosive
    away_explosive = away.off_explosive - home.def_explosive
    home_protection = home.off_protection - away.def_havoc
    away_protection = away.off_protection - home.def_havoc
    h_exp = math.log1p(max(0.0, home.effective_plays))
    a_exp = math.log1p(max(0.0, away.effective_plays))

    home_score = _safe_float(game["home_score"])
    away_score = _safe_float(game["away_score"])
    if np.isfinite(home_score) and np.isfinite(away_score):
        margin = home_score - away_score
        home_win = float(margin > 0) if margin != 0 else math.nan
        total = home_score + away_score
    else:
        margin = home_win = total = math.nan

    row = {
        "game_id": str(game["game_id"]),
        "season": int(game["season"]),
        "week": int(game["week"]),
        "gameday": str(game["gameday"]),
        "away_team": str(game["away_team"]),
        "home_team": str(game["home_team"]),
        "epa_matchup_edge": home_epa - away_epa,
        "success_matchup_edge": home_success - away_success,
        "explosive_matchup_edge": home_explosive - away_explosive,
        "protection_matchup_edge": home_protection - away_protection,
        "neutral_pass_rate_diff": home.neutral_pass_rate - away.neutral_pass_rate,
        "pace_seconds_sum": home.pace_seconds + away.pace_seconds,
        "point_differential_diff": home.point_differential - away.point_differential,
        "state_experience_min_log": min(h_exp, a_exp),
        "state_experience_diff_log": h_exp - a_exp,
        "home_win": home_win,
        "home_margin": margin,
        "total_points": total,
    }
    row.update(_context_features(game))
    return row


def _weekly_observations(
    games_week: pd.DataFrame,
    plays_week: pd.DataFrame,
    states: Mapping[str, TeamState],
) -> dict[str, tuple[dict[str, float], float]]:
    if plays_week.empty:
        play_obs: dict[str, list[tuple[dict[str, float], float]]] = {}
    else:
        league = {
            "epa": float(plays_week["epa"].mean()),
            "success": float(plays_week["success"].mean()),
            "explosive": float(plays_week["explosive"].mean()),
            "havoc": float(plays_week["havoc"].mean()),
            "pass_rate": float(plays_week["is_pass"].mean()),
            "pace": float(plays_week["snap_seconds"].mean()) if plays_week["snap_seconds"].notna().any() else math.nan,
        }
        play_obs = {}
        grouped = plays_week.groupby(["game_id", "posteam", "defteam"], sort=True)
        for (_, offense, defense), group in grouped:
            offense = str(offense)
            defense = str(defense)
            n = float(len(group))
            off_epa_dev = float(group["epa"].mean()) - league["epa"]
            off_success_dev = float(group["success"].mean()) - league["success"]
            off_explosive_dev = float(group["explosive"].mean()) - league["explosive"]
            havoc_dev = float(group["havoc"].mean()) - league["havoc"]
            pass_dev = float(group["is_pass"].mean()) - league["pass_rate"]
            pace_dev = (
                float(group["snap_seconds"].mean()) - league["pace"]
                if group["snap_seconds"].notna().any() and np.isfinite(league["pace"])
                else math.nan
            )
            off_prior = states.get(offense, TeamState())
            def_prior = states.get(defense, TeamState())
            off_record = {
                "off_epa": off_epa_dev + def_prior.def_epa,
                "off_success": off_success_dev + def_prior.def_success,
                "off_explosive": off_explosive_dev + def_prior.def_explosive,
                "off_protection": -havoc_dev + def_prior.def_havoc,
                "neutral_pass_rate": pass_dev,
                "pace_seconds": pace_dev,
            }
            def_record = {
                "def_epa": -off_epa_dev + off_prior.off_epa,
                "def_success": -off_success_dev + off_prior.off_success,
                "def_explosive": -off_explosive_dev + off_prior.off_explosive,
                "def_havoc": havoc_dev + off_prior.off_protection,
            }
            play_obs.setdefault(offense, []).append((off_record, n))
            play_obs.setdefault(defense, []).append((def_record, n))

    point_diffs: dict[str, list[float]] = {}
    for _, game in games_week.iterrows():
        hs = _safe_float(game["home_score"])
        aws = _safe_float(game["away_score"])
        if not (np.isfinite(hs) and np.isfinite(aws)):
            continue
        point_diffs.setdefault(str(game["home_team"]), []).append(hs - aws)
        point_diffs.setdefault(str(game["away_team"]), []).append(aws - hs)

    teams = set(play_obs) | set(point_diffs)
    out: dict[str, tuple[dict[str, float], float]] = {}
    for team in teams:
        records = play_obs.get(team, [])
        names = sorted({name for record, _ in records for name in record})
        combined: dict[str, float] = {}
        for name in names:
            vals = [(record[name], weight) for record, weight in records if name in record and np.isfinite(record[name])]
            if vals:
                combined[name] = float(np.average([v for v, _ in vals], weights=[w for _, w in vals]))
        if team in point_diffs:
            combined["point_differential"] = float(np.mean(point_diffs[team]))
        plays = sum(weight for _, weight in records) / 2.0
        out[team] = (combined, plays)
    return out


def assert_feature_firewall(frame: pd.DataFrame) -> None:
    expected = set(IDENTITY_COLUMNS + MODEL_FEATURES + TARGET_COLUMNS)
    unexpected = sorted(set(frame.columns) - expected)
    if unexpected:
        raise DataContractError(f"unexpected feature-table columns: {unexpected}")
    polluted = [c for c in frame.columns if any(token in c.lower() for token in MARKET_TOKENS)]
    if polluted:
        raise DataContractError(f"market-derived predictive columns are forbidden: {polluted}")
    missing = sorted(set(MODEL_FEATURES) - set(frame.columns))
    if missing:
        raise DataContractError(f"frozen model features missing: {missing}")


def build_weekly_features(games: pd.DataFrame, pbp: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Create one pregame row per game with no same-week state leakage."""
    plays, play_audit = _qualifying_plays(pbp)
    games = games.sort_values(["season", "week", "gameday", "game_id"]).copy()
    states: dict[str, TeamState] = {}
    rows: list[dict] = []
    previous_season: int | None = None
    weeks_processed = 0

    for (season, week), games_week in games.groupby(["season", "week"], sort=True):
        season = int(season)
        week = int(week)
        if previous_season is not None and season != previous_season:
            for _ in range(max(0, season - previous_season)):
                for state in states.values():
                    state.shrink_offseason()
        previous_season = season

        teams_this_week = set(games_week["home_team"].astype(str)) | set(games_week["away_team"].astype(str))
        for team in teams_this_week:
            states.setdefault(team, TeamState())

        # All rows are emitted before this week's PBP or scores update any state.
        for _, game in games_week.iterrows():
            rows.append(
                _feature_row(
                    game,
                    states[str(game["home_team"])],
                    states[str(game["away_team"])],
                )
            )

        game_ids = set(games_week["game_id"].astype(str))
        plays_week = plays[plays["game_id"].astype(str).isin(game_ids)]
        observations = _weekly_observations(games_week, plays_week, states)
        for team, (observation, n_plays) in observations.items():
            states.setdefault(team, TeamState()).update(observation, n_plays)
        weeks_processed += 1

    frame = pd.DataFrame(rows, columns=IDENTITY_COLUMNS + MODEL_FEATURES + TARGET_COLUMNS)
    assert_feature_firewall(frame)
    audit = {
        **play_audit,
        "feature_rows": int(len(frame)),
        "weeks_processed": weeks_processed,
        "target_complete_rows": int(frame[TARGET_COLUMNS].notna().all(axis=1).sum()),
        "model_id": MODEL_ID,
        "same_week_update_policy": "batch_after_all_week_features",
    }
    return frame, audit


def input_hash_records(paths: Iterable[str | Path]) -> list[dict[str, str]]:
    return [
        {"filename": Path(path).name, "sha256": sha256_file(path)}
        for path in paths
    ]
