# Selected-QB NFL margin and spread process — October 19, 2026

The selected NFL QB parent now has a fitted, source-bound margin research child,
an evaluated training policy, and an optional runner integration. Numerical
validation passed. Historical predictive validation remains **HOLD**: the
preregistered primary CRPS comparison was inconclusive, and the aggregate
historical screen did not pass. Wagering remains **OFF**. These changes are on
draft PR #69; they are not yet merged into `main`.

## Scope and identity

The parent remains `nfl.integrated_context.qb.v1.research`. The child models the
integer **home final score minus away final score**, for regular-season games
including overtime and ties (`FULL_GAME_OT_REGULAR`). It attaches the existing
shared full-support margin fitter to the exact selected QB parent. Its only
conditional-scale feature is `absolute_parent_margin`, derived from the parent
point prediction. Markets do not enter fitting or distribution generation.

The winner head, point margin, and point total are preserved. The child supplies
cover/push/loss probabilities and a separate margin simulation. It does **not**
fit a total distribution or supply over/under probabilities. Its margin-derived
winner probability is separate from the parent's conditional-on-no-tie winner
head; the two must not be silently substituted.

## Source qualification and timing

The retained integrated-context archive supplied 2,895 feature rows and 1,871
selected-QB out-of-time forecasts covering 2019–2025. Seven expanding annual
parent folds were refitted using only earlier seasons. Replayed predictions
matched within `1.42e-14`; the final packed parent coefficients matched within
`8.88e-16`. All 1,871 schedule joins passed date, team, regular-season scope, and
score-margin checks. All six held-out ties were retained. The original parent
fit excludes ties through complete-target filtering; this inherited limitation
was preserved and disclosed.

The information set is `RECONSTRUCTED_QB_OOF_PRIOR_SEASON_FITS`. These rows reuse
historical research and are not an untouched or prospective cohort. Archived
source availability and starter identities were not proved as of each kickoff.
Schedule starts come from a retained provider schedule; parent fit cutoff
(July 1 of the forecast season), forecast cutoff (kickoff minus one hour), and
result availability (kickoff plus 24 hours) are explicit reconstructed bounds.
They must not be represented as observed publication times. Actual artifact
creation times remain October 20 UTC / October 19 Pacific, 2026.

The preregistration was committed as
`42cf2712507a29e8a67cfa4b1fc9f70e0be85a28` before new fitting or evaluation.
`data/nfl/qb_margin_full_support_v1/design.json` has SHA-256
`af2a6d8abf7db528671000fb952b6bff1a0c853f9b14940df6e6a578673499f2`.
The qualified cohort has SHA-256
`1f4cb50d7d464169c50ab3326ac5cf904c5242d0ce7509e2212f44f8fa8f1947`.
Original feature, OOF, audit, parent, and schedule bytes are hash-bound; each
derived row is checked against the raw sources and replayed parent fold.

## Fixed evaluation and result

The initial margin fit used 1,055 rows from 2019–2022. The later-season evaluation
used 816 rows from 2023–2025. The empirical residual baseline and full-support
challenger use the same parent and identical events. The existing purged
chronological 70/30 internal parameter-selection policy uses training rows only.
No options were changed based on the later-season results.

The fixed home-handicap grid was
`[-14, -10, -7.5, -7, -6.5, -3.5, -3, 0, 3, 3.5, 6.5, 7, 7.5, 10, 14]`.
Those are hypothetical diagnostic contracts, not observed historical prices.
Each game contributes equal weight after its lines are aggregated. Uncertainty
uses 2,000 moving-block bootstrap replicates, four contiguous observed week
blocks, and seed `7192026`; there are 57 observed time blocks.

