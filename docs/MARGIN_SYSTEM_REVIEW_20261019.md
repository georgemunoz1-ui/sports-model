# October 19 external-review hardening

Base: draft PR #69 at `1a3bb94ee37e74ad428b2d516ec2d6a39a701067`.
The supplied review names a different source layout (`_shared.require_sigma`,
`emit.py`, `cover.py`, `_record_time_key`). Those functions are absent from this
revision. This correction maps every finding to the real PR contracts and tests
the equivalent failure modes; it does not claim to have patched unavailable code.

| Review finding | Disposition in this implementation |
|---|---|
| 1. Fabricated sigma provenance / no OOF evidence | **Fixed analogous artifact gap.** There is no scalar-sigma adapter. Fitting already required at least 60 same-parent chronological OOT rows. New artifacts retain per-event scope, positive OOT declaration, source hashes and timestamps; consumers recheck evidence, counts, IDs, chronology, residual/scaling state, tuning partitions and model identity even after resealing. Contradictory optional OOF aliases reject. |
| 2. All-push emit/validate inconsistency | **Covered and explicit.** This API emits five unconditional settlement states, not ex-push probabilities. All-push reports round-trip with push=1, full-win=0 and null fair odds. |
| 3. Missing ex-push label accepted | **Equivalent label enforcement added.** Every new ladder requires `UNCONDITIONAL_FULL_WIN_WITH_SEPARATE_SETTLEMENT_STATES`. Re-sealed missing or false `EXCLUDING_PUSHES` labels reject. No conditional probability is mislabeled as unconditional. |
| 4. Numeric seasons sorted lexicographically | **Already avoided; regression added.** Actual timezone-aware timestamps determine fitting, evaluation and blocks. Season fields do not order records. Tests include season labels 9/10 and timestamp years 0009/0010. |
| 5. Non-dict NFL diagnostics crash | **Fixed analogous card bug.** Malformed diagnostics/nested prediction/snapshot and other row structures produce stable coded UNAVAILABLE states; independent valid rows continue. |
| 6. Substring arm selection or missing pool arm | **Exact identity enforced and tested.** League and full structured parent ID select the fit; information set and settlement must match. Missing IDs reject. `database_residuals` free text neither selects nor rejects a pool. |
| 7. Symmetric boosts claimed mean-preserving | **Not present.** No such claim or symmetric boost routine exists here. The public mean is computed from the final PMF, separate from the parent mean input. Lattice weighting and no-tie conditioning may change the mean; no demeaning was introduced. |
| 8. NaN line gives uncoded crash | **Already guarded; regression added.** NaN and infinities reject with `FINITE_NUMBER_REQUIRED` before rounding at pricing, ladder and simulation entry points. |
| 9. Reversed windows, zero variance, min_n=1 | **Guarded and tested.** Per-event parent-fit/forecast/start/result chronology must precede fit time. Single rows cannot meet the 60-row minimum. Zero residual variance uses the existing declared 0.25 standard-deviation floor and yields finite replayable PMFs. |
| 10. Integer empirical CDF/push mismatch | **Already avoided; regression added.** All accepted score/margin support is integer. Push mass and empirical sampling come from the same PMF; fractional raw margins reject rather than silently changing protocols. |
| 11. Finalize without validating | **Fixed equivalent gap.** Fit, lightweight-report and card builders invoke their validators before returning/publishing JSON. Re-sealed semantic tampering is tested. |
| 12. CFB overlapping buckets/fractional week truncation | **Not present in this layer.** There are no week buckets, first-match rules or `int(week)` conversions in shared margin fitting, prediction or evaluation. Chronology is timestamp based; this does not certify unrelated legacy CFB modules. |
| 13. Suggested tests | Added applicable regressions for all-push output, provenance refusal, NaN lines, timestamp ordering, empirical analytic-vs-MC settlement and re-sealed records. `IntegerNormalMargin` is absent; the real Student-t/discrete implementation and retained draws are tested. |

An independent review also found that a re-sealed card could remove or duplicate
results without updating coverage. The validator now rederives seven-league
coverage, checks unique event/model/settlement rows and derives execution status
from source coverage.

## Verification and compatibility

- Focused tests include the new negative probes and existing cross-sport,
  distribution-history and NFL spread regressions. See the committed verification
  JSON for the final count and source hashes.
- All eight retained NHL distributions replayed **800,000 saved draws exactly**.
  Raw draw/file hashes, PMF summaries and settlement probabilities matched.
- Refitting the same **1,312-row NHL training cohort** produced exactly identical
  residual/scaling state, tail parameters, lattice factors and tuning selection.
  New provenance/code fields produce a distinct artifact identity. Two held-out
  events also passed the strengthened prediction path.
- Fitting and prediction mathematics were not changed. Existing historical
  results retain their original code/model identities and are not relabeled as
  results of the new artifact. Old fits require their pinned original code or a
  new fit from the original qualifying cohort; editing old hashes is prohibited.
- The validator checks declared evidence for consistency, not source authenticity.
  Raw PMF import remains explicitly structural and diagnostic, never OOF certification.
- Full repository health remains unresolved in the partial recovered snapshot.
  No promotion, default change, production publication, merge or wagering authority.

Reproduce the software checks from the repository root:

```bash
python3 -m unittest tests.test_margin_system tests.test_margin_challenger \
  tests.test_margin_system_evaluation tests.test_margin_system_card \
  tests.test_margin_review_regressions tests.test_cross_sport_distributions \
  tests.test_distribution_history tests.test_nfl_spread_calibration -q
```

Evidence: `data/research/margin_review_20261019/verification.json`.
