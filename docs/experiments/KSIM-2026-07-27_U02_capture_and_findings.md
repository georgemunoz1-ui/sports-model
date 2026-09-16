# KSIM-0727-U02 — Phase-2A capture, and what it exposed

> **CLASSIFICATION (2026-07-28, owner-authorized): `EVIDENCE_DEFICIENT_SHADOW`.** This capture did
> **NOT** qualify: C5 item 5 (visible slate date) failed, the frozen protocol contains no exception
> for independent slate identification (D2 built a degraded path for item 6 only), and the
> amendment window closed at `af12e52` twelve hours before this capture arrived (D3/E2). The title
> of commit `7efb9b9` ("first qualifying Phase-2A capture") is superseded by
> `data/mlb/props/evidence/2026-07-27/KSIM-0727-U02_capture_CLASSIFICATION.json`. Status:
> TIMING_ELIGIBLE 23/23 · EVIDENCE_COMPLETE no · CLASS_B_QUALIFIED false. The four decisions are
> permanently barred from the prospective ledger and gate for this slate; any outcome/CLV work on
> them is descriptive shadow analysis only, never pooled. §2's "referred to the protocol owner"
> framing is likewise superseded — under the frozen text there was nothing to adjudicate.

**Phase 1 is not modified.** `data/mlb/props/simulated/2026-07-27_KSIM_phase1.json` verified at
`7f827fd0014e5835ec3bf3572bbe1ff36dce452d5e0a55b735d04fe665c12d2f` before and after this work.

| | |
|---|---|
| capture id | `KSIM-0727-U02` |
| class | **B — `USER_SUPPLIED_OPPORTUNISTIC_CAPTURE`** |
| `received_at_utc` / `observed_at_utc` | `2026-07-27T16:38:58Z` |
| `source_quote_time_utc` | `null` — board displays none |
| decisions frozen at | `2026-07-27T16:48:48Z` |
| decision record sha256 | `60fe448c01937410946d9c1d2c01322f70c47dbb188bdfbf0a92415d1f1279e2` |
| eligible | **23 of 23** — earliest first pitch `18:35:00Z`, 116 min after arrival |
| fired | **4** |
| staked | **$0.00. `real_money.authorized = false`.** |

This is the **first capture for this slate carrying complete two-sided prices**. Every prior
attempt was `ACCESS_BLOCKED` or `NO_QUALIFYING_MARKET`.

---

## 1 — Why this is class B and not class A

C2: **a single screenshot is not a scan cycle.** No source was queried by us in A1 order; one
image arrived. Six book columns inside one aggregator page does not make it a six-source cycle,
and the prices are the aggregator's *rendering* of each book rather than each book's own
response. Recorded as `book_attribution_source: AGGREGATOR_DISPLAYED`.

Consequences, per C4/C8: it **may** freeze executable decisions, it may **never** be presented as
the hierarchy-selected primary comparison, and it is **never pooled** with class-A results.

## 2 — Open deficiency: C5 item 5 is NOT satisfied

**The K-board image does not visibly display a slate date.** A date control is partially visible
top-right but is cropped and illegible. Confirmed on independent re-read.

The three game-board images in the same upload are stamped `2026-07-27`, and all 24
pitcher/matchup pairs on the K board correspond exactly to the frozen 7/27 slate. That is strong
corroboration — but C5 requires the date be visible **in the image**, not supplied alongside it.

This is recorded as a **failure of the stated test**, not argued away. C5 item 5 is the exact
guard that classified `KSIM-0727-U01` as `STALE_PRIOR_SLATE`. Reinterpreting it at the first
moment it would block a capture, in the direction that unblocks it, is precisely the move the
protocol exists to prevent — and E2 forbids amendment. **Referred to the protocol owner.**

Because the decision record is hashed and committed *before* first pitch, adjudicating this
either way afterwards cannot be outcome-dependent: voiding the set costs nothing, and the frozen
content is fixed either way.

## 3 — C1, the headline comparison, is EXCLUDED

The aggregator designates no book's main line, so every pitcher is **`MAIN_LINE_UNRESOLVED`**.
Per D2 that permits a frozen decision and outcome/CLV scoring **against the identical book and
line**, but excludes the simulated-main-line placement comparison.

**So C1 — frozen mechanical line vs first captured complete quote, the comparison KSIM was built
around — cannot be scored from this capture.** C2 (`VERIFIED_OPENER`) remains **empty**. What this
capture supports is the executable-decision test, not the line-placement test.

## 4 — Board integrity

- **T1 (hold 2–12%)** — **PASS, 0 failures across 110 price pairs.** Each book shows its own tight
  characteristic band: DK 5.45–6.21%, FD 5.85–6.17%, MGM 5.76–7.74%, BR 6.77–7.31%, CZR 5.88–8.21%.
  **Audit correction 2026-07-28:** T1 validates only broad two-sided price coherence. It detects
  some gross price errors, does not validate line values at all (the line never enters the hold
  formula), and cannot establish digit-perfect transcription — demonstrated: +124 misread as +134
  passes at 4.1% hold. Transcription confidence rests on the re-reads, and all reads to date are by
  the same model family (`REPRODUCED_BY_CORRELATED_READER` — see the transcription audit addendum).
- **T3 (cross-book line dispersion ≤ 1.0K)** — at tolerance, twice. Wheeler DK/FD/CZR 7.5 vs
  MGM/BR 6.5; Keller DK/FD/MGM/CZR 3.5 vs BR 4.5. Both minority rungs are priced like alt rungs
  (Wheeler MGM +130/−175, Keller BR −165/+123). Neither fired.
