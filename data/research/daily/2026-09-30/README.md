# Sports model research — September 30, 2026

Execution verified at 2026-09-30T15:23:13.968173+00:00. Pacific slate date. **PROVISIONAL / DIAGNOSTIC. Action OFF; dose 0.0.**

| League / event | Start PT | Arm | Model output | Simulation output | Disposition / limits |
|---|---|---|---|---|---|
| NHL · Los Angeles Kings @ Colorado Avalanche | 7:00 PM | Initial winner research | Colorado Avalanche 64.84% | 64.93% | PRE_START; goalie/skater availability unconsumed; winner only |
| NHL · Pittsburgh Penguins @ Philadelphia Flyers | 4:30 PM | Initial winner research | Philadelphia Flyers 64.43% | 64.33% | PRE_START; goalie/skater availability unconsumed; winner only |
| NHL · New York Islanders @ Toronto Maple Leafs | 4:30 PM | Initial winner research | Toronto Maple Leafs 50.49% | 50.74% | PRE_START; goalie/skater availability unconsumed; winner only |
| MLS · St. Louis CITY SC @ Red Bull New York | 4:30 PM | Initial Poisson 1X2 | Home 38.63%; draw 24.83%; away 36.54% | Home 38.59%; draw 24.96%; away 36.45% | PRE_START; regulation only; lineup/injury/weather unconsumed |

Each event used **100,000 actual draws**. NHL: `nhl.initial_causal_score.research.v1`; MLS: `mls.initial_causal_score.research.v1`. Neither is an automatically selected tested default. The separate NHL joint-score challenger and its prior forecasts are unchanged; it is not blended into this board. No new market snapshot was consumed or used to select an arm.

## Other scheduled events and no-game evidence

| League | Event(s) | Disposition |
|---|---|---|
| MLB | PHI @ ATL, CWS @ HOU, BOS @ NYY, CHC @ SD | NOT_SUPPORTED_POSTSEASON: official wild-card game type is outside the merged regular-season builder |
| WNBA | ATL @ WAS; GSV @ DAL | NOT_SUPPORTED_POSTSEASON: FF7 target contracts and current fitter are regular-season only |
| NFL | No September 30 game in captured census | No numerical run; QB provisional default retained, combined quarantined/experimental; B2 pending trace/complete registration |
| CFB | No September 29 completed event or September 30 event in captured census | No newly completed game-day trigger; CONTROL-MISSING; RESEARCH, NO-CURRENT-SEASON-ASSIMILATION-GATE |
| NBA | No event; training camps, preseason begins October 3 | Automatic selection executed and refused NO_VERIFIED_TESTED_DEFAULT:nba:winner |

NBA phase verified from https://www.nba.com/news/key-dates (official schedule JSON returned 403; no JSON success claimed). WNBA playoffs verified independently from https://www.wnba.com/playoffs/2026 and retained official schedule JSON. MLS is in regular season: https://www.mlssoccer.com/competitions/mls-regular-season/2026/matches/rbnyvsstl-09-30-2026/. D.C. United–Paderborn is a friendly, outside the MLS league arm. NHL official census: https://api-web.nhle.com/v1/schedule/2026-09-30.

## MLB short packet/input review

Today has four official postseason games; first start **11:00 a.m. Pacific**. All four September 29 finals/PBP sequences reconciled (288 completed plate appearances). Fresh official feeds are retained as a successor source capture; no postseason model contract was invented and no stale package was retimed.

| Matchup | Probable starters, away / home | Confirmation and forecast |
|---|---|---|
| Philadelphia Phillies @ Atlanta Braves | Cristopher Sánchez / Tyler Mahle | Probables only; confirmation timestamps unestablished; postseason forecast unsupported |
| Chicago White Sox @ Houston Astros | Sean Burke / Hunter Brown | Probables only; confirmation timestamps unestablished; postseason forecast unsupported |
| Boston Red Sox @ New York Yankees | Sonny Gray / Max Fried | Probables only; confirmation timestamps unestablished; postseason forecast unsupported |
| Chicago Cubs @ San Diego Padres | Kevin Gausman / Nick Pivetta | Probables only; confirmation timestamps unestablished; postseason forecast unsupported |

Full-season PBP completeness, actual lineup/starter confirmation times, injury effective/retrieval times and bullpen availability are not established. Weather feed availability is retained per event, not a fitted adjustment. No event forecast cutoff is declared for the unsupported postseason arm. September 14 runtime pins and all previous packets remain unchanged. This morning review cannot confirm later lineups or inactive releases.

