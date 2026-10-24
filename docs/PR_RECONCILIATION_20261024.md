# PR readiness reconciliation — October 24, 2026

This branch reconciles seven reviewed PRs onto main
`c2a00e25282794e52981126217cb115be70398d5`. This is software integration,
not a model promotion, new forecast, prospective registration or predictive
validation. Wagering authority remains OFF. Original branch commits and dated
reports remain in history; their old results do not certify this integration.

## Reviewed scope and dispositions

| PR / original head | Reconciliation | Boundary |
|---|---|---|
| #68 / `b812e5701767daefc2f0367ee5926b1c66bb546e` | Isolated CFB binary-isotonic proposal and tests retained | No selected calibration changed |
| #70 / `37cfcf048a8f1ff6860ad49b8098160b07646364` | Margin library/adapters, side-bound v2 receipts and corrected non-push scoring | Football key-number parameters remain placeholders; no default promotion |
| #73 / `d64924730197c693d511c5227d80bad33921dd47` | Explicit settlement bridge and pinned-source comparison retained | No fitted distributions or selected-QB product changed |
| #71 / `8ad6d19d871e9e25397ac6db8b7d4e1e455c4f19` | Roster evidence and required-roster gate integrated into current runners | Conflicts remain blocked; no invented availability weights or player effects |
| #74 / `d5ab18213253fb2c903a943f06d499fe547afc7d` | Projection audits/provenance retained; distinguish numeric-v2 from legacy seed counterexamples | Declarations require receipt verification; market-informed modes stay explicit |
| #41 / `373b48be5d284515fbe39b6988e7eeac1111c680` | Current NFL validation, WNBA adapter and diagnostic workflow preserved; dated requests archived | Unknown context cannot be silently discarded or relabeled |
| #38 / `7f6c75736f9645e23de61cb3fae1352e1bfcf81d` (includes #37 ancestry) | Current immutable weekly-state implementation preserved; historical evidence retained | Broken obsolete runtime changes and legacy state-writing acceptance not activated |

Merge commits preserve ancestry without force pushes. Other draft/conflicting
PRs are outside this repair scope. In particular #69's selected-QB margin
completion is not integrated by importing its comparison fixture.

## Forecast and grading integrity

`sports.margin_quote.v2` binds `orientation`, `probability_basis=UNCONDITIONAL`
and the integer/half-line payoff contract into each receipt. Symmetric HOME/AWAY
quotes have different identities. The v2 validator rejects v1 records; no old
receipt is relabeled or rehashed. This three-outcome API rejects quarter lines;
#73's explicit five-state settlement bridge remains a separate contract.

Validation inputs require `p_push` and an explicit probability basis. With
realized pushes excluded, unconditional `p_cover` is divided by `1-p_push` for
Brier, log loss and reliability. Already conditional probabilities stay
conditional. A hand-checkable regression with `p_cover=.4`, `p_push=.2`, two
wins, two losses and one push yields conditional Brier `.25`, not `.26`.
Invalid mass, undefined conditioning, unsupported settlement and unlabelled
legacy inputs fail closed. No canonical ledger or stored forecast is rescored.

Roster annotations preserve `market_blind_numeric.v2` identities, numerical
outputs and draw bytes. Six actual shared-runner fixtures exercise 100,000
draws each. Legacy synthetic CLI fixtures explicitly request `legacy.v1`.

An NFL selection-sidecar aliasing defect was exposed during integration:
appending `WINNER_HEAD_UNAVAILABLE` could mutate the in-memory parent after
persistence, making later disclosure hashes disagree with saved bytes. The
selection bridge now copies its input. Pregame/live mutation regressions and
the actual NFL disclosure-sidecar test exercise this boundary.

## Historical components and current acceptance

The old PR #41 requests are preserved under
`docs/history/2026-10-24-pr-reconciliation/pr41/card_requests/`, outside the
active request directory. Its package builder is retained but not run.

