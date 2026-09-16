# P0 — Result binding protocol

Standing protocol after the 2026-08-27 `RESULT_DATE_COHORT_CONTAMINATION` incident, in which a
grading record joined 8/27 forecasts to the 8/26 finals of the same matchups and published
records, Brier scores, P&L and conclusions derived from them.

## The rule

A result is gradable only when it binds to the **scheduled game**, never to a matchup:

```
sport + canonical_game_id/game_pk + scheduled_date + result_date + away_team + home_team
```

A matchup alone can never bind a result. In baseball a three-game series repeats the same matchup
on consecutive days, and consecutive-series game ids are *adjacent integers* — so neither the
team pair nor a lone id is self-corroborating.

## Mechanical refusals

| Code | Condition |
|---|---|
| `PRIOR_DATE_SERIES_JOIN` | same matchup, earlier date |
| `RESULT_DATE_MISMATCH` | result date ≠ board slate date (either direction) |
| `SCHEDULED_DATE_MISMATCH` | scheduled date ≠ board slate date |
| `GAME_PK_UNMATCHED` / `GAME_PK_AMBIGUOUS` | id absent from, or duplicated on, the board |
| `GAME_PK_MISMATCH_FOR_MATCHUP` | matchup on the board, id is a different game |
| `TEAMS_REVERSED` | same game, home/away swapped |
| `FINAL_PRECEDES_START` | final timestamped before first pitch |
| `FINAL_TOO_LATE_AFTER_START` | final > 18h after first pitch without `suspended_resumed` |
| `EVIDENCE_SCORE_DISAGREEMENT` | identity binds but the scores contradict retained evidence |
| `BOARD_PK_NOT_A_REAL_IDENTIFIER` | board carries a placeholder id, making the id check circular |
| `DOUBLEHEADER_NEEDS_GAME_NUMBER` | board holds siblings; row must declare which |
| `DUPLICATE_BINDING_TWO_ROWS_ONE_GAME` | two rows claim one scheduled game |
| `COHORT_COVERAGE_INCOMPLETE` | cohort does not cover the board and did not say so |
| `AGGREGATE_TOUCHES_REFUSED_ROW` | any aggregate over a cohort with any of the above |

## Full-cohort refusal

**A single failed row blocks every aggregate over that cohort** — record, Brier, MAE, log loss,
P&L, promotion evidence, estimator input and publication. No partial metric may silently exclude
or substitute a row. Narrowing is legal only when stated explicitly
(`require_full_coverage=False`) with a recorded reason.

The 8/27 damage was never the five bad rows. It was the numbers computed over them.

## Every results card must print

```
RESULT_BINDING_PASS = n/n
DATE_COHERENCE_PASS = n/n
CANONICAL_ID_MATCH  = n/n
REFUSED_ROWS        = 0  (or the refused rows, listed)
```

`0/0` means *nothing claimed*, not *nothing checked*, and must say so.

## Binding proofs

Every graded slate emits an indexed proof under `data/governance/bindings/` listing each row, the
game it bound to, and its codes. The proof is what makes a published denominator auditable.

## Regression coverage

`harness/result_binding_gate.py --mutants` runs 7 mutants, each disabling one protection; all must
be caught. The primary fixture feeds the real prior-day finals of the five contaminated matchups
into the real 8/27 board and requires all five to be refused **by name**. Fixtures also cover
reversed teams, evidence-score disagreement, premature and late finals, doubleheader siblings,
placeholder ids, duplicate binding and partial cohorts.

## Fixture integrity

Fixture constants are code. Every board id in a fixture declares its provenance
(`CAPTURED` with a source, or `SYNTHETIC_UNVERIFIED`), and the selftest fails on an undeclared id.
A gate that forbids id inference must not perform id inference.
