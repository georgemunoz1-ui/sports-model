# AGENTS.md — Sports Model Harness (entry point — read this first, then follow pointers)

## Mission
Long-running betting-research agent. Improve prediction accuracy over time across MLB (live),
WNBA/NFL/CFB/NBA (registered stubs). DATA > Implied. Bet objective = +EV vs price break-even,
NEVER raw win%. Everything is PAPER until a go-live gate in state.json passes. $0 real risk today.

## Session-start ritual (every run, before any work)
1. `cd /home/claude/work/sportsmodel && python3 harness/healthcheck.py`  — verifies dataset
   integrity, ledger consistency, last-run recency. FIX health failures before new work.
2. Read `state.json` — current verdicts, ledgers, gates, experiment queue, next actions.
3. Read `docs/progress.md` (last ~120 lines) — what the previous run did and left for you.
   The window is 120, not 30, because entries now run 15-30 lines each and a 30-line read
   landed mid-paragraph with no dated header in view. `harness/journal_continuity.py`
   PARSES this line and fails if the newest dated entry falls outside the window stated
   here, so changing the number changes what is enforced — keep them honest together.
4. Do ONE unit of work well (a daily cycle, or ONE experiment), not everything at once.

## The daily cycle (two halves)
- PREGAME (before first pitch): `harness/runbook.md#pregame` — fetch slate+probables (statsapi via
  WebFetch; shell HTTP is proxy-blocked), pull as-of pitcher stats from local logs, produce K-prop
  card via `engine/kprops.py` logic (start-only!), log slate to data/, send card to Taco.
- POSTGAME (after last final): `harness/runbook.md#postgame` — fetch finals, upsert results.csv,
  append pitcher_logs, grade K-prop card into docs/kprop_ledger.md, update V13 forward tally,
  update state.json ledgers, append docs/progress.md, message Taco the grade.

## Hard rules (mechanically enforced by healthcheck where possible)
R1 NEVER invent a number. Missing data -> null + flag. Every ledger figure traces to a source.
R2 NO look-ahead: features must be as-of pregame. Grading uses finals only.
R3 Frozen things stay frozen: V11 spec; the n=1,461 sides verdict (coin flip — no ML/RL/sides
   plays) unless a pre-registered experiment in state.json overturns it at stated sample size.
R4 Small samples don't move verdicts. Log the daily grade; verdicts change only at gate sizes.
R5 Big edge = probably your bug. Any |EV|>35% or |proj-line|>1.5K -> audit inputs before carding.
R6 Corrections log (docs/v11_log_*.md style) is append-only. Errors get logged, not erased.
R7 One parameter change per experiment, pre-registered in state.json BEFORE evaluation.
R8 All web data via WebFetch tool; verbatim-extraction prompts; on 429 wait 60-90s, retry once.

## Where things live (progressive disclosure)
- state.json .............. machine state: ledgers, gates, verdicts, experiment queue (JSON on
                            purpose — harder to accidentally rewrite than prose)
- harness/runbook.md ...... step-by-step daily procedures + fetch URL patterns that WORK
- harness/healthcheck.py .. integrity gate (run first, always)
- docs/progress.md ........ append-only run journal (your handoff to the next session)
- AUTHORIZATIONS.md ....... doctrine history + Taco's standing decisions (AUTH-1..7) — READ-ONLY
- docs/history/ ........... original V11-era protocol docs (context, frozen)
- data/backfill/mlb/2026/ . results.csv (1,505+ finals) | features.csv | pitcher_logs/{id}.txt |
                            park_factors.json | starters.csv | pitchers.csv | calibration.json
- engine/ ................. kprops*.py (LIVE track) | v13*.py + gbm_model.py (sides — verdict: dead)
- cards/ .................. daily cards (json + html); sports/ ... multi-sport registry+schema

## Who decides what
Agent: runs cycles, grades honestly, proposes experiments, flags anomalies. Taco: authorizes any
doctrine change, go-live, real money, new engine tracks. When unsure -> paper + ask in the summary.


## NFL integrated research path (2026-09-14)

For NFL model/simulation requests use `python scripts/run_nfl_integrated.py --date YYYY-MM-DD --output UNIQUE_DIRECTORY`.
The shared card interface is `pipelines.cards.adapters.nfl`; configuration is
`data/nfl/contextual_v1/runtime.json`. This path emits the recovered EPA reference
and fitted QB, availability/workload, travel, and combined research arms. Do not
substitute the small SRS runner while reporting that contextual features are absent.
Read `docs/NFL_CONTEXT_INTEGRATION.md` and the current event package first. A date
not present in the package is unacquired, not a verified zero-game slate.
Create a new source-bound event package before forecasting another date. All
research arms remain distinct; combined features failed their retrospective
probability screen and are not a promoted production model. Old forecasts and
the existing go-live policy remain unchanged.


NFL market-aware and live modes are now fitted, not proposed-only. See
`docs/NFL_MARKET_LIVE_MODELS.md` and `data/nfl/modes_v1/runtime.json`. Use explicit
`--mode enhanced_pregame` with a source-bound market packet, or `--mode live`
with that pregame market prior and a current pre-play packet. Keep football-only
research available. Do not call the market-weighted output an independent edge,
or a categorical live winner simulation a drive/score simulator.


For full-game NFL spread calibration use the integrated command with
`--home-spread HANDICAP` (home-team orientation), or
`scripts/run_nfl_spread_calibration.py` on a preserved forecast directory.
Read `docs/NFL_SPREAD_CALIBRATION.md`. It emits both raw and calibrated research
probabilities. The historical scoring screen passed, but integer push reliability
worsened and market superiority is unestablished. Do not call it validated
spread pricing or apply it to totals, first halves, or other model IDs.

For the selected QB parent, the separate margin distribution is configured by
`data/nfl/qb_margin_full_support_v1/runtime.json` through the optional
`margin_distribution_config` entry in the contextual runtime. The integrated
research runner saves a separate margin child automatically, including a
hypothetical spread ladder when no observed line is supplied. Read
`docs/NFL_QB_MARGIN_PROCESS_20261019.md`. Its historical primary comparison is
inconclusive, predictive status remains HOLD, and wagering is OFF. This child
does not provide totals or replace the independent winner head. Historical
saved forecasts require explicit retrospective mode; future pregame outputs
must be frozen before kickoff with previously created, verified fit/config/
evaluation artifacts. Existing combined-arm calibration remains a distinct path.
