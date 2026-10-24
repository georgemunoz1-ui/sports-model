# Detroit–Buffalo learning acceptance audit — September 18, 2026

## Verdict

**END_TO_END_LEARNING_NOT_DEMONSTRATED.** The game was captured and reconciled, but the normal pipeline did not publish updated state or issue a future forecast consuming it. This is an executed architecture audit, not another grade of the winner prediction.

The local 23-check acceptance audit produced **18 PASS, 3 FAIL, 2 BLOCKED**. A clean GitHub runner independently reproduced the three failed safety assertions: **four real-source regression tests, one pass and three failures**, not setup errors. Existing NFL tests still passed **108/108**. They did not cover these end-to-end safety requirements.

No runtime/model functions were patched, coefficients fitted, default changed, prior forecast overwritten, or main branch updated. All state files produced by adversarial cases are test-only and must not be installed. Action remains OFF, dose 0.0. This branch is based on unmerged PR37, whose model code supplied the September17 run; it is not a merged-main deployment.

## Normal path: where learning stopped

Fresh source receipt: **2026-09-18 07:37:46 UTC / 00:37:46 PDT**. The archived nflverse PBP contains 184 Detroit–Buffalo records and reconciles against the captured schedule to Buffalo41–Detroit31, halftime27–10. The final is also present in the retained official NFL game center and team pages. nflverse is a data project, not itself the NFL's official gamebook.

The complete Week2 schedule contains 16 games: one final, 15 pending. Calling the existing `run_nfl_assimilation_check` with that full schedule and the exact frozen Week1-updated prior produces:

- `completed_coverage_complete: true`
- `weekly_state_update_eligible: false`
- `state_update_applied: false`
- `reason: WEEK_NOT_COMPLETE_OR_PRIOR_STATE_NOT_SUPPLIED`
- no new `team_state.json` and no released-state future forecast.

The prior was supplied, so the applicable cause is the incomplete week. This wait is intentional under the frozen weekly-batch policy, not evidence that the final was missed. Do not drop pending games to evade it. A game-level eligibility flag does not establish whole-week release eligibility.

The quarterback updater has a separate limitation. Its builder rejects Week2 with `QB_WEEK1_COMPLETE_SCHEDULE_REQUIRED`; its applier rejects `completed_week=2` with `QB_UPDATE_SCOPE_REQUIRES_SEPARATE_WEEKLY_CHAIN`. The current implementation is specifically Week1→Week2, not a general weekly state chain. Finishing the remaining Week2 games alone will not remove that code limitation.

The actual integrated CLI for September27 was also executed without date overrides. It refused with `NFL_DATE_NOT_CAPTURED:2026-09-27`. No fresh Week3 context package exists on that path. The future forecast delta is **null/unavailable**, not a calculated zero.

## Three reproduced safety failures

### 1. Extra-week PBP leaks into a state update

`advance_states` sends the entire supplied PBP frame into `_qualifying_plays` and `_weekly_observations` without first restricting it to the supplied schedule's game IDs. Coverage records unmatched source games but the state transform still consumes them.

Two real-source reproductions:

1. Supplying only the Detroit–Buffalo schedule row with the complete 17-game season PBP changed **all32 teams**, rather than only Detroit and Buffalo.
2. Supplying the legitimate, complete **16-game Week1 schedule** with the refreshed season PBP also consumed the extra Week2 game. Its reconstructed Week1 state differed for **all32 teams** from the correctly Week1-filtered reconstruction because the extra game also changes the league-relative centering. This second reproduction does not depend on truncating the authoritative Week1 schedule.

Expected Week1 state digest from the same refreshed source, filtered to Week1: `e8ff49b149b7b40a10dfbf3ffd60996ed8d2ab959959220ef6d9ecaf300fb10e`.
Actual unfiltered-orchestrator digest: `4567ef5e35254e8e4048dc93f20509fa7a36488dd9136ccafe5f79cbe2ca3f86`.

This is a cross-week contamination defect and a potential look-ahead defect in historical reconstruction. It does **not** show that the original September17 forecast contained its own result: its frozen raw PBP contains only the16 Week1 games, and all its hashes remain unchanged.

### 2. A truncated schedule can masquerade as a complete week

In an explicitly adversarial call, removing the15 pending Week2 games caused the orchestrator to mark the remaining one-game schedule as weekly-update eligible and write state. The update boundary does not independently bind supplied coverage to the full authoritative schedule. The honest full-schedule call correctly blocks; the truncated test exposes a missing boundary check.

