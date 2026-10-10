# NHL 2026-27 acquisition scope

The NHL provider labels 2026-27 as season 2027. Use the reviewed v2 scope explicitly for both capture and preparation; the legacy all-league commands retain their previous scope and must not be used for this rollover. This is an acquisition repair for `nhl.initial_causal_score.research.v1`, not a new accuracy default, model-method change, or live wagering authorization.

```sh
python scripts/capture_team_histories.py \
  --league nhl \
  --season-scope research/nhl-season-scope-2026-27-v2.json \
  --output NEW_HISTORY_DIRECTORY

python scripts/prepare_initial_baselines.py \
  --league nhl \
  --season-scope research/nhl-season-scope-2026-27-v2.json \
  --history NEW_HISTORY_DIRECTORY \
  --current FRESH_CURRENT_DIRECTORY \
  --output NEW_PACKAGE_DIRECTORY
```

Every initial output directory must be fresh. To continue an interrupted scoped NHL history capture, repeat the same capture command and output path with `--resume`. The scope and immutable plan must match exactly. For normal current preparation, omit `--as-of-utc` so the actual UTC clock is used. That option exists for reproducible research and offline replay; it is not permission to backdate a forecast or relabel post-start results as pregame.

For the current integrated operation, the existing reviewed atomic source collector remains the prescribed producer of both history and current scoreboards. The repository command above now uses the same atomic raw/receipt principles for scoped NHL history capture; legacy league capture remains unchanged. Pass its `history` and `current` subdirectories directly to preparation. Its `nhl.atomic_history_capture.v1` and `nhl.atomic_current_capture.v1` reports require no legacy report conversion or receipt rewriting. This repository change does not alter the separately hash-pinned operational runner; use its preserved runtime until its runtime profile is separately reviewed and updated.

## Interruption and resume

Scoped NHL captures write raw bytes to a unique attempt-specific temporary file, flush and fsync it, atomically link it to its immutable raw path, and fsync the directory. Only then is the exact transport receipt committed by the same atomic procedure. A crash before the receipt commit leaves unused bytes; resume issues a new attempt and never reconstructs retrieval timestamps. Committed receipts are reused only after URL, source identity, exact clocks, payload, length and hash verification, within the unchanged six-hour TTL. Corrupt, stale and incomplete attempts remain preserved. Completion views are rebuilt from selected receipts without modifying them.

A failed transport records its failure time and leaves retrieval time null. Capture stops on the first failed request without an automatic retry. HTTP 401/403 failures and explicit proxy tunnel 401/403 denials require review and are not automatically retried on resume. An exclusive process lock rejects concurrent writers to the same capture directory. This patch does not resume, rewrite, or delete earlier retained attempts.

## Source contract

The unchanged v2 profile is byte-pinned at SHA-256 `12410ec50d94654cdbda6207f5a638968ae065156774445176ecf5574e65e45f`. It includes 219 applicable team-season schedule URLs for provider seasons 2021 through 2027. Only Seattle's 2021 season and Utah's 2021–2024 seasons are excluded as nonexistent. The scope retains the official evidence URLs. Utah provider ID `129764` and Arizona ID `24` remain distinct; Arizona appearances in opponent histories keep their original ID. No franchise state is aliased.

History reports must contain those 219 distinct successful requests, the five exact scope exclusions, the scope hash, and `action_authority: false`. Current reports require the same scope hash, `action_authority: false`, `timezone: America/Los_Angeles`, explicit `covered_dates`, and the prior/current/following provider-day scoreboards for each covered Pacific date. `events.json` must contain the complete `nhl` event map bound to retained raw bytes and their exact retrieval timestamps.

Each numerical receipt requires HTTP 200, exact timezone-aware request and retrieval timestamps, successful capture status, a contained relative raw path, and the raw SHA-256 digest. Applicable schedule payloads must identify the requested team and provider season even when empty; a current-season fallback never substitutes for historical data. Every source must be available and no older than six hours at preparation cutoff. Missing, duplicated, failed, future, stale, altered, or unbound sources fail closed. New seasons or changed exclusions need a separately reviewed profile.

Training remains 2021–2024, validation 2025, later audit 2026. Regular-season population, statistical methods, registered model identity, previous-UTC-day embargo, six-hour TTL, output immutability, and wagering OFF remain unchanged. Packages record source manifest hashes, scope hash, preparation code hash, and acquisition-contract code hash.

## Offline verification

```sh
python -m unittest discover -s tests -p 'test_nhl*.py' -v
python -m pytest tests/test_current_runtime_contracts.py tests/test_model_defaults.py tests/test_cross_sport_distributions.py tests/test_distribution_history.py -q
```

The NHL suite uses synthetic transport and data only. It covers provider-year rollover, source census and identity, franchise applicability, exact clocks and raw bindings, embargo, immutable outputs, explicit opt-in, byte-identical package replay, atomic interruption boundaries, resume, stale/corrupt receipt preservation, missing receipts, denied requests, and failed-transport timestamps. These checks establish software contracts, not predictive validity, fresh acquisition, or full repository health.
