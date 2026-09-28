# QB margin and cover process

The requested full-game spread output now has its own QB-only registered research
model: `nfl.qb_margin.residual_alignment.v1.research`. It supersedes the dependency
on the quarantined combined spread path. The selected winner model remains
`nfl.integrated_context.qb.v1.research`. Combined/availability quarantine, old
forecasts, grading state, market overlay OFF and action authority OFF remain.

## Acquisition and registration

1. Recover the original features and OOF predictions from the retained integrated
   context archive. Require the exact hashes in `data/nfl/qb_margin_v1/design.json`.
   `acquisition.json` identifies the archive and retained source. These are reused
   historical data, not evidence of original pregame availability.
2. The design and one appended `state.json` experiment were committed at
   `954bc0e26be86b04206b9f82cedc857426891bad` before fitting or evaluating this law.
   No old experiment entry or production default was edited.
3. Run `scripts/fit_nfl_qb_margin.py --source-dir SOURCE_DIRECTORY --output NEW_FIT_DIRECTORY
   --prereg-commit 954bc0e26be86b04206b9f82cedc857426891bad`. The source directory
   must contain the original hash-matched `features.csv` and `oof_predictions.csv`.
   Existing output directories are rejected.
4. The fit independently regenerates every 2019–2025 QB OOF head from prior
   seasons only. Evaluation in 2020–2025 uses only earlier-season QB residuals.
   The deployment law uses all 1,871 QB OOF residuals through 2025, with no 2026
   outcomes. Fitting, evaluation and provenance are separate retained artifacts.
5. Bind the fitted model and evaluation hashes in the separate QB-margin runtime
   configuration. This registration grants diagnostic computation only. Any
   changed law, feature family, calibration or tuning policy requires a new design
   and model identity. No outcome-driven retuning of this candidate is permitted.

## Distribution and simulation

The unchanged QB Ridge head supplies a home-minus-away location. The fitted law
centers QB OOF margin errors, translates them by that location and rounds to
integer final margins. It assigns the unchanged QB logistic probability to
non-tie win/loss mass and a prior-history Jeffreys tie estimate to zero margin.
The exact weighted mean can differ from the Ridge center; both are reported.

The residual standard deviation is fitted from QB errors: **13.1317 points**.
It is not inferred from a betting line or winner probability. The distribution
is a final-margin model including overtime, not a joint score or drive model.
Totals, team totals, first halves, live and quarter-point contracts remain outside
this model's scope. Missing outcome support fails instead of borrowing another arm.

`Model cover probability` is the exact distribution mass satisfying
`final home margin + home handicap > 0`. `Sim cover probability` counts the same
settlement in 100,000 actual margin draws. Push mass is retained separately.
Away handicaps negate the supplied home handicap. CHI +3.5 therefore uses
`--home-spread 3.5`; the corresponding PHI line is -3.5.

NumPy PCG64 uses a seed derived from the frozen reference/model/code identity and
draw count. Market lines and prices do not enter that identity or generation.
All alternate lines use the same frozen draws. Comparisons are separate files.

## Current-event execution

Resolve the requested date through a fresh source-bound event package, preserving
original source times. Verify the schedule against official sources and the source
freshness budget before execution. Use `scripts/prepare_nfl_event.py` for a new
package and bind the latest eligible weekly state with the existing validated
state path. The small source-receipt serialization fix from PR49 is included here
so valid weekly-state metadata is not mistaken for a source download receipt.

For September 28, retain the sealed Week 2 parent (`e962a66b…`), 32 games. Week 3
Sunday results cannot advance Monday's parent. Preserve unresolved Chicago QB
conditions separately, with no invented scenario weights or starter confirmation.
The retained September 28 source capture was 5.21 hours old at this execution,
inside the six-hour schedule budget. No old source was retimestamped.

```bash
NFL_CONTEXT_PACKAGE=/ABSOLUTE/PATH/TO/CONDITION/event_package.json \
NFL_WEEKLY_STATE_SEED_SHA256=85a125580dbe1be76cac0d0edbb889d9ec22040ae078263c49460721484718d6 \
python scripts/run_nfl_integrated.py \
  --date 2026-09-28 --simulations 100000 \
  --weekly-state-store /ABSOLUTE/PATH/TO/STATE \
  --weekly-state-id e962a66b806e2371f7890ec6bc91c57726282ea2b2467a05761c603f00d406cf \
  --qb-margin --home-spread 3.5 --output NEW_UNIQUE_DIRECTORY
```

This writes the unchanged QB winner output, then a separately identified margin
forecast, exact support and weights, 100,000 `<i2` margin draws, actual-clock
registration, hashes and a comparison file with both cover columns. Existing
folders and post-start registration are rejected. Preserve every previous version.

## September 28 results

| Chicago QB condition | Selection | Model cover | Sim cover (100,000) |
|---|---|---:|---:|
| Keenum | PHI -3.5 | 47.92% | 47.94% |
| Keenum | CHI +3.5 | 52.08% | 52.06% |
| Bagent | PHI -3.5 | 47.38% | 47.19% |
| Bagent | CHI +3.5 | 52.62% | 52.81% |

Exact projected PHI margin: +2.38 points (Keenum) / +2.23 (Bagent).
The half-point contracts have zero push probability. The selected QB non-tie
winner probabilities remain unchanged; the margin distribution retains ties.

## Verification and disposition

`verify_nfl_qb_margin.py` independently reconstructs coefficients, historical
residuals, support and weights, and replays both saved arrays using an inverse CDF.
It checks the eight distribution bindings, actual registration chronology,
32-game state consumption, exact hashes, settlement signs and a synthetic QB
feature perturbation. Removing report-missingness from the diagnostic feature
record has zero effect on the QB distribution. The feature perturbation is a
unit/sensitivity probe, not an alternative real forecast. Original frozen bytes
remain unchanged.

The historical screen evaluated 1,615 games, 11,305 fixed-line contracts. Candidate
CRPS 7.291716 versus rounded-normal reference 7.291450; paired season-bootstrap
95% interval for the difference [-0.012152, +0.012457]. The 90% interval covered
91.33%. The preregistered improvement screen **did not pass**. At fixed +/-3
probes, average push mass was 2.87% versus 7.31% observed; at +/-7 it was 2.53%
versus 3.84%. There was one zero-mass observed contract; clipped log loss and the
zero count are both retained. Do not call this calibrated integer spread pricing
or evidence of betting advantage. Half-point computation does not eliminate
uncertainty about the fitted margin shape.

Execution COMPLETED; predictive validation HOLD; publication INELIGIBLE;
canonical prospective eligibility false; wagering authority OFF. Historical
execution and engineering checks do not grant predictive validation. Prospective
promotion requires a separately preregistered untouched cohort and the existing
review gates; this task does not invent that approval or clear global health RED.
Postgame comparisons must reference these immutable identities and preserve
research-only grading status; they cannot enter the primary winner denominator.
