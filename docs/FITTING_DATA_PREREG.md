# Fitting-data preregistration: NFL / WNBA / MLB qualifying historical data

Status: RESEARCH-ONLY. `research_only: true`, `action_authority: false`.
Release state unchanged: RELEASE RED / ACTION OFF / DOSE 0.0. No wagering
authority is granted or implied by any artifact produced here.

Market firewall: no market-implied probabilities, lines-as-features, or
closing-line columns are used anywhere in this pipeline. The MLB harness
market loader (`load_market_by_gamepk`, results.csv `close_ml_*` columns) is
stubbed to `{}` before any harness code executes. NFL key-number mass is
fitted on game outcomes only (nflverse final scores), never on spreads.

Companion to `docs/MARGIN_LAYER_PREREG.md` (PR #70). This document covers the
parent-specific historical fitting data required by the margin adapters.

## Scope and qualification bar

A margin adapter may quote only when its dispersion/distribution inputs are
parent-model-produced and out-of-sample:

- `estimate_sigma` requires provenance `{sport, oof: true, window_start,
  window_end}` — chronological OOF only (`SIGMA_PROVENANCE_NOT_OOF`).
- Empirical distributions require >= 200 support; simulated distributions
  require >= 10,000 draws; discrete football margins carry fitted key-number
  mass from >= 2,000 games of history.
- All artifacts are append-only and hash-pinned (`record_sha256` /
  per-file sha256 in manifests). Identical rewrite is a no-op; differing
  rewrite raises `ARTIFACT_IMMUTABLE`.

## MLB — `mlb.v13_1.gamma_poisson_monte_carlo.v1` (1.0.2)

Qualifying data: per-game simulated score draws (away/home integer arrays,
int16 npz) for the full 2026 regular-season replay window
(2026-03-25 .. 2026-07-19 backfill), 30,000 sims/game, per-game seed
`722 + gamePk` (order-invariant).

- Builder: `scripts/build_mlb_margin_draws.py` — replays
  `harness/run_v13_historical.py` verbatim (same `run()` code path), captures
  `(ra, rh)` at the `v13_sim` return via a `sys.setprofile` hook, derives
  actuals from features.csv `total`/`margin` only (parity + sign checks),
  estimates the qualifying OOF sigma via
  `models.common.margins.sigma.estimate_sigma`.
- CI: `.github/workflows/margin_fitting_ci.yml` — probe (unsharded 25 games,
  timing + order-invariance reference) -> 8 sharded replays -> aggregate.
  The aggregate (`scripts/ci_mlb_aggregate.py`) fail-closes on:
  `SHARD_SET_INCOMPLETE`, `SHARD_PROVENANCE_DRIFT`, `DUPLICATE_GAME`,
  `SHARD_FILE_MISSING`, `SHARD_FILE_HASH_MISMATCH`,
  `AGGREGATE_GAMES_MISSING`, `AGGREGATE_COUNT_INCONSISTENT`,
  `ORDER_INVARIANCE_VIOLATION`, `ORDER_INVARIANCE_UNVERIFIED`,
  `AGGREGATE_SIGMA_UNAVAILABLE`.
- Output: `data/mlb/margin_draws_v1/{manifest.json, residuals.csv,
  <gamePk>.npz}` — committed by the aggregate job with `[skip ci]`.
- Pins: features.csv + `data/mlb/ml_asof/p3_candidate_config.json`
  (sha256 prefix `eede422d`) + harness sha256 are embedded in every manifest.

## WNBA — `wnba.rs.ff7_logit_ridge.v1_0.shadow`

Qualifying data: chronological walk-forward OOF residual bank for the frozen
7-feature ridge parent (`harness/wnba_model_v1.py`, imported never copied).

- Builder: `scripts/build_wnba_margin_oof.py` — re-runs the harness
  walk-forward, retains per-game `(date, m_pred, m_act)`, and BEFORE writing
  verifies reproduction against the frozen 2026-08-29 bank
  (`data/wnba/model/wnba_margin_residuals_2026-08-29.npy`): n == 1721,
  |MAE - 9.881| < 0.01, |sd - 12.5523| < 0.01 (ddof=0). Any drift ->
  `OOF_REPRODUCTION_MISMATCH` and nothing is written.
- Output (CI `wnba` job): `data/wnba/model/wnba_margin_oof_residuals_v1.json`
  (per-row date/pred/actual/residual as actual - pred, payload_sha256,
  provenance, verbatim `estimate_sigma` output) and
  `data/wnba/model/wnba_margin_ridge_head_v1.json`
  ({impute, mean, scale, coefficient, intercept}; `b2b_edge` is never
  standardized -> mean=0/scale=1 in the repack).
- Runtime requirement: pyarrow (staging parquet reads). Installed in CI.

## NFL — `models/nfl/contextual/model.py` (arms: base/qb/travel/availability/combined; selected = qb)

Delivered now:

- `data/nfl/margin_fit/nfl_key_number_mass_v1.json` — fitted symmetric
  key-number mass boosts vs a normal baseline (mu=+2.240, sigma=14.611) from
  6,967 completed regular-season games 1999-2025
  (`data/nfl/source/2026-09-03_nflverse_regular_games.csv`, hash-pinned).
  Loaded by `pipelines/margins/nfl_key_numbers.py`
  (fail-closed: `NFL_KEY_NUMBER_MASS_MISSING` / `_HASH_MISMATCH` /
  `_SCHEMA_INVALID`).
- `data/nfl/margin_residuals/nfl_combined_margin_residuals_v1.json` —
  combined-arm margin residual pool (n=1871, sigma=13.466, seasons
  2019-2025) decoded from the committed
  `data/nfl/contextual_v1/model_packed.json` score-pair residuals.
  Limitation label: `SCORE_PAIR_DERIVED_NOT_MARGIN_HEAD`. The NFL adapter
  continues to fail closed with `MARGIN_POOL_MODEL_MISMATCH` while the
  selected arm is `qb` and only the `combined` pool exists — intended.
- CI `nfl-verify` job re-derives both artifacts from their committed sources
  and requires byte-identical sha256 (reproducibility gate).

Blocked on owner input (documented, script ready):

- Per-arm qualifying pools (base/qb/travel/availability) require
  `data/nfl/contextual_v1/fit_03/oof_predictions.csv` (sha256 pin
  `cb11bb530bb7d8149e0fbae8f6d6cc1775f6879ab157051e3c86dff525092510`), which
  lives in the owner's external recovered-root archive and is not committed.
  Once that file is restored, run:
  `python3 scripts/build_nfl_margin_residuals.py`
  (fail-closed: `OOF_MISSING` / `OOF_HASH_MISMATCH`; per-arm n >= 200).

## CI workflow summary

`.github/workflows/margin_fitting_ci.yml`, branch `feature/margin-fitting-data`:

1. `test` — full pytest suite (margin layer + all fitting builders).
2. `probe` — MLB selftest + unsharded 25-game 30k-sim timing probe.
3. `replay` — 8 shards x ~185 games x 30k sims (per-game seed rule makes
   shards equivalent to one full run).
4. `aggregate` — completeness/integrity/provenance gates, probe
   order-invariance cross-check, overall qualifying OOF sigma, commits
   `data/mlb/margin_draws_v1/` with `[skip ci]`.
5. `wnba` — OOF bank regeneration with reproduction gate, commits
   `data/wnba/model/` artifacts with `[skip ci]`.
6. `nfl-verify` — NFL artifact reproducibility gate (no commits).

Nothing in this workflow merges to main; all commits land on the feature
branch for review.
