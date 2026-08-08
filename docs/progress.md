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

2026-07-27b — PUSH-TERM-MISSING fixed in engine/kprops.py
--------------------------------------------------------------------------------
Taco's critique (2) is now patched. This is a correctness fix, not a parameter change,
so R7 does not gate it; it is pre-registered nowhere because there is nothing to test —
the old code was arithmetically wrong about what a push is.

WHAT WAS WRONG. p_over(ek,line) computed k0=ceil(line); 1 - sum(pmf(0..k0-1)), i.e.
P(X >= ceil(line)). On a half-point line (4.5 -> ceil 5) that is right and no push exists.
On an INTEGER line (5.0 -> ceil 5) it returns P(X>=5), which counts X==5 — a push, stake
returned — as an OVER win. ev(p,ml) had the matching gap: two outcomes where there are
three.

MAGNITUDE, measured not asserted:
  ek=5.00, line 5:  P(over) 0.38404  P(push) 0.17547  P(under) 0.44049
                    old P(over) was 0.55951 — overstated by exactly the push mass.
                    At -110 that flips the bet from EV +6.81% to EV -9.14%. 16-point swing.
  ek=5.68, line 6:  P(over) 0.34245  P(push) 0.15921  P(under) 0.49834

WHAT CHANGED.
  - new probs(ek,line) -> (p_over, p_push, p_under), the single source of truth. Integer
    lines carve out pmf(L); half-point lines return p_push=0.0 and the identical old split.
  - p_over() retained but now returns TRUE P(over) — on an integer line it no longer
    includes the push. Docstring says so.
  - ev(p, ml, p_push=0.0) is now three-outcome: p*prof - (1 - p - p_push). Default 0.0
    reproduces the old form bit-for-bit, so no half-point call site moves.
  - select_play computes edge against the CONDITIONAL-ON-SETTLING probability, p/(1-p_push),
    which is the correct comparison to a vigged implied price. Identical to the old
    p - imp(price) whenever p_push is 0.
  - plays now carry a p_push field.

VERIFICATION — the fix is a proven no-op on the existing record.
  - All nine graded K-prop rows are on half-point lines (4.5, 3.5, 2.5, 5.5, 6.5, 7.5).
    Zero historical rows change. No ledger row was edited, and none will be.
  - Self-test extended 4 -> 8 checks. New ones assert: half-point lines gain no push mass
    and reproduce the pre-fix P(over) to 1e-12; integer push mass equals pmf(L) and matches
    0.17547 at ek=5; the three probabilities sum to 1; integer P(over) strictly shrank;
    ev() is bit-for-bit back-compatible at p_push=0; and a fair push-eligible bet is
    EV-neutral. PASS.
  - harness/test_ingest_kquote.py PASS — it replays the 7/26 board and reproduces the hand
    made Soriano ledger row field-for-field. Unchanged.
  - healthcheck HEALTHY, 0 fail, 1 warn (the warn is the ungraded Soriano row).

RELATED FINDING, LOGGED NOT PATCHED. Scanning stored boards for integer lines turned up 25
of them — all game TOTALS (7.0, 8.0, 9.0, 10.0, 11.0), which push exactly like K props do.
The totals path is safe today only by accident: daily_card.py:102 emits a directional lean
(s["tot"] > tl), never a probability or a price, so there is nothing yet to get wrong.
The moment totals are priced they need probs()-style three-outcome handling. Totals remain
NOT_READY and unbet. Recorded so this is not rediscovered as a new bug later.

Gate string, state.json, ledgers: untouched. Real money still $0, unauthorized.

---

### 2026-07-27 (01:52 UTC) — CORRECTION-ONLY RECONCILIATION; the history finally has a remote

No engine, selector, projector or ledger row was touched. Every change here repairs a CLAIM,
a STAMP, or a GATE DEFINITION. Real money still $0, unauthorized. Sides still DEAD.

DURABILITY — L13 closed. All 54 commits are pushed to
github.com/georgemunoz1-ui/sports-model, branch `sportsmodel/main`, tip 91d2d9c. Four days of
work had been living in exactly one place. It now lives in two. The standing obligation is to
push after every session; the container still holds nothing durable on its own.

Note for anyone reading the delivered archives: the worktree tarball is an OLDER snapshot than
the bundle — it predates e3dcb52 (core_breakdown.html) and 91d2d9c (the push fix). The bundle
is authoritative. If you restored from the tarball you would silently lose the push-term fix.

DECISION_POLICY_VERSION — introduced. `dp-2026-07-27` names the whole decision path a play
passes through: projector, selector thresholds, intake guards, settlement maths. Changing any
one of them starts a new version, because the plays the new path produces are not exchangeable
with the plays the old one produced. The prior version history is recorded as NOT
RECONSTRUCTIBLE rather than invented — no ledger row carries the policy that produced it.

THE GATE FORKS, AND THE PROSPECTIVE SIDE STARTS AT ZERO.
  historical audit  : 9 graded, 4-5, -1.61u. Preserved in full. Never re-graded, never
                      retro-dropped (R6). This is the audit trail.
  prospective gate  : 0/100 under dp-2026-07-27.
Yesterday's proposal was to start it at 8, on the reasoning that eight of the nine survive
today's short-line guard. That was wrong and Taco called it. Surviving a filter applied after
the fact is not the same as having been selected by the current policy: those eight were chosen
under rules that no longer exist, and the decision about which to keep would be made with their
results already in hand. That is the L5 error — a selection rule that cannot be written down in
advance — wearing a tidier costume. A prospective gate starts prospectively. Zero.

RETRACTION REPAIRED IN state.json. The "two independent measurements converge at 1.35-1.42"
claim was retracted in the docs on 7/27 but state.json still carried it as
`engine_vs_market_shrinkage.convergence`. Now retracted there too, original text preserved
verbatim (R6), with the estimators recomputed side by side from the 24 stored rows in
data/mlb/box/2026-07-25_grades.json:

    convention                        from outcomes    from market (clean, GS>=15)
    calibration slope  E[y|x]              1.35              1.08
    sd-matching, Poisson stripped          1.31              1.24
    noiseless inversion  1/slope           5.68              1.42

The quoted pair took 1.35 from row 1 and 1.42 from row 3.

A CORRECTION INSIDE THE CORRECTION. Yesterday's retraction put the outcome-side sd-matching
figure at 1.56. That number was computed from an ASSUMED mean of 4.9. The 24 stored rows were
sitting in the repo the whole time and give mean(actual) = 5.750, sd(actual) = 2.723 — so the
Poisson-stripped talent sd is sqrt(7.413 - 5.750) = 1.290 and the ratio to sd(proj) = 0.983 is
1.31, not 1.56. An assumed input inside a correction is precisely the R1 error the correction
was written to fix, and it is the "summaries are not sources" failure class one more time: I
reached for a rounded summary statistic when the raw rows were one file away. The honest range
narrows from ~1.1-1.6 to ~1.1-1.35. Direction still holds across every cut; magnitude is still
not identified, and the outcome-side evidence is still not significant (SE 0.515, 95% CI
[0.28, 2.42], t vs no-stretch 0.68).

NEXT-ACTION #2 REWRITTEN. It read "fit and FREEZE the E5 stretch scalar", which presumes a
converged estimate that does not exist. It now requires the pre-registration to name the
ESTIMATOR, the CONVENTION and what it optimises, and a READOUT the transform cannot trivially
satisfy — held-out MAE and log-loss on plays the selector would actually make.
KPROP-EDGE-ARTIFACT is explicitly disqualified as that readout: a stretch near 1.4 drives
residual-vs-line to zero whether or not the extra spread is real.

STAMPS. docs/model_breakdown.html was stamped "HEAD b23c254 - 52 commits". b23c254 is 51
commits; 52 is the count at b9257bb, the commit that ADDED the document. The correction note in
that file — written specifically to fix a miscount — restated the same wrong number. Both
wordings preserved per R6. Filed as REVISION-STAMP-DRIFT. Both documents are now stamped to the
real tip, and model_breakdown.html carries a note saying it is no longer the tip.

PUSH-FIX STATUS PROPAGATED. state.json predated commit 91d2d9c entirely and carried no
push-term entry; core_breakdown.html L9 still said "cheap guard, not yet written";
model_breakdown.html still said "live correctness bug, not yet fixed". All three now record it
as RESOLVED, with the independent re-verification: probs() sums to 1 and matches closed-form
Poisson at every point tried, back-compat is exact (max deviation 0.00e+00 across 240x12
half-point cases), and the -110 flip +6.81% -> -9.14% reproduces.

NEW DEFECT LOGGED, NOT PATCHED — ERBB-PLACEHOLDER-UNFLAGGED. Eight pitcher-date rows
(656876/621111/678022/571945 on 07-21; 543037/663903/695611/687562 on 07-22) carry ER=0, BB=0
as placeholders that were never fetched. The caveat lives in pitcher_logs/README_NOTE.txt,
which no code reads and no healthcheck tests, and a genuine 0-ER start is indistinguishable
from a placeholder by inspection. Season ERA is understated by +0.10 to +0.35 for those arms.
K-props are UNAFFECTED — E[K] reads only SO and TBF, both verbatim per the note. ERA and BB%
feed the sides sim only, and sides are frozen and unbet, so no play is affected. This is L13's
exact shape: a risk written down beside the data instead of encoded in it. R1 wants null plus a
flag, not a zero. Fix queued, not applied here — this pass is correction-only.

