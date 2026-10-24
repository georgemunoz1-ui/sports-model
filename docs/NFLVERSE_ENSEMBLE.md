# NFLverse integration and target-aligned ensemble — September 18, 2026

## Decision

**Research integration completed; improvement screen FAILED; default unchanged.**

The new path loads NFLverse using `nflreadpy==0.1.5`, verifies metric/identity contracts, and ensembles compatible out-of-fold predictions from five existing contextual NFL models and three independently developed PR36 models. It is not a production promotion or a current forecast. Bills–Lions and prior frozen forecasts are unchanged. ACTION OFF; dose0.0.

Base: intact main `09ef320c2838b98951c5c336ba985c39bfd083e6`. Branch: `codex/nflverse-metric-ensemble-20260918`. Executed verification commit: `43cd428922d4dde60a0178ebbd6badd279b6b6e4`.

## Sources actually incorporated

The Python package was installed and all eight 2026 loaders executed successfully. Captured package outputs are labeled derived tables, not raw HTTP source bytes. Raw 2015–2024 PBP, injuries and snap files are separately retained with hashes.

| Current data | Rows |
|---|---:|
| Play-by-play | 2940 |
| Regular-season schedules | 272 |
| Player statistics | 1190 |
| Team statistics | 34 |
| Rosters | 2980 |
| Snap counts | 1585 |
| Timestamped depth charts | 531796 |
| Injuries | 412 |

Current capture cutoff: `2026-09-18T18:37:50.064342+00:00`. PBP reconciled to all17 completed games, including DET–BUF. The latest depth snapshot has2207 rows across32 teams, explicitly **candidate depth, not confirmed starters**. All1122 observed player IDs matched roster GSIS IDs. Counting statistics reconciled in374 player-sum/team-total checks with zero mismatches. All observed offense/defense/special-teams snap percentages were valid fractions. These are same-provider consistency checks, not independent official-gamebook clearance.

Previously reviewed source status:

- `nflverse/nflreadpy`, `nflverse/nflverse-data`, `nflverse/nflfastR`: loader/source integration; existing football feature transforms reused.
- `samhoppen/NFL_public`: pinned coaching data incorporated through the independently authored PR36 scoring/coaching models, not copied external fitted forecasts.
- `samhoppen/Fantasy-Evaluator`: pace and expected-drive-point leads remain registered; no unfitted effect is called active.
- `samhoppen/nflWAR_public`: retained candidate; compatible identity/scale/PIT/fitting requirements remain unresolved.
- `samhoppen/shank_wnba`, `shankapotomus/wnba-rapm`: separate WNBA track; known source defects remain blocked; not an NFL ensemble member.
- Toto, TabICL and Granite: no fitted compatible NFL output available for this experiment, so not silently ensembled.

PR36 commit: `544584db9ac1e66606190b326e625ae7b7da2db4`. Its25-file manifest and4797 predictions replayed with maximum absolute error3.55e-15. Historical coaching publication times remain unverified.

## Model and metric correspondence

Winner and margin heads combine contextual base, QB, availability, travel and combined models with PR36 scoring Ridge, coaching Ridge and scoring XGBoost. Total points use only the five contextual models; PR36 had no fitted total head. Weights are nonnegative and sum to1 independently per target.

The feature registry maps all100 contextual columns to missingness and actual model-head/ensemble coefficients. In the2024 artifact trace,96 have a nonzero path. The inactive columns are `rest_missing`, `location_missing`, `roof_missing`, `qb_unknown_count`. The23 prior candidate-family records are retained with their existing lifecycle labels. Registered, observed, fitted and used are not interchangeable.

Tests cover fraction/percentage units, team aliases, home probability orientation, home-minus-away margin, home-plus-away total, ties, EPA offensive/defensive perspective, observed denominators, snap-share versus summed-role semantics, chronological cohorts, source/feature/model pins, and target/period/cutoff agreement. `spread_line` is positive for a home favorite in the source and becomes negative home handicap only for downstream market comparison. Market fields and market-based source models are excluded from the football feature path.

`research.nfl_fusion.ensemble.predict_packets` requires the complete compatible member set; it fails instead of silently dropping models or renormalizing. It is a research admission interface, not independently authenticated source authorship or canonical writer attestation. Current observations were not installed as production state and no new current-game forecast was issued.

A real null non-play feed row exposed a parsing issue. The null adapter was corrected, three feed regressions added, and evaluation rerun. No weights, splits or scoring thresholds were changed after looking at test results.

## Chronological test

