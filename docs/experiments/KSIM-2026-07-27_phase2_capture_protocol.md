# KSIM-2026-07-27 — PHASE 2 CAPTURE PROTOCOL

Final clarification, issued after the protocol addendum was accepted. **Phase 1 is not
modified.** Terminology here **supersedes** the EVENT_A / EVENT_B naming used in
`KSIM-2026-07-27_protocol_addendum.md` §5.

| | |
|---|---|
| Phase-1 artifact | `data/mlb/props/simulated/2026-07-27_KSIM_phase1.json` |
| **Phase-1 sha256** | `7f827fd0014e5835ec3bf3572bbe1ff36dce452d5e0a55b735d04fe665c12d2f` |
| Verified unchanged | `sha256sum -c` OK, and `harness/verify_lineage.py` OK |

---

## 1 — Naming. Nothing is an "opener" until it is proven to be one

| term | definition |
|---|---|
| `FIRST_CAPTURED_LINE` | the first K line we observed for a pitcher, **possibly one-sided** |
| `FIRST_CAPTURED_COMPLETE_QUOTE` | the first capture carrying book + line + over price + under price + timestamp |
| `VERIFIED_OPENER` | a quotation established as the **market's opening** quotation by a verified market-origin timestamp or an authenticated historical-odds feed |

**Neither of the first two may be called an opener.** "First we saw it" is a fact about our
retrieval; "first the book posted it" is a fact about the market, and we have never once had
evidence for the second. Absent a market-origin timestamp or odds-history feed, `VERIFIED_OPENER`
is simply **absent** — not inferred, not assumed to be the earliest capture.

## 2 — Two timestamps, never conflated

Every capture records both:

- **`observed_at_utc`** — when *we* retrieved it. Always present.
- **`source_quote_time_utc`** — the book's or feed's own quote timestamp, **only if the source
  supplies one**. If the source supplies none, this is **`null`**.

Setting `source_quote_time_utc = observed_at_utc` is prohibited. It would manufacture market
provenance out of our own retrieval clock, and it is the single mistake that would let a
mid-slate screenshot masquerade as an opener.

## 3 — Required fields on every capture

    book                       named sportsbook
    source_url_or_feed         where it came from
    observed_at_utc            our retrieval time
    source_quote_time_utc      book/feed time, or null
    line                       posted K line
    over_price                 or null if not shown/legible
    under_price                or null if not shown/legible
    raw_payload                screenshot path or raw JSON/text, retained
    source_labels_main_line    true / false / unknown -- does the SOURCE designate it the main line

A capture missing `raw_payload` is provenance-only and may not be scored. Prices that are
present at source but not transcribed are `null` **with a flag** — never guessed (R1).

## 4 — Main-line selection, by market designation only

When a book shows several strikeout lines for one pitcher:

1. **Use the line the book itself designates default/main.** Record
   `main_line_basis: "book_designated"`.
2. **Otherwise** mark the pitcher `MAIN_LINE_UNRESOLVED`, **retain every alternate rung**, and
   score nothing from that pitcher's line placement.

**Prohibited: choosing the rung nearest E\[K\].** That would select the comparison to minimise
the very error being measured, guaranteeing a flattering result no matter how the engine
performs. The rule must be independent of the projection, and it is.

This is the same defect class that quarantined 10 of 30 arms on 7/26 — an alt rung read as a
main line — approached from the other side.

## 5 — Phase-2A eligibility is decided by the clock

A Phase-2A capture is valid for **executable-decision scoring** only if
`observed_at_utc` **precedes that pitcher's scheduled first pitch**.

A quotation first captured after first pitch is **ineligible for executable-decision scoring**.
It is still recorded, still reported, and may still be used for line-placement description —
but it may not produce a frozen executable decision, and it may not be relabelled later.

Per-pitcher deadlines, taken from the frozen artifact:

