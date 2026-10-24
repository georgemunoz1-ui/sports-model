# Independent candidate assimilation — 2026-09-16

Implemented a reusable research layer using standard open-source libraries and independently authored feature/evaluation code. Sam Hoppen's repositories supplied review leads and pinned data snapshots; their implementation code and fitted weights were not transplanted. No operational forecasting defaults, prior forecast files, release gates, or wagering authority change. The work is on an isolated review branch.

## What is now executable

- Ridge regression with training-only median imputation, missingness indicators and StandardScaler.
- XGBoost regression with a small fixed search grid and deterministic seed.
- Chronological development cross-validation: six expanding training windows, disjoint tuning/calibration/test seasons, complete events kept together.
- Sigmoid probability calibration fitted on a later, separate season, never on the test season. Raw diagnostic probabilities use the fitted margin and training residual scale.
- Per-feature timestamp validation using the existing strict PIT contract; source SHA-256 validation; market-field rejection; refusal of duplicated or split events.
- NFL last-eight scoring features and coaching continuity/experience, updated only after each calendar-date batch.
- NFL observed play-by-play summaries and stable-player-ID high-value touches.
- Independent offensive/defensive ridge RAPM design with five players per side, a negative defensive design sign, and projected minute exposure summing to five. Its external-source fit is blocked by the source audit below.

The generic PIT validator and the historical replay are deliberately separate. Historical coaching metadata were downloaded now, without archival publication timestamps. Date ordering prevents outcome leakage but does not prove those metadata were available before historical kickoff. Results are retrospective development diagnostics, not certified historical PIT performance.

## Registered experiment and findings

`research/candidate_methods/protocol.json` was written and registered in `state.json` before the first fit. For each test season 2019–2024, training ends three seasons earlier, tuning uses the second prior season, calibration uses the immediately prior season, and the model is frozen for the test season. Prior completed games can update the last-eight-game inputs during that season. Hyperparameter selection uses tuning margin MAE. There is no refit after tuning. NFL 2025 and 2026 are excluded from this experiment's fitting and scoring; this is an experiment-local holdout, not a claim that the wider project has never seen those seasons.

All arms score the same **1,599 regular-season games**. Probability metrics exclude five ties and are explicitly conditional binary diagnostics, not valid three-way moneyline prices.

| Arm | Margin MAE | RMSE | Raw home Brier | Sigmoid home Brier | Sigmoid log loss |
|---|---:|---:|---:|---:|---:|
| Ridge, lagged scoring | 10.35055 | 13.35368 | 0.228189 | 0.227731 | 0.647804 |
| Ridge, plus coaching | 10.35895 | 13.33711 | 0.227669 | 0.227484 | 0.647015 |
| XGBoost, lagged scoring | 10.42637 | 13.43196 | 0.229696 | 0.228631 | 0.649417 |

Coaching-minus-baseline MAE: **+0.00840 points**, paired date-cluster bootstrap 95% interval **[-0.05933, +0.08109]**. XGBoost-minus-baseline: **+0.07582**, interval **[+0.00753, +0.14284]**. Lower error is better. These bootstrap intervals cluster 324 game dates, do not model serial dependence between dates, and are not adjusted for multiple comparisons.

Coaching has mixed metrics and no clear margin improvement. The particular XGBoost setup did worse on this sparse feature set. Calibration slightly improved aggregate Brier in all three arms, but coaching log loss was slightly worse after calibration. This does not reject XGBoost generally or establish a forecasting edge. The comparator is a simple last-eight-game scoring model, **not the current integrated NFL model**. No model is promoted.

Portable fitted artifacts, exact fold event IDs, predictions, reliability tables, source receipts, software versions, source/code hashes and the registered configuration are retained in `data/research/candidate_methods_v1/verified_20260916/`.

## Collected NFL observations

The 2026 Week 1 capture contains all 16 games and 32 team-game rows. The extractor retains EPA and success rates with observed denominators for all plays, pass/rush, early downs, third downs and red-zone plays; neutral pass rate; sacks and turnovers; target concentration; observed YAC minus source-provided expected YAC; conservative running-clock elapsed time; and player high-value touches.

The pace proxy has 542 eligible consecutive-snap intervals. It orders by numeric source `order_sequence`, resets across games/quarters/drives and excludes preceding stoppages. This is elapsed game-clock time, **not an independently fitted pace-over-expectation model** or exact snap-to-snap wall-clock time. High-value touches comprise receptions plus rush attempts at or inside the opponent's 10-yard line: 722 touches across 259 player/game/type records. This is a workload definition, not fitted expected fantasy scoring. Target concentration uses identified targeted receivers and excludes unassigned passes, with denominator retained. Source xYAC itself is an upstream model estimate with unverified training vintage, so this residual is observation-only.

