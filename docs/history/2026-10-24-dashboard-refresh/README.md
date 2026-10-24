# Sports Model Research System

Seven-league forecasting and simulation research: **NFL, CFB, NBA, WNBA, MLB, NHL and MLS**. Core research products are **moneyline, spread/run line/puck line, and totals**; support and qualification are specific to the model, league and settlement contract.

**Documentation reconciled October 23, 2026 Pacific / October 24 UTC**, against `main` at [`15bc5b8`](https://github.com/georgemunoz1-ui/sports-model/commit/15bc5b87ee8e403589c0bf384aa4667039935db4). `main` is the consolidated code entry point, not a README-only landing branch. Dated reports retain their original checkpoint statements.

> **Research execution is not predictive qualification.** Wagering authority remains **OFF**. Selected research defaults, initial baselines, challenger results, software CI, repository health, source freshness and durable archiving are separate statuses. No validated profitability ranking or automatic model promotion is claimed.

## Start here

| Need | Current reference |
|---|---|
| Status, evidence and blockers | [Current status](docs/CURRENT_STATUS.md) |
| Recent merged and pending work | [Recent changes](docs/RECENT_CHANGES.md) |
| Installation and real runner commands | [Model access](docs/CONSOLIDATED_MODEL_ACCESS.md) |
| Selected model and product boundaries | [Default selection](docs/MODEL_DEFAULT_SELECTION.md) |
| Input preparation, current inference and scheduling | [Research runtimes](docs/ALL_MODELS_CURRENT_RUNTIME.md) |
| Agent/review/registration workflow | [Operating workflow](docs/OPERATING_WORKFLOW.md) and [AGENTS.md](AGENTS.md) |
| Cross-sport formula work still to evaluate | [Research roadmap](docs/RESEARCH_ROADMAP.md) |
| Local 55 failures / 4 warnings versus hosted health | [Scoped health reconciliation](docs/HEALTH_RECONCILIATION_2026_10_23.md) |
| Most recently supplied card snapshot | [October 23, 3:31 p.m. Pacific repricing record](docs/cards/2026-10-23-1531-PT.md) — archived, not live |
| All documentation | [Documentation index](docs/README.md) |

## What is now integrated

[PR #78](https://github.com/georgemunoz1-ui/sports-model/pull/78) merged the independent CFB matchup-efficiency and NBA possession-efficiency experiments, component receipts, source reconciliation, chronological common-event comparisons, separate selector diagnostics and opt-in local SHADOW logging. Personnel and joint stages have separate identities. The NFL kickoff-date binding repair preserves the selected QB forecast; it is not a new NE-specific predictor.

[PR #75](https://github.com/georgemunoz1-ui/sports-model/pull/75) repaired event-scoped diagnostic winner identities. [PR #76](https://github.com/georgemunoz1-ui/sports-model/pull/76) integrated numerical identity, lineage, selection and evaluation controls with real runners and archive hooks. [PR #77](https://github.com/georgemunoz1-ui/sports-model/pull/77) added an explicit empty-registration preflight without fabricating forecasts or grades. [PR #72](https://github.com/georgemunoz1-ui/sports-model/pull/72) added availability and dependence disclosures.

### Executed efficiency research — not promotion evidence

Binary single-class Brier; lower is better. Delta is challenger minus control. Intervals are paired chronological-block bootstrap intervals from the retained diagnostic execution.

| Candidate | Common events / opportunities | Brier delta | 95% interval | Disposition |
|---|---:|---:|---|---|
| CFB matchup efficiency | 1,045 / 1,196 | +0.000453 | [−0.001894, +0.002705] | HOLD; improvement unestablished |
| NBA possession efficiency v2 | 2,458 / 2,460 | +0.001298 | [−0.000971, +0.003499] | HOLD; improvement unestablished |
| NBA joint-score v2 | 2,458 / 2,460 | +0.003833 | [+0.001456, +0.006366] | HOLD; worse on this winner metric |

The NBA efficiency margin MAE also worsened by **0.151969 points**. Do not repair that conclusion by selecting a favorable threshold or relabeling the same inspected sample as confirmation. Preserve these candidates; evaluate new increments under new identities and frozen protocols. Details: [original results](docs/research/efficiency_2026_10_23/SWARM_RESULTS_2026_10_23.md), [subsequent integration status](docs/research/efficiency_2026_10_23/INTEGRATION_STATUS.md).

The experiment has **3,503 unique common events** and **7,006 candidate-stage receipts**. Its **58 local SHADOW registrations concern 17 unique future games**, not 58 independent games. Superseded candidates and repeated forecasts must not inflate the event denominator.

## Current boundaries

- **Grading:** the latest retained [canonical preflight](data/grading/canonical/operations/preflight-39999394059-1.json) reports zero registrations and no settlement. Local SHADOW logging is not canonical registration.
- **CI:** PR #78 records 9/9 final-head and 6/6 post-merge checks passing. Its [hosted consolidation run](https://github.com/georgemunoz1-ui/sports-model/actions/runs/39940720358) passed 1,367 tests; the separate local swarm suite passed 1,402. Different scopes are not interchangeable.
- **Storage:** deployed archive hooks are not a verified durable upload. The retained status is `BLOCKED_UNCONFIGURED`; [CI storage requirements](docs/CI_STORAGE_ARCHIVE.md) remain necessary.
- **Markets:** preserved independent models remain market-blind. Explicit market-informed NFL modes are separate research paths. A saved quote or positive arithmetic return is not proof of an executable edge.
- **Open work:** PRs #68, #69, #70, #71, #73 and #74 remain open at this checkpoint. A capability in one of those branches is not automatically available on main.

## Quick start

From a complete checkout, use Python 3.12 and the repository dependencies:

```bash
python -m pip install -r requirements-consolidated.txt
python -m pip install --no-deps -e .
python scripts/model_defaults.py
python -m pytest tests research/tests -q
python harness/healthcheck.py
```

Run health separately from software tests and retain its failures. Before generating a card, acquire source-bound current packages and follow the [runner guide](docs/CONSOLIDATED_MODEL_ACCESS.md). A missing package is not a verified empty slate. An already started event cannot become a new pregame forecast.

## Preservation and scope of this update

This documentation synchronization changes no model coefficients, defaults, forecast artifacts, canonical ledgers, release decisions or workflow schedules. It publishes no new predictive evaluation. Historical reports, [state.json](state.json), [AUTHORIZATIONS.md](AUTHORIZATIONS.md) and the append-only [progress journal](docs/progress.md) retain their original evidence.

The superseded landing page and operating guides are preserved by original Git blob in [documentation history](docs/history/2026-10-23-status-refresh/). [File-level change summary](docs/CHANGE_SUMMARY_2026_10_23.md).
