# Codex baseline with NoVig board — 2026-08-23

Models: MLB transparent RF/RA+starter reference · WNBA `wnba.rs.fourfactor_logit_ridge.v0_5.shadow` plus reference distributions · NFL information-adjusted preseason reference. Simulation seed `20260823`; 100,000 trials per game.

## Binding output contract

Every scheduled game receives a winner forecast and a total forecast. WNBA and NFL also receive an ATS forecast. `forecast_status` is always `FORECAST_REGISTERED`; freshness, compression, missing injuries, neutral-site limitations and wager authority appear only in the separate `action_status`. A blocked forecast remains visible and gradeable.

Reproduce with `python baseline_2026-08-23/reference_sim.py`. The deterministic JSON stdout sha256 is `8d8cee922a4e930367ddd801b871be564f41edca6199f0d089a6084cc6af72d4`.

The owner's model should answer the same card with, at minimum: `game`, immutable `model_id`, `training_cutoff_utc`, information class/dose, simulation seed and count, winner probability, projected score, projected total, ATS side/probability where applicable, total side/O-P-U probabilities, `forecast_status`, and separate `action_status`. Comparison occurs on winner Brier/log loss, margin MAE, total MAE and ATS result; sports and estimands are never pooled.

## Decision summary

| Sport | Forecasts emitted | Official action | Classification |
| --- | ---: | --- | --- |
| MLB | 15 winner + 15 total | No wager action | Transparent current-board reference; not V13 |
| WNBA | 4 winner + 4 ATS + 4 total | No wager action | Frozen shadow outputs remain gradeable; action blocked |
| NFL | 1 winner + 1 ATS + 1 total | **TEN moneyline (-170), 0.5 units** | Information-adjusted preseason reference |

## MLB simulation forecasts

| Game | Winner forecast | Projected score A-H | Total forecast | Action |
| --- | --- | ---: | --- | --- |
| STL@PHI | PHI 51.8% | 4.44-4.60 | OVER 7.5 (64.6%) | PASS_REFERENCE_ONLY |
| WSH@MIA | MIA 51.3% | 4.39-4.51 | OVER 8.5 (50.9%) | PASS_REFERENCE_ONLY |
| PIT@LAD | LAD 56.4% | 4.10-4.66 | UNDER 8.5 (50.4%) | PASS_REFERENCE_ONLY |
| CIN@ARI | ARI 57.3% | 4.22-4.88 | OVER 8.5 (53.2%) | PASS_REFERENCE_ONLY |
| ATL@MIL | MIL 54.5% | 4.03-4.45 | OVER 7.5 (58.1%) | BLOCKED_NEUTRAL_SITE_PARK_UNMODELED |
| TB@BAL | TB 51.5% | 4.69-4.55 | OVER 8.5 (55.0%) | PASS_REFERENCE_ONLY |
| TOR@NYY | NYY 55.2% | 3.66-4.09 | UNDER 7.5 (50.6%) | PASS_REFERENCE_ONLY |
| DET@KC | DET 56.0% | 4.60-4.07 | UNDER 8.5 (51.6%) | PASS_REFERENCE_ONLY |
| ATH@HOU | HOU 51.4% | 5.03-5.15 | OVER 9 (53.9%; push 10.6%) | PASS_REFERENCE_ONLY |
| LAA@TEX | TEX 55.9% | 3.93-4.44 | OVER 8 (45.0%; push 12.1%) | PASS_REFERENCE_ONLY |
| NYM@CWS | CWS 52.9% | 4.05-4.33 | OVER 8 (45.1%; push 12.1%) | PASS_REFERENCE_ONLY |
| SF@BOS | BOS 61.8% | 3.83-4.90 | OVER 8 (49.3%; push 11.8%) | PASS_REFERENCE_ONLY |
| CLE@COL | CLE 54.1% | 6.02-5.62 | OVER 11 (48.4%; push 9.7%) | PASS_REFERENCE_ONLY |
| MIN@SD | SD 52.8% | 4.13-4.37 | UNDER 8.5 (53.4%) | PASS_REFERENCE_ONLY |
| CHC@SEA | CHC 54.8% | 4.15-3.75 | OVER 7.5 (51.3%) | PASS_REFERENCE_ONLY |

For whole-number totals, the side label is the larger of over and under probabilities; push mass is reported separately. Therefore an over probability below 50% can still exceed the under probability after pushes.

## MLB board audit

The 2026-08-23 V13 card was not regenerated because the available checkout's MLB form state ends 2026-08-09. Instead of suppressing output, `reference_sim.py` emits a transparent comparison baseline from current-board RF/RA, starter ERA with explicit shrinkage, fixed reference park factors and negative-binomial scoring. The rows below remain a market-and-probables audit only. The VSiN `EST` columns were not used.

