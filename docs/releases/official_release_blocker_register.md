# Standing-health triage — 2026-09-16

Scope: the three standing health failures and all nine recovery records. This is a decision/evidence ledger, not a forecast or promotion. Action OFF; dose 0.0.

**Corrections verified locally:** four jobs were reported overdue, not five. One was false: RJ-003 had already closed because its trigger did not fire. After the reporter repair, three jobs are overdue and four remain nonterminal; RJ-005 is due later on September 16. RJ-001 acquisition is 123/123 but its separate score-verification phase remains 0/126.

The archive is the MLB pitch-data source at `harness/ingest_lancebroz.py`, window July 1 through August 31 inclusive. It is not the collection of every model coefficient or forecast artifact. The September 3 release has a blocked eligibility decision; verified hashes do not make that decision eligible.

## Decisions

| Issue | Decision | Owner | Next physical action | Due/review |
|---|---|---|---|---|
| REL-ARCHIVE-001 | FIX-IN-PROGRESS | data-platform maintainer (Codex) | Restore pinned upstream snapshot in clean CI; verify each Git blob and SHA-256; retain raw objects; separately reconcile August 31 and scheduled-game coverage. | 2026-09-17T04:26:41.997358+00:00 |
| REL-RECOVERY-001 | FIX-IN-PROGRESS | repository maintainer (Codex) | Run negative regressions and remote health; retain child blockers and phase counts. | 2026-09-17T04:26:41.997358+00:00 |
| REL-HISTORICAL-001 | ACCEPTED-RISK | release maintainer (Codex) | Keep September 3 evidence immutable; define a separate current-profile check and prove dependencies before replacing any current-health coupling. | 2026-09-17T04:26:41.997358+00:00 |
| RJ-001-PROVENANCE | ACCEPTED-RISK | acquisition maintainer (Codex) | Inventory the 126 score-verification IDs against current Tier-1 bindings and retain a missing-ID manifest before acquiring finals. | 2026-09-17T04:26:41.997358+00:00 |
| RJ-002-OOF-REPLAY | RESOLVED | modelling maintainer (Codex) | Retain replay limitation: per-game uncertainty consumption needs separate registration. | 2026-09-17T04:26:41.997358+00:00 |
| RJ-003-FALLBACK-ARM | DESCOPED | modelling maintainer (Codex) | Retain closed conditional job; do not execute a fallback or substitute it for the selected default. | 2026-09-17T04:26:41.997358+00:00 |
| RJ-004-WNBA-INJURY | DESCOPED | wnba_features maintainer (Codex) | Carry the remaining availability obligation in RJ-005. | 2026-09-17T04:26:41.997358+00:00 |
| RJ-005-WNBA-FEATURE-PIPELINE | BLOCKED | wnba_features maintainer (Codex) | Identify an official archived report for the exact missing team/date units; hash it or record unavailable historical inputs; build a separately dated future context packet. | 2026-09-17T04:26:41.997358+00:00 |
| RJ-006-NFL-MODEL-RESTORATION | BLOCKED | model_registry maintainer (Codex) | Locate original data/nfl/model/runs/2026-08-10_nflverse_2015_2025_oof_v2 and invalidation record in owner backup; verify exact source pins before assigning units. | 2026-09-17T04:26:41.997358+00:00 |
| RJ-007-DATELESS-JOIN-REMEDIATION | FIX-IN-PROGRESS | harness maintainer (Codex) | Test duplicate/date/outcome refusal; enumerate canonical IDs for historical migration sidecars without changing frozen boards. | 2026-09-17T04:26:41.997358+00:00 |
| RJ-008-NFL-LAUNCH-SHADOW | RESOLVED | nfl_launch maintainer (Codex) | Preserve registration; use selected QB identity for new eligible research packages. | 2026-09-17T04:26:41.997358+00:00 |
| RJ-009-CFB-LAUNCH-SHADOW | RESOLVED | cfb_launch maintainer (Codex) | Preserve registration and the CFB CONTROL-MISSING label for current-season assimilation. | 2026-09-17T04:26:41.997358+00:00 |

