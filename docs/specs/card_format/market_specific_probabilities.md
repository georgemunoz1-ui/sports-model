Add explicit market-specific probability fields to every card record. Use `model_win_pct` for ML, `model_cover_pct` for Spread/RL, and `model_over_pct` or `model_under_pct` for totals; do not use one generic `model_pct` field because its meaning changes by market.

## Add this prompt block

```text
For every game, output exactly three independent markets:

ML:
- selection
- model_win_pct
- model_loss_pct
- model_draw_pct when the sport/market permits a draw
- market_no_vig_pct
- edge_pp
- entry_price
- decision

SPREAD_RL:
- selection
- line
- model_cover_pct
- model_push_pct
- model_noncover_pct
- market_no_vig_cover_pct
- edge_pp
- entry_price
- decision

TOTALS:
- selection: OVER or UNDER
- line
- model_over_pct
- model_under_pct
- model_push_pct
- market_no_vig_selected_pct
- edge_pp
- entry_price
- decision

Rules:
- ML probability means probability of winning the moneyline market.
- Spread/RL probability means probability of covering the supplied line.
- Totals probability means probability of going over or under the supplied total.
- Use null when a probability, line, price, or market is unavailable.
- Do not infer cover probability from moneyline probability.
- Do not infer totals probability from team win probability.
- For half-point lines, model_push_pct must be 0.0.
- For whole-number spreads or totals, preserve model_push_pct when applicable.
- For soccer 1X2 markets, output home, draw, and away probabilities that sum to 1.0.
- Calculate edge against the supplied no-vig market probability, not the vig-included implied probability.
- Do not recalculate or invent model probabilities.
- If the source does not provide a probability, output null and do not estimate it from the market.
```

