# KSIM-2026-07-27 — PROTOCOL ADDENDUM (Phase 1 accepted, artifact immutable)

Phase 1 is accepted and **immutable**. This document records protocol clarifications issued
after the freeze. It **does not modify, append to, or reinterpret** the frozen artifact.

| | |
|---|---|
| Phase-1 artifact | `data/mlb/props/simulated/2026-07-27_KSIM_phase1.json` |
| **Phase-1 sha256** | `7f827fd0014e5835ec3bf3572bbe1ff36dce452d5e0a55b735d04fe665c12d2f` |
| Verified unchanged | `sha256sum -c` OK at addendum time |
| Addendum issued | 2026-07-27, after Phase-1 acceptance |
| Engine commit | `6146baa` |

---

## 1 — The ±0.5 K band is not a confidence interval

The artifact field `simulated_line_ci` is **renamed for all reporting purposes** to
**DECLARED COMPARISON BAND** (equivalently, TOLERANCE BAND).

It was declared, not statistically estimated. It carries no coverage guarantee and must never
be described as a calibrated interval, and "the market opened inside the CI" must never be
reported as a coverage statistic. The correct phrasing is *"the opener fell inside / outside the
declared ±0.5 K tolerance band."* The artifact's own value already reads
`+/-0.5 K (one half-point rung) - DECLARED, NOT FITTED`; this fixes the vocabulary everywhere else.

## 2 — The −115 prices are a null assumption, not a forecast

The fixed `-115 / -115` pair is a **standardized null assumption** used to make the rows
well-formed. It is **not a price forecast**.

- **Do not score it for price-prediction accuracy.**
- Phase 2 must not compute simulated-minus-actual price error, price directional agreement, or
  any shading-accuracy statistic against it.
- **Target B measures mechanical line-placement error only** — the distance between the derived
  line and the actual opening line, in strikeouts.
- The artifact's `expected_shading_direction` is `NONE`, which is the null, not a prediction that
  books will price symmetrically.

## 3 — Independence claim, stated precisely

The earlier wording "the Tier-1 game-board exposure cannot leak into it" is **withdrawn as
overclaiming** and replaced with:

> The transformation from E[K] to the derived line contains no market input. Independence of
> E[K] itself depends on the frozen engine and its input lineage containing no betting-market
> variables.

### Supporting lineage

`proj()` reads exactly three things. Nothing else enters E[K].

| input | sha256 |
|---|---|
| `engine/kprops.py` | `72a30c2650b6c4dc6b2b6c2f8a57f1848b1e139909cf0ad7b0120441f7411b56` |
| `data/backfill/mlb/2026/pitchers.csv` | `a350ff454f247019e56bd39c6a6e2d393f0ffc5999cb079fb88be55a5e98d6a7` |
| 23 pitcher logs (composite) | `806e5cd2f0a7964900b421069b1bfe596ccc71e885dfa6bb30fb0a55bcd53f20` |

Composite = sha256 over `pid:hash` pairs sorted by pid.

**Schema audit.** `pitchers.csv` columns are `id, name`. Pitcher logs are
`date|ip|er|so|bb|tbf|gs` (7-field) or `date|opp|home|side|ip|er|so|bb|tbf|gs` (10-field).
No line, price, odds, total, moneyline or implied-probability column appears anywhere in the
lineage. The claim is therefore supported **for these inputs at these hashes** — it is a
property of the audited files, not a general guarantee.

### Per-log hashes

| pitcher_id | sha256 |
|---|---|
| `453286` | `8e549450fc17b2095c1e7ba96d14dc8e1d33c8d6d0ad52a8eeb5c2accc57bc8e` |
| `518876` | `61a2dcea0e4f572d3cf6ecb1b4a85fecc1703ef6ee3ede512e07b1300a7822c1` |
| `527048` | `dbef833deab4ce6fbd05c82ee8cd456730531ab65d3da88b717de6041acbaced` |
| `554430` | `c830dbfc7f8154fa2c63104e4369163113b9ad9a36257325634abc2b72adedcf` |
| `608331` | `dc1f63c83b20954cd53baece114f2fdb2dfde2dc25033052dd256fa04fcaa9cc` |
| `641816` | `2afbbe855e811c257790181edb40ce94e4d7e746c83e503f13867900962f8a38` |
| `656605` | `9a73cf8981e8bc2999c712f7458381f93171e22172a3dd22e48eab89a607d682` |
| `656849` | `3330c801b0087c50948775404a5c1ee429d0bde106e6d0d1a147600bbb0b4806` |
| `663969` | `3252674dac16a8df888265c249b3079694f7b35230eeceac1de65d2f66f26008` |
| `669461` | `30ee53a79591a66678dacfa81865f1dbb8feff79cc73e5b0df2eac9b5323104a` |
| `669923` | `828b7ea54bfc266f555abaa319e9ae923e3f645952becb90d4554d5f29f818ac` |
| `672456` | `20a5178b71d931f2b7c69f7f7d3f193f30aa4d7a2fbe7925f360961a1547fee9` |
| `674841` | `890ea5a6da962517ff9f954dc884fab002b67cb80623449b8142491a70e99461` |
| `677944` | `4f29ba1000e0f10a7b08acbc83e327a15119ad708d1e838f3120303ea19a787c` |
| `677958` | `4c7eb718a9afa3cea22b5016c14cbe2ff1758c46fe3c0a171be7ecfeb1702d85` |
| `678022` | `ef16f92ee1849f8a0240ba34f39331a6adb6963de8a7e17bbe9d69e1e44fcdda` |
| `680694` | `f64acfbe5f18c354d1a426847770f7517073905c0d432450974ff7bd6022b790` |
| `687075` | `bc9d0da449f53f4225dcb0c485927dff8f656acf65ccbf2fffb8c35b4b3ee2cf` |
| `695505` | `58824008b9195978f47542bb00598e561bee6b26631fd187d274c7bc23151e0c` |
| `700712` | `6ecdf0b0ca109bca226adf6aaebcecde8b3af09205482bb067bc80183b373b0a` |
| `702273` | `671c744b420b9522fc1cedd36b00772d12f10a645f6109846ecaba80e5bb4577` |
| `801139` | `617e3227243b65d0b979b080201bd38872344f8e701585dd73aace71118a0142` |
| `837227` | `44d80001a753991bb381b4b3e1182dd41398d2e52b6ca62f03c776d2efbcb583` |

