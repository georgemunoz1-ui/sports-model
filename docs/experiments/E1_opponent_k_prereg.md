# E1 — Opponent-K% adjustment for K-prop projections · PRE-REGISTRATION

**Status:** PRE-REGISTERED, frozen 2026-07-24. NOT yet run.
**R7 commitment:** every metric, slice, and threshold below is fixed BEFORE any result is seen. If a
threshold is changed after this doc is committed, the change is logged with a reason and the run is
re-labeled exploratory (not confirmatory).

Motivation is the 7/22 Cole 11K and 7/23 Sale 11K under misses — but those two points are the
*occasion* for this test, not evidence for its conclusion. This pre-registration exists specifically
to prevent "narrative repair": an adjustment that improves the two anecdotes after the fact without
generalizing.

---

## 1. Hypotheses
- **H1:** the current K projection omits opponent strikeout tendency; adding an as-of opponent-K%
  term improves projection accuracy, most for premium-K arms vs high-K offenses.
- **H0 (null, default):** opponent-K% adds no broad predictive improvement; the two recent misses are
  short-run clustering. H0 is retained unless the pre-committed rule in §6 is met.

## 2. Method (FROZEN)
Isolates the opponent effect — nothing else in the engine changes.
- Pitcher rate `p` = current engine as-of **shrunk** K-rate (unchanged formula).
- Opponent team K-rate-taken, as-of, shrunk: `o = (ΣK_taken + L·N0)/(ΣPA + N0)`, prior **N0 = 200 PA**
  at league rate `L`.
- League K-rate `L` = as-of cumulative through the day BEFORE the start.
- Combine via **odds-ratio / log5** (reduces to `p` when `o = L`, symmetric, bounded):
  `adj = (p·o/L) / ( p·o/L + (1−p)(1−o)/(1−L) )`
- `E[TBF]` unchanged; `E[K] = adj · E[TBF]`; Poisson tails unchanged.
- **Strict as-of:** `p, o, L, E[TBF]` use only games strictly before the start date. No look-ahead,
  including in the slice definitions (§5).

