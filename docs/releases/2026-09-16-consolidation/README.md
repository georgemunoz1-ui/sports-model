# Post-consolidation release identity audit

This record verifies the existing main commit. It is not an official release or retroactive forecast promotion.

- main: `547053102f25952323d123b019df07aed9661fc9`
- sportsmodel/main: `a9957cdadd8e5836c77057e9bb3bd34913fdcb3e`
- Identical content tree (Git SHA1): `c7ecb703d5e380690eb367f1ef91ce48797fcb92`. Commits differ.
- Main CI run: `35047682608`; 331 tests passed. Health exit code: 1.
- Downloaded artifact SHA256 matches GitHub's recorded digest.
- Hosted image: ubuntu-24.04 / 20260907.300.1. No container/environment digest was captured; none is invented.

See release-identity.json for dependency-file hashes, tree-manifest digest, retained evidence hashes, scope and closure criteria. The model-access guide exists in this exact tested checkout at docs/CONSOLIDATED_MODEL_ACCESS.md.

## Findings that change the repair plan

1. Production archive repository is reachable. Reachability is not restoration, schema validation, full date-window coverage or confirmation of the exact source used by the historical run. The source-health implementation currently only checks for some window files and a 40-character commit; official archive acceptance needs stronger coverage/hash checks.
2. Four recovery jobs remain RUNNING: RJ-001, RJ-005, RJ-006 and RJ-007. RJ-001's 123/123 counter covers provenance; its score verification subphase remains 0/126. Do not close it from the headline counter.
3. The September 3 release has zero artifact and contract problems but remains correctly BLOCKED. Healthcheck hard-codes that historical decision as today's mandatory gate. It also includes market/action requirements. Preserve that manifest; separate historical integrity from a versioned current forecast release profile through an explicit dependency/specification change. Do not relabel the old release or silently remove its gate.
4. The test run is not evidence of protected branches/tags or full container reproducibility. A protected release tag and required release-suite acceptance remain unestablished.

No inputs were refreshed, no new forecast executed, and no recovery obligation closed in this identity audit. The original audit and historical forecast artifacts remain unchanged.
