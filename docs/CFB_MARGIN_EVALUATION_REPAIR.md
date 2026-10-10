# CFB margin evaluation repair (local review)

Base reviewed: `b5ab679c73dae0e698b835c03aa091d2b279dba6`.
This is an evaluation-safety repair, not a fitted model release, promotion, or
retroactive certification. No historical model/forecast/default/ledger is changed.

## Additive correction to earlier evidence

The original `models/cfb/fit_margin_distribution_v1.py` fitted the mean head on the
first 80% of rows. It estimated global and weekly residual scales on the remaining
20%, then reported probability Brier on those same outcomes. That probability
score reused calibration outcomes and is **not untouched holdout performance**.
Mean-head MAE/RMSE did not fit the mean coefficients on those outcomes; they can
remain holdout diagnostics conditional on correct source chronology and feature
provenance. Do not blanket-label those mean diagnostics as in-sample.

The original fitter trusted row order and merely recorded `--as-of`. The retained
legacy table inspected here actually is kickoff-ordered, with timezone-aware UTC
`kick` and no duplicate `game_id`; this audit does not claim observed shuffled data
or prove historical look-ahead. It lacks original feature/label availability
metadata, so the stronger point-in-time claim cannot presently be established.

The table has 36,901 rows, of which 17,472 are FBS-v-FBS. The old fitter did not
filter divisions although its output declared FBS-v-FBS. The repair filters the
explicit division columns. The archived output remains unchanged; its population
claim must not be silently transferred to a new candidate.

The old workflow's declared date windows never reached the fitter. Its overlapping
training/validation defaults cannot describe an independent three-way evaluation.
Both fit workflows now require all six window bounds, pass them through environment
variables, and use the new migrated input path. The old push-triggered workflow
runs regression tests only; fitting needs explicit workflow-dispatch windows.
Python/package versions, mathematical feature coefficients, frozen runtime defaults,
and simulator implementation have not been changed by this patch.

## New fitting protocol

- Explicit inclusive UTC calendar-date windows, ordered train, calibration, test.
  No data-selected default split, and no silent row dropping/imputation.
- One row per canonical source event ID; duplicates are rejected. Entire FBS
  season-week groups stay together, including groups partly outside a window.
- Sort by timezone-aware kickoff and event ID before all fitting/scoring.
- Feature availability must precede kickoff; label availability must follow kickoff.
  Selected kickoffs must precede `--as-of`; selected labels must be available by it.
- Every train label is available before the first calibration kickoff, and every
  calibration label before the first test kickoff. Late labels fail closed.
- Fit OLS coefficients only on train; global and weekly residual RMS only on
  calibration; retain the existing 200-row threshold for weekly residual scales.
- Evaluate the fixed mean and residual model only on test. Analytic normal-CDF
  Brier uses the exact weekly-scale/global-fallback selection of `monte_carlo_v1`.
  It is not a Monte Carlo sampling accuracy experiment.
- Record explicit event cohorts, hashes and UTC boundaries. Never refit on test
  after scoring. Candidate stays `SHADOW_CANDIDATE`, version `1.1.0`.
- Exclusive new output files only. Existing output paths or identical output paths
  are rejected. A crash can leave a partial new output; use a fresh directory to
  retry. Existing artifacts are never replaced by this command.

“Test” means excluded from this fitter's parameter estimation. Previously inspected
historical data do not become a fresh research holdout merely by using this code.
Freeze/register a suitable evaluation design under repository governance **before**
a genuine evaluation; do not select windows after looking at their metrics.

## Required source-backed migration (not executed)

Keep `data/cfb/model/cfb_v1_features.parquet` immutable. Create a separate
`data/cfb/model/cfb_margin_pit_features_v1.parquet` only after verifying source
history. Preserve the existing model feature values where replay is justified.
The migrated table must include:

- `game_id`, `season`, `week`, `home_division`, `away_division`
- Existing target, Elo, neutral-site and conference-game columns (documented aliases
  are accepted); all finite, neutral/conference binary and season/week integral
- `kick`: original source kickoff with an explicit timezone
- `feature_available_at_utc`: latest original availability of **all** contributing
  pregame inputs/state dependencies, timezone-aware and strictly before kickoff
- `label_available_at_utc`: source-backed final-result availability, timezone-aware
  and after kickoff; a later retrieval timestamp alone is not historical proof
- `kick_source_ref`, `feature_source_ref`, `label_source_ref`: retained receipt IDs

Do not fabricate availability times from kickoff, assume a fixed game duration,
copy the migration/run time, or backdate current source retrievals. Existing source
`kick` does not establish when features or final labels were known. Where authentic
availability cannot be reconstructed, retain the blocker and do not refit.

Supply `cfb_margin_pit_features_v1.provenance.json` beside retained source receipts:

```json
{
  "schema": "cfb_margin_pit_provenance_v1",
  "dataset_hash": "sha256:<actual migrated parquet digest>",
  "sources": [
    {"id": "source receipt ID", "path": "receipts/source.json", "sha256": "sha256:<actual receipt digest>"}
  ]
}
```

Each source must be a local file within the manifest directory tree, hashed and
bound to row references. The code verifies byte integrity and row bindings. It
cannot prove that arbitrary supplied timestamps truly came from the receipts;
an audited source-to-column reconstruction and dependency-availability review is
still required. Include the reconstruction and source timestamp semantics in the
migration review. Hashes do not make a fabricated timestamp authentic. Emitted state therefore labels
availability as caller-asserted, source authentication as UNESTABLISHED, and
promotion eligibility false. A separate reviewed migration cannot be replaced
by changing those labels.

Do not use the retained historical input for a full refit until this migration and
the prospective/untouched design review are complete. Synthetic tests exercise
software isolation only, and establish no predictive improvement.

## Checks and remaining limits

Run focused tests:

```
python -m unittest discover -s tests -p 'test_cfb_margin_evaluation.py' -v
python -m compileall -q models/cfb/fit_margin_distribution_v1.py tests/test_cfb_margin_evaluation.py
```

The real legacy input was passed only into preparation: it correctly refused
missing original PIT columns before numerical fitting. Source digest:
`sha256:30dc3cc56cb959cd36c184877525a32ee5d75416dd11cab82d90f980c1a46b90`.
No authentic new fit or performance measurement was run.

Repository health was attempted on the available partial runtime materialization.
Missing modules/datasets/history prevent full-repository health verification;
pre-existing health obligations remain. Full CI in a complete checkout and parent
review are still required before publication. No remote branch/PR/merge was made.
