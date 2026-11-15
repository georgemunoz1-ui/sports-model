# Consumed-feature contract review — November 15, 2026

This follow-up to PR #117 closes a concrete declaration gap in the shared fitted-head audit. It does not complete statistical acceptance or authorize deployment.

## Reproduced defect

At baseline `14ccf3edacd6a5ad1463b66bbdd08582aab589e7`, the shared CFB audit accepted an undocumented feature name as `OBSERVED_TRANSFORMED`. A regression renamed the consumed `home_ewma_points_for` column to `collector_worked`, preserving all values, column positions and fitted coefficients. The receipt still declared `FITTED_HEADS_REPLAYED`. The new regression expected `TRACE_BLOCKED` and failed at that assertion before the repair.

This probe is a synthetic schema-change test. It is not evidence that the real CFB model used that invented feature.

## Repair

The registry now names every consumed column of the current initial NBA/NHL/MLS score arms and selected CFB Elo/form arm: nine initial-score columns and ten CFB columns. Each resolves to a contract with a feature definition, source, freshness requirement, missing-value representation, imputation rule, indicator usage, fallback/refusal behavior and input unit.

The receipt binds those declarations to the actual model ID, fitted-artifact hash, consumed heads and per-head medians, centers and scales. It exposes raw current values and input states. Recorded historical pre-imputation counts are shown by season where supplied; an absent count stays `UNMEASURED`. Those normalized counts do not certify provider coverage or historical publication timing.

The declarations include indirect paths: fitted league priors, history-dependent shrinkage, 14-day rest fallback, cold-history flags, normalized venue omissions, Elo 1500 defaults, absent season-transition markers and head-specific EWMA/rest medians. Unresolved normalized CFB schedule flags and season markers cannot be labeled as confirmed substantive observations in change attribution.

An unknown feature, model or fitted-head scope now makes the trace `TRACE_BLOCKED`. Head scope includes the link kind: a logistic head cannot inherit a point-head contract, and MLS goal heads require Poisson links. A second pre-fix regression reproduced that incorrect contract inheritance and then passed after the kind check. The receipt retains the exact unknown feature names. Malformed head vectors also produce a bounded trace failure. The original research forecast remains visible and unchanged. Every receipt retains `HOLD_PENDING_SCOPE_REVIEW`; no approval index or statistical threshold is populated.

## Verification and remaining scope

Dedicated tests exercise the actual adapters for NBA, NHL, MLS and CFB with synthetic fitted parameters. They check unknown-column/model/head refusal, complete consumed-column coverage, observed zero versus missing state, explicit historical-support limits, malformed vectors and numerical-row preservation. Existing shared missingness tests continue to exercise paired transforms, source failure, duplicate rejection, metadata/order invariance and bound previous editions.

This expands the engineering contract evidence for four shared packed-head routes. Native NFL, WNBA, MLB, standalone CBB and separate derived/companion routes retain their existing inventories and limitations. Their independent statistical review and model-specific forward evidence are not supplied by this change. All new contract entries remain `ENGINEERING_INVENTORY_PENDING_INDEPENDENT_MODEL_REVIEW`.
