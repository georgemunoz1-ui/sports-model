# E1 — Opponent-K% adjustment · CONFIRMATORY RESULT (2026-07-24)

**VERDICT: REJECT (retain H0).** Opponent-K% does not generalize and does not even repair its own
motivating cases. Projections stay UNCHANGED. Cole 11K (7/22) + Sale 11K (7/23) are logged as
short-run clustering, exactly as Taco insisted before the data was pulled.

## Data provenance (all pre-registered, frozen before scoring)
- 30 team hitting gamelogs fetched from statsapi; **all 30 terminal G/SO/AB/BB reconciled EXACTLY**
  to the 7/23 snapshot (blocking gate; caught + fixed 2 transcription errors — SD, LAA — before pass).
- Replay table: **2,659 starts**, as-of pitcher shrunk K-rate × opponent log5 (o = ΣSO/Σ(AB+BB),
  N0=200, strict date<D, DH=start-of-day). 24 starts quarantined (post-7/19 / spot-starters), never
  league-avg-substituted. Table frozen + committed before this scoring ran.
- Mean adjustment size = **0.295 K** — the opponent term genuinely moves projections; it just
  doesn't move them toward the truth.

## Results (baseline vs E1; +ΔMAE = E1 better)
| slice | n | MAE base | MAE E1 | ΔMAE | NLL base | NLL E1 | slope E1 |
|---|---|---|---|---|---|---|---|
| **OVERALL** | 2659 | 1.862 | 1.859 | **+0.004** | 2.234 | 2.232 | 0.998 |
| premium-K arms (p≥27%) | 217 | 1.998 | 1.994 | +0.004 | 2.301 | 2.296 | 1.153 |
| high-oppK offenses (o≥24%) | 632 | 1.802 | 1.853 | **−0.050** | 2.204 | 2.223 | 0.932 |
| **INTERACTION (prem × highK)** | 41 | 1.830 | 1.938 | **−0.108** | 2.268 | 2.290 | 0.914 |
| COMPLEMENT (rest) | 2618 | 1.863 | 1.858 | +0.005 | 2.233 | 2.231 | 0.998 |

Line-dependent metrics (displaced-line hit rate, decision-change ROI) DEFERRED — no historical prop
lines exist; the pipeline now collects them going forward.

## Frozen §6 rule application
1. overall ΔMAE +0.004 ≥ 0.03 → **FAIL** (improvement is ~0, an order of magnitude below materiality)
2. NLL not worse (2.232 ≤ 2.234) AND slope 0.998 ∈ [0.90,1.10] → PASS (model stays calibrated)
3. displaced-line hit → DEFER
4. complement ΔMAE +0.005 ≥ −0.01 → PASS (no hidden broad benefit either)
5. decision-change ROI → DEFER

→ c1 fails → **not ADOPT**. Not GATE-TO-MATCHUP either: the interaction cell does not improve
(it degrades −0.108), so there is nothing to gate. → **REJECT.**

## Interpretation
The log5 combination is the theoretically correct way to merge a pitcher rate and an opponent rate,
and it applied a real 0.295-K average nudge — yet overall accuracy is flat and the premium×high-K
cell gets **worse**. Mechanism: a premium arm's own high K-rate already carries most of the signal;
multiplying in a high opponent-K rate pushes the projection up, but actual strikeouts regress, so E1
systematically **over-projects** exactly the matchups the Cole/Sale story pointed at. The two 11-K
games were pitcher-side variance, not a systematic opponent blind spot. This is the outcome the
pre-registration was built to protect: had we gated on "does it fix the recent misses," the sliced
view shows we would have *degraded* those very matchups.

## Actions (per §11 on REJECT)
- Projections UNCHANGED. Do NOT integrate opponent-K into kprops.py / price_board().
- RETAIN the data pipeline (team gamelogs, e1_data, reconciliation gate) for forward tracking + the
  opponent-K reference table (context/display only, never alters plays).
- The verdicts.mlb_kprops open question ("are ≥0.9K line deviations book-info?") is NOT resolved in
  favor of opponent-K; that channel is rejected. Deviations remain unexplained (candidate: park,
  catcher framing, ump, or genuine book edge — future E-queue, fresh pre-registration each).
- A dampened-opponent variant (shrunk opponent weight) is a DIFFERENT hypothesis; it would need its
  own pre-registration. E1 as specified is closed.
