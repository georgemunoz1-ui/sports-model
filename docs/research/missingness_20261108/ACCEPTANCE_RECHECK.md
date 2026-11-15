# Missingness acceptance recheck — November 8, 2026

Reviewed PR #117 at `53f889b054b1e779664204b8f3284fed3ec36b33` and repaired two engineering defects. This is a draft-branch verification, not deployment, predictive qualification, or completion of every acceptance criterion.

## Defects repaired

1. Hosted Missingness assurance run `42489907554` stopped during dependency installation: the included NFL requirements pinned pytest 8.4.2 while consolidated requirements also pinned 8.3.5. Keep the single existing NFL pin. A fresh Python 3.12 virtual environment successfully installed consolidated requirements. Changes to dependency files now trigger missingness CI.
2. Native NFL receipts retained CIN–ATL reporting-state dominance, but HTML omitted the attribution and shared Markdown contained no missingness section. Both presentations now display the retained per-arm/head components, model/version, simulation evidence, and unresolved terms. The dated NFL runner embeds its already verified native receipt so its real output retains that evidence. Link-scale contributions remain distinct from probability changes; absent evidence is unavailable, not zero. Unknown shared-model dominance remains unassessed.

The new renderer does not change fitted predictions, inputs, distributions, draws, contracts or release authority. Existing artifacts are not rewritten.

## Exercised evidence

- Fresh consolidated environment installed successfully; pytest 8.4.2, NumPy 2.3.5, scikit-learn 1.8.0 and SciPy 1.17.0.
- Full suite: `python -m pytest -q tests research/tests` — **2,356 passed**. The subsequent dated-wrapper addition was checked with **15 passing** NFL runner/presentation tests; counts overlap the full suite.
- Focused missingness/runtime/release/workflow checks: **127 passed** before the dated-wrapper addition.
- Release, promotion and readiness selftests all passed.
- An independent reviewer reproduced the original display omission with the retained fixture, checked actual runner and release invocation, and independently passed the 15 final NFL runner/presentation tests. Separate standalone CBB companion inspection passed 5 checks. This is engineering review, not an authorized statistical review signature.
- Actual integrated CIN–ATL retained-input replay completed with **100,000 draws**, marked `RETROSPECTIVE_DIAGNOSTIC`. All five arm outputs, features, selected predictions, simulation metadata, joint-law state and assimilation matched the earlier same-cutoff run. Winner draw bytes matched exactly. HTML readback passed and displayed `REPORTING_STATE_DOMINATED`. The independent reviewer separately verified the native receipt, dated wrapper, exact HTML hash, byte-identical draws and reconciliation of all head contributions; QB changes were zero and no registration was created.
- The combined home-margin reporting-presence contribution is **−8.013630686687792 points** (home is Atlanta). This is a diagnostic input attribution, not an injury-value estimate. See `cin_atl_readback.json`.

## Acceptance disposition

| Requirement | Verified scope | Remaining dependency |
| --- | --- | --- |
| 1. Inventory every runner and arm, including CBB | Main research inventory and separately identified branch routes exist; standalone CBB has companion #111 | Companion branches and their parent model branches remain unmerged; production-wide deployment is not established |
| 2. Reviewed feature contracts | Receipts expose feature use, imputation and pending support; NFL has per-arm fitted terms | Shared contracts remain PENDING, reviewed limits absent, approved review registry empty |
| 3. Applicable sensitivity/failure tests in each runner | Inspected shared/NFL/CBB paths invoke audit/readback; engineering tests exercise failure and isolation | Some derived/child paths explicitly report CHILD_SENSITIVITY_NOT_ESTABLISHED or PAIRED_PARENT_AND_STUDY_REQUIRED; do not call every product cleared |
| 4. Current output attribution | Corrected HTML and shared Markdown; native dated NFL receipt retained; CIN–ATL actual replay verified | Paired attribution requires a valid earlier receipt; absent comparison remains explicit |
| 5. Unsupported cases cannot become official selections | Inspected current release, promotion and readiness paths deny absent scoped approvals | Approved signatures and witness configuration are operational prerequisites, not populated by this repair |
| 6. Model-specific evaluation and forward monitoring | Separately versioned NFL report-count candidate and earlier chronological study retained | No held-out intervention activations, no established improvement, and no approved forward cohort; candidate stays off |
| 7. Independent verification of invocation | Reviewer inspected real paths and exercised tests; no inspected official-selection bypass found | This does not approve uninspected branch integration, protected deployment, or statistical release |

PR #117 is stacked on runner hardening. Companion PRs #111–#116 preserve the separate CBB, matrix, combination, personnel, event-refresh and joint-route workstreams. No merge, model promotion or wagering activation is included.

Pinned-environment health remains RED: 6 failures and 7 warnings, including frozen-lineage/successor verification, unavailable production pitcher archive, overdue recovery, historical release eligibility and standing-health evidence. Software test success does not clear those claims. Local health generated audit files were excluded from the patch.
