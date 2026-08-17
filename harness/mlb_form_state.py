#!/usr/bin/env python3
"""Build a leakage-safe MLB team-form state from canonical results and Tier-1 captures.

The live card historically read every final in results.csv, including dates at or after the
requested slate, and a max-date freshness check could miss an interior hole.  This module makes
the contract explicit:

* only games with game_date < target_date enter form;
* the newest valid result-capture ledger for a date may extend results.csv;
* a conflicting canonical/capture final blocks instead of silently overwriting;
* D-1 must be present and the trailing 14-day calendar may not contain an interior hole.

The result-capture overlay lets a verified board update tomorrow's card without pretending that
an older results.csv has already been rewritten.  It does not grade forecasts or alter a model.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import hashlib
import json
import tempfile
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
RESULTS = BASE / "data/backfill/mlb/2026/results.csv"
CAPTURE_ROOT = BASE / "data/result_capture/mlb"

TEAM_ALIASES = {
    "Arizona Diamondbacks": "AZ", "ARI": "AZ", "AZ": "AZ",
    "Atlanta Braves": "ATL", "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC", "Chicago White Sox": "CWS", "CHW": "CWS",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE", "Colorado Rockies": "COL",
    "Detroit Tigers": "DET", "Houston Astros": "HOU", "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD", "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY", "Athletics": "ATH", "OAK": "ATH", "ATH": "ATH",
    "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD",
    "San Francisco Giants": "SF", "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB", "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}


class FormStateError(ValueError):
    pass


def normalize_team(value: str) -> str:
    value = str(value or "").strip()
    return TEAM_ALIASES.get(value, value)


def _date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise FormStateError(f"invalid ISO date {value!r}") from exc


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BASE))
    except ValueError:
        return str(path)


def validate_official_board(path: Path) -> tuple[dict, list[str]]:
    doc = json.loads(Path(path).read_text())
    errors, seen = [], set()
    games = []
    for date_doc in doc.get("dates", []):
        game_date = date_doc.get("date")
        date_games = date_doc.get("games", [])
        if date_doc.get("expected_game_count") != len(date_games):
            errors.append(f"{game_date}: expected count does not match game rows")
        for game in date_games:
            games.append(game)
            if game.get("game_id") in seen:
                errors.append(f"duplicate game_id {game.get('game_id')}")
            seen.add(game.get("game_id"))
            if not str(game.get("status", "")).startswith("FINAL"):
                errors.append(f"{game.get('game_id')}: non-final status")
            if game.get("away") == game.get("home"):
                errors.append(f"{game.get('game_id')}: self matchup")
            if game.get("away_score") == game.get("home_score"):
                errors.append(f"{game.get('game_id')}: tied MLB final")
            away_sum = sum(value for value in game.get("away_innings", []) if value is not None)
            home_sum = sum(value for value in game.get("home_innings", []) if value is not None)
            if (away_sum, home_sum) != (game.get("away_score"), game.get("home_score")):
                errors.append(f"{game.get('game_id')}: linescore sum mismatch")
            if f"/{game_date.replace('-', '/')}/" not in str(game.get("source_url", "")):
                errors.append(f"{game.get('game_id')}: source URL date mismatch")
    validation = doc.get("validation", {})
    if validation.get("expected_games") != len(games):
        errors.append("board validation.expected_games does not match rows")
    if validation.get("final_games") != len(games):
        errors.append("board validation.final_games does not match rows")
    if doc.get("source_tier") != 1 or doc.get("source_family") != "MLB_OFFICIAL":
        errors.append("board is not labeled MLB_OFFICIAL Tier-1")
    scope = doc.get("scope", {})
    if scope.get("required_base_cutoff_game_date") != (
        _date(scope.get("start_date")) - dt.timedelta(days=1)
    ).isoformat():
        errors.append("scope.required_base_cutoff_game_date must be the day before start_date")
    if not isinstance(scope.get("required_base_final_count"), int) or scope["required_base_final_count"] < 1:
        errors.append("scope.required_base_final_count must be a positive integer")
    if scope.get("model_predictions_present") is not False:
        errors.append("official form board must not contain model predictions")
    if scope.get("forecast_card_registered_for_capture_dates") is not False:
        errors.append("form-board capture dates must be labeled as having no registered card")
    if scope.get("backtestable") is not False:
        errors.append("form-board results must be explicitly non-backtestable")
    if scope.get("disposition") != "RESULT_BACKFILL_ONLY_NOT_BACKTESTABLE":
        errors.append("form-board disposition must block retrospective grading")
    return doc, errors


def materialize_board(path: Path, output_root: Path = CAPTURE_ROOT) -> list[Path]:
    path = Path(path)
    doc, errors = validate_official_board(path)
    if errors:
        raise FormStateError("; ".join(errors))
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    evidence_rel = str(path.resolve().relative_to(BASE))
    evidence_sha = sha256_file(path)
    captured = doc["captured_at_utc"]
    stamp = captured.replace("-", "").replace(":", "")
    written = []
    for date_doc in doc["dates"]:
        game_date = date_doc["date"]
        out = output_root / f"{game_date}_{stamp}.json"
        prior = []
        for candidate in sorted(output_root.glob(f"{game_date}*.json")):
            if candidate.resolve() == out.resolve():
                continue
            try:
                prior_doc = json.loads(candidate.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            rank = (prior_doc.get("ledger_recorded_at_utc") or "", str(candidate))
            prior.append((rank, candidate))
        ledger = {
            "schema": "result_capture_ledger.v1",
            "sport": "MLB",
            "date": game_date,
            "ledger_recorded_at_utc": captured,
            "schedule_authority": doc["source_urls"][doc["dates"].index(date_doc)],
            "expected_game_count": date_doc["expected_game_count"],
            "evidence_path": evidence_rel,
            "evidence_sha256": evidence_sha,
            "forecast_card_registered": False,
            "backtestable": False,
            "disposition": "RESULT_BACKFILL_ONLY_NOT_BACKTESTABLE",
            "games": [],
        }
        if prior:
            ledger["supersedes"] = str(max(prior)[1].resolve().relative_to(BASE))
        for game in date_doc["games"]:
            ledger["games"].append({
                "game_id": str(game["gamePk"]),
                "away": game["away"],
                "home": game["home"],
                "state": "FINAL",
                "backtestable": False,
                "disposition": "RESULT_BACKFILL_ONLY_NOT_BACKTESTABLE",
                "observations": [{
                    "status": "ACCEPTED_FINAL",
                    "observed_at_utc": captured,
                    "source_tier": 1,
                    "source_family": "MLB_OFFICIAL",
                    "source_game_date": game_date,
                    "away_score": game["away_score"],
                    "home_score": game["home_score"],
                    "source_url": game["source_url"],
                    "evidence_path": evidence_rel,
                    "evidence_sha256": evidence_sha,
                    "linescore_sum_pass": True,
                    "backtestable": False,
                    "disposition": "RESULT_BACKFILL_ONLY_NOT_BACKTESTABLE",
                }],
            })
        out.write_text(json.dumps(ledger, indent=2) + "\n")
        written.append(out)
    return written


def apply_board_to_results(path: Path, results_path: Path = RESULTS) -> dict:
    """Append a validated form board only when the canonical base reaches the prior date."""
    path, results_path = Path(path), Path(results_path)
    doc, errors = validate_official_board(path)
    if errors:
        raise FormStateError("; ".join(errors))
    board_dates = [date_doc["date"] for date_doc in doc["dates"]]
    if board_dates != sorted(board_dates) or len(board_dates) != len(set(board_dates)):
        raise FormStateError("board dates must be unique and sorted")
    for left, right in zip(board_dates, board_dates[1:]):
        if _date(right) - _date(left) != dt.timedelta(days=1):
            raise FormStateError(f"non-contiguous board dates: {left}, {right}")

    with results_path.open() as handle:
        reader = csv.DictReader(handle)
        existing = list(reader)
        fieldnames = list(reader.fieldnames or [])
    required = {
        "sport", "season", "game_id", "date", "status", "away", "home",
        "away_score", "home_score", "home_win", "margin", "total", "neutral_site",
        "venue", "source", "ingested_utc", "source_tier", "result_status",
        "evidence_path", "evidence_sha256",
    }
    missing_columns = sorted(required - set(fieldnames))
    if missing_columns:
        raise FormStateError("results file lacks required columns: " + ", ".join(missing_columns))

    start = _date(board_dates[0])
    base_d1 = (start - dt.timedelta(days=1)).isoformat()
    base_dates = {row["date"] for row in existing
                  if row.get("status") == "final" and row.get("total") not in (None, "")
                  and row.get("date", "") < board_dates[0]}
    if base_d1 not in base_dates:
        raise FormStateError(
            f"canonical base stops before {base_d1}; refusing a later-date append that would hide the gap"
        )
    scope = doc["scope"]
    if scope["required_base_cutoff_game_date"] != base_d1:
        raise FormStateError("board base-cutoff contract does not match its start date")
    base_d1_count = sum(
        1 for row in existing
        if row.get("status") == "final" and row.get("total") not in (None, "")
        and row.get("date") == base_d1
    )
    if base_d1_count != scope["required_base_final_count"]:
        raise FormStateError(
            f"canonical {base_d1} coverage is {base_d1_count}/{scope['required_base_final_count']} finals"
        )
    base_window = [(start - dt.timedelta(days=days)).isoformat() for days in range(1, 15)]
    base_present = [value for value in base_window if value in base_dates]
    base_holes = sorted(value for value in base_window if value not in base_dates
                        and any(other < value for other in base_present)
                        and any(other > value for other in base_present))
    if base_holes:
        raise FormStateError("canonical base has interior result-date holes: " + ", ".join(base_holes))

    by_id = {row["game_id"]: row for row in existing}
    by_matchup = {(row.get("date"), normalize_team(row.get("away")), normalize_team(row.get("home"))): row
                  for row in existing}
    evidence_rel = display_path(path)
    evidence_sha = sha256_file(path)
    additions = []
    for date_doc in doc["dates"]:
        for game in date_doc["games"]:
            matchup = (date_doc["date"], game["away"], game["home"])
            prior = by_id.get(game["game_id"]) or by_matchup.get(matchup)
            score = (str(game["away_score"]), str(game["home_score"]))
            if prior:
                prior_score = (prior.get("away_score"), prior.get("home_score"))
                if prior_score != score:
                    raise FormStateError(
                        f"existing result conflicts with board for {date_doc['date']} "
                        f"{game['away']}@{game['home']}: {prior_score} vs {score}"
                    )
                continue
            away_score, home_score = game["away_score"], game["home_score"]
            row = {name: "" for name in fieldnames}
            row.update({
                "sport": "mlb", "season": "2026", "game_id": game["game_id"],
                "date": date_doc["date"], "status": "final",
                "away": game["away"], "home": game["home"],
                "away_score": str(away_score), "home_score": str(home_score),
                "home_win": "1" if home_score > away_score else "0",
                "margin": str(home_score - away_score), "total": str(home_score + away_score),
                "neutral_site": "0", "venue": "",
                "source": "mlb.com/scores direct official form board",
                "ingested_utc": doc["captured_at_utc"], "source_tier": "1",
                "result_status": "FINAL", "evidence_path": evidence_rel,
                "evidence_sha256": evidence_sha,
            })
            additions.append(row)
    if additions:
        with results_path.open("a", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writerows(additions)
    return {
        "evidence_path": evidence_rel,
        "evidence_sha256": evidence_sha,
        "base_complete_through": base_d1,
        "board_dates": board_dates,
        "added": len(additions),
        "already_present": sum(len(day["games"]) for day in doc["dates"]) - len(additions),
    }


def _canonical_rows(path: Path, target_date: str) -> list[dict]:
    rows = []
    with path.open() as handle:
        for raw in csv.DictReader(handle):
            if raw.get("status") != "final" or raw.get("total") in (None, ""):
                continue
            if raw.get("date", "") >= target_date:
                continue
            rows.append({
                "game_id": raw["game_id"],
                "date": raw["date"],
                "away": normalize_team(raw["away"]),
                "home": normalize_team(raw["home"]),
                "away_score": int(raw["away_score"]),
                "home_score": int(raw["home_score"]),
                "venue": raw.get("venue") or "",
                "source": "results_csv",
            })
    return rows


def _newest_ledgers(root: Path) -> dict[str, tuple[tuple[str, str], dict, Path]]:
    newest = {}
    for name in sorted(glob.glob(str(root / "*.json"))):
        path = Path(name)
        try:
            doc = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if doc.get("sport") != "MLB" or not doc.get("date") or not isinstance(doc.get("games"), list):
            continue
        rank = (doc.get("ledger_recorded_at_utc") or "", str(path))
        if doc["date"] not in newest or rank > newest[doc["date"]][0]:
            newest[doc["date"]] = (rank, doc, path)
    return newest


def _capture_rows(root: Path, target_date: str) -> tuple[list[dict], list[str]]:
    rows, ledger_paths = [], []
    for game_date, (_, doc, path) in sorted(_newest_ledgers(root).items()):
        if game_date >= target_date:
            continue
        expected = doc.get("expected_game_count")
        games = doc.get("games", [])
        if expected != len(games):
            raise FormStateError(f"{path}: expected_game_count={expected} but has {len(games)} games")
        accepted_for_date = []
        for game in games:
            if game.get("state") != "FINAL":
                continue
            accepted = [obs for obs in game.get("observations", [])
                        if obs.get("status") == "ACCEPTED_FINAL"]
            if len(accepted) != 1:
                raise FormStateError(f"{path}: {game.get('game_id')} FINAL lacks one accepted observation")
            obs = accepted[0]
            if obs.get("source_tier") != 1 or obs.get("source_game_date") != game_date:
                raise FormStateError(f"{path}: {game.get('game_id')} is not date-consistent Tier-1")
            if obs.get("away_score") is None or obs.get("home_score") is None:
                raise FormStateError(f"{path}: {game.get('game_id')} FINAL lacks a score")
            accepted_for_date.append({
                "game_id": str(game["game_id"]),
                "date": game_date,
                "away": normalize_team(game["away"]),
                "home": normalize_team(game["home"]),
                "away_score": int(obs["away_score"]),
                "home_score": int(obs["home_score"]),
                "venue": game.get("venue") or "",
                "source": display_path(path),
            })
        if accepted_for_date:
            if len(accepted_for_date) != expected:
                raise FormStateError(
                    f"{path}: only {len(accepted_for_date)}/{expected} games are Tier-1 FINAL"
                )
            rows.extend(accepted_for_date)
            ledger_paths.append(display_path(path))
    return rows, ledger_paths


def load_complete_form(
    target_date: str,
    *,
    results_path: Path = RESULTS,
    capture_root: Path = CAPTURE_ROOT,
    trailing_days: int = 14,
) -> tuple[list[dict], dict]:
    target = _date(target_date)
    canonical = _canonical_rows(Path(results_path), target_date)
    captures, ledger_paths = _capture_rows(Path(capture_root), target_date)

    merged = {(row["date"], row["away"], row["home"]): row for row in canonical}
    overlay_count = 0
    for row in captures:
        key = (row["date"], row["away"], row["home"])
        prior = merged.get(key)
        if prior:
            old_score = (prior["away_score"], prior["home_score"])
            new_score = (row["away_score"], row["home_score"])
            if old_score != new_score:
                raise FormStateError(
                    f"conflicting Tier-1 final for {row['date']} {row['away']}@{row['home']}: "
                    f"results.csv={old_score}, capture={new_score}"
                )
            continue
        merged[key] = row
        overlay_count += 1

    rows = sorted(merged.values(), key=lambda row: (row["date"], row["game_id"]))
    dates = {row["date"] for row in rows}
    d1 = (target - dt.timedelta(days=1)).isoformat()
    window = [(target - dt.timedelta(days=days)).isoformat()
              for days in range(1, trailing_days + 1)]
    present = [value for value in window if value in dates]
    holes = sorted(value for value in window if value not in dates
                   and any(other < value for other in present)
                   and any(other > value for other in present))
    if d1 not in dates:
        raise FormStateError(f"D-1 final state missing: required {d1}")
    if holes:
        raise FormStateError("interior result-date holes in trailing form window: " + ", ".join(holes))

    metadata = {
        "target_date": target_date,
        "time_rule": f"strict game_date < {target_date}",
        "state_cutoff_game_date": max(dates),
        "required_d1": d1,
        "trailing_days_checked": trailing_days,
        "interior_holes": holes,
        "canonical_final_rows": len(canonical),
        "tier1_capture_overlay_rows": overlay_count,
        "tier1_capture_ledgers": ledger_paths,
        "form_rows": len(rows),
        "status": "CURRENT_COMPLETE",
    }
    return rows, metadata


def selftest() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        results = root / "results.csv"
        results.write_text(
            "status,total,date,game_id,away,home,away_score,home_score,venue\n"
            "final,7,2026-08-14,g14,A,B,4,3,V\n"
            "final,9,2026-08-18,future,A,B,5,4,V\n"
        )
        captures = root / "captures"
        captures.mkdir()
        for date_value, game_id, away, home, away_score, home_score in (
            ("2026-08-15", "g15", "C", "D", 2, 1),
            ("2026-08-16", "g16", "E", "F", 6, 5),
        ):
            doc = {
                "sport": "MLB", "date": date_value,
                "ledger_recorded_at_utc": date_value + "T23:59:00Z",
                "expected_game_count": 1,
                "games": [{
                    "game_id": game_id, "away": away, "home": home, "state": "FINAL",
                    "observations": [{
                        "status": "ACCEPTED_FINAL", "source_tier": 1,
                        "source_game_date": date_value,
                        "away_score": away_score, "home_score": home_score,
                    }],
                }],
            }
            (captures / f"{date_value}.json").write_text(json.dumps(doc))
        try:
            rows, meta = load_complete_form(
                "2026-08-17", results_path=results, capture_root=captures, trailing_days=3
            )
            if len(rows) != 3 or any(row["date"] >= "2026-08-17" for row in rows):
                failures.append("strict pre-slate merge failed")
            if meta["state_cutoff_game_date"] != "2026-08-16" or meta["tier1_capture_overlay_rows"] != 2:
                failures.append("capture overlay metadata failed")
        except FormStateError as exc:
            failures.append(f"valid complete state rejected: {exc}")

        (captures / "2026-08-15.json").unlink()
        try:
            load_complete_form("2026-08-17", results_path=results, capture_root=captures, trailing_days=3)
            failures.append("interior 8/15 hole was accepted")
        except FormStateError as exc:
            if "interior" not in str(exc):
                failures.append(f"wrong missing-date failure: {exc}")

    if failures:
        print("mlb_form_state selftest: FAIL")
        for failure in failures:
            print("  " + failure)
        return 1
    print("mlb_form_state selftest: PASS (Tier-1 overlay, strict pre-slate cutoff, D-1 and interior-hole gates)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-date")
    parser.add_argument("--validate-evidence")
    parser.add_argument("--materialize-evidence")
    parser.add_argument("--apply-evidence")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.validate_evidence:
        _, errors = validate_official_board(Path(args.validate_evidence))
        if errors:
            for error in errors:
                print("FAIL " + error)
            return 1
        print("MLB official form board: PASS")
        return 0
    if args.materialize_evidence:
        try:
            paths = materialize_board(Path(args.materialize_evidence))
        except (FormStateError, OSError, json.JSONDecodeError) as exc:
            print(f"MLB official form board: FAIL ({exc})")
            return 1
        for path in paths:
            print(path.relative_to(BASE))
        return 0
    if args.apply_evidence:
        try:
            result = apply_board_to_results(Path(args.apply_evidence))
        except (FormStateError, OSError, json.JSONDecodeError) as exc:
            print(f"MLB official form board apply: DATA_BLOCKED ({exc})")
            return 1
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if not args.target_date:
        parser.error("--target-date is required")
    try:
        _, metadata = load_complete_form(args.target_date)
    except FormStateError as exc:
        print(f"DATA_BLOCKED_FORM_STATE: {exc}")
        return 1
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
