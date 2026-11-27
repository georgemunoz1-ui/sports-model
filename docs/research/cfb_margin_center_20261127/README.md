# CFB margin-center: revised exploratory protocol

Status: EXPLORATORY_DESIGN_NOT_REGISTERED. No fitting, new forecasts, grading, model replacement, action authority or promotion in this change.

This proposal addresses the seven design refinements requested on November 27. The machine-readable design is in protocol.v1.json. The retained November 27 13-fixture audit is discovery evidence only. Identical features and a center-dominated gap are not validation of overprojection. The existing empirical distribution and KNN256 joint score are separate model procedures with separate fit and calibration populations. The October efficiency-joint Brier result does not belong to KNN256.

## Seven refinements
1. H1 is descriptive model disagreement with no validated outcome evidence. Do not use the small, potentially unrelated Nov 20 result as CFB evidence.
2. Arm C learns its calibration from earlier chronological out-of-fold A predictions, with a further disjoint earlier residual-calibration window. No in-sample predictions, future label or market inputs.
3. Exactly one primary endpoint and contrast: event-weighted margin CRPS, B minus C. Signed favorite-margin bias and slopes diagnose mechanisms; they do not constitute additional primary outcomes.
4. Fixed-sequence confirmatory testing of B-C then B-A only upon success; D2-D1 and C-A and bin/metric comparisons are prespecified descriptive. All bins share A's frozen predicted absolute margin; minimum 30 matched games and five distinct weeks; show counts for thin bins.
5. Proposed minimum useful improvement is 0.25 CRPS points; plan power at -0.50 challenger-minus-control. Require upper interval endpoint < -0.25, not merely <0. Define practical equivalence, matched-center convergence and mixed center/coverage/width outcomes explicitly. These values require review and freeze before confirmation.
6. Matched D1/D2 fit population is the per-fold event-ID intersection of both admissible point-model training populations with exact identities/features/outcomes and chronology. Keep calibration separate; the 698-game residual bank is not the common point-fit population.
7. Registration block deliberately incomplete: no pilot B-C paired CRPS losses, no powered sample size or fixed untouched confirmation window yet. Do not infer them from unrelated historical tests or 13 discovery fixtures. See the power procedure and registration blockers in protocol.v1.json.

## Implementation boundaries
Maintain frozen incumbent A and native B identities; chronological reconstructions have separate artifact IDs. Use full margin distribution CRPS, one score per event, no market-derived inputs. Retain the complete eligible population and refusals; score explicitly matched subsets, never silently condition on available outcomes. No confirmatory claims without actual source, chronology, population, power, code and timestamp receipts. The proposed 95% coverage and interval guardrails are planning assumptions, not observed results. Research can proceed without waiting for production release or canonical grading; prospective claims require verified chronology and the registered protocol.

The user-reported commit 0dff6ece could not be resolved in the accessible repository. Do not reinterpret the reported no-fit conformance exercise as a native model validation. CBB total mean-bias registration remains blocked by missing historical cohort evidence. No current code or release files are changed.
