# PREGAME-BOARD-2026-08-30 — V3 (Full Decision-State Framework)

record_id: PREGAME-BOARD-2026-08-30-V3
issued: 2026-08-30 14:30 ET / 11:30 PDT
lineage: V1 (08:15 ET, registered FORECAST_V1) → V2 (13:40 ET, conflict resolutions) → **V3 (14:30 ET, framework upgrade — append-only; V1/V2 unchanged)**
ledger: $0 · wager authority: NO · paper only

V3 does not change any V1/V2 decision. It re-expresses the board in the full decision-state format (p_raw / p_market_no_vig / edge / uncertainty / data-quality / usable_edge), adds movement classification, the GSV@POR scenario engine, PIT lineage, and monitoring panels, per the newly adopted architecture documents.

---

## 1. WNBA — Decision-State Records

σ (margin SD) = 13.97 frozen. Model: wnba.rs.ff7_logit_ridge.v1_0.shadow (walk-forward brier 0.2112 vs base 0.2472, AUC 0.722). Feature cutoff 2026-08-27 ET → DATA_STALE declared. Calibrator: **DORMANT** (n=4 < 500 sample gate) → p_calibrated = p_raw.

| Game | p_raw | p_market no-vig | Edge | Uncertainty band | DQ × Unc | Usable edge | Decision |
|---|---|---|---|---|---|---|---|
| MIN @ ATL 3:00p | ATL .397 (ML) | ATL .4486 (−135/+114) | **−5.2pp ML / +14.3pp spread** (cover p .6425 = Φ(5.1/13.97)) | ±6pp (stale fatigue data) | 0.65 × 0.75 | **+6.9pp** | **LEAN ATL +2.5 (C-tier)** — edge lives in the spread, not the ML; divergence explicitly recorded |
| LAS @ SEA 5:00p | SEA .561 | SEA .5108 (−115/−105) | +5.0pp | ±7pp (coin-flip zone) | 0.65 × 0.70 | +2.3pp | PASS — below conviction floor |
| GSV @ POR 7:00p | GSV .747 | GSV .6369 (−198/+164) | +11.0pp raw → **≈0 scenario-adjusted** | ±10pp (rotation unknown) | 0.40 × 0.60 | ~0 | PASS — raw edge INVALID (post-cutoff roster news, §2) |
| CON @ DAL 8:30p | DAL .833 | DAL .8762 (−1050/+675) | −4.3pp | ±6pp | — | −4.3pp | PASS — market ahead of model on Griner/B2B news |

## 2. Scenario Engine — GSV @ POR

| Scenario | P | Model basis | Margin effect | Adj. p(GSV) | vs market −4.5 |
|---|---|---|---|---|---|
| Full rotation (model assumption) | — | p .747, GSV −8.1 | — | .747 | +11pp raw edge |
| 3 starters out — World Cup (CONFIRMED today) | 1.00 | ~40% usage / ~65 min redistribution; shrink to bench baselines | −6 to −9 pts | .53–.62 | spans the number → edge ≈ 0 |

The market's −5.5→−4.5 move sits inside the scenario band. Model and market agree once news is priced by hand → no bet. Assumptions declared PROVISIONAL; this is sensitivity analysis, not a hidden refit.

## 3. Market Integrity — Movement Classification

Snapshots: DK 04:12 ET capture (entry) + 13:40 ET re-verification (no material move).

| Move | Classification | Confidence | Evidence | Action |
|---|---|---|---|---|
| CON@DAL −9.5→−13.5 | new_information | 0.85 | Griner out + CON B2B + 2 departures, published before/during move | accepted, no contrarian play |
| GSV@POR −5.5→−4.5, tot 160.5→158.5 | new_information | 0.80 | 3 GSV starters' World Cup departures effective today | accepted |
| MIN@ATL tot 179.5→176.5 | unknown | 0.20 | no matching news (Jones out was 8/28, pre-open) | not faded; total not carded |
| KC@CLE ML −167→−180 | unknown | 0.18 | no 48h news; single-direction steam | PASS — unexplained steam not faded (audit clause) |
| TEX@MIL ML −173→−162 | unknown | 0.22 | MIL SP uncertainty plausibly related (partial) | WAIT on lineup card |
| PHI@LAA tot 8.5→8, ML −199→−186 | unknown | 0.20 | true movement (price+line both moved), no news match | PASS |
| BOS@NYY, PIT@STL tots 8.5→8 | unknown | 0.20 | BOS returnees are offense-positive — doesn't explain DOWN move | PASS / WAIT |

"Unknown" is a first-class classification, not a failure. No unexplained move is auto-labeled sharp action and none is faded. Cross-book dispersion: checked games within 1–2¢ of DK consensus except quarantined stale sources (Doc's).

## 4. MLB — Actionable Layer Blocked Slate-Wide (unchanged)

Block reason registered in V1: 0/14 SP_CONFIRMED (probable-only) + pitcher corpus ends 2026-07-19 → every starter slot routes to the CAP under merged P0 freshness rules. Entry prices recorded for CLV only; no simulated wagers. Grid (12:15p–7:20p ET): MIA@WSH PASS (SP conflict resolved V2 — Junk), COL@ATL PASS, BOS@NYY WAIT (Story/Anthony), SEA@TOR PASS, KC@CLE PASS, LAD@DET PASS (stale-source total conflict), SD@TB PASS, TEX@MIL WAIT, CWS@MIN WAIT (Buxton), PIT@STL PASS, HOU@NYM WAIT (CONVERGENCE_FAIL posture stands), BAL@ATH PASS, PHI@LAA PASS, CIN@CHC WAIT (Wrigley wind MISSING), **ARI@SF BLOCKED** (no DK line, starters TBD — reconciled, not dropped).

## 5. NFL / CFB

- **NFL: NO_FORECAST** — 53-man cutdown day; Week 1 opens Wed 9/9.
- **CFB early board (EARLY_FORECAST · NOT FINAL, Sep 3+):** Miami@Stanford −21.5→−24.5 (unknown 0.25); Coastal@WVU −17.5→−21.5 (unknown 0.20); UCLA@Cal +1.5→−1.5 flip (unknown 0.22); Clemson@LSU −10.5, tot 50.5→51.5 (new_info partial 0.5); Baylor/Auburn −7 (σ=18.385, two transfer-QB regimes); SMU@FSU SMU −2.5 (Jennings finger PROVISIONAL, FSU 1-0).

## 6. PIT Lineage · Monitoring · Execution

- **PIT:** decision_time 08:15 ET · entry prices ≤ 04:12 ET capture · re-verified 13:40 ET · feature cutoff 8/27 ET (DATA_STALE) · availability published 8/28–29 · closing lines recorded post-game → CLV computed after, never an input.
- **Feed health:** manual sweep (FU-1 adapter building) caught 1 schedule/board discrepancy (ARI@SF) ✓ · RJ-005 injury feed egress-blocked → scraped availability IDENTIFIED_UNCONFIRMED ✓ · 2 stale-source quote conflicts quarantined ✓ · no zero/extreme EV anomalies, no duplicate ids, no feature timestamp after decision_time ✓.
- **Execution realism:** entry ≤ decision_time satisfied. Latency ladder N/A at paper stage but mandatory for any future executable strategy (edge surviving only at 0s latency = rejected). Parlay: none (no straight bet above C-tier).

## 7. Tonight

Closing lines + all-sports results enter the CARD_UPDATE_PROTOCOL sweep (ET+PDT). Grading is descriptive only; CLV computed against the entries above; 8/30 board graded as registered (V1) with V2/V3 as append-only deltas.
