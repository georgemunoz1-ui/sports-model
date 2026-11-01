# CFB personnel-v2: opt-in event freshness

Implemented October 31, 2026 Pacific, on PR #99 head
`eb70c0cfd5e671a07262e42e5a9d3a2d47b4be0f`. This is an inference-timing
experiment, not a new fit, selected-model change, or promotion.

The child identity is
`cfb.fbs.matchup_efficiency.personnel.v2.event_refresh.v1.research`.
It reuses the exact frozen weekly personnel-v2 coefficients. Both the parent
state and the policy enter the child's state hash. No new training outcomes,
efficiency aggregates, baseline features, calibration or markets enter it.

## Timing and availability policy

| Item | Enforced rule |
|---|---|
| Opt-in | New `--personnel-refresh-config` argument; ordinary historical and SHADOW commands retain their behavior. |
| Personnel cutoff | `min(requested_as_of_utc, scheduled_start - lead_seconds)`. Explicit integer buffer of 1–86,400 seconds; examples use 300. The buffer is an operational parameter, not a fitted accuracy claim. |
| Weekly boundary | Personnel cutoff cannot precede the existing weekly cutoff. Entire schedule is prepared before selecting requested events, retaining earlier games that define the weekly control. |
| Post-start | Requests at/after kickoff are rejected, never clamped backwards. Live computation and locked writer completion must precede kickoff. Future as-of claims are rejected. |
| Existing source controls | Reuse `cfb_personnel.values`: exact bytes/hash, event/team identity, source JSON pointers, declared participation assumptions, schedule census, timezone-aware observations and strict retrieval/availability **before** cutoff. Equality is rejected. |
| Distinct cutoffs | Coverage, historical labels, training and efficiency features remain at the weekly cutoff. Only source-bound QB/returning-snap inputs use the personnel cutoff. |
| Assumptions | Existing independently retained assumption records must bind the exact source hashes; the child additionally rejects assumptions created before source availability. No status-to-probability inference. |
| Historical refresh | Original observed/retrieved/available timestamps must all exist and satisfy the same strict source cutoff checks. A later download cannot be relabeled an earlier capture, even with an anchor. The complete snapshot also needs a pre-cutoff independent signature. |
| Independent chronology | Ed25519 attestation binds exact event identity, complete personnel evidence digest, authority and recorded time. The signer must be in the separate repository-pinned trust-root file and within its validity window. The anchor time must be after all capture/availability/assumption times and before cutoff. Caller-supplied keys are not accepted. |
| Present trust state | No independent authority is provisioned. Historical admission therefore remains blocked for real inputs until reviewed trust roots and authentic historical captures exist. Tests use temporary synthetic keys only. |
| Live unanchored inputs | Structurally valid pre-start inputs may produce a local diagnostic refresh, explicitly `UNVERIFIED`, current-source qualification false and canonical eligibility false. A signed snapshot still does not authenticate the provider, parent training history or full forecasting procedure. |

## Versions, conflicts and immutability

Every source has an explicit native `version_id` bound by JSON pointer, or uses
its content SHA-256 as version identity. Its observation time must also resolve
to the retained source bytes. One version per provider/team stream is allowed
in a snapshot. Competing revisions are quarantined rather than selected by
file order or latest timestamp. Cross-provider value conflicts continue to
fail the existing source-field checks.

A refresh declares its exact predecessor receipt. Under a filesystem lock,
the writer checks the complete local chain, unchanged event identity and parent
card, increasing cutoff, unchanged source-stream set, and linked revisions.
A changed source must have a different content hash and version, a later
observed/retrieved time, and `supersedes_sha256` equal to the prior source hash.
Recapturing identical bytes does not rewrite their original receipt. A
reschedule cannot silently change an existing event chain. New parent states
or policies are distinct experiments, never additional independent events.

Receipts include both cutoffs, writer-owned actual time, predecessor, snapshot,
source versions, features, complete component receipt, parent card/state hashes,
code hashes and immutable copies of raw personnel/assumption bytes. Exclusive
writes never replace a receipt. Missing/tampered predecessors or retained bytes
block appends. A read-only `verify_retained_receipt` rechecks personnel values
and chronology from retained bytes after original input paths disappear.

