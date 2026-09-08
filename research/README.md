# Offline benchmark primitives — diagnostic development

Run `python3 -m unittest discover -s research -p 'test_*.py' -v` from repository root.
Python standard library only. No packages or weights are downloaded. No production modules
are imported; there is no scheduler, market overlay, registry writer, or promotion function.
This is code-level separation, NOT a security sandbox for future third-party inference code.

## Implemented

- Canonical JSON SHA-256, rejecting nonfinite values.
- Flat numeric/null feature allowlist; forbidden market/outcome names checked across all rows.
- Per-feature known-at timestamps, timezone-aware pregame cutoffs, unique event IDs.
- Expanding chronological folds with label-availability filtering and reserved holdout boundary.
- Binary and multiclass log loss/Brier (explicit class order; MLS H/D/A supported).
- State MAE/RMSE, seven-quantile pinball loss, 50/80/90% coverage and interval widths.
- Reproducible paired date-cluster bootstrap, refusing mismatched populations.
- Model-intake validation for identity, hashes, review statuses and disabled operational access.

## Limits and remaining work

These functions are evaluation building blocks, NOT a complete model runner. The caller must
validate rows before splitting, freeze dataset/feature/fold/config manifests before evaluation,
predeclare target class order, primary metric, minimum effect, horizon, timezone and seed.
Timestamp claims require source evidence: this validator cannot prove the claims are true.
No feature-name denylist can detect disguised leakage; source-level PIT auditing is mandatory.
Date clusters preserve same-day dependence, not serial dependence between dates.
No primary winner is selected; no holdout is evaluated or consumed by these utilities.
Missing/failed predictions block paired comparison instead of improving scores by attrition.
Zero realized-class probability is an explicit scoring failure, not a silently clipped loss.

Still pending: model adapters and verified checkpoints; native rolling/shrunk, logistic and
boosted-tree runners; shared train-only imputation; latency/memory and failure-class reports;
calibration slope/intercept/reliability curves; CRPS; serial-block uncertainty; immutable report
CLI and holdout access ledger. No real-game benchmark or performance claim has been produced.

## Candidate intake queue (names supplied by owner; NOT independently verified)

Toto-2.0-22M: first state challenger. TabICL classifier: first tabular challenger.
Granite TTM-R3: cost/quality comparator. Chronos/Mitra: comparators only if pinned locally.
TimesFM/Moirai: licensing review first. PitchPredict: separate long-horizon research.
Every candidate currently has checkpoint revision, weights hash, code revision, dependency lock,
and license review PENDING. No download or operational use is authorized by this queue.
Separate team quantiles do not define a joint score distribution.

## Validation scope

Synthetic tests exercise implementation contracts, not sports predictive performance.
Full repository health remains unverified because the available local checkout is incomplete.
Incumbent models, registered experiments, historical artifacts and action authority are unchanged.
