# How to drop a K quote

The short version: **one arm, one book, both sides of the price, is enough.**
I have been asking for far more than I need. A full 30-arm 6-book board is nice
but it is not the requirement, and waiting to capture one is what has been
putting every board in mid-slate.

## What actually matters, in order

1. **Before first pitch.** This is the only thing that cannot be recovered
   later. A quote captured at 16:40Z for a 20:05Z game is worth more than a
   perfect 30-arm board captured at 19:20Z, because only the first one can
   advance the authorization gate.
2. **Both sides of the price.** `4.5  U +130  O -166`. One side is still
   usable, but the hold test cannot run on it, so it is trusted less.
3. **The time you took it.** Even approximate. Without it nothing can be
   proven pre-lock, and everything is demoted to shadow.
4. Everything else — how many arms, how many books — is upside, not a gate.

## Which is better, the app or the aggregator?

A screenshot of **one book's own prop page** is cleaner than an aggregator
board, and it needs fewer tests to trust. An aggregator shows a best-price-
across-books display, which mixes a book's main line with another book's alt
rung; on 7/26 that contaminated 10 of 30 rows and would have made the shrinkage
fit 65% too aggressive. A single book's page has no alt ladder to confuse, so
the dispersion test is skipped entirely as unnecessary rather than failed.

Say which it is with `source_type`: `"book_direct"` or `"aggregator"`.

## The drop file

`data/mlb/props/drops/<date>_<tag>.json`

```json
{"date": "2026-07-27",
 "captured_utc": "2026-07-27T16:40:00Z",
 "source_type": "book_direct",
 "source_note": "DK app, Sanchez prop page",
 "quotes": [["DK", "Cristopher Sanchez", 7.5, -123, -104]]}
```

`[book, pitcher, line, under, over]`. Use `null` for a price that is not
legible or not shown — never a guess (R1). Two other shapes are accepted if
they are easier to type: a list of objects, or a dict keyed by pitcher name.

If the arm was TBD when the card was cut, add `"teams": {"Name": "PHI"}` so the
game clock can still be resolved.

Then:

```
python3 harness/ingest_kquote.py data/mlb/props/drops/2026-07-27_dk-am.json
python3 harness/ingest_kquote.py data/mlb/props/drops/2026-07-27_dk-am.json --register
```

The first run is always read-only. It prints what each arm passed and failed,
what the engine would play, and whether the clock allows it to count. The
second writes the gate-eligible plays into `ledgers.kprops_paper.plays_pending`
and recomputes the gate string. Nothing is ever staked; everything is paper.

## What the ingester will refuse to do for you

- Register anything it cannot prove was captured before first pitch.
- Treat a line with no price next to it as a market.
- Accept an aggregator row whose books disagree by more than 1.0 K.
- Register an arm posted at 3.5 K or lower, without `--allow-short-lines`.
  A short posted line *is* the book telling us it expects a short outing, and
  the engine's E[TBF] prior does not read that, so it invents an edge. Fedde,
  Freeland, Avila and Baz all had this shape on 7/26. Until there is an
  opener detector, these are measured and not counted.
- Silently disagree with an earlier drop the same day. Same book, same line,
  different price, and the arm is quarantined pending a re-read.

## If you drop a screenshot instead

That still works and always will. I transcribe it into a drop file, and the
same tests run on the result. The only thing that costs you is that the
transcription is mine rather than yours, so it gets the re-read test where a
typed drop does not need it.
