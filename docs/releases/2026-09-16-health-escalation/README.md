# September 16 escalation and unit-binding audit

This revision enforces the issue-register decisions without declaring recovery complete. It preserves the September 3 blocked release, the original material-change dates, historical snapshots and the prior hash-chained triage session.

The two aged release blockers are `RJ-001-PROVENANCE` (official-score verification remains 0/126) and `RJ-006-NFL-MODEL-RESTORATION` (original EPA lineage remains 1/6). Both have explicit P0 escalation records with owner, dependency, last completed action, dated next action, decision and rationale. The September 22 target is at most two aged obligations; an increase requires explanation. A review or escalation does not reset the age.

The WNBA correction is a control gap: six official-availability units remain, within a five-component pipeline. The job history explicitly rolls teams with the slate, but the retained state has no exact six-entry canonical team/date obligation mapping. The six new child cards are ordinal slots, not asserted team/date identities. Their parent remains counted once in the aging metric. Closure requires individual bindings and evidence; closing a parent cannot conceal incomplete children.

## Implemented checks

- Issues older than 14 days require complete, dated escalation records. Missing or expired escalation evidence makes triage validation fail.
- Read-only reports do not advance consecutive blocked-session counts. Only an actual append evaluates an additional session.
- A third recorded blocked session escalates. Risk expiry and overdue remediation still escalate independently.
- Health reports print `accepted_risks_present`, `accepted_risk_release_override: false`, and `official_release_eligible: false`; failure to load triage reports risk presence as unknown and retains the two false clearance fields.
- WNBA availability closure requires canonical team/date/event identity and a hash-verified official artifact reference. Group checks reject missing unit slots and parent closure over incomplete children.

## Validation and limits

Local full suite: **344 passed, 8 subtests passed**. The 13 standing-health tests cover status/evidence refusal, escalation completeness and expiry, append-only chain integrity, read-only session counting, WNBA closure refusal, archive Git-object verification and evaluation join conflicts. The extra subtests reflect the local pytest plugin; clean CI may report only the 344 tests.

These tests do **not** validate original EPA coefficients, recover owner backups, reconcile the 126 historical final scores, bind six official WNBA reports, prove canonical identity migration complete, establish archive schedule completeness, demonstrate forecast calibration or authorize an official forecast. `binding-audit.json` records the sources actually inspected and their limits. The current register's older CI receipts remain evidence for their named older commits, not for this revision.

Use `python scripts/standing_health_triage.py` for read-only verification. Use `--append-session UNIQUE_ID` only for an actual completed triage session; writer-clock and duplicate-session safeguards apply. `triage-report.json` is the immutable receipt for the escalation session. `register-before-escalation.json` preserves the preceding full register.

Health remains RED on recovery obligations and historical release eligibility. Accepted risks do not override either gate. Action OFF; dose 0.0.
