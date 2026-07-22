# PROGRESS JOURNAL (append-only; newest last; next session reads the tail)

## 2026-07-21 — harness bootstrap
- Session history to date: V11 frozen baseline honored -> V13 MC built -> park factors data-derived
  (1,505-final backfill) -> sides verdict DEAD at n=1461 (MC ~coin .2500/53%, GBM worse .2563) ->
  K-props validated in backtest (n=1759, calibrated, MAE 1.92) -> forward paper ledger opened.
- Today: built harness (AGENTS.md, state.json, healthcheck, runbook) per Anthropic/OpenAI
  harness-engineering articles. 7/21 K-prop card sent (4 paper plays: Rasmussen O4.5, Buehler O3.5
  full-weight; Perkins O4.5, Mikolas O2.5 half-weight). Grade scheduled 05:30Z.
- Caught-bug log: relief-outing TBF inflation in K projections (fixed: start-only). Keep R5 sharp.
- For next session: run postgame cycle for 7/21, then pregame 7/22. E1 (opponent-K%) is the queued
  experiment when there's capacity.

## 2026-07-22 (early) — DURABILITY INCIDENT + full harness live
- INCIDENT: container rollback silently erased the 7/19-20 grading turn's writes (results upsert,
  kprops engine, 7/21 card files). Healthcheck CAUGHT IT on first run. Repaired from conversation
  record: results.csv back to 1,505 finals (verified in separate process), kprops.py rebuilt and
  reproduces carded projections exactly (Rasmussen 5.41/Buehler 4.41/Perkins 5.83/Mikolas 3.75).
  New rule in force: git commit after EVERY write batch. Recommend a remote to Taco for true durability.
- HARNESS LIVE: AGENTS.md entry point, state.json (verdicts/ledgers/gates/experiment queue),
  healthcheck, runbook. Recurring tasks created: PREGAME daily 15:00 UTC (card -> Taco),
  POSTGAME daily 05:30 UTC (grade + dataset + ledger). Both fresh-session, bootstrap via AGENTS.md.
- Pending tonight: 4 kprop paper plays grade at next postgame fire (~05:35Z).
