# Priority-league prospective research registration repair

## Scope and honest status

NFL, CFB, WNBA, NBA and NHL shared diagnostic cards now have a writer-owned,
immutable pregame receipt and a separate, source-bound postgame research ledger.
The original MLB registry and certified calibration cohort are unchanged.

This enables **PROSPECTIVE_RESEARCH_SOURCE_UNVERIFIED**, not certified calibration.
`certified_calibration_eligible` is false on every receipt/grade and certified n
stays zero. PIT_ORDERED is retained verbatim; raw-byte attestation is separately
reported and cannot certify historical source authenticity, fitted-state PIT,
model validity, product approval or wagering authority. No parameters, selected
defaults, historical forecasts, or historical ledger rows are changed.

Only binary home-win estimators actually present in the frozen card are scored.
Analytic and simulation values remain separate. Models/configurations are not
pooled. Tied finals are excluded and prior-result corrections fail closed.
Cover and total products remain explicitly unsupported by this receipt schema.
NBA/NHL initial-research opt-in and all existing adapter scope gates remain intact.

## Entry points and persistence

- Existing `.github/workflows/diagnostic-shadow-card.yml`: uploads the original
  card/draw evidence, verifies downloaded bytes, then registers on default branch.
  Receipt/failure reports and frozen cards/draws are committed before reporting
  success. NHL is accepted as a workflow choice but no default is invented.
- `scripts/canonical_forecasts.py register --card ... --run-id ... --artifact-id ...
  --report ...`: actual writer clock, artifact creation time, source cutoff and
  kickoff must be ordered. No historical timestamp argument is available.
- `scripts/canonical_results.py --registry data/grading/canonical/registry.json
  --output data/grading/canonical/results/RUN-ATTEMPT`: captures exact provider
  bytes and normalized independent results. A provider failure does not stop
  other leagues. Scores alone never establish final status.
- `scripts/canonical_forecasts.py grade --results .../results.json --report ...`:
  rehashes/reparses retained result bytes, verifies receipt/card/draw identities
  and exact kickoff, then append-only writes child scores under a process lock.
- New `canonical-research-grading.yml`: daily 13:45 UTC plus manual dispatch,
  activated only if this draft is merged. It serializes with the existing writer,
  persists source evidence, successes and failures, and fails visibly for any
  blocked provider or rejected grading step. It does not require a new artifact
  upload for the grading report.

Paths: `data/grading/canonical/registry.json`, immutable `cards/` and `draws/`,
append-only `ledger.jsonl`, derived `summary.json`, `attempts/`, and `results/`.
Summary groups bind league, model, configuration, product and estimator.
First pregame event/model receipt wins; refreshes cannot replace it or inflate n.
Idempotent retries preserve bytes. Interrupted summary publication recovers from
existing ledger rows without appending duplicates.

NFL shared adapter now invokes its existing `persist_run` when the shared runner
supplies a draw output directory. This fixes discarded winner draws; it does not
change inference. The dedicated NFL runner remains available. Fresh source/NFL
bridge instructions are in FRESH_SOURCE_RETENTION.md.

## Verification and remaining operational steps

Focused tests include correct provider namespaces for all five leagues, retained
provider-byte registration-to-grade replay, draw corruption, source corruption,
source-unverified cohort separation, pregame deadline refusal, changed kickoff,
partial results, independent models, append-before-summary interruption, concurrent
retries, existing MLB grading, and existing NFL context behavior.
These are software fixtures, not live forecasts or predictive evidence.

An actual attempt of the current registered NFL CLI for 2026-10-09, with the exact
configured main event package restored, fails `NFL_DATE_NOT_CAPTURED:2026-10-09`.
That is a genuine remaining source/package blocker, not a verified no-game slate.
No past card was backdated or newly admitted to a prospective cohort.

Before claiming operational resolution: review/merge the patch, prepare fresh
source-bound packages and current eligible state through existing frozen builders,
select an actually supported future event, generate/upload/register it before its
start, inspect its durable receipt, then acquire verified finals and inspect its
first append-only grade and exact replay. Old packages are not made fresh by changing
timestamps. Automatic refits, new defaults, market/live forecasts and deployment
remain outside this repair. A green fixture suite is not this live acceptance.

Executed local validation: `python -m pytest tests research/tests -q` passed
525 tests and 114 subtests in 40.26 seconds on the assembled current-main source
snapshot plus this patch. The initial aggregate run caught a leaked draw-output
environment interaction; persistence now requires an explicit shared-card context
opt-in, and the entire suite was rerun after that correction. Four >1 MiB archived
compressed historical distribution files could not be retrieved via the available
connector; they are not required by this unit/research suite. This is not a claim
that the separate archived historical-replay verifier ran.
