# Independent adversarial validation

This is an implementation review and acceptance record, not a handoff journal or a predictive-validation certificate.

Upstream source: `90daf8e0036c67a5304aa0747bf50b2266e0b364`. The local checkout is a source restoration; missing historical data cannot establish canonical repository health. Existing forecasts, ledgers, weights, defaults, and wagering authority are outside this review's mutation scope.

## Acceptance scope

The reviewed reference is the conversation's accepted separation of raw forecasting, target-specific validation, accuracy-first research selection, price diagnostics, and later evaluation. The supplied route assessment is supporting research, not executable authorization. Arbitrary sample floors, permanent inheritance of parent validation, and unproved optimality claims are not adopted as implementation requirements.

| Attack | Required behavior |
|---|---|
| Caller supplies `validated: true` or a PASS string | No eligibility without registry resolution and matching procedure/protocol/evidence identities. |
| Caller supplies two different reviewer names | Different strings alone must not be described as independently authenticated certification. Trust boundary must be explicit. |
| Child changes features/config but keeps a parent's certificate | No inherited validation; provenance and trial exposure may be retained separately. |
| Exact target swaps event, side, line, period, or settlement | Reject the binding mismatch or create a distinct target evaluation. |
| Payout odds change with exact forecast and target fixed | Selection and confidence remain invariant; price diagnostics may change. |
| Payout quote absent | Price diagnostics null; absence alone cannot block accuracy-first selection. |
| Spread/total target line absent | Block that target evaluation; no invented threshold. |
| Probability is boolean, NaN, infinity, negative, or has invalid mass | No selection or misleading finite derived probability. |
| Live/unresolved outcome appears in grading | Separate status/count; never grade as a settled loss or win. A settled VOID is a non-win under the explicitly frozen unconditional-win objective, with refund status separate. |
| Rejected candidate later loses | No manufactured abstention win. |
| Every row is blocked or no rows selected | Full-scope denominator remains visible; selected accuracy is undefined. |
| Duplicate quote snapshots or alternate lines inflate observations | Reject duplicates in a declared primary evaluation unit; retain nonprimary diagnostics separately. |
| Candidate/control pairs are missing or on different events | Expose missingness; do not fabricate a paired improvement. |
| Old effective time but later observed/retrieved source | Enforce the declared point-in-time policy; no post-cutoff knowledge. |
| Current/future event appears as prior rest history | Reject or exclude with explicit reason. |
| Old-season state is labeled fresh | Latest consumed identity and cutoff cannot be replaced by retrieval time. |
| Frozen record is mutated or dependency resolves through `latest` | Digest/identity verification fails; original artifact remains unchanged. |
| Publication gate fails | Continue independent research generation/logging when its own input contract permits it. |

## Execution status

Executed independently authored test suite:

```bash
python -m unittest discover -s tests -p test_overhaul_adversarial.py -q
```

Result on 2026-10-23: **49 tests passed**. The suite uses its own synthetic inputs and ephemeral Ed25519 keys; it does not borrow the builders' successful fixtures. It exercises a positive research-qualified SHADOW path as well as blocked paths, so fail-closed behavior is not confused with a selector that simply rejects everything.

| Component | Independent checks executed |
|---|---|
| Research selector | Positive SHADOW output, no ACTIVE/publication/wagering authority, missing/malformed/changed prices leave core decision identical, push-aware value and probability bases, forged qualification, untrusted signatures, altered lines/sides/periods, absent target line, boolean/nonfinite/out-of-range mass, incomplete distribution, live and future forecasts, swapped/future quality receipts, child approval reuse, changed family/config, mutable `latest` identity, input immutability. |
| Validation and trial journal | Authenticated author/reviewer identities, same credential under two names, discovery/shadow exclusion, review/registration chronology, self-review, signed revocation, malformed revocation, overflowing expiry, inconsistent evidence counts/coverage/power, signature tampering, existing artifact corruption, 24 simultaneous append attempts, duplicate trial rejection without file changes, anchored tail-truncation detection. |
| Evaluation | Full/eligible/selected denominators, zero-selection undefined accuracy, omitted blocked opportunities, duplicate quote/event inflation, mixed procedure/config/control/family identities, exact population/control target pairing, visible missing controls, no abstention wins, live excluded, push and void correctly scored under unconditional-win objective, risk-coverage ties, curve does not alter operational decisions, insufficient-block uncertainty, multiplicity for unreported trials, dependence-aware power planning direction. |
| Freshness and acquisition | Positive operational-rest reconstruction, post-cutoff/current-event exclusion, missing/future coverage, nonfinal and conflicting history identity, stale April state under a fresh October capture, future training cutoff, invalid numeric features, raw-byte binding, discarded scores, forfeit exclusion, NBA provider end-year, exact current-event packet binding, stale-season masking, conflicting/boolean provider years, future captures and path traversal. |
| Integration review | Read `run_research_selection.py`, `evaluate_research_selections.py`, the card runner's receipt hook, and integrity rendering. Independently tested push-aware control direction and exclusion of post-start raw forecasts while preserving population denominators. The selector CLI records actual execution time, historical mode, hashes of its inputs, and creates a new output directory; root's separate CLI tests cover immutable execution. |

