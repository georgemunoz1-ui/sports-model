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


## Native common view, phase 1

`research/native_feature_access.py` adapts the retained NFL replay and the
existing NBA/CFB efficiency constructors into a common per-event field view.
It records native transform, code digest, native input artifact hash, event
orientation, exact cutoff, declared dependency group and source timing claims.
NBA base possession/efficiency values remain visible even when the optional
personnel stage refuses. CFB optional personnel fields remain missing until
a separately bound native personnel packet exists. No native features are
refitted, no labels enter the exported numerical view and no market data is
used. The verified PIT training accessor deliberately refuses all current
replays: the available dependency groups are not authenticated field-level
proof, and rehashing a document cannot change this.

The remaining five sports require native adapters. An available or finite
feature is not automatically observed, consumed, or suitable for fitting.
The next phase must independently resolve raw dependency locators, clock
and revision receipts, source completeness and transform equivalence before
introducing any verified-PIT admission path.

## Selection policy

Use the existing target-scoped selection catalog and registered promotion
controls; do not create an automatic defaults writer. Require matched
chronological and untouched prospective evidence of a material improvement
in the prespecified proper score: Brier and log loss for winner/contract
probabilities, CRPS for the corresponding predictive distribution. Compare
point MAE and calibration/coverage as additional constraints. Use paired
block intervals, declared multiplicity correction, full-population coverage
and subgroup stability. A supported point-only head cannot claim distribution
CRPS or contract probabilities. Evidence that fails or is inconclusive is
HOLD, even with better point estimates or greater feature coverage. The
existing MLB promotion thresholds remain binding; other target-specific
thresholds must be preregistered, not inherited from MLB or tuned on results.

Examples from the October 23 retained efficiency study: NBA joint Brier
delta +0.00383308 (95% interval [+0.00145619,+0.00636617]); CFB efficiency
Brier delta +0.00045262 ([-0.00189355,+0.00270544]). Neither earns promotion.
Selection is independent of release and wagering authorization. No changes
to defaults, frozen forecast code, parameters or registry in phase 1.

The common adapter has a CLI (`python -m research.native_feature_access`).
The isolated branch CI runs the actual retained NFL event replay with the
three input-byte SHA-256 pins derived from the earlier immutable Git commit,
persists a new diagnostic receipt, independently checks the written receipt's
SHA-256 and retains it in the existing test-evidence artifact. This is not
a new pregame forecast or proof of raw field-level availability. NBA/CFB
tests exercise synthetic histories through native builders; real archive
replay remains open pending independently pinned retained inputs.
