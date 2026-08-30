# 2026-08-30 Pregame Board — FORECAST_V1 (registered, do not overwrite)

Issued: 2026-08-30 08:15 ET / 05:15 PDT · Information cutoff: 2026-08-30 ~04:35 ET (market), 08-29/30 (news)
Paper only · wager authority NO · ledger $0 · DK_RELAY ids unbindable (descriptive)
Governance: model-first (market firewalled from inputs) · merged P0 freshness rules · CARD_UPDATE_PROTOCOL applies to tonight's update

## SLATE (verified independently of sportsbooks)
- WNBA: 4 games — MIN@ATL 3:00p, LAS@SEA 5:00p, GSV@POR 7:00p, CON@DAL 8:30p ET
- MLB: 15 games (14 + ARI@SF found in market reconciliation — no game dropped)
- NFL: NO_GAMES (53-man cutdown day; preseason ended 8/29; Week 1 opens Wed 9/9)
- CFB: not active today — separated EARLY board below (Sep 3+)

## WNBA — MODEL-FIRST FORECASTS
Model: wnba.rs.ff7_logit_ridge.v1_0.shadow (walk-forward brier 0.2112, AUC 0.722)
Feature cutoff: ET 2026-08-27 — **DATA_STALE, missing 8/28–8/29 results incl. slate-team fatigue inputs**
Coherence: all 4 PASS (|p_home − Φ(margin/13.97)| ≤ 5pp)

| Game | p_home | p_away | Model margin (home) | Model total | Data quality |
|---|---|---|---|---|---|
| MIN@ATL | 0.397 | 0.603 | ATL −2.6 | 176.6 | DATA_STALE |
| LAS@SEA | 0.561 | 0.439 | SEA +2.6 | 175.6 | DATA_STALE |
| GSV@POR | 0.254 | 0.746 | GSV −8.1 | 166.0 | DATA_STALE + unresolved rotation |
| CON@DAL | 0.833 | 0.167 | DAL +11.4 | 171.2 | DATA_STALE |

## WNBA — OVERLAY & CLASSIFICATION (market: DK via ESPN, captured 04:12 ET)
| Game | Market | Model | Displacement | Reverse check | Decision |
|---|---|---|---|---|---|
| MIN@ATL | MIN -2.5, tot 176.5, ATL +114 | ATL -2.6, tot 176.6 | ~5.1 pts toward ATL; total aligned | ATL possibly on 8/29 B2B (date CONFLICT unresolved) — model blind to it; Brionna Jones out is in neither. Disagreement partially explainable by stale fatigue input. | **LEAN ATL +2.5 (low confidence, C-tier)** |
| LAS@SEA | SEA -1.5, tot 172.5 | SEA +2.6, tot 175.6 | ~1 pt | No edge; p near 0.5 with stale data | **PASS** |
| GSV@POR | GSV -4.5 (from -5.5), tot 158.5 | GSV -8.1, tot 166.0 | ~3.6 pts model over values GSV | GSV loses 3 starters to World Cup TODAY — model cutoff 8/27 structurally cannot see it; market move toward POR is that information. Model edge invalid. | **PASS (model invalidated by post-cutoff news)** |
| CON@DAL | DAL -13.5 (from -9.5), tot 166.5 | DAL +11.4, tot 171.2 | ~2.1 pts toward CON | Steam -9.5→-13.5 IS the Griner-out + CON B2B + departures information arriving; model blind to all three. Contrarian edge rejected. | **PASS** |

## MLB — CLASSIFICATION (15 games)
Actionable layer: **BLOCKED slate-wide** — zero SP_CONFIRMED anywhere (all SP_PROBABLE per listings, no official announcements); pitcher feature corpus ends 2026-07-19 (stale by construction); every starter slot routes to the registered CAP under merged P0 rules. No V13 actionable forecast is legitimate today.
Forecast-only (descriptive, near-prior, accruing nothing): available on request; not carded.
| Game | Status | Reason |
|---|---|---|
| MIA@WSH | WAIT | SP CONFLICT (Junk vs Phillips) — rerun on official announcement |
| COL@ATL | PASS | SP_PROBABLE only; ATL bullpen depleted (Suarez IL) but no actionable model input |
| BOS@NYY | WAIT | Story/Anthony reinstatement today — lineup impact unresolved; total steamed 8.5→8 |
| SEA@TOR | PASS | SP_PROBABLE; roof TBD |
| KC@CLE | PASS | CLE ML steamed -167→-180 with no model visibility into why — audit clause: no bet against unexplained steam |
| LAD@DET | PASS | Total conflict 7.5 vs 9 (stale source); SP_PROBABLE |
| SD@TB | PASS | SP_PROBABLE; no edge basis |
| TEX@MIL | WAIT | MIL SP UNRESOLVED (May "could start" per mgr) — rerun on lineup card |
| CWS@MIN | WAIT | Buxton day-to-day, projection CONFLICT — monitor |
| PIT@STL | PASS | SP_PROBABLE; 90°F noted |
| HOU@NYM | WAIT | Start-time conflict unresolved; HOU@NYM was a CONVERGENCE_FAIL refusal yesterday — no new verified inputs since |
| BAL@ATH | PASS | SP_PROBABLE |
| PHI@LAA | PASS | Total steamed 8.5→8; no model visibility |
| CIN@CHC | WAIT | Wind direction MISSING at Wrigley + start-time conflict |
| ARI@SF | **BLOCKED** | No line found on any checked book; starters TBD; game confirmed via schedule/board reconciliation |

