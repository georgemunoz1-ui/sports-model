# Current repository status

**Reviewed October 23, 2026 Pacific / October 24 UTC.** Evidence snapshot: `main` at `15bc5b87ee8e403589c0bf384aa4667039935db4`, tree `f7819142a41669d4f291e970deea0626d255a268`. This is a documentation reconciliation, not a new model run or global acceptance.

## Separate the six decisions

| Dimension | Verified checkpoint | What it does not establish |
|---|---|---|
| Code integration | PRs #72 and #75–#78 merged | Every open research branch is integrated |
| Research execution | CFB/NBA chronological comparisons, selectors and local SHADOW paths exercised | Untouched confirmation or profitability |
| Software CI | PR #78 reports 9/9 final-head, 6/6 post-merge checks; hosted suite 1,367 tests | Current source readiness or global health clearance |
| Repository health | Local partial checkout 55 failures/4 warnings; separately recorded hosted health 4/7 | A comparable improvement from 55 to 4, or closure of either report |
| Durable evidence / canonical grading | Archive unconfigured; latest canonical preflight has zero registrations | Verified remote archival or a settled prospective sample |
| Promotion / wagering | Challenger qualification HOLD/SHADOW; action OFF | Owner approval substitutes for predictive evidence |

Sources: [PR #78](https://github.com/georgemunoz1-ui/sports-model/pull/78), [PR #77](https://github.com/georgemunoz1-ui/sports-model/pull/77), [health reconciliation](HEALTH_RECONCILIATION_2026_10_23.md), [canonical preflight](../data/grading/canonical/operations/preflight-39999394059-1.json).

## League and core-product coverage

Capabilities are classified within their exact scope: **absent**, **disconnected**, **runnable-but-unevaluated**, **evaluated**, or **scope-approved**. A scope-approved research winner is not an approved betting product.

| League | Winner / moneyline research | Spread / run / puck line and total research | Qualification boundary |
|---|---|---|---|
| NFL | Selected QB contextual winner; original inference preserved | Separate combined-arm joint/spread calibration; selected-QB full-support margin completion remains on open PR #69 | No borrowing combined residuals for the selected QB; tie, push and OT contracts remain explicit |
| CFB | Selected FBS Elo/form family with separate opener scope; matchup-efficiency challenger evaluated | Selected current parent has no total head; opt-in margin/distribution and efficiency joint experiments are distinct | FBS/FBS and week scope; no fitted personnel increment or validated football key-number claim |
| NBA | Initial causal-score baseline by explicit opt-in; possession-efficiency v2 evaluated | Independent point heads and separately identified continuous joint v2 evaluated | No qualified default promotion; efficiency Brier inconclusive, margin worse, joint Brier worse |
| WNBA | Existing selected FF7 research family; current adapter is present | Winner/margin/total heads retain product-specific historical evidence | Regular-season source contract; no automatic postseason or personnel-effect qualification |
| MLB | Selected V13 current-input research profile; MC-only probability | Other engines and run/total research exist separately | Full-game extra-innings/run-line/total settlement not qualified by winner selection; starter scope must be explicit |
| NHL | Explicit initial research baseline and season-rollover acquisition repair | Separate research distributions | Rest construction/refit and goalie/OT/SO qualification remain unresolved; affected recommendation eligibility stays suspended |
| MLS | Explicit initial Poisson research path for regulation home/draw/away | Shared discrete research supports declared contracts; other branch APIs may refuse handicaps | No verified automatic default; regulation, draw, quarter-handicap and extra-time rules cannot be mixed |

The selection registry remains [defaults_v1.json](../data/model_selection/defaults_v1.json). Read [runtime access](CONSOLIDATED_MODEL_ACCESS.md) and the [preserved historical selection evidence](history/2026-10-23-status-refresh/MODEL_DEFAULT_SELECTION.md); this page changes neither.

## Efficiency results and response to the NBA regression

| Comparison | Common events | Control Brier | Candidate Brier | Candidate minus control | Paired 95% interval |
|---|---:|---:|---:|---:|---|
| CFB efficiency | 1,045 | 0.18409675 | 0.18454937 | +0.00045262 | [−0.00189355, +0.00270544] |
| CFB joint | 1,045 | 0.18409675 | 0.18505651 | +0.00095977 | [−0.00110367, +0.00309803] |
| NBA efficiency v2 | 2,458 | 0.20990081 | 0.21119841 | +0.00129760 | [−0.00097092, +0.00349871] |
| NBA joint v2 | 2,458 | 0.20990081 | 0.21373389 | +0.00383308 | [+0.00145619, +0.00636617] |

NBA efficiency margin MAE delta is **+0.151969**, interval **[+0.046957, +0.261353]**. Total MAE delta is **−0.015256**, interval **[−0.076987, +0.048197]**. Matched-training controls also fail to establish a winner-Brier improvement. These are retained, repaired retrospective diagnostics, not equivalence findings or untouched holdouts.

**Adjustment in selection:** preserve the incumbent/control; do not promote either efficiency candidate or use the worse NBA joint winner output as an operational replacement. Future possession/efficiency, personnel and joint-law repairs must be distinct increments with training-only choices, same-event controls and new confirmation data. This documentation update does not claim to have fitted those new increments.

See the [original experiment report](research/efficiency_2026_10_23/SWARM_RESULTS_2026_10_23.md) and [roadmap](RESEARCH_ROADMAP.md).

## Evidence population and provenance

CFB: 1,196 opportunities, 1,045 paired forecasts, 151 exclusions, 21 week blocks. NBA: 2,460 opportunities, 2,458 paired forecasts, two exclusions, 51 week blocks. Together: **3,503 unique common events**, **7,006 efficiency/joint stage receipts**.

The 58 local SHADOW entries comprise 10 CFB, 24 original NBA and 24 corrected NBA records across **17 unique games**. Each retains 100,000 trials/draws: 5.8 million executions, not 5.8 million independent observations. Preserve old identities and report candidate-stage counts separately from unique events. Canonical eligibility and external timestamp anchoring are not established by local logs.

JMU–App State, NE–Chicago and Denver–OKC remain discovery diagnostics. Ten forecast variants, five retained spread-contract variants and verified finals were recovered, but **zero complete original point-in-time reconstructions**. Missing exact Novig contracts/house rules and earliest evidence remain explicit. The retained OKC moneyline forecast won; the separate Denver +8.5 contract lost. No preventable-loss claim follows.

## Scheduling, grading and archive status

The canonical grading workflow declares daily `45 13 * * *` UTC plus manual dispatch and relevant pushes. Its latest inspected scheduled run [39999394059](https://github.com/georgemunoz1-ui/sports-model/actions/runs/39999394059) completed with `AWAITING_FIRST_PROSPECTIVE_REGISTRATION`: **registered_count=0**, **settlement_performed=false**. A successful empty preflight is not nonempty production grading.

The [diagnostic-card workflow](../.github/workflows/diagnostic-shadow-card.yml) is dispatch-driven; the inspected trigger block has no cron. The historical [all-model operations workflow](../.github/workflows/all-model-operations.yml) is branch-specific. PR #78 exercised local efficiency SHADOW paths but deployed no recurring efficiency service. A recurring acquisition → fresh package → candidate → verified archive → canonical registration chain remains unverified.

Archive implementation requires a pinned authorized uploader, CI authentication, destination and independent byte readback. The retained status is `BLOCKED_UNCONFIGURED`; no Drive durability receipt is invented. The storage monitor also needs its own threshold, persistent state and cadence; optional upload skips do not prove quota recovery. See [archive contract](CI_STORAGE_ARCHIVE.md).

## Latest supplied card is not a fresh model execution

The [October 23 3:31 p.m. Pacific card](cards/2026-10-23-1531-PT.md) contains 19 saved comparisons: 5 CFB, 12 NBA and 2 NHL. It reprices preserved morning forecasts; it has **no fresh fit/inference**, no new availability adjustment and **zero additional independent event evidence**. Chicago–Milwaukee was already in progress. All live allocations are zero. The separately described `joint.py` repair was unavailable to that run, so its integration/tests are not certified here.

## Open dependencies

| Workstream | Named dependency / next executable step |
|---|---|
| Personnel increments | Authenticated pre-cutoff status/workload data and an evaluated numerical transform; do not invent minutes or availability weights |
| NFL selector comparison | Exact chronological per-event OOF forecasts/outcomes and split identities |
| Executable market/ATS evidence | Timestamped paired quotes, exact side/line/period/rules, fees, limits and compatible score distributions |
| NHL rest/OT | Reviewed predecessor/horizon semantics, complete historical features, distinct refit/evaluation and explicit OT/SO contract |
| Canonical prospective evidence | Genuine pre-start artifact upload/verification and writer registration, then actual final settlement |
| Archive and health | Authorized uploader/configuration; versioned pitcher archive; overdue recovery and release/standing-health evidence |

Open PRs and component-level overlap are tracked in [recent changes](RECENT_CHANGES.md). Do not silently merge or activate them because similar utilities exist on main.
