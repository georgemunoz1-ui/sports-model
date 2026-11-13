# NBA projected-minutes residual challenger — October 30, 2026

This adds `nba.projected_minutes.residual_margin.research.v1`, a separate research
margin point estimate. It preserves the existing baseline and possession-efficiency
v2 experiments. It does not fit a minutes forecaster, assume arbitrary player point
values, create win/cover probabilities, or change the selected model.

For each player the feature is signed `(expected_minutes - reference_minutes)/48`
(home positive, away negative). The reference rotation must describe the baseline
participation assumption. A fixed-alpha ridge fit learns coefficients from earlier
**out-of-sample baseline margin residuals**, with no intercept. Consequently an
unchanged rotation produces exactly zero adjustment. Both projected and reference
rotations must sum to 240 minutes per team; missing players or replacement minutes
are refused. The regularization constant is fixed at 1.0, not tuned to October's
inspected outcomes. Twenty training events is an engineering floor, not evidence of
adequacy, statistical power, calibration, or qualification.

## Inputs and independent evidence states

Every row contains `event`, `baseline`, `personnel`, and (only for fitting/grading)
`result`. The input schemas are implemented in
`models/experiments/nba_personnel.py` and illustrated by the synthetic fixture in
`tests/test_nba_personnel_minutes.py`.

- Event: stable event/home/away IDs, prestart cutoff, authoritative start, and team
  names for a shared-card join.
- Baseline: exact model/state identity, frozen margin, earlier training IDs and
  maximum result-availability time, explicit `personnel_adjustment_included:false`,
  `reference_rotation_policy:"BASELINE_PARTICIPATION_REFERENCE"`, forecast source,
  `state_source`, and `training_source`. The exact numeric fitted-state object
  must hash to `state_sha256`; training metadata must bind that same hash.
- Personnel: `roster_by_team`, roster source, and a complete `players` list. Each
  player has team/player IDs, explicit status, expected/reference minutes, the two
  construction methods, scenario assumptions, and status/minutes sources.
- Result: observed home margin, availability timestamp and source. A result source
  may not predate its declared availability or arrive after the fitting cutoff.

A source reference requires `path`, SHA256, `provider`, `source_uri`,
`retrieved_at_utc` and an RFC6901 `data_pointer`; `provider_updated_at_utc` is
nullable. Bytes are read back and hash-checked. They must decode as an
`nba-personnel-normalized-evidence.v1` envelope whose provider/URI/timestamps
exactly match the receipt. The pointer must select the exact expected
role/event/values object. Baseline, training, fitted state, roster, each player's
status and workload, and result all have independent semantic bindings. Balanced
minute changes, altered outcomes, parent margin/state/training edits or a pointer
to another role fail even when source hashes remain valid. Retrieval must precede the forecast cutoff, and provider update may
not follow retrieval. These checks bind source bytes and declared timing. **They do
not authenticate providers, verify raw-to-normalized extraction, certify external
historical presence, or establish that a baseline excludes every indirect personnel
effect.** Those remain distinct review requirements; all outputs say
`provider_authenticity:NOT_ASSESSED`, `pit_eligibility:NOT_ASSESSED`.

`UNKNOWN` status blocks. QUESTIONABLE/DOUBTFUL/LIMITED requires a named ACTIVE or OUT
scenario and assumptions. Such output is conditional; scenarios are never mixed
with invented weights. Conditional training rows and outcome comparisons are
refused until actual scenario matching exists. Unseen players with a nonzero
minutes delta block instead of silently assigning zero impact. Unseen players with
zero delta contribute no change under the stated reference-rotation procedure.

Numeric features exclude current-event outcomes. Fit state seals the training
population, residual targets, source evidence, fixed method and code hash. Prediction
rejects reused training events, a fit at/after forecast cutoff, mixed baseline
procedures, changed code/state, boolean/nonfinite values and incomplete rotations.
Component receipts show every consumed feature and its point contribution.

## Executable interfaces

Historical manifest: `schema:"nba-personnel-experiment.v1"`,
`evidence_scope:"TEST_ONLY"` or `"HISTORICAL_RECONSTRUCTED"`, `fit_cutoff_utc`,
`training` rows and strictly later `evaluation` rows.

```bash
python scripts/run_nba_personnel_experiment.py \
  --input /absolute/path/experiment.json --output /new/output/directory
```

The runner writes immutable state, forecasts, matched rows, exclusions and a report.
It reports paired margin MAE only. Point summaries do not establish improvement;
registered dependence-aware evaluation and untouched confirmation remain required.
Missing/insufficient training yields a retained BLOCKED report and CLI exit 2.

For shared-card use, `research.efficiency.nba_personnel_runner.shadow_from_card`
accepts `(card_path, config_path, output)`. Configuration is:

```json
{
  "schema": "nba-personnel-shadow.v1",
  "state": {"path": "fitted-state.json", "sha256": "EXACT_FILE_SHA256"},
  "inputs": {"path": "event-inputs.json", "sha256": "EXACT_FILE_SHA256"}
}
```

`event-inputs.json` uses `schema:"nba-personnel-inputs.v1"`, `rows:[...]`.
Each baseline additionally binds `parent_forecast_sha256` to the exact parent row.
The sidecar verifies that hash, `numerical_identity.fitted_state_sha256`,
event/team/start/cutoff, model ID and margin against
the existing shared-card row. Missing event inputs get explicit BLOCKED rows.
Outputs are separate; the parent card is never edited. A completed sidecar is
DIAGNOSTIC, not canonical prospective SHADOW registration.

## Executed scope and open dependencies

The new tests exercise 22 synthetic training events and two later synthetic matched
events, the real CLI, sidecar join, refusal paths, numerical consumption and output
immutability. This is software evidence only. Existing NBA efficiency tests also
pass; no frozen source or fitted artifact was modified.

No qualifying real projected/reference-minutes training archive was located in the
checkout. Actual personnel fitting and predictive evaluation remain BLOCKED pending:

1. Complete source-bound historical and current rotations, statuses and timestamps.
2. A defensible projected-minutes construction and baseline reference-rotation policy.
3. Frozen out-of-sample parent forecasts and observed outcomes on matching events.
4. Raw-source parsing/reconciliation and independent provider/PIT evidence.
5. Registered matched evaluation with dependence-aware uncertainty and confirmation.

No code deployment, current forecast refresh, qualification, allocation or wagering
change follows from the implementation. Wagering remains OFF; allocation zero.

## Independent-review correction

The first draft verified source bytes without binding consumed values. Independent
review reproduced accepted balanced-minute, result and parent-field mutations.
The successor requires exact normalized role/value and metadata bindings, plus
parent fitted-state and training evidence. Regression tests retain those mutation
classes. This closes the reproduced binding defects; upstream provider
authentication and original PIT presence remain independently unresolved.