The existing first-forecast SHADOW registry is untouched. Refreshes use a
separate store and declare `FIRST_ACCEPTED_REFRESH_PER_EVENT_PARENT_POLICY`;
later versions remain auditable and are not additional samples or a license to
select the best hindsight forecast. There is no automatic grading or promotion.
Local locking/content hashes are not hostile-host WORM protection, external
registration timestamps, provider authentication or canonical registration.

## Integration points

| File / function | Change |
|---|---|
| `models/experiments/cfb_personnel.py::values` | Optional personnel cutoff; original source/value checks retained; schedule coverage remains weekly. |
| `models/experiments/cfb_efficiency.py::predict` | Explicit `personnel_refresh` keyword invokes policy validation, reuses unchanged numerical kernels and emits a distinctly identified child. Default path is unchanged. |
| `research/efficiency/cfb_personnel_freshness.py` | Cutoff, identity, revision, clock, immutable writer and read-only retained-source verifier. |
| `research/efficiency/runner.py::personnel_refresh_from_card` | Full-schedule preparation, source-card and frozen-state bindings, per-event refusal/continuation, component receipts and separate refresh store. |
| `scripts/run_efficiency_experiments.py` | New mutually exclusive CFB-only command route. Existing weekly execution remains available. |
| `scripts/audit_cfb_personnel_freshness_inputs.py` | Read-only retained-capture audit; never constructs missing observations. |

Example invocation (requires real supplied files):

```bash
python scripts/run_efficiency_experiments.py --league cfb \
  --source-card /absolute/path/frozen-card.json \
  --personnel-refresh-config /absolute/path/refresh-config.json \
  --output-dir /absolute/path/new-output-directory
```

Configuration shape; placeholders are not usable evidence:

```json
{
  "schema": "cfb.personnel-refresh-run.v1",
  "mode": "SHADOW",
  "history": {"path": "history.json", "sha256": "ACTUAL_FILE_SHA256"},
  "parent_state": {"path": "frozen-personnel-v2-state.json", "sha256": "ACTUAL_FILE_SHA256"},
  "policy": {"policy_id": "cfb.personnel-event-freshness.v1", "lead_seconds": 300},
  "refresh_store": "personnel-refresh-store",
  "requests": [{
    "event": {"event_id": "CFB:PROVIDER_ID", "other": "complete canonical event identity required"},
    "requested_as_of_utc": "ACTUAL_AWARE_ASOF_TIME",
    "previous_receipt_sha256": null,
    "personnel_evidence": {"schema": "cfb.personnel-input.v2", "other": "complete source-bound v2 evidence required"}
  }]
}
```

For historical mode, each request must also contain `chronology_anchor` with
`payload` (`schema=cfb.personnel-clock-attestation.v1`, `authority_id`, canonical
`event`, `evidence_sha256`, `recorded_at_utc`) and `signature_base64`. The signature
uses the repository's canonical JSON encoding. Signed chronology is only as
trustworthy as the independently operated, reviewed clock authority.

## Executed evidence and limits

See `EXECUTION.json`, acceptance logs, and `retained-source-audit.json` for the
actual commands, source hashes and test populations. Tests cover late QB changes,
missing/naive/invalid timestamps, equality boundaries, source revisions,
signature substitution, post-start requests/writers, duplicate identities,
receipt/byte tampering, original-path removal, parent preservation and market
independence. All test personnel, probabilities and signing keys are synthetic.

The October 31 retained context audit checked 47 captures across 47 CFB events;
all 47 raw hashes matched. None contained normalized personnel-v2 evidence,
none exposed provider observation timestamps in their capture receipts, and no
injury groups were present. Existing source-bound personnel admission refused
all 47. This is a retained-input audit, not fresh source acquisition or a claim
that no useful public information exists elsewhere. The October 30 blocker
register and three earlier CFB capture records remain unchanged.

Authentic current-source qualification: **not established**. Authentic
historical personnel training/evaluation inputs and eligible fitted parent:
**unavailable in the exercised retained evidence**. New qualifying predictive
events: **0**. No Brier, log-loss, accuracy improvement or prevented-loss claim
is made. Signed source-snapshot chronology alone does not qualify the historic
parent features, training labels or EPA-provider chronology.

Before predictive evaluation, freeze this procedure/buffer and first-refresh
selection rule, acquire source-confirmed historical/current inputs, verify all
parent/input chronology, and run chronological same-event comparisons against
the unchanged weekly control. Personnel timing, model fitting and prospective
confirmation remain separate stages. No challenger promotion without that
evidence. Wagering OFF; publication ineligible; no defaults or forecasts changed.
