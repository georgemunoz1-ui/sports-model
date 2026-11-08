"""Standalone men's D-I basketball score research. No selection or publication authority."""

import argparse
import csv
import hashlib
import io
import itertools
import json
import sys
import re
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models.common.discrete_research import digest
from scripts import cbb_missingness as missingness

PACIFIC = ZoneInfo("America/Los_Angeles")
HISTORY_REPO = "sportsdataverse/hoopR-mbb-data"
REFERENCE_COMMIT = "0790e43de19394df681322d21da53e0c77db8ec7"
# ESPN Division I conference IDs observed in the source seasons; unrecognized affiliations abstain.
D1 = frozenset(
    map(
        int,
        "1 2 3 4 5 6 7 8 9 10 11 12 13 14 16 18 19 20 21 22 23 24 25 26 27 29 30 43 44 45 46 49 62".split(),
    )
)
PARAMS = {
    "margin_update": 0.08,
    "total_update": 0.05,
    "offseason_retention": 0.50,
    "min_prior_games": 5,
    "calibration_season_ending": 2025,
    "first_history_season": 2022,
}
N = 100_000
SETTLEMENT = "FULL_GAME_INCLUDING_OVERTIME"
MODEL = "cbb.men.d1.opponent_adjusted_score_residual.v1.research"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def now():
    return datetime.now(timezone.utc)


def ts(s):
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return t


def write(p, d):
    with p.open("x") as f:
        json.dump(d, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def remote(url):
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "cbb-shadow-research"}),
        timeout=60,
    ) as response:
        return response.read()


def capture(day, path):
    path.mkdir(parents=True, exist_ok=False)
    season = day.year + int(day.month >= 7)
    if season < 2027:
        raise ValueError("FORWARD_SEASON_ONLY")
    head = json.loads(
        remote(f"https://api.github.com/repos/{HISTORY_REPO}/branches/main")
    )["commit"]["sha"]
    entries = []

    def get(name, url, kind):
        data = remote(url)
        (path / name).write_bytes(data)
        entries.append(
            {
                "file": name,
                "url": url,
                "retrieved_at_utc": now().isoformat(),
                "sha256": sha(data),
                "kind": kind,
            }
        )

    for y in range(2022, season + 1):
        name = f"mbb_schedule_{y}.parquet"
        commit = REFERENCE_COMMIT if y <= 2026 else head
        get(
            name,
            f"https://raw.githubusercontent.com/{HISTORY_REPO}/{commit}/mbb/schedules/parquet/{name}",
            "history",
        )
    for offset in range(-4, 2):
        key = (day + timedelta(days=offset)).strftime("%Y%m%d")
        get(
            key + ".json",
            f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?dates={key}&limit=1000&groups=50",
            "scoreboard",
        )
    write(
        path / "manifest.json",
        {
            "date": day.isoformat(),
            "season": season,
            "entries": entries,
            "captured_at_utc": now().isoformat(),
        },
    )


def conference(v):
    return str(v).isdigit() and int(v) in D1


def venue(value):
    # Strict and common to historical parquet values and live JSON.
    return bool(value) if isinstance(value, (bool, np.bool_)) else None


def team_id(value):
    return value is not None and re.fullmatch(r"[1-9][0-9]*", str(value)) is not None


def normalized(r):
    c = r["competitions"][0]
    players = c["competitors"]
    sides = {v.get("homeAway"): v for v in players}
    h, a = sides.get("home", {}), sides.get("away", {})
    ht, at = h.get("team", {}), a.get("team", {})
    issues = []
    if (len(r["competitions"]) != 1 or str(c.get("id")) != str(r["id"])
        or len(players) != 2 or set(sides) != {"home","away"}
        or not all(team_id(v.get("id")) and str(v["id"]) == str(v.get("team", {}).get("id")) for v in (h,a))
        or h.get("id") == a.get("id")):
        issues.append("TEAM_IDENTITY")
    site = venue(c.get("neutralSite"))
    if site is None:
        issues.append("VENUE_UNRESOLVED")
    start = ts(c["date"])
    # Copy a fixed allowlist; no odds, ranks, favorites or prices enter the numeric inputs.
    return {
        "id": str(r["id"]),
        "utc": start.isoformat(),
        "day": start.astimezone(PACIFIC).date().isoformat(),
        "season": int(r["season"]["year"]),
        "type": int(r["season"]["type"]),
        "h": str(h.get("id", "")),
        "a": str(a.get("id", "")),
        "hn": ht.get("displayName", "Unresolved home team"),
        "an": at.get("displayName", "Unresolved away team"),
        "neutral": site,
        "issues": issues,
        "affiliation_resolution": "OBSERVED_BOTH" if all(t.get("conferenceId") is not None for t in (ht,at)) else "UNRESOLVED",
        "final": c["status"]["type"]["name"] == "STATUS_FINAL"
        and c["status"]["type"]["completed"],
        "status": c["status"]["type"]["name"],
        "hs": h.get("score"),
        "as": a.get("score"),
        "d1": all(conference(t.get("conferenceId")) for t in (ht,at)),
    }


