# Proposed fixed-base QB-offset challenger

Tracking: [#55](https://github.com/georgemunoz1-ui/sports-model/issues/55), workstream B.

**DRAFT_PROPOSAL_NOT_REGISTERED.** This is a reviewable design document, not a registration receipt or execution permission. It does not implement an estimator, fit a model, run an evaluation, generate forecasts or change production state. The JSON contract is [NFL_QB_OFFSET_PREREG.json](../data/nfl/contextual_v1/NFL_QB_OFFSET_PREREG.json).

The existing QB arm independently refits shared team coefficients and its intercept. The proposed challenger freezes those base parameters within each chronological fold and fits only an additive QB term with Bernoulli likelihood:

```text
eta_challenger = eta_base_raw + gamma' z_QB
p_challenger = sigmoid(eta_challenger)
```

The coefficient on the raw base logit is exactly 1. The initial proposal has no new intercept and no added calibration. It is not least squares on `y - p_base`, a probability blend or a hard rule that prevents a pick flip. Zero adjustment must reproduce the designated raw base probability within `1e-12` without changing the base artifact.

## First increment: change one thing

The proposed identity is `nfl.fixed_base_qb_offset.raw5.v1.challenger`. The initial increment retains the five existing QB transforms and shrinkage/retention rules, allowing a direct test of the fixed-offset architecture. It does not simultaneously introduce a different QB rating, new prior, clipping cap, blend, calibration or intercept.

This raw-QB candidate can still double count information already present in team strength. A starter-deviation signal remains the preferred next hypothesis, under a separate identity, once its reference QB context and as-of weighting are defined and bound to source data. The current team features do not themselves establish one exact embedded QB baseline.

The proposed penalty is `lambda=1` on the mean Bernoulli negative log-likelihood, with fold-local standardized QB features. This is a concrete proposal for review, not an optimized value or a claim that it is equivalent to an existing library's `C=1`. The optimizer and exact software configuration remain pending.

## Chronology and final-refit alignment

Each outer test block is an official NFL season-week with a cutoff before its first kickoff. The base fit, transforms and hashes are frozen for that block. Adjustment-training offsets come from inner chronological OOF base predictions made using strictly earlier rows; using fitted offsets from the final full-sample base is forbidden.

At a later prospective origin, repeat the same process: construct prior-only OOF offsets, fit the QB adjustment, fit the base on all eligible prior rows, and freeze the pair before the next block. OOF base fits have shorter histories than the final inference base. The proposal explicitly records this distribution difference and evaluates the full pairing at every outer origin; it does not claim that cross-fitting makes the distributions identical.

All imputers, scalers, priors, QB states and feature transforms are fitted or advanced using eligible prior information. No extra calibration is included in this initial candidate. Unknown or ambiguous starter identities prevent a candidate forecast; a known debutant with zero recorded dropbacks is a different state and remains eligible under the existing shrinkage formula. Failures remain visible in coverage counts.

## Exploration is not confirmation

Existing 2019-2025 arm comparisons are reused history. The October 4 cohort has already been graded and inspected; the October 5 ATL-NO forecast/flip was examined before this proposal, which is post-start. Neither cohort can become untouched confirmation evidence. No historical registration timestamp is asserted.

Confirmatory event manifests, source-time provenance, minimum populations, precision requirements and the prospective decision horizon are still pending. An untouched historical window must be independently verified; if none exists, historical work remains exploratory and confirmation must accumulate prospectively under a registered future protocol. Merely splitting known history chronologically does not undo its prior use.

## What is ready, and what is pending

| Item | Proposed disposition |
|---|---|
| Candidate, outcome, orientation | Distinct NFL regular-season home-win, conditional-non-tie candidate |
| Offset and intercept | Raw base linear predictor, coefficient 1, no new intercept |
| QB information | Existing five features for first architecture-only increment |
| Preprocessing and training | Fold-local; chronological inner OOF offsets |
| Calibration | None for the initial candidate |
| Comparisons | Same-event base, incumbent QB and challenger; paired Brier/log loss and coverage |
| Statistical review | Proposed season-week block bootstrap, two primary Brier contrasts with Holm multiplicity control |
| Known contamination | Reused history and October 4/5 excluded from confirmation |
| Data inventory, exact folds and solver | Pending verification and pinning |
| Holdout manifests, minimum samples and practical tolerances | Pending review; null fields prevent authorization |
| Registration and execution | Not performed or authorized by this document |

The CFB preregistration file supplied the structure, not NFL validity thresholds. Numerical sample sizes, practical improvement tolerances and a prospective decision horizon must be justified and frozen before confirmation; none is invented from this week's results. Review of this draft can proceed now. Actual execution still needs proof that the required historical matrix and point-in-time QB records exist and satisfy their input contracts.

Implementation acceptance includes zero-offset identity, immutable base hashes, no future-data or outer-outcome leakage, known-debutant versus unknown-QB handling, visible missing inputs and idempotent replay. Workstream A's flip diagnostics can ship independently; they neither register nor activate this challenger.

**RELEASE RED; market input false; ACTION OFF; DOSE 0.0.** Passing future research criteria would lead to a separate governance review, never automatic promotion or wager authority.
