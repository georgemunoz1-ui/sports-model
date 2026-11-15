# Cross-model missingness acceptance recheck — November 15, 2026

**Disposition: engineering repairs implemented and exercised; system-wide
acceptance remains incomplete.** This extends the existing draft PR #117 and
its companions. It does not merge a model branch, change a selected model,
install an approval, or establish a production monitoring service.

The shared baseline was `14ccf3edacd6a5ad1463b66bbdd08582aab589e7`. The freshly
inspected main branch was `5f81c855f468f61ab6d9270a1fe93b8ed0b5b37f` and did not
contain the missingness draft implementation. Complete source and test hashes,
preserved artifact hashes, logs and independent review receipts are in
[the verification manifest](evidence/verification.json).

## Repairs made after reproducing the failures

| Defect | Repair and verified behavior |
| --- | --- |
| Runner discovery only checked `scripts/run_*.py` | Classifies 133 discoverable entry points using Python AST, console registrations and workflow commands. Twenty inline-Python workflows are pinned for review. New or removed entries and changed inline code fail the inventory test. |
| Direct CFB/MLB Monte Carlo and NFL margin CLIs bypassed receipts | CLI-only hooks retain separate, immutable missingness receipts and perform readback. Native numerical functions are unchanged. Failed acquisition, duplicates and unresolved event identity cannot reach the direct simulation call. |
| An unknown CFB feature could be called an observed input | Actual consumed columns now require explicit feature/model/head contracts. Unknown columns, model IDs, head names or link kinds produce `TRACE_BLOCKED` while the numerical research forecast remains retained. |
| Release readback omitted material contract fields | Every current manifest field is checked, including authority, cutoff, dates, league/market scope and source evidence. Ten altered/omitted-field regressions now fail readback as required. Original v1 artifacts remain readable and cannot pass the current release gate. |
| Malformed evidence for one league raised an exception | The affected league is blocked with explicit problems; healthy siblings remain available. Independent probes exercised 225 malformed shapes without a crash or lost valid sibling. |
| Every review cohort had to include numerical forecasts for missing mandatory inputs | Versioned v2 policies distinguish supported prediction groups and source states from required refusals. They retain all opportunities and enforce predeclared per-group counts and refusal limits. Scored predictions still require paired numeric comparators; unscored refusals can retain witnessed comparator refusals. |

A current blocked/unregistered trace, unverified parent or incomplete feature
inventory is also refused even when a prior scope and the current inventory
have valid test signatures. Ten semantic regressions exercise those denials.

The release-readback defect did not demonstrate actual wager activation: the
recomputed result still held action authority OFF. It did demonstrate that an
altered published manifest could pass its readback routine.

The shared declarations cover all nine columns of each initial NBA/NHL/MLS
score arm and all ten selected-CFB columns. They expose per-head medians, actual
fit/model identity, current transformed states and available historical counts.
Priors, shrinkage, rest defaults, cold-history indicators, Elo replacements,
normalized venue flags and unknown season markers are explicit. Their
statistical-review status remains pending. The other native and companion
models retain their own sport-specific contracts and limitations.

Details: [runner coverage](RUNNER_COVERAGE.md),
[feature contracts](FEATURE_CONTRACT_REVIEW.md), and
[refusal-policy v2](REFUSAL_POLICY_V2.md).

## Cincinnati–Atlanta regression replay

The retained before/after input vectors were evaluated against the unchanged
packed NFL model. All five arms reproduced both editions: **10 fitted
predictions matched**. This was a retained-input retrospective diagnostic;
no new prospective registration or real-game simulation was generated.

| Arm | Report-presence contribution to Atlanta margin | Report-presence contribution to total |
| --- | ---: | ---: |
| Selected QB | 0.00 points | 0.00 points |
| Availability | −7.81 points | −9.23 points |
| Combined | −8.01 points | −11.18 points |

Negative Atlanta-margin movement favors Cincinnati. The combined result is
still flagged `REPORTING_STATE_DOMINATED`. The report-count support reconstructed
from bound training moments is 2,877 games with zero missing team reports,
eight with one missing report and zero with two: **2,885 training games**.
The original two-missing-report state was unsupported by that fit. These
contributions describe an input transition, not player injury values or a
validated betting edge. See [the retained replay](evidence/cin-atl-regression-replay.json).

## Executed verification

- Existing shared baseline: **2,377 tests passed**.
- Updated shared repository and research suites: **2,462 passed, zero failed,
  zero errors, zero skipped**; 85 added regressions. The complete JUnit result
  and command log are retained.
