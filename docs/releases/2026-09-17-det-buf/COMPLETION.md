# Detroit at Buffalo — September 17, 2026

## Completion

**COMPLETED_RESEARCH_NOT_OFFICIAL.** The new event package was persisted, hashed, sealed, uploaded before the primary integrated run, executed for 100,000 binary winner draws, and replay-verified. Action authority remains OFF; dose is 0.0.

Event: `2026_02_DET_BUF`. Kickoff: September 17 at 5:15 p.m. PDT / September 18 at 00:15 UTC.

## Primary results

Selected model: `nfl.integrated_context.qb.v1.research`.

| Output | Buffalo | Detroit |
|---|---:|---:|
| Analytical winner probability | 58.5779175173% | 41.4220824827% |
| 100,000-draw winner simulation | 58.763% | 41.237% |
| Winner draws | 58,763 | 41,237 |

These are binary non-tie probabilities. Monte Carlo standard error is 0.15577 percentage points; the model/simulation difference is 0.18508 percentage points. Simulation samples the model probability and is not independent predictive validation.

Separate Ridge-head diagnostics: Buffalo home margin +2.8039428305 points; total 52.0279385791. These are not joint-distribution score expectations. No joint score simulation or ATS/total settlement probability was issued for the selected QB arm. Its frozen score residual pool is unavailable; the combined-arm pool was not borrowed.

Other analytical comparison arms, not replacements for the selected default: base 60.8170% Buffalo; availability 58.5992%; travel 61.6945%; experimental combined 57.4997%. Selected winner and margin heads agree in direction. Calibration is not established by this run.

## Completed checks and repair

The original missing-date error was resolved for a new, explicitly selected September 17 package. The September 14 frozen package and default pointer were not rewritten.

A second defect was reproduced: `live_features` passed mandatory Week 2 assimilation evidence to a recovered-feature firewall that rejected it as `UNKNOWN_CONTEXT_DIMENSION`. The repair verifies the evidence first, removes only the reserved assimilation key from that feature-binding call, and retains unknown-dimension and market-input refusals.

All 108 NFL tests passed locally and in the preparation job, including eight added admission/refusal regressions. Model coefficients, state-update rules, production defaults and action permissions were not changed.

All 16 Week 1 finals reconciled against the captured schedule and play-by-play. Team state and 37 game/passer QB aggregate records were assimilated. Frozen-state hashes and reconstructed live features were verified. This is research state-flow proof, not complete official-gamebook clearance.

A separate post-run diagnostic removed Week 1 state updates while retaining the same current context: Buffalo probability was 59.3507530958% without those updates versus 58.5779175173% with them, a -0.7728355785 percentage-point change. This demonstrates numerical use of the updates, not predictive improvement.

Official final inactive lists, current official depth charts and injury reports, official schedules, and the kickoff-hour NWS stadium-area forecast were retained with raw-byte hashes. ESPN scoreboard acquisition failed with HTTP 403; the failure was preserved. Provider market metadata remained quarantined, with no verified bookmaker/quote time and no predictive market overlay.

Personnel scope matters: final inactives were verified, but injury/workload proxy features do not numerically enter the selected QB arm. Unverified workload, actual travel itinerary, full reserve-status coverage and new-field-specific effects were not invented.

## Chronology — September 17 Pacific time

| Stage | PDT | UTC |
|---|---|---|
| Official/current source retrieval | about 4:45:18 p.m. | 23:45:18 |
| Research pre-execution writer seal | 4:56:48.841722 p.m. | 23:56:48.841722 |
| Immutable input artifact created | 4:56:50 p.m. | 23:56:50 |
| Primary integrated-run cutoff | 4:57:23.168324 p.m. | 23:57:23.168324 |
| Primary output registration | 4:57:23.546788 p.m. | 23:57:23.546788 |
| Exact replay verification completed | 4:57:25.111300 p.m. | 23:57:25.111300 |
| Completed output artifact created | 4:57:27 p.m. | 23:57:27 |

The preparer computes recovered-head validation diagnostics before the seal. The seal and external artifact receipt precede the requested primary integrated CLI run and simulations; they are not represented as canonical release authorization.

## Evidence and persistence

Repository: `georgemunoz1-ui/sports-model`.
Branch: `codex/nfl-det-buf-20260917-sealed-run`.
Executed source commit: `a5733ce8717afb922e666f537e1e54996f366c6d`.
Workflow run: `35289006699`.

Input artifact: `10525098218`; ZIP SHA-256 `5117e28c7026e4ce08b11cd51da5abff755d26d67b56b017066cd7b54d348366`.
Completed artifact: `10525312986`; ZIP SHA-256 `12babe78049b69d07e41dfd4568b36c9f0fe41d511d73dd796364f7a19b52074`.
Event package SHA-256: `f39e1fa968b7b1ea78b141d784c83726c7f7147635be08374ba9e1d942c1910d`.
Primary forecast-file SHA-256: `d9ae74cb122fb8d09fe5f05a6d856b01fbffd9813642066a8e47aeca0dac228e`.
Forecast identity: `b1326932a2baf78bfea08c55309ebc8ea573dd12afce2d771096726cd39654df`.
Winner-array file SHA-256: `a7b23ad17dc91ac0705ef581697a6e59525bc42e82f5d4dbefbeeadebf9abde4`.
Seed: `15515975723517109339`.

The complete archive includes source bytes, package, before/after states, model/code archive, source and output manifests, the pre-execution seal, external receipt, primary and replay forecasts and arrays, tests, and retained health evidence. All 33 input-manifest entries and 51 completed-manifest entries were independently rechecked after download. The winner array files replay byte-for-byte; forecast JSON files retain their distinct real cutoff/registration times.

A new research registry entry is retained at `data/nfl/run_registry/20260917_det_buf_research.json`. Analytic and Monte Carlo evaluation references are distinct. No outcome or grade has been invented. GitHub artifacts have 90-day retention, expiring December 16, 2026; the downloadable archive is supplied separately for retention.

## Remaining governance and metadata limitations

Global health/recovery obligations, official-gamebook clearance and canonical prospective release eligibility remain unresolved. The output is research-only, not an official cleared card. Main was not modified or merged by this work.

The frozen extraction metadata label `HUMAN_REVIEWED_FIELDS` is imprecise: extraction was reviewed by the assistant, not an independently documented human reviewer. This note corrects its interpretation without changing frozen bytes.
