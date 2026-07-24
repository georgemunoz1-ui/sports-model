# PROGRESS JOURNAL (append-only; newest last; next session reads the tail)

## 2026-07-21 — harness bootstrap
- Session history to date: V11 frozen baseline honored -> V13 MC built -> park factors data-derived
  (1,505-final backfill) -> sides verdict DEAD at n=1461 (MC ~coin .2500/53%, GBM worse .2563) ->
  K-props validated in backtest (n=1759, calibrated, MAE 1.92) -> forward paper ledger opened.
- Today: built harness (AGENTS.md, state.json, healthcheck, runbook) per Anthropic/OpenAI
  harness-engineering articles. 7/21 K-prop card sent (4 paper plays: Rasmussen O4.5, Buehler O3.5
  full-weight; Perkins O4.5, Mikolas O2.5 half-weight). Grade scheduled 05:30Z.
- Caught-bug log: relief-outing TBF inflation in K projections (fixed: start-only). Keep R5 sharp.
- For next session: run postgame cycle for 7/21, then pregame 7/22. E1 (opponent-K%) is the queued
  experiment when there's capacity.

## 2026-07-22 (early) — DURABILITY INCIDENT + full harness live
- INCIDENT: container rollback silently erased the 7/19-20 grading turn's writes (results upsert,
  kprops engine, 7/21 card files). Healthcheck CAUGHT IT on first run. Repaired from conversation
  record: results.csv back to 1,505 finals (verified in separate process), kprops.py rebuilt and
  reproduces carded projections exactly (Rasmussen 5.41/Buehler 4.41/Perkins 5.83/Mikolas 3.75).
  New rule in force: git commit after EVERY write batch. Recommend a remote to Taco for true durability.
- HARNESS LIVE: AGENTS.md entry point, state.json (verdicts/ledgers/gates/experiment queue),
  healthcheck, runbook. Recurring tasks created: PREGAME daily 15:00 UTC (card -> Taco),
  POSTGAME daily 05:30 UTC (grade + dataset + ledger). Both fresh-session, bootstrap via AGENTS.md.
- Pending tonight: 4 kprop paper plays grade at next postgame fire (~05:35Z).

## 2026-07-22 (manual postgame, user-triggered)
- 7/21 graded: Rasmussen WIN (5K, proj 5.41 — nailed), Buehler LOSS (3K vs 4.41), Perkins LOSS (4K vs 4.5, near-miss), Mikolas VOID (gs=0, relief — book rules void no-start props). Day 1: 1-2-1V, -0.47u.
- 13 finals + 2 PPD (PIT@NYY, BAL@BOS -> likely 7/22 DHs) upserted; dataset 1518 finals. Pitcher logs appended (ER/BB placeholders noted).
- 05:30Z trigger will find work done; should no-op gracefully.

## 2026-07-22 (midday) — board priced
- Taco posted RotoWire K board + odds. 4 paper plays: Cole U6.5(-105), Singer U5.5(-144), Jump O4.5(+104), Bennett U5.5(-148, half). Pending in state.json.
- Detmers/Kremer overs correctly declined (prices pre-shaded steep toward our projections — E3 note).
- Starter changes vs morning probables: Lauer, Dobbins, Fried, Kay, Quantrill, Miles, Perez, Hughes.

## 2026-07-23 (manual postgame for 7/22)
- K-props day 2: Jump WIN (5K>4.5, +110), Bennett WIN (4K<5.5), Cole LOSS (11K!! vs proj 5.59 — biggest miss yet), Singer LOSS (6K vs 4.46). Day -0.56u; cumulative 3-4-1V, -1.03u (hand-math error caught+fixed, corrections entry); gate 7/100 (Mikolas VOID does not count).
- ML tracking day 1: 3-1 (MIL✓ BOS✓ KC✓ | SEA✗).
- Cole 11K vs proj 5.59 = 5.4K miss on a 19-start sample -> E1 (opponent-K%) escalated: PIT strikes out a LOT; opponent adjustment would have raised Cole's proj + possibly flipped the play. Priority experiment.
- Dataset 1,535 finals. Logs appended.

