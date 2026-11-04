# Men's college basketball card and postgame workflow

Only full Division I vs Division I games with verified identity from two sources. Pacific slate date governs the board. A pregame card is immutable once generated; diagnostics attach by hash and never change the card bytes. These are diagnostic shadows only: no market input, no action authority.

## Pregame

```bash
python scripts/capture_cbb_daily.py --date "$DAY" --output "$RUN/pregame-sources"
python scripts/cbb_shadow_card.py --date "$DAY" --inputs "$RUN/pregame-sources" --output "$RUN/parent/card.json"
sha256sum "$RUN/parent/card.json" > "$RUN/frozen-parent.sha256"
python scripts/cbb_market_and_grades.py attach --card "$RUN/parent/card.json" --card-sha "$PARENT_SHA" --inputs "$RUN/pregame-sources" --output "$RUN/market.json"
sha256sum "$RUN/market.json" > "$RUN/frozen-market.sha256"
```

The card records `as_of_utc`, `generated_at_utc`, per-event start, original margin/total projections, home win probability, and the full support/mass distributions used. Quotes require DraftKings paired prices with matching handicaps, captured strictly before tip. Moneyline "OFF" entries are not prices.

## Postgame

Fetch a fresh schedule and final-game summaries for the same Pacific slate date. Use the original immutable card and market hashes. A rerun must use a new grade file; preserve previous grades and original forecast bytes.

```bash
python scripts/capture_cbb_daily.py --date "$DAY" --output "$RUN/postgame-sources"
MARKET_SHA=$(cut -d' ' -f1 "$RUN/frozen-market.sha256")
python scripts/cbb_market_and_grades.py grade --card "$RUN/parent/card.json" --card-sha "$PARENT_SHA" --market "$RUN/market.json" --market-sha "$MARKET_SHA" --inputs "$RUN/postgame-sources" --output "$RUN/grades.json"
```

Grading requires verified event/team/start identity, a completed final and the full-game score including overtime. Prior score projections and the original lines determine winner, margin and total errors, and win/loss/push for the higher-probability side. Report priced and unpriced counts, unresolved finals, and paired model/market cohorts separately. Use provider-labeled postgame closing prices as a separate retrospective benchmark. Show sample sizes and compare uncertainty across dates once enough independent dates are available.

The November 3, 2026 FanMatch rows are an external benchmark. The first dated in-house shadow parent in this integration is November 4. Preserve these distinct identities. The in-house methodology and scope restrictions are in CBB_MENS_SHADOW.md.

Grading also requires the same capture directory's `coverage.json`, recorded by sha256 in the grade output. Any event carrying a `FINAL_RECONCILIATION_REQUIRED`, `TIP_RECONCILIATION_REQUIRED`, or `IDENTITY_NOT_CROSS_CHECKED` issue — and any slate whose coverage is missing, blocked, or dated for a different card — is never graded `FINAL` and is excluded from accuracy and settlement summaries until the disagreement is resolved in a new, separate capture. Original grades and forecast bytes are preserved unchanged; corrections are append-only in new grade files.
