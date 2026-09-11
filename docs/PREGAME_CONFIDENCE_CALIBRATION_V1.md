# Pregame Confidence Calibration v1

## Purpose

This standard separates **forecast direction** from **confidence support**. A model can have a legitimate pregame opinion while still expressing too much certainty for the quality, freshness, and application state of its inputs.

The governing question is:

> Did the model's reported confidence match what was actually known and applied before kickoff?

This is distinct from asking whether a known disruption caused the final result.

## First named rule: `early_season_input_quality_gate.v1`

For NFL forecasts, if all of the following are true before kickoff:

- `season_week <= 2`
- rating state is `PRIOR_SEASON_ONLY`
- relevant current-state information was `CAPTURED_NOT_APPLIED`
- a disruption such as materially different travel/logistics state is known

then the forecast is labeled:

```text
forecast_tier = REDUCED
confidence_support_dose_cap = 0.6
uncertainty_policy = WIDEN_REQUIRED_EXACT_SCALE_NOT_ESTABLISHED
action_authority = OFF
rationale = Confidence exceeds input support
```

The `0.6` value is a **preregistered unvalidated governance cap**, not a win-probability multiplier and not a point-spread adjustment. The exact mapping from support state to predictive variance remains `NOT_ESTABLISHED` until separately estimated and validated.

## What the rule does not do

It does not:

- rewrite a frozen historical forecast;
- infer that travel, injury burden, or any other single factor caused a loss;
- claim that the observed final score was predictable;
- rescale the reported win probability after the outcome is known;
- alter the forecast mean without a separately versioned predictive transform;
- grant action authority.

The original forecast remains the official prospective object and is graded unchanged.

## Governance distinction

| Question | Treatment |
|---|---|
| Were there pregame reasons to reduce confidence? | Eligible for confidence-support classification |
| Did a disruption cause the result? | `NOT_CLAIMED` absent validated causal evidence |
| Should the model have predicted the realized score? | No hindsight reconstruction |
| Did confidence exceed input support? | Valid calibration finding when documented pregame limitations support it |

## Relationship to expanded game state

`expanded_game_state.v1` remains the primary forecast-input contract. This confidence standard evaluates whether the forecast's **certainty** is supported when some expanded-state inputs are stale, missing, or captured but not applied.

A future `nfl.elo_margin_monte_carlo.v1.1` or successor may consume the confidence record to widen the predictive distribution, but only after the variance mapping is separately preregistered and validated. Until then:

```text
mean_forecast_adjustment_permitted = false
probability_rescaling_permitted = false
uncertainty_scale_numeric = null
```

## Evidence and grading

Confidence-calibration lessons are append-only governance evidence. They never replace official Brier, log-loss, margin, total, or team-score grades. Outcome data may motivate an audit, but the trigger fields themselves must be based on information that was known before kickoff.

## Initial lesson

The first recorded lesson uses source event ID `401872657` and records a forecast near 69% for the Rams as having exceeded the support provided by prior-season-only ratings plus captured-but-not-applied current-state/travel information. The record deliberately makes no causal claim about the final result and no claim that the realized score was foreseeable.
