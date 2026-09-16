The cleanest way is to require **one game object containing three separate market objects**: `ML`, `SPREAD_RL`, and `TOTALS`. Do not ask the model to compress all three into one ambiguous string such as `MIA -108 · 9`; use a strict schema and validate the result. Structured-output APIs can enforce fields, types, and allowed enum values, although they cannot guarantee that the odds or probabilities are factually correct. [learn.microsoft](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs)

## Copy/paste prompt

```text
You are the Decision-State Card Formatter.

Convert the supplied sportsbook/model records into a decision card.

For EVERY game, output exactly three independent market records:

1. ML
2. SPREAD_RL
3. TOTALS

Use "SPREAD_RL" for:
- point spread in NFL, NBA, WNBA, NCAAF, NCAAB, NHL, soccer, and similar sports
- run line in MLB

Use "TOTALS" for:
- game total
- regulation total
- full-game total
- player total only when explicitly identified

Do not combine markets. Each market must have its own:
- selection
- line
- entry price
- model probability
- market no-vig probability
- edge
- movement
- data-quality status
- decision

Rules:

- Never invent a line, price, probability, sportsbook, starter status, or movement value.
- Use null when a required value is missing.
- If a market is absent, output decision = "NO_LINE".
- If the game or market is blocked by a data-quality cap, output decision = "BLOCKED" or "CLV_ONLY" according to the supplied record.
- If information is unresolved, output decision = "WAIT".
- If no positive actionable edge remains, output decision = "PASS".
- A positive ML edge must not imply a positive spread/run-line or totals edge.
- Evaluate ML, SPREAD_RL, and TOTALS independently.
- Do not use closing odds or post-decision information as model inputs.
- Preserve the supplied version, decision timestamp, entry cutoff, feature cutoff, and model version.
- Do not recalculate probabilities unless explicitly instructed.
- Do not upgrade PASS, WAIT, LEAN, BLOCKED, or CLV_ONLY to PLAY.
- Data-quality caps override model edge.
- Output one human-readable table and one machine-readable JSON object.
- The JSON is canonical; the table must be generated from the JSON.

Allowed decisions:
PLAY, LEAN, PASS, WAIT, BLOCKED, CLV_ONLY, NO_LINE, NO_FORECAST

Allowed market names:
ML, SPREAD_RL, TOTALS

Required table columns:

| Game | ML | Spread/RL | Totals | Movement | Game Decision | Note |

Each market cell must use this format:

selection line price
p_model / p_market_no_vig / edge_pp
market_decision

If a field is unavailable, write "N/A" in the table and null in JSON.
```

## Recommended JSON structure

Use this as the canonical response shape:

```json
{
  "card_metadata": {
    "board_version": "586faaa",
    "card_version": "V3",
    "decision_time": "2026-08-30T08:15:00-04:00",
    "entry_cutoff": "2026-08-30T04:12:00-04:00",
    "feature_cutoff": "2026-08-27T00:00:00-04:00",
    "paper_only": true,
    "ledger": 0,
    "model_version": "model-name",
    "calibrator_status": "DORMANT"
  },
  "games": [
    {
      "event_id": "mlb_mia_wsh_2026-08-30",
      "game": "MIA @ WSH",
      "sport": "MLB",
      "start_time": "2026-08-30T12:15:00-04:00",
      "game_status": "PASS",
      "markets": [
        {
          "market": "ML",
          "selection": "MIA",
          "line": null,
          "entry": {
            "book": "DraftKings",
            "price_american": -108,
            "timestamp": "2026-08-30T04:12:00-04:00"
          },
          "p_model": null,
          "p_market_no_vig": null,
          "edge_pp": null,
          "usable_edge_pp": null,
          "movement": {
            "classification": null,
            "confidence": null,
            "open": null,
            "current": null
          },
          "data_quality": {
            "status": "CAP",
            "score": null,
            "reason": "SP_CONFIRMED unavailable"
          },
          "decision": "CLV_ONLY",
          "note": "Entry retained for closing-line evaluation only"
        },
        {
          "market": "SPREAD_RL",
          "selection": null,
          "line": null,
          "entry": {
            "book": null,
            "price_american": null,
            "timestamp": null
          },
          "p_model": null,
          "p_market_no_vig": null,
          "edge_pp": null,
          "usable_edge_pp": null,
          "movement": {
            "classification": null,
            "confidence": null,
            "open": null,
            "current": null
          },
          "data_quality": {
            "status": "MISSING",
            "score": null,
            "reason": "Spread/run line not supplied"
          },
          "decision": "NO_LINE",
          "note": null
        },
        {
          "market": "TOTALS",
          "selection": null,
          "line": 9.0,
          "entry": {
            "book": null,
            "price_american": null,
            "timestamp": null
          },
          "p_model": null,
          "p_market_no_vig": null,
          "edge_pp": null,
          "usable_edge_pp": null,
          "movement": {
            "classification": null,
            "confidence": null,
            "open": null,
            "current": null
          },
          "data_quality": {
            "status": "INCOMPLETE",
            "score": null,
            "reason": "Total side and price not supplied"
          },
          "decision": "NO_LINE",
          "note": "Do not infer Over or Under"
        }
      ],
      "note": "SP conflict resolved V2; probable starter data remains capped"
    }
  ]
}
```

