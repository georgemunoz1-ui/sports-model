# Multi-Sport Backfill & Feature Store

Sport-agnostic labeled-game dataset powering training, backtesting, and calibration for every
sport. One schema (`schema.py::COLUMNS`), one registry (`registry.py::SPORTS`), pluggable per-sport.

## Layout
    data/backfill/manifest.json        progress tracker (resumable — skip done windows)
    data/backfill/{sport}/{season}/results.csv    canonical labeled games
    sports/schema.py                   canonical row + append/verify (idempotent, de-duped)
    sports/registry.py                 endpoints, windows, season bounds, park factors per sport

## Two-phase design (efficiency)
1. RESULTS first — schedule+scores+venue from the reliable endpoints (MLB StatsAPI; ESPN for the
   rest). Cheap, fast, gives outcome labels (home_win/margin/total) for all games immediately.
2. FEATURE enrichment second — pluggable, per-game, fills `features_json` (SP rates as-of-date,
   team form, rest, weather...). Never blocks phase 1. No look-ahead: features must be as-of the
   pre-game state.

## Fetch discipline (learned from rate-limit failures)
- WebFetch only (python http is proxy-blocked here). Small windows (registry `window_days`) to beat
  the summarizer truncation. Throttle; on 429/403 wait 60-90s, retry ONCE, then log-gap + continue —
  never spin. Write-as-you-go so a killed run resumes from the manifest.
- Verify every window: extracted rows vs the date's totalGames; cross-check vs known finals.

## Adding a sport
Add an entry to `registry.SPORTS` (endpoints, window, season, parks) + a one-line normalizer note.
NFL/NBA/WNBA/CFB entries are already stubbed with verified ESPN endpoints — populate when in season.