## Aging and escalation

Baseline: **2 unresolved leaf issues** have gone more than 14 days without a material change. Previous-session count is **unknown**, not zero. No declining trend can yet be claimed. A review, deadline extension or status rename does not reset this clock. Aggregate recovery row is excluded to avoid double counting.

Third consecutive BLOCKED session becomes OVERDUE-ESCALATED. An expired ACCEPTED-RISK decision or missed FIX-IN-PROGRESS due date also escalates. Escalation requests an explicit decision; it never automatically accepts risk or removes a mandatory dependency. Accepted risk here means a dated decision to retain RED/no official forecasts while work is deferred, not approval of unsupported forecasts.

## Reproduce (five commands)

Use the exact commit named in the PR/CI record. Replace COMMIT with that SHA; private repository read access is required.

```bash
git clone https://github.com/georgemunoz1-ui/sports-model.git && cd sports-model
git checkout COMMIT
python3 -m pip install -r requirements-consolidated.txt
python3 -m pytest tests -q
python3 scripts/standing_health_triage.py
```

Expected on the initial repair: 342 tests pass (plus 8 subtests); triage validation_errors is empty, official_release_eligible is false. Future due-date escalation is expected and is not a failed reproduction. Binary archive recovery is separately executed by `.github/workflows/standing-health-triage.yml`; it records source commit, Git blob identity, SHA-256, required parser columns and exact environment. Software tests do not prove original historical availability or game coverage.

## Evidence boundaries

- Local verification is operator-reported until a clean remote run is linked. A CI artifact is available to authorized repository readers; it is not an anonymous public verification endpoint.
- Existing RJ-002/008/009 closures are limited to their archived metadata/registration scopes. The original records are evidence, not new prospective validation.
- No working official_pregame_v1 dependency graph was found. The dependency assessment is provisional and removes no mandatory health check.
- Current forecasts, P3 assimilation, CFB assimilation control and unresolved action rules remain separate.
- No historical forecast, packet pin, model coefficient or registration timestamp has been changed.

## Issue cards

### REL-ARCHIVE-001

The MLB ingestion source directory is absent locally; the old check accepted any one parquet and a 40-character SHA.

**Why unresolved / closure scope:** Archive is outside this repository and its checkout was not restored in this runtime. A reachable upstream candidate does not prove original historical source identity.

**First retained entry:** not established. **Last historical touch:** 2026-09-16T04:26:41.997358+00:00. **Last material change:** 2026-09-16T04:26:41.997358+00:00.

**Done definition:** Pinned binary window recovered and all object hashes verify; Required schedule coverage and historical claim scope documented; Production runtime configured to the verified mount and source_health passes

**Evidence:** `harness/ingest_lancebroz.py` (SHA-256 f2e43cf64c597adc30909d1ac11ff3b6644c7a0600a4e85a3e914618b0a8d616), `docs/releases/2026-09-16-health-triage/archive-candidate.json` (SHA-256 36f7b43d254a0407358a9036ad7761680ec7264d72d5d93985f79682e5d0757f)

**Residual limitation:** Official release eligibility, historical registration or forecasting superiority. Mandatory health and current-event gates remain.

### REL-RECOVERY-001

Recovery reporter misclassified CLOSED_CONDITION_NOT_FIRED as overdue and hid incomplete RJ-001 phases behind 123/123.

**Why unresolved / closure scope:** Reporter and job schema diverged; factual repair was not previously made. Other child jobs still require actual recovery.

**First retained entry:** not established. **Last historical touch:** 2026-09-16T04:26:41.997358+00:00. **Last material change:** 2026-09-16T04:26:41.997358+00:00.

**Done definition:** Closed RJ-003 not overdue; Incomplete score phase remains visible; All child issues have decisions and no unresolved work is silently removed

