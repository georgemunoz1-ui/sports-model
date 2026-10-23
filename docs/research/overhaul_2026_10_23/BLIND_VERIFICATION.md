# Independent blinded conformance verification

**Result: 61 independently authored tests passed for the pinned source snapshot.** This establishes the tested software behavior. It does not qualify a sports model, establish an accuracy improvement, authorize publication or wagering, or verify a deployed CI/Drive workflow.

Final run after the coordinator declared the production Python source frozen: `python -m pytest tests/test_blind_conformance.py -q` — **61 passed in 5.07 s**, exit 0. Execution began **2026-10-23 06:26:41 UTC** and completed **06:26:47 UTC**. Source hashes were identical before and after execution, with no source changes from the earlier checkpoint.

Snapshot SHA256: `4b51c925202b1b3b8963d1af9b230d928c8453e2442fc1e862f152cde14a9943`.

The complete source and retained-fit input hashes are in [`BLIND_VERIFICATION_FINAL_EXECUTION.json`](BLIND_VERIFICATION_FINAL_EXECUTION.json); output is in [`BLIND_VERIFICATION_FINAL_TEST.log`](BLIND_VERIFICATION_FINAL_TEST.log). The earlier checkpoint receipt and log remain preserved separately. The test source is [`tests/test_blind_conformance.py`](../../../tests/test_blind_conformance.py). A later edit to any pinned file requires a new run before applying this result to the changed implementation. This working snapshot has no local Git metadata; the receipt does not claim a verified commit identity.

## Independence and method

The verifier read implementation source, public APIs, raw retained NFL input/model artifacts, and the two supplied user Markdown specifications. The verifier did **not** read builder test suites, the precheck DOCX, or `ADVERSARIAL_REVIEW`, `VALIDATION`, `CAPABILITY_GAPS`, or `THEORY_REVIEW` reports. Assertions and synthetic fixtures were independently chosen. Reproductions were sent to the coordinating agent; implementation fixes were made by their owners, then tested again independently. The verifier changed only its test and verification artifacts.

All newly constructed populations, outcomes, signing keys, external-adapter responses and future event packages are explicitly synthetic. Test keys are local fixtures and confer no real review authority. The NFL CLI test uses retained fitted coefficients with synthetic future inputs. Both actual CLI tests execute real inference, persistence and selection code through subprocesses; they do not mock the forecasting or selection implementation.

The unavailable original five-test wording is **not quoted or claimed to be reproduced verbatim**. Its operational interpretation is: a valid exact-identity positive twin versus an invalid identity; revocation blocks selection while preserving raw research; expired versus unexpired validation; children retain lineage without inheriting approval; malformed or tampered lifecycle evidence fails without erasing frozen replay. All five have direct assertions in this suite.

## Independently reproduced defects and final regression results

| Finding | Observed reproduction | Result on this snapshot |
|---|---|---|
| B01 — NFL v2 execution | `reidentify_nfl_run(..., semantics=SEMANTIC)` raised `NameError` because it referenced undefined `forecast_kwargs`. | Fixed. NFL reidentification and actual NFL CLI execute. Explicit legacy replay remains available. |
| B02 — Missing power declaration | A correctly signed v2 protocol/lifecycle with `power_assumptions` removed still qualified. | Fixed. Missing declaration rejects; a positive declared protocol qualifies. |
| B03 — False delivery closure | `delivery.stage=Verified` accepted arbitrary strings for commit, missing configuration/verification files and a non-URL run value. | Fixed. The false closure rejects. A complete bound positive twin passes, while an otherwise matching failed run rejects. |
| B04 — MLS target/mass mismatch | The bridge labeled a `.55 home / .25 away / .20 draw` 1X2 forecast as tie-refund, while recording push mass zero and loss `.45`. | Fixed. It preserves explicit regulation 1X2 semantics, including draw as a possible predicted outcome. |
| B05 — Population omission | A source card with one generated row and one failed row reported two events but omitted the failed event from its evaluation population. | Fixed. The failed opportunity remains in the population as blocked, with null forecast mass. |
| B06 — Incomplete predictive identity | Removing any of model identity, fitted state, feature semantics or calibration identity from an otherwise correctly signed candidate still qualified. | Fixed. All four incomplete candidates reject; the complete positive twin qualifies. |
| B07 — Newly emitted MLS targets could not settle | The corrected bridge emitted `regulation_90` targets, but `settle_target` rejected every such target. | Fixed. Home/away/draw golden settlements pass with explicit regulation scores. Missing score period and full-game scores reject. |

No reproduced defect above remains open in this pinned snapshot. Passing tests are evidence for these assertions, not an exhaustive proof that the program is defect-free.

## Behavioral evidence