PR #38's dated workflows and three obsolete tests are preserved verbatim as
`.txt` under `docs/history/2026-10-24-pr-reconciliation/pr38/`. They were not
counted as passing tests or installed as active CI. They target a superseded
state writer or unavailable historical APIs. Current acceptance instead uses
`tests/test_nfl_weekly_state.py` and `tests/test_nfl_context.py`: scheduled-team
and week scoping, complete schedule/PBP requirements, no future input leakage,
replay/idempotence, hash/parent-chain checks, concurrent writes and strict
information-regime validation. The legacy mutable writer stays disabled.
Historical scripts and registry evidence were retained without execution.

No existing file under `models/current`, `models/nfl/contextual`,
`pipelines/cards/adapters` or `data` was modified, removed or renamed relative
to the pinned base. `AUTHORIZATIONS.md` and prior `state.json` keys are unchanged.
Old `docs/progress.md` bytes remain an exact prefix. The one added historical
NFL registry file is not a new forecast registration.

## Verification and remaining gates

Local focused verification passed 254 tests. The first full run exposed the
parent aliasing defect and a missing import in the new draw tests; both were
repaired. Final local results are recorded below when execution completes.

The `PR reconciliation acceptance` workflow checks protected original files,
state and append-only journal; runs repository, research and isolated isotonic
tests; retains exact current-run JUnit/log bytes, a verified complete Git
bundle and a run/head/base-bound SHA-256 manifest. Its GitHub upload is required,
with seven-day retention and no `continue-on-error`. Upload/download verification
is a merge gate for this reconciliation. Quota failure is not waived by tests.

The separate Drive archive remains `BLOCKED_UNCONFIGURED`: its approved bridge
and CI authentication are absent. A successful seven-day GitHub artifact would
establish only that retention, not Drive durability, prospective registration
or recovery of earlier failed uploads. Branch protection was inspected as
unenforced with no required-check contexts; settings were not changed.

Final local full suite: **1,863 passed in 135.74 seconds** using Python 3.12.14.
Command: `python -m pytest tests research/tests research/cfb_binary_isotonic_proposal/test_binary_isotonic_repair.py -q --junitxml=tests.xml`.
Original local logs/JUnit and execution receipt are retained in
`docs/releases/2026-10-24-pr-reconciliation/`.

Health remains RED: four failures and seven warnings, with all seven current
source snapshots stale. Failures concern the unavailable/unversioned pitcher
production archive, overdue recovery jobs, historical September 3 release
eligibility and standing-health evidence. These are unresolved dependencies,
not cleared by software tests. Health-generated reports were restored exactly
and not substituted for original data. Protected source/state/journal and
verbatim archived-file checks passed; workflow YAML parses.

At initial publication, hosted CI and artifact readback were pending. No merge
is claimed in this document.

### Hosted integration follow-up

The first hosted run on `ee6b7d765d28e4efbb8373830ecda965269705da`
passed the full acceptance suite and required GitHub artifact upload
([run 40137946545](https://github.com/georgemunoz1-ui/sports-model/actions/runs/40137946545)).
This establishes upload availability for that execution, not account-wide quota
measurement or a verified Drive archive.

Two separate checks correctly rejected old evidence bindings against current
files. The historical margin comparison now checks out its original main pin
and loads PR #70's original library/validator under isolated module names.
The source manifest and old defect expectations are unchanged. Local execution
passes 162 synthetic and 26 retained-law comparisons, including the original
side collision, lost quarter-line settlement and `.26` Brier reproduction.
Current repaired behavior is checked separately by the v2 regression suite.

The old finding manifest and acceptance receipts remain unchanged. The new
`FINDING_EVIDENCE_pr_reconciliation_v1.json` points to a separately executed
complete-suite receipt and retains explicit links to each prior finding.
Its source hashes bind the newly tested code; no old acceptance is rehashed to
pretend it covered changed files. Original logs and the historical comparison
are under `docs/releases/2026-10-24-pr-reconciliation/ci-repair/`.
Final-head hosted checks and independent artifact readback remain required.

Final local rerun after the CI-reader repairs: **1,863 passed in 125.61 seconds**.
All 19 successor finding packets validate against the actual new execution.
The initial artifact was independently downloaded: its published ZIP digest,
all five manifest member hashes and Git bundle verification match. This receipt
is limited to the initial head; the final head needs its own hosted evidence.
