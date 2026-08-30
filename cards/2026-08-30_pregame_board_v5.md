# 2026-08-30 Pregame Board — V5 (market-specific probability fields; append-only, no decision changes)

Issued: 2026-08-30 16:05 ET · lineage V1 (08:15, registered, sha256 `2ab780f7…`) → V2 → V3 → V4 (3-market schema) → **V5 (market-specific probabilities)**
V5 adds the owner addendum: ML uses `model_win_pct`, SPREAD_RL uses `model_cover_pct`, TOTALS uses `model_over_pct`/`model_under_pct`, push probability shown when applicable (half-point lines → 0.0). No-vig market probabilities only; edges in percentage points; spec validation battery run clean (57/57 rows). JSON canonical: `2026-08-30_pregame_board_v5_canonical.json`.

**Legend:** M = model win% · C = model cover% · O/U = model over/under% · Mkt = market no-vig% · E = edge pp · P = push%

## WNBA

| Game | ML | Spread/RL | Totals | Movement | Game Decision | Note |
|---|---|---|---|---|---|---|
| MIN @ ATL | ATL +114 · M39.7 / Mkt44.9 · -5.2pp · PASS | ATL +2.5 · C64.2 / Mkt50.0 · +14.3pp · LEAN | line 176.5 · model% not supplied · NO_LINE | unknown 0.2 (179.5→176.5) | **LEAN** | Brionna Jones out (pre-open); ATL possible B2B - model blind; only edge surviving reverse checks |
| LAS @ SEA | SEA -105 · M56.1 / Mkt51.1 · +5.0pp · PASS | line -1.5 · p=N/A · PASS | line 172.5 · model% not supplied · NO_LINE | — | **PASS** | coin-flip zone with stale data |
| GSV @ POR | GSV -198 · M74.7 / Mkt63.7 · +11.0pp · PASS | line -4.5 · p=N/A · PASS | line 158.5 · model% not supplied · NO_LINE | new_information 0.8 (-5.5→-4.5) | **PASS** | scenario engine: full rotation .747 vs 3-out .53-.62; model and market agree post-adjustment |
| CON @ DAL | DAL -1050 · M83.3 / Mkt87.6 · -4.3pp · PASS | line -13.5 · p=N/A · PASS | line 166.5 · model% not supplied · NO_LINE | new_information 0.85 | **PASS** | no contrarian play against explained steam |

## MLB (actionable layer BLOCKED slate-wide — ML entries CLV_ONLY)

| Game | ML | Spread/RL | Totals | Movement | Game Decision | Note |
|---|---|---|---|---|---|---|
| MIA @ WSH | MIA -108 · p=N/A · CLV_ONLY | N/A · NO_LINE | line 9.0 · model% not supplied · NO_LINE | — | **PASS** | SP conflict RESOLVED V2 (Janson Junk) |
| COL @ ATL | ATL -224 · p=N/A · CLV_ONLY | N/A · NO_LINE | line 8.5 · model% not supplied · NO_LINE | — | **PASS** | ATL bullpen depleted (Suarez IL) |
| BOS @ NYY | BOS -115 · p=N/A · CLV_ONLY | N/A · NO_LINE | line 8.0 · model% not supplied · NO_LINE | unknown 0.2 (8.5→8.0) | **WAIT** | Story/Anthony lineup status; tot steam unexplained |
| SEA @ TOR | SEA -135 · p=N/A · CLV_ONLY | N/A · NO_LINE | line 8.0 · model% not supplied · NO_LINE | — | **PASS** | roof TBD |
| KC @ CLE | CLE -180 · p=N/A · CLV_ONLY | N/A · NO_LINE | line 7.5 · model% not supplied · NO_LINE | unknown 0.18 (-167→-180) | **PASS** | unexplained steam, not faded (audit clause) |
| LAD @ DET | LAD -166 · p=N/A · CLV_ONLY | N/A · NO_LINE | line 7.5 · model% not supplied · NO_LINE | — | **PASS** | stale-source total conflict quarantined (Doc's 9.0) |
| SD @ TB | TB -165 · p=N/A · CLV_ONLY | N/A · NO_LINE | line 7.5 · model% not supplied · NO_LINE | — | **PASS** | — |
| TEX @ MIL | MIL -162 · p=N/A · CLV_ONLY | N/A · NO_LINE | line 8.5 · model% not supplied · NO_LINE | unknown 0.22 (-173→-162) | **WAIT** | MIL SP unresolved (May 'could start') -> lineup card |
| CWS @ MIN | MIN -112 · p=N/A · CLV_ONLY | N/A · NO_LINE | line 8.5 · model% not supplied · NO_LINE | — | **WAIT** | Buxton day-to-day, projection CONFLICT |
| PIT @ STL | PIT -113 · p=N/A · CLV_ONLY | N/A · NO_LINE | line 8.0 · model% not supplied · NO_LINE | unknown 0.2 (8.5→8.0) | **PASS** | 90F noted |
| HOU @ NYM | NYM -119 · p=N/A · CLV_ONLY | N/A · NO_LINE | line 9.0 · model% not supplied · NO_LINE | — | **WAIT** | CONVERGENCE_FAIL posture stands; no new verified inputs |
| BAL @ ATH | BAL -148 · p=N/A · CLV_ONLY | N/A · NO_LINE | line 10.5 · model% not supplied · NO_LINE | — | **PASS** | — |
| PHI @ LAA | PHI -186 · p=N/A · CLV_ONLY | N/A · NO_LINE | line 8.0 · model% not supplied · NO_LINE | unknown 0.2 (8.5→8.0) | **PASS** | price+line both moved (true movement), no news match |
| CIN @ CHC | CHC -142 · p=N/A · CLV_ONLY | N/A · NO_LINE | line 9.0 · model% not supplied · NO_LINE | — | **WAIT** | Wrigley wind MISSING |
| ARI @ SF | N/A · NO_LINE | N/A · NO_LINE | N/A · NO_LINE | — | **BLOCKED** | absent from DK board; starters TBD; confirmed via schedule/board reconciliation |

## NFL / CFB

- **NFL: NO_FORECAST** — 53-man cutdown day; Week 1 opens Wed 9/9.
- **CFB early board** (EARLY_FORECAST · NOT FINAL): Miami@Stanford −21.5→−24.5 (unknown 0.25) · Coastal@WVU −17.5→−21.5 (unknown 0.20) · UCLA@Cal flip +1.5→−1.5 (unknown 0.22) · Clemson@LSU −10.5, tot 50.5→51.5 (new_info partial 0.5) · Baylor/Auburn −7 (σ=18.385) · SMU@FSU −2.5 (Jennings PROVISIONAL).

## Validation record

- 19 games × 3 markets; market names exactly {ML, SPREAD_RL, TOTALS} ✓
- All populated probabilities in [0,100]; ATL spread cover+push+noncover = 64.3+0.0+35.7 = 100.0 ✓
- NO_LINE markets carry no selection+line pair and no model probability ✓ (totals model point estimates, e.g. 176.6, are NOT probabilities → null per spec)
- Half-point lines → model_push_pct = 0.0 ✓; whole-line totals push pct null (no sim-derived push mass available — not invented)
- Game decision never more aggressive than most restrictive market ✓
- Disclosed exception (unchanged from V4): ATL +2.5 LEAN entry.price = null — line captured, spread price not in 04:12 relay; not invented (R1), not downgraded (V1 registered)

record_id: PREGAME-BOARD-2026-08-30-V5 · paper only · ledger $0 · wager authority NO