STILL OPEN, CONFIRMED PRESENT IN CODE. HFA-SPLIT (v13_1.py:58 x1.03 vs daily_card.py:63
x1.005, both still there). The 8-field parser is LATENT not live: 5,139 log rows are 7-field,
134 are 10-field, zero are 8-field — it blocks forward writes and is corrupting nothing today.
selector_version tagging on ledger rows is still unimplemented; only the state.json half landed.

VERIFICATION. kprops self-test PASS. ingest_kquote regression PASS. healthcheck HEALTHY.

### 2026-07-27 (02:0x UTC) — housekeeping: stop tracking compiled bytecode

No source, no model, no claim, no ledger row touched. `git diff --stat -- '*.py'` is empty.

Five .pyc files were tracked and there was no .gitignore. engine/__pycache__/kprops.cpython-311.pyc
is rewritten every time engine/kprops.py is imported — which healthcheck, the kprops self-test and
the ingest regression all do — so the working tree went dirty after every verification run. The
healthcheck line "git working tree clean (N dirty)" was reporting on files that nobody had edited.

Added .gitignore (__pycache__/, *.py[cod], *.egg-info/) and untracked the five .pyc files. Bytecode
regenerates on import and is never an input to anything. Verified afterwards: kprops self-test PASS,
ingest regression PASS, healthcheck HEALTHY, and the tree stays clean across a full suite run.

### 2026-07-27 (02:1x UTC) — three wording corrections; earlier entries left intact per R6

All three came from Taco reading the 7/27 entry above. Earlier log entries are NOT edited —
the wrong wording stays where it was written and is superseded here. state.json and
core_breakdown.html ARE edited, because those are current-state documents rather than a log,
and both carry the superseded wording inline.

1. "THE HONEST RANGE NARROWS TO ~1.1-1.35" — withdrawn as phrasing. It reads as an interval
   estimate and it is not one. Replacement wording, now used everywhere:

     the four comparable point estimates span 1.08-1.35; this is not a confidence interval
     or an identified parameter range, and no-stretch remains plausible.

   "Comparable" means the 2x2 of calibration slope and dispersion matching (1.35 / 1.08 /
   1.31 / 1.24). The noiseless-inversion row is excluded because 5.68 against 1.42 is not
   comparable across sources — which is precisely the arithmetic that made the original
   "convergence" claim possible.

2. ROW MISLABELLED. The table row read "sd-matching, Poisson noise stripped". That was true of
   only half the row. The OUTCOME cell strips Poisson sampling variance out of actual K counts,
   sqrt(var(actual) - E[lambda]) / sd(proj) = 1.31. The MARKET cell is sd(line)/sd(E[K]) =
   corr/slope = 1.24, with no Poisson correction of any kind — posted lines are not Poisson
   draws and there is nothing to strip. Labelling both cells the same way implied a symmetry
   between the two estimates that does not exist. Row is now "dispersion matching; outcome
   estimate Poisson-stripped".

3. INTEGER-LINE SCOPE, overstated and now measured. The claim was "0 of the 4 line values in
   any captured board are integer". Wrong twice.

   First, the population. That scan keyed on a JSON field named "line" and found 4 values. The
   K boards store quotes POSITIONALLY as [book, line, under, over], so the scan missed almost
   the entire population. Counted properly, across all 10 board files under data/mlb/props/:

     365 posted K line values, 0 integer.
     distinct values: 1.5 2.5 3.5 4.5 5.5 6.5 7.5 8.5 9.5 11.5 12.5 — every one a half-point.

   The conclusion survives and is now much better supported: no K prop captured to date could
   have hit the push bug, so for this market the 7/27 fix is preventive.

   Second, the scope word. "Any captured board" wrongly swept in the game-total boards, which
   DO contain integer lines — 25 of them (7.0/8.0/9.0/10.0/11.0), as the 91d2d9c entry above
   already recorded. Those push exactly the way K props do. Totals are safe today only because
   daily_card.py:102 emits a directional lean and never a price. The correct statement is
   scoped to K props and says nothing about totals.

   Same failure class as the 1.56: a summary statistic reached for when the raw rows were one
   file away, and a scope word ("any") doing work the measurement did not support.

No engine, selector, ledger row, gate or verdict touched. Real money still $0, unauthorized.

### 2026-07-27 (02:2x UTC) — decision_policy_version WIRED; the gate is now computed, not typed

Scope: this unit only. No ER/BB work, no parser work, no HFA work, no engine change.

WHAT WAS ACTUALLY BROKEN. decision_policy_version and the prospective 0/100 landed in
state.json earlier today as text. They were declarative and would not have survived:
harness/ingest_kquote.py rewrites gates.kprops_go_live.progress on EVERY --register run,
computing it as `record_w + record_l` — which counts every settled row regardless of the
policy that produced it. The hand-set "0/100 under dp-2026-07-27" would have been silently
clobbered back to "9/100 graded" the next time a play was registered, and nothing would have
reported it. healthcheck did not look at the gate at all.

NEW harness/policy_gate.py — one place that owns the counter. Three numbers, kept apart:
  prospective    graded rows tagged with the CURRENT policy. This is the gate. 0/100.
  historical     every settled row ever. Audit trail. 9 settled, 4-5, -1.61u. Never
                 re-graded, never retro-dropped (R6).
  retrospective  8 of 9 — EXPLORATORY ONLY, and narrower than it looks. See below.
VOID is excluded from settled counts: Mikolas returned the stake and decided nothing, so
`graded` holds 10 rows and only 9 of them settled.

THE 8-OF-9 IS A SHORT-LINE-GUARD-ONLY STATISTIC. The only current criterion checkable against
a stored row is the short-line hold, because the row carries its posted line. EV>0, edge>=0.04
and |proj-line|>=0.8 all need E[K] as it stood BEFORE that start, and recomputing it now would
read a pitcher log that already contains the start being priced — the exact R2 leak resolve_ek()
exists to block. So it is not "8 of 9 plays are still valid". It is "8 of 9 clear the one guard
that can be checked without cheating". It moves no gate. The one blocked row is Buehler O 3.5.

NO INVENTED HISTORICAL TAGS. The nine rows carry no decision_policy_version and none was
written onto them. Absence is recorded as absence (R1); an untagged row is simply not a
current-policy row. healthcheck asserts this and FAILS if a tag ever appears on them.

WIRING.
  - ingest_kquote.py stamps decision_policy_version on every newly registered row, and now
    writes the gate line through policy_gate.progress_string() instead of the hardcoded
    record_w+record_l form.
  - healthcheck gained four checks, all FAIL-not-warn: the policy_gate self-test; stored gate
    string == recomputed; prospective counts only current-policy rows; historical audit intact;
    and no invented tag on a historical row. A gate that has quietly drifted is worse than no
    gate, so these fail loudly.

BUG FOUND AND FIXED DURING THE UNIT. policy_gate imported SHORT_LINE from ingest_kquote so the
guard and the statistic reporting on the guard could not drift apart — but ingest_kquote now
imports policy_gate, and SHORT_LINE is defined BELOW that import, so the cycle failed at load
time with ImportError. Caught by running the import, not by reading it. Fixed with a lazy
read inside the function; both directions import cleanly and the constant is still read from
the module that enforces it rather than duplicated.

TESTS THAT CAN FAIL. Verified by breaking things on a deepcopy, not by assertion:
  - drift the stored gate string to "9/100 graded" -> detected.
  - back-date a policy tag onto a historical row -> prospective jumps 0->1, untagged drops
    9->8, two self-test assertions fail.
  - append a genuine current-policy WIN -> prospective goes 0->1/100 while the 9 untagged rows
    stay out of the gate.
state.json verified byte-identical after the test run.

Verified: policy_gate self-test PASS, kprops self-test PASS, ingest regression PASS,
healthcheck HEALTHY 0 fail. Real money still $0, unauthorized. Sides still DEAD.

### 2026-07-27 (03:01 UTC) — KSIM-2026-07-27 PHASE 1 FROZEN (simulated board, no market exists)

Pre-market forecast for the 7/27 slate, frozen before any pitcher-K line was published.
Everything in it is labelled SIMULATED - NOT AN ACTUAL MARKET. No engine change, no ledger
row, no gate movement. Real money still $0, unauthorized.

  artifact  data/mlb/props/simulated/2026-07-27_KSIM_phase1.json
  sha256    7f827fd0014e5835ec3bf3572bbe1ff36dce452d5e0a55b735d04fe665c12d2f
  cutoff    2026-07-27T02:33Z      frozen  2026-07-27T03:01:55Z
  engine    6146baa, FROZEN - no stretch applied, E5 has not read out

WHY THE ID IS NOT AN E-NUMBER. Two experiments are already numbered E4 and "E5" is used in
prose for the shrinkage work while the queue's E5 is the WNBA port. Adding a numeric ID would
compound an open R7 defect, so this board is KSIM-2026-07-27.

