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

## 2026-07-25 — 7/24 board sourced + priced (SHADOW), 7/24 graded
**Request:** "Get odds for ML, RL and Totals. Search for Pitcher K props as well for 7/24. Then run
information via model."

- **ML/RL/Totals 7/24:** already captured pre-lock from Taco's board → `data/mlb/odds/2026-07-24_pregame.json`
  (15 games, ML + total + over/under juice + runline both sides). No gap to fill.
- **K props 7/24:** sourced 20 arms w/ real stated prices from three editorial sources (oddsindex,
  VSiN, DK Network) → `data/mlb/props/2026-07-24_kboard.json`. RotoBaller premium is a JS shell
  (unfetchable, consistent with the RotoWire finding of 7/22). **No sportsbook attribution** available;
  cross-source spreads are real (Jared Jones O5.5 at +106 / +110 / -103). Unpriced sides recorded as
  `null`, never inferred (R1).
- **TIMING / INTEGRITY:** board was captured 2026-07-25 ~01:30 ET — **after** every 7/24 game was final.
  Retroactive plays are result-contaminated. Added `harness/shadow_price.py`: calls the same canonical
  `kprops.price_board()` but writes NOTHING to state.json. Result: **1 of 20 arms qualified**
  (Skubal UNDER 8.5 @-140, disp -1.84 → R5 audit). Actual 12 K → would have LOST (-1.00u hypothetical).
  Logged under new `ledgers.kprops_shadow`. **Paper ledger unchanged 4-5 / -1.61u; gate stays 9/100.**
- **ENGINE FIX:** `engine/kprops.py` `_ids()`/`proj()` now accent-normalize (`_norm`) — same defect class
  as daily_card.py @10596a3. A board saying "Jesus Luzardo" previously returned "skip: no log" for
  "Jesús Luzardo". Self-test still PASS.
- **7/24 grading** (`harness/grade_0724.py`, all arithmetic computed):
  - ML directional tracking **2-1, +1.12u** (NYY +112 W on a 1-0 shutout at full trust, ATL +100 W,
    SEA -120 L). Record **5-2 → 7-3**.
  - V13 sides **8-7** → **21-12 → 29-19**. Road leans 4-1, home-chalk leans 4-6 (one slate; no inference).
  - V13 total leans **5-7**, 3 no-lean. Totals remain NOT_READY.
  - K projection on the board: **n=18, MAE 2.52 vs naive-4.6 MAE 2.66** — barely beats a constant.
- **HYPOTHESIS-GENERATING ONLY (not a finding):** the 5 largest under-projections were all deep high-K
  starts (Skubal 12, Schlittler 12, Sasaki 9, Yesavage 9, Luzardo 9); the largest over-projections were
  short outings (Arrighetti 1.0 IP/0K, Miller 5.1 IP/0K). Candidate mechanism = **E[TBF] shrinkage
  toward 24 compressing workhorse starts** — distinct from E1's opponent-K term. Generated AFTER seeing
  results, so it cannot be tested on them; any test needs R7 pre-registration against an untouched
  future holdout. **No engine change made.** E3 (prop line-move CLV) remains the next experiment.

### 2026-07-25 (02:15 ET) — 7/25 card built; ML tracking rebuilt as a pre-registered EV ledger

- **Slate + lines.** 15 games pulled from statsapi (`data/mlb/slates/2026-07-25.psv`). Full ML/RL/Totals
  board from covers.com → `data/mlb/odds/2026-07-25_pregame.json`, explicitly labeled **OPENING/EARLY**
  (captured 05:50Z, ~11h before the 17:10Z first pitch). ESPN served cached 7/12 data, RotoWire is a JS
  shell, sportsbookreview showed 7/23, vegasinsider and dimers showed 7/24, oddsshark is
  `ROBOTS_DISALLOWED` (no bypass attempted). covers was the only full 7/25 board — **single source, no
  book attribution.**
- **Card.** `harness/build_card_0725.py` → `cards/2026-07-25_card.html`. Every figure is computed from
  `cards/2026-07-25_card.json`; nothing hand-typed. Verified programmatically (all 15 games present, all
  ML strings and V13 percentages match source, no capped game registered, EV recomputed independently):
  **PASS**.
- **No 7/25 K board exists yet** at 02:15 ET. Per R1 the card carries **zero prop plays** — projections
  only. Cease **8.14** is the highest E[K] this engine has produced on any priced slate (36.9 K%, 17 GS).
