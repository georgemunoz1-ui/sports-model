# Selected-path market-independence audit — 2026-10-22

The reviewed feature paths do not consume sportsbook prices as fitted predictive
features. That is **not** an unconditional end-to-end independence result:
unfiltered event/package metadata can alter simulation identity and draws. The
explicit NFL market ensemble and live prior are market-informed by design.

Audit baseline: main `90daf8e0036c67a5304aa0747bf50b2266e0b364` and PR74
`bd6205e0109190dec0fb47452d0f484dca203574`. The numerical paths below are identical
on those revisions. Added disclosures/tests do not change model code, fitted
parameters, seeds, selection defaults, frozen forecasts, experiments or ledgers.

## Selection and numerical lineage

Selection is `scripts/generate_card_force.py:load_adapter/generate` → league
adapter → `pipelines/cards/selected.py:apply_default`, with evidence hashes
checked by `pipelines/cards/selection.py:select`. NFL also has the separate
`scripts/run_nfl_integrated.py` entry point. Inspect the mode, exact model ID,
package selector and target; neither the league name nor a reporting flag is
sufficient evidence.

| League and routed identity | Historical/contextual numerical inputs and fit | Winner | Margin | Total | Market boundary |
| --- | --- | --- | --- | --- | --- |
| NFL: `nfl.integrated_context.qb.v1.research` | `base_features.py` derives EPA, success, explosive, protection, neutral pass rate, pace, point differential, rest, venue/roof/weather and experience from schedule/PBP state. `features.py:qb_features` adds shrunk QB EPA and change features; `runtime.py:live_features` binds eligible current weather/rest and QB state. `model.py:fit` uses training-only median imputation, scaling, logistic/Ridge heads. | Selected logistic non-tie home-win probability; Bernoulli draws. | Separate Ridge diagnostic in `result.prediction.home_margin`; shared selected QB card leaves `projected_margin` null. | Separate Ridge diagnostic `total_points`; shared card leaves `projected_total` null. | `runtime.py:run` rejects explicit market packets in research mode. Selected QB has no joint-score residual sampler. Combined/availability/travel arms are separate research identities. |
| CFB week 2+: `cfb.fbs.elo_form_logit_ridge.v1_0.shadow` | `scripts/prepare_cfb_current.py:prepare` replays `harness/cfb_v1_port.py:build_state`, adds eligible results, fits median/scaler/logistic and Ridge on FBS-v-FBS outcomes. `models/current/cfb.py:feature_row` reads Elo/regression/HFA, scoring/margin EWMAs, rest, neutral site and conference flag. | Logistic fitted head; Bernoulli draws. | Independent Ridge home-margin point estimate; card reorients to predicted winner. | No fitted selected total head; null. | No price/line feature read. Current QB/personnel effects are not included just because reports exist. |
| CFB week 1: `cfb.fbs.elo_context_logit.v1_0.week1_shadow` | `harness/cfb_forecast_0829.py:build` fits the lean Elo/home-advantage, neutral-site, conference subset. `models/current/cfb.py` can consume a matching lean package. | Opener-specific logistic head. | Legacy lean Ridge diagnostic. | Unavailable. | Legacy script reads the owner relay to enumerate events and computes implied/EV/spread disagreement **after** predictions. The current package builder selects week-2-plus; an opener cannot silently use that identity. Regression uses a synthetic matching opener package, not a new authentic opener refit. |
| WNBA: `wnba.rs.ff7_logit_ridge.v1_0.shadow` | `prepare_wnba_current.py` verifies official/ESPN historical box scores and calls `harness/wnba_model_v1.py:make_rows/fit_full`. `TeamState.feats` builds shrunken net rating, eFG, turnovers, offensive rebounding, free-throw rate, rest and back-to-back differences. Total features use historical league mean scoring, pace excess and combined net rating. | Ridge-regularized logistic, existing rounding retained; Bernoulli draws. | Separately fitted linear/ridge point head. | Separately fitted linear/ridge point head. | No price feature. These point heads and winner draws do not themselves provide cover or over/under probabilities. |
| MLB: `mlb.v13.current_input.research.v1` | `models/current/mlb.py:forecast` reads team runs for/against, both starter ERA/starts/K/BB and park factor. `harness/run_v13_historical.py:v13_sim` uses frozen shrinkage, park/contact, innings and Gamma-Poisson formulas plus `engine/hfa.py`. These include fixed heuristic constants, not a newly fitted all-context model. | Selected V13 Monte Carlo estimator, with declared tie proxy. `d_logistic_2f` uses frozen fitted coefficients on run-differential and shrunk-ERA gaps and remains a separate challenger. | Run means retained; selected run-line/full-margin settlement unavailable. | Selected total is null despite internal run totals. | `apply_default` selects the V13 estimator. No odds feature. Modern current packages require `SPORTS_RESEARCH_PACKAGE_DIR`; legacy routing is discussed below. |
| NBA: `nba.initial_causal_score.research.v1` | `prepare_initial_baselines.py:parse/causal_rows/fit` uses provider final scores and eligible earlier games. `models/current/baseline.py:feature` builds scoring EWMAs shrunk toward a training prior, rest, cold-start and neutral-site indicators. Deployment heads fit outcomes via median/scaler/logistic/Ridge. | Logistic; Bernoulli draws. | Independent Ridge estimate. | Independent Ridge estimate. | Explicit `SPORTS_INITIAL_BASELINES=1` required. Registry has **no verified default**. No player model or efficiency shadow is silently substituted. |
| NHL: `nhl.initial_causal_score.research.v1` | Same baseline machinery with NHL scoring history and fitted heads; source/season scope remains separate. | Logistic; Bernoulli draws. | Independent Ridge estimate. | Independent Ridge estimate. | Opt-in research, no verified default. No goalie effect or OT/shootout joint-score capability is inferred from a winner probability. |
| MLS: `mls.initial_causal_score.research.v1` | Same scoring/rest feature construction; fitted Poisson regressors for home and away goals. | Skellam regulation 1X2 from the two rates; independent Poisson goal draws. | Home/away goal expectations are available but the adapter's exposed margin field remains null. | Sum of fitted goal rates. | Opt-in research, no verified default. Independent-Poisson assumption is not a fitted dependence model. |