def load(path, day, cutoff):
    m = json.loads((path / "manifest.json").read_bytes())
    history = {}
    recent = {}
    historic_hashes = {}
    if (
        m["date"] != day.isoformat()
        or not 0 <= (cutoff - ts(m["captured_at_utc"])).total_seconds() <= 6 * 3600
    ):
        raise ValueError("CAPTURE_STALE_OR_WRONG_SLATE")
    expected_dates = {
        (day + timedelta(days=o)).strftime("%Y%m%d") + ".json" for o in range(-4, 2)
    }
    if {s["file"] for s in m["entries"] if s["kind"] == "scoreboard"} != expected_dates:
        raise ValueError("MISSING_SCOREBOARD_DATE")
    if {s["file"] for s in m["entries"] if s["kind"] == "history"} != {
        f"mbb_schedule_{y}.parquet" for y in range(2022, m["season"] + 1)
    }:
        raise ValueError("INCOMPLETE_HISTORY")
    cols = [
        "game_id",
        "season",
        "season_type",
        "date",
        "neutral_site",
        "home_id",
        "away_id",
        "home_conference_id",
        "away_conference_id",
        "home_score",
        "away_score",
        "status_type_name",
        "status_type_completed",
    ]
    files = [row["file"] for row in m["entries"]]
    if len(set(files)) != len(files) or any(row["kind"] not in {"history","scoreboard"} for row in m["entries"]):
        raise ValueError("DUPLICATE_OR_UNEXPECTED_SOURCE")
    for source in m["entries"]:
        f = source["file"]
        b = (path / f).read_bytes()
        if sha(b) != source["sha256"] or ts(source["retrieved_at_utc"]) > ts(
            m["captured_at_utc"]
        ):
            raise ValueError("SOURCE_RECEIPT")
        if source["kind"] == "history":
            year = int(f[-12:-8])
            if not source["url"].startswith(
                f"https://raw.githubusercontent.com/{HISTORY_REPO}/"
            ) or (year <= 2026 and REFERENCE_COMMIT not in source["url"]):
                raise ValueError("HISTORY_ORIGIN")
            historic_hashes[f] = source["sha256"]
            d = pd.read_parquet(io.BytesIO(b), columns=cols)
            d = d[
                (d.season == year)
                & d.season_type.isin([2, 3])
                & (d.status_type_name == "STATUS_FINAL")
                & d.status_type_completed
                & d.home_conference_id.isin(D1)
                & d.away_conference_id.isin(D1)
            ]
            for g in d.itertuples(index=False):
                t = ts(g.date)
                pastday = t.astimezone(PACIFIC).date()
                if t >= cutoff or pastday >= day:
                    continue
                key = str(g.game_id)
                if key in history:
                    raise ValueError("DUPLICATE_HISTORY_GAME")
                if venue(g.neutral_site) is None or not all(team_id(v) for v in (g.home_id,g.away_id)):
                    raise ValueError("HISTORICAL_VENUE_OR_ID_UNRESOLVED:" + key)
                history[key] = {
                    "id": key,
                    "day": pastday.isoformat(),
                    "utc": t.isoformat(),
                    "season": year,
                    "h": str(g.home_id),
                    "a": str(g.away_id),
                    "hs": int(g.home_score),
                    "as": int(g.away_score),
                    "neutral": venue(g.neutral_site),
                }
        else:
            expected = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?dates={f[:8]}&limit=1000&groups=50"
            if (
                expected != source["url"]
                or (cutoff - ts(source["retrieved_at_utc"])).total_seconds() > 6 * 3600
            ):
                raise ValueError("CURRENT_SOURCE_MISMATCH")
            for raw in json.loads(b)["events"]:
                g = normalized(raw)
                if g["id"] in recent and recent[g["id"]] != g:
                    if recent[g["id"]]["day"] == g["day"] == day.isoformat():
                        # Deterministic refusal for this event. A clean peer remains gradeable.
                        old = recent[g["id"]]
                        g = min((g,old), key=lambda item:(item["utc"],item["h"],item["a"],item["hn"],item["an"]))
                        g = dict(g, issues=sorted(set(g["issues"]) | {"CONFLICTING_SCHEDULE"}))
                    else:
                        raise ValueError("CONFLICTING_SCHEDULE")
                recent[g["id"]] = g
    for key, g in recent.items():
        if (
            g["final"]
            and g["d1"]
            and g["type"] in (2, 3)
            and g["day"] < day.isoformat()
            and ts(g["utc"]) < cutoff
        ):
            if g["issues"]:
                raise ValueError("HISTORICAL_SOURCE_UNRESOLVED:" + key)
            g = {
                k: g[k]
                for k in ["id", "day", "utc", "season", "h", "a", "hs", "as", "neutral"]
            }
            g["hs"] = int(g["hs"])
            g["as"] = int(g["as"])
            if key in history and any(
                g[k] != history[key][k] for k in ("h", "a", "hs", "as", "neutral")
            ):
                raise ValueError("CONFLICTING_HISTORICAL_FINAL")
            history[key] = g
    for g in history.values():
        if g["h"] == g["a"] or min(g["hs"], g["as"]) <= 0 or g["hs"] == g["as"]:
            raise ValueError("INVALID_FINAL")
    recent_ids = {
        g["id"]
        for g in recent.values()
        if g["final"]
        and g["d1"]
        and g["day"] < day.isoformat()
        and g["season"] == m["season"]
        and g["type"] in (2, 3)
    }
    if not recent_ids.issubset(history):
        raise ValueError("RECENT_FINAL_ASSIMILATION")
    targets = sorted(
        [g for g in recent.values() if g["day"] == day.isoformat()],
        key=lambda r: (r["utc"], r["id"]),
    )
    return (
        sorted(history.values(), key=lambda g: (g["day"], g["utc"], g["id"])),
        targets,
        m,
        historic_hashes,
    )


