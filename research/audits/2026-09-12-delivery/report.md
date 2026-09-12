# September 11 closeout and September 12 diagnostic card

Partial completion: September 11 final results captured; forecast grading blocked pending original frozen card. September 12 MLB: 15 model outputs plus 100,000 Monte Carlo paths per game. CFB and MLS remain incomplete.

Source branch: codex/nfl-wnba-nba-models-v1 at 3d6f9e787c7fb55d43a55e685c339c4038fad80d. [Executed workflow](https://github.com/georgemunoz1-ui/sports-model/actions/runs/34689434612).

Research diagnostics only. Action authority OFF. No model promotion. No old forecast rewritten. Raw artifact manifest: 28/28 members verified. Healthcheck: 13 failures, 8 warnings.

## September 11 final results

These are result records, not completed forecast grades. Rounded conversation predictions cannot substitute for the original frozen artifact.

| League | Away | Score | Home |
|---|---|---:|---|
| MLB | Pittsburgh Pirates | 2–12 | Chicago Cubs |
| MLB | Colorado Rockies | 2–6 | Detroit Tigers |
| MLB | Los Angeles Angels | 3–4 | Washington Nationals |
| MLB | New York Mets | 4–6 | New York Yankees |
| MLB | Baltimore Orioles | 7–4 | Toronto Blue Jays |
| MLB | Houston Astros | 1–3 | Tampa Bay Rays |
| MLB | Kansas City Royals | 3–2 | Boston Red Sox |
| MLB | Los Angeles Dodgers | 6–2 | Miami Marlins |
| MLB | Philadelphia Phillies | 5–6 | Atlanta Braves |
| MLB | Cincinnati Reds | 0–20 | Milwaukee Brewers |
| MLB | Cleveland Guardians | 5–2 | Minnesota Twins |
| MLB | Chicago White Sox | 3–7 | St. Louis Cardinals |
| MLB | Seattle Mariners | 5–6 | Athletics |
| MLB | Texas Rangers | 1–9 | Arizona Diamondbacks |
| MLB | San Diego Padres | 7–5 | San Francisco Giants |
| CFB | Missouri Tigers | 38–21 | Kansas Jayhawks |
| CFB | Villanova Wildcats | 13–59 | Louisville Cardinals |
| CFB | Norfolk State Spartans | 3–59 | Virginia Cavaliers |
| CFB | Richmond Spiders | 0–73 | NC State Wolfpack |
| CFB | Rutgers Scarlet Knights | 21–28 | Boston College Eagles |

## September 12 MLB

Snapshot requested 10:49:44 UTC / 3:49:44 AM PDT; actual source fetch completed later, as recorded in the JSON provenance. Both probabilities below refer to the HOME team. Scores are simulated mean runs, not supported full-game settlement products.

| Away @ Home | Away–home mean runs | Fixed home % | Gamma MC home % | Input warning |
|---|---:|---:|---:|---|
| Colorado Rockies @ Detroit Tigers | 4.38–4.78 | 55.2 | 53.0 | Incomplete contextual inputs |
| New York Mets @ New York Yankees | 3.91–4.72 | 60.7 | 53.1 | Incomplete contextual inputs |
| Pittsburgh Pirates @ Chicago Cubs | 4.18–4.91 | 59.3 | 59.2 | Incomplete contextual inputs |
| Baltimore Orioles @ Toronto Blue Jays | 4.00–3.98 | 49.7 | 49.6 | Incomplete contextual inputs |
| Los Angeles Angels @ Washington Nationals | 4.17–4.63 | 56.1 | 52.7 | Incomplete contextual inputs |
| San Diego Padres @ San Francisco Giants | 3.58–3.26 | 45.2 | 46.1 | Incomplete contextual inputs |
| Kansas City Royals @ Boston Red Sox | 3.57–3.82 | 53.6 | 49.7 | Incomplete contextual inputs |
| Cleveland Guardians @ Minnesota Twins | 4.05–3.82 | 46.7 | 50.1 | Incomplete contextual inputs |
| Los Angeles Dodgers @ Miami Marlins | 3.95–3.18 | 38.8 | 47.4 | Incomplete contextual inputs |
| Houston Astros @ Tampa Bay Rays | 4.23–4.29 | 50.7 | 49.3 | Incomplete contextual inputs |
| Cincinnati Reds @ Milwaukee Brewers | 3.79–5.52 | 71.3 | 58.0 | HOME_STARTER_PRIOR_FALLBACK:era,gs,k,bb |
| Philadelphia Phillies @ Atlanta Braves | 4.08–4.35 | 53.7 | 51.9 | AWAY_STARTER_PRIOR_FALLBACK:era,gs,k,bb |
| Chicago White Sox @ St. Louis Cardinals | 3.52–3.53 | 50.2 | 49.3 | Incomplete contextual inputs |
| Texas Rangers @ Arizona Diamondbacks | 3.94–4.69 | 59.9 | 57.3 | Incomplete contextual inputs |
| Seattle Mariners @ Athletics | 6.24–5.86 | 45.8 | 47.5 | Incomplete contextual inputs |

Fixed Poisson and Gamma/workload simulation use different distributions. Their gaps are not Monte Carlo convergence errors. Largest gap: Cincinnati–Milwaukee, 13.26 percentage points. Four direction flips: KC–BOS, CLE–MIN, HOU–TB, CWS–STL. Near-50% differences should not be treated as strong directional signals.

## CFB and MLS status

CFB emitted only Jacksonville State–Ohio (Ohio 54.2815% model / 53.813% simulation, home margin +2.3341) and New Mexico State–Hawaii (Hawaii 81.8687% / 81.610%, home margin +19.7614). These are incomplete native diagnostics from the cached schedule, not a reconciled full card. No score/total projection is supplied by this margin engine. The other 78 cached rows retain their blocks.

MLS has 12 captured scheduled events but no completed model/simulation output in this run. NFL, NBA, WNBA, and NHL captures contained no events for September 12.

## Defects

- **SEP11_FROZEN_FORECAST_NOT_RECOVERED**: 20 final outcomes captured; exact Sep11 probabilities, input lineage, and original bytes not recovered. No probability grades appended.
- **CFB_RATING_FALLBACK_EXHAUSTED**: Native CFB runner generated 2 forecasts from 80 cached schedule rows; 78 blocked. Empty fallback rating map in adapter.
- **CFB_SCHEDULE_RECONCILIATION_REQUIRED**: Fresh ESPN capture returned 25 events; cached Sep3 schedule contains 80 rows for Sep12. Neither count is certified as complete current FBS coverage.
- **CFB_CURRENT_STATE_NOT_ASSIMILATED**: No validated current-season assimilation or cross-division repair applied; no emergency forecasts fabricated.
- **MLS_STATE_NOT_MATERIALIZED**: 12 events in source capture. Baseline code exists but verified historical state and a simulation run were not materialized for this card.
- **HEALTHCHECK_RED**: 13 failures, 8 warnings in captured runner environment. Workflow success is not operational acceptance.
- **MLB_STARTER_PRIOR_FALLBACK**: CIN at MIL: home starter statistical prior fallback. PHI at ATL: away starter statistical prior fallback.
- **MLB_PRESENTATION_CONTRACT**: Native CSV claims runline/total supported after line attachment and grading eligible. Delivery overlay explicitly declines full-game settlement support and canonical prospective eligibility; original output preserved.
- **MLB_INFORMATION_LIMITATIONS**: Complete lineup, bullpen availability, and weather/roof binding not established. Fetch clocks do not prove historical source-effective timestamps.
