#!/usr/bin/env python3
"""Fail-closed validation for source-specific NFL preseason line captures."""

from __future__ import annotations

MODULE_ID = "nfl_preseason_line_guard"

import argparse
import datetime as dt
import json
import math
from collections import Counter
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
DEFAULT_CAPTURE = (
    BASE / "data/nfl/odds/2026-08-14_preseason_current_20260814T223227Z.json"
)
FORBIDDEN_KEYS = {
    "average",
    "best_price",
    "consensus_probability",
    "de_vig",
    "devig",
    "edge",
    "ev",
    "implied_probability",
    "model_probability",
}


class LineCaptureError(ValueError):
    """The capture cannot be treated as a valid preseason market snapshot."""


def _utc(value: object, field: str) -> dt.datetime:
    if not isinstance(value, str):
        raise LineCaptureError(f"{field} must be an ISO-8601 string")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LineCaptureError(f"{field} is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LineCaptureError(f"{field} lacks a UTC offset")
    return parsed.astimezone(dt.timezone.utc)


def _walk_keys(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).lower()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _finite_or_none(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise LineCaptureError(f"{field} cannot be boolean")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise LineCaptureError(f"{field} must be numeric or null") from exc
    if not math.isfinite(number):
        raise LineCaptureError(f"{field} must be finite")
    return number


def _favorite_from_quote(quote: dict, away: str, home: str) -> str | None:
    away_spread = _finite_or_none(quote.get("away_spread"), "away_spread")
    home_spread = _finite_or_none(quote.get("home_spread"), "home_spread")
    if away_spread is not None and away_spread != 0:
        return away if away_spread < 0 else home
    if home_spread is not None and home_spread != 0:
        return home if home_spread < 0 else away
    away_ml = _finite_or_none(quote.get("away_moneyline"), "away_moneyline")
    home_ml = _finite_or_none(quote.get("home_moneyline"), "home_moneyline")
    if away_ml is not None and home_ml is not None and away_ml != home_ml:
        return away if away_ml < home_ml else home
    return None


def validate_capture(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("sport") != "NFL" or data.get("season_phase") != "PRESEASON":
        raise LineCaptureError("route scope must be NFL PRESEASON")
    if data.get("capture_kind") != "CURRENT_LINES":
        raise LineCaptureError("capture_kind must be CURRENT_LINES")
    if data.get("target_window") != "RECOVERY_T_MINUS_30":
        raise LineCaptureError("this artifact must retain its recovery-window identity")
    if data.get("backfills_missed_window") is not False:
        raise LineCaptureError("a late recovery capture cannot backfill T-minus-90")
    if data.get("grade_scope") != "MARKET_BENCHMARK_ONLY":
        raise LineCaptureError("preseason line rows must stay MARKET_BENCHMARK_ONLY")
    if data.get("promotion_eligible") is not False:
        raise LineCaptureError("market benchmark cannot be promotion eligible")
    if data.get("wager_authority") != "NO" or data.get("stake") != "$0":
        raise LineCaptureError("wager authority or stake drifted")
    if data.get("provenance", {}).get("raw_source_bytes_on_disk") is not False:
        raise LineCaptureError("recovery provenance no longer matches the captured evidence")

    forbidden = sorted(set(_walk_keys(data)) & FORBIDDEN_KEYS)
    if forbidden:
        raise LineCaptureError(f"forbidden derived market/model fields present: {forbidden}")

    captured = _utc(data.get("captured_at_utc"), "captured_at_utc")
    games = data.get("games")
    if not isinstance(games, list) or len(games) != 3:
        raise LineCaptureError("August 14 recovery slate must contain exactly three games")
    seen: set[str] = set()
    expected = {"401873276", "401873277", "401873278"}
    for game in games:
        game_id = str(game.get("game_id"))
        if game_id in seen:
            raise LineCaptureError(f"duplicate game_id {game_id}")
        seen.add(game_id)
        kickoff = _utc(game.get("game_start_utc"), f"{game_id}.game_start_utc")
        if captured >= kickoff:
            raise LineCaptureError(f"{game_id}: capture is not pregame")
        if game.get("model_forecast") is not None:
            raise LineCaptureError(f"{game_id}: unauthorized preseason model forecast")
        if game.get("forecast_status") != "NO_INDEPENDENT_PRESEASON_MODEL":
            raise LineCaptureError(f"{game_id}: preseason model status drifted")

        away = str(game.get("away_team"))
        home = str(game.get("home_team"))
        quotes = game.get("source_quotes")
        if not isinstance(quotes, list) or len(quotes) < 2:
            raise LineCaptureError(f"{game_id}: fewer than two source-specific quotes")
        favorites: list[str] = []
        quote_ids: set[str] = set()
        for quote in quotes:
            quote_id = str(quote.get("quote_id"))
            if not quote_id or quote_id in quote_ids:
                raise LineCaptureError(f"{game_id}: missing or duplicate quote_id")
            quote_ids.add(quote_id)
            if quote.get("quote_scope") != "SOURCE_SPECIFIC":
                raise LineCaptureError(f"{quote_id}: quote is not source-specific")
            source_url = quote.get("source_url")
            if not isinstance(source_url, str) or not source_url.startswith("https://"):
                raise LineCaptureError(f"{quote_id}: missing source URL")
            accessed = _utc(quote.get("accessed_at_utc"), f"{quote_id}.accessed_at_utc")
            if accessed >= kickoff:
                raise LineCaptureError(f"{quote_id}: quote was not captured pregame")
            favorite = _favorite_from_quote(quote, away, home)
            if favorite is not None:
                favorites.append(favorite)
        counts = Counter(favorites)
        declared = game.get("current_favorite")
        if counts.get(str(declared), 0) < 2:
            raise LineCaptureError(
                f"{game_id}: current favorite lacks two-source agreement: {dict(counts)}"
            )
        if any(team != declared for team in counts):
            raise LineCaptureError(
                f"{game_id}: simultaneous current favorite-sign conflict remains: {dict(counts)}"
            )

        personnel = game.get("pregame_personnel")
        if not isinstance(personnel, dict) or not personnel.get("facts"):
            raise LineCaptureError(f"{game_id}: pregame personnel evidence is missing")
        for fact in personnel["facts"]:
            fact_capture = _utc(
                fact.get("captured_at_utc"), f"{game_id}.personnel.captured_at_utc"
            )
            if fact_capture >= kickoff:
                raise LineCaptureError(f"{game_id}: personnel fact is not pregame")
            if not fact.get("source_url") or not fact.get("fact"):
                raise LineCaptureError(f"{game_id}: personnel fact lacks evidence")

    if seen != expected:
        raise LineCaptureError(f"wrong August 14 game inventory: {sorted(seen)}")
    return {
        "capture_id": data["capture_id"],
        "games": len(games),
        "quotes": sum(len(game["source_quotes"]) for game in games),
        "status": "PASS",
    }


def selftest() -> int:
    result = validate_capture(DEFAULT_CAPTURE)
    print(
        "nfl_preseason_line_guard: PASS "
        f"({result['games']} games, {result['quotes']} source-specific quotes, "
        "pregame personnel bound, no derived market/model fields)"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    path = args.path if args.path.is_absolute() else BASE / args.path
    result = validate_capture(path)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