## Gates, execution and evidence tiers

- **Implemented/inspected:** immutable package/code/state digests, source TTL, model scope, source/cutoff ordering, pre-start rejection and explicit research opt-in. Main remains `43ad83382af067b019a086d45d23569497ca6e08`; 116 present code/control files matched Git objects. PR #45 remains open and unmerged; its helper files match explicit commit `835003dc872991d44679fcdb923b77cfbb9043c2`. The supplied cross-sport protocol remains applicable with the user’s September 23 numerical-research amendment.
- **Source review executed:** four event-specific agent decisions bind source hashes; runner review bindings add fresh package hashes. Official NHL event identities/start times agree with the provider census. MLS identity/start agrees with the official match page. NHL injuries were captured and inspected, but are not numerical goalie/skater features. MLS final lineups remain unconfirmed.
- **Current-packet execution:** fresh NHL and MLS packages loaded with code/state/TTL checks; four actual runners emitted retained draws and consumed-feature traces. Four seed replays matched exactly. Source availability, feature use and forecast execution are separately recorded.
- **Test execution:** targeted pytest invocation failed before tests ran: `No module named pytest`. Therefore test suite status is NOT-RUN, not PASS. Actual package/draw verification is a separate executed check.
- **Health:** exit 1, 11 failures and six warnings in this local assembled snapshot, including environment/git/source-mount limitations and unresolved historical obligations. It is not a passing main CI claim. Current research results do not override those release failures.

The initial-arm previous-UTC-day embargo remains enforced. September 29 NHL results were collected as completed outcomes but are **not assimilated into these September 30 features**. This is the frozen chronology rule, not a claim of current-season assimilation. MLS consumed eligible earlier regular-season history under the same rule. No forecast is called current with missing source receipts.

## League-specific evaluation populations

| League | Population / period | Tier and restriction |
|---|---|---|
| MLB | 1,054-game broader April–July 2026 OOF screen; separate 234-game June 29–July 19 holdout | Frozen V13 research, NO_PROMOTE; no postseason or full-game run-line/total settlement validation |
| NFL | 1,865 non-tied reused-history OOF games, 2019–2025 (1,871 including six excluded ties) | QB provisional research default; not untouched program-level holdout; official gamebook/P3/current personnel/registration remain separate |
| CFB | 10,818 historical FBS/FBS Week 2+ OOF games, 2011–2025 | Historical selection does not close executable current-season assimilation acceptance |
| WNBA | 1,633 walk-forward games from 2017–2026 window, original feature-state scope through July 22 | FF7 winner, margin and total target-specific evidence retained; fresh postseason fit/feature-frame/runner is not established |
| NBA | No verified default evaluation population | Initial research capability does not establish automatic selection or current readiness |
| NHL | Train 2021–2024: 4804; validation 2025: 1312; later audit 2026: 1312 | Retrospective current-provider copies; historical PIT availability unproved; no promotion |
| MLS | Train 2021–2024: 1921; validation 2025: 510; later audit 2026: 402 | Retrospective current-provider copies; historical PIT availability unproved; no promotion |

NFL lessons remain binding: preserve arm labels, gross/net/sack-yard accounting and win/margin/score coherence; a winner simulation is not a joint-score law. MLB lessons remain immutable September 14 pins and injury-source lag. NHL yesterday’s richer distribution did not establish superiority over the original winner arm; keep them separate. Tests and simulation counts are not predictive validation.

## Standing health — read-only due-date checkpoint

**Aged unresolved leaf obligations: 11.** Previous corrected leaf count: 9; last persisted grouped-session count: 2. The increase is REL-ARCHIVE-001 and RJ-007 crossing 14 days since their September 16 material changes. The September 16 baseline remains two; the ≤2 target is not met. Parents/aggregate are excluded. No new session, blocked streak, material-change date or owner acceptance was written.

Both P0 cards contain recorded owner, dependency, last-action evidence, dated next action, escalation owner and decision. Their September 17 next actions are overdue; the existing risk reviews are expired. Recorded role confirmation is not a fresh owner attestation. Thirteen current register/evidence validation errors remain. No waiver is inferred.

