# NBA personnel experiment refusal receipts — November 15, 2026

Follow-up to draft PR #114, based on `3246bd3e6b356abe47ead1a298ce329d4622b57a`.

## Reproduced gap

The NBA historical personnel experiment wrote only `report.json` when fitting was refused. An independently executed synthetic empty-training case returned `BLOCKED` with `NBA_PERSONNEL_TRAINING_POPULATION_INSUFFICIENT` and no missingness receipt. Evaluation rows rejected before prediction likewise had only an event ID and reason. The card-side personnel runner already retained and verified receipts for successful and refused rows; that execution path is unchanged.

Two regressions failed before the fix on the missing receipt keys: the fit-failure case and a missing-personnel evaluation row.

## Additive repair

- A failed fit now adds a run-level coverage receipt to the existing report. It explicitly identifies a run without a fitted state, records the reason and unforecasted opportunity count, and leaves feature values null. It creates no state or forecast file.
- Every evaluation exclusion now retains an input-row-indexed coverage receipt bound to the original input hash, run, model ID, fitted-state hash, source-code hashes, cutoff and unchanged exclusion reason.
- A malformed or absent declared event ID is retained as supplied in the exclusion; the receipt uses an explicitly unresolved row scope. A syntactically present ID does not by itself claim identity validation.
- A result-reconciliation failure after a valid prediction keeps that prediction and its original native receipt. The new coverage receipt identifies that a forecast was emitted; it supplies no substitute value or imputed sporting effect.
- The report writer reads the saved file back and verifies all new refusal receipts before returning.

Existing numeric model code, fitted parameters, forecasts, paired results, predictive labels, CLI exit conventions and card-side flow are unchanged. The execution report's existing source hash correctly records the new audit-runner code. Previous artifacts are not rewritten. All receipts remain research-only with release HOLD and action authority OFF.

## Verification

The existing PR #114 workflow selects `tests/test_nba_personnel_minutes.py`, `tests/test_cfb_personnel_v2.py` and `tests/test_efficiency_integrity.py`. That exact scope passed **135 tests** after the repair: 128 existing tests and seven new regression cases. New cases include missing training, missing personnel, result-only exclusion, absent ID, duplicate ID and two write/readback tamper checks. The valid sibling forecast is compared directly with the unchanged native model output.

This is software and evidence-retention verification. It grants no source authentication, independent statistical approval, predictive qualification or deployment authority.

## Independent review successor

Independent review of `54631e115216d1ab4216e348aa5e0772ad198f8f` found two further defects. Removing all exclusions and editing the counters could pass the standalone report verifier, because it only checked remaining entries. A `None` evaluation row or `None` event container also raised before protected event handling, preventing the valid sibling's final files from being written. Four independently authored regressions reproduced these failures; publication was held.

The successor derives an indexed inventory from every original evaluation row before fitting. It retains each original row's digest, declared event identity and container types, then records the actual disposition and any emitted forecast hash. This inventory and the complete report are bound by a run-level coverage receipt. The verifier reconciles all paired/excluded counts and dispositions against the inventory, including duplicates and unresolved rows. A supplied original input path independently rebuilds the inventory; the writer always supplies that path and compares the complete original input hash before writing and again during readback. The fit-failure path receives the same input comparison, so a source changed during a failed fit cannot publish a misleading refusal report.

All prediction-row/event extraction now runs inside protected per-row handling. Malformed containers receive explicit indexed exclusions with no invented sporting identity or feature values, and valid siblings retain their output. An unknown declared ID is not automatically counted as a duplicate sporting event.

The exact three-file PR #114 workflow scope now passes **141 tests**. The independently authored four probes plus the expanded NBA suite passed **53 tests**; those populations overlap and are not additive. Additional regressions check source-inventory reconstruction, ordinary report omission, altered counters, and input mutation during a failed fit. The native model, CLI, selected defaults, state and card-sidecar function remain unchanged.

Checksums establish integrity and retained source correspondence, not provider authenticity against a caller who regenerates an entire input/report/receipt package. Existing independent-review and release requirements remain in force.
