# SPORTSMODEL OPERATING WORKFLOW (authoritative)

Owner-reconciled 2026-08-08. This is the single operating workflow all agents follow. It supersedes
ad-hoc process notes. Governance rules R1 (never invent numbers), R3 (frozen stays frozen), R6
(append-only) remain the substrate. Gate 0/100 NO_PROMOTE; model ledger $0; push only on explicit
per-release authorization.

## Agent responsibilities

| Role | Responsibility |
|---|---|
| Pregame agent | Schedule, starters, lineups, injuries, weather, odds and K props |
| Validation agent | Forecast identity, simulations, grading, cohorts and promotion evidence |
| Release agent | Signatures, frozen hashes, bundle backup and safe Git publication |
| Root / orchestrator | Reconciles conflicts and authorizes the next state; **only writer during integration** |

Agents supplement one another but **never independently overwrite the same forecast or push
concurrently.** During integration the orchestrator is the sole writer (release step 1: pause all
agent writes).

## Pregame workflow — PER GAME (not once per slate)

1. **T−120 minutes** — re-pull gamePk, first pitch, starters, available lineup, roster/IL,
   weather/roof, same-book odds and K props. Hash the raw evidence. Freeze `FORECAST_T120_v1`.
2. **T−30 minutes** — re-pull everything, including fields already filled. Freeze a NEW version:
   `FINAL_PREGAME` when model-required inputs are confirmed, else `DIAGNOSTIC` when unresolved.
   **Never overwrite T−120.**
3. **After forecast freeze** — join same-book two-sided quotes into a SEPARATE benchmark sidecar.
   **Never use prices as prediction inputs.**
4. **First pitch** — lock eligibility. Anything received afterward is `LATE_CAPTURE`.
5. **Postgame** — ingest the official result. Grade EVERY frozen forecast version in its eligible
   cohort.

A screenshot documents what was shown; it does **not** automatically confer `HIGH_CONFIDENCE`.

## Three independent states (eliminates permanent-pending)

```json
{
  "forecast_status":  "FINAL_PREGAME",
  "benchmark_status": "COMPLETE_QUOTE",
  "execution_status": "UNAUTHORIZED",
  "next_action":      "GRADE_AFTER_FINAL",
  "owner":            "grading_agent",
  "deadline_utc":     "..."
}
```

- Missing prices do **not** prevent outcome grading.
- Missing lineups do **not** block a model that does not consume lineups.
- Unattributed odds block market comparison, **not** model learning.
- Execution can stay `UNAUTHORIZED` while forecasting and evaluation continue normally.

Nothing sits in indefinite PENDING: each state advances or is explicitly blocked with an owner and
a deadline.

## Model workflow

Priority (unchanged): **1. ML → 2. K → 3. RL → 4. Totals.**

Historical V13 evaluation: strict as-of rows, the established **100,000 simulations per game**, with
an **independent per-game seed derived from `model_id + gamePk + 722`** (distinct stream per model
identity). **Never replay historical games through `harness/daily_card.py`** (look-ahead leakage) —
use `harness/run_v13_historical.py`.

Every experiment receives a **forced disposition** — `ADOPT` | `REJECT` | `INCONCLUSIVE` |
`DATA_BLOCKED`. No indefinite PENDING.

The Phase-4 logistic candidate `d_logistic_2f` is an ACTIVE forward challenger. Its betting
authorization may stay closed without preventing forecasts or learning.

## Release workflow (protected push)

1. Pause all agent writes.
2. Verify: clean tree, ancestry (remote is a direct ancestor), exactly the expected linear commit
   count, all signatures Good against the pinned key, all suites/selftests pass, frozen hashes intact.
3. Cut and round-trip a complete bundle (backup).
4. Confirm the remote target has not changed since step 2.
5. Dry-run one explicit refspec.
6. Push only the explicit refspec, e.g. `95c9ac2:refs/heads/sportsmodel/main`.

No force, tags, implicit push, rebase, amend, or unrelated PR branch. **Push requires explicit
per-release authorization from the owner.**

## Implementation status (orchestrator ledger)

| Element | Status |
|---|---|
| Operating workflow doc (this file) | DONE (2026-08-08) |
| Push of 95c9ac2 → origin/sportsmodel/main | DONE last turn under explicit owner auth; remote verified at 95c9ac2 (the release procedure above is adopted for FUTURE pushes) |
| Three-state tracking schema | DEFINED here; applied to live forecasts in data/mlb/forecasts/forecast_states.json |
| Per-game T−120 / T−30 versioned freezes in the re-pull Routine | PENDING — Routine is approval-gated; will carry this richer spec once approved |
| run_v13_historical: seed = f(model_id,gamePk,722), 100k default | PENDING — deferred to reconcile with the running full-system-audit (orchestrator is sole writer during integration; will not edit audited engine files mid-audit) |
| Forced experiment dispositions (ADOPT/REJECT/INCONCLUSIVE/DATA_BLOCKED) | DEFINED here; wired into the experiment queue during integration |
| Full-system-audit findings | RUNNING (wf_7d2c1d88-8eb); orchestrator reconciles findings + this spec into one change set on completion |
