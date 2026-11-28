# Model version and immutable state contract

Recorded November 22, 2026 Pacific. This is the owner-requested amendment to
rules 3 and 5. The original numbered policy was not located in the inspected
repository, so this document records the amendments without inventing the other
rules or replacing the unrelated R3/R5 in `AGENTS.md`.

**Status: adopted documentation contract; implementation acceptance cases below
are planned, not passed.** This amendment changes no executable code, frozen
forecast, model/default selection, fitted artifact or registry entry.

## Rule 3 amendment — separate procedure and state identities

Record the state hash separately from the configuration, parameter and
input-snapshot hashes. Require the registry to resolve the full state hash to a
retained immutable state snapshot and verify that snapshot at forecast freeze
time. Display the model version and a short state-hash prefix on the HTML card;
retain the full digest and snapshot reference in the JSON receipt. Consecutive
cards may share a model version while identifying the distinct states that
produced their forecasts.

The model version identifies the recorded forecasting procedure used for
evaluation across dates. The state hash identifies the exact team/event state
that the procedure consumed. A package hash or a combined model/state/config
hash does not replace these separate fields.

## Rule 5 replacement — routine refresh boundary

A state refresh retains the model version and its existing validation status only when the documented refresh procedure advances team or event state using inputs available by the forecast cutoff. The fitted parameters, residual bank, feature definitions, history and cutoff rules, and settlement logic must match the recorded version. A refit or a change to any of those rules must be classified separately. A refresh grants no promotion or additional validation credit.

### Cutoff value versus cutoff rule

Advancing the actual forecast cutoff or state-history boundary under the same
documented policy can be routine. Changing the embargo, eligible-history window,
availability convention, season/week inclusion policy or cutoff rule is a
procedure change. Preserve the actual boundary in the state snapshot and the
forecast cutoff separately in the receipt. A change in state-history boundary
must be traceable even if the numerical team ratings happen to be unchanged.

Likewise, identical point estimates or coefficients do not establish an
unchanged probability procedure: a changed residual bank can change cover and
total probabilities. A refit remains separately classified even if its output
happens to match the old parameters. Newly fitted NBA/NHL deployment packages
must not be relabeled as routine refreshes merely because their family model ID
is unchanged.

Existing validation remains restricted to its recorded product, population and
information-set scope. A new state receives no new validation credit. Changes
outside the routine-refresh contract require a separately recorded identity and
evaluation disposition before they can be treated as the same validated
procedure; no automatic promotion follows.

## Required identity and snapshot fields

| Field | Meaning and verification |
|---|---|
| `model_version` | Recorded forecasting-procedure version; do not append a date solely because state advanced. Preserve family, parent and child IDs separately where applicable. |
| `state_sha256` | Full SHA-256 of the declared canonical state-snapshot representation. Use the complete digest for lookup and comparison. |
| `state_snapshot_ref` | Retained immutable object that the registry resolves and re-hashes before freeze. A digest without retained bytes is insufficient. |
| `configuration_sha256` | Exact applicable predictive configuration, distinct from state, inputs and presentation settings. |
| `parameter_sha256` | Exact fitted parameters and transformations for the selected parent or child. |
| `residual_bank_sha256` | Exact consumed residual bank. If none is consumed by this product, use null with an explicit `NOT_USED_FOR_THIS_PRODUCT` reason; do not borrow another arm's bank. |
| `feature_definition_sha256` | Recorded feature definitions and numerical transform identity. |
| `history_rule_sha256`, `cutoff_rule_sha256` | Recorded history-admission and cutoff policies, distinct from their realized dates/times. |
| `settlement_logic_sha256` | Product-specific period, tie/push/overtime and settlement logic. |
| `refresh_procedure_sha256` | Recorded state-update procedure or immutable procedure manifest. |
| `input_snapshot_sha256` | Exact event-level input snapshot consumed for this forecast; retain the existing native input hash under its original name too. |
| `state_history_cutoff_utc`, `forecast_cutoff_utc` | Realized state boundary and forecast information cutoff; neither is an assembly, generation or registration timestamp. |
| `state_verification` | Actual verification clock, verifier identity, full expected/observed digests and scoped result. |

The state schema must cover all state actually consumed by the selected path,
including team and QB/personnel state where used, consumed-event membership and
the applicable history boundary. Retain source bindings and native state IDs.
Declare canonical serialization and schema version; identical canonical content
resolves idempotently, while distinct content has a distinct hash. Retain parent
state/transition lineage without overwriting an existing object.