- Release, promotion and readiness selftests passed.
- Independent release review first reproduced 13 failures and one passing
  positive control, then verified the repairs. Additional JSON-shape probes
  retained every valid sibling.
- Independent native NBA/NHL/MLS/CFB checks retained all existing row fields
  and all five saved synthetic draw files byte-for-byte when attaching the
  expanded contracts. This is a same-revision numerical preservation test;
  runtime commit/source identities can legitimately change artifact hashes.
- Three direct model modules are identical outside `main()` by independent
  AST comparison. Selected defaults, approval anchors, model registry pins,
  the packed NFL fit and the original CIN–ATL fixture remain byte-identical.

### Companion branches rechecked separately

| Draft PR | Pinned head | Passing workflow scope |
| --- | --- | ---: |
| #111 standalone CBB | `92c1080895a55fa3060fff663835e82341484319` | 28 |
| #112 joint-volatility child | `4e0710c45d744e407fdd694d2cd19734b9dbdf21` | 49 |
| #113 NBA combination | `7433619cc8fab62df1cda33000cbf11384cd84cc` | 32 |
| #114 NBA/CFB personnel, original check | `3246bd3e6b356abe47ead1a298ce329d4622b57a` | 128 |
| #115 CFB event freshness | `b480f7690f154bc0a0d7247bb7508c1502543f43` | 183 plus 20 source-bound finding packets |
| #116 joint operator route | `5d07f9372590ec73d1e8c02f62959471c026404c` | 125 |

These populations overlap and must not be summed as independent events. The
CBB mixed fixture retains one generated forecast and two explicit refusals,
with independent receipt replay for all three. All six workflows run their
missingness checks on every pull request without base/path filters.

The #114 recheck found a historical-experiment fit-failure return and
pre-prediction exclusions without receipts. The additive follow-up at
local reviewed successor `d1dd65c03a288b59032076170080e3b2ded67fd3` adds those refusal receipts,
complete source-row inventory, malformed-row isolation and readback. Its exact
workflow scope passes **141 tests**, including 13 new regressions. Independent
review passes 145 tests including four additional omission/isolation probes. Native fitted-model source, default registry, state and card-side
execution are unchanged. Its separate verification record is retained beside
the companion evidence. This exact reviewed tree (`956a61bab722855f22ed0d2153faa39806175d5f`)
was published additively to #114 as `348152ba39886fa54e4ec5fd4eafd99153267415`
and fetched back to verify tree equality. The #115 historical CLI can exit zero while retaining
explicit refusals; a zero process exit is not forecast completeness or release
eligibility.

## Acceptance against the owner's seven requirements

| Requirement | Current evidence | Remaining condition |
| --- | --- | --- |
| Inventory every active runner and arm, including CBB | Expanded shared census plus pinned companion inspection and CBB invocation checks | The actual combined/deployed revision must be inventoried and exercised after integration; dynamic shell indirection requires manual review. |
| Reviewed contracts for every missingness-dependent feature | Explicit consumed-column engineering contracts and retained native/companion feature evidence | Independent statistical review of each exact model/head/product, source/season support and fallback remains pending. |
| Sensitivity/failure tests are invoked | Full shared suite, actual CLI hooks, companion workflows and negative probes executed | Derived child sensitivities that report unestablished support remain ineligible; software checks do not fill that evidence. |
| Current-output attribution receipts | Shared/native receipts retain reporting, substantive, model, simulation and unresolved components; missing pairs remain unavailable | Publication needs the actual dated run and matching prior receipt; this audit does not create a new daily slate. |
| Unsupported cases cannot become official selections | Draft release/readiness/promotion paths reject absent scoped approval and invalid current evidence; v2 narrows approved source states | Default-branch deployment and protected integration remain outstanding. No branch-only check is claimed as active production enforcement. |
| Model-specific evaluation and real forward monitoring | Versioned policy and refusal mechanics exercised; existing NFL candidate remains separately identified | No approved product limits, qualifying untouched confirmation cohort or real source-bound monitoring writer/witness process was established. |
| Independent verification of invocation | Independent release, feature, native CLI and v2 review plus companion execution evidence | This is engineering review, not an authorized scientific review or protected deployment approval. |

Pinned-environment repository health still reports **four failures and seven
warnings** at the recorded feature-contract checkout. Failures concern the
unavailable/unversioned production pitcher archive, overdue recovery jobs,
historical release eligibility, and standing-health evidence. Those are not
cleared by the passing missingness tests.

**Execution: COMPLETED for the described engineering scopes. Predictive
validation: HOLD. Official publication: INELIGIBLE. Wagering authority: OFF.**
No coefficient was zeroed, no model promoted and no frozen forecast rewritten.
