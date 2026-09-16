# Phase 1.1 durability hardening

Phase 1.1 numerical behavior remains frozen. This patch adds provenance, schema, registry, and remote-durability controls only.

## Two evidence classes

- `LOCAL_ONLY`: reproducible local evidence without a contemporaneous protected-remote receipt. It may be retained for replay/debugging but is not canonical prospective-calibration evidence.
- `REMOTE_DURABLE`: a validated shadow forecast whose content-addressed manifest was accepted by the protected authoritative remote before scheduled start.

Historical Sept. 5 Phase 1.1 files are never upgraded from `LOCAL_ONLY` by a later import. Their repository event is `LATE_DURABILITY_IMPORT`, with `retroactive_registration_permitted=false`.

## Future chronology gate

A future eligible record must satisfy:

`source observed <= cutoff <= created <= remote receipt < scheduled start`

The remote receipt is separate from the model calculation and must bind repository, protected branch, commit SHA, receipt time, and artifact-manifest SHA-256. Missing or post-start receipt fails closed.

## Default branch caveat

At the September 6 reconciliation, GitHub default `main` and operational `sportsmodel/main` were distinct stale lineages. This patch is reviewed against `sportsmodel/main`; scheduled workflow durability is not considered repaired until the governed operational lineage is reconciled into the repository default branch and protection is enabled.
