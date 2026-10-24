# MLB postseason production audit — October 6, 2026

## Scope and status

The postseason winner kernel remains `mlb.postseason.v13_empty_base_extras.research.v1`, an unvalidated research challenger from draft PR #51. Main is `43ad83382af067b019a086d45d23569497ca6e08`; PR #51 is open/unmerged at `ff442c08baf92cee2ed7ff1811f923e13599ad13`. This change adds an explicit audited operator; it does not activate itself in existing automation, change the default, alter coefficients, or close official-release gates.

The October 5 opener/bulk and roster incidents exposed a reporting and input-control gap. A probable starter is not a workload plan; a captured lineup is not a numerical lineup adjustment. The frozen kernel draws each starter's innings from the same clipped Normal(5.4,1.3) prior and uses a team-runs-allowed/league blend for relief pitching. These remain limitations, not repaired predictive features.

## Executed October 6 result

Fresh official capture: 2/2 postseason events; 2,446 prior-date finals, including 17 postseason finals, across all 30 teams, through October 5. All four named starters matched the official schedule, event feeds and captured active rosters. Posted batting orders were checked by ID against the corresponding active roster and boxscore. Active-roster membership is not a complete injury or postseason-series eligibility certification.

Latest research freeze: October 6, 2026 at 21:16:31 UTC / 2:16 p.m. Pacific. Each event ran 100,000 paths and exact replay verified every retained array. The two-sided winner probabilities sum to one.

| Event | Start PT | Away winner estimate | Home winner estimate | Context |
|---|---|---:|---:|---|
| LAD at ATL | 3:00 p.m. | LAD 51.203% | ATL 48.797% | Both batting orders posted, numerically unconsumed |
| MIL at SD | 6:30 p.m. | MIL 51.037% | SD 48.963% | MIL batting order missing; SD posted; numerically unconsumed |

Monte Carlo only: no independent analytic probability. Approximate numerical 95% intervals for away wins: LAD 50.893–51.513%; MIL 50.727–51.347%. These measure sampling error, not uncertainty about the model. No supported score, run-line or total forecast. No new market comparison was computed from old prices.

The retained morning estimates were LAD 51.116% and MIL 50.954%. The new estimates differ by +0.087 and +0.083 percentage points. A changed run identity changes the seed; these movements are within sampling error and are not evidence of a lineup/workload adjustment or improved prediction. The 2:13 p.m. audit freeze is separately preserved. A subsequent attempt correctly failed review binding after contract text was normalized to exact repository bytes; it produced no forecasts. A new, time-stamped review bound the exact contract before the 2:16 p.m. run.

## New operator

Use unique absolute output directories:

```bash
python3 scripts/mlb_postseason_workflow.py collect --root CAPTURE_DIR --date YYYY-MM-DD
python3 scripts/mlb_postseason_audited.py collect-context --root CAPTURE_DIR --output CONTEXT_DIR
# Inspect source bytes and write an actual event-specific agent review.
python3 scripts/mlb_postseason_audited.py run --root CAPTURE_DIR --context CONTEXT_DIR --contract research/registrations/mlb_postseason_v1.json --review REVIEW.json --output NEW_OUTPUT_DIR
python3 scripts/mlb_postseason_workflow.py verify --run NEW_OUTPUT_DIR/runs/RUN_ID
```

The review keeps all existing fields and adds `context_report_sha256` plus `event_context[EVENT_ID].pitching_plan` and `.availability_review`. It must follow the latest source retrieval. Text attestation does not establish numerical feature consumption. Context collection obtains dated official active rosters and F/D/L/W pitcher logs; it does not fit or activate those features.

The operator enforces existing source-feature rebuild and code-pin checks, then adds event/feed/start identity, active-starter roster checks, batting-order shape and player membership, explicit D−1 date, finite/non-boolean numerical inputs, source age/hash checks, pitcher-log identity/duplicate/out accounting, and per-event review. A conflict blocks its event while independent events continue. Existing output directories are rejected before writes; use `verify` for replay. Outputs list actual used numerical fields separately from context, bind all loaded local Python source hashes, retain runtime versions, and set `final_ready:false`.

