# Health remediation candidate

The previous clean remote checkout failed five health checks. This candidate repairs the relay contract fixture and capability registration and separates deterministic ingestion testing from production archive availability. It does not waive a release gate.

The relay fixture is synthetic, not a recovered production capture. Its expected result and digest are retained. The lancebroz integration test uses a synthetic DataFrame and mocked parquet decoder; it verifies actual append, placeholder, duplicate and cutoff behavior but does not certify external parquet acquisition. An explicit production-source health check remains blocking.

Local verification: both self-tests pass, four repair regressions pass, 14 current-data tests pass, standard acceptance 16/16. Clean remote results are required before closure.

Recovery jobs remain unchanged. RJ-001 count 123/123 does not itself prove Tier-1 score provenance; RJ-002 lacks a terminal disposition; RJ-003 uses an unsupported closed status. RJ-005 needs historical official availability evidence. RJ-006 still lacks original immutable lineage artifacts. RJ-007 requires historical identity migration and source-backed backfill. No historical missing input can be manufactured from current reports.

Official release remains BLOCKED. No new forecast executed or promoted. The attached September 9 ratings report is comparison evidence only and is not an ARM_A input.

## Verified remote result

Clean checkout c5f9e9aa5ac2ba1c1f420fdb0a36ad1d257f6af8, workflow run 34878682302: 18 regression tests passed; readiness acceptance 16/16; health exit 1 with two failures (production archive unavailable and five overdue recovery jobs). All downloaded artifact hashes verified. The successful evidence-collection job is not a successful health check. See verification.json and audit/healthcheck.log.
