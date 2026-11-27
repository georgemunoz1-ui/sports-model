# Unified PIT feature access — shadow migration

## Scope and evidence

Retain defaults and numerical runtime byte-for-byte. Shared access means all
eligible feature families are visible to research arms, not forced into
incumbent inference. NFL already builds one vector in
`models/nfl/contextual/runtime.py:live_features` and selects each arm's fitted
columns. The existing QB arm (0.22291 Brier) beats the combined arm (0.23103)
in the same 1,865 decisive outcomes; that reused retrospective evaluation is not
prospective validation. The combined-specific score pool cannot be lent to QB.

First integration: `python -m scripts.audit_nfl_feature_access` replays the
existing native builder on a pinned retained package and computes per-arm
matrix membership, nonzero coefficients, and fitted-imputation usage. This
is a historical feature-access diagnostic, not verified field-level PIT data.
It never updates incumbent state or emits registrations. The CLI requires
independent pins for the package, model and recovered parameters; optional
retained source roots use the repository's source_attestation. Field-level
lineage is deliberately marked unestablished even when bytes are retained.

## Per-sport migration targets (research only)

| Sport | Existing foundation | Required next binding |
|---|---|---|
| NFL | contextual runtime, base/QB/availability/travel/combined, combined joint law | source-bound personnel, weather, historical state; distinguish report absence, proxy and imputation; new independently fitted group-shrunk arm and its own OOF law |
| NBA | current baseline; possession-efficiency experiment and EPM shadow | verified box-stat pace/efficiency, pregame minutes and lineup-vs-baseline deltas; legal discrete final-score law |
| WNBA | selected FF7 model and feature pipeline | current team/player/rotation evidence, matched possession features; target-specific validation |
| CBB | shadow score/residual engine, reconciliation gate | point-in-time D-I possession/PPP/shot history, venue/MTE/rest, regulation and OT; no market inputs |
| CFB | selected week-specific/FBS winner, joint empirical shadow | retain scope; source-bound EPA/tempo/personnel/weather; separate exact score-law evaluation |
| NHL | initial score research baseline, contextual acquisition candidates | verified goalies, lineup, 5v5/special-teams/shot quality; regulation vs OT/SO law |
| MLB | selected V13 research, separate distribution research | verified starter/bullpen/lineup/park, extra-inning handling and product-specific settlement |
| MLS | initial regulation 1X2 baseline | verified xG/team/personnel/rest/venue and regulation vs advancement; postseason separate scope |

## Common feature table design (not an active training contract)

Each canonical event and cutoff must bind exact team orientation, event start,
information cutoff, model-independent input snapshot, consumed state watermark,
state hash, feature-definition/config/parameter hashes (separately), and field
records. Field records carry stable feature ID, typed value/unit, transform ID,
observation status (observed/derived/proxy/imputed/missing/conflicting/not yet
published/not applicable), source role, retained raw artifact SHA-256, exact
record locator, source publication/availability and retrieval times, input
dependencies and version, and policy for eligibility. Observed absence is not
missing acquisition. Derived features must bind all dependencies; a finite
numeric proxy is not a verified observation. Exact feature consumption is
separate by model ID/head; membership and nonzero coefficient do not establish
empirical causal importance. Market records never enter the training matrix.

Do not declare all sports training-ready from the schema. Build adapters against
native acquisition, attestation and state-update policies, then validate raw
evidence and transforms, including revision chronology. Immutable hashes do not
by themselves prove that a historical observation was available at the cutoff.
Results and market tables are held separately for grading.

## Shadow study

Keep the existing incumbent, ordinary full-context ridge, group-regularized
full-context, and prespecified leave-one-feature-group-out controls. Fit
preprocessing and group penalties on nested earlier-period splits only.
Evaluate all arms on identical chronological events, with excluded/missing
rows retained. Freeze each candidate's parameter/feature recipe and use only
that arm's prior out-of-fold residuals to estimate a compatible joint final-score
law; distinguish point heads from distribution means, preserve sport-specific
integer/OT/tie rules, and do not force winner coherence by borrowing another
arm's residuals. Compare Brier, log loss, MAE, CRPS, calibration and interval
coverage by product; use clustered uncertainty and LODO, matched coverage,
and a preregistered untouched prospective evaluation before selection review.
No automatic promotion, release, or action authority. RED/HOLD, NO_PICK, 0 units.
