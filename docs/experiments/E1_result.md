# E1 — Opponent-K% adjustment · CONFIRMATORY RESULT (2026-07-24)

**VERDICT: REJECT (retain H0).** Scored on the PAIRED experiment-of-record population (engine-eligible,
n_prior≥5, ≤7/19 horizon). Opponent-K% does not generalize and does not repair its motivating cases.
Projections stay UNCHANGED. Cole 11K (7/22) + Sale 11K (7/23) logged as short-run clustering.

## Population correction (Taco red-gate)
A first pass scored 2,659 starts — WRONG population: it swept in pitchers with 1–4 prior starts, whom
the engine's own `proj()` refuses (`len(starts)<5 -> None`). The experiment-of-record is the **paired
n_prior≥5 population** the engine actually operates on. That first score is VOID. Corrected population:
- **1,757 starts** (vs the recorded 1,759 — 2 fewer because the Sale phantom-row repair removed 2
  ineligible starts since the record was set; a data correction, not a drop).
- row_id = `pitcher_id|gamePk`; **1,757 unique ids == count**; **0 quarantined-in-population** (the 4
  eligible rows first quarantined — Yamamoto/Schlittler 7/19 DHs, Chandler/Ashcraft — were resolved
  after fixing a full-team-name canon gap in results.csv and adding same-opponent-DH handling).
- Baseline projection **identical** to the engine on all 1,757 rows; E1 adds ONLY the opponent term
  (o=L ⇒ ek_e1==ek_base by construction). Paired row-for-row.

## Data provenance (all pre-registered, frozen before scoring)
- 30 team hitting gamelogs from statsapi; **all 30 terminal G/SO/AB/BB reconciled EXACTLY** to the
  7/23 snapshot (blocking gate caught + fixed 3 real defects pre-score: duplicated LAA gamePk, PIT
  rows pasted into SD, pipe-delimited starters.csv read as CSV).
- As-of pitcher shrunk K-rate × opponent log5 (o = ΣSO/Σ(AB+BB), N0=200, strict date<D, DH=start-of-day).
- Mean adjustment size = **0.279 K** — the opponent term genuinely moves projections; just not toward truth.

## Results — paired, baseline vs E1 (+ΔMAE = E1 better)
| slice | n | MAE base | MAE E1 | ΔMAE | NLL base | NLL E1 | slope E1 |
|---|---|---|---|---|---|---|---|
| **OVERALL** | 1757 | 1.849 | 1.838 | **+0.011** | 2.236 | 2.230 | 1.009 |
| premium-K arms (p≥27%) | 172 | 1.974 | 1.965 | +0.009 | 2.307 | 2.299 | 1.217 |
| high-oppK offenses (o≥24%) | 334 | 1.781 | 1.785 | −0.004 | 2.201 | 2.189 | 1.088 |
| **INTERACTION (prem × highK)** | 29 | 1.439 | 1.477 | **−0.037** | 2.149 | 2.136 | 1.269 |
| COMPLEMENT (rest) | 1728 | 1.855 | 1.844 | +0.011 | 2.237 | 2.231 | 1.010 |

Line-dependent metrics (displaced-line hit rate, decision-change ROI) DEFERRED — no historical prop
lines exist; the pipeline now collects them going forward.

## Frozen §6 rule application
1. overall ΔMAE +0.011 ≥ 0.03 → **FAIL** (improvement is a third of the materiality threshold)
2. NLL not worse (2.230 ≤ 2.236) AND slope 1.009 ∈ [0.90,1.10] → PASS (model stays calibrated)
3. displaced-line hit → DEFER
4. complement ΔMAE +0.011 ≥ −0.01 → PASS (no hidden broad benefit)
5. decision-change ROI → DEFER

→ c1 fails → not ADOPT. Not GATE-TO-MATCHUP either: the interaction cell **degrades −0.037**, so there
is nothing to gate. → **REJECT.** Verdict identical to the (void) 2,659 pass — robust to the correction.

## Interpretation
The log5 combination is theoretically correct and applied a real 0.279-K average nudge, yet overall
accuracy barely moves and the premium×high-K cell — the exact matchup the Cole/Sale story pointed at —
gets **worse**. Mechanism: a premium arm's own high K-rate already carries most of the signal, so
multiplying in a high opponent-K rate over-projects those matchups while actual Ks regress. The two
11-K games were pitcher-side variance, not a systematic opponent blind spot. The pre-registration +
paired discipline did their job: a naive "fix the recent misses" would have degraded those matchups.

## Actions (per §11 on REJECT)
- Projections UNCHANGED. Do NOT integrate opponent-K into kprops.py / price_board().
- RETAIN the data pipeline (team gamelogs, e1_data reconciliation gate, opponent-K reference) for
  forward tracking + display only (never alters plays).
- verdicts.mlb_kprops open question ("are ≥0.9K deviations book-info?") NOT resolved in opponent-K's
  favor; that channel is rejected. Deviations remain unexplained (future E-queue: park / framing / ump,
  each fresh-pre-registered).
- A dampened-opponent variant is a DIFFERENT hypothesis needing its own pre-registration. E1 closed.
