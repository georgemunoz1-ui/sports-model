# Offline benchmark primitives — diagnostic development

Run `python3 -m unittest discover -s research -p 'test_*.py' -v` from repository root.
Python standard library only. No packages or weights are downloaded. No production scheduler,
market overlay, registry writer, canonical-ledger writer, or promotion function is imported.

## Implemented

- Canonical JSON SHA-256, rejecting nonfinite values.
- PIT feature/timestamp contracts and label-aware chronological folds with reserved holdout boundary.
- Binary/multiclass log loss and Brier; state MAE/RMSE, pinball, coverage and interval width.
- Reproducible paired date-cluster bootstrap that refuses mismatched populations.
- Model-intake validation for identity, hashes, review status and disabled operational access.
- Read-only frozen-artifact adapters for MLB, CFB and MLS.
- Deterministic `evaluate_frozen_forecasts` CLI with immutable content-addressed reports.

## Frozen-artifact evaluation

The runner reads only artifacts explicitly named by a frozen manifest plus an append-only outcome
JSONL ledger. It never writes forecasts, grades, model state, registries, or canonical prospective
ledgers. A source hash is checked on read and checked again after report generation.

```bash
python -m research.evaluate_frozen_forecasts \
  --forecast-manifest manifests/sept_6_local_diagnostic.json \
  --grade-ledger ledgers/sept_6_local_grades.jsonl \
  --scope LOCAL_DIAGNOSTIC \
  --league mlb \
  --output-dir reports/evaluation \
  --report-date 2026-09-07 \
  --fail-on-unexpected-row \
  --write-canonical-rows
```

Outputs live at:

```text
<output-dir>/<scope>/<canonical-row-dataset-sha256>/<report-hash>/
```

and include `evaluation_report.json`, `evaluation_report.md`, `evaluation_manifest.json`,
`evaluation_manifest.sha256`, `excluded_rows.csv`, `validation_failures.csv`, and optionally
`evaluation_rows.jsonl`. Existing byte-different output collisions fail closed. The report hash is
SHA-256 of canonical report content before its self-identifying hash fields are appended.

`LOCAL_ONLY` source evidence maps only to `LOCAL_DIAGNOSTIC` and can never be emitted as canonical
prospective eligible. `REMOTE_DURABLE_PROSPECTIVE` must be explicit and eligible. Mixed evidence is
refused unless a combined descriptive report is explicitly requested; that mode has no promotion
or canonical-ledger authority.

## Metric contracts

Binary reports expose both conventions:

```text
binary_brier_single_class_mean   = mean((p_home - y_home)^2)
binary_brier_multiclass_sum_mean = 2 * binary_brier_single_class_mean
multiclass_brier_class_sum_mean  = mean(sum_k((p_k - y_k)^2))
```

Partial frozen quantiles are never reconstructed. A P10/P90-only artifact can report P10/P90
pinball and 80% central-interval coverage. Missing 50%/90% interval fields are
`NOT_AVAILABLE_IN_FROZEN_ARTIFACT`. Full seven-quantile rows additionally call the existing
`state_scores` primitive.

MLB winner grading may remain available under the frozen artifact's disclosed tie proxy, while
score/margin/total metrics are excluded after extra innings when the model target is regulation-only.
No final-score substitution is performed.

CFB paired comparisons require identical event identity, cutoff, evidence scope, outcome target,
shared universe hash, and complete one-row-per-arm/event populations. An incomplete population is
rejected, never filtered. Fewer than two independent date clusters yields
`NOT_RUN_INSUFFICIENT_DATE_CLUSTERS` instead of a confidence interval.

MLS emits explicit H/D/A rows only after identity-valid grading. Quarantined identity failures and
postponements cannot enter multiclass scoring.

## Limits and remaining work

These functions are evaluation infrastructure, not a challenger inference runner. Timestamp claims
remain dependent on the frozen source evidence; structural chronology validation cannot prove a
source claim independently. Calibration slope/intercept/reliability curves, CRPS, serial-block
uncertainty, holdout access ledger, baseline model runners and verified challenger checkpoints remain
pending.

The de-identified Sept. 6-shaped fixture proves adapter/report compatibility only. A real Sept. 6
scorecard requires the retained machine-readable append-only grade ledger; narrative closeout text is
not reconstructed into grade rows. No real-game performance claim is made by this PR.

## Candidate intake queue

Toto-2.0-22M, TabICL and Granite TTM-R3 remain `INTAKE_PENDING`: checkpoint revisions, weight hashes,
inference revisions, dependency locks and license/data reviews are still pending. No download,
operational use, promotion or action authority is granted.

## Validation scope

Synthetic/de-identified tests exercise implementation contracts, not sports predictive performance.
Full repository health remains unverified until this draft is exercised in a complete checkout.
Incumbent models, registered experiments, historical artifacts and action authority remain unchanged.
