# PR #45 standing-health repair

This is a workflow evidence repair, not model validation or release clearance.
The nine aged unresolved obligation leaves remain open. No deadline, material-change
clock, issue-card hash, triage-session count, model selection, fitted parameter,
forecast, or historical release record is changed.

## Inspected evidence

- PR head: `835003dc872991d44679fcdb923b77cfbb9043c2`; base:
  `7f3f0911686e1e7bb87a90fd7928ed554a49b3de`.
- [Failed triage run 35916497206](https://github.com/georgemunoz1-ui/sports-model/actions/runs/35916497206),
  merge checkout `c92b5a02591947799b969b286ede41768e6c87a8`.
- Downloaded artifact `10775840016`, verified ZIP SHA-256:
  `8367e0b6b4147542b364e6d8c2aff343289bb4813895780aff72bd1bc1b2bea0`.
- All 390 tests passed. The recovery refusal tests completed; triage returned 1.
  Bash stopped before environment capture, archive checkout and archive verification.
- The retained health log reports **4 failures / 7 warnings**, not the PR body's
  older 4/8 count. Consolidation and durability succeeded independently.
- `triage.json` has ten validation errors: two expired escalation reviews and
  eight missing aged-escalation records (including the WNBA grouping parent).
  The trend correctly counts nine leaves, excluding that parent.

## Minimal repair

Split regressions, recovery refusals, triage capture, environment capture and archive
recovery into independent steps. Capture the real triage/health exit codes. Attempt
the existing pinned archive checkout even when earlier checks fail; verify it before
health evaluation. Upload the evidence before a final strict gate examines every
step outcome and both exit codes. Missing evidence, skipped work, cancellation and
nonzero results fail. There is no `continue-on-error` or tolerated failure allowlist.

The archive remains the explicit recovery candidate at
`d49271818de98ee3b582dce134bb724861dda859`. Recovering it can repair availability in
this CI environment; it cannot establish historical retrieval, complete schedule
coverage, August 31 coverage, or deployment to another runtime.

Regression tests execute the actual workflow shell blocks with synthetic process
results, including failure, cancellation, missing receipts and successful completion.
These fixtures do not exercise or validate a sports model. The appended canonical
journal records the current handoff without rewriting older entries.

## Remaining conditions for defensible green readiness

| Failure or obligation | Required closure evidence | Boundary |
|---|---|---|
| Archive availability | Successful pinned checkout, all Git-object hashes and parser checks, configured runtime mount | Candidate availability alone does not close REL-ARCHIVE-001's historical/schedule conditions |
| Recovery jobs | Complete and independently verify the actual units for RJ-001, RJ-005, RJ-006 and RJ-007; preserve job histories | Deadlines and counts cannot be reset to obtain green |
| RJ-001 score phase | Canonical 126-event inventory and retained authoritative final-score bindings for every required row | 123/123 acquisition is distinct from 0/126 score verification |
| RJ-005 six availability leaves | Source-bound historical team/date/event mapping, then corresponding official report bytes for each unit | Ordinal slots cannot be assigned teams by inference or closed through their parent |
| RJ-006 original lineage | Owner-held `data/nfl/model/runs/2026-08-10_nflverse_2015_2025_oof_v2` and invalidation artifact, with original source pins | Selected QB successor is not proof of original EPA lineage; progress remains 1/6 |
| RJ-007 historical joins | Canonical date/event migration evidence and duplicate/date/outcome refusal checks | Passing current refusal tests alone does not migrate historical records |
| September 3 release | Preserve original BLOCKED decision; separately specify and verify an event-specific prospective profile and its dependency graph before any current-health separation | No retroactive registration, historical recoloring, or exemption based only on age |
| Triage governance | Genuine dated escalation actions and decisions for REL-HISTORICAL-001, RJ-001, RJ-005 parent and all six leaves, and RJ-006 | A review or renamed status does not reset material age or waive any gate |

The two existing escalation decisions expired on September 17. Updating their dates
without completing an action or obtaining the required owner decision would not
resolve the underlying dependency. An audit is not an owner decision.

The seven warnings in the inspected run concern: legacy results freshness (last
final September 2), one non-Tier-1 adjacent-day duplicate score, two daily pregame
input gaps, 18 missing interior lineage days, work since the canonical journal entry,
and the root redirect's checkout mtime. The handoff update addresses the journal
content gap. Historical data and current event inputs require their own source-bound
repairs; changing dates or copying current results into old forecasts is not closure.
The separate runtime report also says all seven current snapshots are stale.

## Verification and authority

Reproduce with the repository's `requirements-consolidated.txt` environment:

```bash
python -m pytest tests/test_standing_health_workflow.py tests/test_standing_health_triage.py -q
python -m pytest tests -q
python scripts/standing_health_triage.py
python harness/healthcheck.py
```

The last two commands must remain nonzero while their existing mandatory conditions
are unsatisfied. Full health also requires the configured archive and Git history.
Health writes three generated `data/audit` reports; their dirty status is retained
as evidence, not committed as a repair to historical source data.

Official release remains ineligible. Accepted-risk release override remains false.
Action authority stays OFF and dose stays 0.0. Software acceptance, evidence
collection, predictive validation, current-event readiness and release eligibility
must be reported separately.