## Findings repaired and retested

1. **Evaluation could mix procedure/configuration versions.** Required SHA256 bindings now reject mixed procedure, selector configuration, control, and target-family identities. Exact event target and slate binding remains independently checked. The integration caller must still pin the chosen upstream artifact/version; this does not certify that arbitrary input rows came from that artifact.
2. **VOID outcomes changed the objective silently.** The evaluator initially removed VOID from the primary scoring denominator even though selection uses unconditional win probability over win/loss/push/void. It now counts resolved VOID as non-win for that objective, while decisive-only accuracy and refund status are separate. LIVE/MISSING remain ungraded.
3. **Extreme expiry and malformed revocation could raise uncaught errors.** These now yield ineligible assessments rather than escaping the registry's rejection path.
4. **Different names could conceal the same author/reviewer signing credential.** Signed authorship is required; the verifier now rejects author/reviewer aliases sharing one public key. Different keys still cannot prove different human reviewers.
5. **Final-status prefixes could classify a forfeit as played rest history.** Played-final statuses now use an explicit allowlist; the adversarial forfeit is excluded.
6. **Old team state could conceal a future model-training cutoff.** A training cutoff after the forecast cutoff now produces `FIT_NOT_AVAILABLE_PREFORECAST` even when the consumed team timestamps are old.
7. **Normal upcoming schedule rows poisoned valid operational rest.** Completion ordering was initially checked before excluding current/future/nonfinal rows. An upcoming event observed before its scheduled start was therefore treated as corrupt history and made both teams' rest unknown. A realistic regression reproduced the failure; filtering now precedes completed-game timing validation, and the test passes without weakening malformed prior-final handling.
8. **The evaluation adapter used a 50% threshold to choose a control side from unconditional probability.** With win/loss/push masses of .45/.35/.20, this incorrectly chose LOSS. The adapter now compares complete win and loss masses and records the tie convention. The independent fixture now chooses WIN and reports the correct same-event control accuracy.
9. **Blocked post-start forecasts could still contaminate full-slate accuracy.** The evaluation adapter now retains the opportunity in the population but removes that raw estimate from scoring, discloses a scoring exclusion, and requires controls to exist before event start. The independent post-start fixture remains in the denominator and contributes zero raw forecast scores.

No failure remains in these 49 executed checks. This is bounded implementation evidence, not a statement that all future inputs, integrations, or predictive failure modes have been covered. Root integration tests and canonical repository health are separate checks.

## Authority and evidence limits

- Passing deterministic tests establishes software behavior only.
- A locally generated hash chain proves internal linkage; without an independent anchor it does not prove when a record existed.
- The registry authenticates signed scientific attestations and checks their stated criteria. It does not independently authenticate outcomes, recompute claimed power/intervals from paired data, or establish that a claimed historical signing time is true. Production trust anchors, witness services, and review policy remain external dependencies.
- `TrialLog.family_id` is assigned externally. The module does not contain a procedure-ancestry graph that forces a renamed family to inherit previous inspected configurations. Exact procedure binding prevents borrowed approval; inherited multiple-testing exposure requires trusted lineage integration.
- Source hashes establish byte identity. Coverage receipts remain acquisition assertions; they do not prove a provider omitted no games. Operational rest requires an `ALL_PLAYED_GAMES` population assertion, refuses regular-season-only coverage, uses a disclosed capture-age policy, and emits a separate candidate requiring refit and chronological evaluation, not silent inference through old fitted coefficients.
- Quality receipts are upstream diagnostic assertions bound to a forecast/input identity. The selector does not independently recalculate all upstream state or feature contributions from those receipts.
- Confidence bands are explicitly unavailable until qualified definitions and denominators exist. This suite supplies no probability-calibration, interval-coverage, injury-effect, or improved-accuracy evidence.
- These checks used synthetic inputs and local restored source. They did not establish new real-world pregame captures, authenticate the Oct 21–22 outcomes, rerun historical predictive validation, or establish canonical whole-repository health.
- No current output may become a production selection or wager through this test suite.
