# Diagnostic swarm results — 2026-10-23

## Outcome and scope

The coordinator, six assigned workers, and independent verifier executed the CFB/NBA experiments, discovery reconstruction, NFL runner investigation, separate selector diagnostics, and local prospective SHADOW logging. Neither efficiency challenger demonstrates superior winner probability quality. These are reconstructed retrospective diagnostics, with post-result data-contract repairs explicitly retained. No automatic promotion, production-default change, external repository write, merge, publication change, or wagering authority was granted.

The actual remote repository is pinned at `278b9a2e655b72b720fefc215a5129a8e6cd2c93`, tree `2389a7c781598b3a947768d76096bd0c80270159`. The local source is a partial materialization: all 856 materialized original files match remote Git blob hashes. Its synthetic local Git commits are not the remote commit. Original forecast evidence remains immutable.

## Protocol and executed comparisons

The initial protocol and `swarm_protocol_v1.json` were frozen before the new run results were inspected. CFB trains through 2024 and evaluates 2025–2026; NBA trains provider seasons 2021–2024 and evaluates 2025–2026. Probability scaling, imputations and fitted parameters use earlier training data only. The primary loss is binary single-class Brier. Paired 95% intervals use 2,000 whole-week block-bootstrap samples with seed 2302026. Selector thresholds remain the predeclared grid 0.50 through 0.95 in increments of 0.05. No optimum is selected.

| Product | Paired events | Control | Challenger | Delta (challenger minus control) | 95% interval |
|---|---:|---:|---:|---:|---|
| CFB efficiency Brier | 1,045 | .18409675 | .18454937 | +.00045262 | [−.00189355, +.00270544] |
| CFB efficiency margin MAE | 1,045 | 12.793729 | 12.760060 | −.033669 | [−.149154, +.073896] |
| CFB joint Brier | 1,045 | .18409675 | .18505651 | +.00095977 | [−.00110367, +.00309803] |
| NBA efficiency Brier | 2,458 | .20990081 | .21119841 | +.00129760 | [−.00097092, +.00349871] |
| NBA efficiency margin MAE | 2,458 | 11.321077 | 11.473046 | +.151969 | [+.046957, +.261353] |
| NBA efficiency total MAE | 2,458 | 14.976434 | 14.961178 | −.015256 | [−.076987, +.048197] |
| NBA joint Brier | 2,458 | .20990081 | .21373389 | +.00383308 | [+.00145619, +.00636617] |

CFB compares 1,045 common events from a 1,196-event population over 21 chronological week blocks. NBA compares 2,458 of 2,460 events over 51 blocks. Matched-training ablations reuse exactly the candidate's 2,670 CFB / 4,660 NBA training identities; neither supports a Brier improvement. Exact offered-line ATS/price validation is blocked by missing historical market contracts and qualified discrete settlement distributions. Candidate continuous-score interval/CRPS diagnostics are retained without substituting them for push/OT validation.

## Repairs and preserved lineage

1. CFB joint dispatch now supplies separate pre-2024 fitting and 2024 residual-calibration populations and retains its actual continuous score draws.
2. NBA source normalization excludes explicitly labeled All-Star events before outcome parsing. Four out-of-scope score-control training games had created an apparent total-MAE benefit; that initial apparent gain is rejected. All prior runs remain available.
3. The independent verifier found historical NBA midnight starts whose features used event-start day but whose receipt was clipped to start minus one microsecond. The repair resolves the cutoff before all feature generation and applies it to training, evaluation, calibration and a distinctly named aligned control. The unchanged legacy control procedure stays callable. The amendment was frozen before refitting. New candidates are `nba.possession_efficiency.research.v2` and `nba.possession_efficiency.joint.research.v2`; 704 training and 352 evaluation feature rows change. Old identities/states/registrations remain untouched.
4. Component receipt builder and verifier now bind outer identity/time to retained event, model, stage and fitted-state references. Rehashed event/model/start splices are rejected.
5. NFL starter adjudication now compares an exact kickoff instant, or an Eastern game date when kickoff time is unavailable. Six rebuilt weekly transitions consume 93 games and reproduce original team/QB states. The original selected-QB NE probability is unchanged.