These postgame observations cannot explain a pregame Week 1 forecast. The earliest preserved PBP retrieval was 2026-09-15T22:19:57.664095+00:00. Any later candidate forecast must additionally bind its own event, cutoff and source availability, fit coefficients on compatible historical data, and record features actually consumed. The collection alone supplies none of those permissions or evidence.

## WNBA quality gate

The pinned `stints_rich_2026.csv` contains 2,370 rows from 26 games, May 8–17. There are **39 rows with invalid points under the registered possession contract**, up to **105 points**, and **405 rows disagreeing with `2*fgm + fg3m + ftm`**. These counts can overlap. IDs and ten-player uniqueness pass. The whole external fit is blocked; problematic rows are not silently discarded, corrected from an assumption, or treated as real possession targets.

The RAPM method passes synthetic sign, exposure, identity and fitting tests. It has **not** been fitted to reliable WNBA observations here. A repair requires official play-by-play reconciliation, possession-definition and score-transition validation, complete-game coverage, dates, and minutes. If the data represent aggregated stints rather than possessions, the model must use documented exposure weights and a revised, separately registered contract. Unknown current players and incomplete rotations block deployment. The old player-store effects are not imported.

## Reviewed candidates and next evidence

See `research/candidate_methods/candidate_registry.json` for source references, implemented/fitted/used states, and specific missing requirements. Priorities are: repair WNBA possession data; obtain historical NFL PBP for rolling pace/drive/workload features; capture dated coaching/roster snapshots; then compare one feature family at a time against the integrated NFL baseline on a newly registered evaluation.

All evaluation remains research. Existing repository health is red: the local health run reports recovery-job and historical release-eligibility failures. That local checkout was not exact current main, and this narrow suite does not certify full repository health. The failures remain visible and unmodified.

## Reproduce and verify

Use Python 3.12 with `research/candidate_methods/requirements.txt`. Supply the eight exact source files listed in `source_manifest.json`. Six third-party CSVs have immutable commit-qualified URLs and matching Git blob hashes. The two nflverse files have preserved retrieval receipts and SHA-256; a later file at the same URL may differ and will be rejected. A compressed source snapshot is supplied for exact replay. Treat these retrospective files as historical evidence, not as a current feed. The offline run performs no HTTP requests. Extract `data/research/candidate_methods_v1/sources.tar.gz` into a new directory and use that directory for both source arguments. Source snapshots include quarantined third-party rating tables for audit only; these are not model inputs.

```bash
python -m unittest discover -s tests -p test_candidate_methods.py -v
python -m research.candidate_methods.run \
  --sources /absolute/path/to/captured_csvs \
  --nfl-sources /absolute/path/to/captured_csvs \
  --output /absolute/path/to/new_result_directory
```

Run `python -m research.candidate_methods.replay data/research/candidate_methods_v1/verified_20260916` to verify all 25 retained artifact hashes and replay 4,797 arm/game predictions without refitting. Maximum observed replay difference is 3.56e-15.

An existing output directory is refused. The first exploratory execution used newline-normalized coaching text; its values and all model predictions match the final execution. The final execution restores the exact original CRLF bytes and absent final newline, verifies the Git blob hash, and adds third-down/red-zone/target-concentration observation columns. No selection grid or evaluation protocol was changed after seeing scores.

## Standard methods learned and encoded

Ridge minimizes squared error plus an L2 coefficient penalty; train-fold scaling makes that penalty comparable across numeric feature units. Sparse RAPM indicators are left in their natural possession units to preserve the interpretation. [Ridge](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html) and [StandardScaler](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html).

XGBoost adds regularized trees to reduce a supervised loss. Tree depth, number of trees, shrinkage and penalties are tuned only on past data; tree inputs do not require StandardScaler. Its availability does not establish predictive value. [XGBoost model tutorial](https://xgboost.readthedocs.io/en/stable/tutorials/model.html).

Random K-fold evaluation is inappropriate when future observations could inform earlier events. Here development folds move forward by season, and all rows belonging to an event stay together. Inner tuning, calibration and outer tests use distinct chronological populations. [Cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html).

Calibration maps frozen model outputs to empirical probabilities on a separate past population. Reliability bins, Brier and log loss measure different aspects; none alone proves a betting edge. Isotonic calibration is deferred until there is sufficient independent calibration data and a new registered comparison. [Probability calibration](https://scikit-learn.org/stable/modules/calibration.html).

Fit preprocessing only on training observations; distinguish event time, label availability and source publication/retrieval time. Enforce stable IDs, lag before joining, quarantine invalid records, and keep final outcomes and market fields out of football-only features. Historical source revisions can still invalidate a claim of point-in-time testing. [Common pitfalls and leakage](https://scikit-learn.org/stable/common_pitfalls.html).
