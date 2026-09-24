# MLB calibration persistence repair — 2026-09-24

Base: main `7f3f0911686e1e7bb87a90fd7928ed554a49b3de`.

The scheduled grading workflow forced yesterday's date even though the registry
contained only September 4. The September 23 run `35898673979`, job `107308930273`,
reported `selected_count: 0`, succeeded, and committed only `updated_at_utc`.
The daily card workflow had no pregame registration writer. Current card output
explicitly requires a separate registration attestation; changing that flag would
not repair the missing evidence.

## Changes

- Scheduled grading selects every pending registered card, so older partial cards
  remain eligible for subsequent result checks. An explicitly requested unregistered
  date fails with `UNREGISTERED_CARD_DATE` and does not change durable state. A
  zero-selection query reports `NO_ELIGIBLE_FORECASTS`, `grade_count=0`, and
  `success=false` without a timestamp commit. An exhausted queue is a process
  no-op; an explicitly unregistered date exits nonzero.
- The default-branch Diagnostic Shadow Card workflow uploads its immutable artifact,
  then invokes a writer that downloads that exact artifact, checks its card hash,
  validates pregame/PIT/probability restrictions and stamps the actual writer clock.
  It persists the unchanged card by content hash and a date-keyed registry entry.
  A different run cannot replace an existing date's canonical card. Rerunning the
  exact writer identity is a read-only lookup, including after first pitch.
- Grading verifies the pinned card, registration and artifact identity before
  reading outcomes. The writer supplies only the previously missing attestation;
  other diagnostic exclusions still reject. Frozen card eligibility fields are
  never rewritten. A `forecast_run_id` supplied to the grader asserts an existing
  registration; it cannot create postgame registration.
- The registry runner validates candidate grades before appending a ledger suffix.
  Existing bytes/order stay unchanged. Corrected scores, identity/hash conflicts,
  invalid finals and invariant failures reject the batch without changing the
  ledger, summary or registry. Raw result snapshots and receipts are retained.
- Local writers share an exclusive lock; both Actions workflows share a concurrency
  group. The ledger append is the recovery point: retries after interrupted summary
  publication reconstruct the derived summary/registry without duplicating grades.
  Git pushes fail normally on concurrent changes outside these workflows.

The standalone accumulator CLI delegates to the same registry transaction. It no
longer permits an unregistered `--card` to bypass registration. Runtime artifact
expiry no longer loses enrolled cards because the exact bytes are committed with
registration. Artifact identity and provider observation time remain recorded.

## Recovered backlog

Only September 4 has preserved registration in this calibration registry.
The canonical run is `33854661221`, immutable artifact `9929690482` (published
2026-09-04 08:41:59Z), and the original registered timestamp is unchanged at
08:55:00Z. GitHub timestamp-anchor run `33856095536` observed original registry
commit `a4b8e422ca09d14eaa84e3e8c0814f6ddf190374` at 08:59:22Z, before the
first forecasted start at 18:10Z. This is an external observation of the registry
commit, not reliance on the commit's author-written date.

The downloaded ZIP matches its published SHA-256. Its original forecast bytes are
retained under `data/grading/mlb/cards/a89d6ce7bb6720f151fe21c3563e0851f939fc114e7c407b8fbeea422f10e70c.json`.
The original registry timestamp and run selection are preserved; hash/receipt
bindings added during recovery do not assert a new historical registration.

All 16 final scores match both retained September 22 official MLB StatsAPI daily
and season snapshots (same provider, not independent providers). Raw daily bytes,
original acquisition receipt, registration anchor and replay checks are retained.
No September 21/22 card was retroactively enrolled, reconstructed or promoted.

| September 4 archived estimator | N | Correct | Brier | Log loss |
|---|---:|---:|---:|---:|
| Fixed-rate analytic probability | 16 | 11 | 0.2181480763 | 0.6272713046 |
| Archived Gamma-Poisson simulation | 16 | 10 | 0.2406064917 | 0.6742390980 |

These are the original card's estimator definitions, not new runs of the current
selected model. The existing summary gate remains
`PIPELINE_VALIDATION_ONLY_UNDER_50`. This is pipeline evidence, not a promotion.

## Verification and operation

- 53 focused tests passed: 16 grading/registration tests plus existing recovery
  governance, model-default and MLB current-path coverage. Includes concurrent
  retries, interrupted publication, pending-to-final append, false-success
  prevention, immutable reruns, and conflicting-result rejection.
- Workflow YAML and every embedded shell script parsed successfully. Executing the
  scheduled request resolver produced a blank filter, selecting all pending cards.
- Independently recomputed all 16 paired probability scores from the frozen card
  and raw results. Recovery appended 16 rows; replay appended zero. Card, ledger,
  registry and summary hashes were identical before/after replay.
- Initial repository health remains RED. It included unrelated historical/release
  failures and local checkout/dependency limitations. This repair does not close
  those obligations or claim global readiness. Remote PR checks remain separate.

Evidence: `docs/releases/2026-09-24-mlb-grading/`.

Normal operation after merge:

```bash
python scripts/grade_mlb_registry.py --output-dir output/mlb_grading
```

Offline exact September 4 replay (read the retained receipt for source provenance):

```bash
python scripts/grade_mlb_registry.py --grade-date 2026-09-04 --include-graded \
  --results-json data/grading/mlb/results/7cc343a80af30845ae84865773383afd9de0887bac61bf1240bc75d9601e247b.json \
  --output-dir output/mlb_grading_replay
```

The daily writer operates only on eligible default-branch pregame card runs.
Locally generated or branch-only diagnostic cards do not silently join this registry.
Model defaults, forecast computations, market overlay, action authority and release
policy files are unchanged. The change is reviewable as a PR; it is not active on
main until merged.

## Final review acceptance addendum

The original remote consolidation run passed **393 tests** and all validation
steps, then failed artifact archival because GitHub's artifact storage quota was
exhausted. No artifacts were deleted and no storage/billing limit was changed.
The final workflow additionally emits the complete deterministic acceptance JSON
in the job log and compares it with the committed local report. Artifact upload
remains an independently visible final step; a quota failure is not relabeled PASS.

`acceptance.json` binds all 16 event IDs to model/version, generation/start times,
probability orientation, output hash and input/state snapshots. All 16 scheduled
September 4 events in the retained daily snapshot appear in the frozen registered
card and recovered ledger; excluded September 4 count is zero for this registry.
It also verifies first ingestion in an isolated test store, two fresh-process
replays against copies of committed registry state, and independent Brier arithmetic.
The first published PR commit `e4ad413145a49a418eb99e055f148ff24effbbb3`
remains an immutable backup. Real forecast and grade bytes are never rewritten.

New grade uniqueness keys explicitly bind event, model/version, cutoff,
creation time, card hash and output hash. Existing recovered v2 IDs are recognized
only through matching card/event/cutoff bindings; their original bytes stay intact.
Additional admission checks require model/version and input/state snapshot identity.
The generator itself still cannot self-certify grading eligibility.

Reports expose `NO_PREGAME_REGISTRATION` for September 21–22 and
`REPLAY_IDEMPOTENT` for duplicate-free retries. Existing durable legacy statuses
remain backward compatible. The acceptance gate does not count missing registration
as a loss, a 0–0 record, or a no-game day.

Merge scope remains registry/governance repair. The standalone model/release health
issues are not resolved by merging this PR. No protected default or authority file
is changed relative to the PR base.