The important part is that a missing spread/run line gets its own `NO_LINE` record rather than disappearing. That prevents the model from accidentally treating an absent market as a pass.

## Table output

Generate the human-readable card from the JSON:

```text
| Game       | ML                              | Spread/RL       | Totals             | Movement | Game Decision | Note |
|------------|----------------------------------|-----------------|--------------------|----------|---------------|------|
| MIA @ WSH  | MIA -108; p=N/A; CLV_ONLY       | N/A; NO_LINE    | 9.0; NO_LINE       | —        | CLV_ONLY      | MLB slate CAP |
```

For a fully populated record:

```text
| Game       | ML                                      | Spread/RL                                | Totals                                  | Movement       | Game Decision | Note |
|------------|-----------------------------------------|-------------------------------------------|------------------------------------------|----------------|---------------|------|
| Team A @ B | Team A -115; p=.57/.53; +4.0pp; PASS   | Team B +2.5; p=.55/.51; +4.0pp; LEAN     | Under 8.5; p=.56/.51; +5.0pp; PLAY       | unknown .18    | LEAN          | ML and total disagree |
```

Use `p_model / p_market_no_vig / edge_pp` in every populated cell so the model cannot hide whether the advantage belongs to the ML, spread/run line, or totals market.

## Decision precedence

Add this rule to the prompt:

```text
Decision precedence:

NO_FORECAST or BLOCKED data status
  overrides
CLV_ONLY
  overrides
WAIT
  overrides
PASS
  overrides
LEAN
  overrides
PLAY

A game-level decision must never be more aggressive than its most restrictive governing market/data status.
```

For example:

```text
ML:          PASS
Spread/RL:   WAIT
Totals:      PASS
Game status: WAIT
```

And:

```text
ML:          +8% raw edge but blocked
Spread/RL:   NO_LINE
Totals:      PASS
Game status: BLOCKED
```

This preserves the conservative behavior already present in your board.

## Edge calculation rules

Have the model display, but not independently invent, these fields:

\[
\text{edge}_{pp}
=
100\left(p_{\text{model}} - p_{\text{market,no-vig}}\right)
\]

For the decision layer:

```text
usable_edge_pp
= raw_edge_pp × data_quality_factor × uncertainty_factor
```

Keep these separate:

```text
raw edge
usable edge
decision threshold
decision
```

A market can therefore show:

```text
ML raw edge:       +11.0pp
Scenario-adjusted: +0.8pp
Usable edge:        0.0pp
Decision:          PASS
```

That is preferable to overwriting the original raw edge.

## Best implementation pattern

Use two stages:

```text
Stage 1: analytical engine
  produces probabilities, prices, edges, movement, DQ, uncertainty

Stage 2: card formatter
  produces ML, Spread/RL, Totals records and table
```

The formatter should not recalculate probabilities or make new betting judgments. It should only:

- Preserve supplied values.
- Expand each game into three markets.
- Apply allowed decision/status rules.
- Render missing values explicitly.
- Validate that the table matches the JSON.

Add these validation checks:

```python
assert set(m["market"] for m in game["markets"]) == {
    "ML", "SPREAD_RL", "TOTALS"
}

for market in game["markets"]:
    if market["decision"] == "NO_LINE":
        assert market["entry"]["price_american"] is None

    if market["decision"] in {"PLAY", "LEAN"}:
        assert market["selection"] is not None
        assert market["entry"]["price_american"] is not None
        assert market["p_model"] is not None
        assert market["p_market_no_vig"] is not None
```

The central instruction is:

```text
Every game must always output exactly three independent market rows:
ML, SPREAD_RL, and TOTALS.
Missing markets must be represented explicitly as NO_LINE.
Never infer one market’s decision from another market.
```