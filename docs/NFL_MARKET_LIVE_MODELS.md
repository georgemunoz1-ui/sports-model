# Fitted NFL market-aware and live modes

Both requested modes have fitted artifacts and are connected to
`pipelines.cards.adapters.nfl` and `scripts/run_nfl_integrated.py`.
`data/nfl/modes_v1/runtime.json` pins each model's digest. These are usable
research models, not promoted wagering models. The football-only research
mode and prior issued artifacts remain available and unchanged.

## Commands

Run a captured event with the fitted market-aware ensemble:

```bash
python scripts/run_nfl_integrated.py --date 2026-09-14 \
  --event-id 2026_01_DEN_KC --mode enhanced_pregame \
  --model-id nfl.market_ensemble.v1.research \
  --market-packet /path/to/pregame_market_packet.json \
  --simulations 100000 --output /path/to/new_output_directory
```

Run a live three-way winner update after kickoff:

```bash
python scripts/run_nfl_integrated.py --date 2026-09-14 \
  --event-id 2026_01_DEN_KC --mode live \
  --model-id nfl.live_state_hgb.v1.research \
  --market-packet /path/to/preserved_pregame_market_packet.json \
  --live-packet /path/to/current_preplay_packet.json \
  --simulations 100000 --output /path/to/another_new_output_directory
```

For multiple events, either packet file may contain `event_packets`, an object
keyed by canonical event ID. Unknown model IDs never fall back. Missing required
market/state inputs produce explicit errors. The live path needs the captured
schedule but does not require loading the football coefficient/context package.

## Acquiring and binding inputs

`prepare_nfl_mode_packet.py` creates a source-hashed packet from acquired raw
JSON. It requires the actual observation time and source, records ingestion time,
and refuses future observation times. It does not download a live feed or invent
an observation time from the game clock. For a market capture, the raw JSON must
contain `event_id`, `home_team`, `away_team`, and `quotes` with exactly
`home_moneyline`, `away_moneyline`, `home_spread`, `total_line`. Home spread is
negative for a home favorite. These are full-game American-odds observations.

For a live capture, raw JSON is a single nflverse-shaped pre-play record with
event/team identifiers, `play_id`, `posteam`, `posteam_score`, `defteam_score`,
`game_seconds_remaining`, `quarter_seconds_remaining`, `qtr`, `down`, `ydstogo`,
`yardline_100`, `home_timeouts_remaining`, and `away_timeouts_remaining`.
Supply `--effective-at` as the actual state time. The adapter maps possession
scores to home/away and normalizes OT regulation-seconds remaining to zero,
retaining the separate OT period clock. It never uses post-play totals as state.

```bash
python scripts/prepare_nfl_mode_packet.py --kind live \
  --raw acquired_play.json --event captured_event.json \
  --source SOURCE_URL --observed-at ACTUAL_OBSERVATION_UTC \
  --effective-at ACTUAL_PREPLAY_STATE_UTC --output current_live_packet.json
```

Live state must describe a scrimmage pre-play situation in quarters 1–5, with
valid score, clock, down, possession, field position and timeouts. Current and
effective state age must both be <=120 seconds. The pregame prior must have been
observed before kickoff. Live prices are not fitted inputs of this version.
An old game cannot be emitted as a live forecast using a model trained on its
season. Historical inference uses the dedicated replay/evaluation commands.
The writer refuses future information cutoffs and never overwrites an output
folder. Simulations and manifests are saved, including a separate tie class.

## Market model

The design was externally committed before fitting (318ede5014aed5f219b840c0e254d30804fb69fe).
The full integrated football arm's chronological OOF outputs were joined to
historical moneylines, spreads and totals. On 2019–2021, separate football weights
in {0.0,0.1,...,1.0} were selected for binary Brier, margin MAE and total MAE.
Selected football weights are 0.0, 0.0 and 0.1 respectively. Thus winner and
margin currently equal the market benchmark; totals blend 10% football and 90%
market. The selected boundary value is retained, not replaced with a hand-chosen
weight. The price input is declared, never presented as an independent edge.

