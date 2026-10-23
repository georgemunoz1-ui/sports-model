# Independent canonical grading follow-up

**39 independently authored cases passed after the operational source freeze**, exit 0, in 0.16 seconds on 2026-10-23 at 06:53:35 UTC. The four reviewed/test files had identical hashes before and after execution. The original conformance suite, its receipts, and all 69 files in its frozen source/input manifest are unchanged; that suite was not rerun.

This review covered the new preflight script, its focused owner tests, and the canonical workflow. Independent assertions were written before reading the owner's tests. No builder conclusion reports were consulted. Synthetic fixtures and local CLI subprocesses were used; this review did not execute a hosted workflow, acquire live results, register forecasts, settle games, or change implementation code.

| Behavior | Independent result |
|---|---|
| Clean absent registry | Returns `AWAITING_FIRST_PROSPECTIVE_REGISTRATION`; no registry, forecasts, or grades are fabricated. Empty directories, the writer lock, earlier explicit waiting reports, and rejected registration reports do not create false registration evidence. Repeated CLI attempts write only distinct operational reports. |
| Missing registry with prior state | Frozen cards, draws, selections, either ledger, summary, and a successful-registration report each cause `INTEGRITY_FAILURE`. Existing bytes remain unchanged. |
| Malformed registry | Invalid syntax, duplicate keys, nonfinite values, wrong structure, and empty registries fail instead of becoming a first-run success. A structurally nonempty registry permits acquisition only; full receipt validation remains the acquisition/grading responsibility. |
| Attempt isolation | Old-attempt results alone fail. The exact current run/attempt path must contain a finite, unambiguous JSON list. Symlinks at the results root, attempt directory, and result leaf reject. |
| Workflow gates | The workflow passes both run ID and attempt to the current-results check and gates grading on that check's explicit ready status. It no longer uses a prior-attempt wildcard. Evaluating its actual terminal condition for seven success/failure combinations preserves acquisition failures, grading failures, preflight/current-results failures, and an unexpectedly skipped grade. The clean first-run state is allowed to finish without grading. |

One defect was independently reproduced and corrected during this follow-up: a symlink from `results/321-2` to `results/321-1` allowed old results to satisfy the current-attempt check. The original check inspected only the leaf symlink. The final source rejects each relevant path component, and all three independent symlink regressions pass. No reproduced finding remains open.

The final snapshot SHA256 is `b13b3a78bdc5ea12204796982618b2f9c6ffc0cacb27021f1d53058c62665eab`. Exact file hashes, timestamps, original-snapshot reconciliation, and the output-log hash are recorded in [BLIND_CANONICAL_PREFLIGHT_EXECUTION.json](BLIND_CANONICAL_PREFLIGHT_EXECUTION.json). Output is in [BLIND_CANONICAL_PREFLIGHT_TEST.log](BLIND_CANONICAL_PREFLIGHT_TEST.log); independent tests are [test_blind_canonical_grading_preflight.py](../../../tests/test_blind_canonical_grading_preflight.py).

This is a source-level operational check. It does not establish the result of a subsequent hosted run or independently certify the contents of forecast receipts and result observations.
