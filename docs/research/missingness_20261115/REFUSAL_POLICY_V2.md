# Model-specific refusal and prediction cohorts

The November 15 engineering update adds `sports.missingness_policy.v2` and
`sports.missingness_evaluation.v2`. Existing v1 artifacts retain their original
meaning. No installed policy, approved review, sensitivity threshold or model
parameter is changed by implementing this schema.

## Defect addressed

The v1 review requires numerical predictions in all three report groups:
complete, partial and missing. That cannot describe a model whose supported
behavior is to refuse a mandatory missing input. It also cannot describe a
confirmation population supporting only the complete-input scope without
implying evidence for unobserved missing-input groups.

V2 distinguishes the full witnessed opportunity population from the subset
with supported numerical forecasts. Refusals remain in the population and
coverage accounting; they are never assigned zero losses or invented
probabilities. Scored forecasts still require same-event numerical incumbent
and independent comparators.

## Required, predeclared fields per stratum

| Field | Contract |
| --- | --- |
| `prediction_groups` | Nonempty subset of complete, partial and missing in which the model is permitted to forecast |
| `prediction_source_states` | Exact source-ID mapping to allowed observation states; group membership alone does not authorize a failed mandatory source |
| `minimum_predictions_by_group` | Positive integer count for each declared prediction group |
| `minimum_refusals` | Required number of observed refusals, including zero when the reviewed confirmation scope does not require them |
| `max_refusal_rate` | Maximum refused share of the complete witnessed opportunity population |

These fields have no production defaults. Their values and empirical basis
belong in the model/product/season-specific policy before confirmation. The
existing calibration bounds, native head and units, source definitions,
freshness, imputation, fallback, engineering evidence, independent review and
signed chronology checks continue to apply.

An unsupported source state or report group produces deterministic refusal
reasons. A supported observation cannot simply be reclassified as a refusal to
avoid a difficult result. Declaring a wider supported group requires forecasts,
minimum counts and paired performance evidence for that group. A complete-only
approval cannot authorize a later partial or missing-input forecast.

## Refusal evidence

Every v2 row has a `FORECAST` or `REFUSED` disposition, and the pregame
registration binds that disposition together with the forecast/refusal object,
audit, fixture start, procedure, target and both comparator objects.

A refusal object contains `status: REFUSED` and the exact derived reason codes.
Its audit product is `coverage`; the monitored stratum retains the source
states and intended head/unit. Numerical head values and reporting controls are
absent, and candidate loss and sensitivity are null. Identity, original
registration, confirmation chronology, reconciled result and complete-population
checks still apply. Deleting a refused event fails population reconciliation.

On a refused candidate row, a comparator may either have a numerical forecast
or its own witnessed refusal. A comparator refusal has nonempty reasons, no
point estimate and no loss. On a scored candidate row, both comparators must
have numerical forecasts available by the shared registration time. No
post-result comparator substitution is allowed.

## Verification and limits

Positive and adversarial tests exercise complete-only approval, actual
predictions in all three groups, mandatory-input refusals, per-group and
refusal-count limits, refusal omission, fabricated losses, hidden numerical
heads, signed disposition changes, comparator refusals, late comparators and
wrong-event results. An independently constructed v2 full-release positive
control succeeds. A newly signed current receipt with unsupported acquisition
failures is then refused while a valid sibling league remains healthy.

These tests use ephemeral `TEST_ONLY` signing keys and synthetic outcomes. They
are software evidence, not a scientific review or a real forward cohort. The
protected production approval index remains empty. A source-bound production
measurement writer and independently exercised witness process are still
required to establish that reported source states and same-fit control values
correspond to actual acquisition and inference.