NFL's PBP filter reads `wp`, not `vegas_wp` (`base_features.py:_qualifying_plays`).
The provider's [official example](https://nflfastr.com/articles/nflfastR.html#example-5-win-probability-calculator)
shows unchanged `wp` when the spread changes, while `vegas_wp` changes. This
supports the field distinction, not provenance certification of every historical
provider file. EPA and QB-state lineage, original availability times and current
package eligibility remain separate checks.

## Explicit exceptions and limits

### MI-001 — NFL market-aware modes (intentional)

`models/nfl/modes/runtime.py:market_values` proportionally de-vigs moneylines,
negates the home spread for expected home margin, and reads the total line.
`core.py:ensemble` computes `w * football + (1-w) * market` per target.
The decoded, hash-checked `data/nfl/modes_v1/market_model.json` has football
weights **winner 0.0, margin 0.0, total 0.1**. Thus this saved research mode's
winner and margin are fully market-derived, and its total is 90% market-derived.
It is `nfl.market_ensemble.v1.research`, not the selected QB model. Perturbation
tests verify all three outputs and both simulation arrays change while its
football reference remains identical. No independent edge is implied.

`models/nfl/modes/runtime.py:live` passes the de-vigged pregame home probability
through `core.py:state_features` as `pregame_logit` into the fitted HGB outcome
model. Score, clock, possession, field position, down/distance and timeouts are
the live nonmarket features. Changing the prior changes the tested prediction.
Changing only spread/total leaves those features and analytic probabilities
unchanged but still changes the full-packet RNG identity. This is a categorical
winner model, not a drive or score simulator.

### MI-002 — embedded metadata can change RNG (OPEN)

The following paths hash more than numerically consumed nonmarket features:

| Path | Material entering seed identity | Demonstrated effect |
| --- | --- | --- |
| `models/current/common.py:emit` | Entire event plus raw package hash | CFB/WNBA/NBA/NHL fitted heads unchanged; retained winner draws change. |
| `models/current/mlb.py:forecast` | `inputs.package_sha256` plus starter/team dictionaries | Selected Monte Carlo probability and retained run/winner arrays can change. |
| `models/current/baseline.py:forecast` MLS branch | Entire event plus raw package hash | Fitted Poisson rates/1X2/mean total unchanged; retained goal arrays change. |
| `models/nfl/contextual/runtime.py:run` | Entire event and admitted context (plus artifact/features/code) | Extra event market metadata changes winner draws with identical selected QB head predictions. |

