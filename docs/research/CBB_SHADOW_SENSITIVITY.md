# CBB spread and moneyline sensitivity analysis

Run the offline comparison with Python 3.11 or later. Supply the frozen CBB parent, the recovered market board and the reconciled grades from the same slate. The output path must be new.

```shell
python research/cbb_shadow_sensitivity.py inputs/card.json inputs/board.json inputs/grades.json replay.json
python -m unittest discover -s tests -p 'test_cbb_shadow_sensitivity.py' -v
```

## Procedures

The spread procedure multiplies each deviation from the frozen mean home margin by 1.25. It divides mass between adjacent legal, nonzero integer margins to preserve the mean and total probability. It then scores the distribution at the original half-point line. The handicap enters only at settlement and when reporting subgroups. This procedure estimates a final margin for games that include overtime.

The market-informed moneyline procedure gives the frozen winner probability 75% weight and the normalized two-sided market probability 25%. It uses a single book captured after the forecast was frozen and before play. The spread benchmark requires both opposing half-point lines and prices. The November 14 prices came through ESPN with receipt times. Provider-side timestamps were unavailable.

Both comparisons score the original side even if its adjusted probability crosses 50%. The output includes the input and code hashes, matched rows and exclusion reasons. Five graded November 14 moneyline games lacked comparable prices. The review’s exclusion ledger covers fixtures missing from the grade input.

## Evaluation

The scale and blend weight were chosen after inspecting November 14. That slate is available for development and reproduction only. Before evaluating later slates, record the new procedure identities, parameters, training and evaluation periods, required coverage, minimum sample and calibration criteria. Freeze each forecast before play and retain point-in-time receipts.

For spreads, compare the existing procedure with center-only, scale-only and combined adjustments on identical events and exact lines. Track signed error, interval coverage and probability scores across both team orientations and report the small-handicap and large-handicap groups separately. For moneylines, compare the blend with the original model and the same-time normalized market. Report paired score differences by slate and account for missing forecasts and quotes.

Independent prospective evidence, verified input consumption and separate release authorization govern promotion.