## Validation performed

- 26 tests passed: 15 inherited postseason kernel/workflow tests plus 11 new operator tests. Tests include forged numerical source features, missing review binding, early review, corrupt arrays, post-start refusal, unsupported products, concurrent legacy request idempotency, and new roster/start/lineup/staleness/type/output refusals.
- Twelve current-input sign probes passed, six per event: worse home pitching/run prevention lowers home win probability; worse away pitching/run prevention raises it; stronger offense helps its own side. Each probe used 100,000 common-seed paths and was labeled a mechanical diagnostic.
- Nine of nine original numerical contract pins unchanged. Forty-nine downloaded source/governance files matched their applicable repository Git blobs. This is a selected source snapshot, not a complete repository checkout.
- Both actual latest forecasts and all five retained arrays per event reproduced exactly. Actual draw count, seed, dtype/shape, source/code/input/contract/review hashes and local writer time are retained.
- Full repository health was attempted in a partial snapshot and could not establish canonical health. Missing local datasets/modules are not newly established repository defects. Existing RED obligations remain binding.

## Issue cards

**MLB-OPS-20261006 — input/context distinction.** FIXED: the new explicit operator checks roster/feed identity and exposes missing versus collected-but-unused inputs; current 2/2 execution inspected. NOT ESTABLISHED: automatic use by other entry points or existing automation. REMAINING: integration/merge review and complete injury/series-roster evidence. NEXT EVIDENCE: negative operational fixtures and subsequent cards through this entry point. Tier: source-bound execution and exact local replay.

**MLB-WORKLOAD-20261006 — opener/bulk and short hooks.** FIXED: acquisition and display of recent starts, relief appearances and pitch counts. NOT ESTABLISHED: numerical opener/bulk, postseason hook or current reliever effect. REMAINING: separately identified workload challenger and chronological evaluation. NEXT EVIDENCE: as-of announced roles, projected innings policy, bullpen availability, same-event Brier/log loss and calibration. May's last-five-start mean is 3.40 decimal innings; Pivetta's is 4.40 including his September 30 postseason start. Both still receive the generic prior. Do not infer an announced limit from these averages. Tier: official source audit; numerical feature change NOT RUN.

**MLB-PERSONNEL-20261006 — lineup/injury lag.** FIXED: observed batter IDs reconcile with captured active rosters; posted/missing state is explicit. NOT ESTABLISHED: full injury completeness, platoon/lineup offensive replacement or injury impact. REMAINING: validated player-to-team transform under a separate candidate identity. NEXT EVIDENCE: actual pre-cutoff lineup/availability input manifests, sensitivity and out-of-sample evaluation. Tier: current acquisition, not numerical consumption.

**MLB-INTEGRITY-20261006 — reproducibility and settlement.** FIXED: new output-directory refusal, exact-source verification, retained local writer receipts and replay. Existing postseason empty-base extra-inning winner handling remains intact. NOT ESTABLISHED: canonical prospective registration, external timestamp attestation, score/total/run-line settlement or postseason calibration. REMAINING: durable evidence, integration and forward evaluation. NEXT EVIDENCE: immutable artifact verification and matched-event prospective grading when independently eligible. Tier: exact replay, no accuracy certification.

## Persistent restrictions

The historical V13 NO_PROMOTE verdict remains binding. Tests and Monte Carlo counts are not predictive validation; one correct opener game or a short winning slate does not close a structural input defect. Start-only K-prop TBF rules remain product-specific and are not silently reused to alter winner probabilities. September 14 packet pins and all older forecasts are unchanged. Existing calibration-registry repair on main is not a new grade execution in this audit.

`EXECUTION_STATUS: COMPLETED` (two limited-feature research forecasts). `PREDICTIVE_VALIDATION: UNVALIDATED`. `PUBLICATION_ELIGIBILITY: INELIGIBLE` for official release. `canonical_registration:false`; `prospective_grade_eligible:false`; `official_release_eligible:false`; `WAGERING_AUTHORITY:OFF`; dose `0.0`.
