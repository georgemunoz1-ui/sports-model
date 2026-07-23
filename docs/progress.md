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

## 2026-07-22 (manual postgame, user-triggered)
- 7/21 graded: Rasmussen WIN (5K, proj 5.41 — nailed), Buehler LOSS (3K vs 4.41), Perkins LOSS (4K vs 4.5, near-miss), Mikolas VOID (gs=0, relief — book rules void no-start props). Day 1: 1-2-1V, -0.47u.
- 13 finals + 2 PPD (PIT@NYY, BAL@BOS -> likely 7/22 DHs) upserted; dataset 1518 finals. Pitcher logs appended (ER/BB placeholders noted).
- 05:30Z trigger will find work done; should no-op gracefully.

## 2026-07-22 (midday) — board priced
- Taco posted RotoWire K board + odds. 4 paper plays: Cole U6.5(-105), Singer U5.5(-144), Jump O4.5(+104), Bennett U5.5(-148, half). Pending in state.json.
- Detmers/Kremer overs correctly declined (prices pre-shaded steep toward our projections — E3 note).
- Starter changes vs morning probables: Lauer, Dobbins, Fried, Kay, Quantrill, Miles, Perez, Hughes.

## 2026-07-23 (manual postgame for 7/22)
- K-props day 2: Jump WIN (5K>4.5, +110), Bennett WIN (4K<5.5), Cole LOSS (11K!! vs proj 5.59 — biggest miss yet), Singer LOSS (6K vs 4.46). Day -0.56u; cumulative 3-4-1V, -1.03u (hand-math error caught+fixed, corrections entry); gate 8/100.
- ML tracking day 1: 3-1 (MIL✓ BOS✓ KC✓ | SEA✗).
- Cole 11K vs proj 5.59 = 5.4K miss on a 19-start sample -> E1 (opponent-K%) escalated: PIT strikes out a LOT; opponent adjustment would have raised Cole's proj + possibly flipped the play. Priority experiment.
- Dataset 1,535 finals. Logs appended.