**Evidence:** `harness/recovery_jobs.py` (SHA-256 2282e960f8afdfcdd0ae6b6d1132b55a5db9b8cacf7f7ad606e34138abacce36), `data/registry/recovery_jobs.json` (SHA-256 41e169d346c5f76314c762de4d61e14cb60048578f6ab09067a5b123106e14a1)

**Residual limitation:** Official release eligibility, historical registration or forecasting superiority. Mandatory health and current-event gates remain.

### REL-HISTORICAL-001

Health invokes the September 3 release decision; its artifact and contract verify, but the original decision is BLOCKED.

**Why unresolved / closure scope:** Its past inputs/registration cannot be supplied prospectively now; green historical eligibility would misrepresent chronology. Keeping this gate RED is deliberate while a new prospective profile is specified.

**First retained entry:** not established. **Last historical touch:** 2026-09-03T18:40:16Z. **Last material change:** 2026-09-03T18:40:16Z.

**Done definition:** Original September 3 record continues to verify without altered bytes; New event-specific profile has registration, inputs and publication before cutoff; Any historical/current-health separation is versioned and tested

**Evidence:** `harness/release_gate.py` (SHA-256 660d41d46ac80897a4b0a0b80d9ce564a4e0faf9e0b465459a5bf9642ba2fd2a), `harness/healthcheck.py` (SHA-256 3cd6747f38eb661f2f037133d85c3439926540ef2d7189948fd2076f2b83a7a6), `data/acquisition/2026-09-03_update.json` (SHA-256 15a06fa465ee6882cbffd0896a7378d763e8f8e23677543e2ec36f6d9d6ff7de), `data/releases/2026-09-03_release.json` (SHA-256 d1f8ff727bb8eb3744a06240ca11de3692860a5ab47f46c74413f7c20e201414)

**Residual limitation:** Official release eligibility, historical registration or forecasting superiority. Mandatory health and current-event gates remain.

### RJ-001-PROVENANCE

Provenance phase is 123/123, but the distinct official-score verification phase remains 0/126.

**Why unresolved / closure scope:** Score-bearing source bindings were not completed; pitch events without final scores cannot substitute.

**First retained entry:** 2026-08-25T02:45:00Z. **Last historical touch:** 2026-08-28T07:54:53Z. **Last material change:** 2026-08-26T19:15:00Z.

**Done definition:** Declared component evidence retained with hashes; Component regression/closure checks pass; no merely renamed progress

**Evidence:** `data/registry/recovery_jobs.json` (SHA-256 41e169d346c5f76314c762de4d61e14cb60048578f6ab09067a5b123106e14a1), `harness/recovery_jobs.py` (SHA-256 2282e960f8afdfcdd0ae6b6d1132b55a5db9b8cacf7f7ad606e34138abacce36)

**Residual limitation:** Official release eligibility, historical registration or forecasting superiority. Mandatory health and current-event gates remain.

### RJ-002-OOF-REPLAY

Existing August 27 completed replay record lacked its required terminal disposition.

**Why unresolved / closure scope:** Metadata omission corrected now; no new model replay or per-game uncertainty approval claimed.

**First retained entry:** 2026-08-25T23:06:00Z. **Last historical touch:** 2026-08-27T06:50:00Z. **Last material change:** 2026-08-27T06:50:00Z.

**Done definition:** Declared component evidence retained with hashes; Component regression/closure checks pass; no merely renamed progress

**Evidence:** `data/registry/recovery_jobs.json` (SHA-256 41e169d346c5f76314c762de4d61e14cb60048578f6ab09067a5b123106e14a1), `harness/recovery_jobs.py` (SHA-256 2282e960f8afdfcdd0ae6b6d1132b55a5db9b8cacf7f7ad606e34138abacce36), `data/audit/2026-08-27_rj002_oof_replay.json` (SHA-256 175dde62b56d74dca298d3c567f4b7965bd6d4946528a9bf09caa0d7f4087509)

