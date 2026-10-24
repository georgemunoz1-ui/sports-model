# Qualified external-report adaptations

This is a method and reporting audit, not a model promotion or an outcome-driven
refit. The owner supplied two GameChampAI reports on October 21, 2026 and asked
that their best qualified elements be adapted. Their stated original run times,
source facts, rosters, fitted parameters and simulation draws were not independently
authenticated. No forecast probability from either report enters our predictors.

## Qualification decisions

| Element | Decision | Adaptation |
|---|---|---|
| Explicit minutes budgets | Implemented as arithmetic audit | NBA regulation 240, WNBA regulation 200; per-player limits, duplicate allocation and reported OUT conflicts; roster truth remains separate. |
| Player/team and pass/rush/TD conservation | Implemented as arithmetic audit | Sum named terms against the same component target, with declared rounding precision; flag different component identities instead of silently rescaling. |
| Prior-season-only and component-only controls | Implemented as report arithmetic; model experiments still proposed | Compare named probabilities on the identical event/side/line/settlement; display method range, never scenario counts as a calibrated failure probability. |
| Unknown versus assumed versus confirmed availability | Reuse merged PR72 | Structured knowledge states, conditional scenarios and exact parent binding already exist. |
| Honest unsupported props and parlay dependence | Reuse merged PR72 | Expected values are not hit probabilities; joint-draw arithmetic is separate from sampler replay and predictive validity. |
| No double injury/home/defense adjustments | Retain in challenger specification | Minutes replacement and fitted impact must not also receive an unexplained multiplier; implement consumption proof before claiming use. |
| Player-led scoring, pace, opponent context and shrinkage | Candidate only | Need source-bound historical minutes/rates, fitted construction and untouched chronological evaluation. Neither attached report provides a qualified executable fit. |
| CFB market-anchored mean/total and first-score heuristic | Reject as independent model features | Preserve one original as contrast evidence. Compare benchmarks only downstream. |
| Re-anchor the distribution at every alternate market line | Reject | Freeze the independent law once, then price each contract against that same law. A market-informed arm needs a distinct identity. |
| 50/50 OT winner without OT scores | Reject for full-game spread/total settlement | A winner assignment does not generate final scoring/push distributions. |
| 40% 3PM haircut, loser −3%, BRI/TTS/psychology boosts, display caps | Reject as numerical adjustments | No fitted evidence supplied. Raw probability must not be replaced by a cosmetic confidence cap. |
| NBA 50/50 blend, sigma 12, correlation .30, HFA 2.5; CFB sigma/fallbacks/85–15 TD split | Do not adopt constants | Possible sensitivity settings, not qualified coefficients. |
| ≥5 pp edge, zero of 44 failures, ≤4 pp method range | Do not adopt thresholds | Predeclare and evaluate an offline policy; this grid is neither a random sample nor an exhaustive model-uncertainty distribution. |
| Public splits / “book liability” | Exclude from generation | Shares do not establish net book exposure or sharp information. |

## Executable integration

The new `projection_audits` optional event field in the PR72 disclosure packet
now accepts audits implemented by `pipelines/cards/projection_audits.py`. The shared
all-seven runner, separate NFL pregame runner and standalone disclosure CLI already
use this common path. An omitted field adds no numerical computation to the model.

Each audit has an `audit_id`, a relative `source_artifact: {path, sha256}`, and at
least one of `minutes_budgets`, `allocation_checks`, `method_sensitivities`. The
actual source bytes must match. Parent event/model/input bindings remain mandatory
at the existing disclosure event level. Unknown fields, malformed values, duplicate
IDs, path escapes, bad hashes, changed contracts and invented method weights fail
closed. Independent events continue with an explicit PARTIAL result.

Minutes rows: `team_id`, `component_id`, `basis: REGULATION`, and `players` with
`entity_id`, `minutes`, optional `reported_availability: IN|OUT|UNKNOWN`. These
are regulation allocations, not expected minutes including overtime. Only NBA and
WNBA have minutes rules here. Sources: NBA Rule 5 (12-minute periods), WNBA FAQ
(10-minute quarters): https://official.nba.com/rule-no-5-scoring-and-timing/ and
https://www.wnba.com/faq . Other leagues can use generic allocation/sensitivity
checks without inheriting basketball budgets.