| Metric | Empirical baseline | Full-support challenger | Challenger minus baseline, 95% CI |
| --- | ---: | ---: | --- |
| Mean CRPS (primary) | 7.312197 | 7.304288 | −0.007908 [−0.022664, +0.011302] |
| Three-way cover/push/loss Brier | — | — | −0.001490 [−0.002555, −0.000132] |
| Three-way category log loss | — | — | −0.006500 [−0.008938, −0.003957] |
| Conditional nonpush cover Brier | — | — | −0.000602 [−0.001131, +0.000091] |
| Conditional nonpush cover log loss | — | — | −0.001746 [−0.003482, +0.000477] |
| Mean absolute margin error | 10.161392 | 10.167312 | +0.005919; interval crosses zero |
| Exact-margin zero-support outcomes | 1 | 0 | Baseline mean log score is infinite; it is not clipped |
| 95% predictive interval coverage | 95.5882% | 95.8333% | Challenger mean width 53.8958 points |

The challenger had 50%/80%/90% interval coverage of
50.3676%/78.5539%/89.5833%, respectively. Exact-margin challenger mean log loss was
3.892297. All 1,632 paired cover ladders were monotone. Integer-line pushes and
conditional nonpush scores were retained separately; half-integer lines have
zero push probability.

Four of five preregistered historical checks passed: nonpositive CRPS delta,
three-way Brier delta at most 0.002, 95% coverage between 0.90 and 0.99, and zero
challenger unsupported outcomes. The required CRPS confidence-interval upper
bound below zero failed. The aggregate screen is **NOT_PASSED** and the primary
diagnostic is **INCONCLUSIVE**. Better secondary category scores do not override
the primary gate or establish profitable spread pricing.

## Evaluation and deployment refit are distinct

After the fixed evaluation was retained, the preregistered algorithm and internal
selection policy were refitted on all 1,871 qualifying 2019–2025 rows. This was
specified before evaluation; it did not select parameters using external test
scores. Numeric internal selections may differ because the training population
differs. The all-history refit itself has no directly held-out evaluation.

| Role | Model ID | Internal artifact SHA-256 |
| --- | --- | --- |
| Evaluated 1,055-row fit | `nfl.margin.full_support.research.96c5a8cb7e9970e7` | `a741d83543a7dd3c1af82d39006084d69c4732a3a8672ac912104d9045df1e19` |
| Deployment 1,871-row refit | `nfl.margin.full_support.research.ad4017ccf0663e24` | `e50967eec466439749658881591442ade365af37d4e2371300b7686ab7469cd4` |

`registration_evaluation.json` binds both identities and records
`deployment_artifact_directly_evaluated: false`. File-byte hashes are distinct
from the models' internal content hashes. The deployment file SHA-256 is
`fb715ddf7abb86c3d725a9f3e1fbe510c4852881e8e3dd83342f6ddc744691cb`;
the registration/evaluation file SHA-256 is
`ca44c9eeefa4352ebf2c71831e1b0c596a18fd33d06d680a597a6abed31cf694`.

## Retained execution and reproduction

The completed immutable evidence directory is `nfl-margin-20261019/study-v1`
in the session evidence package. It contains the design and pre-fit execution
binding, both evaluated models, 1,632 retained PMFs for 816 games, evaluation and
cover diagnostics, deployment refit, registration mapping, and a file manifest.

The exact executed study script was retained separately as
`study-v1-executed-runner.py`, SHA-256
`9a87d73e2722a168a92e4d41f5001f3e2566b85979aec9463d630a934f6571be`.
While that execution was running, an independent deeper source validator was
added to the current runner's pre-fit entry point. The unchanged completed
cohort separately passed that validator; the receipt is
`study-v1-source-validation.json`. This is an independent recheck, not a claim
that the completed execution invoked the later preflight. The validator has
SHA-256 `e2000fec668df721bfe1f645cab3b54f70a97fc52088cac31eda00af047cfb58`.
No fitting or scoring logic changed. Future entry rejects a bad source binding
before creating an output directory or fitting either model.

From the repository root, with the retained archive and schedule evidence
available, the qualification command is:

```bash
python scripts/build_nfl_qb_margin_cohort.py \
  --source /path/to/integrated_context_report \
  --schedule /path/to/retained-schedule.csv \
  --schedule-receipt /path/to/source-refresh.json \
  --parent-model data/nfl/contextual_v1/model_packed.json \
  --output /path/to/new-qualified-cohort
```

Run the fixed study into a new directory; existing output is refused:

