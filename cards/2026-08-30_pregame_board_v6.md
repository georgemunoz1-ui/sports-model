# 2026-08-30 Pregame Board — V6 (signal/execution separation; append-only, no decision changes)

Issued: 2026-08-30 16:35 ET · lineage V1 (08:15, registered, sha256 `2ab780f7…`) → V2 → V3 → V4 → V5 → **V6 (owner review fixes)**
V6 applies the owner review of V5: (1) **signal vs execution separated** — ATL +2.5 is now `signal_decision: LEAN` + `execution_status: NO_PRICE` (actionable=false, clv_eligible=false, roi_eligible=false); the line is retained for model evaluation only and no entry EV/CLV is computed from a line-only observation. (2) **Clock semantics renamed** — `entry_snapshot_cutoff` 04:12 ET vs `decision_time` 08:15 ET, conservative stale-price caveat + no-new-information-between record. (3) **Movement qualified by market** — every movement record carries `movement.market`. (4) **Source-status flags** — line/price/probability/source_available + actionable/clv_eligible/roi_eligible on every market. Extended validation battery: clean. JSON canonical: `2026-08-30_pregame_board_v6_canonical.json`.

**Legend:** M = model win% · C = model cover% · Mkt = market no-vig% · pp = edge pp · movement prefixed [MARKET]

## WNBA

| Game | ML | Spread/RL | Totals | Movement | Game Decision | Note |
|---|---|---|---|---|---|---|
| MIN @ ATL | ATL +114 · M39.7 / Mkt44.9 · -5.2pp · PASS | ATL +2.5 · C64.2 / Mkt50.0 · +14.3pp · LEAN / NO_PRICE | N/A · NO_LINE | [TOTALS] unknown 0.2 (179.5→176.5) | **LEAN** | Brionna Jones out (pre-open); ATL possible B2B - model blind; only edge surviving reverse checks |
| LAS @ SEA | SEA -105 · M56.1 / Mkt51.1 · +5.0pp · PASS | line -1.5 · p=N/A · PASS | N/A · NO_LINE | — | **PASS** | coin-flip zone with stale data |
| GSV @ POR | GSV -198 · M74.7 / Mkt63.7 · +11.0pp · PASS | line -4.5 · p=N/A · PASS | N/A · NO_LINE | [SPREAD_RL] new_information 0.8 (-5.5→-4.5) | **PASS** | scenario engine: full rotation .747 vs 3-out .53-.62; model and market agree post-adjustment |
| CON @ DAL | DAL -1050 · M83.3 / Mkt87.6 · -4.3pp · PASS | line -13.5 · p=N/A · PASS | N/A · NO_LINE | [SPREAD_RL] new_information 0.85 (-9.5→-13.5) | **PASS** | no contrarian play against explained steam |

## MLB (actionable layer BLOCKED slate-wide — ML entries CLV_ONLY)