- **`ml_tracking` FROZEN at 7-3, superseded.** Its selection rule was "V13 directional lean + my
  discretion," which is not an EV rule and was never written down in advance; the 7-3 therefore measures
  an unspecified process and cannot be honestly extended. Rows kept as history, not deleted.
- **NEW `ml_ev_tracking`, rule pre-registered 06:20Z — before the 17:10Z first pitch (R7).** Mechanical:
  (1) compute V13 P(win) for BOTH sides of every game; (2) qualify iff `EV>0 AND edge>=0.04` — the same
  thresholds `select_play` already uses, not tuned for this ledger; (3) exclude capped games (starter TBD
  or <5 GS), logging the exclusion; (4) register every qualifier, no discretion; (5) freeze the opening
  price, capture close separately for CLV.
- **7/25 qualifiers (3 of 30 sides): COL +186 (p .462, edge +11.2%, EV +.321), KC +154 (p .466, edge
  +7.2%, EV +.184), STL −116 (p .592, edge +5.5%, EV +.102).** Two of the three are sides V13 expects to
  **lose more often than win** — they qualify purely on price. This is the objective function behaving as
  specified: **+EV vs break-even, not win% > 50%.** Expect this ledger's W-L to look mediocre while
  performing well; units and CLV are the readouts.
- **Excluded by rule 3 and logged, not hidden:** ATH +144 (EV +.139) — MIN starter TBD *and* Mason
  Barnett has no start log. Recording it makes the cost of the trust rule measurable.
- **Open data problems carried on the card, not buried:** TOR@BOS run-line side labels look inverted at
  source (UNVERIFIED); CHC@PIT price conflict between covers' board (+116/−128, 8.0) and covers' own
  matchup page (+112/−102, 7.5), unreconciled; ATH@MIN total 10.5 is a 1.5-run outlier; **7/24 pitcher
  logs still unbackfilled** (boxscore extraction was mixing `seasonStats` into game stats — skipped
  rather than injecting unverified numbers; no effect on 7/25 since no pitcher starts on consecutive days).
- Sides still DEAD, totals still NOT_READY, K-prop paper ledger unchanged at **4-5 / −1.61u, gate 9/100**,
  $0 real money, unauthorized.

### 2026-07-25 (02:40 ET) — multi-book K LINE board received (no prices); engine externally validated

- Taco supplied a screenshot of a 5-book strikeout table (DK / FD / MGM / BetRivers / Caesars), 27 arms.
  Row set cross-checks exactly: 30 slate starters − PHI TBD − MIN TBD − Barnett (no log) = 27.
- **No prices.** The Under/Over columns rendered as book icons. Transcribed lines only →
  `data/mlb/props/2026-07-25_klines.json` with **every quote null**. Ran the canonical engine on it via
  `shadow_price.py`: **0 of 27 qualified, by construction.** R1 held mechanically, not by discipline.
- **Column-semantics diagnostic (the important finding).** Mean signed displacement (E[K] − line):
  DK −1.44, FD −1.23, CZR −1.27, MGM −0.61, **BR −0.11**; MAE 1.44 / 1.33 / 1.29 / 0.86 / **0.49**.
  DK, FD and CZR post ≥7.5 K lines on Andre Pallante (16.9 K%), Bryce Elder (19.8 K%) and Tanner Bibee
  (19.0 K%). No book prices a 16.9 K% starter at 8.5. **Those columns are an alt-line ladder, not five
  quotes on one bet.** Only BetRivers behaves like a main line.
- **NEAR MISS, recorded although it did not happen:** ingesting the board naively would have manufactured
  **11 fake R5-level UNDER edges** (Pallante −4.36, Burke −3.73, Elder −3.64, Brown −3.16, Skenes −3.11 …)
  purely by comparing projections against alt lines. The qualify-then-best selector would have taken the
  fattest of them. Same failure family as the WSH 813-vs-858 extraction error: the number looked like a
  signal and was an artifact of the source.
- **ENGINE VALIDATION:** against the BR column the engine sits at **MAE 0.49 K over 24 arms**, built with
  no knowledge of this board. First external multi-book check the K engine has had. This is a *calibration*
  signal, not a profitability one — agreeing with the market is how you confirm the model is sane and also
  exactly how you make no money. Edge lives in the 4 arms where it disagrees.
