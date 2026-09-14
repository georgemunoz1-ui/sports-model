# September 10, 2026 diagnostic closeout

Requested at 10:54 PM Pacific September 10 (05:54 UTC September 11). Pacific daylight time applies. Actual source retrieval clocks are in receipts.json. All seven scheduled events final: MLB five, NFL one, FBS board one. Other captured league boards empty.

## Frozen evidence
MLB source forensic_0910/sources/mlb/diagnostic_card.json generated 08:22:50Z September 10; NFL source forensic_0910/nfl_forecast.json generated 08:25:06Z. Remote original package: research/audits/2026-09-10 at commit 43fe32a2c2969b1296b7a99791790fd072e0b5a1. Both use 100,000 simulations. Original artifacts unchanged. MLB cross-provider mapping uses same away/home pair and September 10 slate, with both IDs retained. No doubleheaders in this population.

## MLB
| Game | Frozen away-home score | Final away-home | Fixed direction | Gamma direction |
|---|---|---|---|---|
| TB-ATL | 3.93-3.86 | 1-3 | TB loss | TB loss |
| HOU-PHI | 4.17-5.68 | 2-1 | PHI loss | PHI loss |
| TEX-SEA | 3.38-3.28 | 3-4 | TEX loss | TEX loss |
| COL-NYY | 4.06-6.20 | 3-10 | NYY win | NYY win |
| PIT-CWS | 4.35-4.38 | 2-0 | CWS loss | PIT win |

Fixed: 1/5, Brier 0.262043, log loss 0.715953. Gamma: 2/5, Brier 0.253381, log loss 0.699985. Shared score centers total MAE 4.0916, margin MAE 2.514516. Full-game score diagnostics do not validate the missing extra-inning score continuation. Gamma's one direction flip won today; it is still near-even, not evidence for an outcome-based flip rule.

Largest total overestimates: HOU-PHI 9.855 projected vs 3 actual; PIT-CWS 8.728 vs 2. NYY margin projected +2.137 vs +7 actual. TEX-SEA total projected 6.658 vs 7 actual but winner direction missed at near-even probabilities. These observations cannot isolate causation from unbound lineup/bullpen/weather inputs.

## NFL
SF 27-LAR 7; halftime SF 10-LAR 7. Frozen LAR model 69.3757%, simulation 68.609%; projected LAR 27.86-SF 21.30. Both directions lost; margin error 26.5596 points, total error 15.15928. Model Brier 0.481298/log loss 1.183375; sim Brier 0.470719/log loss 1.158649. Actual margin -20 and total 34 both below simulation P10 (-11,36). One miss is not a calibration estimate. Prior-season rating construction and missing applied current availability/travel adjustments remain limitations, not established causal explanations.

Against the preserved 11:55 AM PT market snapshot, Rams -3.5 lost and Under 48.5 won. First-half Under 24.5 won with 17 points. User-reported Robinhood price 0.57 was not an executed trade confirmation; hypothetical profit is 0.43 per contract before fees. No first-half model existed, so no retrospective win probability or first-half model grade is assigned. Earlier pass at 0.57 was an evidence/price decision, not a forecast of Over.

## CFB
Miami 77-FAMU 7. Miami -59.5 covered and Over 65.5 won against preserved snapshot. RATING_FALLBACK_EXHAUSTED prevented a frozen forecast: no model grade, no reconstruction.

## Limits and next work
Diagnostic child records only; no canonical prospective promotion or action authority. Latest inspected repository health remained red; this grading job does not rerun or clear those gates. Keep frozen controls. Prioritize MLB run means and bullpen-state binding; NFL current roster/QB/travel state and a separately validated first-half engine. No retuning or promotion from this slate. Report all failures and retain the full population.
