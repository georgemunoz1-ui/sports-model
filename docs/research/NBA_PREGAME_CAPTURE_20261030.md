# NBA combination pregame source capture

Implemented and exercised October 30, 2026, on draft PR #98. This extends the
explicit-dataset experiment with an opt-in acquisition command and extraction
replay in its actual audit/fit path. B0, the frozen protocol, existing forecast
records, model defaults and production runners are unchanged.

## Actual pregame execution

Final exercised run: `nba-pregame-8c057dfba8d749e2b1c59a74fac856a5`,
2026-10-30 19:00:31–19:00:42 UTC (12:00 p.m. Pacific). The preceding run,
`nba-pregame-daf6184a9ce34df1951231fd61ab8401`, was captured at
18:56:57–18:57:12 UTC. Both cover the same **10 distinct events**, not 20.
Neither run ingests outcomes or attempts a real-data fit.

| Quantity | Final run |
|---|---:|
| Schedule-matched future pregame opportunities | 10 |
| Original B0 point-margin records preserved | 10 |
| D&T upcoming events matched | 10 |
| Accessible D&T pregame point-margin values | 0 |
| Databallr public team rows / paired event observations | 30 / 10 |
| Source-eligible C1 / C2 observations | 0 / 0 |
| Fitting-eligible completed observations | 0 |
| Real coefficients fitted / new challenger forecasts | 0 / 0 |

| ESPN event | Matchup (away at home) | Start, Pacific |
|---|---|---|
| 401909277 | Charlotte at Washington | Oct 30, 4:00 p.m. |
| 401909278 | Chicago at Boston | Oct 30, 4:30 p.m. |
| 401909279 | Detroit at Brooklyn | Oct 30, 4:30 p.m. |
| 401909280 | New York at Philadelphia | Oct 30, 4:30 p.m. |
| 401909281 | Orlando at Toronto | Oct 30, 4:30 p.m. |
| 401909282 | Indiana at Miami | Oct 30, 5:00 p.m. |
| 401909283 | Houston at Dallas | Oct 30, 5:00 p.m. |
| 401909284 | LA Clippers at Minnesota | Oct 30, 5:00 p.m. |
| 401909285 | LA Lakers at Golden State | Oct 30, 7:00 p.m. |
| 401909286 | Denver at Phoenix | Oct 30, 7:00 p.m. |

## Source access and meaning

| Source/method | Exercised status | Admission boundary |
|---|---|---|
| ESPN public NBA scoreboard | Exact HTTP bytes, receipt and 10 event/team/start identities captured | Must remain scheduled, same date, same orientation and pre-cutoff |
| D&T public `/games?date=2026-10-30&days=1` | HTTP 200; `has_access=0`; upcoming projected scores null | `SUBSCRIPTION_REQUIRED` and `PROJECTION_UNAVAILABLE`; older completed-game projections are never substituted |
| D&T documented v2 `/api/v2/game-predictions` | Adapter and synthetic tests implemented; authenticated live request **not exercised** | No configured `DUNKS_AND_THREES_API_KEY`; no account purchase, new credential access or private endpoint discovery |
| Databallr public `/teams` HTTP | HTTP 200 application shell | No factor values extracted from the shell |
| Databallr rendered public DOM | 30 teams, six factors and displayed ranks captured in the browser at 18:52:47 UTC | Exact DOM export retained; import clock is distinct from browser observation and provider time; no independently authenticated provider as-of instant |

D&T's public [v2 documentation](https://dunksandthrees.com/api/v2/documentation)
specifies Authorization-header credentials, a flat-object JSON response,
`p_home_mov`, predicted scores, team IDs, game status and `update_dt`. The
documented game start is Eastern time. It does **not** identify the timezone of
the naive `update_dt` values observed here. The adapter only accepts an explicit
timezone-aware update instant; it does not guess that naive updates are UTC or
Eastern. HTTP Date and Last-Modified are receipt metadata, not provider as-of.

