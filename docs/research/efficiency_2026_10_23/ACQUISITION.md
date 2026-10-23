# Efficiency experiment source acquisition

Base repository: `278b9a2e655b72b720fefc215a5129a8e6cd2c93`. Acquisition occurred on 2026-10-23 UTC. No original forecast, baseline, default, canonical grade, or action authority was changed.

**38 of 38 requested source files were captured with HTTP 200; 625,326,081 bytes.** SHA-256 was recomputed from every retained file when preparing `acquisition_manifest.json`. These are acquisition counts, not eligible/evaluated/USED populations. Large raw files remain outside git; the committed compact manifest preserves their public requested URL, digest, size and actual retrieval time. Redirect headers and signed temporary URLs are excluded.

## Historical source census

| League | Provider season | Dataset | Games | Rows |
|---|---:|---|---:|---:|
| CFB | 2021 | classic_epa_pbp | 887 | 163444 |
| CFB | 2022 | classic_epa_pbp | 1459 | 252307 |
| CFB | 2023 | classic_epa_pbp | 1494 | 254090 |
| CFB | 2024 | classic_epa_pbp | 1609 | 277048 |
| CFB | 2025 | classic_epa_pbp | 1657 | 293200 |
| CFB | 2026 | classic_epa_pbp | 925 | 163933 |
| NBA | 2021 | team_box | 1166 | 2332 |
| NBA | 2021 | schedule | 1204 | 1204 |
| NBA | 2021 | player_box | 1172 | 31593 |
| NBA | 2022 | team_box | 1324 | 2648 |
| NBA | 2022 | schedule | 1335 | 1335 |
| NBA | 2022 | player_box | 1324 | 33880 |
| NBA | 2023 | team_box | 1321 | 2642 |
| NBA | 2023 | schedule | 1322 | 1322 |
| NBA | 2023 | player_box | 1321 | 34057 |
| NBA | 2024 | team_box | 1320 | 2640 |
| NBA | 2024 | schedule | 1322 | 1322 |
| NBA | 2024 | player_box | 1320 | 35028 |
| NBA | 2025 | team_box | 1324 | 2648 |
| NBA | 2025 | schedule | 1329 | 1329 |
| NBA | 2025 | player_box | 1324 | 35250 |
| NBA | 2026 | team_box | 1326 | 2652 |
| NBA | 2026 | schedule | 1330 | 1330 |
| NBA | 2026 | player_box | 1326 | 34883 |
| NBA | 2027 | team_box | 14 | 28 |
| NBA | 2027 | schedule | 1206 | 1206 |
| NBA | 2027 | player_box | 14 | 385 |

NBA provider season 2027 is the 2026–27 season. Historical counts include source-provided postseason/other rows until the model normalizer applies its declared regular-season population. Team-box and player-box game counts differ in 2021; availability of one table does not establish completeness of the other.

CFB classic PBP includes non-FBS games and some rows without schedule timestamps. The selected baseline must retain its exact historical state/feature construction, while evaluation explicitly filters its declared FBS-v-FBS/week eligibility. Never treat raw PBP game counts as the evaluated population.

## Provenance and chronology limits

- All historical archives were retrieved now. They support retrospectively reconstructed, past-game-only features; they do not prove what the provider displayed before historical kickoffs/tipoffs. Original provider observation time is unknown.
- Third-party CFB EPA model training vintage and its historical training cutoff are unverified. EPA-based results must disclose this additional provenance limitation. Market, spread, over/under, WP and WPA columns exist in raw PBP but are not authorized feature inputs for these market-blind experiments.
- The CFB 2026 PBP release includes 925 unique game IDs, but about 45% of its rows lack `start_date`; the authoritative schedule join is required. JMU–App State event 401869845 is absent from this capture. Fresh ESPN summaries are descriptive result evidence, not a substitute for missing fitted EPA.
- NBA season 2027 release initially contains 14 games through October 21. Fresh ESPN summary captures add the two October 22 games, event 401909093 and401909094. These results were first observed by this acquisition at the actual retrieval timestamps; their final-whistle availability is not invented.
- The current scoreboards returned 12 NBA and 5 CFB events for October 23. October 24 returns 8 NBA and 25 CFB events. The October 24 CFB response is not independently certified as a complete all-day census.

