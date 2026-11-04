# Men's college basketball card and postgame workflow

CBB is a distinct diagnostic population. Show every scheduled game involving a men's Division I team on its America/Los_Angeles slate date. Independently reconcile the full Division I schedule, including games against non-Division I opponents. The internal model currently supports Division I vs. Division I only. Keep explicit uncovered rows and source failures. A zero count requires a verified empty schedule. A date mismatch or unverified division must be reported.

## Pregame

Use a new directory for each command and write the raw parent hash to a separate receipt before attaching prices. For example, set DAY to the Pacific slate date, RUN to an unused directory, and run from the repository root:

```bash
set -e
mkdir -p "$RUN"
python scripts/capture_cbb_daily.py --date "$DAY" --output "$RUN/market-sources"
python scripts/cbb_shadow.py capture --date "$DAY" --inputs "$RUN/model-inputs"
python scripts/cbb_shadow.py card --date "$DAY" --inputs "$RUN/model-inputs" --output "$RUN/parent"
sha256sum "$RUN/parent/card.json" > "$RUN/frozen-parent.sha256"
PARENT_SHA=$(cut -d' ' -f1 "$RUN/frozen-parent.sha256")
python scripts/cbb_market_and_grades.py attach --card "$RUN/parent/card.json" --card-sha "$PARENT_SHA" --inputs "$RUN/market-sources" --output "$RUN/market.json"
sha256sum "$RUN/market.json" > "$RUN/frozen-market.sha256"
```

Before publishing a research supplement, compare the complete schedule event-ID set, starts, teams and eligible statuses with the parent card. Surface scope discrepancies. Preserve coverage for ineligible and unavailable games, and continue independently verified rows and other sports when a source is missing. The price capture is separate from inference. ESPN's `side.close` field in a pre-tip capture is the quote actually displayed at retrieval, rather than a final close. The diagnostic attachment checks parent hash, pre-tip capture and attachment times, exact event/side/line/settlement, raw source bytes and retrieval receipt. The current source has no independent provider-observed tick. Official recommendations, staking and EV-based promotion are disabled.

## Postgame

Fetch a fresh schedule and final-game summaries for the same Pacific slate date. Use the original immutable card and market hashes. A rerun must use a new grade file; preserve previous grades and original forecast bytes.

```bash
python scripts/capture_cbb_daily.py --date "$DAY" --output "$RUN/postgame-sources"
MARKET_SHA=$(cut -d' ' -f1 "$RUN/frozen-market.sha256")
python scripts/cbb_market_and_grades.py grade --card "$RUN/parent/card.json" --card-sha "$PARENT_SHA" --market "$RUN/market.json" --market-sha "$MARKET_SHA" --inputs "$RUN/postgame-sources" --output "$RUN/grades.json"
```

Grading requires verified event/team/start identity, a completed final and the full-game score including overtime. Prior score projections and the original lines determine winner, margin and total errors, and win/loss/push for the higher-probability side. Report priced and unpriced counts, unresolved finals, and paired model/market cohorts separately. Use provider-labeled postgame closing prices as a separate retrospective benchmark. Show sample sizes and compare uncertainty across dates once enough independent dates are available.

The November 3, 2026 FanMatch rows are an external benchmark. The first dated in-house shadow parent in this integration is November 4. Preserve these distinct identities. The in-house methodology and scope restrictions are in CBB_MENS_SHADOW.md.
