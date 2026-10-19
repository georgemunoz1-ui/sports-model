# PREREG: Margin-Distribution Layer — Validation Harness & Evaluation Plan

**Status:** PREREGISTERED — research-only diagnostic
**Schema:** `docs.prereg.margin_layer.v1`
**Date:** 2026-10-07
**Scope:** `models/common/margins/` (core API), `pipelines/margins/` (sport adapters +
validation harness), `tests/test_margins_*.py`
**Implementation anchor:** `pipelines/margins/validate.py`
**Action authority:** NONE. Nothing in this layer places, sizes, routes, or
recommends any wager; nothing auto-promotes any model; nothing mutates a
frozen artifact.

---

## 1. Purpose and scope

The margin layer converts (predicted margin, market line) pairs into cover
probabilities per sport, via one of four distribution constructors
(`normal_margin`, `empirical_margin`, `simulated_margin`,
`discrete_football_margin`) and the `cover_quote` pricing function. This
document preregisters **how that layer is validated and what would ever count
as evidence for or against it**, before any graded outcome is examined.

This layer is a **research-only diagnostic**:

- Every emitted record carries `research_only: true` and
  `action_authority: false` (see `emit.py` schema `sports.margin_quote.v1`).
- Outputs may be written only to append-only ledgers; frozen model artifacts
  are never mutated.
- All evaluation is **chronological / out-of-fold only**. In-sample fit
  evaluation is rejected by the harness, not merely discouraged.

Non-goals are listed explicitly in §8 and are binding.

## 2. Definitions

All lines use the repo's **signed home-spread convention**:
`home_spread < 0` means home is favored (e.g. `-3.5`). Adjusted margin is
`actual_margin + home_spread` where `actual_margin = home_score − away_score`.

For a bet on side `s ∈ {home, away}` at line `L` with actual margin `M`:

| Term | Definition |
|---|---|
| **cover** | `M + L > 0` for a home bet; `M + L < 0` for an away bet |
| **push** | `M + L == 0` exactly (integer lines only; impossible at half-point lines) |
| **loss** | the remaining case |
| **p_cover / p_push / p_loss** | distribution-implied probabilities of the three outcomes |
| **p_cover_ex_push** | `p_cover / (p_cover + p_loss)`; always labeled explicitly as ex-push and never silently substituted for `p_cover` |

**Ex-push labeling rule.** Scoring metrics (Brier, log loss, reliability) are
computed on **decided games only** — pushes are excluded from both numerator
and denominator and reported separately (`n_total`, `n_push`, `n_scored`,
`brier_denominator == n_scored`). Any comparison that mixes push-inclusive and
push-exclusive quantities is a defect and must fail review.

**Symmetry invariant.** For any distribution and line,
`p_cover(home) + p_cover(away) + p_push == 1` within `1e-9`. The core library
enforces this; the harness assumes it.

## 3. Margin sources and sigma provenance (per sport)

Sigma provenance rules are binding on every constructor call:

1. **No cross-sport sigma sharing.** A residual pool or sigma estimate from
   one sport must never price another sport's covers. `estimate_sigma`
   requires `provenance={'sport', 'window_start', 'window_end', 'oof': True}`;
   sport mismatch or missing provenance is a hard error.
2. **Chronological OOF only.** Sigma windows must end strictly before the
   first game priced. `oof: False` or unlabeled in-sample windows are refused.
3. **Pinned windows.** Once a sigma is used in a graded output, its
   (sport, window_start, window_end, n) tuple is recorded in the ledger and
   never retroactively recomputed over the same games.

| Sport | Margin source | Sigma source |
|---|---|---|
| NFL | qb-arm margin head, bound to artifact hash | chronological OOF residuals of the **same arm**; combined-arm residual pool misuse is rejected (`UNAVAILABLE_FOR_SELECTED_ARM` lineage) |
| CFB | ridge margin model | week-segmented chronological OOF residuals |
| MLB | direct simulation counting (integer run margins) | sim counting; residual sigma only as cross-check |
| NHL | margin head (puck line ±1.5) | chronological OOF residuals; outputs keep the standing `uncalibrated` label |
| NBA / WNBA | margin heads | chronological OOF residuals, per-league |
| MLS | **UNSUPPORTED_1X2_ONLY** — no margin layer; any attempt to price MLS spreads through this layer is rejected |

## 4. Validation harness (what is computed)

All functions live in `pipelines/margins/validate.py`. Constants are pinned
in code; changing them invalidates prior audit outputs.

### 4.1 `cover_calibration(records)`

Input: chronologically ordered records (`p_cover`, `line`, `actual_margin`,
`orientation`, `sport`, `season`, `week`|`date`). **Nondecreasing timestamps
are required**; otherwise `ValueError('VALIDATION_REQUIRES_CHRONOLOGICAL_ORDER')`.
The harness never re-sorts — order is part of the audit trail.

Outputs, all push-exclusive with explicit denominators:

- **Brier** and **log loss** (probabilities clipped at `1e-7`, pinned) of
  cover probabilities over decided games.
- **Reliability table**: 10 equal-width decile buckets on `[0,1]`; per bucket
  `n`, `predicted_mean`, `observed_rate`. Empty buckets are reported with
  `n=0`/NaN, never dropped.
- **Overall bias**: `mean(p_cover) − mean(observed cover)` over decided games.
- **Calibration slope**: n-weighted least-squares slope of observed on
  predicted across non-empty buckets (gate in §5).

### 4.2 `sigma_audit(pred, actual, sport, *, seasons=...)`