COHORT RECONCILIATION - 24 probable, 23 eligible, 1 excluded, none silently dropped.
  EXCLUDED: Zac Thornton (MLBAM 804267, NYM). GS=3 against the pre-registered >=5 GS floor in
  engine.kprops.proj(). Not missing and not skipped: the name resolves, the log exists, and it
  holds three starts (5/20, 6/26, 7/12). The engine returns nothing rather than a guess. He is
  also in data/backfill/mlb/2026/_need_logs.txt as pending backfill. Row preserved in
  excluded_rows with the reason attached.
  Name-resolution note: "Zach Thornton" fails at LOOKUP (pid None); "Zac Thornton" resolves and
  fails at the SAMPLE GATE. Same None, different cause - only the second is the eligibility rule.

TIERS. Never pooled in any Phase 2 readout.
  Tier 2, K-market-exposed (1): Kyle Bradish. A 5.5 line was visible before freeze. Performance
    projection is evaluable; simulated-line accuracy MUST NOT be scored as blind.
  Tier 1, game-market-exposed (22): the generator had seen this slate's moneylines, run lines
    and totals before freeze. Exploratory, partially exposed line-baseline cohort - NOT a blind
    confirmatory market test.
  Tier 0, clean: ZERO. No pitcher on this slate is fully blind. A genuinely blind
    market-forecast test requires a future untouched slate.

SIMULATED-LINE RULE, pre-registered before any 7/27 K line was seen:
  line = round(2*E[K])/2, over -115, under -115, no shading, CI +/-0.5 K DECLARED NOT FITTED.
  It uses only E[K] and is fitted to nothing, so the Tier-1 exposure cannot leak into it.
  The 7/26 engine-vs-market fit (slope 0.703) was deliberately NOT used: n=12, unlicensed under
  R7, magnitude unidentified (1.08-1.35), and fitted to the market - which would import the very
  anchor a blind test exists to detect.

THE SELECTOR COLUMN IS VACUOUS IN PHASE 1, and this is a property of the system rather than of
this slate. When the simulated line is the engine's own number rounded to the nearest rung, the
largest achievable |displacement| is 0.25 K against a 0.8 K floor, so select_play rejects all 23
rows by construction. select_play is a MARKET-DISAGREEMENT detector; it cannot fire against the
model's own number. The column is retained for schema fidelity with the reason recorded on every
row, and it carries no information until Phase 2 scores it against a real quote.

R2 CHECK. Newest start in pitcher_logs is 2026-07-23, so no 7/27 start can be present and proj()
cannot read the outcome it is projecting.

TWO DEFECTS CAUGHT BEFORE THE HASH - which is the point of freezing in two steps.
  1. frozen_utc was first written as 02:41:00Z, a time that traced to no command. Replaced with
     the actual wall clock at write (R1).
  2. pmf enumerated k=0..12 alongside pmf_12plus = P(K>=12), double-counting k=12; distributions
     summed to as much as 1.0236. Corrected to k=0..11 plus a 12+ tail. Sums are now 1.0 +/- 2e-5.
  Both are recorded in the artifact under corrections_before_freeze.

SIDE OBSERVATION. 13 of 23 rows land on an INTEGER simulated line, mean push mass 0.182. Under
the pre-7/27 code every one of those would have scored the push as an OVER win - Martin Perez at
4.0 would have read P(over) 0.557 instead of 0.362. The push fix was not hypothetical.

STARTER STATUS is single-source and UNCONFIRMED on every row: generator transcription of an
aggregator screenshot, T4 re-read not done, CBS used as operator baseline. 6 of 30 starters were
wrong on 2026-07-25 and PHI ran a true opener.

Verified: kprops PASS, ingest regression PASS, policy_gate PASS, healthcheck HEALTHY 0 fail.

### 2026-07-27 (03:1x UTC) — KSIM protocol addendum; Phase 1 untouched and re-verified

Eight clarifications issued after Phase-1 acceptance, recorded in
docs/experiments/KSIM-2026-07-27_protocol_addendum.md. The frozen artifact was NOT modified:
sha256sum -c re-verified OK before and after writing the addendum. Real money still $0.

  Phase-1 hash (unchanged): 7f827fd0014e5835ec3bf3572bbe1ff36dce452d5e0a55b735d04fe665c12d2f

WHAT CHANGED IN THE PROTOCOL, not in the data:
 1. The +/-0.5 K band is renamed DECLARED COMPARISON BAND / TOLERANCE BAND everywhere. It was
    declared, not estimated; "opened inside the CI" must never be reported as coverage.
 2. The -115 prices are a standardized NULL ASSUMPTION, not forecasts. Phase 2 must not score
    price error, price directional agreement, or shading accuracy against them. Target B is
    mechanical LINE-PLACEMENT error only.
 3. "Tier-1 exposure cannot leak in" is WITHDRAWN as overclaiming. Replaced with the exact
    wording: the transformation from E[K] to the derived line contains no market input;
    independence of E[K] itself depends on the frozen engine and its input lineage containing
    no betting-market variables. Lineage now hashed and audited (below).
 4. Phase 2 splits: 2A before first pitch (openers + frozen executable decisions), 2B after
    games (closes + results). An uncaptured opener is OPENER_NOT_CAPTURED forever - never
    reconstructed once results are known.
 5. Two opening events kept apart. EVENT_A = first publicly observed line, even one-sided,
    NOT executable. EVENT_B = first complete quote (book, line, over, under, timestamp), the
    only thing select_play() may see.
 6. Opener-source rule PRE-REGISTERED before further lines appear: first complete EVENT_B by
    capture timestamp; ties broken DK > FD > BR > MGM > CZR > HR.
 7. Starter-status changes alter eligibility, never the frozen projection. Scratch -> preserve
    and mark NOT STARTED. Replacement -> no retroactive projection. Short outing or injury exit
    -> RETAIN the result and label it; never silently drop it.
 8. Phase 2 writes NEW artifacts citing the Phase-1 hash. The frozen file is never appended to.

INPUT LINEAGE, hashed to support the item-3 independence claim. proj() reads exactly three
things and nothing else enters E[K]:
  engine/kprops.py                       72a30c2650b6c4dc6b2b6c2f8a57f1848b1e139909cf0ad7b0120441f7411b56
  data/backfill/mlb/2026/pitchers.csv    a350ff454f247019e56bd39c6a6e2d393f0ffc5999cb079fb88be55a5e98d6a7
  23 pitcher logs (composite)            806e5cd2f0a7964900b421069b1bfe596ccc71e885dfa6bb30fb0a55bcd53f20
Schema audit: pitchers.csv is (id, name); logs are date|ip|er|so|bb|tbf|gs or
date|opp|home|side|ip|er|so|bb|tbf|gs. No line, price, odds, total, moneyline or implied-prob
column anywhere. The claim holds FOR THESE INPUTS AT THESE HASHES - a property of the audited
files, not a general guarantee. Per-log hashes are tabulated in the addendum.

