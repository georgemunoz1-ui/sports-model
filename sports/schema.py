"""
Canonical, SPORT-AGNOSTIC game record + normalization/verification.
One schema for MLB / NFL / NBA / WNBA / CFB so every downstream model, backtest, and
calibration tool reads the same columns regardless of sport. Sport-specific pre-game
inputs live in `features_json` (a nested dict) so the flat schema never changes.
"""
import json, csv, os

# Canonical columns — DO NOT reorder (downstream code reads by name, but CSV header is fixed here)
COLUMNS = [
    "sport",          # "mlb" | "nfl" | "nba" | "wnba" | "cfb"
    "season",         # int, e.g. 2026
    "game_id",        # canonical id, sport-prefixed e.g. "mlb:2026:824766"
    "date",           # ISO date "YYYY-MM-DD" (local game date)
    "status",         # "final" | "postponed" | "suspended" | "scheduled"
    "away", "home",   # canonical team abbreviations
    "away_score", "home_score",
    "home_win",       # 1 if home_score>away_score, 0 if <, "" if tie/void
    "margin",         # home_score - away_score  ("" if no result)
    "total",          # away_score + home_score  ("" if no result)
    "neutral_site",   # 1/0
    "venue",
    # closing market (nullable — enriched separately; never used as a prediction input, only price/eval)
    "close_ml_away", "close_ml_home", "close_spread_home", "close_total",
    # sport-specific pre-game features as JSON (nullable — the enrichment layer fills this)
    "features_json",
    "source", "ingested_utc",
]

def make_row(sport, season, game_id, date, status, away, home,
             away_score=None, home_score=None, neutral_site=0, venue="",
             close=None, features=None, source="", ingested_utc=""):
    """Build one canonical row (dict). Computes home_win/margin/total when scores present."""
    hw = margin = total = ""
    if away_score is not None and home_score is not None and str(status).lower() == "final":
        a, h = int(away_score), int(home_score)
        margin = h - a; total = a + h
        hw = 1 if h > a else (0 if h < a else "")
    close = close or {}
    return {
        "sport": sport, "season": season, "game_id": game_id, "date": date, "status": status,
        "away": away, "home": home,
        "away_score": away_score if away_score is not None else "",
        "home_score": home_score if home_score is not None else "",
        "home_win": hw, "margin": margin, "total": total,
        "neutral_site": int(neutral_site), "venue": venue or "",
        "close_ml_away": close.get("ml_away", ""), "close_ml_home": close.get("ml_home", ""),
        "close_spread_home": close.get("spread_home", ""), "close_total": close.get("total", ""),
        "features_json": json.dumps(features) if features else "",
        "source": source, "ingested_utc": ingested_utc,
    }

def append_rows(path, rows):
    """Idempotent append: writes header once; de-dupes on game_id against existing file."""
    existing = set()
    if os.path.exists(path):
        with open(path) as f:
            for r in csv.DictReader(f):
                existing.add(r["game_id"])
    new = [r for r in rows if r["game_id"] not in existing]
    write_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if write_header: w.writeheader()
        for r in new: w.writerow(r)
    return len(new), len(rows) - len(new)  # (added, skipped_dupes)

def verify_file(path):
    """Basic integrity: row count, finals, ties, dupes, date span."""
    rows = list(csv.DictReader(open(path))) if os.path.exists(path) else []
    ids = [r["game_id"] for r in rows]
    finals = [r for r in rows if r["status"] == "final"]
    return {
        "rows": len(rows), "finals": len(finals),
        "dupe_ids": len(ids) - len(set(ids)),
        "date_min": min((r["date"] for r in rows), default=None),
        "date_max": max((r["date"] for r in rows), default=None),
        "postponed": sum(1 for r in rows if r["status"] == "postponed"),
    }
