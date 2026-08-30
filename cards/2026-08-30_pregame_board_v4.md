# 2026-08-30 Pregame Board — V4 (strict 3-market card format; append-only, no decision changes)

Issued: 2026-08-30 15:45 ET · lineage V1 (08:15, registered, sha256 `2ab780f7…`) → V2 (13:40) → V3 (14:30) → **V4 (format upgrade)**
V4 re-renders the frozen V1 decisions in the owner-supplied Decision-State Card Formatter schema: exactly three independent market records per game (ML / SPREAD_RL / TOTALS), JSON canonical (`2026-08-30_pregame_board_v4_canonical.json`), table generated from JSON. No probabilities recalculated; no decisions changed; decision precedence NO_FORECAST/BLOCKED > CLV_ONLY > WAIT > PASS > LEAN > PLAY.

## WNBA

| Game | ML | Spread/RL | Totals | Movement | Game Decision | Note |
|---|---|---|---|---|---|---|
| MIN @ ATL | ATL 114; p=0.397/0.449/-5.2pp; PASS | ATL +2.5 2.5; p=0.642/0.500/+14.3pp; LEAN | 176.5; NO_LINE | unknown 0.2 (179.5→176.5) | **LEAN** | Brionna Jones out (pre-open); ATL possible B2B - model blind; only edge surviving reverse checks |
| LAS @ SEA | SEA -105; p=0.561/0.511/+5.0pp; PASS | -1.5; p=N/A; PASS | 172.5; NO_LINE | — | **PASS** | coin-flip zone with stale data |
| GSV @ POR | GSV -198; p=0.747/0.637/+11.0pp; PASS | -4.5; p=N/A; PASS | 158.5; NO_LINE | new_information 0.8 (-5.5→-4.5) | **PASS** | scenario engine: full rotation .747 vs 3-out .53-.62; model and market agree post-adjustment |
| CON @ DAL | DAL -1050; p=0.833/0.876/-4.3pp; PASS | -13.5; p=N/A; PASS | 166.5; NO_LINE | new_information 0.85 | **PASS** | no contrarian play against explained steam |

## MLB (actionable layer BLOCKED slate-wide — ML entries CLV_ONLY)

| Game | ML | Spread/RL | Totals | Movement | Game Decision | Note |
|---|---|---|---|---|---|---|
| MIA @ WSH | MIA -108; p=N/A; CLV_ONLY | N/A · NO_LINE | 9.0; NO_LINE | — | **PASS** | SP conflict RESOLVED V2 (Janson Junk) |
| COL @ ATL | ATL -224; p=N/A; CLV_ONLY | N/A · NO_LINE | 8.5; NO_LINE | — | **PASS** | ATL bullpen depleted (Suarez IL) |
| BOS @ NYY | BOS -115; p=N/A; CLV_ONLY | N/A · NO_LINE | 8.0; NO_LINE | unknown 0.2 (8.5→8.0) | **WAIT** | Story/Anthony lineup status; tot steam unexplained |
| SEA @ TOR | SEA -135; p=N/A; CLV_ONLY | N/A · NO_LINE | 8.0; NO_LINE | — | **PASS** | roof TBD |
| KC @ CLE | CLE -180; p=N/A; CLV_ONLY | N/A · NO_LINE | 7.5; NO_LINE | unknown 0.18 (-167→-180) | **PASS** | unexplained steam, not faded (audit clause) |
| LAD @ DET | LAD -166; p=N/A; CLV_ONLY | N/A · NO_LINE | 7.5; NO_LINE | — | **PASS** | stale-source total conflict quarantined (Doc's 9.0) |
| SD @ TB | TB -165; p=N/A; CLV_ONLY | N/A · NO_LINE | 7.5; NO_LINE | — | **PASS** | — |
| TEX @ MIL | MIL -162; p=N/A; CLV_ONLY | N/A · NO_LINE | 8.5; NO_LINE | unknown 0.22 (-173→-162) | **WAIT** | MIL SP unresolved (May 'could start') -> lineup card |
| CWS @ MIN | MIN -112; p=N/A; CLV_ONLY | N/A · NO_LINE | 8.5; NO_LINE | — | **WAIT** | Buxton day-to-day, projection CONFLICT |
| PIT @ STL | PIT -113; p=N/A; CLV_ONLY | N/A · NO_LINE | 8.0; NO_LINE | unknown 0.2 (8.5→8.0) | **PASS** | 90F noted |
| HOU @ NYM | NYM -119; p=N/A; CLV_ONLY | N/A · NO_LINE | 9.0; NO_LINE | — | **WAIT** | CONVERGENCE_FAIL posture stands; no new verified inputs |
| BAL @ ATH | BAL -148; p=N/A; CLV_ONLY | N/A · NO_LINE | 10.5; NO_LINE | — | **PASS** | — |
| PHI @ LAA | PHI -186; p=N/A; CLV_ONLY | N/A · NO_LINE | 8.0; NO_LINE | unknown 0.2 (8.5→8.0) | **PASS** | price+line both moved (true movement), no news match |
| CIN @ CHC | CHC -142; p=N/A; CLV_ONLY | N/A · NO_LINE | 9.0; NO_LINE | — | **WAIT** | Wrigley wind MISSING |
| ARI @ SF | N/A · NO_LINE | N/A · NO_LINE | N/A · NO_LINE | — | **BLOCKED** | absent from DK board; starters TBD; confirmed via schedule/board reconciliation |

## NFL / CFB

- **NFL: NO_FORECAST** — 53-man cutdown day; Week 1 opens Wed 9/9.
- **CFB early board** (EARLY_FORECAST · NOT FINAL): Miami@Stanford −21.5→−24.5 (unknown 0.25) · Coastal@WVU −17.5→−21.5 (unknown 0.20) · UCLA@Cal flip +1.5→−1.5 (unknown 0.22) · Clemson@LSU −10.5, tot 50.5→51.5 (new_info partial 0.5) · Baylor/Auburn −7 (σ=18.385) · SMU@FSU −2.5 (Jennings PROVISIONAL).

## Validation record

- 19 games × 3 markets = 57 market rows; every game has exactly {ML, SPREAD_RL, TOTALS}. ✅
- Decision counts: LEAN 1 · PASS 7 · CLV_ONLY 14 · NO_LINE 35. No game decision is more aggressive than its most restrictive market status. ✅
- **One disclosed schema exception:** ATL +2.5 LEAN carries `entry.price_american = null` — the 04:12 ET relay captured the line but not the spread price. V4 cannot invent it (R1) and cannot downgrade the registered V1 lean; recorded here as a known gap for tonight's sweep.
- Missing markets are explicit NO_LINE (e.g., all MLB run lines), never silently dropped. ✅

record_id: PREGAME-BOARD-2026-08-30-V4 · paper only · ledger $0 · wager authority NO