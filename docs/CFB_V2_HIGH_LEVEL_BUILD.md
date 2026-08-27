# CFB v2 high-level build

## Current position

The recovered historical implementation of `cfb.fbs.elo_form_logit_ridge.v1_0.shadow` remains
immutable. It is not present on the current production branch and must be ported without its stale
shared-harness changes before it can serve there as the operational baseline. Its registered
2019-2025 walk-forward evaluation contains 5,856 games across 111 season-week blocks:

| Target | V1 | Baseline | Status |
|---|---:|---:|---|
| Home-win Brier | 0.1711 | causal Elo 0.1925 | validated on full scope |
| Home-margin MAE | 13.43 | Elo-margin 14.82 | validated |
| Total MAE | 13.04 | rolling total 13.04 | not validated |

The aggregate home-win result is not enough for a high-level FBS betting model. The adversarial
audit found that much of the separation comes from FBS-versus-FCS games. On 5,106 FBS-versus-FBS
games, v1 Brier was 0.1895 and it was effectively tied with evaluation-only ESPN pregame Elo.

V2 is therefore a challenger, not an edit to v1.

## Source architecture

1. Pin `sportsdataverse/cfbfastR-raw` for the raw ESPN schedule and per-game cache.
2. Pin `sportsdataverse/cfbfastR-cfb-raw` for offline-reprocessable enriched per-game JSON.
3. Pin `sportsdataverse/cfbfastR-cfb-data` for the scripts and schemas that reshape the enriched
   games into play-by-play, EPA/WPA, advanced boxes, rosters and injury tables.
4. Pin the corresponding `sportsdataverse/sportsdataverse-data` GitHub release assets for the
   versioned `espn_cfb_*` seasonal tables.
5. Optionally use the versioned `CFBD/cfbd-python` client for returning production, talent,
   recruiting and transfer data when a configured API key and retained responses are available.
6. Retain repository, commit, path, byte size, SHA-256 and retrieval time for every input.

The SportsDataverse repositories share an upstream family. Agreement across raw, enriched and
parsed outputs is a transformation check, not independent source confirmation.

## Modeling layers

### Baselines

- Expanding home-win rate
- Causal Elo
- Frozen v1 direct probability and margin
- Rolling matchup-total heuristic

### V2 challenger

- Opponent-adjusted offensive and defensive EPA/play
- Early-down EPA and success rate
- Explosiveness, havoc and finishing drives
- Pace
- Returning production and quarterback continuity
- Talent composite and transfer balance
- Coaching continuity
- Home/neutral, travel, time-zone, altitude and rest context

All state is reconstructed in kickoff order. A game updates a team only after its own feature row
has been emitted. One official week shares one cutoff.

### Estimation

- Home win: histogram gradient boosting plus nested prior-only calibration
- Margin: histogram gradient boosting with absolute-error loss
- Total: independently evaluated histogram gradient boosting; disabled unless it beats both
  registered total baselines

FBS-versus-FBS is the primary cohort. FBS-versus-FCS is reported separately so large talent
mismatches cannot manufacture an aggregate validation claim.

## Week 1 policy

Week 1 cannot be treated as a normal continuation of 2025 form. Before V2 forecasts, each team
needs retained pregame values for talent, returning production, quarterback continuity and coach
continuity. When any required block is unavailable, publish the v1 forecast and
`V2_INPUT_BLOCKED` only when the clean v1 port is present and healthy. Otherwise publish
`SYSTEM_FAILURE_CFB_BASELINE_UNAVAILABLE` with no forecast. Do not silently substitute
prior-season performance.

The owner-relayed Top 25 board is a useful market overlay but is not a complete Week 1 schedule.
The production card must begin from the complete FBS-involving schedule and mark the Top 25 subset
as a view. Prices remain separate from prediction.

## Execution sequence

1. Capture and reconcile the complete Week 1 schedule with canonical game IDs.
2. Acquire pinned raw and parsed historical data.
3. Materialize one causal feature row per eligible game.
4. Run season-week walk-forward fits and keep all OOF predictions.
5. Compare v2 against every baseline with paired week-block inference.
6. Run leakage, market-firewall, cohort and chronology mutation tests.
7. Register v2 as a prospective shadow only if the historical gates pass.
8. Freeze the Week 1 forecast board before attaching DraftKings prices.

## Merge integration checklist

Before this branch can leave draft, the integration commit must:

1. Rebase onto the current `sportsmodel/main` without overwriting concurrent sport work.
2. Register `harness/cfb_v2_contract.py` in the module manifest.
3. Add CFB information-class ledger entries for every published card artifact.
4. Register CFB arm-completeness expectations for every cohort joining a board.
5. Port the historical v1 CFB implementation without its stale shared-harness changes, or retain
   the explicit no-forecast failure state.
6. Keep the production healthcheck green on a fresh clone.

No result authorizes a wager. Real-money authority remains closed and stake remains zero.
