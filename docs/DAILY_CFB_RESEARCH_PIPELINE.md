# Selected CFB daily research execution

This is a narrow operating pilot for the existing selected
`cfb.fbs.elo_form_logit_ridge.v1_0.shadow` model, FBS versus FBS in week 2 or later.
It does not change selected defaults, selected formulas or frozen coefficient artifacts, qualification
gates, old forecasts, market independence, or authority. Official release and
wagering remain OFF. A branch workflow is not an active scheduled service.

## Execution and state location

`scripts/run_daily_research.py --next-slate --output NEW_DIRECTORY` discovers the
next eligible slate within six days, retrieves the pinned historical files and
current cfbfastR season schedule, and reconciles exact event IDs, teams and starts
with adjacent-date ESPN FBS scoreboards. Missing classification, conflicting
starts, unverified event status, incomplete prior-week results, and malformed
source bytes fail explicitly. Raw bytes and failure receipts are retained.

The existing `prepare_cfb_current.py` reproduces the frozen historical features,
assimilates earlier eligible finals, and freezes the selected weekly package.
The existing shared-card command emits its original probabilities and 100,000
winner draws per event. The full slate receipt distinguishes forecasted,
post-start and unsupported events. Cover and total availability are stated
separately; the selected parent does not gain a new score law from this workflow.

The pregame workflow uploads the entire source/package/card tree, downloads that
new artifact into a separate directory, checks the manifest and every byte, and
then calls the existing canonical writer with the real Actions artifact ID.
The writer independently checks the uploaded card, draws, optional selector
sidecar, source chronology and actual pre-kickoff registration time. It never
retrospectively creates a receipt or substitutes caller-supplied artifact metadata.

Pilot state lives on **`research/daily-cfb-archive-v1`**:

| Path on evidence branch | Purpose |
| --- | --- |
| `runs/pregame-RUN-ATTEMPT-REPETITION/` | Immutable complete captures, packages, cards and stage receipts |
| `runs/postgame-RUN-ATTEMPT/` | Immutable result acquisition and grading attempts |
| `registry/` | Canonical-writer receipts, retained forecasts/draws and append-only grades |

Both pilot workflows restore this branch into a fresh checkout and copy its
`registry/` to their working canonical root. They serialize under the same
concurrency group. The archive writer refuses existing run paths, changed old
forecast records, deleted files and modified ledger prefixes; it never force
pushes. After a push, a fresh remote clone must match the exact commit and bytes.
Git gives versioned remote retention with no Actions expiry, **not WORM storage**
or independently signed source provenance.

The legacy workflow `canonical-research-grading.yml` still reads
`main:data/grading/canonical/`. This change neither populates that separate legacy
registry nor redirects its schedule. A future integration must select one
canonical state location and avoid competing writers before claiming a unified
service. Do not copy or retro-register older diagnostic cards into either store.

## Separate postgame and notifications

`daily-cfb-research-postgame.yml` uses authenticated repository access to restore
the original pilot registry, retrieves live results from the existing approved
HTTPS provider routes, verifies exact events/final statuses/source hashes, and
grades original probabilities through the canonical grader. An empty registry or
not-yet-due event is a waiting state, never completed settlement. Missing overdue
finals, conflicts, source failures, and changed evidence remain failures.

Acquisition, forecast coverage, registration, upload/readback, grading and remote
retention failures create a GitHub issue and read it back. This demonstrates
issue delivery only, not email, push notification or human receipt. The separate
failure drill is explicitly labeled TEST_ONLY and modifies no forecast.

The pinned Python version, dependency lock, exact action commits, actual package
versions, selected-source snapshots and code hashes accompany the execution.
Local tests use synthetic engineering fixtures and a local bare Git remote; they
cannot establish a real prospective event or remote provider authenticity.

## Deployment and acceptance

The scoped integration-branch push performs two independent acquisitions and
executions; if they cover the same events, the canonical writer retains the first
receipt and the event sample does not double. Postgame and failure-drill acceptance
are explicitly triggered by request files in their declared branch paths.

Cron declarations become scheduled execution only after reviewed default-branch
deployment. Before declaring the operating loop established, inspect two forward
runs, complete Actions readbacks, durable remote bytes, a delivered injected
failure, an independently reviewed receipt, and authentic postgame settlement.
Current captures remain `PROSPECTIVE_RESEARCH_SOURCE_UNVERIFIED` under the existing
writer; model validation, provider authenticity and historical parent-model
provenance are separate unresolved evidence questions.