## NFL
**NO_FORECAST (registered scope)** — no competition scheduled (cutdown day). Silence with reasons, by rule.

## CFB EARLY BOARD — Sep 3+ (EARLY_FORECAST — NOT FINAL; separated from active slate)
Full market snapshot + intel captured (BetIQ consensus 8/30; BetOnline openers 5/26). Most interesting early discrepancies to track OPEN→CURRENT→CLOSE:
- Miami (FL) @ Stanford: steamed -21.5→-24.5 (Mensah vs turnover-prone Warren) — model prep flags QB mismatch; watch if it crosses -26.
- West Virginia -17.5→-21.5 vs Coastal Carolina — largest steam on board; no model confirmation yet.
- UCLA @ California: flipped +1.5→-1.5 — full 3pt swing; watch for buyback.
- Clemson @ LSU: -10.5 stable after round-trip; total 50.5→51.5 steamed. Kiffin/Leavitt vs new-OC Clemson (Vizzina PROVISIONAL) — highest-information Week 1 game.
- Baylor vs Auburn (ATL): -7→-7.5; two transfer-QB regimes (Lagway vs Brown) — uncertainty elevated per Week-1 protocol.
- SMU @ FSU (Mon): SMU -2.5 stable at key number; Jennings finger "100%" per coach — PROVISIONAL.
Week-1 σ=18.385 applies; all roster-turnover games carry inflated uncertainty. Rerun closer to game day after depth charts/injuries/QB announcements refresh.

## PARLAY ANALYSIS
No straight bet above C-tier exists today → **no parlay constructed**. Standards not weakened to manufacture one.

## INFORMATION-WATCH LIST (rerun triggers)
| Game | Missing | Why it matters | Trigger |
|---|---|---|---|
| MIA@WSH | Official SP | Junk/Phillips conflict | Team announcement |
| TEX@MIL | MIL lineup card | May "could start" | Card posted (~12:10 ET) |
| CWS@MIN | Buxton status | Projection conflict | Lineup card |
| CIN@CHC | Wind direction + time | Wrigley totals sensitivity | Updated forecast/lineup |
| BOS@NYY | Story/Anthony lineup status | Offense shift | Lineup card |
| MIN@ATL | ATL 8/29 result (B2B?) | Fatigue input for the one LEAN | Box score confirmation |
| All MLB | Confirmed lineups | Cards post ~2h pre-pitch | Postings begin ~10:15 ET |
| All WNBA | Game-day injury PDF + starters | GTDs (Cannon, Nelson-Ododa, Samuelson) | WNBA PDF / ~30-60min pre-tip |

## DATA-INTEGRITY AUDIT (pre-publish, per spec §15)
- Schedule/board reconciliation: **1 discrepancy found and resolved** — ARI@SF present on schedule authorities, absent from DK board → BLOCKED, not dropped. ✅
- Start-time conflicts unresolved: HOU@NYM (3:00 vs 3:10), CIN@CHC (7:00 vs 7:20) — reported, not guessed. ✅
- SP conflict: MIA (Junk vs Phillips) — reported. ✅ No stale starter minted as confirmation anywhere. ✅
- Market firewall: no market number entered any model input; overlay ran only after forecasts registered. ✅
- Model version: single WNBA model id recorded; no version mismatch. ✅
- DATA_STALE disclosed on every WNBA forecast (cutoff 8/27). ✅
- No prediction generated after game start (issued 08:15 ET; first pitch 12:15 ET). ✅
- RJ-005 injury availability remains egress-blocked system-side → scraped availability graded IDENTIFIED_UNCONFIRMED; confidence capped accordingly. ✅

## END-OF-PREP SUMMARY
- **BEST WNBA:** LEAN ATL +2.5 (C-tier, low confidence) — the only edge surviving reverse checks. Everything else PASS.
- **BEST MLB:** none actionable (BLOCKED layer); watch list above.
- **BEST NFL:** no games.
- **BEST OVERALL:** ATL +2.5 lean is the entire board. This is a thin card by design — the goal was the cleanest prospective set, not the most bets.
- **PASSES of note:** GSV@POR and CON@DAL — nominal model edges correctly rejected because post-cutoff roster news explains the market move.
- **MODEL HEALTH:** 1 schedule/board discrepancy (resolved), 3 time/SP conflicts (reported), systemic DATA_STALE on WNBA (2 days), MLB actionable layer blocked by stale corpus + zero SP confirmations, RJ-005 still egress-blocked.

record_id: PREGAME-BOARD-2026-08-30-V1 · append-only · V2+ permitted on legitimate new pregame info with reason logged