Allocation rows: `check_id`, `unit`, `source_component_id`, `target_component_id`,
`terms: [{entity_id, value}]`, `target`, optional `rounding_step` in
`{0, .001, .01, .1, 1}`. One rounding unit applies to each term and the target;
the maximum rounding tolerance is `(number_of_terms + 1) * step / 2`. Different
components produce `NOT_COMPARABLE_COMPONENTS`, not a repaired distribution.
Negative terms are unsupported by this nonnegative budget interface.

Sensitivity rows: `sensitivity_id`, `contract`, `variants`. Each variant has its
own exact matching `contract`, `method_id`, and `probability`. Contract keys are
`event_id`, lowercase `league`, `product: winner|margin|total`, `settlement`,
`side`, `line` (null for winner). Spread lines remain home-handicap oriented.
The output is the supplied named-method minimum, maximum and percentage-point
range. Missing methods are not invented. It is not a blend, a confidence interval,
a probability of failure or a predeclared decision rule.

All audit inputs are caller-extracted claims. A byte hash does not authenticate
their extraction, provider, roster, timestamp or predictive quality. Audits may
describe externally supplied reports acquired after kickoff because they are
reporting-only; they cannot become pre-cutoff known inputs or change a frozen
forecast. `source_facts_verified` and `point_in_time_verified` remain false.
Arithmetic PASS is not forecast approval. An arithmetic mismatch is a finding;
the audit can execute successfully while documenting that mismatch.

## Results on the supplied reports

NBA: both declared rotations sum to 240. Displayed player points sum to 122.5
(Minnesota) and 125.9 (Miami), compatible with reported component expectations
122.38 and 125.94 within one-decimal rounding. Those two component expectations
sum to 248.32, not the separately reported 248.43; the 0.11 gap exceeds their
two-decimal rounding tolerance. The 248.32 player component and 240.33 blended
game total differ by 7.99 points and remain separate component identities.

Miami winner: the two supplied named methods are .617 and .550, a 6.70 pp range.
Under 242.5: the primary/player-only/ratings-only probabilities are .545/.379/.701,
a 32.20 pp range. The report additionally claims a wider 32.67%–70.11% range and
44 scenarios. Those 44 individual rows are absent; the 37.44 pp summary was not
represented as a recomputed grid. No new Monte Carlo run or original replay is
claimed. The stated equal-variance joint-normal assumptions imply zero
margin-total covariance; they do not establish realistic joint dependence.

CFB: the two pass/rush play budgets and two named/FIELD TD-lambda budgets reconcile
arithmetically (including stated rounding). They remain conditional bookkeeping;
player allocation is blocked in the source itself. The mean margin and total are
explicitly market anchored, so none qualifies as independent predictive evidence.

The newly supplied NMSU–SHSU original fulfills the pending request to archive one
market-anchored contrast card. The original bytes and SHA256 receipt are retained
with the user-facing adaptation evidence, linked to the preceding diagnostic
journal; no earlier missing file is claimed recovered.

## Next numerical challenger, not yet activated

Candidate design: current-player minutes and rates -> conserved team possessions,
usage and scoring -> separately fitted joint margin/total distribution. Keep the
existing team model unchanged as control. Use prior-season-only as a declared
ablation; estimate recency/sample shrinkage and blend weights on training folds,
not from the reports or October 21 outcomes. Track roster churn and whether
preseason inputs transfer to regular-season performance. Do not reuse unsupported
team/player identities or unconfirmed minutes as facts.

Before activation: source-bound historical rosters and minutes, numerical feature
consumption evidence, fitted state, registered identity/design, same-event/time
chronological comparison, proper scoring/calibration/tail/coverage guardrails,
power/precision and multiplicity plan, and untouched prospective shadow evidence.
Missing coefficients/data leave this candidate NOT_RUN. The proposed recipe is
not a fitted player engine. No active experiment, model default, historical
forecast, certified ledger or wagering authority is changed by this patch.
