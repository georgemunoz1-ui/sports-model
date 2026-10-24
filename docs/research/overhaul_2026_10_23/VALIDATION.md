# Executed validation

Date: 2026-10-23 UTC. Base: `90daf8e0036c67a5304aa0747bf50b2266e0b364`.

## Results

| Check | Result |
|---|---|
| `python -m pytest tests -q` | **886 passed in 58.78 seconds**, exit 0. |
| Independently authored adversarial suite | **49 passed**, included in the full count. |
| Selection CLI | Seven real subprocess tests, included in the full count; positive signed TEST_ONLY and empty-trust blocked paths. |
| Evaluation/card integration | Fourteen tests, included in the full count; immutable output, source/target tamper, chronology, controls and April-state visibility. |
| Research entrypoints | Selection, evaluation, rest candidate, history capture and baseline preparation `--help` commands all exited 0. |

The full test output is retained in `pytest_full.txt`. `VALIDATION.json` records
its digest, environment versions and changed implementation/test hashes. Counts
above overlap and must not be summed.

## Reproducibility and preservation

Source was restored from the connected repository at the pinned commit and each
restored file checked against its Git blob digest. Initial broad test attempts
failed on missing committed fixtures in that partial restoration. Those fixtures
were fetched unchanged; the final full-suite run above passed. Missing local
files were not patched into fabricated datasets or bypassed tests.

The remote commit is built on the original complete Git tree, replacing only
reviewed source/config/docs/test paths. Missing unmodified local files are not
deletions. Frozen forecasts, existing model weights, default catalogs, canonical
ledgers and read-only authorization history are not included in the patch.
The local health command's generated `data/audit/pregame_preflight.json` is excluded.

The original baseline, shared current-model runtime and adapters remain byte
identical to main, preserving existing package code pins. The runner adds its
diagnostics only after forecasting. Regression tests verify unchanged probabilities,
input snapshots and simulation replay behavior.

## What these checks do not establish

- Improved out-of-sample accuracy or calibration. No new predictive model is
  fitted or promoted, and synthetic signatures are not real scientific approval.
- Complete operational repository health. The initial health scan ran on a
  partial source restoration with absent history/data; that output cannot prove
  canonical full-repository health. The GitHub workflow records health separately.
- Deployed registration trust, independently authenticated outcomes, complete
  source coverage, inherited trial-family accounting or automatic drift monitoring.
- Resolution of existing overlapping PRs, including upstream stochastic market
  leakage, all distribution repairs or all player-input architecture.

The gap register and README give ownership/dependencies and closure criteria for
those items. Publication and wagering authority remain disabled.