### 3. The same completed game can update state twice

The repeated-game test starts from a state already updated with this event, then submits the identical game/source again. The orchestrator accepted another update and produced a different state digest. It neither rejected the duplicate state transition nor returned the unchanged state. Immutable raw-file ingestion does work; **idempotent source storage is not idempotent model-state application**.

These failures occurred only in isolated adversarial/reconstruction outputs. No bad state was published or installed.

## What the current feature filters actually see

Of184 PBP feed records, the frozen team-efficiency filter admits **21 early-down, neutral-win-probability plays**, all in the first quarter: **16 Buffalo offensive plays and five Detroit offensive plays**. The other feed records include later blowout-state plays, third/fourth downs and non-offensive events. Thus184 is not an offensive-play denominator.

The separate frozen QB dropback filter yields **75 usable records**:42 for Jared Goff and33 for Josh Allen, aggregated into two player-game observations. Those observations were saved as `DATA_EXISTS_ONLY`, with `active_in_run: false`; the Week2 QB chain is unavailable. Final point differential enters the team update separately from the early-down filter, so it would also be wrong to claim that the model ignores all information outside those21 plays.

A small hypothetical state response would not, on its own, prove excessive prior shrinkage. Filter scope, league-relative centering, updater implementation and release timing must be distinguished from the statistical question of how much weight to put on one game.

## Subroutine response is not operational learning

An isolated, unreleased one-game transform changes team state. Rebuilding features for the real September27 BUF–LAC and DET–NYJ schedule rows changes nine and eight selected-model features, respectively; the fitted heads respond numerically. This proves that the low-level arithmetic is connected.

These are **not Week3 forecasts**: the isolated transform uses one-game rather than full-week league centering, holds QB IDs at their last observed identities, does not apply the new QB observations, and uses missing future-weather handling. No current Week3 QB/availability/weather verification was claimed. The exact technical sensitivity outputs are retained separately and were not installed into the canonical runner. This does not meet the user's DATA→STATE→FEATURES→FUTURE_FORECAST acceptance condition.

## Evidence and reproducibility

Source capture run: **35320323493**, commit `5d4e65b8d6f891f251ab7e28c4a2cc0ef23d5455`.
Source artifact:10536523716, ZIP SHA256 `e3bb75c06ec7851879b95d15d49e8d3d8d3f11e7980dd315534e398478f548a8`.
PBP bytes SHA256: `d67966cebda946f80448d097b51a83d7cc7630e460dbbe2d58883cfee44a5778`.

Clean-run acceptance reproduction: **35320937477**, code commit `618ec390fa26d105f83ecf7347e8431d5d462481`.
Acceptance artifact:10536454886, ZIP SHA256 `625b1b96697b1cd8d341d8f097de6ca5bf3a7b25f1bd9baa725940b29eb1d11b`.
All18 artifact-manifest entries were hash-verified after download. Workflow conclusion intentionally remains failure because three actual assertions failed.

Regression implementation: `tests/test_learning_acceptance_det_buf.py`.
Execution workflow: `.github/workflows/nfl-learning-acceptance-tests.yml`.
Local acceptance JSON SHA256: `dbfe9b1b02df2b5ce650b40551b38ddc732ad62bb5b6fb448793b7b424ee339e`.
Local full diagnostic script SHA256: `0ba6b0a0ad38ff6f0be04153864c9f5b1b0e8cba5a6a6d73d426775dc0a79705`.

The downloadable evidence bundle contains the full local audit program, input archives, machine results, unreleased probes, new source receipts and remote test evidence. GitHub artifacts expire December17,2026. No long-term artifact permanence is claimed.

Global health remains RED. The NFL-only dependency environment reported seven health failures and nine warnings; several health self-tests lacked pytest in that narrow environment, while archive/recovery/historical-release blockers also persisted. This is not a clean consolidated-environment health certification. The108 focused NFL tests passed in that environment.

## Required repairs before the learning loop can pass

First bind the authoritative schedule and select only its eligible game IDs **before** any league centering or state aggregation. Add processed-game IDs, parent-state hashes and revision handling so each completed game is applied exactly once. Then implement a general QB state chain without reapplying offseason retention every week. Preserve the frozen weekly-batch policy, or separately register and evaluate a partial-week design rather than silently changing it.

Finally build a genuinely fresh Week3 package after the required inputs and week state are available, invoke the actual integrated runner, and prove that changed state hashes and features occur in its saved output while earlier forecasts remain immutable. Until then, **captured and reconciled is not learned and used**.
