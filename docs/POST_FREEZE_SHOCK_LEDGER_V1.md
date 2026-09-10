# Post-Freeze Shock Ledger v1

## Purpose

The shock ledger records material state transitions that occur after a forecast is frozen and the event has begun. It exists to make postgame evaluation interpretable without rewriting history.

A shock annotation is **not** a forecast revision, excuse, causal estimate, or permission to change official scoring. The primary prospective grade always compares the frozen pregame forecast with the observed final outcome.

## Two-layer contract

### Layer 1 — official prospective grade

Store the immutable forecast identity, exact frozen pregame values, observed final, and proper scoring metrics. No post-kickoff information may change this layer.

Required governance:

- `official_grade_unchanged = true`
- `shock_adjustment_applied = false`
- `primary_scores_retained = true`
- counterfactual replacement is forbidden

### Layer 2 — realized-state diagnostic

Record the observed transition, timing/exposure, evidence, and severity. This layer may contain a player-value estimate only when the estimate comes from a separately versioned subsystem.

Until such a subsystem exists, classification precedes valuation:

```text
value_delta.status = NOT_ESTABLISHED
outgoing_value = null
incoming_value = null
incoming_minus_outgoing = null
posterior_interval_50 = null
posterior_interval_90 = null
source_model_id = null
source_model_version = null
counterfactual_status = DISABLED
causal_attribution_status = NOT_ESTABLISHED
```

Do not infer player value from the score, one-game box score, yards per attempt, or the fact that the team won or lost.

## Official-grade separation

For a frozen home-win probability `p` and observed binary result `y`:

```text
Brier = (p - y)^2
LogLoss = -log(p)      when home wins
LogLoss = -log(1 - p)  when away wins
```

Margin and total errors use the frozen forecast values and final score directly. A shock never replaces these metrics.

## Value-delta states

`NOT_ESTABLISHED` means no numeric estimate may be stored.

`UNVALIDATED_RESEARCH_ESTIMATE` may store a posterior estimate only when a source model ID/version and uncertainty intervals exist. It remains ineligible for pregame adjustment, official rescoring, and promotion.

`VALIDATED_RESEARCH_ESTIMATE` may support a separately labeled research-only counterfactual. It still may not alter the official prospective grade.

## Operational decision rules

| Condition | Official grade | Counterfactual | Diagnostic label |
|---|---|---|---|
| Post-kickoff QB injury; no validated QB model | unchanged | disabled | `POST_FREEZE_QB_REPLACEMENT` |
| Post-kickoff QB injury; validated player-value model | unchanged | research-only | `POST_FREEZE_QB_REPLACEMENT_VALUE_ESTIMATED` |
| QB inactive known before frozen cutoff | create/re-run legitimate pregame card if policy permits | not post-freeze | `PREGAME_QB_CHANGE` |
| QB change after earlier cutoff but before kickoff | preserve early card; create a later registered pregame card | no backdating | `LATE_PREGAME_QB_CHANGE` |
| No material state shock | unchanged | none | `ORDINARY_VARIANCE_OR_MODEL_ERROR` |

## Seattle–New England, 2026-09-09

The first production-shaped example is `NFL_2026-09-09_NE_SEA_001`.

The frozen information-enhanced shadow forecast expected Seattle with Sam Darnold at QB1 and carried forecast-output hash `sha256:06b1afebbb335a65510bec3b6763e938175c7d916b6531e59fdc32583d9019cb`.

Observed after kickoff: Darnold suffered a hip injury on Seattle's first drive, Drew Lock entered for the next Seattle possession, and Darnold did not return. The transition is classified as a high-severity post-freeze QB replacement. No Darnold-to-Lock numeric value delta is established in v1.

The event remains fully graded against the original frozen forecast; the realized-state annotation only flags the clean-context slice for downstream stratification.

## Prohibitions

Never:

- rewrite the pregame probability, margin, total, or team-point projection using post-kickoff information;
- replace official Brier/log-loss with a counterfactual score;
- estimate `Lock - Darnold` from the 13-10 final or either quarterback's one-game stat line;
- use an unvalidated value delta for arm promotion;
- use postgame shock information as though it had been available at the pregame cutoff;
- label a value difference causal without a validated causal/player-value design.
