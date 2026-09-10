# September 9 MLB postgame diagnostic

Frozen forecast run 34330917567. Official results matched by gamePk, date and home/away.
No model rerun, forecast mutation, market settlement or promotion. One date cluster.

| Game | Final (away–home) | Fixed P(home) | MC P(home) | Fixed correct | MC correct |
|---|---:|---:|---:|---:|---:|
| Minnesota Twins @ Detroit Tigers | 2–7 | 56.4% | 54.4% | 1 | 1 |
| Toronto Blue Jays @ Athletics | 0–2 | 41.4% | 49.4% | 0 | 0 |
| St. Louis Cardinals @ San Francisco Giants | 6–7 | 41.0% | 43.8% | 0 | 0 |
| Washington Nationals @ San Diego Padres | 2–9 | 46.0% | 47.5% | 0 | 0 |
| Texas Rangers @ Seattle Mariners | 2–3 | 44.4% | 47.2% | 0 | 0 |
| Cleveland Guardians @ Baltimore Orioles | 5–9 | 49.1% | 49.4% | 0 | 0 |
| Houston Astros @ Philadelphia Phillies | 7–11 | 59.8% | 55.7% | 1 | 1 |
| New York Mets @ Miami Marlins | 15–14 | 59.8% | 56.2% | 0 | 0 |
| Los Angeles Angels @ Boston Red Sox | 6–4 | 69.0% | 58.0% | 0 | 0 |
| Colorado Rockies @ New York Yankees | 1–6 | 62.9% | 53.2% | 1 | 1 |
| Tampa Bay Rays @ Atlanta Braves | 7–2 | 49.0% | 51.2% | 1 | 0 |
| Arizona Diamondbacks @ Kansas City Royals | 2–5 | 61.7% | 54.6% | 1 | 1 |
| Pittsburgh Pirates @ Chicago White Sox | 4–2 | 47.4% | 50.9% | 1 | 0 |
| Chicago Cubs @ Milwaukee Brewers | 6–8 | 62.2% | 56.1% | 1 | 1 |
| Cincinnati Reds @ Los Angeles Dodgers | 1–14 | 78.1% | 61.9% | 1 | 1 |

## Summary

```json
{
  "scope": "DIAGNOSTIC_ONLY",
  "forecast_run_id": 34330917567,
  "forecast_archive_sha256": "f37858c9f976c356e17c1bf7c47d87831faed84adf801869053897d17a48d26b",
  "result_source_sha256": "1b8121f051563e5c92b6c76ed828d76d996eb58310e5f94baf0485755c031479",
  "all_games": {
    "n": 15,
    "fixed_correct": 8,
    "mc_correct": 6,
    "fixed_brier": 0.24510370771983322,
    "mc_brier": 0.24813490546666667,
    "fixed_log_loss": 0.6817797365125929,
    "mc_log_loss": 0.6892600349405249,
    "delta_brier": 0.003031197746833423,
    "delta_log_loss": 0.007480298427932008,
    "margin_error": 3.6409373333333335,
    "total_error": 5.439034666666666,
    "total_bias": -2.5767306666666667
  },
  "starter_bound": {
    "n": 14,
    "fixed_correct": 7,
    "mc_correct": 6,
    "fixed_brier": 0.245486286750485,
    "mc_brier": 0.24716861722142855,
    "fixed_log_loss": 0.6824326131532503,
    "mc_log_loss": 0.6873159501596817,
    "delta_brier": 0.0016823304709435657,
    "delta_log_loss": 0.004883337006431431,
    "margin_error": 3.5493192857142857,
    "total_error": 5.784273571428572,
    "total_bias": -2.717519285714286
  },
  "starter_fallback": {
    "n": 1,
    "fixed_correct": 1,
    "mc_correct": 0,
    "fixed_brier": 0.2397476012907086,
    "mc_brier": 0.26166294090000003,
    "fixed_log_loss": 0.6726394635433893,
    "mc_log_loss": 0.7164772218723294,
    "delta_brier": 0.02191533960929143,
    "delta_log_loss": 0.0438377583289401,
    "margin_error": 4.92359,
    "total_error": 0.6056899999999992,
    "total_bias": -0.6056899999999992
  },
  "critical_divergence": {
    "n": 1,
    "fixed_correct": 1,
    "mc_correct": 1,
    "fixed_brier": 0.04793041743636573,
    "mc_brier": 0.1450162561,
    "fixed_log_loss": 0.24709071657269005,
    "mc_log_loss": 0.47934310670783126,
    "delta_brier": 0.09708583866363427,
    "delta_log_loss": 0.2322523901351412,
    "margin_error": 10.76542,
    "total_error": 6.813739999999999,
    "total_bias": -6.813739999999999
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
