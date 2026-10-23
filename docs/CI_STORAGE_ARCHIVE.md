# CI archive and storage monitor

These changes separate software acceptance, durable evidence retention and an
optional GitHub copy. They do not change model authority or grant release
clearance. No artifact deletion or notification sender is implemented.

## Inventory and recoverability, October 23, 2026

The recursive main tree at `90daf8e0036c67a5304aa0747bf50b2266e0b364`
contained 2,725 entries and was not truncated. All 24 open PR changed-file lists
were inspected. No Drive uploader executable was located in those sources.
`docs/ARTIFACT_STORAGE_REPAIR.md` documents earlier compression and a separately
retained Library backup; it does not contain a configured CI Drive uploader.
An existing Drive archive folder was subsequently located at
`1zQnJYCktPvBHOYL805ozk_yfUD17Lguj` (Sports Model Archives). A folder and a
connected interactive uploader do not establish GitHub Actions credentials.

MLB run `39906285378`, job `120258891413`, checked merge candidate `fe0d38f`
for PR head `f6cbfcda2528a76ca1bf4710ef3e05711a3d6c4a` and main `90daf8e`.
Its original job-log service reports 32 passing tests, `HEALTH_EXIT=1`, health
RED with four failures and six warnings, then artifact quota exhaustion. The
run-artifact endpoint returned no artifacts. The job-log text is recoverable;
its timestamped rendering of health output is not the original
`mlb-health.log` byte stream. A recreated file or rerun must be labeled as a
transcript/reconstruction or a new execution, never the original artifact.
There is no basis to claim the failed-upload Git bundle can be recovered from
log text. A newly generated bundle has a new receipt and execution identity.

## Archive behavior

`scripts/ci_evidence_archive.py` packages explicit files in a new directory.
Its ZIP includes `manifest.json`, `checksums.sha256`, exact report bytes,
repository/workflow/run/attempt identity, checkout SHA and nullable head/base
SHAs. Missing optional reports are disclosed. Reports are not recreated or
silently omitted. Every present member is checked before upload and after an
independent download of the returned Drive object; the entire ZIP must match
SHA-256 and size. The archive name includes run, attempt and manifest hash.

The MLB-current and consolidation workflows invoke this path before any
optional GitHub upload. Consolidation keeps its complete `--all` Git bundle,
reference comparison and bundle verification. With no configuration, the
archive emits `BLOCKED_UNCONFIGURED`, `durable_archive_verified: false`, and
skips GitHub upload. This is a disclosed retention blocker, not an archive
success. Software checks can still run. Configured upload or verification
failure is fatal; there is no blanket archive `continue-on-error`.

If explicitly enabled by `CI_OPTIONAL_GITHUB_ARTIFACTS=true`, a verified archive
can also be copied to GitHub with seven-day retention. That optional copy has
its own outcome and cannot retroactively invalidate a verified Drive copy.
Its failure is recorded separately. Other workflows' retention is unchanged.

## Configuration and adapter contract — deployment still blocked

The new repository variable `CI_STORAGE_CONFIG_JSON` must contain:

```json
{
  "schema": "ci-storage-config-v1",
  "adapter_path": "operator-supplied-path-to-approved-bridge.py",
  "adapter_sha256": "operator-supplied-64-character-sha256",
  "drive_destination_id": "operator-authorized-folder-id"
}
```

These are schema examples, not configured values. The operator must supply the
existing authorized uploader and its CI authentication/setup. No credential,
secret name, OAuth scope, service account or new permission grant is assumed.
The bridge is executed as `python adapter.py OPERATION`, receives one JSON
object on stdin and returns one JSON object on stdout. Each response includes
`provider: "google_drive"`. Nonzero exits, malformed output, changed adapter
code or mismatched identities fail closed. Credentials must not be put in the
variable or bridge output; adapter stderr is not echoed by the caller.

| Operation | Request / required response |
|---|---|
| `capabilities` | Return `protocol: "ci-storage-adapter-v1"` and `operations` list. |
| `put_immutable` | Accept `destination_id`, `name`, `local_path`, `sha256`, `size_bytes`; return matching destination/name and a nonempty `object_id`. Existing identical objects may be reused; conflicting bytes must never be overwritten. |
| `download` | Accept `object_id` and a fresh `local_path`; materialize the exact binary bytes. The caller independently hashes them. |
| `state_get` | Accept `destination_id`, `state_key`; return `state` and opaque `revision`, both null only when no state exists. |
| `state_compare_and_swap` | Accept the same key, `expected_revision`, and complete `state`; atomically refuse stale revisions; return new `revision` and canonical `state_sha256`. The caller performs a separate read-back. |

The archive needs the first three operations. The monitor also requires the
two state operations, including real compare-and-swap semantics. A list-then-
overwrite emulation is insufficient. A mock adapter verifies this protocol in
tests; it is explicitly not a deployed Drive uploader. Integration is complete
only after the real bridge/auth path has passed an upload/download test and
state-conflict test against the intended destination. Current tooling cannot
configure GitHub variables/secrets, dispatch workflows or read account billing.

## Persistent threshold monitor

`scripts/ci_storage_monitor.py` requires complete paginated artifact metadata.
It sums visible, nonexpired artifact sizes in **this repository**. It reports
account quota as `UNKNOWN_NOT_MEASURED`; the result excludes other repositories,
unavailable artifacts, billing adjustments, caches and any separate account
quota calculation. No below-threshold result proves uploads are available.
Incomplete, duplicate or changing pagination fails rather than becoming zero.

`CI_STORAGE_MONITOR_CONFIG_JSON` must explicitly provide schema
`ci-storage-monitor-v1`, `repository`, metric scope
`repository_visible_active_artifacts_bytes`, positive integer `threshold_bytes`,
`state_key`, and `initial_below_policy` (`baseline_only` or `record_event`). No
threshold or initial-below policy is chosen automatically. Threshold/scope
changes cannot reuse a prior state's identity silently.

Persistent state is fetched from the configured adapter, hash-checked, updated
using compare-and-swap and read back before success is reported. At-or-above to
below emits one pending `CROSSED_BELOW` event; repeated below observations emit
none. Initial-below behavior follows the explicit policy. Returning above and
crossing below again emits a new event. Pending events remain pending: no event
is represented as delivered, no sender is enabled and no recipient is assumed.

The workflow is manual or a relevant main-branch push, with serialized runs;
there is no schedule yet. With missing configuration it records
`BLOCKED_UNCONFIGURED`; notifications remain `DISABLED_UNCONFIGURED`. Enabling
periodic monitoring and delivery requires the operator's threshold/scope,
persistent state location, cadence, destination/recipient and delivery/ack
policy. No existing artifact is deleted by either script or workflow.

## Validation

Offline tests exercise sealed ZIP members and run identities, successful fake
transport read-back, corrupt downloads, pinned-code tampering, immutable output
directories, configured failures, actual workflow ordering/retention, complete
pagination, initial-below policy, repeated-below suppression, recrossing,
configuration changes, compare-and-swap conflicts and state corruption. These
tests establish implementation behavior, not actual Drive retention or quota.
