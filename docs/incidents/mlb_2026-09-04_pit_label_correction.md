# MLB 2026-09-04 PIT Label Correction

Status: **PROVENANCE CORRECTION**  
Action authority: **OFF**

## Affected runs

- Canonical diagnostic run: `33850296385`
- Reproduction run: `33850371300`

Both runs declared:

```text
as_of_utc = 2026-09-04T12:00:00Z
```

The Actions executions completed at approximately `07:47Z` and `07:48Z`, before the requested 12:00Z cutoff had occurred.

## Correct interpretation

Those artifacts are valid deterministic reproductions of the live MLB StatsAPI inputs fetched during their executions. They are **not** valid claims of a reconstructed 12:00Z point-in-time state.

Correct label:

```text
LIVE SNAPSHOT BEFORE REQUESTED CUTOFF
requested cutoff: 2026-09-04T12:00:00Z
actual live fetch/generation: approximately 2026-09-04T07:47Z-07:48Z
historical PIT reconstruction: unsupported by the current MLB adapter
```

The existing 16/16 forecast coverage and reproduction evidence remain valid for the inputs actually used. This correction affects temporal provenance, not the determinism finding.

## Remediation

The MLB adapter and diagnostic-card workflow now record separately:

- `requested_as_of_utc`
- live source fetch timestamps
- `actual_data_vintage_utc` as a fetch-time proxy
- `min_source_timestamp_utc`
- `max_source_timestamp_utc`
- `generated_at_utc`
- `pit_delta_seconds`
- `pit_status`
- `pit_reason`
- `pit_reconstruction_supported`
- `data_vintage_basis`

The fetch timestamp is explicitly labeled as a proxy, not as a source-effective timestamp.

Diagnostic shadow cards may still print when PIT is stale or unknown, but they remain non-actionable and carry a visible PIT warning. A live-only fetch after a requested historical cutoff is labeled `PIT_REPLAY_INVALID` rather than silently treated as a replay.