- **T4 (independent re-read)** — **PASS** on all four firing rows.
- Market-implied λ spread across books is ≤0.28K on every pitcher. The market is internally
  coherent, so the disagreements below are model-vs-market, not market noise.

## 5 — The four frozen decisions

| pitcher | side | book | line | price | EV | edge | disp | wt | mkt λ | model−mkt |
|---|---|---|---|---|---|---|---|---|---|---|
| Andrew Alvarez | OVER | BR | 3.5 | +100 | +0.431 | +0.215 | +1.36 | 0.5 | 3.52 | **+1.34** |
| David Peterson | OVER | MGM | 3.5 | +120 | +0.395 | +0.179 | +0.86 | 1.0 | 3.40 | **+0.96** |
| Tatsuya Imai | UNDER | FD | 6.5 | −150 | +0.292 | +0.175 | −1.59 | 1.0 | 6.24 | **−1.33** |
| Jack Perkins | OVER | MGM | 4.5 | −120 | +0.221 | +0.120 | +1.15 | 0.5 | 4.91 | **+0.75** |

Frozen per A7 the moment they qualified — no waiting for a better price. `select_play` was run
unmodified, and `E_K`/`gs` were taken **verbatim from the frozen artifact**; `proj()` was not
re-run, because recomputing after seeing the market would change the blinded inputs.

**These four are exactly the four largest model-market disagreements on the slate.** That is the
selector working as specified — it is a disagreement detector — and it is also, under R5,
precisely where defects live.

## 6 — The result that matters more than the plays

**Audit correction 2026-07-28 — "essentially unbiased" withdrawn.** Bias is an expectation over
repeated samples relative to truth; a near-zero cross-sectional difference from a constructed
market estimate on one slate does not establish it. The supportable statement: **on this single
slate, the mean difference between model E[K] and the constructed market-implied λ was near zero**
— +0.013 (proportional de-vig; +0.023 under power de-vig), median −0.026, mean|diff| 0.416 K,
n=23, cross-sectionally correlated, construction-dependent (Poisson inversion + de-vig choice),
exploratory (R4). On 19 of 23 the model sits within half a strikeout of the six-book consensus.
It is the first external comparison this engine has had — a comparison, not a measurement of bias.

The selector also stopped being vacuous. Against the self-consistent simulated line it fired
**0 of 23** (max |disp| 0.25K against a 0.8 floor). Against a real market it fires **4 of 23**.

## 7 — Defects surfaced (R5), stated at the strength the evidence supports

**D-B — low-GS upward bias. Mechanistic, and the better supported of the two.**
`gs<10` mean diff **+0.460** (n=4) vs `gs≥10` **−0.081** (n=19); corr(gs, diff) = **−0.300**.
The mechanism is visible in the code without reference to any outcome:
`etbf = (tbf + 24.0*3)/(starts + 3)` shrinks expected batters-faced toward a **full 24-batter
start** with a 3-start prior. For a swingman or short-leash arm that prior is a third of the
weight and inflates the workload he will actually get. Alvarez (6 starts, **7 relief
appearances**, raw 20.0 TBF/start → etbf 21.33) and Perkins (7 starts, **18 relief appearances**)
are both in this bucket and both fire OVER. The market at Alvarez 3.5 implies ~15 batters faced —
a bulk/short outing the prior refuses to price.
**n=4 in the low bucket. Under R4 this does not move a verdict.** It is a candidate defect for a
pre-registered experiment on a future slate, not a finding.

**D-A — pitcher logs are badly stale. Real, material, and NOT shown to cause the above.**
Median staleness **18 days**, mean 21.0, and **21 of 23 logs are ≥14 days old**. Max Fried's log
ends **2026-05-13 — 75 days before the slate**; Scherzer 47 days. At typical rotation cadence
that is three to four missing starts per pitcher.
Honest limit: **corr(stale_days, |model−market|) = −0.153** — essentially nothing, faintly the
wrong sign. Staleness is a genuine data defect that should be fixed on its own merits, but this
capture provides **no evidence it drives the disagreements**. Fried, the stalest log on the board,
sits −0.22 from the market.

**D-C — `information_cutoff_utc` is misleading.** The frozen artifact records
`2026-07-27T02:33Z`. No look-ahead occurred (R2 is intact — the data is old, not future), but the
field implies a data recency that does not exist. The cutoff was never the binding constraint;
log staleness was. Logged here per R6; **the frozen artifact is not edited.**

## 8 — Not done, and why

- **Not registered into `ledgers.kprops_paper`.** The prospective gate stays at **0/100 under
  dp-2026-07-27**. Registration would move it to 4 pending and is a separate, unapproved action —
  and with D-B open it is not obvious these should count. The decision record is hashed and
  committed before first pitch, so selectively registering later would be visible.
- **Zac Thornton not added.** He appears on the captured board at 4.5 across five books. He was
  excluded before freeze on GS=3 < the ≥5 floor, and `select_play` returns None for gs<5 anyway.
  Adding him because the market posted him would be post-hoc cohort expansion.
- **Sides and totals not priced.** The three game-board images are retained as evidence only.
  Sides remain DEAD (R3), totals NOT_READY. `ml_ev_tracking` is not run: it is unapproved, and its
  V13 P(win) input is ambiguous while **HFA-SPLIT** is unresolved (`v13_1.py:58` ×1.03 vs
  `daily_card.py:63` ×1.005). The **Best Odds** image is a cross-book best-price composite — a C7
  contaminated pair, unusable as a quote in this or any future unit.