| Game | Probables | Captured market | Total | Action / reason |
| --- | --- | ---: | ---: | --- |
| STL@PHI | Leahy / Sanchez | PHI -210; STL +195 | 7.5 | NO MODEL ACTION — both starter records are zero-stat placeholders |
| WSH@MIA | Kent / Junk | MIA -157; WSH +146 | 8.5 | NO MODEL ACTION — both starter records are zero-stat placeholders |
| PIT@LAD | Bachar / Snell | LAD -301; PIT +239 | 8.5 | NO MODEL ACTION — price too large without a current probability |
| CIN@ARI | Abbott / Bratt | ARI -135; CIN +112 | 8.5 | NO MODEL ACTION — no current model probability |
| ATL@MIL | Mahle / Drohan | MIL -130; ATL +108 | 7.5 | BLOCKED — Bowman Field neutral-site / park-domain issue |
| TB@BAL | Martinez / Baz | TB -108; BAL +101 | 8.5 | NO MODEL ACTION — both starter records are zero-stat placeholders |
| TOR@NYY | Soriano / Rodon | NYY -134; TOR +125 | 7.5 | NO MODEL ACTION — usable matchup, stale team-form state |
| DET@KC | Valdez / Lynch | DET -106; KC -102 | 8.5 | NO MODEL ACTION — both starter records are zero-stat placeholders |
| ATH@HOU | Basso / Javier | HOU -176; ATH +163 | 9.0 | NO MODEL ACTION — current probability required before opposing the market |
| LAA@TEX | Kikuchi / Quantrill | TEX -163; LAA +135 | 8.0 | NO MODEL ACTION — Kikuchi row is a zero-stat placeholder |
| NYM@CWS | McLean / Newcomb | NYM -108; CWS +100 | 8.0 | NO MODEL ACTION — near-pick'em requires real discrimination |
| SF@BOS | Wilkinson / Bennett | BOS -231; SF +188 | 8.0 | NO MODEL ACTION — Wilkinson row is a zero-stat placeholder |
| CLE@COL | Griffin / Sugano | CLE -175; COL +144 | 11.0 | NO MODEL ACTION — both starters are zero-stat placeholders; Coors variance |
| MIN@SD | Ober / Buehler | SD -144; MIN +119 | 8.5 | NO MODEL ACTION — both starter records are zero-stat placeholders |
| CHC@SEA | Imanaga / Miller | CHC -112; SEA -108 | 7.5 | NO MODEL ACTION — near-pick'em requires real discrimination |

MLB research read only: PHI, LAD, BOS and CLE are the strongest market favorites; TOR@NYY, NYM@CWS and CHC@SEA are the cleanest price-sensitive matchups. Those are review priorities, not selections.

## NFL baseline selection

**TEN moneyline (-170), 0.5 units.** Classification: `INFORMATION_ADJUSTED_PRESEASON_BASELINE`; this is a real selection, but it is not misrepresented as output from a trained NFL model.

Tennessee announced that its starters could play approximately one half, while Seattle is expected to lean on Drew Lock and Jalen Milroe after its veteran work in the joint practice. The captured moneyline breaks even at 62.96%; the current broader-market comparison supports a 64%–65% evidence-adjusted win range (estimated EV +1.7% to +3.2% per unit). The smaller stake reflects unusually high preseason rotation uncertainty. TEN −4.5 (+102) remains a side lean, but same-line markets price the cover close to 50-50, so it is not the primary selection. The total remains a pass.

| Winner forecast | Projected score | ATS forecast | Total forecast | Action |
| --- | ---: | --- | --- | --- |
| TEN 64.5% | SEA 16.88 - TEN 21.13 | SEA +4.5 (50.8%) | UNDER 38.5 (51.3%) | **BET TEN ML -170, 0.5u** |

NFL market baseline: fair ML SEA 37.65% / TEN 62.35%; fair cover SEA +4.5 51.19% / TEN -4.5 48.81%; fair total over 47.54% / under 52.46%. The market-only numbers do not create the selection; the documented rotation information moves TEN moneyline into the separate information-adjusted baseline above.

## WNBA simulation forecasts

| Game | Winner forecast | Projected score A-H | ATS forecast | Total forecast | Action |
| --- | --- | ---: | --- | --- | --- |
| SEA@DAL | DAL 68.3% | 83.31-88.64 | SEA +8.5 (60.5%) | UNDER 172.5 (51.4%) | BLOCKED — DOG COMPRESSION |
| IND@CHI | IND 69.8% | 92.51-86.63 | IND -3.5 (57.9%) | UNDER 187.5 (72.5%) | BLOCKED — STALE STATE / NO INJURY BYTES |
| LVA@TOR | LVA 77.5% | 87.52-79.40 | TOR +13.5 (67.3%) | UNDER 180.5 (83.2%) | BLOCKED — DOG COMPRESSION + NEUTRAL-SITE HCA |
| WAS@POR | WAS 52.5% | 83.47-82.38 | POR +4.5 (61.6%) | OVER 164.5 (54.0%) | BLOCKED — DOG COMPRESSION |

ATS cushion is market line minus the model's fair line: SEA +3.17, IND +2.38, TOR +5.37, POR +3.41. Only IND clears the 2-point decision deadband without being an underdog-side compression read; it remains blocked by stale state and missing injury evidence.

Totals remain diagnostic, but they are emitted and gradeable. Their probabilities come from the disclosed reference total distribution rather than a validated WNBA totals head.
