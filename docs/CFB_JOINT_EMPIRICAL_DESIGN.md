# CFB joint final-score challenger, v1

Registered for development on 2026-10-03 before this evaluation is executed.
Identity: cfb.joint_final_score.knn256.v1.research. Incumbent remains unchanged.

Fixed method: 256 equally weighted nearest historical FBS/FBS Week-2+ score
pairs using the incumbent's ten causal pregame features, median imputation and
standardization fitted on training rows only. Historical features retain their
original lineage. No prices or current-event results are features. Scores are
observed final scores including whatever overtime the source reported, with no
continuous rounding, fabricated tie-breaking, or extra scoring process.

Screen: train through 2023; reconstruct 2024-25 evaluation without adapting on
evaluation outcomes. Compare the same ten-feature logistic control on matched
events. Report Brier, log loss, margin/total MAE, central-80% coverage and 2,000
season-week cluster bootstrap draws. Historical feature availability is not a
prospective PIT attestation and reused historical seasons are not an untouched
program-level holdout. No automatic promotion. Future acceptance requires a
registered prospective cohort and target-specific cover/total calibration.

Operational run: train score library through 2025; consume a fresh, hash-bound
incumbent team-state package and its numerical feature values. Retain score
support, all 100,000 paired score draws and input/state hashes. Reject expired
packages and post-start events. This produces a separate challenger card.

Handicap and total curves are hypothetical thresholds, not sportsbook quotes.
Integer thresholds expose empirical push mass. Mathematical settlement support
does not prove probability calibration or exact sportsbook contract compliance.

Weather and personnel are absent from the historical training frame. They remain
unconsumed until source-bound historical observations, identity mappings, and a
chronologically fitted transform exist. Never replace missing context with zero
or inject guessed point adjustments to claim closure. ACTION OFF.
