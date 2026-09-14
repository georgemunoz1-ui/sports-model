# Sports Model Research System

## Consolidated code: PRs #17–#25

Use **`sportsmodel/main`** as the operational code branch. This tree integrates
research evaluation, the information-source stack, contextual NFL models,
explicit model selection, market-aware/live research, spread calibration,
halftime/joint research, current-date acquisition and NFL assimilation.

[Build verification](docs/releases/2026-09-14-pr17-25/verification.json) records
184 passing targeted tests and a 100,000-draw canonical NFL run with exact
football bundle/winner/score replay and nine verified artifact hashes.
[Retained run and test evidence](docs/releases/2026-09-14-pr17-25/runtime-verification.zip)
contains the original run artifacts. These are research records, not canonical
prospective promotion evidence. The September 9 overview is retained in
[documentation history](docs/history/README_pre_consolidation_2026-09-14.md).

## Run the current NFL package

```bash
python scripts/run_nfl_integrated.py --date 2026-09-14 \
  --event-id 2026_01_DEN_KC --simulations 100000 \
  --home-spread -2.5 \
  --halftime-artifact data/nfl/halftime_v1/model.json \
  --output <new-unique-output-directory>
```

The configured event package is `data/nfl/assimilation_v1/event_package.json`.
The runner enforces pregame chronology and requires a newly acquired package
for dates outside its coverage. Research, market-aware and live modes are
explicit; none silently substitutes the SRS baseline. See
[NFL context](docs/NFL_CONTEXT_INTEGRATION.md),
[market/live modes](docs/NFL_MARKET_LIVE_MODELS.md),
[spread calibration](docs/NFL_SPREAD_CALIBRATION.md),
[halftime research](docs/NFL_HALFTIME_JOINT.md), and
[assimilation](docs/NFL_ASSIMILATION_AUDIT.md).

## Limits that remain active

- This is code integration, not an accuracy promotion. The combined and halftime
  arms retain their failed retrospective improvement screens.
- Week 1 has 15 reconciled completed games. The frozen weekly state-release rule
  waits for DEN–KC final; this merge does not change that rule.
- Current-data readiness across all sports remains partial. Full-repository health
  is not green; recovery jobs and readiness acceptance defects remain open.
- News checkpoint materialization and extraction validation remain incomplete.
  Research features do not automatically become numerical forecast adjustments.
- Action authority remains OFF. Market-aware output is not an independent edge.

Start each session with `AGENTS.md`, `state.json`, `docs/progress.md` and the
canonical health check. Preserve earlier forecasts, grades and research verdicts.