Missing, altered, unresolved or cross-model state bindings must fail the new
freeze contract before the forecast/receipt is committed. Preserve any raw
diagnostic output with its failure status; do not call it a verified freeze.
State-identity registration does not constitute canonical prospective forecast
registration, source authenticity, validation, publication or wagering authority.

## Display and evaluation behavior

HTML must show the full model-version label and a readable state prefix, with
the full digest available in the JSON receipt. Prefixes are display labels only;
registry lookup and equality use all 64 hexadecimal characters. Unknown legacy
state identities remain explicitly unavailable rather than reconstructed as a
historical freeze-time attestation.

Preserve numerical/RNG identities and retained draw bytes when adding metadata.
HTML export must preserve the original JSON text, including 64-bit seeds; do not
round-trip it through JavaScript numbers. A new display edition must reference
its frozen parent and must not overwrite an earlier card.

Evaluate the same model version across eligible dates within the declared
product, arm, population and cohort policy. Keep state hashes as replay and
diagnostic dimensions rather than treating every state as a new procedure.
Maintain the existing first-forecast/event deduplication rule: a later state,
quote refresh or contract evaluation does not create another independent game.

## Source-reviewed integration map

Inspected PR #127 head `dfbd82232493ad82287c2f51fc99f10795da2c0e`.
Two independent read-only agent reviews agreed on these boundaries.

| Path | Current source finding | Required implementation |
|---|---|---|
| Shared current packages | `models/current/common.py` validates a combined model/state/config digest. | Add a separate complete-state resolver without renaming or rewriting legacy hashes. |
| Shared card | `scripts/generate_card_force.py` normalizes an explicit field list and writes JSON/CSV/Markdown. | Retain the separate identity fields, resolve state before the first freeze write, and add an HTML renderer. |
| Existing freshness diagnostic | NBA/NHL/MLS state-receipt failures become warnings. | Do not reuse this permissive behavior for the required freeze gate. |
| NFL integrated runner | `scripts/run_nfl_integrated.py` has a separate persistence path; weekly-state verification already replays immutable nodes. | Bind the verified complete team/QB state before persistence; retain native node and any new envelope hashes separately. |
| NFL distribution children | Selected-QB margin and combined-arm distributions have different fitted laws and residual use. | Give each child its own parameter/bank/config/settlement binding and exact parent-state reference. |
| Canonical registration/grading | `scripts/canonical_forecasts.py` currently carries combined/input hashes and groups scores using the combined hash. | Require verified state for new-schema receipts, retain old receipts, and add procedure-level evaluation across states without changing event deduplication. |
| CBB and November full-card HTML | Active CBB source and external November assembler are not in this consolidated checkout. | Integrate and test their actual retained paths separately; shared-runner changes alone do not cover them. |

Do not edit `models/current/common.py`, `pipelines/cards/semantic_identity.py`
or pinned NFL numerical modules merely to add display metadata. Their source
hashes participate in package admission or numerical/RNG identity. Use a
separately versioned assembly/freeze boundary and retain its own code identity.

## Integration acceptance cases — all planned

| Case | Required result |
|---|---|
| 1. Consecutive routine states | Same recorded model version and validation scope; different retained state digests; complete state resolution at each freeze. |
| 2. Repeated identical state | Idempotent resolution, no overwrite and no additional observation merely from rerunning assembly. |
| 3. Missing, altered or wrong-model snapshot | Freeze refusal before the new forecast/receipt is committed; explicit failure evidence retained. |
| 4. Fixed points/parameters, changed residual bank | Refuse routine-refresh classification and inherited qualification. |
| 5. Cutoff value and rule | A later allowed cutoff value can retain the version; a changed history/cutoff rule cannot pass as routine. |
| 6. Other procedure changes | Refit, parameter, feature, predictive-configuration, refresh-rule or settlement changes receive a separate classification and appropriate identity, never a silent state-only label. |
| 7. Identity propagation and numerical stability | HTML/JSON/CSV agree; full digest resolves; raw JSON export preserves seeds; metadata attachment preserves numerical identities, probabilities and draw bytes. |
| 8. Complete native state | NFL includes team and QB state; every active parent/child has its own compatible binding; partial hashes cannot attest complete state. |
| 9. Cohort continuity and legacy artifacts | Same procedure grades across dates; state/quote editions do not double-count an event; old missing-state receipts stay unchanged and are not retroactively certified. |

These are acceptance requirements, not a report of executed tests. This
documentation amendment ran no inference, fitting, predictive evaluation,
forecast settlement, canonical registration or deployment.

**RED / HOLD · NO_PICK · ACTION_OFF · 0 official units. No automatic merge or
promotion.**