Protocol was committed before evaluation: `research/nfl_fusion/protocol.json`, commit `adfeab7640d65c1e8ec4495a0de6a27b71830d8a`.

The historical feature pass covers2015–2024. Contextual models fit earlier seasons only for each2019–2024 prediction. All eight arms align to1599 common games. Ensemble fitting uses2019–2021; calibration uses2022; evaluation uses544 regular-season games from2023–2024. No2025/2026 outcomes, including Bills–Lions, enter fitting or selection.

| Comparison | Correct / games | Accuracy | Brier | Log loss |
|---|---:|---:|---:|---:|
| QB architecture baseline, chronological refits | 359/544 | 65.99% | 0.221189 | 0.631585 |
| Equal-weight eight-model blend | 333/544 | 61.21% | 0.224381 | 0.639031 |
| Learned weights, raw blend | 348/544 | 63.97% | 0.220879 | 0.631451 |
| Learned weights + calibration, declared primary | 346/544 | 63.60% | 0.222920 | 0.635915 |

Lower Brier/log loss is better. The raw blend barely improves Brier (-0.000311), but gets11 fewer winners correct. The predeclared calibrated candidate worsens Brier by+0.001730; week-cluster bootstrap95% interval [-0.002426,+0.005937],10000 resamples. The preregistered improvement screen fails. Do not replace the primary after seeing the result.

Margin MAE: QB10.1634 points vs ensemble10.1812. Total MAE: QB10.2941 vs ensemble10.2954. Neither improves.

Winner weights: QB49.84%, coaching Ridge29.44%, combined12.97%, scoring XGBoost4.08%, scoring Ridge3.66%, other standalone arms effectively0%. These are historical learned weights, not odds adjustments. Correlated models containing the same feature are not independent evidence.

These are reused retrospective project years, not a virgin prospective holdout. Historical publication timing, starter identity, injury and weather limitations persist. No blanket calibration or future profitability claim follows.

## Verification and retained evidence

Source build run35381140577. Verification run35382612110. **154 tests passed**:100 existing NFL tests plus54 fusion/feed tests. Actual Python return codes are checked; no tee masking. Reloaded fitted coefficients replay exactly in the recorded environment;100000 historical binary winner draws replay exactly. They are not a current forecast or joint score/drive simulation.

139 full-input manifest entries, including raw files, and101 nonraw distribution entries were independently verified after download. Final artifact manifest17 entries and nested results manifest12 entries also match; nested files are not additional independent evidence.

| Artifact | ID | ZIP SHA-256 |
|---|---|---|
| Inputs, run35381140577 | 10561959968 | `47a31f05130a3dc7f3ca18b0884ae6010dc367cb56fd1e0f6a3cce4c6ae4ce03` |
| Raw sources, run35381140577 | 10562910420 | `82bebb479812a3a2714ccec3068e634aa43a3cb15ca64b781fcb6d54cc86ed9e` |
| Verified results, run35382612110 | 10562806842 | `0b6ca579775632ffdb84c847b17c52b5420fcd8af65967e24dbc105916a2d983` |

Artifacts expire December17,2026. Portable weights are committed to `data/nfl/fusion_v1/ensemble_packed.json`; long cohort ID lists are replaced by their hashes/counts, with the parent artifact retained. Its predictions matched the uncompressed model locally. No default pointer references this failed-screen candidate.

To reproduce with Python3.12:

```bash
pip install -r research/nfl_fusion/requirements.txt
python -m unittest discover -s tests -p 'test_nfl_fusion*.py' -v
python -m research.nfl_fusion.run --inputs fusion-inputs --output NEW_OUTPUT_DIRECTORY
```

## Important correction and remaining blockers

The earlier `nfl-learning-repair-35322440580.zip` reports66 tests with25 errors, including a literal-backslash-newline SyntaxError in assimilation.py. Its green workflow masked the failing Python process. A correction is posted on PR38 (comment5734470023). That generic weekly-chain/idempotency repair remains unverified and is not inherited here.

Current integration starts from intact main, but global health is still RED: four failures/nine warnings in retained health evidence. Archive/recovery, historical release and standing-health obligations remain. The complete safe weekly state transition and later live forecast consumption are not proved by this ensemble test. Unit/metric verification is separate from model promotion and global release eligibility.

Primary documentation: https://nflreadpy.nflverse.com/ ; https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html ; https://github.com/nflverse/nflreadr/blob/main/data-raw/dictionary_schedules.csv . Source-specific results above come from the pinned retained artifacts.
