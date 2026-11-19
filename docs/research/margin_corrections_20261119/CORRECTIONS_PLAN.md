# CFB and NFL margin and total distribution corrections: research plan

Status: PLAN ONLY. RED / HOLD / NO_PICK / ACTION_OFF / 0 official units.
This document changes no code, model, default, fitted artifact, frozen forecast or registry.
Base: main at 5e204c1aa7bb06b64684b81dd71472265d91a786.

## 1. Why this plan exists

The frozen November 19 card (Sports-Card-2026-11-19.json, SHA-256 f96cd3f06e23e9c943b3f4dea129c8024ba8a4debd703599f4fcd1287a1de0be) shows two football gaps:

- CFB Rice @ Temple: winner 59.6% (cfb.fbs.elo_form_logit_ridge.v1_0.shadow) and a margin point estimate of Temple by 3.70, but no spread probability and no total. Card warnings: SELECTED_PARENT_HAS_NO_MARGIN_DISTRIBUTION, TOTAL_HEAD_NOT_FITTED_FOR_SELECTED_CFB_ARM, QB_AND_AVAILABILITY_TRANSFORM_NOT_CONSUMED.
- NFL Indianapolis @ Houston: conditional-on-no-tie winner 72.71%, a separate margin-child cover probability (Indianapolis +12.5 at 62.92%), a total point estimate of 43.62, but no total probability. Card warnings: SELECTED_PARENT_HAS_NO_TOTAL_DISTRIBUTION, NO_SELECTED_QB_JOINT_SCORE_SAMPLER.

## 2. Findings from repository inspection

1. pipelines/margins/cfb.py (cfb_cover) already maps the ridge margin to a discrete football margin distribution with a week-segmented sigma. A code search finds it referenced only by itself and tests/test_margins_adapters.py. It is not wired into the card path.
2. pipelines/cards/margin_system.py is an opt-in research path that prices hypothetical default handicaps from retained PMFs and refuses market quotes (market_quotes_used must be False). It does not price a posted line.
3. pipelines/margins/cfb.py and pipelines/margins/nfl.py both use key-number masses labeled RESEARCH_PLACEHOLDER_EMPIRICAL_REFIT_REQUIRED. cfb_cover also needs a fitted sigma_table and artifact hash that were not found.
4. NFL margin child nfl.margin.full_support.research.ad4017ccf0663e24 (docs/NFL_QB_MARGIN_PROCESS_20261019.md): primary CRPS comparison inconclusive (delta -0.007908, 95% CI [-0.022664, +0.011302]); aggregate screen NOT_PASSED; the deployed all-history refit was not directly evaluated; no total distribution; the joint score simulator is COMBINED-specific and unavailable for the selected QB arm.
5. docs/CFB_V2_HIGH_LEVEL_BUILD.md: v1 total MAE 13.04 equals the rolling-total baseline (not validated); FBS-vs-FBS home-win Brier 0.1895 was effectively tied with ESPN pregame Elo. The document is an August plan and may be stale.
6. Draft PR #105 (joint volatility matrices) fits NBA, NHL and MLS only and records explicit blockers for CFB, NFL, WNBA and MLB. Draft PR #106 routes the card to the joint path. Both are unmerged.
7. Not established: which code path produced the NFL cover probability on the November 19 card, and the card-builder entry point that would call the adapters.

## 3. Corrections, in order

Each item ships as a separate shadow output with its own tests. None changes a default.

### C1. CFB spread probability on the posted line
- Wire cfb_cover into the card path using the captured market line as the contract line.
- Fit a week-segmented sigma_table from out-of-sample residuals (2019-2025 walk-forward, 5,856 games per the CFB v2 document); retain n, window and fallback labeling.
- Refit key-number masses from out-of-fold margins before any trust; until then keep the placeholder warning on every row.
- Keep the result labeled shadow. Market lines must not enter fitting.

### C2. NFL margin adapter and total distribution
- Refit NFL key-number masses from out-of-fold margins.
- Add a total distribution head only if it beats the registered total baselines on a preregistered chronological evaluation; otherwise keep totals unavailable.
- Evaluate the deployed all-history refit directly, or label it unevaluated on every output.

### C3. CFB total
- The v1 total head only tied its baseline. Publish a clearly labeled baseline total distribution, not a claim of model skill, unless a challenger passes its gate.

### C4. Market no-vig comparison harness
- Extend pipelines/margins/validate.py to score model probabilities against paired no-vig prices on the same held-out games (Brier, log loss, CRPS where a distribution exists, interval coverage).
- Requires retained market-priced history; none was found for CFB or NFL margin heads. Without it this step stays blocked.

### C5. Joint-score sampler for CFB and NFL
- Stack on #105 and #106; do not duplicate them. One paired-score draw set per game so winner, margin and total agree; store draws, seed, hash and distribution id; price any later line without a new forecast.

## 4. Acceptance gates for any promoted output

- Preregistration committed before fitting; chronological, purged splits; no market input in fitting.
- Out-of-sample proper scores versus paired no-vig market probabilities; no probability clipping (versioned separately if ever used).
- Interval coverage checks; ties, pushes, overtime and conditional targets kept separate.
- Fail closed on missing sigma, identity or artifact hash.
- Hosted CI green on the exact head; independent review of source and hashes.
- Release remains RED / HOLD until separately authorized.

## 5. Files expected to change in later PRs

pipelines/margins/cfb.py, pipelines/margins/nfl.py, pipelines/margins/_shared.py, models/common/margins/distribution.py, pipelines/margins/validate.py, pipelines/cards/margin_system.py, the card-builder entry point (to be located), data/nfl/contextual_v1/runtime.json, data/nfl/qb_margin_full_support_v1/runtime.json, docs/MARGIN_LAYER_PREREG.md, tests/test_margins_adapters.py, tests/test_nfl_margin_distribution.py, scripts/audit_margin_integration.py.

## 6. Sensitivity note (not a model output)

Using the repository's discrete football margin construction with an assumed sigma of 13.0 to 16.8 and the placeholder key numbers, a Temple -2.5 cover probability for a 3.70 margin mean would fall near 53-54% and a Temple win probability near 57-60%. The sigma values are assumptions, not fitted. This only bounds how large the missing numbers are likely to be.

## 7. Non-goals

No betting action, selection, unit sizing, probability cap, fade rule, default promotion, forecast rewrite or canonical registration.

## 8. Open questions

- Which entry point builds the daily card, and where should the posted line be bound?
- Which path produced today's NFL cover number?
- Where are the retained out-of-fold CFB residuals and any market-priced history for the harness?
- Has the v1 CFB implementation been ported onto the current main, per the v2 document's checklist?
