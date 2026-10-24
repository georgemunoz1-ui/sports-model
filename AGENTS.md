# AGENTS.md — Sports Model Harness

## Current entry point

Documentation reconciled October 23, 2026 Pacific / October 24 UTC. `main` is the consolidated seven-league source. Read [current status](docs/CURRENT_STATUS.md), [model access](docs/CONSOLIDATED_MODEL_ACCESS.md) and [operating workflow](docs/OPERATING_WORKFLOW.md) before relying on an older snapshot. The previous agent instructions are preserved verbatim in [history](docs/history/2026-10-23-status-refresh/AGENTS.md).

Mission: maintain reproducible sports forecasting and simulation research across NFL, CFB, NBA, WNBA, MLB, NHL and MLS. Core market research covers moneyline, spreads/run lines/puck lines and totals. Existing selected models and experimental candidates have different scopes. Everything remains research/paper until the exact applicable qualification and go-live gates pass. **Wagering authority OFF; no live allocation from unqualified challengers.**

## Session-start ritual

1. From the actual repository root, run `python3 harness/healthcheck.py` and retain its complete output and checkout identity. Inspect failures and block affected claims; do not turn unrelated release debt into a blanket ban on independently valid research. A partial checkout cannot certify global health.
2. Read `state.json` and `data/model_selection/defaults_v1.json`. Preserve existing verdicts, ledgers, gates and source pins; an old top-level timestamp is not proof that every nested record is old or that current inputs are fresh.
3. Read `docs/progress.md` (last ~120 lines) and the current documentation checkpoint. The journal is append-only; retain dated headers and original statements. `harness/journal_continuity.py` checks that the newest dated entry is visible in this window.
4. Pin the real branch/commit, inspect relevant open PRs and actual runner capabilities, and define a reviewable scope. The owner-authorized parallel research overhaul permits independent workstreams; the coordinator is the sole integration writer.

## Hard rules

R1 Never invent a number. Missing inputs or evidence remain null/flagged. Every reported result traces to source bytes or an explicitly labeled calculation.

R2 No look-ahead. Features, transformations, parameters, calibration and selector choices use permitted earlier information. Separate decision-time odds from closing prices. Current retrieval of historical data is not original point-in-time availability.

R3 Frozen things stay frozen: V11, existing V13 verdicts, original forecasts, fitted states and registered artifacts. A new version preserves parent lineage and unresolved defects; predictive evidence remains bound to the exact evaluated procedure/population.

R4 Software tests, Monte Carlo draws and repeated versions are not independent event evidence. Small samples and postgame explanations do not establish improvement, preventability or profit.

R5 Audit large model-market disagreements rather than declaring them locks. Preserve legacy anomaly thresholds where applicable; do not silently relax them or infer current personnel effects from disclosures.

R6 Corrections and result ledgers are append-only. Add a successor with exact parent identity; do not rewrite historical forecasts or approval statements. Keep pushes, voids, half outcomes and abstentions explicit under a declared scoring convention.

R7 Separate identifiable increments and freeze protocols before confirmation results. Evaluate selectors separately from forecasters. Do not tune candidates or thresholds to rescue JMU–App State, NE–Chicago or Denver–OKC.

R8 Retain source receipts, as-of cutoffs, exact event/team/market/settlement identities, model/state/code hashes and simulation metadata. Use available approved connectors/acquisition paths; do not bypass access denials or claim external sources were verified when they were not.

## Actual research paths

Use `scripts/generate_card_force.py` for shared cards and `scripts/run_nfl_integrated.py` for NFL contextual inference. Fresh source-bound packages are required. A missing package is unacquired, not a verified empty slate; a started event cannot receive a newly backdated pregame prediction.

CFB/NBA efficiency experiments use `scripts/run_efficiency_experiments.py`; shared-card integration is opt-in through `--efficiency-research-config`. Efficiency, personnel and joint increments retain separate identities. PR #78's repaired retrospective analyses remain diagnostic. NBA efficiency/joint regressions do not justify promotion. See [results and integration](docs/research/efficiency_2026_10_23/INTEGRATION_STATUS.md).

NFL selected-QB winner, combined-arm joint/spread, explicit enhanced-pregame and live modes are distinct. Do not borrow another arm's residuals. The spread calibration path requires an explicit combined model ID. Market-informed outputs are not independent market edges. Consult [NFL context](docs/NFL_CONTEXT_INTEGRATION.md), [market/live](docs/NFL_MARKET_LIVE_MODELS.md) and [spread](docs/NFL_SPREAD_CALIBRATION.md) contracts.

Shared numerical identity defaults to `market_blind_numeric.v2`; preserve `legacy.v1` only as an explicitly identified replay path. Do not edit old hashes or seed identities to clear a drift failure.

## Evidence, scheduling and release

Keep raw forecasts even when selection eligibility fails. Local SHADOW logging, remote durable archival and canonical pregame registration are different achievements. Count unique events separately from candidate-stage registrations. Required archive/registration evidence cannot be bypassed; successful empty grading preflight is not settled prospective evidence.

Use [CI storage](docs/CI_STORAGE_ARCHIVE.md) and [current workflow status](docs/ALL_MODELS_CURRENT_RUNTIME.md). Do not describe a local run, branch-only workflow or unconfigured uploader as an active scheduled service. No promise of background execution without an actual deployed scheduler/task.

Repository writes, merges and publication changes require the applicable owner authorization and protected workflow. No force push, history rewrite, invented approval or automatic model promotion. [AUTHORIZATIONS.md](AUTHORIZATIONS.md) remains read-only. Owner authorization does not replace missing predictive qualification or enable wagering.

## Handoff

Report actual commands, test scope, run IDs, event populations, hashes, results, exclusions and integration status. End every task as completed and exercised; implemented but not exercised; blocked with a named dependency; or rejected/deferred with a reason. Do not substitute documentation or unexecuted scripts for completed work. The [research overhaul contract](docs/research/overhaul_2026_10_23/README.md) and original progress/evidence records remain available.

Selected-QB full-game margin distributions remain a separate opt-in research product.
Use `--margin-model data/nfl/qb_margin_full_support_v1/runtime.json`; no automatic
child activation or default change. Read `docs/NFL_QB_MARGIN_PROCESS_20261019.md`.
The historical primary comparison is inconclusive (HOLD), wagering is OFF, and
totals, combined-arm calibration and winner heads remain separate. Historical
replays cannot create prospective grading registrations.
