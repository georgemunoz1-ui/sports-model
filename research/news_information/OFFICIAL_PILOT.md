# Official information pilot — capture and state, no predictive adjustment

Run `python -m research.news_information.official_pilot --date YYYY-MM-DD --output pilot-output`
in the dedicated network-enabled research worker. No production runner imports this module.
The GitHub workflow captures the current UTC provider date on changes to the pilot, not on a timer.
It has read-only repository permission, no checkout credentials and a 15-minute timeout.

The MLB parser uses StatsAPI game/team/person IDs and preserves all schedule games, including
missing probable pitchers. Active rosters populate names and observed membership. Membership starts
at retrieval, not a fabricated season-start date. A probable is never promoted to confirmed.
NFL official injury HTML is archived but does not count as parsed injury/roster/game coverage.
Official IDs are provider identifiers, not proof of >=99.5% identity accuracy against a labeled corpus.
No runtime model is necessary for this structured-source pass.

Source response bytes, request/retrieval times, response metadata and SHA-256 receipts are saved.
Capture failures are retained; unknown schedule size stays null rather than becoming zero coverage.
Cutoff is taken after capture; already-started games remain visible and are labeled nonpregame.
The provider official date is explicit; this is not yet the America/Los_Angeles canonical slate.
NFL report currency and event binding still need provider-specific validation before state use.
Archives can contain postgame fields or navigation/market text: only allowlisted structured fields
enter derived state. Raw documents are not direct predictive features.

The deterministic reducer keeps independently conflicting claims rather than picking the latest
timestamp blindly. A same-source explicit supersession chain checks previous state, subject/event/
dimension, retrieval chronology and effective chronology. Post-cutoff claims cannot change a past
snapshot. The pilot emits first-observed probable claims, with effective-time basis disclosed;
cross-capture automatic supersession is not inferred yet.

RawArchive now stores observation metadata under observations/<record hash>.json. Legacy
source_metadata.json files remain untouched. Consumers must use the returned metadata_path.

Outputs: content-addressed report, registry, claims, reduced snapshot and full slate; raw response
hashes are rechecked. Actions archives expire after 30 days: this is remote research retention,
NOT protected canonical pregame durability. Copy audited receipts/evidence into durable project
storage before expiry. No research quality target passes merely because a parser test passed.

Remaining: NFL structured/HTML parsing and identity binding; MLB lineups, bullpen, roof/weather;
independently labeled corpus; real compact-stack model smoke tests; data-derived versioned A/B/C
predictive transforms and prospective equal-population grading. These remain unimplemented here.
