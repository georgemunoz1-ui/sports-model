"""Independent CFB matchup-efficiency experiment; never changes the selected arm.

Historical archive EPA can have been recomputed by the provider. Chronological
reconstruction is therefore diagnostic, not proof of original point-in-time data.
The first stage augments the exact incumbent feature transform; it does not fit a
total head or infer personnel. EPA-positive success is explicitly named below.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from models.current.linear import pack, predict as linear_predict

MODEL_ID = "cfb.fbs.matchup_efficiency.v1.research"
CONTROL_ID = "cfb.fbs.elo_form_logit_ridge.v1_0.shadow.reconstructed_2024fit"
MATCHED_CONTROL_ID = "cfb.fbs.elo_form.matched_population.control.v1"
BASELINE_PARENT_ID = "cfb.fbs.elo_form_logit_ridge.v1_0.shadow"
PERSONNEL_ID = "cfb.fbs.matchup_efficiency.personnel.v1.research"
JOINT_ID = "cfb.fbs.matchup_efficiency.joint.v1.research"
STAGE_ID = "matchup_efficiency"
DEFAULT_CONFIG = {
    "opponent_ridge_alpha": 20.0,
    "opponent_sample_weight_denominator": 50.0,
    "history_seasons": 3,
    "minimum_team_games": 2,
    "minimum_type_plays": 20,
    "winner_c": 1.0,
    "margin_ridge_alpha": 1.0,
    "label_lag_hours": 24,
    "minimum_training_rows": 100,
    "fit_through_season": 2024,
    "baseline_parameters": {"k": 28.0, "hfa": 55.0, "regress": 0.75, "alpha": 0.4},
    "success_definition": "EPA_STRICTLY_POSITIVE",
    "feature_freeze": "EARLIEST_KICKOFF_IN_SEASON_WEEK",
}
METRICS = ("pass_epa", "rush_epa", "pass_epa_success", "rush_epa_success")
EFFICIENCY_FEATURES = [f"{side}_{metric}" for side in ("home", "away") for metric in METRICS]
PERSONNEL_FEATURES = [f"{side}_{key}" for side in ("home", "away") for key in ("qb_availability", "offense_returning_snap_share", "defense_returning_snap_share")]
BASELINE_FEATURES = [
    "elo_diff_with_home_advantage", "home_ewma_points_for", "home_ewma_points_against",
    "away_ewma_points_for", "away_ewma_points_against", "home_ewma_margin",
    "away_ewma_margin", "rest_days_diff", "neutral_site", "conference_game",
]
FEATURES = BASELINE_FEATURES + EFFICIENCY_FEATURES


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def config_with(overrides=None):
    cfg = dict(DEFAULT_CONFIG)
    cfg["baseline_parameters"] = dict(DEFAULT_CONFIG["baseline_parameters"])
    if overrides:
        unknown = set(overrides) - set(cfg)
        if unknown:
            raise ValueError("UNKNOWN_CFB_CONFIG:" + ",".join(sorted(unknown)))
        cfg.update(overrides)
    if cfg["history_seasons"] < 1 or cfg["minimum_team_games"] < 1 or cfg["minimum_type_plays"] < 1:
        raise ValueError("INVALID_CFB_CONFIG")
    return cfg


def feature_config_hash(cfg):
    return digest({k: cfg[k] for k in ("opponent_ridge_alpha", "opponent_sample_weight_denominator", "history_seasons", "minimum_team_games", "minimum_type_plays", "label_lag_hours", "baseline_parameters", "success_definition", "feature_freeze")})


def utc(value):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return stamp.tz_convert("UTC")


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _provider_id(value):
    if isinstance(value, (bool, np.bool_)) or value is None:
        raise ValueError("CFB_PROVIDER_ID_REQUIRED")
    if isinstance(value, (int, np.integer)) and value > 0:
        return str(int(value))
    if isinstance(value, str) and value.isascii() and value.isdigit() and int(value) > 0:
        return str(int(value))
    raise ValueError("CFB_INVALID_PROVIDER_ID")


def canonical_game(row):
    """Normalize schedule records without guessing an event or team identity."""
    row = dict(row)
    gid = _provider_id(row.get("game_id", str(row.get("event_id", "")).removeprefix("CFB:")))
    if not gid or not row.get("home_team") or not row.get("away_team"):
        raise ValueError("CFB_EVENT_IDENTITY_REQUIRED")
    if row["home_team"] == row["away_team"]:
        raise ValueError("CFB_IDENTICAL_COMPETITORS")
    row["game_id"] = gid
    row["event_id"] = "CFB:" + gid
    row["start_time_utc"] = utc(row.get("start_time_utc", row.get("start_date"))).isoformat()
    for side in ("home", "away"):
        key = side + "_id"
        if key not in row or row[key] is None:
            raise ValueError("CFB_PROVIDER_TEAM_ID_REQUIRED")
        row[key] = _provider_id(row[key])
    if row["home_id"] == row["away_id"]:
        raise ValueError("CFB_IDENTICAL_PROVIDER_IDS")
    row["season"] = int(row["season"])
    row["week"] = int(row["week"])
    row.setdefault("neutral_site", False)
    row.setdefault("conference_game", False)
    row.setdefault("home_pregame_elo", None)
    row.setdefault("away_pregame_elo", None)
    return clean(row)


def aggregate_pbp(parquet_paths, games, source_by_path):
    """Bind each play to schedule IDs; aggregate only FBS-v-FBS scrimmage plays.

    Provider possession names must exactly identify one event competitor; no fuzzy
    aliasing. Result availability is unknown historically: a conservative 24-hour
    label lag is an explicit reconstruction assumption, not an original receipt.
    """
    import pyarrow.parquet as pq
    schedule = {g["event_id"]: g for g in map(canonical_game, games)}
    rows, incidents, seen, normalizations = [], [], set(), []
    columns = ["game_id", "new_id", "home_team_id", "away_team_id", "home_team", "away_team",
               "pos_team", "def_pos_team", "EPA", "down", "rush", "pass", "sack",
               "penalty_no_play", "play_type", "wallclock", "completed", "start_date"]
    for path in map(Path, parquet_paths):
        source = dict(source_by_path[str(path)])
        raw_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if source.get("sha256") != raw_hash:
            raise ValueError("CFB_SOURCE_HASH_MISMATCH")
        frame = pq.read_table(path, columns=columns).to_pandas()
        for gid, group in frame.groupby("game_id", sort=False):
            eid = "CFB:" + str(int(gid))
            if eid not in schedule:
                incidents.append({"event_id": eid, "reason": "NO_MATCHING_SCHEDULE_EVENT"})
                continue
            g = schedule[eid]
            original_count = len(group)
            group = group.drop_duplicates()
            if len(group) < original_count:
                normalizations.append({"event_id": eid, "rule": "COLLAPSE_IDENTICAL_CONSUMED_PLAY_FIELDS", "removed_rows": original_count - len(group)})
            if not g.get("completed") or g.get("home_division") != "fbs" or g.get("away_division") != "fbs":
                continue
            if eid in seen:
                raise ValueError("DUPLICATE_CFB_PBP_EVENT:" + eid)
            seen.add(eid)
            expected_ids = (int(g["home_id"]), int(g["away_id"]))
            actual_ids = group[["home_team_id", "away_team_id"]].drop_duplicates()
            if len(actual_ids) != 1 or tuple(int(v) for v in actual_ids.iloc[0]) != expected_ids:
                incidents.append({"event_id": eid, "reason": "PROVIDER_TEAM_ID_CONFLICT"})
                continue
            starts = group.start_date.dropna().unique()
            if len(starts) > 1 or (len(starts) == 1 and utc(starts[0]) != utc(g["start_time_utc"])):
                incidents.append({"event_id": eid, "reason": "PROVIDER_START_CONFLICT"})
                continue
            identity = group[["home_team", "away_team"]].drop_duplicates()
            if len(identity) != 1:
                incidents.append({"event_id": eid, "reason": "AMBIGUOUS_EVENT_NAMES"})
                continue
            hn, an = identity.iloc[0]
            if pd.isna(hn):
                hn = g["home_team"]
            if pd.isna(an):
                an = g["away_team"]
            if hn == an:
                incidents.append({"event_id": eid, "reason": "AMBIGUOUS_EVENT_NAMES"})
                continue
            valid = group.down.between(1, 4) & ~group.penalty_no_play.fillna(True)
            valid &= np.isfinite(group.EPA)
            valid &= ~group.play_type.fillna("").str.contains("kneel|spike", case=False, regex=True)
            pass_mask = valid & ((group["pass"] == 1) | (group.sack == 1))
            rush_mask = valid & (group.rush == 1) & ~pass_mask
            classified = group.loc[pass_mask | rush_mask]
            paired = (((classified.pos_team == hn) & (classified.def_pos_team == an)) |
                      ((classified.pos_team == an) & (classified.def_pos_team == hn)))
            if not paired.all():
                incidents.append({"event_id": eid, "reason": "AMBIGUOUS_POSSESSION_TEAM"})
                continue
            ids = group.new_id
            if ids.isna().any() or (ids.abs() >= 2**53).any() or (ids % 1 != 0).any() or ids.duplicated().any():
                incidents.append({"event_id": eid, "reason": "DUPLICATE_PLAY_ID"})
                continue
            pair_rows = []
            for side, name, other in (("home", hn, "away"), ("away", an, "home")):
                record = {"event_id": eid, "team_id": g[side + "_id"], "opponent_id": g[other + "_id"],
                          "season": g["season"], "week": g["week"], "start_time_utc": g["start_time_utc"],
                          "available_at_utc": (utc(g["start_time_utc"]) + pd.Timedelta(hours=24)).isoformat(),
                          "availability_basis": "RECONSTRUCTED_24H_LABEL_LAG_NOT_ORIGINAL_RECEIPT",
                          "source": source, "play_filter": "PASS_INCLUDES_SACKS_NO_NOPLAY_KNEEL_SPIKE",
                          "play_identity": "EVENT_ID_PLUS_PROVIDER_NEW_ID_EXACT_INTEGER"}
                for play_type, mask in (("pass", pass_mask), ("rush", rush_mask)):
                    subset = group.loc[mask & (group.pos_team == name), "EPA"]
                    record[play_type + "_plays"] = int(len(subset))
                    record[play_type + "_epa_sum"] = float(subset.sum())
                    record[play_type + "_successes"] = int((subset > 0).sum())
                pair_rows.append(record)
            if any(r["pass_plays"] == 0 or r["rush_plays"] == 0 for r in pair_rows):
                incidents.append({"event_id": eid, "reason": "INCOMPLETE_PASS_RUSH_COVERAGE"})
                continue
            rows.extend(pair_rows)
    return {"team_games": rows, "incidents": incidents, "normalizations": normalizations, "source_count": len(parquet_paths),
            "matched_events": len(rows) // 2, "evidence_scope": "RETROSPECTIVE_ARCHIVE_RECONSTRUCTION",
            "limitations": ["PROVIDER_EPA_MODEL_TRAINING_CHRONOLOGY_UNKNOWN", "ORIGINAL_AVAILABILITY_RECEIPTS_ABSENT",
                            "GARBAGE_TIME_NOT_ADJUSTED", "EPA_POSITIVE_SUCCESS_NOT_YARDAGE_SUCCESS"]}


def validate_team_games(records, games):
    by_event = {g["event_id"]: g for g in games}
    seen = set()
    for r in records:
        key = (r["event_id"], str(r["team_id"]))
        if key in seen:
            raise ValueError("DUPLICATE_CFB_TEAM_GAME")
        seen.add(key)
        if r["event_id"] not in by_event:
            raise ValueError("CFB_METRIC_EVENT_NOT_IN_SCHEDULE")
        g = by_event[r["event_id"]]
        if {str(r["team_id"]), str(r["opponent_id"])} != {g["home_id"], g["away_id"]}:
            raise ValueError("CFB_METRIC_TEAM_ID_MISMATCH")
        if utc(r["start_time_utc"]) != utc(g["start_time_utc"]):
            raise ValueError("CFB_METRIC_START_MISMATCH")
        if utc(r["available_at_utc"]) <= utc(r["start_time_utc"]):
            raise ValueError("CFB_FINAL_AVAILABLE_BEFORE_START")
        for typ in ("pass", "rush"):
            n, total, success = r[typ + "_plays"], r[typ + "_epa_sum"], r[typ + "_successes"]
            if isinstance(n, bool) or not isinstance(n, (int, np.integer)) or n <= 0:
                raise ValueError("CFB_INVALID_PLAY_COUNT")
            if isinstance(total, bool) or not np.isfinite(total):
                raise ValueError("CFB_INVALID_EPA")
            if isinstance(success, bool) or not isinstance(success, (int, np.integer)) or not 0 <= success <= n:
                raise ValueError("CFB_INVALID_SUCCESS_COUNT")
        source = r.get("source", {})
        if not source.get("source") or len(source.get("sha256", "")) != 64 or not source.get("retrieved_at_utc"):
            raise ValueError("CFB_SOURCE_BINDING_REQUIRED")


def opponent_state(records, cutoff, season, config=None):
    cfg = config_with(config)
    cutoff = utc(cutoff)
    usable = [r for r in records if utc(r["available_at_utc"]) < cutoff
              and season - cfg["history_seasons"] < int(r["season"]) <= season]
    teams = sorted({str(r[k]) for r in usable for k in ("team_id", "opponent_id")})
    counts = {t: {"games": 0, "pass_plays": 0, "rush_plays": 0} for t in teams}
    if not usable:
        return {"teams": {}, "metrics": {}, "used_event_ids": [], "source_bindings": [], "cutoff_utc": cutoff.isoformat()}
    index = {t: i for i, t in enumerate(teams)}
    x = np.zeros((len(usable), 2 * len(teams)))
    for i, r in enumerate(usable):
        x[i, index[str(r["team_id"])]] = 1
        x[i, len(teams) + index[str(r["opponent_id"])]] = 1
        counts[str(r["team_id"])]["games"] += 1
        for typ in ("pass", "rush"):
            counts[str(r["team_id"])][typ + "_plays"] += r[typ + "_plays"]
    fits = {}
    for metric in METRICS:
        typ = metric.split("_")[0]
        numerator = typ + ("_successes" if metric.endswith("success") else "_epa_sum")
        n = np.array([r[typ + "_plays"] for r in usable], float)
        y = np.array([r[numerator] for r in usable], float) / n
        reg = Ridge(alpha=cfg["opponent_ridge_alpha"]).fit(x, y, sample_weight=n / cfg["opponent_sample_weight_denominator"])
        fits[metric] = {"intercept": float(reg.intercept_),
                        "offense": {t: float(reg.coef_[i]) for t, i in index.items()},
                        "defense_allowed": {t: float(reg.coef_[len(teams) + i]) for t, i in index.items()}}
    sources = {r["source"]["sha256"]: r["source"] for r in usable}
    return {"teams": counts, "metrics": fits, "used_event_ids": sorted({r["event_id"] for r in usable}),
            "source_bindings": list(sources.values()), "cutoff_utc": cutoff.isoformat(),
            "max_history_available_at_utc": max(r["available_at_utc"] for r in usable),
            "state_sha256": digest({"records": usable, "config": cfg})}


def efficiency_features(state, event, config=None):
    cfg = config_with(config)
    failures, components = [], {}
    if utc(state["cutoff_utc"]) > utc(event["start_time_utc"]):
        raise ValueError("CFB_FEATURE_STATE_AFTER_START")
    for side, other in (("home", "away"), ("away", "home")):
        team, opponent = str(event[side + "_id"]), str(event[other + "_id"])
        count = state["teams"].get(team, {})
        if count.get("games", 0) < cfg["minimum_team_games"]:
            failures.append(side.upper() + "_INSUFFICIENT_EFFICIENCY_HISTORY")
        for typ in ("pass", "rush"):
            if count.get(typ + "_plays", 0) < cfg["minimum_type_plays"]:
                failures.append(side.upper() + "_INSUFFICIENT_" + typ.upper() + "_PLAYS")
        for metric in METRICS:
            fit = state["metrics"].get(metric)
            if not fit or team not in fit["offense"] or opponent not in fit["defense_allowed"]:
                components[side + "_" + metric] = None
                continue
            value = fit["intercept"] + fit["offense"][team] + fit["defense_allowed"][opponent]
            if metric.endswith("success"):
                value = float(np.clip(value, 0, 1))
            components[side + "_" + metric] = float(value)
    return components, sorted(set(failures))


def prepare_examples(history, config=None):
    """Build baseline and matchup feature receipts before each weekly block.

    history={games:[schedule records],team_games:[aggregate_pbp rows]}. No score or
    metric from the target event enters its feature state. The incumbent's exact
    transform stays in its module and is invoked rather than reimplemented.
    """
    from harness import cfb_v1_port as incumbent
    cfg = config_with(config)
    games = sorted(map(canonical_game, history["games"]), key=lambda g: (utc(g["start_time_utc"]), g["game_id"]))
    if len({g["event_id"] for g in games}) != len(games):
        raise ValueError("DUPLICATE_CFB_SCHEDULE_EVENT")
    records = history.get("team_games", [])
    validate_team_games(records, games)
    completed = [g for g in games if g.get("completed") and g.get("home_points") is not None and g.get("away_points") is not None]
    frame = pd.DataFrame(completed)
    frame["kick"] = pd.to_datetime(frame.start_time_utc, utc=True)
    base = incumbent.build_state(frame, **cfg["baseline_parameters"])
    base_by_id = {"CFB:" + str(r["game_id"]): clean({k: r[k] for k in BASELINE_FEATURES}) for r in base.to_dict("records")}
    targets = [g for g in games if g.get("home_division") == "fbs" and g.get("away_division") == "fbs"]
    cutoffs = {}
    for g in targets:
        key = (g["season"], g["week"])
        cutoffs[key] = min(cutoffs.get(key, utc(g["start_time_utc"])), utc(g["start_time_utc"]))
    cutoffs = {k: v - pd.Timedelta(microseconds=1) for k, v in cutoffs.items()}
    legacy_late = set()
    last_start_by_team = {}
    for g in games:
        key = (g["season"], g["week"])
        if key in cutoffs and any(last_start_by_team.get(g[side + "_id"], pd.Timestamp.min.tz_localize("UTC")) >= cutoffs[key] for side in ("home", "away")):
            legacy_late.add(g["event_id"])
        if g.get("completed"):
            for side in ("home", "away"):
                last_start_by_team[g[side + "_id"]] = utc(g["start_time_utc"])
    states, result = {}, []
    for g in targets:
        key = (g["season"], g["week"])
        if key not in states:
            states[key] = opponent_state(records, cutoffs[key], g["season"], cfg)
            expected = {}
            recent = frame[(frame.kick + pd.Timedelta(hours=cfg["label_lag_hours"]) < cutoffs[key]) &
                           (frame.season > g["season"] - cfg["history_seasons"]) &
                           (frame.home_division == "fbs") & (frame.away_division == "fbs")]
            for prior in recent.to_dict("records"):
                for side in ("home", "away"):
                    expected[str(prior[side + "_id"])] = prior["event_id"]
            states[key]["expected_latest_event_by_team"] = expected
        state = states[key]
        if g["event_id"] in base_by_id:
            bx = base_by_id[g["event_id"]]
        else:
            earlier = frame[frame.kick < cutoffs[key]].copy()
            target = dict(g, home_points=0, away_points=0, kick=utc(g["start_time_utc"]))
            probe = incumbent.build_state(pd.concat([earlier, pd.DataFrame([target])], ignore_index=True), **cfg["baseline_parameters"]).iloc[-1]
            bx = clean({k: probe[k] for k in BASELINE_FEATURES})
        ef, failures = efficiency_features(state, g, cfg)
        for side in ("home", "away"):
            expected = state.get("expected_latest_event_by_team", {}).get(g[side + "_id"])
            if expected is not None and expected not in state["used_event_ids"]:
                failures.append(side.upper() + "_LATEST_FBS_EFFICIENCY_GAME_MISSING")
        if g["event_id"] in legacy_late:
            failures.append("LEGACY_BASELINE_FEATURES_AFTER_WEEK_CUTOFF")
        if g["week"] <= 1:
            failures.append("WEEK1_REQUIRES_SEPARATE_SELECTED_CONTROL")
        complete = bool(g.get("completed") and g.get("home_points") is not None and g.get("away_points") is not None)
        outcome = None
        if complete:
            outcome = {"home_win": int(g["home_points"] > g["away_points"]),
                       "home_margin": float(g["home_points"] - g["away_points"]),
                       "total": float(g["home_points"] + g["away_points"]),
                       "home_score": float(g["home_points"]), "away_score": float(g["away_points"])}
        result.append({"event_id": g["event_id"], "event": g, "season": g["season"], "week": g["week"],
                       "start_time_utc": g["start_time_utc"], "cutoff_utc": cutoffs[key].isoformat(),
                       "label_available_at_utc": (utc(g["start_time_utc"]) + pd.Timedelta(hours=cfg["label_lag_hours"])).isoformat() if complete else None,
                       "features": {**bx, **ef}, "baseline_features": bx, "target": outcome,
                       "components": ef, "feature_config_sha256": feature_config_hash(cfg), "eligible": not failures, "reasons": sorted(set(failures)),
                       "source_bindings": list({v["sha256"]: v for v in state["source_bindings"] + history.get("schedule_sources", [])}.values()),
                       "history_max_available_at_utc": state.get("max_history_available_at_utc"),
                       "history_event_ids": state["used_event_ids"], "component_state_sha256": state.get("state_sha256"),
                       "evidence_scope": "RETROSPECTIVE_ARCHIVE_RECONSTRUCTION"})
    return result


def fit(train_examples, config=None, *, control=False, matched_control=False, personnel=False):
    cfg = config_with(config)
    rows = [r for r in train_examples if r.get("target") is not None and ((control and not matched_control) or r.get("eligible"))]
    if personnel:
        rows = [{**r, "features": {**r["features"], **personnel_values(r)}} for r in rows]
    if len({r["event_id"] for r in rows}) != len(rows):
        raise ValueError("DUPLICATE_CFB_FIT_EVENT")
    if any(r["season"] > cfg["fit_through_season"] for r in rows):
        raise ValueError("CFB_FIT_AFTER_DECLARED_SEASON")
    if any(r.get("feature_config_sha256") != feature_config_hash(cfg) for r in rows):
        raise ValueError("CFB_FEATURE_CONFIG_DRIFT")
    if len(rows) < cfg["minimum_training_rows"]:
        raise ValueError("CFB_INSUFFICIENT_FIT_POPULATION")
    if control and not matched_control and (len(rows) < 500 or len({r["season"] for r in rows}) < 5):
        raise ValueError("CFB_INCUMBENT_MINIMUM_HISTORY_NOT_MET")
    features = BASELINE_FEATURES if control else FEATURES + (PERSONNEL_FEATURES if personnel else [])
    x = [[r["baseline_features" if control else "features"].get(k) for k in features] for r in rows]
    x = np.asarray([[np.nan if v is None else v for v in row] for row in x], float)
    if np.isinf(x).any() or np.all(np.isnan(x), axis=0).any():
        raise ValueError("CFB_UNIDENTIFIED_OR_NONFINITE_FEATURE")
    y = [r["target"]["home_win"] for r in rows]
    if len(set(y)) != 2:
        raise ValueError("CFB_BOTH_WINNER_CLASSES_REQUIRED")
    clf = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=cfg["winner_c"], max_iter=2000))
    margin = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=cfg["margin_ridge_alpha"]))
    clf.fit(x, y)
    margin.fit(x, [r["target"]["home_margin"] for r in rows])
    identity = MATCHED_CONTROL_ID if matched_control else CONTROL_ID if control else PERSONNEL_ID if personnel else MODEL_ID
    result = {"model_id": identity, "parent_model_id": BASELINE_PARENT_ID, "stage_id": "matched_population_control" if matched_control else "incumbent_reconstruction" if control else "personnel" if personnel else STAGE_ID,
              "feature_names": features, "fitted_model": {"winner": pack(clf, "logistic"), "margin": pack(margin, "linear")},
              "config": cfg, "feature_config_sha256": feature_config_hash(cfg), "training_rows": len(rows), "training_event_ids": [r["event_id"] for r in rows],
              "training_population_sha256": digest([{k: r[k] for k in ("event_id", "features", "target")} for r in rows]),
              "training_max_start_utc": max(r["start_time_utc"] for r in rows),
              "training_max_label_available_at_utc": max(r["label_available_at_utc"] for r in rows),
              "source_bindings": list({s["sha256"]: s for r in rows for s in r["source_bindings"]}.values()),
              "action_authority": False, "predictive_validation": "UNVALIDATED"}
    result["state_sha256"] = digest(result)
    return result


def fit_control(train_examples, config=None):
    return fit(train_examples, config, control=True)


def fit_matched_control(train_examples, config=None):
    return fit(train_examples, config, control=True, matched_control=True)


def personnel_values(example):
    supplied = example.get("personnel_features")
    sources = example.get("personnel_sources", [])
    if not isinstance(supplied, dict) or set(supplied) != set(PERSONNEL_FEATURES) or not sources:
        raise ValueError("CFB_PERSONNEL_SOURCE_BOUND_INPUTS_REQUIRED")
    for value in supplied.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("CFB_PERSONNEL_VALUE_RANGE")
    for source in sources:
        if not source.get("source") or len(source.get("sha256", "")) != 64 or not source.get("available_at_utc"):
            raise ValueError("CFB_PERSONNEL_AVAILABILITY_PROOF_REQUIRED")
        if utc(source["available_at_utc"]) >= utc(example["cutoff_utc"]):
            raise ValueError("CFB_PERSONNEL_AFTER_CUTOFF")
    return supplied


def fit_personnel(train_examples, config=None):
    return fit(train_examples, config, personnel=True)


def predict(state, example, stage=None):
    if digest({k: v for k, v in state.items() if k != "state_sha256"}) != state.get("state_sha256"):
        raise ValueError("CFB_FITTED_STATE_DIGEST_MISMATCH")
    if state.get("feature_config_sha256") != example.get("feature_config_sha256"):
        raise ValueError("CFB_FEATURE_CONFIG_DRIFT")
    if state["model_id"] == JOINT_ID:
        return predict_joint(state, example)
    if stage is not None and stage not in (state["stage_id"], "efficiency" if state["model_id"] == MODEL_ID else state["stage_id"]):
        raise ValueError("CFB_STAGE_ID_MISMATCH")
    if state["model_id"] not in (MODEL_ID, CONTROL_ID, MATCHED_CONTROL_ID, PERSONNEL_ID):
        raise ValueError("CFB_UNKNOWN_MODEL_ID")
    if utc(state["training_max_label_available_at_utc"]) >= utc(example["cutoff_utc"]):
        raise ValueError("CFB_TRAINING_LABEL_AFTER_FORECAST_CUTOFF")
    if example["event_id"] in state["training_event_ids"]:
        raise ValueError("CFB_TARGET_EVENT_IN_FIT")
    if state["model_id"] in (MODEL_ID, PERSONNEL_ID, MATCHED_CONTROL_ID) and not example.get("eligible"):
        raise ValueError("CFB_MATCHUP_INPUT_BLOCKED:" + ",".join(example["reasons"]))
    if example["week"] <= 1:
        raise ValueError("WEEK1_REQUIRES_SEPARATE_SELECTED_CONTROL")
    if "LEGACY_BASELINE_FEATURES_AFTER_WEEK_CUTOFF" in example.get("reasons", []):
        raise ValueError("LEGACY_BASELINE_FEATURES_AFTER_WEEK_CUTOFF")
    feature_values = example["baseline_features" if state["model_id"] in (CONTROL_ID, MATCHED_CONTROL_ID) else "features"]
    if state["model_id"] == PERSONNEL_ID:
        feature_values = {**feature_values, **personnel_values(example)}
    x = [feature_values[k] for k in state["feature_names"]]
    p = linear_predict(state["fitted_model"]["winner"], x)
    margin = linear_predict(state["fitted_model"]["margin"], x)
    components = dict(example["components"]) if state["model_id"] in (MODEL_ID, PERSONNEL_ID) else {}
    for name, head in state["fitted_model"].items():
        values = np.array([np.nan if v is None else v for v in x], float)
        values = np.where(np.isnan(values), head["impute"], values)
        contributions = (values - head["mean"]) / head["scale"] * head["coefficient"]
        components[name + "_intercept"] = head["intercept"]
        components.update({name + "_contribution_" + k: float(v) for k, v in zip(state["feature_names"], contributions)})
    return {"model_id": state["model_id"], "stage_id": state["stage_id"], "event_id": example["event_id"],
            "p_home": p, "home_margin": margin, "total": None,
            "components": components, "input_snapshot": dict(zip(state["feature_names"], x)),
            "model_state_sha256": state["state_sha256"], "action_authority": False,
            "limitations": ["TOTAL_HEAD_NOT_FITTED", "NO_PERSONNEL_FEATURES", "NO_JOINT_SCORE_DISTRIBUTION",
                            "ORIGINAL_HISTORICAL_PIT_UNVERIFIED", "PROVIDER_EPA_MODEL_TRAINING_CHRONOLOGY_UNKNOWN"]}


def predict_control(state, example):
    if state["model_id"] not in (CONTROL_ID, MATCHED_CONTROL_ID):
        raise ValueError("CFB_NOT_CONTROL_STATE")
    return predict(state, example)


def _fit_total(rows, cfg):
    x = np.array([[np.nan if r["features"][k] is None else r["features"][k] for k in FEATURES] for r in rows], float)
    reg = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=cfg["margin_ridge_alpha"]))
    reg.fit(x, [r["target"]["total"] for r in rows])
    return pack(reg, "linear")


def fit_joint(train_examples, calibration_examples, config=None):
    """Separate score-head increment with 2024 out-of-sample residual covariance.

    The calibration fits through 2023, predicts 2024 without refitting on its
    labels, then score means refit through 2024. Gaussian real-valued score draws
    are a research distribution, not integer football/key-number/OT settlement.
    """
    cfg = config_with(config)
    earlier = [r for r in train_examples if r.get("eligible") and r.get("target")]
    calibration = [r for r in calibration_examples if r.get("eligible") and r.get("target")]
    if not earlier or not calibration or max(r["season"] for r in earlier) > 2023 or {r["season"] for r in calibration} != {2024}:
        raise ValueError("CFB_JOINT_REQUIRES_TRAIN_THROUGH_2023_CALIBRATION_2024")
    if len(calibration) < 50 or {r["event_id"] for r in earlier} & {r["event_id"] for r in calibration}:
        raise ValueError("CFB_JOINT_CALIBRATION_POPULATION")
    early_config = {**cfg, "fit_through_season": 2023}
    early = fit(earlier, early_config)
    total_head = _fit_total(earlier, early_config)
    errors, cal_predictions = [], []
    for r in calibration:
        point = predict(early, r)
        total = linear_predict(total_head, [r["features"][k] for k in FEATURES])
        errors.append([r["target"]["home_margin"] - point["home_margin"], r["target"]["total"] - total])
        cal_predictions.append({"event_id": r["event_id"], "home_margin": point["home_margin"], "total": total})
    errors = np.array(errors)
    covariance = np.cov(errors, rowvar=False, ddof=1)
    if not np.isfinite(covariance).all() or np.linalg.eigvalsh(covariance).min() <= 0:
        raise ValueError("CFB_JOINT_NONPOSITIVE_COVARIANCE")
    final = fit(earlier + calibration, cfg)
    final.pop("state_sha256")
    final["model_id"] = JOINT_ID
    final["stage_id"] = "joint_distribution"
    final["parent_model_id"] = MODEL_ID
    final["fitted_model"]["total"] = _fit_total(earlier + calibration, cfg)
    final["residual_covariance_margin_total"] = covariance.tolist()
    final["residual_mean_margin_total"] = errors.mean(axis=0).tolist()
    final["calibration"] = {"method": "2024_OUT_OF_SAMPLE_AFTER_FIXED_2023_FIT", "rows": len(calibration),
                            "event_ids": [r["event_id"] for r in calibration], "prediction_sha256": digest(cal_predictions),
                            "predictions": cal_predictions, "parent_2023_state_sha256": early["state_sha256"]}
    final["distribution_id"] = "cfb.continuous_gaussian_margin_total.v1.diagnostic"
    final["state_sha256"] = digest(final)
    return final


def predict_joint(state, example):
    from scipy.stats import norm
    if state.get("model_id") != JOINT_ID:
        raise ValueError("CFB_NOT_JOINT_STATE")
    if digest({k: v for k, v in state.items() if k != "state_sha256"}) != state.get("state_sha256"):
        raise ValueError("CFB_FITTED_STATE_DIGEST_MISMATCH")
    if state.get("feature_config_sha256") != example.get("feature_config_sha256"):
        raise ValueError("CFB_FEATURE_CONFIG_DRIFT")
    if not example.get("eligible"):
        raise ValueError("CFB_MATCHUP_INPUT_BLOCKED")
    if example["event_id"] in state["training_event_ids"] or utc(state["training_max_label_available_at_utc"]) >= utc(example["cutoff_utc"]):
        raise ValueError("CFB_JOINT_TRAINING_OVERLAP")
    x = [example["features"][k] for k in FEATURES]
    margin = linear_predict(state["fitted_model"]["margin"], x) + state["residual_mean_margin_total"][0]
    total = linear_predict(state["fitted_model"]["total"], x) + state["residual_mean_margin_total"][1]
    cov = np.array(state["residual_covariance_margin_total"])
    p = float(norm.cdf(margin / np.sqrt(cov[0, 0])))
    components = {**example["components"], "expected_home_score": (total + margin) / 2,
                  "expected_away_score": (total - margin) / 2, "expected_margin": margin, "expected_total": total,
                  "margin_variance": float(cov[0, 0]), "total_variance": float(cov[1, 1]),
                  "margin_total_covariance": float(cov[0, 1])}
    return {"model_id": JOINT_ID, "stage_id": "joint_distribution", "event_id": example["event_id"],
            "p_home": p, "home_margin": margin, "total": total, "components": components,
            "input_snapshot": dict(zip(FEATURES, x)), "model_state_sha256": state["state_sha256"],
            "distribution_id": state["distribution_id"], "action_authority": False,
            "limitations": ["CONTINUOUS_SCORE_SURROGATE_NOT_INTEGER_FOOTBALL_SETTLEMENT", "NO_FITTED_OVERTIME_OR_KEY_NUMBER_MASS",
                            "GAUSSIAN_NEGATIVE_SCORE_TAIL_NOT_TRUNCATED", "PROVIDER_EPA_MODEL_TRAINING_CHRONOLOGY_UNKNOWN",
                            "ORIGINAL_HISTORICAL_PIT_UNVERIFIED"]}


def simulate_joint(state, example, n=100000, seed=20261023):
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 1000000:
        raise ValueError("CFB_JOINT_DRAW_COUNT")
    point = predict_joint(state, example)
    rng = np.random.default_rng(seed)
    margin_total = rng.multivariate_normal([point["home_margin"], point["total"]], state["residual_covariance_margin_total"], size=n)
    scores = np.column_stack(((margin_total[:, 1] + margin_total[:, 0]) / 2,
                              (margin_total[:, 1] - margin_total[:, 0]) / 2))
    receipt = {"distribution_id": state["distribution_id"], "count": n, "seed": seed, "rng": "numpy.PCG64",
               "score_support": "REAL_VALUED_GAUSSIAN_DIAGNOSTIC", "encoding": "numpy.float64.little_endian.rows_home_away",
               "draw_sha256": hashlib.sha256(scores.astype("<f8").tobytes()).hexdigest(),
               "home_win_probability": float(np.mean(scores[:, 0] > scores[:, 1])),
               "negative_score_draws": int(np.any(scores < 0, axis=1).sum()), "settlement_eligible": False}
    return scores, receipt