The captured [methodology](https://dunksandthrees.com/about/epm) identifies
2026–27 as the current generation's first live season. The normalization stores
that documented generation separately from the unavailable exact build ID.
Historical live generations and reconstructed backtests remain separate.
The API adapter uses the explicit `p_home_mov`, with a score-difference
consistency check; it never substitutes win probability for a point margin.
The public-page path derives a margin only when both projected scores are
accessible. No authenticated subscription export schema was invented.

The [Databallr table](https://databallr.com/teams) was observed on NBA, 2026–27,
All teams, Full Season, Overall, Per 100, with both 3P-luck sliders at zero. The
page describes box-score-derived six factors and positive-good signs. The parser
checks those semantics, controls, all 30 identities and exact headers, discards
only the separate displayed ranks, and rejects missing/nonfinite factors.
`source_model_version` describes the factor definition; provider build and
provider as-of remain null. The captured values are available for inspection,
but do not pass the frozen experiment's timestamp requirements. No zero fill,
assumed source time or relaxed retrieval-bound policy was introduced.

## Receipt and normalization contract

`research/nba_pregame_capture.py` reuses the repository's atomic fsync/no-clobber
writer and safe-relative-path primitives from `scripts/nhl_atomic_capture.py`.
The broad `capture_operational_inputs.py` / `recovery_capture.py` infrastructure
was inspected; its JSON-only parser does not parse these provider pages. The
new collector uses bounded public URLs and the documented API, with no redirects,
cookie harvesting, session scraping, secret query strings or hidden API probing.

Each new run directory contains exact raw responses/imports, writer request and
completion times, selected nonsecret response headers, byte counts, hashes,
source/model generations, normalized event-level sources, a dataset, audit
report and manifest. Raw content is committed before its receipt. Reruns require
a new directory and cannot overwrite prior files. The original browser-clock
claim remains inside its raw export; the local import is not a new browser fetch.
Local hashes and clocks are not independent timestamp attestation or canonical
pregame registration.

The schedule supplies independent ESPN identities and UTC starts. Exact NBA
team IDs and a small explicit abbreviation bridge reconcile providers; unknown
teams, duplicate events, reversed orientations and start conflicts are rejected.
The capture deadline is individually start minus five minutes; the comparison
cutoff is the actual normalization observation, capped at that deadline.
Late or started events remain visible and excluded. The source's own status
must also be scheduled. No caller-supplied as-of clock is exposed by the CLI.

B0 is copied byte-for-byte. Its complete original forecast, original creation
and feature times, input/state/procedure/identity receipts and warnings remain
attached. It is the preserved earlier point-margin head, not the winner head,
and is not rerun or retrospectively retimed to the new comparison cutoff.
This acquisition work does not clear its prior input/qualification limitations.

For newly captured sources, the actual combination audit/fit path now reopens
receipt and source bytes and re-extracts values, event identity, generation and
timestamps. Rehashing edited normalized values does not bypass extraction replay.
Unknown provider clocks, shell-only responses, access failures, unavailable
values, generation changes and parser failures remain explicit. Original
explicit datasets retain their existing checks; no prior result is rewritten.

## Commands and integration

```bash
python scripts/capture_nba_combination_sources.py \
  --date 2026-10-30 --output /new/capture-directory \
  --baseline /path/to/original/point_parent_card.json \
  --databallr-dom /path/to/rendered-dom-export.json --dunks-api

python scripts/run_nba_forecast_combination.py audit \
  --dataset /new/capture-directory/dataset.json \
  --protocol data/research/nba_forecast_combination_v1/protocol.json \
  --stage C1 --output /new/audit-c1.json
```

The collector emits exit 2 for partial acquisition while retaining evidence.
Omitting `--databallr-dom` leaves a shell-only classification. Omitting
`--baseline` leaves B0 missing. `--dunks-api` reads only the dedicated configured
environment variable, sends it only to the documented endpoint, and saves no
request headers. A missing credential produces `CREDENTIAL_NOT_CONFIGURED`
without making an unauthenticated API call. An attempted API error is not
silently replaced with a different source vintage.

The rendered export schema is directly tested against the captured page:
`url`, `title`, `page_text`, `table_rows` (each th/td innerText), `controls`
(button text/outerHTML for NBA, active season, All, Full Season, Overall,
Per 100 and Totals), and `sliders` (both visible range-input values after opening
3P Luck). Browser start/end observations are retained verbatim. Only observed
DOM is read. The exporter is an in-session browser step, **not an unattended
Databallr service**. Future changes in UI semantics fail closed.

The new CI workflow runs synthetic contract tests on the branch/PR. It has no
collection cron, no live credentials and no publication step. No scheduled
collector was deployed, and no canonical archival/writer registration was
performed. This is usable acquisition tooling plus a real, partial source run.

## Verification and readiness

71 focused tests pass: 29 new capture tests, 30 existing combination tests and
12 existing atomic-capture tests. Coverage includes genuine response shapes in
synthetic fixtures, source timing, per-event deadline/status, version and identity
mismatches, null/nonfinite values, duplicate events, raw/receipt tampering,
rehashed extraction edits, missing credentials, secret-header filtering, strict
factor semantics, B0 preservation and immutable reruns. These are engineering
tests, not independent sports observations. The authenticated API success path
has synthetic coverage only. The genuine run has 10 paired B0/Databallr
observations and zero complete, eligible B0/B1/C2 populations.

Session-start full-checkout health: RED, six failures and six warnings. Existing
lineage/equivalence, pitcher-archive, recovery, historical-release and standing
health issues remain. No global-health certification follows from these tests.

Chronological challenger evaluation is **not ready**: it still needs accessible
D&T pregame projections with verified timestamp semantics; a Databallr source
with authenticated pre-cutoff provenance and provider as-of evidence; then 100
distinct eligible completed fitting events in the permitted version stratum.
After that, produce genuinely later same-event B0/B1/C1/C2 forecasts and OOS
errors under the frozen protocol. No coefficients were fitted here, no
uncertainty model was borrowed and no predictive improvement is claimed.

Execution PARTIAL; predictive validation NOT_ASSESSED; publication INELIGIBLE;
wagering OFF. The collection and normalization components are implemented and
exercised within the source limitations above.
