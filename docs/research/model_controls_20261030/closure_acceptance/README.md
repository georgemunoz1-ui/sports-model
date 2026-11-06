# Version-bound finding evidence successor

The previous finding packet remains unchanged at
`docs/research/overhaul_2026_10_23/FINDING_EVIDENCE_remaining_prs_v1.json`.
Its shared October 24 acceptance receipt pins 671 Python source files. Ten of
those files changed during the October 30 model-controls implementation, so
validating that historical receipt against current source correctly failed at
`harness/market_capture.py`. This is source drift, not permission to edit an old
receipt or bypass the validator.

The successor packet is
`docs/research/overhaul_2026_10_23/FINDING_EVIDENCE_model_controls_20261030_v1.json`.
It retains all 19 findings, original status/limitations and Tested delivery
stage. Each entry references the unchanged parent packet and a newly executed
acceptance receipt. CI now selects this successor.

## Executed scope

On source commit `d1d690ae4a1dbc3ee9c71b0940d33aa4c0a7a991`, the full existing
Research integrity pytest step plus affected model-control regressions passed:
**985 tests across 42 files, 39.14 seconds**. The exact command, test list,
runtime environment, start/end timestamps and log/JUnit hashes are in
`acceptance.json`. All 699 tracked Python source files were hashed before and
after execution and were unchanged. That source snapshot does not claim every
file was exercised; the named test command defines the test scope.

`prior_packet_verification.log` retains the original expected rejection;
`reconciliation.json` records all ten changed source hashes and exact parent
packet/receipt identities. `successor_verification.json` records successful
validation of all 19 successor packets using the unchanged validator.

No original packet, acceptance receipt, forecast, fitted state, selection
default, authority field or Python implementation was edited by this fix.
The old result remains evidence about its original source version. The new
local test execution grants no predictive validation, model promotion,
production publication or wagering authority.
