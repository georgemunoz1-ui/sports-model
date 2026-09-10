# AGENTS.md — Sports Model Harness (entry point — read this first, then follow pointers)

## Mission
Long-running betting-research agent. Improve prediction accuracy over time across MLB, NFL, CFB,
NBA, WNBA, NHL, and MLS. DATA > Implied. Bet objective = +EV vs price break-even, NEVER raw win%.
Everything is PAPER until a go-live gate in state.json passes. $0 real risk today.

The repository-wide primary research forecast standard is `expanded_game_state.v1`: start from a
league baseline, then attempt to bind verified sport-specific pregame game state. A baseline-only
forecast is a required fallback/benchmark, not the preferred current research opinion when valid
expanded state is available.

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
- PREGAME (before first pitch/kick/tip/puck drop): follow the league runbook, reconcile the full
  authoritative event universe, freeze PIT baseline inputs, then attempt every expanded-game-state
  dimension required for that league. Missing enrichment stays explicit UNKNOWN/UNAVAILABLE.
- POSTGAME (after last final): bind finals to frozen forecast identities, grade only supported
  targets, append results/evidence, annotate material post-freeze state shocks separately, update
  state/progress, and never mutate the pregame artifact or its official score.
- Legacy MLB K-prop procedures remain in `harness/runbook.md`; do not interpret that narrower
  runbook as permission to omit the repo-wide game-state contract from game forecasts.

## Hard rules (mechanically enforced by healthcheck/CI where possible)
R1 NEVER invent a number. Missing data -> null + flag. Every ledger figure traces to a source.
R2 NO look-ahead: features must be as-of pregame. Grading uses finals only.
R3 Frozen things stay frozen: V11 spec; the n=1,461 sides verdict (coin flip — no ML/RL/sides
   plays) unless a pre-registered experiment in state.json overturns it at stated sample size.
R4 Small samples don't move verdicts. Log the daily grade; verdicts change only at gate sizes.
R5 Big edge = probably your bug. Any |EV|>35% or |proj-line|>1.5K -> audit inputs before carding.
R6 Corrections log (docs/v11_log_*.md style) is append-only. Errors get logged, not erased.
R7 One parameter change per experiment, pre-registered in state.json BEFORE evaluation.
R8 All web data via approved fetch tooling; extract source facts without inventing unavailable
   values. Respect source timestamps, retrieval timestamps, and retry/rate-limit policy.

R9 EXPANDED GAME STATE IS THE DEFAULT FORECAST STANDARD. Every valid-event game forecast across
   MLB/NFL/CFB/NBA/WNBA/NHL/MLS must begin with a reproducible league baseline and attempt to bind
   the sport-specific dimensions in `models/common/expanded_game_state_standard_v1.py` before the
   primary research card is emitted. Team-strength-only/SRS-only/Elo-only forecasts may remain as
   baseline benchmark arms, but must not be labeled the primary current research forecast when
   verified expanded state and a versioned impact transform are available.

R10 NO VALID GAME IS SILENTLY OMITTED FOR MISSING ENRICHMENT. Missing information adapter/data is
   not the same as a missing forecast. If authoritative event identity and baseline team strength
   are valid, emit the baseline and label the card `BASELINE_ONLY` or
   `BASELINE_WITH_UNRESOLVED_INPUTS`. Unresolved dimensions are explicit UNKNOWN/UNAVAILABLE and
   contribute zero adjustment. Only invalid authoritative event identity may suppress a game.

R11 SPORT-SPECIFIC GAME-STATE DIMENSIONS ARE REQUIRED BY CONTRACT:
- MLB: team strength; starter; lineup; bullpen; schedule/rest/workload; park/weather/roof.
- NFL: team strength; QB; active/inactive/injury/practice state; OL/secondary/position-group health;
  snap/workload state; schedule/rest/travel; weather/venue.
- CFB: team strength; QB; availability/suspension; depth chart; position-group health;
  schedule/rest/travel; weather/venue/neutral site.