## 2026-07-23 (midday) — selection-logic fix + Sale registered
- Taco caught best-EV-first flaw: qualifying U7.5@HR quote masked by non-qualifying max-EV U6.5@FD. Engine gains select_play() (qualify-then-best). Sale U7.5 -145 HR 1.0u registered pre-pitch (E[K] 6.54, disp -0.96, edge +7pp). Official 7/23 engine card = Sale U7.5 + Seymour O4.5. Taco 5-play raw baseline unchanged, grades in parallel.

## 2026-07-23 (audit closeout, per Taco)
- Sale log corruption CONFIRMED (phantom rows) -> 6 logs re-fetched verbatim; Sale now 18GS/123SO/426TBF matching external EXACTLY (+ tonight's start). Other 5 flagged = legit openers, not corruption.
- Healthcheck gains log-integrity rule (dupe dates / consecutive >3IP starts). price_cli.py is now the mandated board->plays caller (wires select_play mechanically). progress gate-count corrected (7/100, voids excluded).

## 2026-07-23 (late) — reconciliation protocol adopted (Taco spec)
- StatMuse route VERIFIED fetchable; confirms Sale repair (5/20+5/28 real, 5/22+5/27 phantom; 123 K).
- Healthcheck: spacing now FLAGS for reconciliation (warn) instead of hard-fail; opener-aware; never auto-delete.
- Runbook: full repair protocol + quarantine rule + 8-field forward format (adds opponent).

## 2026-07-24 (postgame for 7/23)
- ENGINE K-props 1-1, -0.58u: Seymour O4.5 WIN (7K), Sale U7.5 LOSS (11K vs proj 6.54). Cumulative 4-5, -1.61u; gate 9/100.
- Sale 11K = SECOND straight day a premium-K arm beat our UNDER (Cole 11K 7/22), both disp<1.0. EPISTEMIC NOTE (Taco): this is NOT yet "book-info not book-error" — 2 misses reveal a PLAUSIBLE opponent-K% omission but are equally consistent with short-run clustering at n=2. E1 must improve the 1759-start replay before the opponent-K explanation earns causal status. Escalated to top for TESTING.
- TACO raw baseline 3-2, +0.48u vs engine -0.58u — but the divergence is subtler than "discipline too tight": the 4 plays the engine declined/skipped went 2-2 (Williams W, Dobnak W, Bradley L, McGreevy L) = -0.36u flat. Filters were NET-CORRECT (declining Bradley -153 juice + McGreevy no-disp AVOIDED 2 losses; only Williams was a true shrinkage-cost-a-winner, elite-K arm pulled 0.75->0.47). Baseline's profit came from the SHARED Seymour play (+0.84 full vs engine +0.42 half). Engine lost the night PURELY on its unique Sale play. A/B night-1 Brier raw 0.244 < shrunk 0.258 (n=4, noise).
- ML tracking 2-1 (MIN✓ +112 upset, ATL✓, STL✗). Cumulative 5-2. V13 dir 3-2 -> 21-12.
- Dataset: 1,539 finals (7/23 upserted; ARI@STL already present). Logs: 9 starts appended + Sale 7/23 placeholder corrected (3.2|7K -> 6.0|11K); Sale season now 19GS/134SO/450TBF = external EXACTLY.
- BUG: runbook 8-field forward log format crashes sp_asof (field[1] parsed as IP). Reverted to 7-field; parser needs opp-aware len==8 branch before adoption. Logged to known_issues.

## 2026-07-24 (E1 pre-registration + team-K snapshot)
- E1 PRE-REGISTERED (frozen): log5/odds-ratio opponent-K method + full reporting spec (6 metrics + complement slice) + adopt/gate/reject thresholds. docs/experiments/E1_opponent_k_prereg.md. Awaiting Taco threshold sign-off + per-game data fetch before confirmatory run.
- Taco uploaded 7/23 season team stats -> parsed to team K-rate-taken table (data/mlb/team_batting_asof/2026-07-23.json). League 22.7%. High-K(>=24%): LAA,CIN,PIT,BAL,NYY,CWS,PHI. Low-K: TB 19.4%, AZ 20.0%, TOR 20.1%.
- KEY pre-run diagnostic: E1 would REPAIR Cole (PIT high-K, play flips to no-play, avoids loss) but NOT Sale (SD league-avg rank 12, adj +0.09K, play still fires+loses). Only 1 of 2 anecdotes is an opponent-K case (Sale's SD opponent is league-average, so opponent-K barely moves his projection) -> the Sale miss is NOT an opponent-K case; its cause is not identified here. Feature must stand on broad replay merit, not these two games. (snapshot=look-ahead if used as historical feature; per-game fetch still required.)

## 2026-07-24 (E1 first replay run — SUPERSEDED; wrong population, see relabel + closure below)
- Pulled all 30 team hitting gamelogs (statsapi). BLOCKING reconciliation gate: all 30 terminal G/SO/AB/BB matched the 7/23 snapshot EXACTLY (caught+fixed SD + LAA transcription errors via the gate; ignored the model's wrong self-reported sums, parsed raw arrays locally per Taco).
- Froze replay table: 2659 starts (as-of pitcher shrunk K-rate x opponent log5, o=SigmaSO/Sigma(AB+BB), N0=200, strict date<D, DH=start-of-day; 24 quarantined, never league-avg-subbed). Fixed a pipe-delimited starters.csv join bug (was resolving only 129/2659 -> 2659/2659).
- [SUPERSEDED — this run scored the WRONG 2659 population; VOID per red-gate]. Overall ΔMAE +0.004K; interaction cell -0.108K; complement +0.005; NLL 2.232 vs 2.234, slope 0.998. Bounded reading only: E1-as-specified showed no material incremental value on that (wrong) sample; NO causal claim about the Cole/Sale misses (cause UNEXPLAINED). Projections UNCHANGED. See E1_confirmatory_closure.md.
- Pre-registration vindicated: the sliced view shows a naive "fix the recent misses" would have DEGRADED exactly those matchups. R7 discipline paid off.

## 2026-07-24 (E1 PAIRED correction — Taco red-gate)
- Taco red-gate: the confirmatory replay must be PAIRED on the experiment-of-record (n=1759, engine-eligible), not a fresh 2659 sample. The 2659 score included n_prior 1-4 pitchers the engine's proj() refuses (<5 GS -> None). VOID.
- Reconstructed paired population: engine-eligible n_prior>=5, horizon <=7/19, row_id=pid|gamePk. 1757 starts (vs recorded 1759: -2 from Sale phantom-row repair). 1757 unique ids==count; 0 quarantined-in-pop. Baseline projection identical row-for-row; E1 adds only opponent term.
- Resolver fixes to hit 0 quarantine: full-team-name canon gap in results.csv (backfill used "Pittsburgh Pirates", upserts used codes); same-opponent-DH handling (Yamamoto/Schlittler 7/19 LAD@NYY DH). Chandler/Ashcraft resolved via pitcher-team+results fallback.
- PAIRED RESULT [later relabeled EXPLORATORY, NOT confirmatory]: overall ΔMAE +0.011K (<0.03 materiality); interaction cell -0.037K; complement +0.011; NLL 2.230 vs 2.236, slope 1.009. Bounded conclusion: no material incremental value on the observed sample. Projections UNCHANGED.

## 2026-07-24 (E1 confirmatory CLOSED unrecoverable; 1757 relabeled EXPLORATORY — Taco red-gate #2)
- Searched git history (all commits + all blobs), filesystem rowcount scan, backup bundles, and the session transcript for the original 1759 row set / population hash. NONE exists: the 2026-07-18 backtest appended to ANONYMOUS parallel arrays (no pid/gamePk/date captured), printed summary stats only, ran with NO date horizon on the 7/18-vintage logs. The 1759 row IDs are PERMANENTLY UNRECOVERABLE -> original confirmatory replay CLOSED. docs/experiments/E1_confirmatory_closure.md.
- MAE drift 1.92 -> 1.849 is a population/VINTAGE difference (7/18 no-horizon ~310 logs vs 7/24 <=7/19 corrected+grown logs), NOT the removal of 2 Sale starts. Taco correct that a 2-row edit can't move MAE that far.
- RELABEL (4 corrections): (1) 1757 run = EXPLORATORY corrected-population sensitivity, NOT confirmatory. (2) E1 status = NO-PROMOTE / CONFIRMATORY INDETERMINATE. (3) retracted "2 Sale starts explain the drift" -> vintage/horizon/population. (4) retracted the earlier variance attribution for the Cole/Sale misses -> bounded conclusion is ONLY that E1-as-specified showed no material incremental value on the observed sample; the misses' cause is UNEXPLAINED. The 1757 rows are burned for confirmatory reuse; any E1-R needs a pre-registered FORWARD holdout.
- DH provenance fixed factually (not manufactured): fetched Yamamoto (808967) + Schlittler (693645) gamelogs -> both 7/19 = gamePk 823523.
- ENGINE UNCHANGED: no opponent-K term, no ledger/authorization changes ($0, gate 9/100).

## 2026-07-24 (recordkeeping safeguards + E3 sequenced — Taco conceptual sign-off)
- Purged retracted verdict/causal language (E1 'REJECT'-style verdicts, opponent-K no-signal claims, and the Cole/Sale variance attribution) from the LIVING record (progress.md E1 entries, state.json). Historical commit messages d093279 / 5f12da1 left immutable but formally SUPERSEDED via ERRATA in E1_1757_audit.md — rewriting published history is itself an audit-trail alteration and inconsistent with this project's anti-history-rewrite rule.
- AUDIT record for the EXPLORATORY 1757 dataset (exploratory != unaudited): docs/experiments/E1_1757_audit.md — sha256 e1_score_pop.csv=56092b40..., construction table=0dd2e6a9..., scoring-code commits (e1_replay/e1_data @0a520c7, e1_score @5f12da1, dataset frozen @1a644b4), transcript path, DH evidence (Yamamoto 808967 + Schlittler 693645, both 7/19 = gamePk 823523 via gamelog fetch).
- E-QUEUE RESEQUENCED: E3 (prop line-move CLV) is NEXT, BEFORE E2 (neg-binomial tails). E3 directly tests the unresolved book-info question (does market movement carry info missing from the projection?) with NO engine change; E2 addresses tail quality but not the Cole/Sale hypothesis.
- FINAL STATUSES LOCKED: original 1759 replay UNRECOVERABLE; 1757 run EXPLORATORY sensitivity only; production NO PROMOTION; confirmatory E1 INDETERMINATE; Cole/Sale cause UNEXPLAINED; future confirmation = untouched forward holdout.

## 2026-07-24 (pregame card + accent-cap fix)
- 7/24 full-tracking card (15 games, display-only: sides DEAD, totals NOT_READY, no K board -> no plays). Real gamePks captured.
- ENGINE FIX: daily_card pitcher-name lookup was accent-SENSITIVE -> "Jesus Luzardo" (slate) missed "Jesús Luzardo" (DB), silently capping an established arm to league-average. Made IDS lookup accent-insensitive (unicodedata strip). Verified: non-accented slate now resolves Luzardo (6.88) + Márquez (3.77).
- Correction: NYY@PHI ⚠ was Luzardo (accent), not Schlittler; the cap suppressed the TOTAL (projT 8.7->8.1) but NOT the win% -> NYY 61% flip HOLDS at full trust. KC@DET ⚠ is Beck Way (KC rookie, 0 GS), not Skubal (14 GS, resolved). ml_tracking NYY note -> full-trust.
- 3 ML tracking pending (NYY/ATL/SEA) + 15 V13 directional to grade tonight on finals.