def project(state, g, prior):
    if venue(g["neutral"]) is None:
        raise ValueError("VENUE_UNRESOLVED")
    h, a = state[g["h"]], state[g["a"]]
    margin = h[0] - a[0] + prior[0] * (not g["neutral"])
    total = prior[1] + h[1] + a[1]
    return (total + margin) / 2, (total - margin) / 2


def legal_scores(home, away, errors):
    scores = np.floor(np.array([home, away]) + errors + 0.5).astype(np.int32)
    ok = (scores >= 0).all(axis=1) & (scores[:, 0] != scores[:, 1])
    if not ok.any():
        raise ValueError("EMPTY_LEGAL_SUPPORT")
    return scores[ok]


def measure(obs, naive=False):
    e = np.asarray(
        [
            [
                r["actual_margin"] - r["margin" if not naive else "prior_margin"],
                r["actual_total"] - r["total" if not naive else "prior_total"],
                (r["p_home"] if not naive else r["prior_p_home"])
                - int(r["actual_margin"] > 0),
            ]
            for r in obs
        ]
    )
    return {
        "n": len(obs),
        "margin_bias_actual_minus_forecast": float(e[:, 0].mean()),
        "margin_mae": float(abs(e[:, 0]).mean()),
        "margin_rmse": float(np.sqrt(np.mean(e[:, 0] ** 2))),
        "total_mae": float(abs(e[:, 1]).mean()),
        "winner_brier": float(np.mean(e[:, 2] ** 2)),
    }