**Residual limitation:** Official release eligibility, historical registration or forecasting superiority. Mandatory health and current-event gates remain.

### RJ-003-FALLBACK-ARM

The conditional fallback job closed August 27 because its reconstruction-failure trigger did not occur.

**Why unresolved / closure scope:** False overdue status came from missing terminal enum support.

**First retained entry:** 2026-08-25T23:06:00Z. **Last historical touch:** 2026-08-27T06:53:30Z. **Last material change:** 2026-08-27T06:53:30Z.

**Done definition:** Declared component evidence retained with hashes; Component regression/closure checks pass; no merely renamed progress

**Evidence:** `data/registry/recovery_jobs.json` (SHA-256 41e169d346c5f76314c762de4d61e14cb60048578f6ab09067a5b123106e14a1), `harness/recovery_jobs.py` (SHA-256 2282e960f8afdfcdd0ae6b6d1132b55a5db9b8cacf7f7ad606e34138abacce36), `data/audit/2026-08-27_rj002_oof_replay.json` (SHA-256 175dde62b56d74dca298d3c567f4b7965bd6d4946528a9bf09caa0d7f4087509)

**Residual limitation:** Official release eligibility, historical registration or forecasting superiority. Mandatory health and current-event gates remain.

### RJ-004-WNBA-INJURY

Old six-team injury task was already superseded by RJ-005; its missing reports were not recovered.

**Why unresolved / closure scope:** Original supersession is recorded, not a claim of successful injury recovery.

**First retained entry:** 2026-08-25T18:00:46Z. **Last historical touch:** 2026-08-25T22:20:00Z. **Last material change:** 2026-08-25T22:20:00Z.

**Done definition:** Declared component evidence retained with hashes; Component regression/closure checks pass; no merely renamed progress

**Evidence:** `data/registry/recovery_jobs.json` (SHA-256 41e169d346c5f76314c762de4d61e14cb60048578f6ab09067a5b123106e14a1), `harness/recovery_jobs.py` (SHA-256 2282e960f8afdfcdd0ae6b6d1132b55a5db9b8cacf7f7ad606e34138abacce36)

**Residual limitation:** Official release eligibility, historical registration or forecasting superiority. Mandatory health and current-event gates remain.

### RJ-005-WNBA-FEATURE-PIPELINE

The historical feature job retains 11/17 units with six official availability sections unbound.

**Why unresolved / closure scope:** Current code cannot supply missing historical report bytes or their pregame retrieval proof. Current WNBA data is a separate fresh-packet task.

**First retained entry:** 2026-08-25T22:20:00Z. **Last historical touch:** 2026-09-03T19:21:08Z. **Last material change:** 2026-09-03T19:21:08Z.

**Done definition:** Declared component evidence retained with hashes; Component regression/closure checks pass; no merely renamed progress

**Evidence:** `data/registry/recovery_jobs.json` (SHA-256 41e169d346c5f76314c762de4d61e14cb60048578f6ab09067a5b123106e14a1), `harness/recovery_jobs.py` (SHA-256 2282e960f8afdfcdd0ae6b6d1132b55a5db9b8cacf7f7ad606e34138abacce36)

**Residual limitation:** Official release eligibility, historical registration or forecasting superiority. Mandatory health and current-event gates remain.

### RJ-006-NFL-MODEL-RESTORATION

Original EPA v0.2 immutable run directory and remaining lineage components are absent; job remains 1/6.

**Why unresolved / closure scope:** Three recovered metadata files do not contain the original full run; the selected QB successor is a different model identity.

**First retained entry:** 2026-08-27T08:43:15Z. **Last historical touch:** 2026-08-28T07:54:53Z. **Last material change:** 2026-08-27T08:43:15Z.

**Done definition:** Declared component evidence retained with hashes; Component regression/closure checks pass; no merely renamed progress