| Issue | FIXED | NOT ESTABLISHED / REMAINING | NEXT EVIDENCE |
|---|---|---|---|
| REL-ARCHIVE-001 · OVERDUE-ESCALATED | Only the executed action/evidence described in this card | Official release eligibility, historical registration or forecasting superiority | Reconcile the 58-file candidate against authoritative required-game coverage, inventory August 31 gap, and bind a separately versioned prospective archive profile. |
| REL-HISTORICAL-001 · OVERDUE-ESCALATED | Only the executed action/evidence described in this card | Official release eligibility, historical registration or forecasting superiority | Keep September 3 evidence immutable; define a separate current-profile check and prove dependencies before replacing any current-health coupling. |
| RJ-001-PROVENANCE · OVERDUE-ESCALATED | Only the executed action/evidence described in this card | Official release eligibility, historical registration or forecasting superiority | Inventory the 126 score-verification IDs against current Tier-1 bindings and retain a missing-ID manifest before acquiring finals. |
| RJ-006-NFL-MODEL-RESTORATION · OVERDUE-ESCALATED | Only the executed action/evidence described in this card | Official release eligibility, historical registration or forecasting superiority | Locate original data/nfl/model/runs/2026-08-10_nflverse_2015_2025_oof_v2 and invalidation record in owner backup; verify exact source pins before assigning units. |
| RJ-007-DATELESS-JOIN-REMEDIATION · OVERDUE-ESCALATED | Only the executed action/evidence described in this card | Official release eligibility, historical registration or forecasting superiority | Test duplicate/date/outcome refusal; enumerate canonical IDs for historical migration sidecars without changing frozen boards. |
| RJ-005-AVAILABILITY-01 · OVERDUE-ESCALATED | Individual tracking slot created | Team/date identity, official availability, pregame receipt or current forecast readiness | Recover the historical mapping for slot 1; bind its team, date and event, then hash the matching official report or document a justified reclassification. |
| RJ-005-AVAILABILITY-02 · OVERDUE-ESCALATED | Individual tracking slot created | Team/date identity, official availability, pregame receipt or current forecast readiness | Recover the historical mapping for slot 2; bind its team, date and event, then hash the matching official report or document a justified reclassification. |
| RJ-005-AVAILABILITY-03 · OVERDUE-ESCALATED | Individual tracking slot created | Team/date identity, official availability, pregame receipt or current forecast readiness | Recover the historical mapping for slot 3; bind its team, date and event, then hash the matching official report or document a justified reclassification. |
| RJ-005-AVAILABILITY-04 · OVERDUE-ESCALATED | Individual tracking slot created | Team/date identity, official availability, pregame receipt or current forecast readiness | Recover the historical mapping for slot 4; bind its team, date and event, then hash the matching official report or document a justified reclassification. |
| RJ-005-AVAILABILITY-05 · OVERDUE-ESCALATED | Individual tracking slot created | Team/date identity, official availability, pregame receipt or current forecast readiness | Recover the historical mapping for slot 5; bind its team, date and event, then hash the matching official report or document a justified reclassification. |
| RJ-005-AVAILABILITY-06 · OVERDUE-ESCALATED | Individual tracking slot created | Team/date identity, official availability, pregame receipt or current forecast readiness | Recover the historical mapping for slot 6; bind its team, date and event, then hash the matching official report or document a justified reclassification. |

RJ-001 acquisition is 123/123 while the distinct official-score phase is **0/126**. RJ-006 original EPA lineage remains **1/6**; RJ-007 is **0/6**. WNBA RJ-005 is **11/17**, with six missing OFFICIAL_INJURY_AVAILABILITY units in a five-component pipeline. Each ordinal child 01–06 was checked separately; all remain UNIT_BINDING_UNRESOLVED, with no team/date identities inferred. RJ-003 remains CLOSED_CONDITION_NOT_FIRED, not an overdue failed recovery.

Reproducibility tier: executed source/package/draw checks for new research; register/hash inspection for standing issues; original-history closure not reproduced. Preserve the September 3 blocked release.

**Next concrete action:** before interpreting tonight’s model/market disagreement, bind current goalie/lineup information and event-matched prices as separate evidence; a registered availability challenger is required before those values can affect this model. Resolve the two P0 overdue dependencies and the newly aged archive/identity items without resetting their clocks. The daily review promises no unattended later cutoff check.

`accepted_risks_present: true`  
`accepted_risk_release_override: false`  
`official_release_eligible: false`  
**Action OFF; dose 0.0.**
