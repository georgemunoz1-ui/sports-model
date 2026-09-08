# First official-source information pilot

Capture code: `4331269123503acd8f1ad23c5f4042c6ca055542`, PR #18, research branch.
Workflow: https://github.com/georgemunoz1-ui/sports-model/actions/runs/34271251397
Actions artifact: `10073891933`, independently downloaded and byte checked.
ZIP SHA-256: `368ccec44fca28d1ab604c762f4af0bec3b68bca198a5c72e2b2640f7fce5a7f`.
Actual capture cutoff: `2026-09-08T19:50:13.791952+00:00`.

The unmodified ZIP contains the MLB schedule, 30 active rosters, one NFL report,
retrieval receipts, registry, full slate, claims and deterministic state output.
Git retention supplements the 30-day Actions artifact. This commit is a later research archive,
not a protected pregame forecast registration. No forecast probabilities were emitted.

| Measure | Actual result | Limit |
|---|---|---|
| MLB schedule | 15/15 provider-date games retained | Not yet the canonical Pacific-date slate |
| Event identity | 15 official gamePk IDs parsed | Independent identity audit pending |
| Rosters | 30/30 scheduled teams parsed | A snapshot, not historical membership truth |
| Player identities | 840 roster IDs + 1 probable-only ID | Labeled identity accuracy unmeasured |
| Raw bytes | 32/32 SHA-256 and byte counts verified | Not a signed protected receipt |
| Cutoff | All 15 starts after actual capture completion | Information capture only |
| NFL report | 2 tables / 11 rows reparsed offline | Players, games and practice dates unbound |
| Extraction quality | Unmeasured | Parser tests do not measure false-positive rates |
| NLP runtime | Not run by this pilot | No checkpoint inference success claimed |
| A/B/C forecasts | Not run | No predictive transforms or quality comparison |

The probable-only identity `mlb:669203` has no active roster assignment in this capture.
Do not invent membership or remove its game. NFL blank game statuses remain UNKNOWN.
Confirmed starters, official lineups, bullpen availability and weather/roof are still missing.
All full-slate rows remain LOW and `NO_FORECAST_INFORMATION_PILOT`.

## Reproduce without a network

```bash
python -m research.news_information.replay_official_pilot research/news_information/pilot_evidence/2026-09-08/official_pilot_4331269.zip
python -m unittest discover -s research/news_information/tests -v
```

Replay verifies receipts and raw hashes, regenerates identities/claims/reduced state,
checks the original bundle digest and parses NFL tables using the newer deterministic parser.
The original capture predates that NFL parser; its report correctly remains capture-only.
`replay_result.json` is a later child diagnostic and does not mutate the original report.

## Remaining execution work

1. Bind NFL practice dates, canonical players and scheduled events; retain ambiguity.
2. Capture official MLB lineup/confirmed-starter observations with real retrieval times;
   distinguish submitted lineups, actual participants and late corrections.
3. Build independently reviewed labels from captured official documents. Split by date/source
   before evaluation; parser-generated answers are not independent labels.
4. Verify the compact NLP stack using exact checkpoint-specific APIs and resolved intake and
   dependency records. Measure destructive errors on those labels.
5. Run prospective A/B/C after sport-specific transforms and equal-population PR17 adapters
   are executable. Keep immutable source snapshots and separate outcome children.

Action authority OFF; predictive improvement unestablished; PR18 remains unmerged research.
