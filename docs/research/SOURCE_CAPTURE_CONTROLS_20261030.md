# Source-capture controls — October 30, 2026

Implemented on an isolated successor branch from `6789e7d090b77c55287f4fe68426f790b0fe0950`. No selected model, fitted state, default, forecast or authority changes.

## Concrete behavior

`harness/market_capture.py` now rejects boolean/nonfinite lines and prices, invalid American prices (magnitude below 100), invalid/naive timestamps, source-update times later than retrieval, missing identities, and attempts to change the valuation-only information class. Consensus revalidates its input records. The two feed parsers retain original line types for validation and stamp retrieval after the response. The SportsGameOdds adapter no longer mislabels event `startsAt` as quote update time; that field is unknown in this adapter's retained schema.

`research/source_capture_contracts.py` binds each typed observation field to a literal JSON pointer in hash-verified raw bytes. It validates aware retrieval/provider/status times, exact event/team/selection identities and quote terms, finite values, and explicit unknown personnel/workload states. Receipt and field matching do not authenticate the provider, establish roster correctness, verify house settlement rules, or prove numerical model use. Source-specific semantic fixtures remain required. A rules identifier is a captured identifier, not a certification that the rule applies.

`python scripts/bind_source_observations.py --capture-root CAPTURE --manifest INPUT --output NEW_DIRECTORY` exercises that path without network access. The input has `cutoff_utc` and `observations`, each containing `kind`, `raw_path`, `receipt`, and `bindings`. The receipt includes `league`, `url`, `raw_sha256`, `retrieved_at_utc`, and optional `provider_observed_at_utc`/`requested_at_utc`. `bindings` maps canonical fields to RFC6901 JSON pointers. Output includes parser/input/output hashes and refuses an existing output directory.

`capture_operational_inputs.py --context-league nba --context-league cfb --context-league nhl` adds opt-in current-Pacific-day summaries and a `context_inventory.json`. It quarantines event mismatches, keeps missing injury information unknown, and reports expected minutes and goalie confirmation as unknown. Capture never applies a personnel adjustment. The existing forecast runner is unchanged.

## Executed evidence

- `python -m pytest tests/test_source_capture_contracts.py harness/test_market_layer.py tests/test_source_attestation.py -q`: **95 passed**.
- `market_capture.py`, `market_sportsgameodds.py`, and `market_theoddsapi.py` selftests: all pass.
- Offline binding against previously retained October 30 provider responses: **86 source-bound personnel rows**, comprising **67 NBA** and **19 NHL** rows. The source inventory spans **16 context events** (10 NBA, three CFB, three NHL); CFB had no injury rows to bind.
- Original responses were retrieved around **15:32 UTC / 08:32 Pacific**; the binding cutoff was 15:35 UTC. This is reuse of recorded captures, not new network acquisition or an original historical PIT attestation. The source-scope and input manifest preserve every recorded retrieval time and digest.
- Bound output SHA256: `967004eb3400bccde123255287a345dcd3d0ecb4a46d36ea8655e8c92add1213`.
- **Zero exact quote bindings**: retained native odds do not supply the required period and house-rule identity bindings. No terms were invented to pass validation.
- Full-checkout session-start health: **RED, 4 failures / 9 warnings**. Failures concern the production pitcher archive, recovery jobs, historical blocked release, and standing-health evidence. Health-generated audit files were restored; frozen records were not changed.

The 86 rows are source statuses, not 86 independent forecasting observations. Expected minutes remain null, personnel transforms remain unapplied, authenticity is `NOT_ASSESSED`, and numerical use is `NOT_USED`.

## Closure register

| Issue | Implemented evidence | Still required |
|---|---|---|
| Invalid quote values/timing accepted | Regression refusals and passing market/feed tests | Authentic fresh exact sportsbook quotes for the desired contracts |
| Detached personnel assertions | Raw-byte/hash/pointer binding exercised on retained captures | Roster reconciliation, complete official status coverage, source-specific semantic fixtures |
| Capture confused with applied adjustment | Explicit NOT_USED/NOT_APPLIED output and null workload | Evaluated workload/effect transform and runner consumption receipt |
| NBA/CFB/NHL summary acquisition omitted | Opt-in operational acquisition path plus selection/identity tests | Live acquisition acceptance in the configured network/runtime |
| Original provider time unavailable | Null retained; retrieval-bound policy explicit | Independently supplied provider-effective time or approved historical-as-of evidence |

Wagering authority OFF. Implementation and source binding do not upgrade prediction or selection eligibility.
