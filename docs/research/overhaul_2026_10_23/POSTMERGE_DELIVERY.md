# Post-merge delivery reconciliation — PR76

PR75 and PR76 are merged. PR76 merge `74c22df865706ba8ec17442c95c7c521ca34f915` has exactly the verified tree `f2452a8687cdf5f449eb6250fb05ec8221351c35`. No model weights, default catalog, historical forecast, prior grading ledger or wagering authorization was replaced by the merge.

## Actual main-branch executions

| Workstream | Actual result | Evidence |
|---|---|---|
| Full software acceptance | 1,101 tests passed on main; configured workflow completed successfully | [Consolidation 39913254193](https://github.com/georgemunoz1-ui/sports-model/actions/runs/39913254193) |
| Forecast/selection integration | 550 focused tests and actual retained-input NFL 100,000-draw replay passed; automatic selection sidecar was BLOCKED with null selected probability | [Integrity 39913254198](https://github.com/georgemunoz1-ui/sports-model/actions/runs/39913254198) |
| MLB workflow | 32 regressions passed; real health scan executed; archive step reported BLOCKED_UNCONFIGURED | [MLB 39913254203](https://github.com/georgemunoz1-ui/sports-model/actions/runs/39913254203) |
| Storage inventory | Read all three pages: 232 visible/live artifacts, 4,843,415,167 bytes. No deletion or notification | [Inventory 39913254248](https://github.com/georgemunoz1-ui/sports-model/actions/runs/39913254248) |
| Canonical grading | Executed and exposed missing first-registration state; no settlement occurred | [Initial grading 39913254135](https://github.com/georgemunoz1-ui/sports-model/actions/runs/39913254135) |

`POSTMERGE_RECEIPTS.json` hashes the merge receipt, five hosted-run receipts and five decoded job transcripts. These are retrieved UTF-8 transcripts, not original lost artifact binaries. The 61-case blinded review remains bound to its unchanged Python snapshot. The local NFL execution manifest remains immutable; its earlier context-only canonical workflow is separately retained at its original hash because workflow launch configuration changed afterward.

## Delivery disposition

| Capability | Honest completion state | Remaining requirement / owner / next executable action |
|---|---|---|
| New numeric forecast path and automatic selection sidecars | Merged, enabled, exercised, verified for the tested actual retained-input NFL path; all seven selected adapters covered by software perturbation checks | Model/data owners: fresh authentic sport-specific inputs and qualifying scientific evidence. No claim all seven live leagues were forecast successfully tonight. |
| Signed lineage, evaluation, settlement invariants and rest oracles | Merged and exercised in hosted regression/CLI tests | Evaluation authority: real trusted signers, frozen protocols and chronological candidates; NHL owner: horizon contract, source census, refit/evaluation. Test keys and raw feature builds do not qualify models. |
| Main storage inventory | Merged, enabled, exercised; counts and source hash recorded | Release engineering: persist full inventory through the configured archive. Account billing/free capacity is not measured by these repository totals. |
| Drive archive and GitHub retention | Code merged and archive preflight exercised; durable upload BLOCKED_UNCONFIGURED. Seven-day retention is in three actual upload configurations, but no new artifact expiration was observed | Repository owner/release engineering: approve destination and provide pinned uploader/auth configuration, run verified upload/readback, then verify optional GitHub artifact expiration. |
| Threshold notification | Persistent transition logic tested; notification and scheduled trigger disabled | Owner must declare metric/threshold, destination, initial-below rule, persistent adapter and schedule. Only then authorize and verify a delivered test notification. |
| Failed report recovery | Decoded original failed-run transcript recovered; original report artifact remains unrecovered (zero retained artifacts on the failed run) | Release engineering: preserve verified recovery bundle before any deletion proposal; any regenerated report must be separately labeled. |
| Canonical first-registration path | Scheduled/main workflow enabled; initial grading was not successful | Grading owner: explicit bootstrap preflight follow-up. First real pregame registration remains blocked by required verified GitHub artifact delivery and fresh-input prerequisites. Do not create a dummy registry or retroregister discovery cards. |
| Predictive improvement | Not promoted or established | Per-sport/evaluation owners: execute the 20-item capability register. Rest refits, player/goalie/minutes models, distribution repairs, uncertainty and target-specific calibration remain explicit work. |

The canonical writer's artifact upload is a required external receipt: it verifies uploaded card/draw/sidecar bytes before writing the registry and durable Git copies. It cannot simply be made optional. Restoring capacity through approved verified archival/cleanup, or separately designing an equivalent witnessed storage authority, is the prerequisite for the first genuine pregame registration.

Actual hosted health remains **RED: four failures and six warnings**. The failures are the unavailable/unversioned production pitcher archive, overdue owned recovery jobs, blocked historical release eligibility, and standing-health evidence/hash-chain obligations. Passing software or explicit unconfigured-archive handling does not close them. Wagering remains OFF.

Manual upload of the prepared 42-file recovery bundle was automatically rejected because the discovered Drive folder was not explicitly authorized in user-authored text. No upload was retried through another destination. The concrete pending action is the 225,453-byte bundle, SHA256 `2588f746b58b3f182621c9065f3faf73f324c6ebff39125c70ead19bd109e74a`, to [Sports Model Archives](https://drive.google.com/drive/folders/1zQnJYCktPvBHOYL805ozk_yfUD17Lguj).

## Separate bootstrap repair checkpoint

The follow-up adds only an operational preflight and workflow gates; frozen forecasting/selection Python remains unchanged. A clean missing-registry state emits AWAITING_FIRST_PROSPECTIVE_REGISTRATION with settlement_performed=false. Any retained forecast/receipt/draw/selection evidence with a missing registry remains an integrity failure. Exact current-attempt result paths are required; ancestor and leaf symlink redirects are rejected. Genuine acquisition/grading failures remain failures. No dummy registry, forecast or grade is created.

Independent follow-up verification passed 39 cases, including a reproduced-and-repaired old-attempt symlink bypass. See BLIND_CANONICAL_PREFLIGHT.md and its bound execution receipt. Hosted deployment of this follow-up is pending at this checkpoint and must be reconciled on its pull request after merge.