| Game | ML | Spread/RL | Totals | Movement | Game Decision | Note |
|---|---|---|---|---|---|---|
| MIA @ WSH | MIA -108 · entry for CLV only · CLV_ONLY | N/A · NO_LINE | N/A · NO_LINE | — | **PASS** | SP conflict RESOLVED V2 (Janson Junk) |
| COL @ ATL | ATL -224 · entry for CLV only · CLV_ONLY | N/A · NO_LINE | N/A · NO_LINE | — | **PASS** | ATL bullpen depleted (Suarez IL) |
| BOS @ NYY | BOS -115 · entry for CLV only · CLV_ONLY | N/A · NO_LINE | N/A · NO_LINE | [TOTALS] unknown 0.2 (8.5→8.0) | **WAIT** | Story/Anthony lineup status; tot steam unexplained |
| SEA @ TOR | SEA -135 · entry for CLV only · CLV_ONLY | N/A · NO_LINE | N/A · NO_LINE | — | **PASS** | roof TBD |
| KC @ CLE | CLE -180 · entry for CLV only · CLV_ONLY | N/A · NO_LINE | N/A · NO_LINE | [ML] unknown 0.18 (-167→-180) | **PASS** | unexplained steam, not faded (audit clause) |
| LAD @ DET | LAD -166 · entry for CLV only · CLV_ONLY | N/A · NO_LINE | N/A · NO_LINE | — | **PASS** | stale-source total conflict quarantined (Doc's 9.0) |
| SD @ TB | TB -165 · entry for CLV only · CLV_ONLY | N/A · NO_LINE | N/A · NO_LINE | — | **PASS** | — |
| TEX @ MIL | MIL -162 · entry for CLV only · CLV_ONLY | N/A · NO_LINE | N/A · NO_LINE | [ML] unknown 0.22 (-173→-162) | **WAIT** | MIL SP unresolved (May 'could start') -> lineup card |
| CWS @ MIN | MIN -112 · entry for CLV only · CLV_ONLY | N/A · NO_LINE | N/A · NO_LINE | — | **WAIT** | Buxton day-to-day, projection CONFLICT |
| PIT @ STL | PIT -113 · entry for CLV only · CLV_ONLY | N/A · NO_LINE | N/A · NO_LINE | [TOTALS] unknown 0.2 (8.5→8.0) | **PASS** | 90F noted |
| HOU @ NYM | NYM -119 · entry for CLV only · CLV_ONLY | N/A · NO_LINE | N/A · NO_LINE | — | **WAIT** | CONVERGENCE_FAIL posture stands; no new verified inputs |
| BAL @ ATH | BAL -148 · entry for CLV only · CLV_ONLY | N/A · NO_LINE | N/A · NO_LINE | — | **PASS** | — |
| PHI @ LAA | PHI -186 · entry for CLV only · CLV_ONLY | N/A · NO_LINE | N/A · NO_LINE | [TOTALS] unknown 0.2 (8.5→8.0) | **PASS** | price+line both moved (true movement), no news match |
| CIN @ CHC | CHC -142 · entry for CLV only · CLV_ONLY | N/A · NO_LINE | N/A · NO_LINE | — | **WAIT** | Wrigley wind MISSING |
| ARI @ SF | N/A · NO_LINE | N/A · NO_LINE | N/A · NO_LINE | — | **BLOCKED** | absent from DK board; starters TBD; confirmed via schedule/board reconciliation |

## NFL / CFB

- **NFL: NO_FORECAST** — 53-man cutdown day; Week 1 opens Wed 9/9.
- **CFB early board** (EARLY_FORECAST · NOT FINAL): Miami@Stanford −21.5→−24.5 (0.25) · Coastal@WVU −17.5→−21.5 (0.20) · UCLA@Cal flip +1.5→−1.5 (0.22) · Clemson@LSU −10.5, tot 50.5→51.5 (0.5) · Baylor/Auburn −7 (σ=18.385) · SMU@FSU −2.5 (Jennings PROVISIONAL).

## Validation record (extended battery, per owner review)

- Signal/execution: `LEAN` ⇒ actionable=false OR price non-null — holds (the one LEAN is NO_PRICE, actionable=false) ✓
- CLV eligibility requires entry line + entry price: 14 MLB ML entries eligible; ATL +2.5 NOT eligible ✓
- ROI eligibility requires actionable + price: 0 markets (nothing executable) ✓
- Every movement record identifies its market: [TOTALS] MIN@ATL, BOS@NYY, PIT@STL, PHI@LAA · [SPREAD_RL] GSV@POR, CON@DAL · [ML] KC@CLE, TEX@MIL ✓
- WNBA ML win+loss = 100% ✓ · ATL cover+push+noncover = 100.0 ✓ · half-point push = 0.0 ✓
- Post-decision re-verification cannot alter V1 fields (append-only lineage; V1 sha256 `2ab780f7…` frozen) ✓
- Clock: `entry_snapshot_cutoff` 04:12 ET / `decision_time` 08:15 ET — conservative stale-price test; no new market info recorded in between ✓

record_id: PREGAME-BOARD-2026-08-30-V6 · paper only · ledger $0 · wager authority NO