The 2022–2025 evaluation contains 1,084 non-tie games. Binary Brier:
football 0.229396; market 0.210455; ensemble 0.210455. Ensemble versus market delta
is exactly zero; its specified superiority screen fails. Total MAE changes from
10.18905 market to 10.18108 ensemble, a small descriptive difference. Margin MAE
is 9.49448 for both. The ensemble has its own 2019–2021 residual-score bank;
it does not borrow the full model's bank. Its score simulation includes empirical
tie mass and is still unvalidated for ATS/key-number settlement.

Historical market observation times are not archived. This is reused historical
pregame-market evidence, not proof of early-morning performance or a closing-line
archive. New input timestamps do not retroactively establish historical PIT validity.

## Live model

A fixed HistGradientBoostingClassifier is trained on 2015–2020 sampled pre-play
states. Temperature is selected from the frozen grid using game-weighted
three-way log loss on 2021–2022; selected value 1.25. The frozen temporal model is
evaluated on 2023–2025. A deployment model is then refitted on 2015–2025 with the
same hyperparameters and frozen temperature; the refitted instance has no new
prospective validation. Portable numeric-tree inference reproduces sklearn
probabilities to floating-point tolerance, without distributing executable pickle.

Fifteen features represent score, margin, clocks, quarter, possession, down,
distance, field position, timeouts, a pregame market logit, and score/time and
possession/field-position transforms. One first valid state per quarter/clock
minute is sampled; every game receives equal total training/scoring weight.
No EPA, WPA, final score or post-play score is a predictor. Final outcomes are
used only as targets. The three outcomes are AWAY_WIN, HOME_WIN, TIE including OT.

Corrected test population: 816 games, 51,719 states, including 309 OT states in
43 games. Three-way Brier 0.321788 vs 0.422186 for a static pregame market prior.
Paired game-weighted change -0.100398, game-bootstrap 95% interval
[-0.116768,-0.083735]. Log loss 0.491871 vs 0.618260. This passes the specified
live-versus-static screen. The advantage includes observing game state; it is not
an equal-information comparison with another live model. The test contains only
one actual tied game, so tie calibration is not established. Live outputs are
winner probabilities and categorical outcome simulations, not drive simulations,
final score paths, player props, or ATS/total probabilities. There is no explicit
OT possession-entitlement feature. Quarter-level scores and reliability bins
are preserved in the evaluation package.

The first extraction incorrectly required the source OT game clock to be zero,
excluding OT states. That extraction/fit was invalidated and retained. The source
clock was normalized correctly and the unchanged fitting design rerun. Reported
results use dataset_02/fit_02 only; no hyperparameters were retuned from test results.

## Evidence and reproducibility

- 2,895 completed historical regular-season games; 2,894 have the required market
  fields. 2017_04_CHI_GB is explicitly excluded for missing moneylines.
- Corrected live dataset: 183,966 states over 2015–2025.
- Source files and derived datasets have SHA256 manifests. Corrected historical
  PBP is not an archive of original real-time receipts.
- 29 integrity tests, including pre/post-play separation, OT normalization,
  missing/future/wrong-event inputs, exact model selection and future writer cutoffs.
- Two matching 100,000-draw replays for market binary, market score and live
  categorical simulations. Replays are labeled technical checks, not new forecasts.
- Full repository health is not asserted: this workspace is a partial recovered
  checkout. NFL-specific tests and GitHub CI are the checks executed for this change.

Training commands: `build_nfl_mode_data.py`, `fit_nfl_modes.py`,
`package_nfl_modes.py`; replay command: `verify_nfl_modes.py`. The separate
report archive contains derived datasets, per-game evaluation rows, simulation
arrays and invalidation evidence; code and fitted deployment models are in Git.

Source documentation: [nflverse schedule data](https://nflreadr.nflverse.com/reference/load_schedules.html),
[nflverse play-by-play data](https://nflreadr.nflverse.com/reference/load_pbp.html).
