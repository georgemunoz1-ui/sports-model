V5 is internally consistent on the major counts: 19 games × 3 markets = 57 rows, with 1 LEAN, 7 PASS, 14 CLV_ONLY, and 35 NO_LINE totaling 57. The main remaining issue is semantic rather than arithmetic: **ATL +2.5 is a model lean, but not an executable paper entry until the missing price is resolved**.

## Important fixes

### 1. Separate signal from execution

For ATL +2.5, use two statuses:

```text
signal_decision:    LEAN
execution_status:   NO_PRICE
actionable:         false
```

The current `LEAN` label can be interpreted as an executable wager even though the entry price is null. A safer display would be:

```text
ATL +2.5 · C64.3 / Mkt50.0 · +14.3pp · LEAN / NO_PRICE
```

Or:

```text
Model signal: LEAN
Paper execution: BLOCKED — entry price missing
```

Do not calculate actual entry EV or CLV from a line-only observation. The line can be retained for model evaluation, but price-dependent metrics remain unavailable.

### 2. Clarify the clock

The card still contains:

```text
decision_time: 08:15 ET
entry capture: ≤ 04:12 ET
```

That is acceptable only if the intended semantics are:

```text
price_as_of: 04:12 ET
decision generated: 08:15 ET
```

Otherwise, rename the fields:

```text
entry_snapshot_cutoff: 04:12 ET
decision_time:          08:15 ET
```

Also record whether any new information arrived between those times. If the model decision was made at 08:15 but used a price from 04:12, the test is conservative but may not represent an executable 08:15 wager. Every input must remain tied to its actual availability time for point-in-time integrity. [docs.glassnode](https://docs.glassnode.com/data/point-in-time-metrics)

### 3. Qualify movement records

The movement column should identify the affected market:

```text
movement.market = TOTALS
movement.side = null
movement.open = 179.5
movement.current = 176.5
```

For example:

```text
MIN @ ATL:
Totals movement: 179.5 → 176.5
Classification: unknown
Confidence: 0.20
```

This prevents a reader or parser from mistaking a total movement for a spread or ML movement.

### 4. Preserve source status

For each market, retain:

```text
line_available
price_available
probability_available
source_available
actionable
clv_eligible
roi_eligible
```

The ATL record should then look like:

```json
{
  "market": "SPREAD_RL",
  "line": 2.5,
  "price_american": null,
  "model_cover_pct": 64.3,
  "market_no_vig_cover_pct": 50.0,
  "edge_pp": 14.3,
  "signal_decision": "LEAN",
  "execution_status": "NO_PRICE",
  "actionable": false,
  "clv_eligible": false,
  "roi_eligible": false,
  "note": "Line captured; entry price missing from relay"
}
```

## Validation additions

Your current validation is good, but add:

```text
[ ] Every populated market identifies its market type
[ ] Every movement has market, book, and timestamp
[ ] LEAN/PLAY requires non-null entry price
[ ] Missing price prevents executable status
[ ] CLV eligibility requires entry line and entry price
[ ] ROI eligibility requires entry price and actionable status
[ ] WNBA ML probabilities sum to 100%
[ ] Every populated spread has cover + push + noncover = 100%
[ ] Every populated total has over + push + under = 100%
[ ] Post-decision re-verification cannot alter V1 fields
```

A useful invariant is:

```python
if market["signal_decision"] in {"PLAY", "LEAN"}:
    assert market["actionable"] is False or (
        market["entry"]["price_american"] is not None
    )
```

## GitHub verification

For the staged push, verify independently:

```text
commit SHA
tree SHA
blob SHA for V1
blob SHA for V4
blob SHA for V5
spec-document hashes
parent commit
repository and branch
```

Do not use the interactive card version `19f1711` as a substitute for the immutable Git commit or blob identity. The card version is a presentation/reference ID; the SHA is the artifact-integrity check.

Overall, V5 looks ready for a protocol sweep after changing ATL from a single executable-looking `LEAN` status to an explicit **LEAN signal / NO_PRICE execution status** and clarifying the 04:12 versus 08:15 timestamp semantics.