**Evidence:** `data/registry/recovery_jobs.json` (SHA-256 41e169d346c5f76314c762de4d61e14cb60048578f6ab09067a5b123106e14a1), `harness/recovery_jobs.py` (SHA-256 2282e960f8afdfcdd0ae6b6d1132b55a5db9b8cacf7f7ad606e34138abacce36)

**Residual limitation:** Official release eligibility, historical registration or forecasting superiority. Mandatory health and current-event gates remain.

### RJ-007-DATELESS-JOIN-REMEDIATION

Evaluation dictionaries silently collapsed duplicate game IDs and allowed cross-date/outcome pairing; historical identity migration remains incomplete.

**Why unresolved / closure scope:** Two live comparison guards repaired; legacy build/grade commands and synthetic historical identities need a separate immutable migration.

**First retained entry:** 2026-08-28T07:17:53Z. **Last historical touch:** 2026-08-28T07:50:02Z. **Last material change:** 2026-09-16T04:26:41.997358+00:00.

**Done definition:** Declared component evidence retained with hashes; Component regression/closure checks pass; no merely renamed progress

**Evidence:** `data/registry/recovery_jobs.json` (SHA-256 41e169d346c5f76314c762de4d61e14cb60048578f6ab09067a5b123106e14a1), `harness/recovery_jobs.py` (SHA-256 2282e960f8afdfcdd0ae6b6d1132b55a5db9b8cacf7f7ad606e34138abacce36), `harness/evaluation_standard.py` (SHA-256 c60647d3f490485435153e1bcbbf9cea54aeeb10e41f103ca89c4f71af32b65d), `harness/promotion_gate.py` (SHA-256 6e419fed61d9e51e4a35de9998641d279a19f64d7d4be52f3d1e8eb58c5d6036)

**Residual limitation:** Official release eligibility, historical registration or forecasting superiority. Mandatory health and current-event gates remain.

### RJ-008-NFL-LAUNCH-SHADOW

Separate NFL launch-shadow registration job was already COMPLETE 4/4; it never closed original EPA recovery.

**Why unresolved / closure scope:** No remaining work in this narrow registration job; model/current-release gates remain separate.

**First retained entry:** 2026-09-03T19:21:08Z. **Last historical touch:** 2026-09-03T19:21:08Z. **Last material change:** 2026-09-03T19:21:08Z.

**Done definition:** Declared component evidence retained with hashes; Component regression/closure checks pass; no merely renamed progress

**Evidence:** `data/registry/recovery_jobs.json` (SHA-256 41e169d346c5f76314c762de4d61e14cb60048578f6ab09067a5b123106e14a1), `harness/recovery_jobs.py` (SHA-256 2282e960f8afdfcdd0ae6b6d1132b55a5db9b8cacf7f7ad606e34138abacce36)

**Residual limitation:** Official release eligibility, historical registration or forecasting superiority. Mandatory health and current-event gates remain.

### RJ-009-CFB-LAUNCH-SHADOW

CFB launch-shadow registration job was already COMPLETE 4/4; current-season assimilation is not established by that closure.

**Why unresolved / closure scope:** No remaining work in this narrow registration job; assimilation control remains missing.

**First retained entry:** 2026-09-03T19:21:08Z. **Last historical touch:** 2026-09-03T19:21:08Z. **Last material change:** 2026-09-03T19:21:08Z.

**Done definition:** Declared component evidence retained with hashes; Component regression/closure checks pass; no merely renamed progress

**Evidence:** `data/registry/recovery_jobs.json` (SHA-256 41e169d346c5f76314c762de4d61e14cb60048578f6ab09067a5b123106e14a1), `harness/recovery_jobs.py` (SHA-256 2282e960f8afdfcdd0ae6b6d1132b55a5db9b8cacf7f7ad606e34138abacce36)

**Residual limitation:** Official release eligibility, historical registration or forecasting superiority. Mandatory health and current-event gates remain.

