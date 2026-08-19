
## 2026-08-11
- 15-game slate cross-validated 4 ways; card built market-blind; 15 forecasts registered pre-board
- owner tier-1 board frozen (MLB 15g + WNBA 3g); 8/10 held games resolved; 10 grades + 10 results rows appended; ml_asof rebuilt
- overlay verdict: zero wagers (14/15 'positive EV' = compression artifact); gate 0/100, ledger $0
- MLV2 preregistered experiment run: 3 candidates (Platt recal, logit7, logit9+rest/form) vs frozen V13 -> NO_ADOPT on all frozen gates; binding constraint is discrimination, not calibration
## 2026-08-12
- 8/12: v1 card pre-board + v2 card with tier-1-confirmed starters, both registered pre-pitch (164 forecasts)
- 8/11 graded 15/15 winner-level from board arithmetic; MIL@SD provisional REVERSED by tier-1 (incident recorded); two-night ledger Brier 0.2515 ~ coin, per the discrimination finding
- boards frozen (MLB 15g low-hold composite + WNBA 3g spread/total); overlay verdict zero wagers

## STANDING DISPLAY RULE (owner, 2026-08-12)
- Every card response shows the FULL slate table — all games, all sports in scope — never a summary subset. Leans and flags are called out IN ADDITION to, not instead of, the complete table.
- WNBA MODEL BUILT: wnba.rs.ff7_logit_ridge.v1_0.shadow — preregistered, all 3 targets VALIDATED (Brier .2112 vs .2472 p_holm<1e-3, AUC .722, margin MAE 9.99 vs 11.41, total 14.16 vs 14.47); 3-game card coherence-gated and registered pre-tip
## 2026-08-13
- 8/12 fully graded tier-1 both sports: MLB v1 .2485/6-15, v2 .2470/6-15 (starter confirmation ~nil); V13 3-night ledger 40g .2492 ~ coin
- WNBA v1.0 FIRST PROSPECTIVE NIGHT: 3/3 sides, Brier .0603, margin MAE 6.5, total MAE 7.2; beat closing spread distance 2/3; n=3 non-evidence guard recorded; no retune
## 2026-08-19 (intake, 09:22Z board)
- 8/19 MLB owner slate ingested pre-start: 15 games/30 teams (franchise partition holds), only DET@PIT 16:35Z time transmitted; evidence sha c01e4ef0c21653a0
- ALL prices absent on the board -> slate state PRICE_DATA_BLOCKED: winner/margin/total generated BEFORE prices and registered (15 forecasts, chain 274/257 PASS); NO ML edge, EV, ATS bet, or total bet emitted; VSiN EST columns firewalled (never model input, never price substitute)
- unified card rows: all 15 trust_status=BLOCKED / blocked_reason=PRICE_DATA_BLOCKED, selection IDs null-with-reason
- unregistered starters recorded, not invented: Jackson Jobe (DET), AJ Smith-Shawver (ATL) -> CAP; both board classes PROJECTED so V14 forward stays idle (T-90 CONFIRMED only)
- 15:05Z starter/lineup refresh scheduled (T-90 before DET@PIT); later starter changes fork cohorts, never overwrite
- 8/19 WNBA dedup ruled: repeated capture = same 2 games, no second card; registered ATS lines grade primary; TOR +380 stays COMPRESSION_CONFLICT
- 09:57Z preview board: 26/30 starter slots named (ATH@KC TBA x2), all times transmitted -> v2 cohort forked (15 forecasts, chain 289/257 PASS); Stock side ambiguity resolved (NYM home); 5 unregistered starters CAP; Statcast career-vs-roster columns firewalled; class PROJECTED so V14 still idle; prices still absent -> PRICE_DATA_BLOCKED unchanged
