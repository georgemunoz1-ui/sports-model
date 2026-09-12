# CFB input intake — September 12, 2026

Status: DATA_CAPTURED_AND_NORMALIZED. No new forecast or fitted parameter change.

Current schedule captured 21:40Z; subsequent roster recapture and official/weather fetches have individual receipt times. These are retrieval-time observations, not permission to backdate earlier forecasts.

- Full raw schedule: 80 events. Targeted live enrichment: 46 teams whose games were pregame FBS/FBS at schedule capture.
- Corrected ESPN roster default limit: 4,600 became 5,320 player listings after explicit limit=1000. Completeness versus official rosters remains unverified. All 46 have season statistics; the aggregate statistics endpoint does not establish a complete historical effective-time contract.
- No usable API depth charts. Official GT Week 1 chart remains a carry-forward warning. Tennessee Week 2 notes and Iowa notes are captured; published claims are not confirmed kickoff availability. Canonical player binding and numeric impacts remain pending.
- NWS point/hourly JSON captured for Austin, Atlanta and Iowa City; venue coordinates are queries, not verified stadium-level weather measurements. Flight arrivals and travel disruption are UNKNOWN.
- Historical scoreboard acquisition: 80 successful monthly requests spanning seasons 2020–2025, including spring 2021. 9,169 deduplicated final events, 9,157 with first-half scores. 933 duplicate captures collapsed, no normalized event conflicts, two empty event objects quarantined. This is observed coverage, not independently established completeness.
- Historical team/division membership needs audit before FCS/FBS fitting. These outcomes retrieved now are not historical pregame snapshots. Elo features must be generated before each outcome update; season membership must not be inferred from 2026 membership.
- CFBD credentials absent in this runtime. No licensed feed or CFBD data claimed collected.

Normalized predictive tables contain no odds. Raw receipts refer to source responses that may contain markets; keep these outside model inputs. No model improvement, calibration, selection, or canonical pregame registration is established.

Remote scope: normalized tables, source receipts, official PDF text extracts, NWS JSON, and collection/normalization scripts. Full ESPN raw responses and official PDF binaries remain local; remote raw-source completeness is NOT established.

## Read the package

`parts/` stores binary chunks. `parts_manifest.json` specifies each original file, ordered part paths, byte count and SHA-256. Concatenate parts in listed order; verify the original hash; decompress JSON gzip files or open evidence_extracts.zip. `manifest.json` describes original artifacts. Do not parse source archives as feature rows.

Validation: unique IDs, quarter/final coherence when quarters supplied, first-half bounds, capture timestamps, and gzip exact roundtrip passed. This is data integrity validation, not repository-wide CI or predictive validation.

Next modeling work: temporal division audit, chronological training/holdout protocol, current QB/availability identity binding, then one isolated model challenger against the preserved baseline. Do not fit a new home intercept or cross-division prior from the day's outcomes.
