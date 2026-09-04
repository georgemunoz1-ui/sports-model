# MLB Probability Calibration V1

Status: **PROSPECTIVE ACCUMULATION**  
Action authority: **OFF**  
Market/EV overlay: **DISABLED**

## Purpose

MLB currently exposes two deliberately separate probability estimators:

- **Analytic P** — independent-Poisson fixed-rate win probability at engine-implied mean runs.
- **Stochastic Sim P** — empirical win probability from the registered Gamma-Poisson Monte Carlo distribution with starter-workload uncertainty.

They are not averaged. Their disagreement is a structural diagnostic until prospective calibration establishes which estimator is better calibrated out of sample.

## Known structural finding

The 2026-09-04 16-game diagnostic ablation isolated the dominant source of disagreement:

| Effect | Observed debugging-slate magnitude |
|---|---:|
| Analytic-vs-Sim mean absolute gap | 6.29 pp |
| Fixed Poisson -> fixed Gamma favorite compression | **6.14 pp mean** |
| Fixed Gamma -> starter-workload effect | **0.01 pp mean** |
| Maximum Gamma effect | 13.96 pp |
| Maximum workload effect | 0.41 pp |

Interpretation: **Gamma run-rate overdispersion explains nearly all of the observed favorite-probability compression on this slate.** Starter-workload randomness contributes little additional probability movement. This is diagnostic evidence, not calibration evidence.

The current engine does not model a shared run environment or bullpen sequencing, so those mechanisms must not be cited as causes of the current gap.

## Forecast grading block

Every generated card now carries a `grading` object per numerical forecast. For MLB, a forecast is eligible for the clean calibration benchmark only when:

1. `PIT_ALIGNED` is true for the card.
2. The card generation timestamp precedes game start.
3. The maximum captured source-fetch timestamp precedes game start.
4. Explicit home-oriented Analytic P and Stochastic Sim P can be resolved.

The block freezes:

```text
analytic_p_home
stochastic_sim_p_home
normal_margin_candidate_p_home
awaiting_outcome
eligible_for_prospective_grading
calibration_bin_analytic
calibration_bin_sim
actual_result = null
brier_* = null
log_loss_* = null
```

Outcome fields are populated only by the grading process after a final score is available.

## Durable grading ledger

`scripts/accumulate_mlb_calibration.py` grades a frozen card against MLB final results and appends idempotently to:

```text
data/grading/mlb/calibration_ledger.jsonl
```

The grade identity is based on `event_id + forecast output_hash`. Exact reproduction artifacts therefore do not double-count the same numerical forecast.

The script records Brier score, log loss, decile reliability bins, PIT metadata, forecast hash, and final score. Sportsbook prices are not accepted as inputs.

## Evidence gates

| Stage | Minimum | Interpretation |
|---|---:|---|
| Early Brier comparison | 100 graded games | Directional evidence only |
| Calibration decision sample | 200 graded games | Reliability bins and estimator comparison become decision-grade candidates |
| Stability | Full season | Check structural stability across season phases |

At >=200 games the automated summary may emit one of these evidence labels:

```text
EVIDENCE_FAVORS_STOCHASTIC_SIM_P_REVIEW_FOR_PROMOTION
EVIDENCE_FAVORS_ANALYTIC_P_RETAIN_PRIMARY
CONTINUE_ACCUMULATION_DIFFERENCE_WITHIN_0_005
```

These labels are **review gates, not automatic model promotion**. No probability definition changes without a versioned model-state decision and chronological calibration review.

Working Brier separation threshold: `0.005`.

## Normal-margin candidate

The proposed candidate

```text
Phi(mean_margin / margin_std)
```

remains diagnostic only. On the initial 16-game test it reached only 6/16 games within 2 pp of Stochastic Sim P, versus the 90% working engineering target. It is not promoted.

A future deterministic Gamma-Poisson probability calculation may be evaluated because it would preserve the stochastic model's overdispersion without Monte Carlo sampling noise. It must first be benchmarked against the existing prospective calibration baseline; it is not a prerequisite for collecting outcomes now.

## Market lock

No market prices, implied probabilities, line movement, or EV calculations enter this calibration loop. Market overlay remains held while probability-definition calibration is orange.