No candidate parameter or selector threshold was tuned to the JMU, NE or Denver outcomes. The losses are discovery cases only. The retained OKC winner forecast won while the separate Denver +8.5 contract lost. The earliest NFL winner forecast did not contain a spread distribution; later support is not backfilled into it.

## Integration and actual run identities

| Execution | Run identity |
|---|---|
| CFB historical | `cfb-efficiency-20261023T095215Z-b1d678e9` |
| NBA final historical | `nba-efficiency-20261023T100514Z-3545fd54` |
| NBA matched control | `nba-matched-training-ablation-20261023T100630Z` |
| CFB selector evaluation | `cfb-selection-evaluation-20261023T095727Z` |
| NBA selector evaluation | `nba-selection-evaluation-20261023T100644Z` |
| CFB local SHADOW | `cfb-shadow-20261023T095513Z-77fbff90` |
| Original NBA local SHADOW | `nba-shadow-20261023T095445Z-395b9c58` |
| Corrected NBA local SHADOW | `nba-shadow-20261023T100706Z-d0ae9d4b` |
| NFL QB replay | `206f0458fc0b6c805ee4ecd987c76a292512ef4a0bb22f99eaea86fb523c3961` |
| NFL combined replay | `203b8bfd0f1fb9efb64cfe976da9cfdf5f14a7817a00ef585ef870408a7a2967` |

The real `scripts/generate_card_force.py --efficiency-research-config` paths wrote 58 immutable local pregame registrations: 10 CFB, 24 original NBA, 24 corrected NBA. Each has 100,000 actual draws/trials with recorded RNG/seed/array/file hashes. Winner Bernoulli trials and continuous joint score draws remain distinct. These registrations lack an external timestamp anchor and canonical grading eligibility. No scheduled service was deployed.

Selectors were evaluated separately from forecasters. All 7,006 primary stage receipts were scored while operational eligibility stayed BLOCKED. Empty selections have null risk; abstentions are not wins; entire population coverage includes unforecastable events. The NFL selector comparison remains blocked by unrecovered per-event chronological OOF rows; existing aggregate NFL evaluations are reused evidence only.

## Validation and remaining dependencies

The final complete repository test command `python -m pytest tests research/tests -q -p no:cacheprovider --junitxml=...` passed **1,402 tests**, with zero failures/errors/skips in the retained JUnit artifact. Earlier failures from missing pinned-main fixtures are preserved; six exact upstream fixtures were restored. Separate reconstruction, point-in-time and independent adversarial audits are retained.

The global health command remains `REPOSITORY_HEALTH_RED`, with 55 failures and 4 warnings concerning unavailable legacy data/external source paths and existing release/governance debts. This is not a globally green repository claim. Scope blockers do not erase independently executable research.

Historical provider-observed timestamps remain absent; CFB's assumed 24-hour result availability and upstream EPA training chronology are not proven historical availability. Personnel stages remain blocked by authenticated pre-cutoff personnel inputs. Exact Novig screenshots, all earliest standalone source snapshots/draws, original canonical registrations and authenticated house rules were not recovered. The three case reconstructions are therefore explicitly partial despite verified finals and recovered contract arithmetic.

Complete command arrays, timings, failed and successful logs, per-event rows, states, source bytes, source mappings, SHA-256 manifests, original forecast evidence and independent reports are in the dated evidence deliverables. Source archives retain all 64 audited acquisition snapshots; dependency closure covers all 57 unique raw-source hashes consumed by the historical/SHADOW candidate runs. Repository implementation is supplied as a separate review patch. External branch/PR writes require the user's requested approval; no merge or promotion is authorized.