def fit(games):
    # Seasons are named by ending year. Warm the ratings on 2022-24, learn empirical residuals on 2025, test on 2026.
    warm = [g for g in games if g["season"] <= 2024]
    nonneutral = [g for g in warm if not g["neutral"]]
    if not nonneutral or not any(g["neutral"] for g in warm):
        raise ValueError("INSUFFICIENT_VENUE_TRAINING_SUPPORT")
    prior = (
        float(np.mean([g["hs"] - g["as"] for g in nonneutral])),
        float(np.mean([g["hs"] + g["as"] for g in warm])),
    )
    home_rates = {
        b: float(np.mean([g["hs"] > g["as"] for g in warm if g["neutral"] == b]))
        for b in (True, False)
    }
    state = defaultdict(lambda: np.zeros(3))
    previous = None
    bank = []
    cal = None
    test = []
    for day, grp in itertools.groupby(games, key=lambda g: g["day"]):
        batch = list(grp)
        season = batch[0]["season"]
        if season != previous:
            if previous is not None:
                for team in state.values():
                    team[:2] *= PARAMS["offseason_retention"]
            if season >= 2026 and cal is None:
                if len(bank) < 1000:
                    raise ValueError("INSUFFICIENT_CALIBRATION")
                cal = np.array(bank)
                cal = cal - cal.mean(axis=0)
            previous = season
        changes = []
        for g in batch:
            h, a = project(state, g, prior)
            hs, as_ = g["hs"], g["as"]
            if min(state[g["h"]][2], state[g["a"]][2]) >= PARAMS["min_prior_games"]:
                if season == 2025:
                    bank.append([hs - h, as_ - a])
                elif season == 2026:
                    scores = legal_scores(h, a, cal)
                    test.append(
                        dict(
                            id=g["id"],
                            day=day,
                            margin=h - a,
                            total=h + a,
                            p_home=float(np.mean(scores[:, 0] > scores[:, 1])),
                            actual_margin=hs - as_,
                            actual_total=hs + as_,
                            prior_margin=prior[0] * (not g["neutral"]),
                            prior_total=prior[1],
                            prior_p_home=home_rates[g["neutral"]],
                        )
                    )
            err_m = (hs - as_) - (h - a)
            err_t = (hs + as_) - (h + a)
            adj_m = PARAMS["margin_update"] * err_m
            adj_t = PARAMS["total_update"] * err_t
            changes.extend(
                [(g["h"], [adj_m, adj_t, 1.0]), (g["a"], [-adj_m, adj_t, 1.0])]
            )
        for k, v in changes:
            state[k] += v
    return state, prior, cal, test, previous


def pmf(vals):
    s, n = np.unique(vals, return_counts=True)
    return {"support": s.tolist(), "masses": (n / n.sum()).tolist()}


def admission(g, state, at):
    if g["issues"]:
        return g["issues"][0]
    if g["status"] != "STATUS_SCHEDULED" or ts(g["utc"]) <= at:
        return "NOT_SCHEDULED_PRE_START"
    if not g["d1"] or g["type"] not in (2, 3):
        return "OUTSIDE_VERIFIED_D1_PAIR"
    if min((int(state[k][2]) if k in state else 0) for k in (g["h"],g["a"])) < PARAMS["min_prior_games"]:
        return "INSUFFICIENT_TEAM_HISTORY"
    return None


def run_contract_checks(targets, state, prior, cutoff):
    """Exercise the actual model's input gates and point transform on a current eligible row."""
    game = next((g for g in targets if admission(g,state,cutoff) is None), None)
    if game is None:
        return {"status":"UNEVALUABLE_NO_ADMITTED_EVENT", "event_id":None}
    h, a = project(state,game,prior)
    if project(state,dict(game,hn="audit alias",an="audit alias",audit_url="annotation"),prior) != (h,a):
        raise ValueError("METADATA_CHANGED_POINT_LAW")
    swap = dict(game,h=game["a"],a=game["h"],neutral=True)
    nh,na = project(state,dict(game,neutral=True),prior)
    if project(state,swap,prior) != (na,nh):
        raise ValueError("TEAM_ORIENTATION_INVARIANCE")
    if admission(dict(game,h="missing"),state,cutoff) != "INSUFFICIENT_TEAM_HISTORY":
        raise ValueError("MISSING_HISTORY_BYPASS")
    try:
        project(state,dict(game,neutral=None),prior)
    except ValueError as exc:
        if str(exc) != "VENUE_UNRESOLVED":
            raise
    else:
        raise ValueError("UNKNOWN_VENUE_BYPASS")
    return {"status":"PASS","event_id":"CBB:"+game["id"],"probes":["metadata","orientation","unknown_venue","missing_history"]}