WHY THE TIE-BREAK ORDER IS NOT QUALITY-RANKED. The 7/25 per-book diagnostic found only
BetRivers behaving like a main line (signed dispersion -0.11, MAE 0.49 vs DK's -1.44/1.44).
Ranking BR first ON THOSE GROUNDS would be circular: the book would be chosen because it agrees
with the model whose line-placement error is being measured, which mechanically shrinks the
error under test. The declared order rests on no quality grounds at all and is a tie-break only.

EVENT_A ALREADY ON THE RECORD. Kyle Bradish, line 5.5, UNDER side only, no price transcribed,
observed 2026-07-27T02:33Z on a Covers player-props board during a 12-source scan. This is the
observation that placed him in Tier 2. It is EVENT_A and cannot be passed to select_play().
The same scan found zero other K lines across the other 23 pitchers and zero complete two-sided
quotes slate-wide.

### 2026-07-27 (03:2x UTC) — Phase-2 capture protocol; lineage hash now reproducible

Final Phase-2 clarification. Phase 1 NOT modified - sha256sum -c OK before and after, and the
frozen artifact does not appear in this diff. Real money still $0, unauthorized.

  docs/experiments/KSIM-2026-07-27_phase2_capture_protocol.md   (new)
  docs/experiments/KSIM-2026-07-27_lineage_manifest.txt         (new, 23 entries)
  harness/verify_lineage.py                                     (new, recomputes every hash)

NOTHING IS AN "OPENER" UNTIL PROVEN. EVENT_A/EVENT_B are renamed FIRST_CAPTURED_LINE and
FIRST_CAPTURED_COMPLETE_QUOTE; a third term VERIFIED_OPENER exists and requires a market-origin
timestamp or an authenticated odds-history feed. "First we saw it" is a fact about our
retrieval; "first the book posted it" is a fact about the market, and we have never had
evidence for the second. Absent that evidence VERIFIED_OPENER is ABSENT, not inferred from the
earliest capture. A supersession banner was added to the addendum's section 5; no accepted text
was rewritten.

TWO TIMESTAMPS, NEVER CONFLATED. observed_at_utc (ours, always present) and
source_quote_time_utc (the book's, null when the source supplies none). Setting the second
equal to the first is prohibited - it manufactures market provenance from our own retrieval
clock, and it is exactly what would let a mid-slate screenshot pass as an opener.

MAIN-LINE SELECTION IS MARKET-DESIGNATED ONLY. If a book shows several rungs, use the one the
BOOK designates default/main; otherwise mark MAIN_LINE_UNRESOLVED, keep every alternate, and
score nothing from that pitcher's line placement. Choosing the rung nearest E[K] is prohibited:
it would select the comparison that minimises the error being measured, guaranteeing a
flattering result however the engine actually performs. Same defect class as the 7/26 alt-rung
contamination, approached from the other side.

PHASE-2A ELIGIBILITY IS THE CLOCK. A capture counts for executable-decision scoring only if
observed_at_utc precedes THAT PITCHER's first pitch. Later captures are still recorded and still
reported, but can never produce a frozen executable decision and can never be relabelled.
Per-pitcher deadlines are tabulated in the protocol from the frozen artifact.

TWO COMPARISONS, NEVER MERGED. C1 = frozen line vs FIRST_CAPTURED_COMPLETE_QUOTE. C2 = frozen
line vs VERIFIED_OPENER, only where authenticated opener history exists. If none exists for this
slate - the present expectation - C2 is reported EMPTY, never approximated from C1.

LINEAGE NOW REPRODUCIBLE, not asserted. harness/verify_lineage.py recomputes all four published
hashes from disk: phase1, kprops.py, pitchers.csv and composite_v1 all OK under
python 3.11.15 / CPython / Linux-6.18.5. Command: python3 harness/verify_lineage.py

  A weakness in the published canonicalisation is documented rather than quietly fixed. v1 is
  ''.join(f'{pid}:{sha256}') over pids sorted as STRINGS with NO delimiter. Concatenating
  variable-length fields without a separator is not injective in general; it is well defined
  here only because pid and sha256 happen to be fixed-width. It cannot be changed without
  invalidating a hash already cited in the addendum and a commit message, so v1 stands, and a
  delimited v2 (fc6f01fa...) is published alongside for future manifests.

BRADISH RECORD CORRECTION. The addendum said "under side only, no price transcribed"; the
source did display an under price whose value never reached our record. Both are true of
different things. Encoded as under_price: null with price_present_but_not_transcribed: true -
never a reconstructed number. He stays FIRST_CAPTURED_LINE only: not complete (no over price),
not a verified opener (no market-origin timestamp), not passable to select_play(), Tier 2.

### 2026-07-27T03:38:00Z — Phase-2A operational rules; scan cycles, evidence hashing, per-pitcher freeze

Eight operational rules appended to docs/experiments/KSIM-2026-07-27_phase2_capture_protocol.md
as section PHASE-2A OPERATIONAL RULES, plus a capture-record template at
data/mlb/props/simulated/_KSIM_phase2a_capture_template.json. Phase 1 NOT modified: sha256sum -c
OK, and the frozen artifact does not appear in this diff. Real money still $0, unauthorized.

A1 fixed scan order DK -> FD -> BR -> MGM -> CZR -> HR, declared in advance, never reordered.
A2 a scan cycle is ONE timestamped sweep; every response is retained including
   market_unavailable. A source that returned nothing is a recorded observation, not an
   omission - the absence of a line at a known time is precisely the evidence that established
   the 7/27 K market had not opened.
A3 primary selection = FIRST cycle containing a qualifying complete main-line quote, then the
   hierarchy WITHIN that cycle, not sub-second retrieval order.
A4 required fields incl. scan_cycle_id, cycle_started_at_utc, observed_at_utc,
   source_quote_time_utc, scheduled_first_pitch_utc, minutes_before_first_pitch (signed;
   negative = after first pitch = ineligible), book, line, both prices, main-line designation.
A5 evidence is the ORIGINAL html/json response or a timestamped screenshot visibly containing
   the complete quote, hashed. A hand-built JSON record is metadata, NOT evidence.
A6 complete ISO timestamps with dates and seconds, always.
A7 freeze each pitcher's executable decision IMMEDIATELY on its qualifying capture.
A8 later quotations preserved for movement/closing analysis, never substituted.

A3 SUPERSEDES THE RULE PRE-REGISTERED IN ADDENDUM SECTION 6 ("first complete quote by capture
timestamp, ties DK > FD > ..."). The change is legitimate ONLY because zero complete quotes
exist for this slate: the 12-source scan at 2026-07-27T02:33:00Z found one one-sided line and no
complete quote. Changing a selection rule after a qualifying capture existed would be
retrospective selection and is prohibited. Recorded here with its timestamp so the ordering of
rule-change and first-capture is auditable.

OPERATIONAL RESOLUTION of A3 vs A7: because DK is first in the hierarchy, a qualifying DK quote
cannot be outranked later in the same cycle and may be frozen at once. If DK does not qualify
the cycle continues down the order, and the non-qualifying responses above the winner are
retained as the evidence that it won.

A5 HAS A CONSEQUENCE WORTH STATING. The existing hand-built drop files under
data/mlb/props/drops/ are METADATA under this rule, not evidence. They remain valid inputs to
the ingester but cannot by themselves substantiate a Phase-2A capture.

A6 CAUGHT AN ERROR OF MINE FROM ONE MESSAGE EARLIER. I wrote "the three West Coast games give
until 01:38Z" with no date. Those games fall on 2026-07-28 in UTC while the rest of the slate is
2026-07-27, so the bare form is ambiguous across exactly the boundary this slate straddles. The
correct form is 2026-07-28T01:38:00Z.
  Forward-only: progress.md holds ~20 bare HH:MMZ forms in earlier entries. It is an
  append-only log and they are NOT rewritten (R6).
  The frozen artifact stores 2026-07-27T18:35Z - full date, no seconds field. Phase 2A writes
  the seconds-complete form. Same instant; the mapping is TABULATED in the protocol, not
  applied to the frozen file.

### 2026-07-27T03:44:00Z — Phase-2A outcome/design rules B1-B5, committed BEFORE any capture attempt

Five rules appended to the capture protocol. Phase 1 NOT modified. Committed before a scan is
attempted so the ordering of rule-freeze and first-capture is auditable, per B5.

B1 four distinct non-capture outcomes: NO_QUALIFYING_MARKET (source responded successfully, no
   qualifying quote - the only one that is a finding), SOURCE_FAILURE, ACCESS_BLOCKED,
   CAPTURE_NOT_RUN. The last three are statements about US, not the market. Collapsing them
   into "no line found" converts our own failure into a market fact.
B2 predetermined order preserved, one query per source per cycle. No re-running a source
   because its first result was unfavourable or incomplete - that is selection disguised as
   retry. Retry permitted only for a failure/block that returned NO content, recorded as a
   separate attempt, never replacing the original.
B3 opportunistic cadence must be labelled OPPORTUNISTIC_CAPTURE, and under it three claims are
   prohibited: that the first captured quote was the first AVAILABLE quote; any cross-pitcher
   market-release timing comparison; any inference about how long a line was up before capture.
B4 game times verified against an authoritative schedule AT capture time, source recorded.
   Deadlines never extended retrospectively after a quote or a result is known.
B5 the amendment window closes at the first qualifying capture. Later methodological
   discoveries are logged and deferred to the next untouched slate, never applied to 7/27 in
   flight.

### 2026-07-27T03:44:20Z — Phase-2A scan cycle KSIM-0727-C01: 6/6 ACCESS_BLOCKED, zero market information

First Phase-2A capture attempted under the protocol frozen at d6229ac. Phase 1 NOT modified.
Real money still $0, unauthorized.

  artifact  data/mlb/props/simulated/2026-07-27_KSIM_phase2a_cycle01.json
  sha256    147b2f3f44f4e00a58fb3400fefafe792137bf0e95585e3ef2abebdb2ad46fd0
  window    2026-07-27T03:43:02Z -> 2026-07-27T03:44:20Z
  design    OPPORTUNISTIC_CAPTURE

RESULT: DK, FD, BR, MGM, CZR, HR queried once each in A1 order. All six returned HTTP 403.
  ACCESS_BLOCKED 6 | SOURCE_FAILURE 0 | NO_QUALIFYING_MARKET 0 | CAPTURE_NOT_RUN 0
  qualifying captures 0, complete quotes 0, lines observed 0.

THIS CYCLE ESTABLISHES NOTHING ABOUT THE MARKET. Under B1 only a successful source response can
establish NO_QUALIFYING_MARKET, and zero sources responded. Saying "no 7/27 K lines were found"
off the back of this would convert our own access failure into a market fact - which is exactly
what B1 was written to prevent, one message after it was written.

TWO STRUCTURAL BLOCKERS, both permanent for the agent-side capture path:

 EGRESS-BLOCKED. statsapi.mlb.com - a plain public JSON API that does not bot-block - also
 returned 403 when queried for the B4 schedule check. A uniform 403 across seven unrelated hosts
 indicates the environment's network policy is refusing non-allowlisted outbound requests. That
 is our perimeter, not seven independent refusals, and retrying later will not change it.

 WEBFETCH-NOT-EVIDENCE. WebFetch converts a page to markdown and answers a prompt over it with a
 small fast model. It returns summarised prose, never the original HTML/JSON. A5 requires the
 original response or a timestamped screenshot, hashed. So even WITH egress, an agent-side
 WebFetch capture could satisfy neither A5 (nothing raw to hash) nor B1's "successful source
 response" standard - it would be a summariser's report of a source, which is the documented
 "summaries are not sources" failure class that has produced five separate incidents on this
 project. This is the long-logged unsolved WebFetch gap becoming operationally binding.

CONSEQUENCE: the agent cannot execute a Phase-2A capture from this environment. The capture path
runs through the OPERATOR - a screenshot or saved raw response from a book's own prop page,
which satisfies A5 and B1 in a way no tool available here can.

B4 NOT SATISFIED this cycle: schedule verification was itself ACCESS_BLOCKED, so
scheduled_first_pitch_utc values stand as frozen in Phase 1, unverified at capture time.

CYCLE DEFECT LOGGED, A4-OBSERVED-AT-NOT-STAMPED: per-source observed_at_utc was not recorded,
only the cycle window. A4 requires a per-capture timestamp. No quote was at stake since every
source was blocked, but the next cycle must stamp each call. Status OPEN.

B5 AMENDMENT WINDOW REMAINS OPEN - no qualifying capture has occurred for 2026-07-27.

### 2026-07-27T03:52:00Z — manual-evidence path (section C); C01 overclaim withdrawn

Eight rules appended to the capture protocol as section C. Phase 1 unaltered. The C01 artifact
is NOT rewritten - its hash still verifies and its original wording stays in the record (R6).
Real money still $0, unauthorized.

C1 OVERCLAIM WITHDRAWN, AND IT WAS MINE. The C01 record and its commit message called the two
   blockers "permanent for the agent-side path" and asserted "retrying later will not change
   this." The evidence was seven HTTP 403s inside a 78-second window. That establishes perimeter
   blocking DURING C01 and nothing about the future - policy, allowlists and environment config
   can all change. Renamed ENVIRONMENT_BLOCKED_DURING_C01 and scoped to that cycle. Claims that
   access can never work are prohibited; retrying is permitted and may succeed.
   The WebFetch limitation is rescoped the same way: summarised-markdown-not-raw-response is a
   property of the fetch tooling CURRENTLY AVAILABLE, not a law of nature.
   This is the same error class the project keeps catching - stating a conclusion wider than the
   observation supports. One 78-second window cannot license the word "permanent."
C2 one user image is a USER_SUPPLIED_OPPORTUNISTIC_CAPTURE, not a completed A1 cycle, and it
   cannot supply statuses or timestamps for sources nobody inspected.
C3 never manufacture per-source timestamps, NO_QUALIFYING_MARKET findings or ACCESS_BLOCKED
   statuses from a single screenshot. Un-inspected sources are CAPTURE_NOT_RUN - the only honest
   status for a source nobody looked at.
C4 two classes. A PRIMARY_PROTOCOL_CAPTURE needs the full DK->FD->BR->MGM->CZR->HR cycle with
   evidence for every source through the qualifying winner, and may be called the primary
   hierarchy-selected comparison. B USER_SUPPLIED_OPPORTUNISTIC_CAPTURE may freeze an executable
   decision but never carries that title - no hierarchy was exercised when one source was seen.
C5 an acceptable screenshot must VISIBLY establish source, player+market, line, BOTH prices from
   the SAME book, slate date, and main-line status where shown. The original image is preserved
   and hashed; a retyped transcription is not the evidence, the file is.
C6 observed_at_utc = when the evidence was received or captured. source_quote_time_utc stays
   null unless the book visibly supplies a quote time IN the image - never inferred from file
   mtime, message time, or processing time.
C7 a one-sided screenshot, or one combining best-over and best-under from different books, is
   NOT a FIRST_CAPTURED_COMPLETE_QUOTE and cannot reach select_play(). The second is the 7/26
   aggregator contamination in screenshot form: a price pair no single book would honour
   together is not a quote, and the hold it implies is fictional.
C8 an isolated user capture may support a prospective executable decision - it is a real price a
   real book showed, frozen before first pitch. But its line-placement result is DESCRIPTIVE and
   SOURCE-SELECTED: the book was chosen by convenience, not by the hierarchy, so the comparison
   carries a selection effect of unknown sign and size. Class A and class B are never pooled.

B5 amendment window REMAINS OPEN - still no qualifying capture for 2026-07-27.

### 2026-07-27T03:58:00Z — section D: manual-evidence timestamps and main-line status; protocol complete

Final pre-capture clarification. Phase 1 unaltered; the C01 artifact untouched and still
verifying. Real money still $0, unauthorized.

D1 ELIGIBILITY RUNS ON A DEFENSIBLE TIMESTAMP, NOT A RECOLLECTION. My own phrasing is withdrawn:
   I asked for a screenshot "plus roughly when you took it," which invites exactly the
   conversion this rule prohibits. Three fields now, never merged:
     received_at_utc              exact system time the ORIGINAL image arrives. Always present.
     user_reported_capture_time   optional, verbatim, WITH timezone and stated precision.
     image_metadata_time          EXIF/file metadata if present and readable.
   The eligibility test uses received_at_utc against that pitcher's scheduled_first_pitch_utc,
   UNLESS the image visibly establishes an earlier time or trustworthy metadata supplies one. An
   approximation is recorded with its precision and NEVER becomes an exact timestamp.
   Consequence, stated now rather than discovered later: an image arriving after first pitch is
   INELIGIBLE for executable scoring even if genuinely taken hours earlier, absent visible or
   metadata proof. Deliberately conservative - received_at_utc is the one time we can evidence,
   and eligibility resting on memory is eligibility revisable after the result is known.

D2 EXECUTABILITY AND MAIN-LINE IDENTIFICATION ARE SEPARATE QUESTIONS. A complete same-book quote
   freezes a Class-B executable decision even when main-line status is invisible.
     book_designated        freeze yes | outcome+CLV yes | line-placement YES
     MAIN_LINE_UNRESOLVED   freeze yes | outcome+CLV yes | line-placement EXCLUDED
     ALT_LINE               freeze yes | outcome+CLV yes | line-placement EXCLUDED (not the
                            book's main market)
   CLV for the non-designated labels is measured against the IDENTICAL book and line only -
   never another book's close, never another rung.
   This REFINES section 4 / A4 rather than contradicting it. A4 said an unresolved main line
   meant "score nothing from that pitcher's line placement." D2 keeps that exclusion and
   separates what was conflated with it: the executable decision still freezes and is still
   scorable for outcome and CLV. Only the placement comparison against the simulated main line
   is excluded, because that comparison presumes we know which rung the book called main.

D3 The 2026-07-27 protocol is COMPLETE at sections A, B, C, D. Per B5 the amendment window
   closes the moment the first qualifying capture is received; anything found after that is
   logged and deferred to the next untouched slate.

Window state: STILL OPEN - no qualifying capture has been received for 2026-07-27.

### 2026-07-27T04:14:43Z — KSIM-0727-U01: user-supplied capture, STALE PRIOR SLATE, no qualifying quote

First USER_SUPPLIED_OPPORTUNISTIC_CAPTURE for 7/27. Phase 1 unaltered, C01 untouched, both still
verifying. Real money still $0, unauthorized.

  record   data/mlb/props/simulated/2026-07-27_KSIM_phase2a_user01.json
  sha256   09a3634406c33b32a8d08fc10e363de280e85bacde098e86f17f96b252640963
           (that hash covers THE RECORD. The screenshot itself has NO hash - see below.)

CLASSIFICATION ACCEPTED AND INDEPENDENTLY CONFIRMED.
  SOURCE_RESPONSE SUCCESS | SLATE_MATCH FALSE | STATUS NO_QUALIFYING_MARKET
  REASON STALE_PRIOR_SLATE_WITH_BLANK_PRICES | qualifying 7/27 quotes 0 | executable decisions 0

MECHANICAL VERIFICATION, not eyeballing. The 30 pitcher names visible in the image were compared
against the frozen 7/27 board and against data/mlb/props/2026-07-26_kboard_full.json:
  overlap with frozen 2026-07-27 : 0
  overlap with stored 2026-07-26 : 30 of 30, with ZERO on the 7/26 board absent from the image
                                   and ZERO in the image absent from the 7/26 board
This is not "partially stale." It is a wholesale rendering of the prior slate - the same thirty
arms, none added, none dropped. Corroborated by arms already on our 7/26 record: Jose Soriano
(the still-pending 7/26 play) and Fedde, Freeland, Avila and Baz (the four short-line arms named
in the 7/27 guard note).

TWO INDEPENDENT DISQUALIFICATIONS, either one sufficient:
  1. WRONG SLATE - none of the 30 arms start on 2026-07-27.
  2. NO PRICES - Under and Over are blank for every book column. Line-only. Even on the correct
     slate this fails C7: a line without both prices is not a FIRST_CAPTURED_COMPLETE_QUOTE.

EVIDENCE COULD NOT BE HASHED - retention gap, logged OPEN. The screenshot arrived as inline
conversation content, not as a file. A filesystem search over /root/.claude, /tmp/claude-0 and
/tmp for images created after 03:00Z returned nothing, so there is no artifact to hash. NO HASH
IS RECORDED. A fabricated digest would be far worse than an absent one, and this is exactly the
shape of the fabricated-bundle metadata caught earlier today (a 63-character "SHA-256" for a file
that did not exist). A5 and C5 require the original file preserved and hashed; this capture does
not meet that bar. Retention needs the operator to supply the image AS A FILE - the only current
copy is the conversation transcript, which is outside our control.

SCOPE, per C3. This is ONE aggregator page rendering five book COLUMNS, not five source
responses. It establishes only that THIS source had not populated a qualifying 7/27 strikeout
board at received_at_utc. It does NOT establish that no sportsbook had 7/27 markets. DK, FD,
MGM, BR and CZR remain CAPTURE_NOT_RUN as individual sources; no per-book NO_QUALIFYING_MARKET
or ACCESS_BLOCKED status was written from this image.

The displayed numbers are NOT 7/27 lines and are never to be described as such. They were not
transcribed into the record: they carry no permitted analytic use, and copying 150 cells out of
an image would add error for no purpose. Preserved as stale-source evidence only.

B5 / D3 AMENDMENT WINDOW REMAINS OPEN - this is not a qualifying capture.

### 2026-07-27T04:27:25Z — evidence recovery FAILED (no file); D1-R applied; 7/27 window CLOSED

Phase 1 unaltered; C01 and U01 untouched, all three still verifying. Real money $0, unauthorized.

EVIDENCE RECOVERY ATTEMPT FAILED - NO FILE ARRIVED.
  record  data/mlb/props/simulated/2026-07-27_KSIM_U01_evidence_recovery_attempt01.json
  sha256  90145e1166834545c91ac526ec9822428a33e45dee357a8aea56172a4edbc155
The operator reported recovering the original PNG and asked that it be downloaded, re-attached,
hashed, and accepted only on a match. No file reached this environment. Searched the session
uploads directory (still only the four items from 01:42Z), all of /root/.claude, /tmp and
/home/user by image extension, and the whole filesystem for any file of exactly 200437 bytes.
All empty. There is also no tool here for retrieving a file from an external upload workspace -
a file must be attached to this conversation to be reachable.
  NO DIGEST IS RECORDED AS RECOMPUTED. By the operator's own rule - recompute locally, accept
  only on a match - the absence of a file means there is nothing to accept. I did not send the
  drafted text asserting the PNG "is attached as a file," because it was not.
  The operator-supplied expected digest bccfc52c...943088 IS recorded, explicitly UNVERIFIED, and
  it is well-formed at 64 hex chars (unlike the 63-char bundle digest caught earlier today).
  Committing it BEFORE any file exists here is deliberate: a later receipt can then be checked
  against a value fixed in advance.
  U01 is unchanged - observed_at_utc, classification and eligibility all stand. Retention gap
  STILL OPEN.

D1-R APPLIED. D1 as committed at 4cb78c0 let an in-image clock or trustworthy metadata override
the arrival stamp. That exception is REMOVED: received_at_utc is now the UNCONDITIONAL
prospective-eligibility timestamp. user_reported_capture_time and image_metadata_time are still
recorded as provenance but decide nothing. This is one-directional - it closes every route by
which a capture could be argued earlier than its arrival, so it can only make qualification
harder, never easier, and cannot be used later to rescue a late capture. U01 is unaffected: its
observed_at_utc already came from received_at_utc under D1's default branch.
  Note: the unconditional form was NOT already committed. The operator's message allowed for
  that possibility; it was not the case, so it was applied here rather than merely marked.

WINDOW CLOSED - AND THE BASIS MATTERS. The 2026-07-27 amendment window is CLOSED as of this
commit, by OWNER DECISION. It is NOT closed because B5 fired. B5/D3 close the window on the
first QUALIFYING capture, and that trigger never fired - U01 was correctly NO_QUALIFYING_MARKET
with zero qualifying quotes and zero executable decisions. So the window standing open was the
rule working as written, not the inconsistency it was described as. Recording "closed per B5"
would put a false trigger in the record; the honest entry is owner decision with the trigger
explicitly marked not-fired.
  Final 7/27 protocol: sections A, B, C, D (incl. D1-R) and E.
  No further 2026-07-27 methodological amendments are permitted. Later discoveries belong to the
  next untouched slate. If the PNG arrives it may be attached as supplemental byte-level
  evidence, but it cannot alter U01 and is not an amendment.

SUBSTANTIVE FINDING UNCHANGED: exact 2026-07-26 slate (30 of 30), blank Under/Over across every
book column, zero overlap with the frozen 7/27 board, no executable K-prop capture.

### 2026-07-27T04:34:00Z — 7/26 model re-run: reproduces exactly; still ungradable

Ran harness/shadow_kboard_0726.py over the stored 2026-07-26 board. No engine change, no ledger
change, no gate movement. Real money still $0, unauthorized.

RESULT REPRODUCES THE RECORD EXACTLY. 20 permitted rows priced, 2 plays selected:
  Jose Soriano  OVER 4.5 @ -166 (FD)  EV +0.073  edge +0.046  p 0.670  weight 1.0
  Erick Fedde   OVER 2.5 @ +106 (FD)  EV +0.469  edge +0.227  p 0.713  weight 0.5
Skipped: 10 QUARANTINED by T3 dispersion, 9 line-only (no priced cell), 3 not on the pre-slate
card, 2 with no pre-slate E[K] (gs=0 against the >=5 floor).

ONLY DIFFERENCE vs the committed output: a p_push field, 0.0 on both rows. That is the 7/27
push-term fix propagating into a script that predates it. Both plays sit on half-point lines, so
p_push is exactly 0.0 and every other field - book, side, line, price, p, edge, EV, disp, weight
- is byte-identical. The fix being a proven no-op on the existing record is now demonstrated on
this board too, not just asserted.

THE CURRENT POLICY WOULD PRODUCE ONE PLAY, NOT TWO. shadow_kboard_0726.py calls
engine.kprops.select_play directly, while the <=3.5 K short-line guard lives in
harness/ingest_kquote.py - so this script predates AND bypasses the guard. Under dp-2026-07-27:
  Soriano OVER 4.5  -> passes the guard
  Fedde   OVER 2.5  -> BLOCKED by the short-line guard, and separately trips the R5 audit
                       threshold at |EV| 0.469 > 0.35
Fedde is the exact defect the guard was written for. The shadow output is a faithful replay of
what the OLD selector did on 7/26 and must not be read as what the current one would do.

STILL NOT GRADABLE. results.csv holds 1,569 finals, latest 2026-07-25; zero rows dated
2026-07-26; no 7/26 box file on disk. A statsapi fetch for the 7/26 schedule+linescore returned
HTTP 403, consistent with the perimeter blocking observed in C01 - retried per C1, which permits
it, and it failed again. So Jose Soriano OVER 4.5 (LAA@SF) remains the one pending gate-eligible
K play, and the healthcheck warning about it stands.

NOTHING ABOUT 7/26 OUTCOMES IS KNOWN HERE. The re-run re-prices a board; it does not observe a
result. No win, loss or push may be inferred from it.

### 2026-07-27T04:52:00Z — 7/26 GRADED from pasted box scores; Soriano WINS; healthcheck 0 warn

Phase 1, C01 and U01 all untouched and still verifying. Real money still $0, unauthorized.

SOURCE, and its limit stated first. User-pasted MLB gamefeed box scores, 15 games, 7/26/2026.
This is a SINGLE SOURCE - it is NOT the 2-of-3 resolution the standing doctrine asks for after
the stale/home-away-swapped statsapi incident. What it does have is INTERNAL corroboration: the
Angels team-pitching SO row reads 10, and the six individual Angels pitchers sum to
5+1+1+2+0+1 = 10. Soriano's 5 SO is therefore confirmed by a total computed independently of his
own line. Slate identity also checks out: 15 games in the paste, and the 30 starters match the
stored 2026-07-26 K board exactly. Graded on that basis, with the single-source limitation
recorded on every row rather than glossed.

K-PROP GRADED. Jose Soriano OVER 4.5 K @ -166 (FD), weight 1.0.
  actual: 5.0 IP, 3 H, 3 BB, 5 SO, 85 NP  ->  5 > 4.5  ->  WIN
  P/L +0.60 (100/166 = 0.60241, 2-dp settlement convention)
  kprops_paper: 4-5 -1.61u -> 5-5 -1.01u, pending 0

ML ROWS GRADED, both losses.
  COL +265 (COL@MIL, final 2-11) LOSS -1.00
  NYY +140 (NYY@PHI, final 4-11) LOSS -1.00
  ml_ev_tracking: 2-1 +1.40u -> 2-3 -0.60u, ROI -12.0%, pending 0
  n=5. Still a number, not evidence.

THE GATE DID NOT MOVE, AND THAT IS CORRECT. Soriano was registered before
decision_policy_version existed, so it is UNTAGGED by construction and no tag was invented (R1).
It lands in the HISTORICAL audit, not the prospective gate.
  prospective : 0/100 under dp-2026-07-27   (unchanged)
  historical  : 9 -> 10 settled, 4-5 -> 5-5, -1.61u -> -1.01u
  retrospective short-line statistic: 8 of 9 -> 9 of 10 (Soriano's 4.5 clears the 3.5 guard;
  Buehler O 3.5 remains the only blocked row)

MY ERROR, CAUGHT BY A TEST. My first grading pass BUILT A FRESH graded row instead of preserving
the registration row, silently dropping edge, ev_per_unit, disp and first_pitch_utc. The
ingest regression caught it immediately - it compares 15 as-registered fields against the ledger
and those fields had vanished. Reverted from backup and re-graded so the graded row IS the
registration row plus grading fields, with an assertion that no as-registered key is lost.
Grading must never destroy the record of what was registered.

TWO TESTS UPDATED, NEITHER WEAKENED.
  policy_gate self-test restructured into STRUCTURAL invariants (true forever: prospective ==
  count of tagged rows, no invented tags, void accounting, settled == W+L, stored string ==
  computed, retrospective stays flagged exploratory) and a KNOWN_LEDGER snapshot that pins the
  current record. Updating KNOWN_LEDGER is now an explicit act a commit must justify; its job is
  to make an UNANNOUNCED ledger change fail loudly. It did exactly that here, failing on
  "historical settled changed: 10" before I had written a word about the grade.
  test_ingest_kquote now searches plays_pending AND graded for the Soriano row. Pure location
  fix - all 15 field comparisons are untouched, and they only still pass because the re-grade
  preserves every as-registered field.

healthcheck: 0 fail, 0 WARN. The standing "kprop pending plays from past dates" warning is
cleared - there are no pending plays left.

STILL OPEN, unchanged by this: no closing price was captured for any of the three graded rows,
so CLV remains uncomputable and E3/E4 stay blocked. results.csv is NOT backfilled with 7/26
finals; only the three ledger rows were graded.

### 2026-07-27T05:06:00Z — 7/26 settlements upgraded to multi-source; a live duplication bug found

db00e00 is NOT rewritten - its one-source limitation stands exactly as written (R6). This appends
verification on top. Phase 1, C01 and U01 untouched. Real money still $0, unauthorized.

  record  data/mlb/box/2026-07-26_grade_verification.json
  sha256  8497bd5a6b53cf89e86e62211eddd23ce2485c71105dafe45da6df8c5159f456

MY PHRASING WAS WRONG AND TACO CAUGHT IT. db00e00 said the Angels team SO total agreeing with the
six individual pitcher entries "confirmed" Soriano's 5 SO "independently". It does not. That is
an INTERNAL CONSISTENCY CHECK, not independent corroboration: both values may derive from the
same underlying box-score data, so their agreement rules out a transcription or arithmetic slip
WITHIN that one source and rules out nothing whatever about the source itself. Calling it
"independent" overstated the evidence - the exact error class this project keeps catching. What
it established: self-consistency of the one paste. What it never established: that the paste was
right.

SETTLEMENTS UPGRADED - values unchanged, evidence standing raised.
  Soriano OVER 4.5 @ -166   CBS + Reuters agree 5.0 IP, 3 H, 3 BB, 5 SO (CBS also 85 pitches)
                            VERIFIED_2_SOURCE   WIN  +0.60u  unchanged
  COL +265 (COL@MIL)        CBS + ESPN agree MIL 11, COL 2
                            VERIFIED_2_SOURCE   LOSS -1.00u  unchanged
  NYY +140 (NYY@PHI)        CBS + ESPN + MLB agree PHI 11, NYY 4
                            VERIFIED_3_SOURCE   LOSS -1.00u  unchanged
kprops_paper stays 5-5 -1.01u; ml_ev_tracking stays 2-3 -0.60u. No gate, verdict or record moves.
"Never grade from a single endpoint" is now SATISFIED for these three rows. It was not satisfied
at db00e00, which said so at the time.

ATTRIBUTION, stated plainly: the multi-source reads were performed by the OPERATOR and reported
here. This environment did NOT fetch CBS, Reuters, ESPN or MLB - egress is blocked, and a further
statsapi attempt at 04:34Z returned 403. The upgrade rests on the operator's reported reads,
recorded as such, not on anything observed here.

A LIVE DUPLICATION BUG, found while checking the assertions Taco asked for.
harness/ingest_kquote.py:379 built its dedup key set from plays_pending ONLY. A graded row LEAVES
plays_pending - so from the moment Soriano was graded this morning, re-running --register on the
7/26 drop would have seen "not already pending" and appended him a SECOND time, duplicating him
across graded + pending. Confirmed reproducible against the live ledger before fixing. The dedup
now spans plays_pending + graded. Note there is no row_id in the ledger schema; (date, normalised
pitcher) is the identity this write path has always used, so it is the identity used here - not
an invented field.

THREE ASSERTIONS ADDED TO THE REGRESSION, and they can fail.
  1. Soriano appears EXACTLY ONCE across plays_pending + graded.
  2. No row identity appears in BOTH collections.
  3. All 15 registration-field comparisons run and are value-identical - the COUNT is asserted,
     so a future edit cannot quietly delete a comparison and still report PASS.
Taco's point was exactly right: searching both collections with next() takes the FIRST match, so
a duplicated row passed silently. Proved by injection on an in-memory copy, never touching the
real ledger: duplicating Soriano across graded+pending trips both assertions 1 and 2; duplicating
him twice inside graded trips assertion 1. Under the old lookup, the first case reported PASS.

## 2026-08-04 — date-safe V13 historical replay runner (owner spec)

Built harness/run_v13_historical.py: the CORRECT "full sims on all data" the owner asked for — a
date-safe HISTORICAL REPLAY, not a loop of harness/daily_card.py over past dates. daily_card reads
every final currently on disk with no historical date filter, so looping it backward is look-ahead
leakage. This runner reads ONLY data/backfill/mlb/2026/features.csv, whose rows are the strict
as-of inputs frozen for each game (the backfill window ends 2026-07-19).

What it fixes vs engine/score_and_calibrate.py (the prior scorer):
  - sims/game CONFIGURABLE (--sims-per-game, default 30000; validated at 2k and 30k, 100k capable).
    score_and_calibrate hardcoded 4000.
  - PER-GAME seed = 722 + int(gamePk): each game's result is independent of row order and of
    parallelism. score_and_calibrate uses one sequential RNG stream, so per-row probs shift with
    order. Selftest proves same-seed determinism + order-invariance.
  - DATE-ORDERED expanding-weekly OOS calibration (temperature T fit on strictly-prior weeks),
    never a random split on the scoring rows.
  - FULL simulated run arrays -> ML win prob, RL cover (±1.5), projected away/home/total, MC SE,
    and a PIT-style totals check. score_and_calibrate emitted ML only.
  - The Phase-4 candidate d_logistic_2f is computed ONCE per row, deterministic, never simulated;
    config double-hash-verified (canonical 132523ac / file-byte eede422d) and refused on drift.

30k run over 1,475 eligible games (13.6s): ALL Brier 0.2527 / logloss 0.6996 / acc 53.0% (home
base 0.522); both-SP subset n=1322 Brier 0.2496 / acc 54.0%; ROLLING OOS n=1242 raw Brier 0.2467 /
acc 55.2%, calibrated 0.2471 — temperature scaling did NOT improve OOS Brier here, so the raw sim
is already ~calibrated on this window. Candidate populated on 1460/1475 (15 honest nulls where team
form is incomplete). Output: data/mlb/evaluations/v13_full_30k.jsonl, one auditable row per game
(gamePk, date, inputs_hash, model_hash, features_file_sha256, seed_base+game_seed, sims, hfa,
sp_mature, full v13 block, candidate, market, outcome).

HONEST NULL, not a broken join. Same-book market benchmark is available on 0/1475 games: the only
same-book close ML on file is 7/24–7/25 (30 rows), which is AFTER the 7/19 feature freeze, so it
cannot overlap the replay window. Verified the join key (game_id split vs gamePk) is correct; the
windows simply don't intersect. No cross-book de-vig was used (that would be an invalid ~1%-hold
market prob). Totals are scored at the REALIZED total as a distribution/PIT check and LABELED as
such (p_sim_over/eq/under_realized) — not a market over/under settlement, because the frozen
features carry no market total line.

GOVERNANCE. Registered the new sim source in harness/model_registry.py as
ml.v13_1.hist_replay.hfa1005.n30000.rng_gamePk (role HISTORICAL_REPLAY_RUNNER) and pinned its hash
(12 sources pinned). HFA is imported from engine/hfa.py (CURRENT=1.005), no stray literal. Runner
is DIAGNOSTIC — never a production card, changes no gate, promotes nothing. Healthcheck HEALTHY
(0 fail). Gate stays 0/100 NO_PROMOTE; model-authorized ledger $0; paper only. Not pushed.

## 2026-08-06 — workflow validated; 8/4+8/5 finals ingested; 8/4 graded; 8/6 card prepped

WORKFLOW VALIDATION (owner request). All selftests PASS (run_v13_historical, model_registry,
ml_p4_forward). Independent full re-run of the 30k historical replay reproduced the committed
v13_full_30k.jsonl BIT-IDENTICALLY (canonical sha ex-built_utc 08033edb3d33...): per-game-seed
determinism holds end-to-end on all 1,475 games.

FINALS INGESTED (WebSearch multi-source, gamePk-keyed from MLB.com gameday URLs). 8/4: 15/15
matching the frozen slate matchups. 8/5: 15/15 series continuations. Contiguity SOLID 7/18 -> 8/5.
ECHO GUARD: three first-pass 8/5 scores were 8/4-echoes surfaced by the search layer and were
CORRECTED by dedicated recap searches BEFORE recording (NYM@CLE 6-5 in 10, not 6-2; MIN@KC 2-1,
not 8-6; ATH@CIN 3-2, not 5-4). PIT@MIL 4-2 was verified genuinely identical both nights (Jones
Tue / Skenes Wed). Evidence files record the guard. ml_asof rebuilt: 1719 rows, vintage
51c9bf44eacc, rebuild check IDENTICAL.

8/4 GRADED (all 15, single-book benchmark from the frozen board, book UNRESOLVED, ~4.5% hold).
Home teams won 11/15 (favorite-friendly night — the mirror of 8/3's road sweep). Market beat the
candidate on BOTH metrics this slate: Brier 0.2266 vs 0.2427, accuracy 10/15 vs 8/15. The
candidate's compression cost it on a night the favorites delivered. V13 incumbent null on all 15
(gamePk unresolved at freeze — documented Phase-4 limitation). Registry now 71 forecasts / 67
grades, chain intact. Cumulative candidate ML: n=54, Brier 0.2530, home 27/54 — DIAGNOSTIC only,
benchmark heterogeneous across dates, clean promotion n still 0.

8/6 CARD PREPPED (PRE-ODDS). Slate assembled by per-series WebSearch confirmation — no single
source enumerated the day. 8 games confirmed (NYY confirmed OFF; 12 other idle teams presumed
travel-day, caveat recorded: a missed Thursday opener is possible and the owner's board is the
completeness authority). Probables named for 6 games; LAA/ATH/SD/AZ starters TBD -> CAP.
FULL-TRACKING card built (cards/2026-08-06_card.json, V13 n=30000, no lines — odds board absent).
P4 forecasts BLOCKED until the owner's frozen odds board arrives (media line BAL -163 seen and
recorded as context ONLY, never a board quote). Gate 0/100 NO_PROMOTE; model ledger $0; not pushed.

## 2026-08-07 — 8/6 board processed; THREE season-data errors found and fixed via records cross-validation

The owner pasted the full 8/6 board POST-FINAL (close quotes + finals + statcast gamefeeds). Frozen
as data/mlb/odds/2026-08-06_gameboards.json. Because the quotes arrived after outcomes, NO
prospective P4 forecasts were generated from it — retrospective diagnostics only.

MY 8/6 PREP WAS WRONG IN TWO WAYS (corrections sidecar 2026-08-06_prep_corrections.json; frozen
artifacts untouched): the slate was 11 games, not 8 (missed WSH@PHI G4of4, DET@SEA G3, TOR@CHC
one-off — the per-series search enumeration inferred series ends wrongly; the recorded caveat
'owner board is the completeness authority' fired exactly), and the card's CIN probable was Rhett
Lowder while the actual starter was Andrew Abbott (graded as-is with SP-MISMATCH flag).

RECORDS CROSS-VALIDATION CAUGHT REAL DATA ERRORS. Recomputing all 22 board teams' pregame records
from results.csv: 19/22 exact, AZ/CHC/CWS each off by one game. Targeted WebSearch verification
resolved ALL THREE, every one in the WebSearch data-hole-closure cohort:
  - 7/29 NYY@CWS: stored NYY 5-4; ACTUAL CWS 6-5 in 12 innings (ESPN 401816316, b-almanac).
  - 7/29 CHC@STL: stored CHC 4-3; ACTUAL STL 3-2 in 10 innings (MLB gameday 823022).
  - 7/23 AZ@STL: ABSENT (7/23 was a partial-capture day); ACTUAL AZ 10-6 (ESPN 401881162) — appended.
Root cause: two extra-innings games captured at wrong regulation-era scores + one dropped game on a
partial day. Post-fix: 22/22 records match exactly. Residual: partial-capture days 7/16(1)/7/23(5)/
7/27(11)/7/30(10) and 8 teams not on the board (LAD NYY SF STL TB TEX COL HOU) remain unvalidated.

DOWNSTREAM CORRECTIONS (append-only): two 7/29 grades had flipped outcomes -> superseding grade
rows G2-* appended (chain intact, 69 grades); metric_corrections_2026-08-07.json recomputes the
31-game cohort: candidate Brier 0.2555->0.2577 (12/31), market 0.2478->0.2547 (16/31), paired
dBrier +0.00765->+0.00304, t-CI [-0.0158,+0.0218] — still crosses zero, still DESCRIPTIVE.
Cumulative candidate ML: n=54 Brier 0.2543 (was 0.2530), home 29/54. CF no-refit replay unaffected
(it compared inputs, not outcomes). ml_asof rebuilt: 1731 rows, vintage 831669da1356.

8/6 INGESTED (11 finals, owner-board source, ws-style keys + gamePk 823754 for PIT@MIL; CWS@BOS
12-11 in 13, TOR@CHC 3-2 in 11). Contiguity 7/18 -> 8/6. CARD GRADED retro-diagnostically
(2026-08-06_card_scoring.json; immutability: signed commit cb44a80 06:59:46Z, first pitch 16:35Z):
V13 Brier 0.2537, 3/8 sides; board market 0.2305, 5/8; V13 total leans 2/7 on a night with a
23-run 13-inning Fenway game and 19 runs in Cleveland; market went 7/11 on the full slate.
Gate 0/100 NO_PROMOTE; model ledger $0; not pushed.

## 2026-08-08 — 8/7 finals ingested; 8/8 card + parlay options (pre-pitch, odds pending)

8/7 FINALS: full 15-game slate enumerated team-by-team (all 30 accounted — the 8/6 miss does not
repeat), 13/15 gamePk-keyed. Three summary-text-only scores were re-verified via dedicated recap
searches BEFORE recording (TOR@PHI 5-4 ninth-inning survival; LAD@AZ 4-3 Waldschmidt walk-off-HR
off Diaz; MIN@MIL 8-6 comeback) — the 7/29 extra-innings lesson is now standard procedure.
Contiguity 7/18 -> 8/7. ml_asof rebuilt: 1746 rows, vintage a0c149a6f45a.

8/8 CARD (15 games, generated ~18:10Z, earliest pitch 19:05Z — pre-pitch): V13 n=30000 card run.
Probables from WebSearch; CAP on NYM@PIT (Stock no-id), MIN@MIL (starters unconfirmed), HOU@SD
(Blanco no-id), DET@SF (Jobe no-id). Notable trades visible: Skubal->LAD, Scherzer TOR, deGrom TEX.

PARLAY CARD (data/mlb/forecasts/2026-08-08_parlay_card.json, PAPER/ADVISORY only): owner rule
'actual win probability over EV'. Eligible legs = V13 favorite sides, both-SP-mature games only
(CAP games excluded). Top legs BOS 60.9 / CHC 60.2 / ATL 57.9 / PHI 57.3 / CWS 56.4. Best combos:
2-leg BOS+CHC 36.7% (BE +173); 3-leg +ATL 21.2% (BE +371); 4-leg +PHI 12.2% (BE +722); alternate
4-leg 11.3% (BE +788). NO ODDS BOARD captured -> EV and the hybrid probability+value ranking are
BLOCKED pending the owner's board; break-evens state the minimum parlay price for +EV IF the model
probabilities are right. No wagers; ledger $0; gate 0/100 NO_PROMOTE. Not pushed.

## 2026-08-08 — standing data-acquisition authorization; injury/roster feed layer

Owner granted a STANDING authorization to acquire public sports data (power ratings, advanced/
team/player metrics, rosters, depth charts, injury/rest/lineup status, statistics) to improve
model accuracy — "autonomous support moving forward." Recorded verbatim in
docs/authorizations/2026-08-08_data_acquisition.json.

CONSTRAINTS HELD REGARDLESS OF THE GRANT (this is data autonomy, not a licence to invent or to
bet): R1 — acquire REAL data from identifiable sources, freeze with provenance (source/URL/
retrieved_utc/confidence), never fabricate; low-quality returns flagged/omitted, not laundered
(cf. the rejected '5-2 records' WebSearch). NETWORK — sanctioned channels only (WebSearch/WebFetch);
the egress-proxy 403s are policy and never routed around. R3/R6 — no silent mutation of frozen
models/cards; new data enters as versioned inputs + reconciliation sidecars, and any model that
consumes it is a NEW hashed identity. MONEY/GATE — data only; gate stays 0/100 NO_PROMOTE, ledger
$0, push still needs separate authorization.

Built the feed layer: data/feeds/{mlb,wnba}/ + data/feeds/MANIFEST.json (schema, provenance
classes, integration policy — V13 is lineup/bullpen-blind, WNBA log5/Massey are injury/rest-blind;
acquired data is surfaced as stale-input flags, not silently consumed). Launched the
acquire-injury-roster-data workflow (wf_50b8a5df-3d1): injuries/rosters/lineups/rest across the
8/8 MLB+WNBA slate, a deep dive on the Storm@Portland 31pp market-vs-rating divergence, and a scout
of standing sources. Findings freeze into data/feeds/ on completion. Gate untouched; not pushed.
