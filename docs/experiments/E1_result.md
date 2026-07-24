# E1 — Opponent-K% adjustment · EXPLORATORY corrected-population sensitivity run (2026-07-24)

**Production decision: NO PROMOTE.** **Confirmatory status: INDETERMINATE** — the pre-registered
confirmatory replay required exact identity with the original n=1,759 experiment-of-record, which is
**permanently unrecoverable** (see `E1_confirmatory_closure.md`). This 1,757-row run is therefore
**EXPLORATORY**, not a confirmatory result. It supports the conservative no-promote decision; it does
NOT constitute a valid confirmatory experiment.

## What this run is (and is not)
- **Is:** an internally-paired sensitivity replay on a *newly reconstructed* engine-eligible
  population (n_prior≥5, ≤7/19 horizon, 7/24-vintage data). Baseline and E1 run on the identical
  1,757 rows; E1 adds only the opponent term.
- **Is NOT:** the original 1,759-row experiment-of-record. Those row IDs were never stored (the
  backtest kept anonymous parallel arrays) and the data vintage has since changed. The 1.92→1.849
  baseline-MAE drift is a population/vintage difference, **not** a two-row edit (closure doc).
- The already-observed 1,757 rows **cannot be reused as confirmatory evidence.** A real confirmatory
  E1-R must be pre-registered against an **untouched forward holdout.**

## Data provenance (reconstructed population)
- 30 team hitting gamelogs from statsapi; all 30 terminal G/SO/AB/BB reconciled EXACTLY to the 7/23
  snapshot (blocking gate caught + fixed 3 real defects: duplicated LAA gamePk, PIT rows pasted into
  SD, pipe-delimited starters.csv read as CSV).
- As-of pitcher shrunk K-rate × opponent log5 (o = ΣSO/Σ(AB+BB), N0=200, strict date<D). Mean
  adjustment size 0.279 K. row_id = pid|gamePk; 1,757 unique == count; 0 quarantined-in-population.
- Doubleheader provenance resolved factually via pitcher gamelogs (Yamamoto + Schlittler 7/19 =
  gamePk 823523), not deterministic assignment.

## Results — paired, baseline vs E1 (+ΔMAE = E1 better) — EXPLORATORY
| slice | n | MAE base | MAE E1 | ΔMAE | NLL base | NLL E1 | slope E1 |
|---|---|---|---|---|---|---|---|
| OVERALL | 1757 | 1.849 | 1.838 | +0.011 | 2.236 | 2.230 | 1.009 |
| premium-K arms (p≥27%) | 172 | 1.974 | 1.965 | +0.009 | 2.307 | 2.299 | 1.217 |
| high-oppK offenses (o≥24%) | 334 | 1.781 | 1.785 | −0.004 | 2.201 | 2.189 | 1.088 |
| interaction (prem × highK) | 29 | 1.439 | 1.477 | −0.037 | 2.149 | 2.136 | 1.269 |
| complement (rest) | 1728 | 1.855 | 1.844 | +0.011 | 2.237 | 2.231 | 1.010 |

Line-dependent metrics (displaced-line hit rate, decision-change ROI) deferred — no historical prop lines.

## Reading (bounded to what the evidence supports)
- On this reconstructed sample, **E1 did not demonstrate material incremental predictive value**:
  overall ΔMAE +0.011 K is a third of the pre-registered 0.03 materiality threshold, and the
  interaction cell — the premium-arm × high-K matchup — did not improve (−0.037 K). Calibration held
  (slope 1.009, NLL flat).
- **This does NOT identify the cause of the Cole (7/22) and Sale (7/23) misses.** The failure of
  this specific full-strength log5 opponent-K specification to add value is not evidence that those
  deviations were "variance." Their cause remains **unexplained**. The only supported conclusion is
  that E1, as specified, did not show incremental value on the observed sample.

## Actions
- **Engine unchanged:** no opponent-K term; no ledger or authorization changes ($0, gate 9/100).
- Retain the data pipeline + reconciliation gate + opponent-K reference table for forward tracking /
  display only (never alters plays).
- Original confirmatory replay CLOSED as unrecoverable. `verdicts.mlb_kprops` opponent-K channel is
  NOT resolved either way; the ≥0.9K-deviation question stays open.
- Future: if opponent-K is to be tested confirmatorily, pre-register E1-R against a forward holdout
  (frozen method/thresholds, scored once). A dampened-opponent variant would be its own pre-registration.