def issue(path, day, dest, previous_card=None, previous_sha=None):
    cutoff = now()
    dest.mkdir(parents=True, exist_ok=False)
    try:
        games, targets, manifest, hfiles = load(path, day, cutoff)
        state, prior, errors, test, last_season = fit(games)
        if errors is None or not test:
            raise ValueError("INSUFFICIENT_CALIBRATION_OR_EVALUATION")
        parent = None
        if previous_card is not None or previous_sha is not None:
            if previous_card is None or sha(previous_card.read_bytes()) != previous_sha:
                raise ValueError("PREVIOUS_CARD_HASH_REQUIRED")
            parent = json.loads(previous_card.read_bytes())
            missingness.verify(parent)
            if parent["date"] != day.isoformat() or ts(parent["generated_at_utc"]) > cutoff:
                raise ValueError("PREVIOUS_CARD_SCOPE")
    except (KeyError, ValueError, OSError, TypeError) as exc:
        write(dest / "missingness_failure.json", {"status":"BLOCKED", "reason":str(exc),
              "date":day.isoformat(), "scheduled":None, "generated_at_utc":now().isoformat(),
              "observation_state":"ACQUISITION_FAILURE" if isinstance(exc,OSError) else "UNRESOLVED_IDENTITY_OR_COVERAGE",
              "action_authority":False})
        raise
    if manifest["season"] != last_season:
        for team in state.values():
            team[:2] *= PARAMS["offseason_retention"]
    state_sha = digest({k: v.tolist() for k, v in sorted(state.items())})
    training_sha = digest([g for g in games if g["season"] <= 2025])
    cfg = {
        "model_id": MODEL,
        "parameters": PARAMS,
        "priors": prior,
        "historical_inputs_sha256": training_sha,
        "bank_sha256": sha(errors.astype("<f8").tobytes()),
        "bank_n": len(errors),
        "code_sha256": sha(Path(__file__).read_bytes()),
    }
    proc = digest(cfg)
    rows = []
    for g in targets:
        base = {k: g[k] for k in ("id", "h", "a", "hn", "an", "utc", "neutral", "d1")}
        row = {
            "event_id": "CBB:" + g["id"],
            "home_team": g["hn"],
            "away_team": g["an"],
            "start_time_utc": g["utc"],
            "source_status": g["status"],
            "forecast_status": "UNAVAILABLE",
            "action_authority": False,
            "qualification": "NO_PICK",
        }
        rows.append(row)
        reason = admission(g,state,now())
        if reason is not None:
            row["reason"] = reason
            continue
        base.update(
            home_state=state[g["h"]].tolist(),
            away_state=state[g["a"]].tolist(),
            state_sha256=state_sha,
        )
        h, a = project(state, g, prior)
        try:
            s = legal_scores(h, a, errors)
        except ValueError as exc:
            if str(exc) != "EMPTY_LEGAL_SUPPORT":
                raise
            row["reason"] = str(exc)
            continue
        seed = int(digest([MODEL, proc, g["id"], digest(base), N])[:16], 16)
        draws = np.random.Generator(np.random.PCG64(seed)).choice(len(s), N)
        pairs = s[draws].astype("<i4")
        drawfile = g["id"] + ".npz"
        np.savez_compressed(dest / drawfile, home=pairs[:, 0], away=pairs[:, 1])
        row.update(
            forecast_status="FORECAST_GENERATED",
            model_id=MODEL,
            model_state_config_hash=proc,
            input_snapshot_hash=digest(base),
            model_input_snapshot=base,
            projected_home_score=h,
            projected_away_score=a,
            home_margin=h - a,
            total=h + a,
            p_home_win=float(np.mean(s[:, 0] > s[:, 1])),
            p_home_win_sim=float(np.mean(pairs[:, 0] > pairs[:, 1])),
            distributions={
                "margin": pmf(s[:, 0] - s[:, 1]),
                "total": pmf(s.sum(axis=1)),
            },
            distribution_input_sha256=sha(s.astype("<i4").tobytes()),
            settlement=SETTLEMENT,
            simulation={
                "file": drawfile,
                "n": N,
                "seed": seed,
                "rng": "numpy.PCG64",
                "packed_pair_sha256": sha(pairs.tobytes()),
                "sha256": sha((dest / drawfile).read_bytes()),
            },
        )
    hist = {
        "evaluation": "RETROSPECTIVE_SEQUENTIAL_SEASON_ENDING_2026",
        "history_min_5_prior_games_each": True,
        "calibration_season_ending": 2025,
        "calibration_residual_pairs": len(errors),
        "train_score_environment_seasons": [2022, 2023, 2024],
        "evaluation_final_pairs_observed": sum(g["season"] == 2026 for g in games),
        "evaluation_no_prediction_reason": "fewer than five prior verified games for at least one team",
        "benchmark": "Training-period mean margin (zero on neutral), mean total and observed home-win frequencies by venue class",
        "scope": "Reconstructed historical chronological diagnostics. No validation registry entry or market comparison.",
        "retrospective_label_timing": "Update after the earlier local game date; historical first-publication times unverified.",
        "model": measure(test),
        "no_team_rating_prior": measure(test, True),
        "historical_season_files": hfiles,
        "promotion": "NONE",
    }
    write(dest / "historical_check.json", hist)
    with (dest / "historical_rows.csv").open("x", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(test[0]))
        w.writeheader()
        w.writerows(test)
    generated = now()
    for i,row in enumerate(rows):
        if row["forecast_status"] == "FORECAST_GENERATED" and ts(row["start_time_utc"]) <= generated:
            # Draws are local scratch until this new edition is sealed.
            (dest / row["simulation"]["file"]).unlink()
            rows[i] = {key:row[key] for key in ("event_id","home_team","away_team","start_time_utc",
                                                 "source_status","action_authority","qualification")}
            rows[i].update(forecast_status="UNAVAILABLE",reason="NOT_SCHEDULED_PRE_START")
    result = {
        "schema": "sports.cbb.shadow_card.v2",
        "previous_card_sha256": previous_sha,
        "missingness_runtime_checks": run_contract_checks(targets,state,prior,cutoff),
        "missingness_historical_support": missingness.historical_support(games, PARAMS["min_prior_games"]),
        "schedule_scope": "CAPTURED_ESPN_SLATE" if rows else "EMPTY_ESPN_WINDOW_REQUIRES_INDEPENDENT_SCOPE_VERIFICATION",
        "date": day.isoformat(),
        "as_of_utc": cutoff.isoformat(),
        "generated_at_utc": generated.isoformat(),
        "timezone": PACIFIC.key,
        "league": "CBB",
        "model": cfg,
        "state_sha256": state_sha,
        "history_finals_used": len(games),
        "history_finals_by_season": dict(
            sorted(Counter(g["season"] for g in games).items())
        ),
        "current_season_finals_by_pacific_day": dict(
            sorted(
                Counter(
                    g["day"] for g in games if g["season"] == manifest["season"]
                ).items()
            )
        ),
        "latest_consumed_start_utc": max(g["utc"] for g in games),
        "history_games_sha256": digest(games),
        "input_manifest_sha256": sha((path / "manifest.json").read_bytes()),
        "market_input": False,
        "action_authority": False,
        "canonical_registration": False,
        "official_release_eligible": False,
        "scope": "Men’s D-I teams with verified ESPN D-I conference affiliation; other scheduled opponents retained as coverage exclusions.",
        "limitations": [
            "No lineup, player, transfer or injury adjustment.",
            "No benchmark against authentic closing spreads/prices in this evaluation.",
            "Recent roster changes only reflected through earlier team outcomes.",
            "Paired final-score residual law conditioned on nonnegative scores and no final tie.",
            "No historical prospective receipt and no odds consumed.",
        ],
        "scheduled": len(rows),
        "forecast_count": sum(
            r["forecast_status"] == "FORECAST_GENERATED" for r in rows
        ),
        "forecasts": rows,
    }
    missingness.attach(result,targets,state,PARAMS["min_prior_games"],parent)
    missingness.verify(result)
    write(dest / "card.json", result)
    missingness.verify(json.loads((dest / "card.json").read_bytes()))
    print(
        json.dumps(
            {
                "date": result["date"],
                "scheduled": len(rows),
                "forecast_count": result["forecast_count"],
                "card_sha256": sha((dest / "card.json").read_bytes()),
                "historical": hist["model"],
            }
        )
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["capture", "card"])
    ap.add_argument("--date", type=date.fromisoformat, required=True)
    ap.add_argument("--inputs", type=Path, required=True)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--previous-card", type=Path, help="Earlier v2 edition of this same slate")
    ap.add_argument("--previous-sha256", help="Independently recorded predecessor card digest")
    args = ap.parse_args()
    if args.command == "capture":
        try:
            capture(args.date, args.inputs)
        except (OSError, KeyError, ValueError) as exc:
            if args.inputs.is_dir() and not isinstance(exc, FileExistsError):
                write(args.inputs / "capture_failure.json", {"status":"BLOCKED", "date":args.date.isoformat(),
                      "scheduled":None, "action_authority":False, "observation_state":"ACQUISITION_FAILURE",
                      "failed_at_utc":now().isoformat(), "reason":str(exc)})
            raise
    elif args.output:
        issue(args.inputs, args.date, args.output,args.previous_card,args.previous_sha256)
    else:
        ap.error("--output required for card")