The current package loader validates code/model hashes but does not reject every
extra market field. Tests change only `market_quotes` in an event or package,
recompute the actual serialized package hash through the real loader, and keep
the fitted state, model ID, nonmarket fields, count and cutoff fixed. These are
accepted payload counterexamples, not injected price coefficients. They also
show why unchanged `input_snapshot_hash` alone is insufficient.

This audit deliberately leaves the numerical identity functions unchanged.
The requested separation holds for market sidecars outside predictive package/
event identity, but not for arbitrary embedded metadata. A follow-up remedy
should reject market-bearing predictive envelopes before inference or define a
new versioned semantic RNG identity while preserving old replay. Do not silently
strip fields, repin frozen packages, regenerate historical draws, or label these
counterexamples a universal independence pass. The tests explicitly assert the
open behavior so a future repair must update its evidence and status together.

Source-receipt hashes can also change when otherwise equivalent provider files
carry different odds. This audit's fixed-state tests do not establish invariance
of an entire reacquisition/refit pipeline or original training provenance.

### MI-003 — legacy MLB route is pinned and currently stale (not a live acceptance)

Without `SPORTS_RESEARCH_PACKAGE_DIR`, the MLB adapter loads
`data/mlb/current_v1/runtime.json`, pointing at the September 14 package.
`_load` checks every pin before constructing the legacy form/starter path.
The retained package's adapter pin is
`62c6e5ae46a286994216e1636c4640ef072bdd0cdd00e39a89b745e67e8e4ae7`, while
the reviewed adapter bytes hash to
`95cdbf3e028012a865e14d1ddbba2a3954c48488abe394f76044ec49063d05d5`.
The healthcheck pin also differs. That route cannot pass its existing full pin
check at this revision; this audit does not bypass it. Its numerical source
trace is `build_board_0825.starter` + retained form + park → `v13_sim` and
`candidate_p` → `apply_default` selecting V13. The executed seven-league regression
uses the source-bound **current-package** MLB path, not a claimed replay of this
stale legacy package. Authentically refreshing the package remains separate work.

## Downstream comparison and reporting

`pipelines/cards/distribution_research.py:build` first derives a separately
identified residual distribution from a frozen parent's point estimate and a
fitted residual model. Contracts are priced afterward by
`models/common/discrete_research.py:price`; the draw seed derives from the
distribution identity, not the contract line/odds. All seven league contracts
are tested for both margin and total with 100,000 draws: changed quote prices
and lines leave distribution and draw bytes identical while contract
probabilities change. Those synthetic tests do **not** create missing fitted
products for the selected live models. NFL spread calibration likewise is an
explicit downstream combined-arm research overlay, not a selected QB product.

`pipelines/cards/market_provenance.py` adds path attribution and the open seed
limitation to shared, separate NFL pregame and standalone disclosure sidecars.
Unknown identities remain unreviewed; explicit market-informed identities or a
true market-input declaration are never labeled market-free. Model IDs support
source-path attribution only, not artifact authenticity. Frozen parent cards
remain unchanged. Grading no longer invents `market_features_used: false` when
the producer supplied no declaration; it records null and an explicit
`NOT_CERTIFIED_BY_REPORTING_FLAGS` status. The runner's overlay-off flag is scoped
to the absence of its attached comparison layer.

The supplied screenshots and external GameChampAI probabilities are not model
inputs. PR74's external budget/method audits remain separate. No unsupported
winner, cover, total or availability probability is introduced.

## Validation and release scope

`tests/test_selected_market_independence.py` executes actual loaders, adapters,
selection, numerical functions and retained-draw serializers with fixed model
state and nonmarket inputs. Six league packages are synthetic; NFL uses the
retained historical fitted artifact. All use 100,000 draws. No forecast function
is mocked and no current-game forecast is registered. CFB opener package routing
is separately exercised. Full historical dataset refits are not executed.

The local restoration was matched to upstream Git blob identities for reviewed
sources. It lacks much of the full historical tree, so its healthcheck cannot
certify repository health. Prior PR74 CI at `bd6205e` independently recorded
726 passing tests and then failed artifact upload on storage quota; durability
passed. Neither establishes predictive validation. The added focused workflow
runs tests directly and uses logs/job summaries without requiring artifact
uploads; the existing full-suite and durability workflows are preserved.

See `docs/releases/2026-10-22-market-independence/acceptance.json` for local test
counts, source hashes and scope. Execution of the audit is complete; universal
simulation independence remains HOLD (MI-002), predictive validation is
NOT_ASSESSED, publication/model-promotion eligibility is NOT_EVALUATED, and
wagering/action authority remains OFF.
