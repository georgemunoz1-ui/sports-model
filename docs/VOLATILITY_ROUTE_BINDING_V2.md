# Explicit parent route binding, version 2

Status: local software verification; hosted checks, artifact readback and owner
confirmation of remote changes remain pending. This is a parent-routing repair,
not predictive qualification or model/default promotion.

The previous route compared only event IDs and starts. A separately pinned
parent file could therefore describe reversed or unrelated teams while sharing
those values. A correct file hash alone did not establish compatible semantics.
The new route rejects incompatible identity or scope before calling the
numerical adapter, creating a distribution, or drawing any paired scores.

## Explicit configuration and receipt identities

The receipted entry points now require configuration schema
`sports.volatility_route_config.research.v2`. The route identity is
`JOINT_VOLATILITY_RESEARCH_BOUND_V2`, and receipts use
`sports.volatility_route_receipt.research.v2`. The configuration otherwise keeps
the explicit information set, research-only authority, SHA256-pinned model
files, optional SHA256-pinned parent card, and downstream contracts.

The unchanged numerical adapter and fitted matrices remain v1. Their historical
Python API and original v1 configuration loader are preserved for reproducing
old results; they are not the new bound-route contract. A v1 configuration sent
to a receipted entry point is refused, not silently reinterpreted as v2.

## Required source declarations

Both the displayed card and the parent must already contain nonempty event and
canonical team identities. For a separate parent, the event set, start times,
ordered canonical teams, namespaces and settlement must match exactly; league
and card date must also match. Displayed target, orientation and information set
must agree with the explicit parent rather than borrowing incompatible scope.

| Row field | Contract |
|---|---|
| `event_id`, `event_id_namespace` | Nonempty explicit source event identity and namespace |
| `start_time_utc` | Parseable aware UTC start; compared as an instant |
| `home_id`, `away_id` | Distinct, nonempty, ordered canonical identities |
| `team_id_namespace` | Nonempty explicit namespace; bare IDs from different providers cannot match |
| `settlement` | Explicit supported league settlement matching the configured parent fit |
| `projected_margin_orientation` | Exactly `HOME_MINUS_AWAY` |
| `target` | Exactly `PAIRED_HOME_AWAY_FINAL_SCORES` |
| `information_set` | Exact match between displayed row, parent, configuration and fit |

Every parent row additionally declares these fields before numerical execution:

| Row field | Contract |
|---|---|
| `model_id` | Exact parent model identity required by the configured fit |
| `input_snapshot_hash`, `model_state_config_hash` | Existing 64-character lower-case SHA256 identities |

Team labels are presentation fields. Aliases are allowed when the ordered
canonical IDs and namespace agree; matching labels cannot override conflicting
IDs. This contract checks consistency of supplied source declarations; it does
not authenticate a provider or manufacture an authoritative name-to-ID map.
Source mapping verification remains an acquisition responsibility.

The receipt binds all these declarations to `parent_forecast_sha256`, calculated
from the exact full parent row, and retains the input, fit and code identities.
The existing chronology, cutoff, fit and score-head validation still runs in
the numerical adapter. No historical cutoff is relabeled as newly pregame.

## Refusal and preservation

All parent rows are identity-checked before any adapter call. Swapped, unrelated,
missing or conflicting canonical IDs; mismatched namespaces; an away-oriented
margin; wrong target, settlement, model or information set; and missing source
identity produce a diagnostic `BLOCKED` receipt with zero draws and no joint
output directory. A new display sidecar may describe the refusal; the original
card, configuration and fit bytes remain untouched. Existing output directories
are refused rather than overwritten. Malformed top-level cards or forecast rows
also retain a refusal receipt; missing event IDs stay null in diagnostic coverage.
Non-finite JSON numbers, numeric overflow and duplicate object keys are refused
in card, parent, configuration and fit files before execution. This prevents
ambiguous input identity and prevents malformed sidecar output from hiding a
refusal receipt.

Existing cards without the new declarations fail closed. Any future source-bound
successor must preserve its original parent and obtain real identities through
the authorized acquisition process. Adding guessed identifiers, using team names
as IDs, or filling missing semantic fields with defaults is not permitted.

Focused synthetic tests cover each rejection before adapter/draw invocation,
all-row prevalidation, alias acceptance, fit-scope disagreement, old-input
refusal and a matching 100,000-pair replay. These are software checks, not new
independent sports events. Local closure evidence is retained under
`docs/research/pr106_route_binding_20261104/` with status
`LOCAL_VERIFIED_HOSTED_PENDING`. The historical closure-evidence hash incident,
global release debt, actual packet acquisition and hosted delivery are separate.
Selected defaults, frozen matrices, forecasts, original journal statements,
prospective grading and wagering boundaries are unchanged.
