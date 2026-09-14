# Dedicated halftime and paired-score research capability

Model: `nfl.halftime_joint_ridge.v1.research`. This is a new research arm, not
a correction, calibration, or replacement of prior football/market forecasts.

Four Ridge heads (fixed alpha 50, median imputation, standardized existing 100
pregame features) predict first-half home/away points and remaining home/away
points. Remaining points include any overtime present in the final-score labels.
Each simulation samples one same-game four-dimensional, expanding-year OOF
residual. This retains empirical dependence between halves. Scores are clipped
at zero and rounded to integers. It is not a scoring-event or fitted key-number
model. A final tie is not resolved by a coin flip or another overtime simulation.

## Data and chronology

2,895 regular-season games, 2015–2025. First-half labels reconcile the final
Q2 post-play score with the first Q3 pre-play score for every game. Source row
order matters: inserted timeout records can have non-chronological play IDs.
The initial sorted-ID extraction wrongly excluded 41 games and is invalidated.
The correction changes extraction only; no model hyperparameters were retuned.

Expanding-year OOF residuals start in 2019. The evaluation mean model is fitted
through 2022 and its residual bank uses 2019–2022 OOF predictions only. Test:
816 games from 2023–2025. Deployment research means are refitted through 2025;
the deployment residual bank has 1,871 OOF games from 2019–2025.
Historical source corrections and feature-availability limitations remain.

## Evaluation: lower is better

| Metric | Dedicated | Half-scaled full-game comparator |
|---|---:|---:|
| First-half margin CRPS | 5.76078 | 5.67358 |
| First-half total CRPS | 4.98215 | 4.91427 |
| First-half winner three-way Brier | 0.53317 | 0.52413 |
| Under 20.5 Brier, fixed-line probe | 0.24972 | 0.24370 |
| Away +1.5 Brier, fixed-line probe | 0.24246 | 0.23708 |
| Paired combo Brier, fixed-line probe | 0.21933 | 0.21891 |

Primary margin CRPS delta +0.08719; season-block 95% interval
[+0.00958, +0.16505], only three test seasons. No improvement/promotion.
Mean predicted halftime tie frequency 3.58% versus 6.00% observed.
Fixed-line probes use the same hypothetical thresholds on each historical game;
they are NOT an archive of historical first-half market quotes or a betting backtest.

## Explicit operational route

```bash
python scripts/run_nfl_integrated.py --date 2026-09-14 \
  --event-id 2026_01_DEN_KC \
  --halftime-artifact data/nfl/halftime_v1/model.json \
  --output <new-unique-run-folder>
```

The option requires the combined football feature source and a fitted artifact
with the exact halftime model ID. It writes `halftime_joint/forecast.json`,
`period_score_draws.npy` and a hash manifest alongside the unchanged football
output. It does not activate a market-aware/live model or replace a calibrated
full-game probability. Source input cutoff and new forecast creation time are
separate fields. Replay is checked before persistence. Minimum 100,000 draws.

Reconstruction:

```bash
python scripts/run_nfl_halftime_research.py \
  --source <nflverse-capture-with-2015-to-2025-pbp> \
  --features data/nfl/contextual_v1/fit_03/features.csv \
  --forecast <frozen-combined-forecast.json> \
  --output <new-unique-fit-folder>
```

Designs are local research receipts, not canonical preregistrations. The reused
test history is not newly untouched evidence. Model selection, full-game
settlement validation, key-number repair and reliable joint/half calibration
remain unresolved. Action authority stays OFF.