- **Watchlist vs BR (|disp| ≥ 0.8, the engine's own gate):** Robbie Ray U6.5 (E[K] 4.73, −1.77, R5),
  Paul Skenes U7.5 (6.39, −1.11), Foster Griffin O4.5 (5.51, +1.01), Bryan Woo U6.5 (5.67, −0.83).
  All four are **unplayable until a real price exists.**
- Greene (3 GS), Bratt (2 GS) and Sears (4 GS) fall under the 5-GS floor — no projection, correctly skipped.
- Ledger unchanged 4-5 / −1.61u, gate 9/100, $0 real money.

### 2026-07-25 (18:10 ET) — CLOCK CORRECTION; KC +154 wins the first pre-registered EV pick; no K prices exist

- **CLOCK ERROR, caught and corrected.** The container clock reads ~4h FAST. I briefly believed it was 02:40 ET
  and then 22:04 ET; two statsapi endpoints put the true time at ~18:10 ET with KC@DET Final, 4 games In
  Progress and 10 not yet started. Every timing claim in the preceding entry was wrong and is superseded here.
- **covers.com served a stale 7/24 page** whose "finals" (COL@MIL 5-2, CIN@STL 4-2, NYY@PHI 1-0 …) were
  **byte-identical to the 7/24 results already in results.csv.** Recognised and **not** written as 7/25 data.
  Had those been ingested, 15 duplicate rows would have entered the dataset under the wrong date.
- **First graded pick on the pre-registered EV ledger: KC +154 WIN (3-2), +1.54u.** Pre-registration stands —
  the rule was fixed at 06:20Z, 10h50m before the 17:10Z first pitch. Note **V13 leaned DET, not KC**: the pick
  existed only because the price was wrong. It won. One game proves nothing, but the mechanism is the point.
  **ml_ev_tracking 1-0, +1.54u.** COL +186 and STL −116 still pending.
- **CLV:** late snapshot (22:10Z) → `data/mlb/odds/2026-07-25_late.json`. Every line identical to the 05:50Z
  open except CHC@PIT total 8.0 → 7.5, which resolves the opening source conflict in favour of the matchup page.
  **COL and STL both 0 cents CLV** — the market never disagreed with my entry price.
- **NO K PROP PRICES EXIST for 7/25 anywhere reachable.** oddsindex serves a cached 7/24 page; vegasinsider
  renders prices without unambiguous over/under attribution (refused — mis-assigning a side IS price invention);
  rotoballer/rotowire are JS shells; oddsshark ROBOTS_DISALLOWED; the 7/25 editorial articles carry **outs**
  props and batter props, not K props. FTN quotes "Skenes Under 17.5 Outs +130" — a market the engine has never
  been validated on, so it was not converted. **Zero prop plays, second slate running.**
- **STRUCTURAL FINDING, now logged in known_issues: price access is the binding constraint, not model quality.**
  The engine posted MAE 0.49 against a real main-line column today; the gate has sat at 9/100 for two slates
  purely because prices are unreachable. The unblocking artifact is the **Export Table Data → CSV** button on
  the source Taco screenshotted. That one file is worth more right now than any further modelling.
- **Transcription conflict:** vegasinsider shows Skenes 6.5-8.5 / Eovaldi 5.5-6.5; my screenshot transcription
  has Skenes 7.5-9.5 / Eovaldi 6.5-8.5. They do not reconcile — further support for the alt-line-ladder reading
  and an independent reason nothing should be staked off an eyeballed image.
- Ledger unchanged 4-5 / −1.61u, gate 9/100, $0 real money.

## 2026-07-25 18:30 ET — 7/26 board ingested pre-slate; V13 favorite-fade hypothesis pre-registered as E4

**Clock, again.** Container read `Sun Jul 26 02:13 UTC`; real time was ~22:30Z on 7/25 (container ~3.8h fast),
established from the statsapi hydrated schedule: 23:10Z games were Pre-Game while 20:10Z games sat in the 6th–7th.

**Caught a bad endpoint.** `/api/v1/game/824244/linescore` returned a stale snapshot ("middle of the 5th, 2-1")
*and* labelled Kansas City as the home team, which the schedule endpoint contradicts (KC is away). The hydrated
schedule — coherent across all 15 games — shows KC@DET **Final, KC 3 DET 2**. So the KC +154 WIN grade stands, but
only because it was cross-checked. Logged to `known_issues`: never grade from a single endpoint.

**7/25 remainder.** COL +186 and STL −116 were still Pre-Game at capture. Ungraded, correctly. Only KC@DET was final,
so the results.csv backfill is deferred rather than done half-way from a source (covers) already caught serving stale pages.

**7/26 board.** User-supplied screenshot, 15 games with real numeric prices. Verified before use:

- matchups and first-pitch times: **15/15 exact** vs statsapi
- starters: **26/30 exact** vs `probablePitcher` (accent-normalized)
- moneyline hold: **2.08%–3.85%, mean 3.03%**, no arbitrage in any game

That hold band is the load-bearing check — a misread price would have broken it. Best-verified board so far.

**Totals are a best-price display, not a market.** The under line is quoted at or above the over line in 15/15 games
(12 positive, 3 zero, **zero negative**). A sampling error mixes signs; this does not. So the consensus total is only
*bounded* for 12 games — `total=null`, no lean emitted. Only ATL@BAL 8.5, HOU@CWS 9.5, COL@MIL 7.5 are genuine.
Same defect class as the 7/25 strikeout alt-line ladder, caught by the same displacement test. Moneylines unaffected,
so the pre-registered ledger is clean.

**Registered (pre-slate by ~17.75h):** COL +265 (p=.324, edge +.050, EV +.183) and NYY +140 (p=.491, edge +.074,
EV +.178). Neither is a team V13 expects to win. Excluded by rule 3: KC +162 and WSH +105.

**Cost of conservatism, measured.** statsapi says TBD for BOS/KC/SF starters where the board names one. Treating
first-party as authority caps those games. A shadow slate using the board's names, identical rule, yields exactly one
extra pick: KC +162 (EV +.153). Shadow wrote nothing — card diverted, canonical regenerated.

**Rule-text vs code discrepancy found.** Rule 3 reads "TBD or <5 GS"; `daily_card.py` implements "TBD or <2 GS".
7/25 was graded under the code, so 7/26 was selected the same way. Verified explicitly: **zero picks flip** between the
two readings on this slate. Text to be amended forward-only, effective 7/27.

**E4 pre-registered.** Across 50 priced, uncapped game-rows on 5 cards, V13 sits −0.086 below the market on home big
favorites (n=8) and −0.019 in the middle (n=40). Four of five picks this ledger has ever made are underdogs. The ledger
may be one systematic "fade the favorite" bet. Readout is **CLV, not W-L**; holdout is forward slates from 7/27, since
these rows generated the hypothesis. Explicitly *not* used to touch today's picks — rule 4 forbids discretion, and
dropping a play after seeing a diagnostic is the exact contamination pre-registration exists to prevent.

**R5 audit.** COL@MIL: V13 proj 9.7 vs line 7.5, displacement +2.2. Freeland 7.61 ERA vs Misiorowski 1.63 / 39.6% K.
The engine appears to punish a bad starter without bound. COL is also a registered ML pick in that game, so the win
probability there is suspect too. Flagged, not vetoed.

**Still zero K-prop prices — third straight slate.** Gate stuck at 9/100. Price access, not model quality, is the bottleneck.
No closing snapshot has ever been captured, which blocks E3 and E4.

## 2026-07-26 03:20Z — 7/25 graded from two agreeing sources; clock belief withdrawn

Taco pasted the full 7/25 gamefeed (15 games, all FINAL). Parsed it locally rather
than trusting any model-reported total (`harness/parse_box_0725.py`): 15 games,
103 pitcher rows, 30 starters. Structural checks all pass — runs allowed reconcile
to runs scored in all 15, and outs-per-staff match the winner (24/27 when the home
team wins, 26/27 for the BAL walk-off).

Added a three-way SO reconciliation: per-pitcher SO vs Team Pitching SO vs the
opposing lineup's batting SO. One dispute — LAD@NYM, NYM staff: 9 / 8 / 9. Resolved
to 9 by 2-of-1 majority across independent fields. The Team Pitching aggregate is
the dissenter and is now demoted to checksum-only status.

Graded only after a second source agreed. A fresh statsapi hydrated schedule matched
all 30 team scores, 0 disagreements. `harness/grade_0725.py` exits non-zero if any
score disagrees or any game is not Final.

- **ml_ev_tracking**: COL +186 LOSS (5-8), STL -116 WIN (7-0). Ledger 2-1, +1.40u.
  n=3. That ROI is arithmetic, not evidence.
- **v13_forward_directional**: 8-7 on the slate, 37-26 cumulative.
- **Total leans**: 6-9-0. Two-slate total 11-16. NOT_READY stands.
- **results.csv**: +15 rows, source `statsapi+box_paste(2-source)`.

**K model out-of-sample, n=24**: MAE 1.94, bias +0.40, RMSE 2.39, corr 0.487,
OLS slope 1.35. Projected sd 0.96 against actual sd 2.67 — the point projections are
badly under-dispersed and the shrinkage is too aggressive. But the tails, which are
what props actually price, came in near nominal (SO≥8: 6 actual vs 4.5 expected;
SO≤3: 5 vs 5.8), because Poisson noise supplies most of the missing spread. Real but
modest defect in the point estimate; not evidence that prop pricing is broken.
Exploratory, one slate, not pre-registered → queued as E5, not applied.

**Clock correction — a previous finding withdrawn.** The URL spelling
`date=2026-07-25` returned a statsapi response ~4h stale (late games still Pre-Game);
the same content at `startDate=&endDate=` returned all 15 Final. NYY@PHI started
23:20Z and cannot be Final before ~02:20Z, so real time was ≥02:20Z on 7/26 — the
container clock was right and the cached read was the liar. Every prior "container is
~3.8h fast" correction was probably this same artifact. Consequence: the 7/26 board
was captured ~02:13Z on 7/26, so it is ~14.0h pre-slate, not 17.75h. Still genuinely
pre-slate; no pick is invalidated, the claim was merely overstated. Corrected in place.

Also logged: `close_ml_*`/`close_total` in results.csv for 7/19–7/25 hold OPENING
prices, so no CLV has ever been measurable; and 6 of 30 card starters missed the
actual first arm, with PHI using a true opener (Tim Mayza, 2.0 IP) that the K
pipeline has no way to detect.

## 2026-07-26 19:30Z — first real two-sided K board, and the engine's shrinkage caught twice

Transcribed all 30 arms of the 7/26 strikeout board (6 book columns; Hard Rock cut
off, prices absent, zero quotes taken from it — R1). Four integrity tests ran before
anything was priced.

T1 hold: 31/31 two-sided quotes inside 2–12%. T4 re-read: the 4 rows transcribed in
the live pass re-read identically from a fresh crop.

T2 rung coherence passed on **every** row — including Misiorowski's 12.5 @ −135 /
11.5 @ −330, which is a perfectly coherent ladder and is obviously not a startable
strikeout market. **T2 is necessary but not sufficient and can no longer be cited
alone.** T3 cross-book dispersion is the load-bearing test: 10 of 30 rows quarantined
for a line spread > 1.0 K.

Regressed the engine's pre-slate E[K] on the board's median posted line. Slope 0.703
on clean rows with GS≥15 (n=12, corr 0.872) — the engine moves 0.70 K when the market
moves 1.0. Implied stretch 1.42×. On 7/25 the outcome regression gave an actual-on-
projected slope of 1.35. Outcomes and prices are independent yardsticks and they agree
on direction and roughly on magnitude.

Measuring on the dirty rows would have said 2.35× — 65% too aggressive. The quarantine
filter is what makes the number usable.

Consequence: residual (E[K] − line) correlates with the line at −0.87. Direction of
nearly every K selection is determined by whether the line is high or low. Registered
E5 as a pre-registered stretch correction against an untouched forward holdout; the
7/25 n=24 and 7/26 n=12 are burned. **Engine unchanged.**

Shadow run over the 20 permitted rows produced 2 selections. One is Soriano, already
registered live and pre-lock — the shadow reproducing it is a pipeline consistency
check, not a second play. The other is Fedde OVER 2.5 @ +106, claimed EV +0.469, and
that is a bug report: a 2.5 K line *is* the market pricing a short outing, and E[TBF]
does not read it. Freeland 1.5, Avila 1.5, Baz 2.5 are the same defect.

Nothing here is gate-eligible. 26 of 30 arms had already started. Gate stays 9/100 +1
pending.

## 2026-07-27 — the capture requirement was mine, not the market's

Taco flagged that the K board is one of the hardest things on the slate to grab
consistently, and he is right. The response was not to ask harder. It was to
notice that I had been treating a full 30-arm 6-book board as the unit of work
when the actual unit is **one arm, one book, both sides of the price**.

`harness/ingest_kquote.py` accepts a capture of any size and runs only the tests
that a capture of that shape can support:

* T1 hold on every two-sided quote. One-sided quotes pass through with that
  stated rather than silently trusted.
* T2 rung coherence as a warning only — demoted 7/26, an alt ladder passes it
  by construction.
* T3 dispersion **only** on aggregator captures with ≥2 books. A single book's
  own prop page has no alt-ladder ambiguity, so running dispersion there would
  discard good prices to answer a question that cannot arise. This makes a
  book-direct screenshot strictly easier to use than an aggregator board, which
  inverts the effort gradient in the right direction.
* T4 re-read against any earlier drop the same date.

Gate eligibility is decided by the clock and nothing else: capture time known,
capture before first pitch, processing before first pitch. Everything else is
shadow at $0. Arms posted ≤3.5 K are held to shadow regardless, because a short
posted line *is* the book encoding a short outing and the E[TBF] prior does not
read it — the Fedde/Freeland/Avila/Baz defect. `--allow-short-lines` overrides.

**Regression test.** `harness/test_ingest_kquote.py` replays the 7/26
live-at-processing board and requires the ingester to reproduce the hand-made
Jose Soriano registration field for field — side, line, price, book, E[K], GS,
p, edge, EV, displacement, weight, game, first pitch. It does, and registers
exactly one play, not two. Five more checks cover the minimum useful capture,
the three ways the clock can disqualify a play, line-only cells, alt-ladder
quarantine, and the short-line hold.

Getting that exact match required a real fix. The card stores E[K] to 2dp, so
replaying through the card gave EV +0.073 against the ledger's +0.074. Rather
than paper over it, `resolve_ek` takes `proj`'s full precision **only when proj
still agrees with the frozen card to within that rounding** — if the log has
moved since the card was cut, the card wins and the divergence is printed. That
keeps the reproducibility of a frozen artifact and the precision of the live
one, without letting a replay quietly price a start using its own result.

Engine untouched. `state.json` untouched. Gate still 9/100.

## 2026-07-27 — full model breakdown, patch-notes form

Rewrote `docs/model_breakdown.html`, superseding the 7/22 version (e74cdcb, 111 lines).
Structure is dated release blocks (ADDED / CHANGED / FIXED / DEPRECATED / KNOWN) from
07-18 through today, then a standing reference section: both engine tracks with formulas
quoted from running code, the selector thresholds, the four-test board suite and T2's
demotion, all seven ledgers with real figures, every graded K-prop row, the four-part
authorization gate, R1-R8, AUTH-1..7, the known-issues list, and the experiment queue.

Every number traces to state.json, the ledgers, or engine source (R1). Verdicts are
stated unsoftened: sides DEAD, totals NOT_READY, "V13 HAS NO DEMONSTRATED EDGE" on
n=1,461, K-props LIVE_PAPER at 9/100 with 4-5 and -1.61u, real money $0 unauthorized.

NEW DEFECT FOUND WHILE WRITING IT — **HFA-SPLIT**. `engine/v13_1.py:58` multiplies the
home run mean by 1.03; `harness/daily_card.py:63` multiplies by 1.005. Same model, two
different home-field advantages, ~2.5% apart in home run environment. The 7/22 breakdown
documented 1.005, so v13_1.py is the file that drifted. No play is affected (sides are
frozen and unbet), but no V13 figure is comparable across the two paths until this is
reconciled. Logged rather than patched (R6); fixing it is a code change and gets its own
unit of work. Added to known issues and to next actions.

Also carried forward, unresolved: the E4 ID collision (lineup-aware offense vs
favorite-fade, both E4) and the prose use of "E5" for the shrinkage experiment while the
queue's E5 is the WNBA port. Under R7 an experiment's identity is part of its
pre-registration, so this must be reconciled before either E4 reads out.

Engine, state.json, gate string: untouched.

2026-07-27 — core breakdown (lessons form) + four corrections from Taco's review
--------------------------------------------------------------------------------
NEW: docs/core_breakdown.html. Companion to model_breakdown.html — same system, but
organized by what was learned rather than by release date. Thirteen lessons L1-L13, each
with the incident that produced it, the lesson, and whether it is actually incorporated in
code or still only doctrine. Plus: the objective that was wrong at the start (AUTH-7,
"beat the house at a high clip" -> "positive EV vs the price's break-even"), the failure
class that produced five separate errors ("summaries are not sources"), the shrinkage
convention table, a gap table of what is doctrine but nothing enforces, and the through-line.

The through-line, stated plainly: everything that survived was validated by something
outside my own reasoning — outcomes, the market, a second source, a pre-registration.
Everything validated against my own reasoning was eventually discarded. And the useful
moves have been subtractive: sides killed, totals held back, boards quarantined, plays
excluded. Nothing added has yet been shown to make money.

TACO'S REVIEW — four critiques, all four verified correct, all four now recorded.

(1) SHRINKAGE "CONVERGENCE" IS INVALID. Retracted. 1.35 is a calibration slope
    (r*sd_a/sd_p = 0.487*2.67/0.96 = 1.354). 1.42 is a noiseless inversion
    (1/slope(E[K]~line) = 1/0.703). Since slope(y~x)*slope(x~y) = corr^2, inverting one
    cannot produce the other. Identity checked: 0.703*1.0817 = 0.7604 = 0.872^2 exactly.
    Applying the market estimator to the outcome data gives 1/0.175 = 5.71, not 1.35 —
    cleanest proof they were never the same quantity, and evidence the estimator is
    unstable at corr 0.487. Consistent table:
        calibration slope   outcomes 1.35   market 1.08
        sd-match, Poisson-stripped (talent sd 1.49)  outcomes 1.56   market 1.24
        noiseless inversion outcomes 5.71   market 1.42
    Also: the outcome fit is not significant. SE 0.516, 95% CI [0.28, 2.42], t = 0.68.
    CONSEQUENCE: next-action #2 rewritten. Pre-registration must name the estimator and
    the convention, not just the number (R7 amendment). And KPROP-EDGE-ARTIFACT cannot be
    the readout — a 1.4 stretch zeroes residual-vs-line whether or not the spread is real.
    Readout is held-out MAE and log-loss on plays the selector would actually make.

(2) PUSH TERM MISSING. Confirmed in code. p_over does k0=int(ceil(line)); 1-sum(...) =
    P(X >= ceil(line)). On an integer line ceil(5)=5 gives P(X>=5), counting X=5 as a win
    when it is a push. P(X=5 | lambda=5.00) = 0.1755. P(X=6 | lambda=5.68) = 0.1592.
    ev(p,ml) has the matching gap. Logged as PUSH-TERM-MISSING. Next unit of work.

(3) GATE COUNTER OUT OF SYNC WITH THE RULESET. Confirmed. 8 of the 9 graded plays would
    not register under the current <=3.5 K guard. Taco's instruction recorded verbatim and
    binding: "You should not retro-drop it — that's how a record gets laundered, and R6
    says so." Resolution is a FORK, not a reset and not a purge: tag every row with
    selector_version, keep the historical counter at 9 as audit trail, define the gate on
    the current version's subset starting at 8. Logged as SELECTOR-VERSION-UNTAGGED.

(4) REPO CLAIM. Taco's tree shows 2 commits and no engine/. This container shows 52 and
    b23c254 present, so we are looking at different trees. The finding underneath is the
    one that mattered: `git remote -v` is EMPTY and always has been. Four days of work
    existed in exactly one ephemeral place. Acted rather than asked — created and delivered
    sportsmodel_2026-07-27.bundle (863K, full history, verified complete, HEAD b9257bb) and
    a worktree tarball. A bundle is a snapshot, not a remote; a real remote still needs a
    repo URL and a token from Taco.

CORRECTED IN docs/model_breakdown.html (delivered version contained these):
  - "40 commits" -> 52. R1-class error; a number stated that did not trace. Original
    wording preserved in a correction note per R6, not silently overwritten.
  - Shrinkage "two independent methods agree" section struck through and retracted in place.
  - Next-action #2 rewritten. Closing summary paragraph rewritten.
  - Two new known issues added: PUSH-TERM-MISSING, SELECTOR-VERSION-UNTAGGED.

Engine, state.json, ledgers, gate string: untouched. No play created, graded, or removed.
Stated order for what follows: push guard, then shrinkage pre-registration to spec, then
selector_version tagging and the gate fork, then the 8-field parser, HFA-SPLIT, E4/E5.
