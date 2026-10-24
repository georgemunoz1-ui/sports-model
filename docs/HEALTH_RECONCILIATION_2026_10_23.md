# Scoped health reconciliation — October 23, 2026

This is an evidence inventory, **not a rerun or closure certificate**. It preserves every failure/warning emitted by the local swarm health command and distinguishes that partial-checkout execution from hosted checks. No failure is marked resolved by editing documentation.

## Source and scope

- Command: `python harness/healthcheck.py`; return code **1**.
- Execution: **2026-10-23 10:05:11.975145–10:05:41.072489 UTC**.
- Working copy: `/workspace/scratch/101f83f5c588/sports-model`, a partial materialization rooted in remote `278b9a2e655b72b720fefc215a5129a8e6cd2c93`, with the local research patch applied. It was not a complete clean main checkout.
- Original retained log: `evidence/commands/global-health-scope-final.log` inside the delivered `Sports-Diagnostic-Swarm-Evidence-2026-10-23.tar.zst`.
- Log SHA-256: `3b5248cbfe0964cfc874b32bc46fac8a2731b85ba806c1d15ea6627685455463`.
- Archive SHA-256: `c91e7b49a1e0f86eacc4d711e5bbe6e80457dc0521f28c11eee345f084c8d8c7`.
- Exact count: **55 failures and 4 warnings**. Rows below preserve the emitted messages, including their original truncation. A missing local file does not prove it is absent from canonical GitHub history.