## 3. Data plan (prerequisite before run)
- **Opponent identity per start:** join `pitcher_logs` row (pitcher→team via `pitchers.csv`) with
  `results.csv` (date, away, home) → opponent. (No log-schema change needed; resolves the 8-field
  blocker for E1's purposes without touching the parser.)
- **As-of team K-rate-taken:** fetch 2026 team batting game logs (`strikeOuts`, `plateAppearances`
  per game per team) from statsapi (~30 fields-limited fetches) → per-team cumulative-by-date table.
- **Historical prop lines:** the displaced-line hit-rate metric needs real historical K lines. If the
  lined-start sample is **< 150 starts**, that metric is REPORTED on what exists but its gate is
  DEFERRED to forward tracking (it cannot then block adoption, but must not degrade on the sample
  available); the historical decision then rests on MAE / Brier / calibration + the slices.

## 4. Baseline
Same 1,759-start as-of replay that validated the K-model (baseline MAE 1.92 vs naive 2.41). E1 runs
on the identical start set with the identical as-of discipline; the ONLY difference is the opponent
term. Baseline = engine with the opponent term switched off.

## 5. Reporting — ALL of the following (Taco spec), baseline vs E1:
a. **Overall MAE** (projected vs actual K) and **Brier + calibration** (reliability curve, fitted
   slope + intercept, dispersion).
b. **Displaced-line hit rate** (|proj − line| ≥ 0.8) on the lined subset.
c. **Premium-K pitchers**, separately (definition §7).
d. **High-opponent-K offenses**, separately (definition §7).
e. **Interaction:** premium arm × high-K opponent (both conditions true).
f. **Changed historical decisions:** count AND direction of plays that flip side or qualification,
   plus the **backtest ROI / hit-rate of the flipped set** (did the changes make or lose money?).
+ **Complement slice** — every start NOT in the premium×high-K cell — reported explicitly. This is
   the narrative-repair detector.

## 6. Pre-committed decision rule (FROZEN)
**ADOPT E1 as a general adjustment** iff ALL hold on the full replay:
1. Overall MAE decreases by **≥ 0.03 K** (material, above run-to-run noise); AND
2. Brier does not worsen and calibration slope stays in **[0.90, 1.10]**; AND
3. Displaced-line hit rate **≥ baseline** (or deferred per §3 — then not a blocker, but must not
   degrade on the available sample); AND
4. Improvement is **not confined to the interaction cell**: the complement-slice MAE also improves,
   or is within **0.01 K** of baseline (i.e. broad, not narrative-only); AND
5. **Decision-change sanity:** the flipped-decision set is **net non-negative in backtest ROI** — we
   do not adopt a change that would have lost money historically even if MAE improves.

**GATE-TO-MATCHUP (partial adopt)** iff: the interaction cell improves materially (≥ 0.10 K MAE) but
the complement degrades beyond the §6.4 tolerance → adopt ONLY for premium×high-K starts, labeled
EXPERIMENTAL, logged as a narrow correction — explicitly NOT a validated general feature.

**REJECT (retain H0)** iff: overall MAE flat/worse, or the only gain is interaction-cell with
complement degradation and even the cell gain < 0.10 K. On reject, the Cole/Sale misses are logged as
short-run clustering; we do NOT claim opponent-blindness as an established deficiency.

## 7. Frozen slice definitions (as-of, no look-ahead)
- **Premium-K pitcher:** as-of season K% **≥ 27%** (league ~22%; ~top quartile of starters).
- **High-opponent-K offense:** as-of opponent team K-rate-taken **≥ 24%**.
- **Displaced:** |proj − line| ≥ 0.8 (existing engine gate).
- **Material MAE move:** ≥ 0.03 K overall; ≥ 0.10 K for the interaction-cell partial-adopt path.

## 8. Thresholds needing sign-off before the scored run (irreversible once run)
| knob | proposed frozen value |
|---|---|
| premium-K cut | K% ≥ 27% |
| high-opp-K cut | opp K% ≥ 24% |
| opponent shrink prior N0 | 200 PA |
| material overall MAE gain | ≥ 0.03 K |
| calibration slope band | [0.90, 1.10] |
| interaction partial-adopt gain | ≥ 0.10 K |
| lined-start defer threshold | < 150 starts |

Once these are confirmed, the run is confirmatory. Changing any of them afterward makes the run
exploratory and requires a fresh pre-registration for a confirmatory pass.

---
## Pre-run diagnostic (2026-07-24, using Taco's 7/23 team-K snapshot)
Snapshot cross-check on the two motivating anecdotes (illustrative — uses the 7/23 season snapshot as
a ~as-of proxy; the confirmatory replay will use per-game as-of):
- **Cole 7/22 vs PIT (24.9% K, rank 3/30, high-K):** log5 raises E[K] 5.59 → 6.12 (+0.53K); UNDER
  displacement 0.91 → 0.38 → **play FLIPS to no-play**. E1 would have AVOIDED the Cole loss. Fits H1.
- **Sale 7/23 vs SD (23.0% K, rank 12/30, league-average):** log5 raises E[K] 6.59 → 6.68 (+0.09K);
  UNDER displacement 0.91 → 0.82 → **play does NOT flip, still fires, still loses.** Sale's 11K was
  pitcher-side variance vs an average-K offense; opponent-K% does not explain it.
**Consequence:** only 1 of the 2 motivating misses is an opponent-K case. The feature CANNOT be
justified by these anecdotes — narrative repair would only fix one of them anyway. E1 must stand on
the broad replay (complement slice, §6.4). This diagnostic strengthens, not weakens, the §2 guard.

---
## Data construction — FROZEN ADDENDUM (2026-07-24, principal spec; no results observed → still confirmatory)
Change log: as-of denominator PA → **AB+BB** (enables EXACT reconciliation vs the 7/23 snapshot's AB/BB
columns; ~immaterial to o, corr ≈ 0.99). Logged per the R7 rule; zero results seen when frozen.

1. **Fetch:** 30 team hitting gameLogs; fields `gamePk, date, atBats(AB), baseOnBalls(BB), strikeOuts(SO)`.
   Preserve raw responses to `data/mlb/team_gamelogs/{ABBR}.json`. Parse locally — NEVER trust the
   model-reported COUNT/SUM (the WSH "813 vs 858" was an extraction-summary error; the raw 103-row
   array reconciled to 858 exactly).
2. **Uniqueness:** key each team-game by `gamePk`, not date.
3. **As-of proxy** for start g vs opponent O on date D:
   `o_asof = (Σ_{O games, date<D} SO + L·N0) / (Σ_{O games, date<D}(AB+BB) + N0)`, N0=200 (frozen).
   Strict `date < D` = one-game shift excluding the current matchup.
4. **Doubleheader policy (FROZEN):** start-of-day totals for BOTH games — a same-date sibling does not
   enter the other's as-of. Achieved by strict `date < D`; we do NOT attempt to prove G1-final-before-G2
   from the gamelog. Policy recorded here as the frozen choice.
5. **Abbreviation map:** one explicit table normalizing all variants → canonical (AZ/ARI, WSH/WSN,
   SD/SDP, SF/SFG, KC/KCR, TB/TBR, ATH/OAK, CWS/CHW). Team-ID → canonical for the fetch.
6. **Quarantine:** any start whose opponent can't be matched to a reconciled team is EXCLUDED + logged;
   never silently assigned league average.
7. **VALIDATION / FREEZE GATE (mechanically separate, BLOCKING):** all 30 teams' terminal G (unique
   gamePk count), ΣSO, ΣAB, ΣBB must reconcile to the 7/23 snapshot before the replay table is built.
   Any mismatch → re-fetch that team; do NOT proceed. Once all 30 reconcile → freeze + commit the replay
   table; the confirmatory replay then runs ONCE without inspecting intermediate performance.
8. **Prior preserved exactly:** N0 = 200.

## Production integration (task 11, AFTER replay verdict)
- Parser: add + TEST 7-, 8-, and 10-field support (opponent-aware) before ANY 8-field forward writes.
- Forward opponent-K: SHADOW MODE first (compute + log, do not alter plays), then promote to
  `price_board()` + healthcheck ONLY if E1 passes. If E1 fails: retain the data pipeline for tracking,
  leave projections unchanged.
