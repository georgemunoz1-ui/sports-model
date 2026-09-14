# MLB September 8–9 postgame analysis

Diagnostic evaluation of original frozen forecasts. All 30 event IDs, dates and home/away assignments matched official finals. No forecast rerun.

September 8 run: 34273154914; September 9 run: 34330917567. September 9 source capture: 34445909661. Actual source retrieval time is recorded in receipt.json; this is not an exact historical 11:30 PM snapshot.

| Date | Fixed correct | Gamma MC correct | Fixed Brier | MC Brier | Fixed log loss | MC log loss | Margin MAE | Total MAE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Sept 8 | 8/15 | 6/15 | 0.2204 | 0.2384 | 0.6264 | 0.6694 | 2.576 | 3.268 |
| Sept 9 | 8/15 | 6/15 | 0.2451 | 0.2481 | 0.6818 | 0.6893 | 3.641 | 5.439 |

## What went wrong

- Sept 8: Gamma MC flipped the near-even Angels–Boston and Tampa Bay–Atlanta games toward the losing home teams. All three critical-gap favorites (NYY, MIL, LAD) won, rewarding Fixed’s stronger probabilities.
- Sept 9: Gamma MC flipped Tampa Bay–Atlanta and Pittsburgh–White Sox toward losing home teams. Both arms missed Toronto–Athletics, St. Louis–San Francisco, Washington–San Diego, Texas–Seattle, Cleveland–Baltimore, Mets–Miami, and Angels–Boston.
- Sept 9 scoring: Mets–Miami finished 15–14 versus a projected 7.54 total, a 21.46-run error. Toronto–Athletics finished 0–2 versus 11.95; Houston–Philadelphia finished 7–11 versus 8.35. Dodgers won 14–1, but the projected margin was only 2.23 runs.
- Gamma softened several losing favorites and therefore reduced some individual losses. Across both dates its probability scores remained worse. This is descriptive evidence from two date clusters, not calibration or promotion proof.
- Starter fallback rows were retained: Sept 8 ARI away and SEA home; Sept 9 ATL home. No-fallback does not mean lineup/bullpen/weather completeness or Tier-A eligibility.
- Displayed run means yield diagnostic score errors only; full-game run-line/total settlement and interval coverage are not established here. No frozen market benchmark is present.
- No causal attribution to a specific pitcher, lineup, bullpen or roof condition has been established by this audit. Keep both arms and investigate input-state/score-distribution errors before tuning.

## Two-day descriptive summary

```json
{
  "scope": "DIAGNOSTIC_ONLY",
  "dates": [
    "2026-09-08",
    "2026-09-09"
  ],
  "n": 30,
  "fixed_correct": 16,
  "mc_correct": 12,
  "date_clusters": 2,
  "promotion_eligible": false,
  "fixed_brier": 0.23272888122755422,
  "mc_brier": 0.24327540482,
  "fixed_log_loss": 0.6541085660181634,
  "mc_log_loss": 0.6793514402608641,
  "delta_log_loss": 0.02524287424270068,
  "margin_error": 3.1085599999999998,
  "total_error": 4.3535113333333335
}
```

This report and grade records do not alter canonical prospective eligibility, existing grades, production models or action authority. No meaningful date-cluster confidence interval is claimed from two dates.
