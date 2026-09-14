# September 10 preparation and September 8–9 MLB forensic audit

Source branch: codex/nfl-wnba-nba-models-v1 at fb2183dad9fa092850714a2a508d217b25bfcebd. Prep runner commit: 18d1d8347b6be825f2efbd8724cc4dd07d0c8ba1. GitHub run 34454769361; source artifact 10143013166, SHA-256 0c88889e185cf6eb52904bf6c2b1fed388f5ad0c9b200b1ea9e0d776f21a89d9. All 52 manifest members verified. Sources and their retrieval clocks are in the archived artifact. No protected-remote or operational-acceptance claim is made.

## Forensic findings

- 27 of 30 games had both frozen starter IDs match the actual starters, identified by official boxscore gamesStarted=1. Three remain UNRESOLVED because the frozen side used a fallback. No identified-starter mismatch was found. Whether any missing actual starter was knowable before cutoff remains null; later boxscores cannot prove that.
- All 60 expected team-run latent means reproduce within 1e-10 from the frozen inputs and seeded workload means. Component traces are ordered telescoping accounting, not unique causal attributions. The actual formula multiplies a starter/bullpen mixture by offense, pitcher-adjusted park and home factors; it is not intrinsically additive.
- All four Gamma direction flips persist in deterministic negative-binomial calculations at frozen latent means, with workload variance removed and ties split equally. Home shape exceeds away shape in all four; unequal distribution shapes can change win probability even with a lower mean. This is a numerical explanation, not evidence that the shape calibration is correct.
- The context tie allocator adds 0.35–0.44 percentage points toward home in the four cases. It reinforces, but does not create, these crossings. Monte Carlo standard error is about 0.158 percentage points per game. Workload plus sampling residual is reported without pretending to separate those two effects.
- Independent latent rates; no shared environment; bullpen is a team-RA proxy, not availability; no lineup, weather/roof or schedule/rest impact in these MLB inputs. Ties resolve winner only; simulated scores do not continue through extras.
- Fixed Poisson uses realized simulation run means, so it is not a wholly independent input model. The Angels–Boston frozen Fixed probability is 49.58% home versus 49.98% at latent means: sampling of the run means matters near 50%.
- Config values for several model parameters are hardcoded in engine functions rather than read dynamically. Changing only the JSON may alter hashes/seeds without changing the intended parameter. Audit the implementation before any future config experiment.
- Quality-stratified residuals are exploratory. Unknown lineup/bullpen/weather/rest states remain explicit. Original cards omitted simulation quantiles; interval coverage is null. No outcomes were used to change inputs or forecasts.

## September 10 scope

ESPN date-specific schedule capture: MLB 5, NFL 1, CFB FBS board 1; NBA/WNBA/NHL/MLS 0. CFB count is the FBS board, not a claim covering every lower-division competition. MLB StatsAPI card matches all five matchup/start-time pairs against ESPN.

MLB: 5/5 diagnostic forecasts, 100,000 paths each, generated around 08:22:50 UTC. All five probable starter input pairs are populated; confirmed lineups, bullpen availability and weather remain unbound. PIT fetch-time proxy is not historical effective-time proof.

NFL: San Francisco at Los Angeles Rams, Melbourne Cricket Ground, neutral site, 00:35 UTC September 11 (5:35 PM PT September 10). Existing NFL engine run for 100,000 paths with the existing baseline config. Prior-season SRS was computed from the repository's 272 market-free 2025 regular-season results using zero-sum least squares. No home-field bonus at this venue. This is BASELINE_DIAGNOSTIC; no 2026 player availability or validated offseason carryover adjustment. Model probability is logistic; simulation is a rounded Normal margin/total model, so they are different probability constructions.

CFB: Florida A&M at Miami, 00:00 UTC September 11. Existing card command found the event but failed with RATING_FALLBACK_EXHAUSTED. No probability or simulation was fabricated. The cross-division transform remains unsupported for a complete current forecast.

The repository healthcheck returned 13 failures and 8 warnings, including dependency/environment failures, lineage/manifest and release-readiness failures. The diagnostic capture/forecast job succeeding does not make the repository healthy. No selection or action authority is enabled; table directions are model opinions, not wagers.

## Retention and reproduction

Old September 8 and September 9 forecasts and grades are unchanged. This is a separate forensic child package. engine_snapshot.py matches both original frozen engine versions byte-for-byte. audit.py uses the original ZIPs and the official boxscore archive; nfl_baseline_run.py uses nfl_2025.csv plus the captured NFL schedule. All model changes, blends and promotions remain off. The prospective improvement protocol still needs a locked component, minimum effect, holdout and full eligibility gates before a challenger can qualify.

## MLB forecast board

| Game | Projected away–home | Fixed home probability | Gamma home probability |
|---|---:|---:|---:|
| Tampa Bay Rays @ Atlanta Braves | 3.93–3.86 | 49.06% | 49.84% |
| Houston Astros @ Philadelphia Phillies | 4.17–5.68 | 68.31% | 58.60% |
| Texas Rangers @ Seattle Mariners | 3.38–3.28 | 48.45% | 49.12% |
| Colorado Rockies @ New York Yankees | 4.06–6.20 | 74.61% | 58.73% |
| Pittsburgh Pirates @ Chicago White Sox | 4.35–4.38 | 50.38% | 49.26% |
