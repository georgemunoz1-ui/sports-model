# Model default selection and product scope

Updated October 23, 2026 Pacific / October 24 UTC. The policy is still [data/model_selection/defaults_v1.json](../data/model_selection/defaults_v1.json). This documentation update does not modify that registry, fitted coefficients, source evidence or wagering gates.

```bash
python scripts/model_defaults.py
python scripts/model_defaults.py --league cfb --week 2 --division FBS_VS_FBS
python scripts/model_defaults.py --league wnba --target total
```

| Scope | Research presentation default / available path | Do not infer |
|---|---|---|
| NFL winner | Selected QB integrated-context arm | Combined-arm residuals or calibrated spreads belong to this winner procedure |
| MLB winner | Frozen V13 current-input research profile; MC-only | An analytic estimate exists, or NO_PROMOTE has been overturned |
| WNBA | Selected FF7 winner/margin/total family with target-specific evidence | Regular-season evidence automatically qualifies postseason, players or every offered line |
| CFB FBS/FBS, Week 2+ | Selected Elo/form logistic/ridge family | Its margin point estimate supplies a qualified cover law or fitted total head |
| CFB FBS/FBS, Week 1 | Separate opener-specific profile | Pooled all-week performance substitutes for opener evidence |
| NBA/NHL/MLS | Explicit initial research baselines; no verified automatic default | Missing default means no executable research adapter exists |
| CFB/NBA efficiency and joint increments | PR #78 experiments are evaluated research, not selected defaults | A merged feature-rich challenger is predictively superior |

## What changed since the September guide

The earlier claim that CFB/WNBA shared-card adapters were absent is obsolete. Current adapters, source package builders and the shared runner exist. NBA/NHL/MLS are accessible with an explicit `--initial-research-baselines` research opt-in. Fresh inputs and exact scope remain mandatory; this flag is not qualification.

The PR #78 comparisons did not establish a winner-Brier improvement for either efficiency challenger. NBA efficiency also worsened margin MAE, and NBA joint v2 worsened winner Brier in the evaluated population. Keep the original baseline/control and HOLD these challengers. Numerical results, intervals, populations and identities are in [current status](CURRENT_STATUS.md) and the [original report](research/efficiency_2026_10_23/SWARM_RESULTS_2026_10_23.md).

## Selection rules that remain in force

A selected model is scoped to a league, target, cohort, procedure and evidence version. Winner selection never transfers automatically to spread, total, props, first-half, regulation/OT, postseason or another sport. Changed features, transformations, calibrators or selectors need separately identified evaluation. A new version cannot erase unresolved ancestor defects or inherit performance without justification.

Software tests and simulation counts do not choose a champion. Compare exact common-event populations chronologically, retain exclusions and abstentions, evaluate selectors separately from forecasters, and account for dependence and inspected alternatives. An interval including zero does not establish either superiority or equivalence.

Owner authorization for integration/promotion was recorded in [PR #78](https://github.com/georgemunoz1-ui/sports-model/pull/78); it does not supply missing qualification evidence. Current challenger qualification remains HOLD/SHADOW. No automatic promotion, release clearance or real-money activation is granted here.

## Historical evidence is preserved

The complete September 16 selection document, including its historical sample sizes, scores and test counts, is preserved verbatim in [history](history/2026-10-23-status-refresh/MODEL_DEFAULT_SELECTION.md). Do not relabel those counts as newly measured October results. The machine registry and [state.json](../state.json) remain authoritative for their existing policy fields, not evidence of current slate freshness.