| Contract | Independent exercise and observed result |
|---|---|
| Market-blind numeric execution | Real NBA, NHL, MLS, CFB, WNBA and current-package MLB adapters were rerun with different price metadata at identical numeric inputs/cutoffs. NFL used real retained-fit inference plus reidentification at one fixed cutoff. Numeric identities, probabilities and retained draw hashes/arrays stayed equal across all seven sports. Archival package identities could differ. |
| Legacy separation | Direct and explicit legacy replay preserve probabilities and draw arrays for NBA/NHL/MLS. NFL's legacy reidentifier preserves the original objects. These tests do not assert that every historical forecast in the repository has been replayed. |
| Qualification and lifecycle | Exact target family and procedure identity are checked. Missing validation retains raw probability while returning null selection probability and `NO_PICK`. Signed revocation and tampered journal tests block selection while leaving the frozen decision verifiable. An unexpired positive twin qualifies and an expired one rejects. |
| Ancestry | A two-parent child retains ancestor/defect identities and does not inherit approval. Changing family labels does not reset two recorded ancestral inspections. Missing parents reject. A synthetic storage implementation isolates and exercises the graph cycle guard. |
| Selection and prices | Probabilities `.61`, `.60`, `.59` against threshold `.60` yield selected, selected and eligible-not-selected. Prices at decimal odds `1.5`, `2`, `4` leave decision identity unchanged. For win/loss/push/void mass `.62/.26/.08/.04`, expected net values are `.05`, `.36`, `1.60`; refunds are not losses. |
| Outcome accounting | A selected WIN/LOSS/PUSH/VOID/LIVE/MISSING fixture yields four resolved outcomes, unconditional accuracy `1/4`, non-win risk `3/4`, decisive-only accuracy `1/2`, and two ungraded outcomes. Proper-score denominators include the resolved refunds under this declared objective. Empty selection risk remains null and abstentions add no wins. |
| Population and pairing | Omitting a declared population event rejects. A different control target rejects. Blocked rows remain in coverage denominators. Mixed unplanned procedure identities reject. Tied probabilities enter the risk/coverage curve together. |
| Dependence, multiplicity and power | One supplied block produces no uncertainty interval. Holm requires the inspected total; `.01` with 40 inspected trials adjusts to `.40`. Power planning reports declared effect, paired SD, dependence, multiplicity and target power; the tested design effect of 2 gives ESS 5 from 10 observations. The signed positive fixture uses 8 events/4 slates/4 selections with protocol-specific justified minima, demonstrating that admission does not impose a universal 200/20/8 floor. |
| Frozen walk-forward procedures | A signed v1 event plan admits four changing state assignments and rejects a substituted state. A separately frozen v2 refit recipe then admits two later computed synthetic mean fits, 2 and 4, plus separately bound controls. Re-signed wrong-recipe and future-available training-data variants reject. |
| Rest semantic oracles | Each training and serving adapter is checked individually against hand-calculated nine-feature vectors. Cases cover UTC midnight, a long bye with the 14-day cap, and road-trip timestamps with `-07:00` and `+09:00` offsets. Expected rest pairs are `13/12 and 4`, `14 and 7`, and `47/24 and 83/24` days. Poisoned `state.last` values demonstrate the candidate does not rely on that proxy. Adding a real later prior game changes home rest from 4 to `25/24` days in each adapter. |
| Legacy rest separation | A separate check retains legacy rest of 14 days while the candidate reports `13/12` and 4 days; the source state is unchanged and the candidate requires refitting/chronological evaluation. No candidate forecast is inferred by applying old coefficients to the new rest values. |
| Actual entrypoints | The shared NBA card CLI and the NFL integrated CLI emit bound decision artifacts and retain raw forecasts under publication/selection blocks. Both use default numeric-v2 execution. Source-card retrospective replay retains its original bytes and is explicitly labeled retrospective/discovery. |
| Storage implementation | Run and attempt produce distinct bundles with member hashes. A synthetic adapter must download identical bytes before archive verification succeeds; corrupted readback rejects. Persistent compare-and-swap/readback tests exercise above/equal/below transitions, suppression of repeated-below events, a later second crossing, and both initial-below policies. Expired artifacts are excluded from active bytes. Account quota remains explicitly unknown. No notification or deletion occurs. |

## Scope limits that remain material

The registry verifies content identity, declared contracts and trusted signatures. It does not independently establish source authenticity, unlogged experiment history, independence of the humans behind signing identities, correctness of a declared power model, or the truth of submitted evaluation statistics. Synthetic positive admission here is deliberately not scientific certification. The refit-policy report correctly says that a trusted authority attested the fit; the validator does not independently execute and reproduce that fit.

No actual Google Drive upload/readback, hosted GitHub Actions execution, merge, enabled workflow configuration, account-level quota measurement, notification or deletion was performed by this verifier. Storage tests exercise implementation contracts with a synthetic adapter. Their passing result cannot be reported as operational deployment or durable external archival success.

Upstream acquisition completeness and exact score-period evidence remain necessary. The suite verifies that known failed opportunities are retained and that regulation settlements refuse unlabeled/full-game scores; it cannot discover games omitted from the upstream schedule or authenticate a caller-supplied result.

The initial repository healthcheck in the restored checkout returned **58 failures and 3 warnings**, including absent historical data and artifacts. This verifier did not repair those unrelated historical dependencies. The new conformance result does not override that health result or change any publication, wagering, or model-promotion status.