```bash
python scripts/run_nfl_qb_margin_study.py \
  --cohort /path/to/qualified/qb_margin_cohort.json \
  --design data/nfl/qb_margin_full_support_v1/design.json \
  --output /path/to/new-study-run \
  --prereg-commit 42cf2712507a29e8a67cfa4b1fc9f70e0be85a28
```

Source/model values and metrics are reproducible; actual creation timestamps
must advance, so new artifact identities and file hashes need not equal the
retained run. A new study run does not replace the fixed historical record.

## Current and future runtime

`data/nfl/qb_margin_full_support_v1/runtime.json` is the pinned optional
configuration. It binds model and evaluation files, the exact packed parent,
and the parent runtime code. `data/nfl/contextual_v1/runtime.json` can reference
it with `margin_distribution_config`; the selected-QB pregame path then emits
the separate child automatically. An explicit invocation is:

```bash
python scripts/run_nfl_integrated.py \
  --date YYYY-MM-DD --event-id YYYY_WW_AWAY_HOME \
  --output /path/to/new-pregame-run \
  --margin-model data/nfl/qb_margin_full_support_v1/runtime.json \
  --home-spread -7.5 --simulations 100000
```

A different date first needs a fresh source-bound event package. Config,
fitted model, and evaluation must exist before the forecast cutoff; the
forecast and child registration must actually be written before kickoff.
Missing or mismatched evidence fails closed and produces a visible child
failure instead of fabricated probabilities. Retained draws, seed, parent
identity, contracts, PMF, and immutable receipt allow settlement and replay.
Research production does not change predictive HOLD or wagering authority.

The October 19 WAS–SF game had started before authorization. Its saved morning
parent can only be transformed through the explicit retrospective command:

```bash
python -m models.nfl.contextual.margin_distribution \
  --forecast-dir /path/to/frozen-morning-nfl-forecast \
  --margin-model data/nfl/qb_margin_full_support_v1/runtime.json \
  --home-spread -7.5 --simulations 100000 --retrospective \
  --output /path/to/new-was-sf-reconstruction
```

Any resulting percentage is a new retrospective research calculation using
the frozen parent, not a probability present on the original morning card or
a newly acquired live forecast. The original card and its missing NFL cover
field remain intact. No current score or later outcome enters the transform.

The completed reconstruction uses the preserved October 19 parent cutoff at
10:35:24 a.m. Pacific and 100,000 frozen margin draws:

| Contract / summary | Analytic margin law | Retained simulation |
| --- | ---: | ---: |
| SF −7.5 cover | 55.1492% | 55.2910% |
| WAS +7.5 cover | 44.8508% | 44.7090% |
| Push at either half-point line | 0% | 0% |
| Mean home margin | SF +10.6899 | SF +10.7247 |

The parent point prediction remains SF +11.0144; the fitted residual law's mean
is a separate summary. The margin median is SF +10; its central 50%/80%/95%
prediction intervals are `[2, 21]`, `[-6, 29]`, and `[-17, 38]` points in home
orientation. These widths describe outcome uncertainty. Monte Carlo intervals
describe only numerical sampling error conditional on this fixed law and do
not establish calibration. The retrospective percentage now exists as a
reproducible research calculation, while predictive validity remains HOLD.

## Verification

The study's seven focused unittest methods passed, including bad-source
rejection before fitting, immutable output, chronology, exact parent scope,
derived scale, nonfinite data, key-number pushes, and conditional push exclusion.
Both fitted challenger artifacts pass the shared model validator; every
completed study manifest hash matches. The cohort validator has seven passing
test methods and passed the unchanged 1,871-row population.
An independent reviewer recomputed all 816 CRPS scores, the four-week bootstrap
interval, 95% coverage, width, and zero-support counts from the retained PMFs;
the results match to floating-point precision.

Focused combined suite: **187 unique current tests passed** (158 prior regressions, 7 cohort, 7 study, 15 adapter). The 185-test initial aggregate plus the final 15-test adapter rerun cover the current bytes; duplicate runs are excluded.
Global healthcheck limitations from the partial checkout are reported
separately; focused tests do not imply that unrelated missing repository assets
were repaired.
