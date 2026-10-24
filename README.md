# Sports Model Research System

Forecasting and simulation research across **NFL, CFB, NBA, WNBA, MLB, NHL and MLS**. The core market products are **moneyline, spread/run line/puck line, and totals**. Availability and qualification are specific to each model, population and settlement contract.

**Navigation refresh: October 24, 2026 UTC.** Implementation reviewed at [`cb06cb5`](https://github.com/georgemunoz1-ui/sports-model/commit/cb06cb561a37661b129f79c7d6c19f3a52055725), the merged PR #79 documentation checkpoint. No newer model commit was present at inspection. The research results below remain the October 23 evaluations, not a new forecast or backtest.

> **Research/paper only. Wagering authority OFF.** Merged code, executable research, predictive qualification, current data, repository health and verified archival are separate statuses. No automatic promotion or proven profitability ranking is claimed.

## Current project views

| Start here | Contents |
|---|---|
| [Status dashboard](docs/dashboard.html) | Seven-league coverage, completed integrations, evidence counts and named blockers |
| [Model breakdown](docs/model_breakdown.html) | Actual model families, core-product boundaries and NBA regression results |
| [System workflow](docs/core_breakdown.html) | Source capture, inference, settlement, selection, registration and grading |
| [Detailed current status](docs/CURRENT_STATUS.md) | Evidence-scoped implementation and operational status |
| [Recent changes](docs/RECENT_CHANGES.md) | Merged milestones and separately identified open research PRs |
| [Runner commands](docs/CONSOLIDATED_MODEL_ACCESS.md) | Setup, required packages and executable research entry points |
| [Documentation index](docs/README.md) | Full navigation, governance, research designs and preserved history |

The HTML files are standalone reader views; linking them does not deploy a GitHub Pages site. Their July/August predecessors are preserved exactly in [dashboard history](docs/history/2026-10-24-dashboard-refresh/). Older dated reports are evidence snapshots, not live status pages.

## Model and core-market coverage

| League | Current research path | Important product boundary |
|---|---|---|
| NFL | Selected QB contextual winner; separately named combined, market-informed and live arms | Combined score/spread residuals cannot be borrowed for the selected QB; selected-QB margin completion remains on open PR #69 |
| CFB | Selected Elo/form family plus evaluated matchup-efficiency challenger | FBS/week scope applies; the selected current parent has no total head; joint/personnel increments stay separate |
| NBA | Explicit initial causal-score baseline plus evaluated possession-efficiency v2 | No qualified automatic default; efficiency winner Brier is inconclusive and joint winner Brier worsened |
| WNBA | Selected FF7 research family and current shared-card adapter | Winner, margin and total evidence is target-specific; regular-season evidence does not automatically extend to postseason |
| MLB | Frozen V13 current-input research profile | Winner probability is Monte Carlo-only; winner selection does not qualify full-game run-line/total or extra-innings settlement |
| NHL | Explicit initial baseline and source-season repair | Affected recommendation eligibility remains suspended; fitted rest, goalie and overtime/shootout qualification remain unresolved |
| MLS | Explicit initial Poisson regulation score path | Three-way home/draw/away; regulation and extra-time/quarter-handicap contracts must stay distinct |

The [default-selection registry](data/model_selection/defaults_v1.json) and existing model parameters are unchanged. See [selection scope](docs/MODEL_DEFAULT_SELECTION.md) and [runtime requirements](docs/ALL_MODELS_CURRENT_RUNTIME.md).

## Recent integrated work

[PR #78](https://github.com/georgemunoz1-ui/sports-model/pull/78) integrated independent CFB/NBA efficiency experiments, component-level forecast receipts, source reconciliation, chronological common-event comparisons, separate selector diagnostics, opt-in local SHADOW logging and the NFL kickoff-date repair. It did not promote the challengers.

[PR #75](https://github.com/georgemunoz1-ui/sports-model/pull/75) repaired diagnostic winner identity matching. [PR #76](https://github.com/georgemunoz1-ui/sports-model/pull/76) connected numerical identity, lineage, selection and evaluation controls to real runners and archive hooks. [PR #77](https://github.com/georgemunoz1-ui/sports-model/pull/77) added first-registration preflight without fabricating forecasts or grades. [PR #72](https://github.com/georgemunoz1-ui/sports-model/pull/72) added availability and dependence disclosures.

[PR #79](https://github.com/georgemunoz1-ui/sports-model/pull/79) refreshed the README and operator guides; its [consolidation run](https://github.com/georgemunoz1-ui/sports-model/actions/runs/40071113060) passed **1,367 tests**. This follow-up updates the remaining outdated HTML entry points. [File-level scope and verification](docs/updates/2026-10-24-dashboard-refresh.md).

## Executed challenger results

Binary single-class Brier; lower is better. Deltas are challenger minus control with retained paired chronological-block bootstrap intervals.

| Candidate | Common events / opportunities | Brier delta | 95% interval | Disposition |
|---|---:|---:|---|---|
| CFB matchup efficiency | 1,045 / 1,196 | +0.000453 | [-0.001894, +0.002705] | HOLD; improvement unestablished |
| NBA possession efficiency v2 | 2,458 / 2,460 | +0.001298 | [-0.000971, +0.003499] | HOLD; improvement unestablished |
| NBA joint-score v2 | 2,458 / 2,460 | +0.003833 | [+0.001456, +0.006366] | HOLD; worse on this winner metric |

NBA efficiency margin MAE also worsened by **0.151969 points**. Preserve the control and these negative/inconclusive results; new formulas need separate identities and earlier-only fitting. Repaired retrospective analyses remain diagnostic, not untouched confirmation. [Original results](docs/research/efficiency_2026_10_23/SWARM_RESULTS_2026_10_23.md) and [integration addendum](docs/research/efficiency_2026_10_23/INTEGRATION_STATUS.md).

Evidence counts: **3,503 unique common events**, **7,006 candidate-stage receipts**, and **58 local SHADOW registrations across 17 unique games**. Multiple versions and simulation draws do not increase the independent-event denominator.

## What remains open

The latest retained [canonical preflight](data/grading/canonical/operations/preflight-39999394059-1.json) has zero registrations and no settlement. Local SHADOW logging is not canonical registration. Archive hooks remain `BLOCKED_UNCONFIGURED`; no verified remote upload is implied by passing CI. [Storage contract](docs/CI_STORAGE_ARCHIVE.md).

The [55-failure/four-warning inventory](docs/HEALTH_RECONCILIATION_2026_10_23.md) is from a partial local checkout; it is not directly comparable with the separately recorded hosted health report. No health issue is closed by a documentation change. Open PRs #68, #69, #70, #71, #73 and #74 remain separately identified in the inspected checkpoint.

The [saved October 23 card](docs/cards/2026-10-23-1531-PT.md) is a 19-row repricing-only snapshot, not live odds or fresh inference. The separately described external `joint.py` and synthetic agent-package claims are not certified integrated. [Cross-sport formula and market research agenda](docs/RESEARCH_ROADMAP.md).

## Setup

Use a complete checkout and Python 3.12:

```bash
python -m pip install -r requirements-consolidated.txt
python -m pip install --no-deps -e .
python scripts/model_defaults.py
python -m pytest tests research/tests -q
python harness/healthcheck.py
```

These are usage commands, not executions performed by this page. Keep software tests and health results separate. Acquire fresh source-bound packages before inference; a missing package is not a verified empty slate. Read [AGENTS.md](AGENTS.md), [operating workflow](docs/OPERATING_WORKFLOW.md), [state.json](state.json) and the append-only [progress journal](docs/progress.md). Frozen forecasts, policies, authorizations, historical records and workflow schedules are not changed by this documentation refresh.