## Current normalized NBA packet and reconciliation

`nba_current_normalized_v3.json` contains 2 completed games and 20 future events, with 0 parser exclusions. The current packet has 2/2 game-level PASS reconciliation results: all four team point totals reconcile to shooting totals and player points; player rebounds reconcile; minutes use declared whole-minute rounding. Oklahoma City sums to 242 displayed player minutes against 240 regulation minutes, within the explicit rounding tolerance. No exact second-level minutes are claimed.

The preserved earlier normalization attempt `nba_current_normalized.json` excluded both finals because the summary header omitted `period`; it was not used. v2 correctly derives completed period count from matching home/away line-score lengths. v3 adds player production and rounding metadata. The complete historical normalizer exclusions belong in the model-run reports, not this acquisition census.

Cross-source findings from the user-supplied Dunks & Threes screenshots versus the fresh ESPN summaries:

- Nembhard: D&T box table says DNP but its shooting table says 5 points. ESPN explicitly records `didNotPlay=false`, 5 points, and Denver player sums reconcile to 84. No D&T player record was imported.
- Blocks: D&T team totals display Denver 9/OKC 2 and Cleveland 2/Philadelphia 7; ESPN player and team totals reconcile to Denver 2/OKC 9 and Cleveland 7/Philadelphia 2. These conflicting D&T values remain quarantined; source priority is not used to silently rewrite evidence. Blocks are not inputs in the first possession-efficiency experiment.

## Current schedule identities

| League | Event ID | UTC start | Matchup |
|---|---|---|---|
| NBA | 401909848 | 2026-10-23T20:00Z | CHI @ MIL |
| NBA | 401909095 | 2026-10-23T23:00Z | NY @ BOS |
| NBA | 401909843 | 2026-10-23T23:00Z | ATL @ CHA |
| NBA | 401909844 | 2026-10-23T23:00Z | DAL @ IND |
| NBA | 401909845 | 2026-10-23T23:00Z | MIN @ ORL |
| NBA | 401909846 | 2026-10-23T23:00Z | TOR @ WSH |
| NBA | 401909847 | 2026-10-24T00:00Z | DET @ MIA |
| NBA | 401909096 | 2026-10-24T01:30Z | HOU @ SA |
| NBA | 401909849 | 2026-10-24T01:30Z | NO @ UTAH |
| NBA | 401909850 | 2026-10-24T02:00Z | MEM @ GS |
| NBA | 401909851 | 2026-10-24T02:00Z | LAC @ LAL |
| NBA | 401909852 | 2026-10-24T02:00Z | POR @ SAC |
| NBA | 401909853 | 2026-10-24T22:00Z | MIA @ CHA |
| NBA | 401909854 | 2026-10-24T23:30Z | BKN @ CLE |
| NBA | 401909855 | 2026-10-24T23:30Z | MIL @ PHI |
| NBA | 401909857 | 2026-10-25T00:00Z | WSH @ CHI |
| NBA | 401909858 | 2026-10-25T00:00Z | SA @ DAL |
| NBA | 401909856 | 2026-10-25T00:30Z | HOU @ ATL |
| NBA | 401909859 | 2026-10-25T01:00Z | NO @ DEN |
| NBA | 401909860 | 2026-10-25T02:00Z | GS @ PHX |
| CFB | 401858271 | 2026-10-23T23:00Z | DUKE @ UVA |
| CFB | 401861965 | 2026-10-23T23:00Z | MASS @ CONN |
| CFB | 401862808 | 2026-10-24T00:30Z | ARMY @ TLSA |
| CFB | 401864525 | 2026-10-24T01:00Z | AFA @ WYO |
| CFB | 401858272 | 2026-10-24T02:30Z | NCSU @ STAN |
| CFB | 401858274 | 2026-10-24T16:00Z | PITT @ MIA |
| CFB | 401858496 | 2026-10-24T16:00Z | IU @ MICH |
| CFB | 401856840 | 2026-10-24T16:00Z | TTU @ CIN |
| CFB | 401856728 | 2026-10-24T16:00Z | LSU @ AUB |
| CFB | 401858270 | 2026-10-24T16:00Z | CAL @ SMU |
| CFB | 401858498 | 2026-10-24T16:00Z | RUTG @ NU |
| CFB | 401856841 | 2026-10-24T16:00Z | WVU @ TCU |
| CFB | 401862809 | 2026-10-24T16:00Z | RICE @ FAU |
| CFB | 401866450 | 2026-10-24T16:00Z | WMU @ TOL |
| CFB | 401856834 | 2026-10-24T17:00Z | BAY @ KU |
| CFB | 401866446 | 2026-10-24T17:00Z | AKR @ KENT |
| CFB | 401866476 | 2026-10-24T17:00Z | M-OH @ CMU |
| CFB | 401858495 | 2026-10-24T19:00Z | ORE @ ILL |
| CFB | 401856835 | 2026-10-24T19:30Z | BYU @ UCF |
| CFB | 401858499 | 2026-10-24T19:30Z | MSU @ UCLA |
| CFB | 401856731 | 2026-10-24T19:30Z | TENN @ SC |
| CFB | 401856727 | 2026-10-24T19:30Z | TA&M @ ALA |
| CFB | 401858497 | 2026-10-24T19:30Z | IOWA @ MINN |
| CFB | 401856730 | 2026-10-24T19:30Z | OU @ MSST |
| CFB | 401858273 | 2026-10-24T19:30Z | BC @ GT |
| CFB | 401862810 | 2026-10-24T19:30Z | UNT @ NAVY |
| CFB | 401864526 | 2026-10-24T19:30Z | HAW @ NIU |
| CFB | 401866447 | 2026-10-24T19:30Z | SAC @ BALL |
| CFB | 401866448 | 2026-10-24T19:30Z | BGSU @ BUFF |
| CFB | 401856839 | 2026-10-24T19:45Z | KSU @ ASU |

