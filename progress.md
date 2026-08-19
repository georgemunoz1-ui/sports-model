
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
- 10:05Z owner price capture (MLB best-odds ML/RL/totals + 26-pitcher K board x5 books + WNBA odds) ingested; owner EV screen reproduced exactly on frozen v2 (one SD sign conflict flagged, owner quote governs); verified array replay produced O/P/U + cover probs at captured lines; 15 price-evaluation lines appended to unified card; frozen 5pp gate fires DET/LAA/COL/AZ/STL/ATH mechanically, owner dispositions govern where stamped; SD+128/NYM+120 both-sides-plus -> executability audit; starter conflicts (CWS 3-source, SF, ATH) keep those rows BLOCKED pending T-90; K splits diagnostic only (kprops gate 0/100); WNBA 10:05Z prices = secondary execution observations, registered lines grade primary; BETTING OUTPUT ZERO
- SD sign correction (owner re-inspected pixels): SD is -128, owner's +128 text withdrawn -> BOTH_SIDES_PLUS audit + apparent arb withdrawn (normal 1.6% overround), SD off the positive screen, NYM +120 stays PRICE_SENSITIVE only; WSH/MIA relabeled AUDIT_REQUIRED—DIRECTION_FLIP; append-only supersession (bb97de7 unedited); STANDING RULE: captured source pixels govern over any derived/transcribed quote, owner's or assistant's
- TOTALS REPORT INCIDENT (mine): 10:05Z-turn chat table asserted four O/P/U rows no replay produced (push mass on half lines = the tell); committed artifacts verified clean and identical to a fresh certification replay; owner's totals gate implemented in unified_card (half-line push==0, exact count partition, per-quote quote_id, no split-line collapsing, sim-array sha binding) + incident-case selftest; quarantine imposed and RESOLVED with certification lines appended; WNBA display convention fixed (margin vs fair spread never blended); standing rule: report-layer numbers are R1-bound to tool-produced artifacts
- 15:05Z scheduled T-90 refresh executed: no new owner board since 10:05Z; acquisition 403 both targets (not routed around); no CONFIRMED capture -> V14 idle (DET@PIT excluded+counted), CWS/SF/ATH stay BLOCKED, no v3 fork (absence of information is not a starter change); preflight price-path tooling gap noted (10:05Z evidence capture satisfied screening at T-6.5h); re-armed 16:50Z
- 16:50Z refresh: still no owner board since 10:05Z; acquisition 403 x2; CWS@CHC T-90 MISSED -> stays BLOCKED through first pitch (starter attribution lands at settlement, never a retro card edit); V14 excludes-and-counts every passing game (zero eligible today so far); next check 22:10Z