| pitcher | game | first pitch (UTC) | frozen line |
|---|---|---|---|
| George Kirby | SEA@TEX | `2026-07-27T18:35Z` | 5.5 |
| Kumar Rocker | SEA@TEX | `2026-07-27T18:35Z` | 4.0 |
| Keider Montero | BAL@DET | `2026-07-27T22:40Z` | 4.0 |
| Kyle Bradish | BAL@DET | `2026-07-27T22:40Z` | 5.5 |
| Merrill Kelly | ARI@PIT | `2026-07-27T22:40Z` | 4.0 |
| Mitch Keller | ARI@PIT | `2026-07-27T22:40Z` | 4.0 |
| Tyler Phillips | PHI@MIA | `2026-07-27T22:40Z` | 3.5 |
| Zack Wheeler | PHI@MIA | `2026-07-27T22:40Z` | 7.0 |
| Andrew Alvarez | TOR@WSH | `2026-07-27T22:45Z` | 5.0 |
| Max Scherzer | TOR@WSH | `2026-07-27T22:45Z` | 3.5 |
| Chase Burns | CLE@CIN | `2026-07-27T23:10Z` | 6.5 |
| Martin Perez | ATL@NYM | `2026-07-27T23:10Z` | 4.0 |
| Slade Cecconi | CLE@CIN | `2026-07-27T23:10Z` | 4.0 |
| Max Fried | NYY@CHW | `2026-07-27T23:40Z` | 5.0 |
| Noah Schultz | NYY@CHW | `2026-07-27T23:40Z` | 4.5 |
| David Peterson | CHC@STL | `2026-07-27T23:45Z` | 4.5 |
| Matthew Liberatore | CHC@STL | `2026-07-27T23:45Z` | 4.5 |
| Tatsuya Imai | HOU@LAA | `2026-07-28T01:38Z` | 5.0 |
| Walbert Urena | HOU@LAA | `2026-07-28T01:38Z` | 5.0 |
| Jack Perkins | BOS@ATH | `2026-07-28T01:40Z` | 5.5 |
| Payton Tolle | BOS@ATH | `2026-07-28T01:40Z` | 5.5 |
| Brandon Sproat | MIL@SF | `2026-07-28T01:45Z` | 5.0 |
| Tyler Mahle | MIL@SF | `2026-07-28T01:45Z` | 5.0 |

## 6 — Two distinct comparisons, reported separately

| comparison | scope |
|---|---|
| **C1** frozen mechanical line vs `FIRST_CAPTURED_COMPLETE_QUOTE` | every eligible pitcher with a complete quote |
| **C2** frozen mechanical line vs `VERIFIED_OPENER` | **only** pitchers with authenticated opener history |

C1 measures how far the model's number sits from *a* market number we could actually see. C2
measures placement against the market's *origin*. They answer different questions, and C1 must
never be presented as C2. If no authenticated opener history exists for this slate — which is
the present expectation — **C2 is reported as empty**, not approximated from C1.

Per the addendum: both are **line-placement error in strikeouts only**. The `-115` prices are a
null assumption and are never scored.

## 7 — Reproducibility of the lineage hash

    python 3.11.15   CPython   Linux-6.18.5-x86_64-with-glibc2.39
    command:  python3 harness/verify_lineage.py
    manifest: docs/experiments/KSIM-2026-07-27_lineage_manifest.txt

`harness/verify_lineage.py` recomputes every published hash from the files on disk and prints
OK/FAIL per item. Current status: **all four reproduce**.

Two canonical forms are documented because the published one cannot be changed without
invalidating a hash already cited in the record:

- **v1 (published)** `''.join(f'{pid}:{sha256}')` over pids sorted as **strings**, utf-8, no
  separator → `806e5cd2f0a7964900b421069b1bfe596ccc71e885dfa6bb30fb0a55bcd53f20`.
  Note the pid sort is lexicographic on the CSV string, not numeric. Concatenating
  variable-length fields without a delimiter is not injective in general; it is well defined
  here only because pid and sha256 are fixed-width in this manifest. Kept verbatim.
- **v2 (use for future manifests)** newline-delimited `f'{pid}  {sha256}'` with a trailing
  newline → `fc6f01fa65f42fc39eaae65861ad49c341dc2935ca59c3251049cbb422c69a30`.

## Kyle Bradish — status restated

`FIRST_CAPTURED_LINE` **only**.

    line                    5.5
    under_price             PRESENT AT SOURCE, value not transcribed -> null + flag
    over_price              null (not shown)
    observed_at_utc         2026-07-27T02:33Z
    source_quote_time_utc   null (Covers board supplied no quote timestamp)
    source                  Covers player-props board, 12-source scan
    status                  NOT a complete executable quote; NOT a verified opener

He is **not** `FIRST_CAPTURED_COMPLETE_QUOTE` (no over price) and **not** `VERIFIED_OPENER` (no
market-origin timestamp). He may not be passed to `select_play()`. He remains **Tier 2**, and
his line-placement accuracy is never scored as blind.

One record correction: the addendum recorded "under side only, no price transcribed." The
source did display an under price; its value was not transmitted into our record. Both
statements are true of different things — the price existed at source, and we hold no value for
it. It is `null` with `price_present_but_not_transcribed: true`, never a reconstructed number.
