# Opt in Monte Carlo precision research

This research runner consumes an existing `sports.discrete_distribution.research.v1` law or selects a law from a hash-validated `sports.distribution_card.research.v1` report produced downstream of the shared-card adapters. It does not call, refit, reseed or replace a selected forecasting engine. Frozen model defaults and the legacy `discrete_research.simulate` implementation remain unchanged.

## Run

From the repository root:

    python scripts/run_mc_precision_research.py \
      --distribution path/to/distribution_report.json \
      --event-id 'CFB:401858254' \
      --model-id cfb.margin.empirical.research.2a9cf9fcd1774e8e \
      --product margin --line -3 --side HOME \
      --experiment-id precision-comparison-001 --seed 722 \
      --output path/to/new-research-directory

The example identifiers are from the retained historical test fixture, not a current forecast. Use actual IDs in your source report. A standalone distribution does not require selectors unless you want an explicit identity check. A report with multiple matches refuses instead of guessing. The output directory must not already exist.

Default: exactly 100,000 draws, alpha 0.05 and absolute numerical tolerance 0.005 (0.5 percentage points). The default does not promise this precision for every law. To allow additional draws, explicitly predeclare `--checkpoints 100000,200000,400000 --tolerance 0.003`. The final checkpoint may not exceed 1,000,000. The run stops only at a declared look when all declared category bounds meet tolerance, or at the cap with `BUDGET_EXHAUSTED_UNRESOLVED`.

To compare two distinct source model IDs, add `--comparison-distribution path/to/other.json` and, if selecting from a report, `--comparison-model-id ...`. Both laws must have the same event, cutoff, league, product and settlement. Identical source model IDs are rejected. The additional research simulation identity is `SOURCE_MODEL_ID::sports.discrete_mc_precision.research.v1`; source identity and input distribution hashes remain intact.

## Output and guarantees

`report.json` retains the exact-law five-category settlement probabilities, observed estimates, simultaneous numerical intervals at each reached look, actual draw count, input file hashes, implementation hashes, stream identity and each arm's draw receipt. `arm_0_draws.npy` and optional `arm_1_draws.npy` retain sampled integer margin or total paths. Paths are marginal draws, not fabricated joint home/away scores. The canonical receipt uses float64-C bytes while the saved NPY file uses int64; each explicitly declares and hashes its own encoding.

The line/side classify existing support only. No sportsbook odds enter sampling. Existing source distributions can have their own information set; this tool does not certify them market-blind. Category probabilities are exact only under the supplied fixed finite law. No parameter refit or extra parameter uncertainty is added by this engine. It does not repair missing support, calibration or historical provenance.

Shared uniforms are assigned to the versioned `finite_score_inverse_cdf.v1` component. Event, experiment, root seed and replicate define the stream, so increasing budget preserves prefixes. Two arms share these uniforms but retain separate identities. Coupling reduces variance only when covariance helps; numerical comparison is not evidence of predictive superiority.

The empirical-Bernstein family allocates alpha over both tails, all five categories per arm, all five paired differences when present, and every predeclared look. It assumes independent identical paths under the fixed input law. Dependence between endpoints or arms within a path is allowed. The low-level module refuses declared RQMC/antithetic/nested-reuse designs; passing an IID label is a caller assertion, not independent evidence. The bound is not an unbounded-horizon confidence sequence and is not a forecast prediction interval.

All outputs retain `action_authority=false`, `prospective_grade_eligible=false`, `predictive_validation=NOT_ASSESSED`, and publication ineligibility. This research command cannot promote, publish or place a wager.

## Verification

    python -m pytest -q tests/test_mc_precision_research.py tests/test_discrete_mc_adapter_compatibility.py

Coverage includes all seven league settlement schemas through the actual discrete module, unchanged source laws and legacy draw hashes, actual retained CFB downstream report selection and CLI execution, paired prefix invariance, quarter-line/push settlement, duplicate identities, event/cutoff/scope mismatch, source corruption, output overwrite refusal and the fixed 100k minimum. The retained fixture is historical diagnostic evidence, not a new prospective forecast.

Theory: Maurer and Pontil, Theorem 4, https://www.cs.mcgill.ca/~colt2009/papers/012.pdf. Stream guidance: https://numpy.org/doc/stable/reference/random/parallel.html. Broader time-uniform alternatives: https://arxiv.org/abs/1810.08240.