The no-vig probability should be calculated by converting both sides to implied probabilities and normalizing them to sum to 100%; comparing model probability directly with vig-included implied probability will overstate or understate the edge. [foxsports](https://www.foxsports.com/stories/betting/what-is-the-vig)

## Recommended JSON fields

```json
{
  "market": "SPREAD_RL",
  "selection": "ATL",
  "line": 2.5,
  "entry": {
    "book": "DraftKings",
    "price_american": -110,
    "timestamp": "2026-08-30T08:15:00-04:00"
  },
  "probabilities": {
    "model_cover_pct": 64.3,
    "model_push_pct": 0.0,
    "model_noncover_pct": 35.7,
    "market_no_vig_cover_pct": 50.0,
    "edge_pp": 14.3,
    "usable_edge_pp": 6.9
  },
  "movement": {
    "classification": "unknown",
    "confidence": 0.18,
    "open_line": 2.5,
    "current_line": 2.5
  },
  "decision": "LEAN",
  "tier": "C",
  "data_quality_status": "PASS",
  "note": "Spread edge only; ML edge is negative"
}
```

For a totals market:

```json
{
  "market": "TOTALS",
  "selection": "UNDER",
  "line": 8.0,
  "entry": {
    "book": "DraftKings",
    "price_american": -105,
    "timestamp": "2026-08-30T08:15:00-04:00"
  },
  "probabilities": {
    "model_over_pct": 44.8,
    "model_under_pct": 54.1,
    "model_push_pct": 1.1,
    "market_no_vig_selected_pct": 50.8,
    "edge_pp": 3.3,
    "usable_edge_pp": 1.6
  },
  "decision": "PASS"
}
```

For a half-point total such as 8.5:

```json
"model_push_pct": 0.0
```

For an integer total such as 8, retain a nonzero push probability if your simulation produces exactly eight runs.

## Card table format

Use one row per game with market cells that contain the corresponding model percentage:

```text
| Game       | ML                                      | Spread/RL                                  | Totals                                  | Movement | Game Decision | Note |
|------------|-----------------------------------------|--------------------------------------------|-----------------------------------------|----------|---------------|------|
| MIN @ ATL  | ATL ML; model 39.7%; mkt 44.9%; -5.2pp | ATL +2.5; cover 64.3%; mkt 50.0%; +14.3pp | N/A; model% not supplied                 | unknown  | LEAN          | Spread edge only |
```

A more compact version:

```text
| Game       | ML                                  | Spread/RL                              | Totals                    | Decision |
|------------|-------------------------------------|----------------------------------------|---------------------------|----------|
| MIN @ ATL  | ATL ML · M39.7 / Mkt44.9 · -5.2pp  | ATL +2.5 · C64.3 / Mkt50.0 · +14.3pp | N/A                       | LEAN     |
```

Define the abbreviations in the card header:

```text
M = model probability
C = model cover probability
O/U = model over/under probability
Mkt = market no-vig probability
E = edge in percentage points
P = push probability
```

## Market-specific display rules

### ML

```text
ML: selection
Model Win %
Market No-Vig %
Edge
Price
Decision
```

Example:

```text
ML: ATL -135 | Win 39.7% | Mkt 44.9% | Edge -5.2pp | PASS
```

For soccer or any three-way market:

```text
ML:
Home 42.0%
Draw 28.5%
Away 29.5%
```

Validate:

```python
abs(home_pct + draw_pct + away_pct - 100) < 0.1
```

### Spread/RL

Use `model_cover_pct`, not `model_win_pct`:

```text
Spread/RL: ATL +2.5 -110
Model Cover: 64.3%
Model Push: 0.0%
Market No-Vig Cover: 50.0%
Edge: +14.3pp
Decision: LEAN
```

For MLB, render the label based on sport:

```text
MLB → RL
NFL/NBA/NHL/CFB → Spread
```

Internally, keep the canonical market name as:

```text
SPREAD_RL
```

### Totals

Always identify the direction:

```text
Totals: Under 8.0 -105
Model Under: 54.1%
Model Over: 44.8%
Model Push: 1.1%
Market No-Vig Under: 50.8%
Edge: +3.3pp
Decision: PASS
```

Do not output only:

```text
Total: 8.0 | Model: 54.1%
```

because the reader cannot tell whether 54.1% means Over or Under.

## Validation rules

Add these checks to the formatter:

```python
for game in card["games"]:
    assert len(game["markets"]) == 3

    market_names = {m["market"] for m in game["markets"]}
    assert market_names == {"ML", "SPREAD_RL", "TOTALS"}

    for m in game["markets"]:
        p = m["probabilities"]

        if m["market"] == "ML":
            if p["model_win_pct"] is not None:
                assert 0 <= p["model_win_pct"] <= 100

        if m["market"] == "SPREAD_RL":
            if p["model_cover_pct"] is not None:
                assert 0 <= p["model_cover_pct"] <= 100
            if p["model_push_pct"] is not None:
                assert 0 <= p["model_push_pct"] <= 100

        if m["market"] == "TOTALS":
            if p["model_over_pct"] is not None:
                assert 0 <= p["model_over_pct"] <= 100
            if p["model_under_pct"] is not None:
                assert 0 <= p["model_under_pct"] <= 100
```

For two-way markets:

```python
assert abs(
    model_cover_pct +
    model_push_pct +
    model_noncover_pct - 100
) < 0.1
```

For totals:

```python
assert abs(
    model_over_pct +
    model_under_pct +
    model_push_pct - 100
) < 0.1
```

For no-line markets:

```python
if decision == "NO_LINE":
    assert selection is None or line is None
    assert model_probability is None
```

Use a strict JSON Schema or equivalent structured-output feature for the response boundary, then run your own semantic validation afterward. Schema enforcement can ensure that the model returns the required structure and enum values, but it does not confirm that the probabilities or odds are correct. [learn.microsoft](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs)

## Final prompt instruction

Add this at the end of the formatter prompt:

```text
Before finalizing, verify:

- Every game has ML, SPREAD_RL, and TOTALS.
- Every market has its own model probability.
- ML uses model_win_pct.
- SPREAD_RL uses model_cover_pct.
- TOTALS uses model_over_pct or model_under_pct.
- Push probability is shown when applicable.
- Market probability is no-vig.
- Edge is expressed in percentage points.
- Missing data is null/N/A, never inferred.
- A decision applies only to its own market.
- The game-level decision cannot be more aggressive than its most restrictive market or data-quality status.
```

The key output distinction should be:

```text
ML          → model_win_pct
Spread/RL   → model_cover_pct
Totals      → model_over_pct / model_under_pct
```

That will prevent the card from mixing a moneyline win probability with a spread-cover probability or treating a total projection as a generic game probability.