## 4 — Phase 2 splits in two

**Phase 2A — before first pitch.** Capture opening markets and **freeze the executable selector
decisions**. This must be written and hashed before any game starts.

**Phase 2B — after games.** Append closing markets, results, innings, TBF, pitch count, role
changes, and settlement.

Openers must **never** be reconstructed after results are known. If Phase 2A was not captured
for a pitcher, that pitcher has **no opener**, and the row is reported as
`OPENER_NOT_CAPTURED` — never backfilled from a later observation.

## 5 — Two opening events, recorded separately

| event | definition | may be passed to `select_play()` |
|---|---|---|
| **EVENT_A** first publicly observed line | any posted line, **even one-sided**, with source and timestamp | **NO** |
| **EVENT_B** first complete executable quote | book, line, over price, under price, timestamp — all five present | **YES** |

Only EVENT_B is executable. EVENT_A is provenance, not a tradeable quote.

**Already recorded — EVENT_A, Kyle Bradish:** line `5.5`, **under side only**, no price
transcribed, observed `2026-07-27T02:33Z` via a Covers player-props board during a 12-source
scan. This is the observation that placed Bradish in Tier 2. It is EVENT_A and **cannot** be
passed to `select_play()`. The same scan found **zero** other K lines across the other 23
pitchers, and zero complete two-sided quotes slate-wide.

## 6 — Opener-source rule, pre-registered now

**Primary rule.** The opener for a pitcher is the **first complete executable quote (EVENT_B)
by capture timestamp**, from any named book.

**Tie-break**, if two complete quotes carry the same timestamp, fixed and declared now:
`DK > FD > BR > MGM > CZR > HR`.

**Why not a quality-ranked hierarchy.** The 7/25 per-book diagnostic found only BetRivers
behaving like a main line (mean signed dispersion −0.11, MAE 0.49 against the engine, versus DK
at −1.44 / 1.44). Ranking BetRivers first *on those grounds* would be **circular**: the book
would be chosen because it agrees with the model whose line-placement error is being measured,
which mechanically shrinks the error being tested. The tie-break order above is therefore
declared on no quality grounds at all, and it is a tie-break only — it can never override an
earlier timestamp.

**Prohibited.** Choosing retrospectively whichever opener flatters the projection; substituting
a close for a missing opener; or switching source rule after seeing any line.

## 7 — Starter-status changes alter eligibility, never the projection

The frozen projection is never edited, deleted, or regenerated under any of these.

| event | handling |
|---|---|
| confirmed starter | retain, evaluate normally |
| scratch / starter change | preserve the row, mark **NOT STARTED**, exclude from performance scoring, report separately |
| replacement pitcher | **no retroactive Phase-1 projection.** The replacement is unprojected and out of cohort |
| short outing, injury exit, opener/bulk usage | **retain the result**, label the event, score it. Never silently excluded |

The last row matters most: dropping a 2-K injury exit because it "isn't representative" is
outcome-dependent filtering, and it is exactly how a projection record gets laundered.

## 8 — Phase 2 is a new artifact

Phase 2A and Phase 2B are written to **new files** that reference
`7f827fd0014e5835ec3bf3572bbe1ff36dce452d5e0a55b735d04fe665c12d2f`.
The Phase-1 file is never appended to, rewritten, or re-hashed.

    data/mlb/props/simulated/2026-07-27_KSIM_phase2a.json   # openers + frozen decisions
    data/mlb/props/simulated/2026-07-27_KSIM_phase2b.json   # closes + results

Each carries `phase1_sha256` and its own hash sidecar. A Phase-2 readout that cannot cite a
matching Phase-1 hash is void.

---

## Standing limits, unchanged by this addendum

- **No Tier-0 row exists.** No pitcher on this slate is fully blind. A genuinely blind
  market-forecast test requires a future untouched slate.
- **Tier 1 and Tier 2 are never pooled.**
- The selector column in Phase 1 is **vacuous by construction** and becomes informative only in
  Phase 2A, scored against an EVENT_B quote.
- Starter status is **single-source and unconfirmed** on every row.
- Real money remains **$0, unauthorized**. This board moves no gate.
