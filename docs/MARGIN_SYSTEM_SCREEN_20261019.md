# Margin system screen — October 19, 2026

Implemented as an opt-in research layer across NFL, CFB, NBA, WNBA, MLB, NHL and MLS. Existing selected defaults and immutable forecasts remain unchanged. The raw model outputs stay independent of market prices.

## Historical evidence

Four retained cohorts supply 3,661 later-period games. Each challenger fits only its earlier residual cohort, selects parameters within a purged chronological inner block, and evaluates the same later events as the frozen empirical baseline. These datasets have been used in prior research, and their availability timestamps were reconstructed; this is neither an untouched holdout nor prospective evidence.

Primary score is CRPS (lower is better). Intervals use 1,000 moving two-observed-week-block bootstrap replicates. These are descriptive intervals without a multiple-testing correction.

| League | Games | Baseline CRPS | Challenger CRPS | Delta [95% interval] | Baseline → challenger zero-support outcomes | Disposition |
|---|---:|---:|---:|---|---|---|
| CFB | 714 | 9.105728 | 9.096782 | -0.008947 [-0.029832, +0.009803] | 10 → 0 | HOLD; interval includes zero |
| NBA | 1,230 | 8.259648 | 8.266216 | +0.006568 [-0.009263, +0.021327] | 4 → 0 | HOLD; interval includes zero |
| NHL | 1,312 | 1.460436 | 1.448992 | -0.011444 [-0.014475, -0.008030] | 1 → 0 | PROMISING; prospective test required |
| MLS | 405 | 0.940874 | 0.945199 | +0.004326 [+0.001083, +0.008195] | 0 → 0 | DO NOT PROMOTE; worse primary score |

The dense integer representation removed all 15 observed zero-support failures in these cohorts. Its finite support has a minimum ±256 envelope, adaptive expansion and an explicit omitted-tail bound of 1e-6; it does not make every mathematically possible score representable. Zero removal for a no-tie final contract remains explicit conditioning, not an overtime mechanism.

## October 19 demonstration

The additive card produces four unchanged NHL empirical distributions and four separately named new challenger distributions, each with 100,000 retained and exactly replayed margin draws (800,000 total). It reuses the morning fixed-parent point inputs with a 15:44:50 UTC cutoff. The challenger artifact was built later; these are newly computed research transforms, not original morning forecasts. Its winner probabilities are derived from its own margin PMF and are distinct from the incumbent winner-only card. All ladder lines are hypothetical thresholds.

The selected NFL QB row retains its SF +11.014 point margin, but a same-parent fitted margin distribution is unavailable. No cover percentage was inferred from its 81.64% winner probability. NFL, WNBA and MLB need qualifying parent-specific cohorts; the common fitting/settlement interface and synthetic software tests cover them, not predictive validation.

## Verification and operational limits

129 focused software and regression tests passed. Independent output checks verified all eight PMFs, handicap complements, draw files, exact 800,000-draw replay and study code pins. Global repository health remains unresolved: this is a partial recovered checkout with missing unrelated modules and datasets. Focused tests do not certify whole-repository CI. No production deployment, model promotion, canonical prospective registration, sportsbook quote validation or wagering authority was enabled.

Reproduce using the commands in `docs/MARGIN_SYSTEM.md`; `scripts/run_margin_system_study.py` runs the four-cohort study and `scripts/evaluate_margin_ladders.py` evaluates fixed hypothetical lines without refitting. `scripts/fit_margin_challenger.py` accepts qualifying earlier OOF forecasts for any supported sport.
