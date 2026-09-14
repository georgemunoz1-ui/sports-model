# September 8 MLB postgame diagnostic

Frozen forecast run 34273154914. Official results matched by gamePk, date and home/away.
No model rerun, forecast mutation, market settlement or promotion. One date cluster.

| Game | Final (away–home) | Fixed P(home) | MC P(home) | Fixed correct | MC correct |
|---|---:|---:|---:|---:|---:|
| Cleveland Guardians @ Baltimore Orioles | 9–5 | 57.8% | 53.4% | 0 | 0 |
| Minnesota Twins @ Detroit Tigers | 3–2 | 59.4% | 54.9% | 0 | 0 |
| Houston Astros @ Philadelphia Phillies | 6–5 | 39.4% | 46.0% | 1 | 1 |
| New York Mets @ Miami Marlins | 7–5 | 59.0% | 57.1% | 0 | 0 |
| Los Angeles Angels @ Boston Red Sox | 6–1 | 49.6% | 52.0% | 1 | 0 |
| Colorado Rockies @ New York Yankees | 3–5 | 79.9% | 61.4% | 1 | 1 |
| Tampa Bay Rays @ Atlanta Braves | 7–1 | 48.0% | 51.9% | 1 | 0 |
| Arizona Diamondbacks @ Kansas City Royals | 5–3 | 52.2% | 51.6% | 0 | 0 |
| Pittsburgh Pirates @ Chicago White Sox | 9–3 | 59.0% | 52.7% | 0 | 0 |
| Chicago Cubs @ Milwaukee Brewers | 3–4 | 73.4% | 59.0% | 1 | 1 |
| Washington Nationals @ San Diego Padres | 4–5 | 49.4% | 50.0% | 0 | 0 |
| Texas Rangers @ Seattle Mariners | 10–5 | 41.8% | 43.3% | 1 | 1 |
| Toronto Blue Jays @ Athletics | 4–2 | 35.7% | 41.9% | 1 | 1 |
| St. Louis Cardinals @ San Francisco Giants | 1–2 | 46.0% | 47.2% | 0 | 0 |
| Cincinnati Reds @ Los Angeles Dodgers | 2–3 | 76.2% | 60.3% | 1 | 1 |

## Summary

```json
{
  "scope": "DIAGNOSTIC_ONLY",
  "forecast_run_id": 34273154914,
  "forecast_archive_sha256": "5cb007a85cada78e4a041986c0b92e2783892baa4b81ccfaff3e13761e5ae8cf",
  "result_source_sha256": "8af260f306c925078b84df2a76d03cc463949e4706886b8eca0e02b9edbcb863",
  "all_games": {
    "n": 15,
    "fixed_correct": 8,
    "mc_correct": 6,
    "fixed_brier": 0.22035405473527525,
    "mc_brier": 0.23841590417333336,
    "fixed_log_loss": 0.6264373955237339,
    "mc_log_loss": 0.6694428455812033,
    "delta_brier": 0.018061849438058105,
    "delta_log_loss": 0.04300545005746935,
    "margin_error": 2.5761826666666665,
    "total_error": 3.267988,
    "total_bias": -0.009315999999999984
  },
  "starter_bound": {
    "n": 13,
    "fixed_correct": 7,
    "mc_correct": 5,
    "fixed_brier": 0.21988170257186151,
    "mc_brier": 0.24019399191538462,
    "fixed_log_loss": 0.6244509696758572,
    "mc_log_loss": 0.6729720962766246,
    "delta_brier": 0.02031228934352311,
    "delta_log_loss": 0.04852112660076737,
    "margin_error": 2.4636976923076923,
    "total_error": 3.096826923076923,
    "total_bias": 0.5943192307692308
  },
  "starter_fallback": {
    "n": 2,
    "fixed_correct": 1,
    "mc_correct": 1,
    "fixed_brier": 0.22342434379746445,
    "mc_brier": 0.22685833385000004,
    "fixed_log_loss": 0.6393491635349325,
    "mc_log_loss": 0.6465027160609648,
    "delta_brier": 0.003433990052535571,
    "delta_log_loss": 0.007153552526032225,
    "margin_error": 3.307335,
    "total_error": 4.380535,
    "total_bias": -3.932945
  },
  "critical_divergence": {
    "n": 3,
    "fixed_correct": 3,
    "mc_correct": 3,
    "fixed_brier": 0.05599651267446001,
    "mc_brier": 0.1585167189666667,
    "fixed_log_loss": 0.2686349724685403,
    "mc_log_loss": 0.5076628890837314,
    "delta_brier": 0.10252020629220668,
    "delta_log_loss": 0.23902791661519102,
    "margin_error": 0.82887,
    "total_error": 2.078703333333334,
    "total_bias": 2.078703333333334
  },
  "date_clusters": 1,
  "confidence_interval": "NOT_ESTIMATED_SINGLE_DATE_CLUSTER",
  "market_comparison": "UNAVAILABLE_NO_FROZEN_MARKET",
  "promotion_eligible": false
}
```

The 30 arm rows are a separate diagnostic child record, not an append to the PR17 canonical ledger.
Score errors refer to the frozen displayed run means; they are not run-line/total market settlement.
No raw simulation quantile arrays are present in this source ZIP, so interval coverage is not computed.

## What happened

Fixed Poisson: 8/15 winners, Brier 0.220354, log loss 0.626437.
Gamma MC: 6/15 winners, Brier 0.238416, log loss 0.669443.
Gamma minus Fixed: +0.018062 Brier and +0.043005 log loss; positive favors Fixed.

The MC direction flips toward Boston and Atlanta were both wrong. These explain the two-game
accuracy difference; fixed probabilities were close to 50%, so their correct sides were weak
preferences, not strong calls. San Diego's MC home probability was 0.49983, which rounds to
50.0% but still selected Washington; classify using full precision.

NYY, MIL and LAD won all three critical-gap games. Both arms selected those winners;
Fixed's higher confidence earned lower log loss (0.268635 vs 0.507663) in that slice.
This is a realized one-night scoring result, not proof that Gamma dispersion is misspecified.

Largest wrong-direction margin errors: PIT–CWS 6.67 runs, TB–ATL 5.84, LAA–BOS 4.97,
CLE–BAL 4.57. Largest total misses: TEX–SEA 8.31, TOR–ATH 6.54, CLE–BAL 5.95.
Overall total bias is near zero (-0.009 runs), yet total MAE is 3.268:
over- and under-predictions cancel in aggregate.

The two fallback games remain in the report: ARI won 5–3 (both arms wrong);
TEX won 10–5 (both arms right). That Texas win does not validate the missing Seattle starter
or establish that the pregame probability movement was informative.
The 13 rows without starter-fallback warnings still favor Fixed on both proper scores;
this slice means no starter fallback, not confirmed starters or Tier-A completeness.

No frozen market comparison is available. One date cannot support the intended date-cluster
uncertainty analysis. No promotion, blend or arm retirement follows from this slate.
Missing lineups/bullpen/weather are possible model limitations, not established causal
explanations of individual losses.

## Replay

The forecast ZIP is preserved verbatim as forecast.zip. Source receipt and raw official results
are retained beside it. analyze.py uses only these frozen local files. To rerun, copy the script,
forecast.zip, receipt.json and official_schedule.json into a new empty directory and execute
the script there; existing analysis and grade outputs are not overwritten.