The independently recorded hosted [main MLB run 39915188865](https://github.com/georgemunoz1-ui/sports-model/actions/runs/39915188865), reconciled in [PR #77](https://github.com/georgemunoz1-ui/sports-model/pull/77), reported **4 failures / 7 warnings**. Different checkout, environment, time and populations make those counts incomparable. Do not subtract 4 from 55 and claim 51 repairs. Neither report is global release clearance, and this update has not rerun either health environment.

## Review categories and next actions

These are scoped triage labels, not newly proven root causes or named-person assignments.

| Code | Count | Meaning | Responsible function / next executable action |
|---|---:|---|---|
| A | 36 | Emitted absence/fixture/provenance dependency or its dependent self-test check | Data/repository owner: restore exact pinned evidence in a complete checkout, verify hashes and rerun the affected check |
| X | 15 | Failed assertion, missing output or execution result requiring reproduction | Relevant harness owner: capture full subprocess output at the same source/configuration; separate fixture/env failure from a code defect before changing code |
| G | 4 | External source, recovery, historical release or standing-health obligation | Release/data owners: supply versioned archive or obligation-specific evidence; no documentary waiver |
| W | 4 | Input freshness, lineage or local worktree warning | Input/release owner: acquire fresh inputs or reproduce lineage/clean-checkout evidence; never relabel old receipts fresh |

The four G records identify the same *families* named in the hosted report, not proven identical failures or a cross-environment one-to-one mapping. Broad assertions such as frozen lineage, successor equivalence and artifact integrity need direct reproduction; this table does not declare them harmless. Apply blockers to affected claims while continuing unrelated research whose own contracts pass.

## Complete emitted inventory

All rows remain **open/not retested in this documentation update**. Source lines refer to the original hash-bound log above, not newly generated health output.

| ID | Source line | Category | Original emitted message |
|---|---:|---|---|
| F01 | 5 | A | exists: data/backfill/mlb/2026/results.csv |
| F02 | 10 | A | results.csv readable ([Errno 2] No such file or directory: 'data/backfill/mlb/2026/results.csv') |
| F03 | 11 | A | result provenance/content checks ([Errno 2] No such file or directory: 'data/backfill/mlb/2026/results.csv') |
| F04 | 12 | A | pitcher_logs cached: 0 (>=310) |
| F05 | 13 | A | close_* contamination manifest ([Errno 2] No such file or directory: 'data/backfill/mlb/2026/results_close_columns_contamination.json') |
| F06 | 14 | A | ER/BB placeholder manifest ([Errno 2] No such file or directory: 'data/backfill/mlb/2026/pitcher_logs/_placeholders.json') |
| F07 | 19 | X | FROZEN_LINEAGE (verifier A: published hashes describe commit 6d4a7c0) |
| F08 | 20 | X | SUCCESSOR_EQUIVALENCE (verifier B: no output) |
| F09 | 23 | X | ml firewall fixtures (building baseline (in memory, twice, for fixtures + determinism)...) |
| F10 | 24 | A | ml p4 forward (  placeholder manifest loads and enumerates known pid) |
| F11 | 38 | A | missing_data_audit selftest (FileNotFoundError: [Errno 2] No such file or directory: 'data/schedule/i) |
| F12 | 39 | A | missing_data_audit selftest names its own module |
| F13 | 40 | A | tier_discipline selftest (FileNotFoundError: [Errno 2] No such file or directory: 'data/backfill/m) |
| F14 | 41 | A | tier_discipline selftest names its own module |
| F15 | 46 | A | form_refresh_diff selftest (FileNotFoundError: [Errno 2] No such file or directory: 'data/backfill/m) |
| F16 | 47 | A | form_refresh_diff selftest names its own module |
| F17 | 48 | A | tier1_lineage selftest (FileNotFoundError: [Errno 2] No such file or directory: 'data/backfill/m) |
| F18 | 49 | A | tier1_lineage selftest names its own module |
| F19 | 50 | X | pregame_preflight selftest (  the fixture did not actually advance the clock, so this proves nothing) |
| F20 | 52 | A | card_render selftest (FileNotFoundError: [Errno 2] No such file or directory: 'cards/2026-08-1) |
| F21 | 53 | A | card_render selftest names its own module |
| F22 | 76 | X | baseline_offset selftest (  INV9 passed a card that no longer hashes to its registered bytes) |
| F23 | 82 | X | adaptive_state selftest (  the live ratings hold 0 teams, expected 30) |
| F24 | 94 | A | wnba_refresh_espn selftest (wnba_refresh_espn selftest: FAIL (no extension artifact at data/wnba/sou) |
| F25 | 102 | X | claim_discipline selftest (  ! C3: wnba totals refused despite a measured record: TOTALS REFUSED fo) |
| F26 | 190 | X | test_feed_adapter selftest (test_feed_adapter selftest: FAIL (3/7)) |
| F27 | 206 | X | test_market_layer selftest (test_market_layer selftest: FAIL (19/21)) |
| F28 | 214 | X | score_collector selftest (  FAIL: LIVE: /workspace/scratch/101f83f5c588/sports-model/data/feeds/fi) |
| F29 | 216 | A | board_invariants selftest (SigmaRegisterMissing: sigma provenance register not found at '/workspace) |
| F30 | 217 | A | board_invariants selftest names its own module |
| F31 | 218 | X | test_score_admission selftest (test_score_admission selftest: FAIL) |
| F32 | 230 | A | build_board_0901 selftest (FileNotFoundError: [Errno 2] No such file or directory: 'data/backfill/m) |
| F33 | 231 | A | build_board_0901 selftest names its own module |
| F34 | 232 | A | grade_wnba_0830 selftest (FileNotFoundError: [Errno 2] No such file or directory: 'cards/2026-08-3) |
| F35 | 233 | A | grade_wnba_0830 selftest names its own module |
| F36 | 234 | A | register_owner_0901_v1 selftest (FileNotFoundError: [Errno 2] No such file or directory: 'cards/2026-09-0) |
| F37 | 235 | A | register_owner_0901_v1 selftest names its own module |
| F38 | 236 | A | register_owner_0901_v2 selftest (FileNotFoundError: [Errno 2] No such file or directory: 'cards/2026-09-0) |
| F39 | 237 | A | register_owner_0901_v2 selftest names its own module |
| F40 | 238 | A | market_overlay_0901 selftest (FileNotFoundError: [Errno 2] No such file or directory: 'cards/2026-09-0) |
| F41 | 239 | A | market_overlay_0901 selftest names its own module |
| F42 | 242 | A | refresh_experiment_0901 selftest (FileNotFoundError: [Errno 2] No such file or directory: 'cards/2026-09-0) |
| F43 | 243 | A | refresh_experiment_0901 selftest names its own module |
| F44 | 246 | X | score_collector mutation suite (  FAIL: LIVE: /workspace/scratch/101f83f5c588/sports-model/data/) |
| F45 | 247 | A | board_invariants mutation suite (SigmaRegisterMissing: sigma provenance register not found at '/w) |
| F46 | 251 | A | missing-data audit (FileNotFoundError: [Errno 2] No such file or directory: 'data/schedule/identity_) |
| F47 | 252 | X | canonical-tier exposure (Traceback (most recent call last):) |
| F48 | 253 | X | registered-artifact immutability (Traceback (most recent call last):) |
| F49 | 257 | X | tier-1 board completeness (no output) |
| W01 | 258 | W | pregame inputs for 2026-10-23 (PREGAME PREFLIGHT 2026-10-23  ->  INPUTS_MISSING) |
| W02 | 259 | W | pregame inputs for 2026-10-24 (PREGAME PREFLIGHT 2026-10-24  ->  INPUTS_MISSING) |
| W03 | 261 | W | tier-1 successor lineage (no output) |
| W04 | 267 | W | git tree: 31 uncommitted path(s) (<=3 tolerated) |
| F50 | 269 | A | health page patch-note binding ([Errno 2] No such file or directory: 'data/audit/model_patch_notes.json') |
| F51 | 273 | G | lancebroz production source ({'ok': False, 'source_directory': '/home/user/lancebroz/mlb-pitcher-data/data/raw/2026/daily', 'source_commit': None, 'n_files': 0, 'expected_files': 0, 'window': {'from_inclusive': '2026-07-01', 'to_exclusive': '2026-09-01'}, 'verification_scope': 'PUBLISHED_GIT_OBJECT_WINDOW_ONLY', 'schedule_completeness_verified': False, 'historical_retrieval_proven': False, 'failure': 'PRODUCTION_ARCHIVE_UNAVAILABLE_OR_UNVERSIONED', 'problems': ['PRODUCTION_ARCHIVE_UNAVAILABLE_OR_UNVERSIONED']}) |
| F52 | 274 | G | recovery jobs (9 registered, 4 overdue, 7 defect(s) still owned) |
| F53 | 282 | G | historical 2026-09-03 release eligibility (BLOCKED; 0 artifact problem(s), 0 contract problem(s)) |
| F54 | 285 | A | board arm completeness (no MLB-bearing board found) |
| F55 | 289 | G | standing-health issue evidence and hash chain |

## Closure and claim boundaries

A closure needs the exact checkout/configuration, restored source identity, actual rerun log, affected-check result and remaining release impact. A passed unit suite, merge, changed wording or accepted research report does not close health failures. A scheduled first-registration no-work result does not prove nonempty grading.

[Machine-readable inventory](status/health_inventory_2026-10-23.json) retains the same 59 records. [Current status](CURRENT_STATUS.md) and [archive configuration](CI_STORAGE_ARCHIVE.md) track separate operational dependencies. The immutable original execution summary is retained in [swarm results](research/efficiency_2026_10_23/SWARM_RESULTS_2026_10_23.md).