- NBA/WNBA: team strength; availability; starting lineup; minutes/workload restrictions;
  rest/back-to-back; travel; venue.
- NHL: team strength; starting goalie; scratches/availability; line/pair combinations;
  rest/back-to-back; travel; venue.
- MLS: team strength; starting XI; goalkeeper; injury/suspension/international duty;
  fixture congestion; travel; weather/venue.

R12 IMPACT LINEAGE IS MANDATORY. Any non-zero game-state adjustment must carry a separately
   versioned impact-transform ID/version/status plus an event-level feature-contribution log.
   `UNVALIDATED_SHADOW` transforms may produce research shadow opinions but cannot silently become
   production authority. Sportsbook odds, implied probability, betting splits, line movement, or
   consensus picks are forbidden predictive inputs. Subjective effort/morale/sentiment is also
   forbidden unless a future preregistered, validated contract explicitly supersedes this rule.
   Market comparison occurs only after the independent forecast is frozen. Action authority is
   OFF unless separately granted by the existing promotion/go-live process.

R13 POST-FREEZE SHOCKS NEVER REWRITE THE FORECAST. A material injury, replacement, ejection,
   weather shift, or other state transition after kickoff/puck drop/first pitch/tip must be stored
   in the separate `post_freeze_realized_state.v1` shock ledger. Layer 1 retains the exact frozen
   forecast identity and all official Brier/log-loss/margin/total/team-score grading. Layer 2 may
   annotate realized timing/exposure and, only from a separately versioned player-value model,
   carry a research value-delta posterior. Until that model exists, the delta is
   `NOT_ESTABLISHED`, numeric fields stay null, causal attribution is `NOT_ESTABLISHED`, and
   counterfactual rescoring is disabled. A future validated counterfactual remains research-only
   and can never alter official prospective scoring or arm-promotion evidence.

## Coverage labels
- `FULL_INFORMATION_SHADOW` — baseline plus all required expanded dimensions are resolved for the
  research shadow contract.
- `BASELINE_WITH_UNRESOLVED_INPUTS` — some game-state dimensions are bound and others remain
  partial/unknown/unavailable; unresolved dimensions add zero adjustment.
- `BASELINE_ONLY` — valid baseline forecast with no usable enrichment.
- `SOURCE_CONFLICT_BASELINE` — authoritative event survives reconciliation but source conflict is
  retained and no disputed enrichment is applied.
- `INVALID_EVENT` — authoritative event identity failed; do not forecast a phantom/ambiguous game.

## Where things live (progressive disclosure)
- state.json .............. machine state: ledgers, gates, verdicts, experiment queue (JSON on
                            purpose — harder to accidentally rewrite than prose)
- harness/runbook.md ...... step-by-step daily procedures + fetch URL patterns that WORK
- harness/healthcheck.py .. integrity gate (run first, always)
- docs/progress.md ........ append-only run journal (your handoff to the next session)
- AUTHORIZATIONS.md ....... doctrine history + standing decisions — READ-ONLY
- docs/history/ ........... original V11-era protocol docs (context, frozen)
- models/common/expanded_game_state_standard_v1.py ... machine-readable repo-wide forecast policy
- models/common/post_freeze_shock_ledger_v1.py ....... two-layer realized-state shock contract
- docs/POST_FREEZE_SHOCK_LEDGER_V1.md ................. shock grading/valuation doctrine
- data/*/post_freeze_shocks/ .......................... append-only event shock evidence
- pipelines/cards/forecast_adapter.py ................. shared adapter boundary enforcing the policy
- data/backfill/mlb/2026/ . results/features/pitcher logs and related MLB source state
- engine/ ................. legacy/live engine tracks and experiments
- cards/ .................. daily cards; sports/ contains multi-sport registry/schema material

## Who decides what
Agent: runs cycles, grades honestly, proposes experiments, flags anomalies. User: authorizes any
doctrine change, go-live, real-money authority, and model-track promotion. When unsure -> preserve
the research artifact, keep action authority OFF, and surface the unresolved decision.