## Schemas

- CFB: event/team identifiers, `year/season/week`, schedule metadata, `EPA`, `epa_success/success`, rush/pass flags, downs, penalties/no-play flags. Selective reads and explicit identity reconciliation are required; source EPA is unadjusted until the challenger fits opponent effects.
- NBA team boxes: event/team/opponent IDs, `team_home_away`, `team_score`, FGM/FGA,3PM/3PA,FTM/FTA,ORB/DRB, `total_turnovers` and schedule period metadata. Estimated possessions must be labeled as estimates and cannot be called observed possessions.
- NBA player boxes: player/team/event IDs, minutes, points, shot counts, rebounds, DNP/status and starter flags. These are observed game participation, not historical pregame availability or expected-minutes projections.
- Normalized current NBA rows: `event_id=NBA:<provider_id>`, `start_time_utc`, `season`, home/away IDs/names/scores/stats/players, `duration_minutes`, `overtime_periods`, `minutes_decimal_places`, source digests/retrieval timestamps, and explicit availability semantics. Future rows omit outcomes.

## Reproduction

```bash
python scripts/acquire_efficiency_history.py --output NEW_SOURCE_DIR --cfb-seasons 2021 2022 2023 2024 2025 2026 --nba-seasons 2021 2022 2023 2024 2025 2026 2027 --player-box
python scripts/capture_efficiency_current.py --output NEW_CURRENT_DIR --date 20261022 --date 20261023 --date 20261024 --include-final-summaries
python scripts/prepare_efficiency_current_nba.py --capture-dir NEW_CURRENT_DIR --output NEW_NORMALIZED_JSON
```

Each capture/normalization output must be new. Recapture is not guaranteed byte-identical because provider releases and endpoints can update; compare digests and create new source identities. This packet establishes data acquisition and scoped source checks only. Personnel stages remain limited by missing historical pregame availability/expected-minutes evidence.

## Durable raw evidence

All seven data-only source archives were saved successfully, with identity metadata applied to their original local paths. `source_persistence.json` binds archive SHA-256, byte count, filename, Library identity and local path. CFB is split by season; NBA history and current source snapshots share one archive. No code/repository snapshot is duplicated in these archives. Full raw source bytes are preserved; only report metadata is sanitized to exclude redirect headers and temporary signed URLs.
