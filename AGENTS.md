# AGENTS.md — Sports Model Harness (entry point — read this first, then follow pointers)

## Mission
Long-running betting-research agent. Improve prediction accuracy over time across MLB (live),
WNBA/NFL/CFB/NBA (registered stubs). DATA > Implied. Bet objective = +EV vs price break-even,
NEVER raw win%. Everything is PAPER until a go-live gate in state.json passes. $0 real risk today.

## Session-start ritual (every run, before any work)
1. `cd /home/claude/work/sportsmodel && python3 harness/healthcheck.py`  — verifies dataset
   integrity, ledger consistency, last-run recency. FIX health failures before new work.
2. Read `state.json` — current verdicts, ledgers, gates, experiment queue, next actions.
3. Read `docs/progress.md` (last ~30 lines) — what the previous run did and left for you.
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