Residual (`actual − pred`) sigma overall, per season, and per `|pred|` bucket
(default edges 0/3/7/10/14/21/∞ — dispersion growing with spread size is
expected, not a defect).

**Drift heuristic (documented heuristic, not a promotion rule):** the last
25% of the chronological sample is the *recent window*, the rest the *fit
window*. Flag `SIGMA_DRIFT` when `|σ_recent − σ_fit| / σ_fit > 15%`. The flag
triggers human review of sigma windows; it blocks nothing by itself.

### 4.3 `key_number_audit(margins)`

For football margin samples: empirical mass at `|margin| ∈ {3, 6, 7, 10, 14,
17, 21}` vs the smooth-normal expectation (normal fitted to `|margin|`,
probability of the rounding bin `[k−0.5, k+0.5]`). Reports per-key excess and
`total_excess_mass`; flags `KEY_NUMBER_MASS_SIGNIFICANT` when total excess
exceeds **2pp** — the documented trigger for preferring
`discrete_football_margin` over a smooth normal. Heuristic, not a gate.

### 4.4 `paired_brier_vs_baseline(records, baseline='fifty_fifty')`

Paired per-game Brier difference `d_i = (p_i − y_i)² − (0.5 − y_i)²` on
decided games (the 0.5-minus-push baseline abstains on pushes by
construction). **Block bootstrap by season-week block** (season-date when
only dates exist), resampled with replacement, **20,000 reps, pinned seed
`20261007`**, 95% percentile CI — mirroring the CFB prereg machinery. Under
60 blocks the result is labeled `BLOCK_BOOTSTRAP_UNDER_60_BLOCKS_PIPELINE_ONLY`
(pipeline validation only, mirrors `PIPELINE_VALIDATION_ONLY_UNDER_50`).
Identical inputs must produce identical CIs (tested).

## 5. Evaluation plan and promotion criteria

The margin layer is evaluated **per sport, chronologically, on graded
outcomes only**, against two baselines: (a) the 0.5-minus-push baseline
(§4.4); (b) where a legal-market cover probability exists, the de-vigged
market price as a diagnostic reference only (never a training target).

**Promotion criteria** (ALL required; promotion itself remains a human,
append-only-ledger decision — §8):

1. **Cover-Brier improvement vs the 0.5-minus-push baseline**: block-bootstrap
   95% CI of the paired Brier difference excludes 0 in the favorable
   direction, over **≥ 2 full seasons** *or* a declared per-sport game minimum
   preregistered before evaluation (e.g. CFB: 1000 games / 60 season-week
   blocks).
2. **Calibration slope in [0.9, 1.1]** (§4.1) over the same window.
3. No unresolved `SIGMA_DRIFT` flag spanning the evaluation window without a
   documented sigma-window revision recorded *before* grading continues.
4. Football sports only: distribution choice (smooth vs discrete) justified
   by a `key_number_audit` run on data strictly preceding the evaluation
   window.

Multi-sport/multi-metric families of comparisons use Holm-adjusted
intervals, consistent with existing repo practice.

## 6. Contamination rules

- **No tuning on observed 2026 slates.** Any parameter choice (sigma windows,
  distribution family, key-number mass table, bucket edges) informed by games
  played in 2026 or later disqualifies the layer from promotion evaluation on
  those games. 2026+ data may be used only as untouched prospective
  evaluation input.
- Sigma and key-number mass estimates must come from windows that strictly
  precede the first priced game (§3); the harness's chronological-order
  enforcement is the tripwire, not the safeguard of record.
- Validation-harness constants (20,000 reps, seed, 2pp, 15%, decile buckets,
  `1e-7` clip) are frozen by this prereg; changing them requires a new prereg
  version, not an edit.
- Audit outputs are append-only; a failed audit is never deleted or
  recomputed-in-place — only superseded by a new, separately dated entry.

## 7. Failure handling

| Signal | Meaning | Required response |
|---|---|---|
| `VALIDATION_REQUIRES_CHRONOLOGICAL_ORDER` | input not time-sorted | fix pipeline ordering; never re-sort inside the harness |
| `PIPELINE_VALIDATION_ONLY_UNDER_50` / `BLOCK_BOOTSTRAP_UNDER_60_BLOCKS_PIPELINE_ONLY` | sample below pipeline-validation floor | treat all statistics as engineering checks only |
| `SIGMA_DRIFT` | recent-vs-fit sigma shift > 15% | human review of sigma provenance before further grading |
| `KEY_NUMBER_MASS_SIGNIFICANT` | key-number excess > 2pp | prefer `discrete_football_margin` for football |
| `COVER_BIAS_EXCEEDS_5PP` | systematic cover-probability bias | investigate margin head and sigma before any promotion review |

## 8. Non-goals (binding)

1. **No action authority.** This layer never emits a bet, a size, an edge
   threshold decision, or a card modification.
2. **No wagering advice** of any kind; cover probabilities are calibration
   diagnostics for margin models.
3. **No automatic promotion.** Meeting every criterion in §5 produces a
   *review packet*, not a promotion. Promotion remains a human decision
   recorded in the append-only ledger.
4. **No frozen-artifact mutation.** The layer reads frozen artifacts by hash;
   it never writes to them.
5. **No cross-sport pooling** of sigmas, residual pools, or calibration
   parameters, even when samples are small.
6. **No CLV or P&L claims.** The grading loop contains no closing-line or
   profitability metrics, consistent with existing repo governance.
7. **No 1X2 sports.** MLS and other 1X2 markets are out of scope
   (`UNSUPPORTED_1X2_ONLY`).
