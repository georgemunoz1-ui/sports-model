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

The collector and attachment use one paired-quote parser. More than one DraftKings offer is ambiguous even when the entries are byte-identical; neither offer order nor price selects a record. A missing provider identity or incomplete offered side/close/odds/required-line scope rejects every contract for that event. Absent products and explicit `OFF` or JSON `null` prices stay unquoted. Other malformed prices, including booleans, containers, empty strings and noninteger numbers, reject the whole event rather than allowing another product to escape. A refused event has `QUOTE_UNAVAILABLE` and an empty contract list; independent clean events can continue. A new capture may resolve the source ambiguity, but it must not overwrite an existing frozen market attachment. Local repair verification is recorded separately from pending hosted acceptance in `reviews/pr108_quote_scope_20261104/closure.json`.

## Postgame

Use a new postgame capture directory and grade filename for each attempt. Pin the collector manifest immediately after capture and retain the pin separately with the run receipts. The manifest binds the exact coverage report and source bytes. This also permits grading agreed events on a slate with individual results still under review.

```bash
CAPTURE="$RUN/postgame-sources-001"
rc=0
python scripts/capture_cbb_daily.py --date "$DAY" --output "$CAPTURE" || rc=$?
if [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ]; then exit "$rc"; fi
sha256sum "$CAPTURE/manifest.json" > "$RUN/postgame-001.sha256"
MANIFEST_SHA=$(cut -d' ' -f1 "$RUN/postgame-001.sha256")
MARKET_SHA=$(cut -d' ' -f1 "$RUN/frozen-market.sha256")
GRADE="$RUN/grades-001.json"
test ! -e "$GRADE"
rc=0
python scripts/cbb_market_and_grades.py grade --card "$RUN/parent/card.json" --card-sha "$PARENT_SHA" --market "$RUN/market.json" --market-sha "$MARKET_SHA" --inputs "$CAPTURE" --manifest-sha "$MANIFEST_SHA" --output "$GRADE" || rc=$?
if [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ]; then exit "$rc"; fi
test -s "$GRADE"
sha256sum "$GRADE" > "$RUN/grades-001.sha256"
```

Each final requires the same event, teams, start, final status and home/away scores in the captured ESPN scoreboard, NCAA contest and ESPN event summary. Per-event score, tip and identity disagreements are reported in the coverage file. Those results stay outside the accuracy and settlement totals. A quote-only issue can coexist with a verified final. A valid incomplete grade writes its event statuses and exits 2. A pinned capture marked `BLOCKED` records that reason and yields zero finals. An integrity failure such as a mismatched capture digest prevents a grade from being written. Older capture formats without a bound event reconciliation require a new capture.

If a source corrects a result, retain the original grade. Repeat the capture and pin steps using the next sequence number. Write a new grade with the original card and market hashes, the new manifest pin, and both `--previous-grade "$RUN/grades-001.json"` and `--previous-grade-sha` with the digest from the retained grade receipt. Version 1 grades lack a market hash and receive the explicit historical label `UNVERIFIABLE_LEGACY_GRADE`. Store the successor beside the original and use one version per event when reporting.

Prior score projections and the original lines determine winner, margin and total errors, and win/loss/push for the higher-probability side. Report priced and unpriced counts, unresolved finals, and paired model/market cohorts separately. Use provider-labeled closing prices for the retrospective benchmark.

The November 3, 2026 FanMatch rows are an external benchmark. The first dated in-house shadow parent in this integration is November 4. Preserve these distinct identities. The in-house methodology and scope restrictions are in CBB_MENS_SHADOW.md.
