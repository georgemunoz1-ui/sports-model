# Phase 1.1 durability reconciliation

Incident: `reconcile-2026-09-06-phase1-1`

This directory is an append-only preservation package for local Sept. 5 Phase 1.1 artifacts discovered without contemporaneous durable repository evidence on the authoritative remote.

- Original local artifact bytes remain preserved unchanged in the local reconciliation archive.
- The repository imports a content-addressed evidence index and lossless base64 transport chunks for the immutable source archives.
- Claimed local timestamps are **not** remote receipts.
- `retroactive_registration_permitted = false`.
- Imported Sept. 5 evidence remains `LOCAL_ONLY` and is **not** canonical prospective-calibration evidence.
- The postgame global health remains **RED**.

Observed remote heads at discovery:

- default `main`: `c3df041c513bf737b14afb613f0a73789c7d6e9c`
- operational `sportsmodel/main`: `98035a19a7ba80bff622e35f4a61661f09082d5c`

Neither branch was protected at discovery and no Sept. 5 journal entry was found. The two histories must not be silently conflated. Code lineage and evidence lineage are reviewed in separate pull requests.
