# Diagnostic winner identity grading

The October 22 readiness evidence bundle's untracked `grade_oct21.py` compared a
forecast pick label directly with the provider's display name. This marked
`New Mexico State` as incorrect against `New Mexico State Aggies` despite the
30–24 final. The source event is ESPN CFB 401871070, team IDs 166 and 2534.

Use the tracked replacement for future descriptive research boards:

    python scripts/grade_research_board.py --board research-board.json --raw-dir retained-scoreboards --output new-assessment.json

The raw directory contains the applicable `cfb_prev.json`, `nba_prev.json`,
`nhl_prev.json`, `wnba_prev.json`, or `mls_prev.json` ESPN scoreboards. Missing
leagues and unresolved identities remain explicit blocked rows, not losses.
NFL integrated/canonical grading uses its existing distinct entry points.

To correct winner identity in an existing descriptive assessment without the
original forecast board (not a full forecast replay):

    python scripts/diagnostic_winner_grading.py --assessment original.json --scoreboard CFB=cfb_prev.json --scoreboard NBA=nba_prev.json --scoreboard NHL=nhl_prev.json --scoreboard MLS=mls_prev.json --scoreboard WNBA=wnba_prev.json --output new-correction.json

Every supplied source must match the original recorded SHA-256. This writes a
new exclusive-create successor, preserves forecast hashes and non-winner metrics,
and names its predecessor hash. It does not overwrite the original or write a
canonical ledger. An unresolved winner is null and excluded from the explicitly
reported winner denominator. Non-winner metrics are preserved, not revalidated.

Binding requires exact provider league metadata, exact event ID, two distinct
competitor IDs and home/away identities. Provider display name, short display
name, location and abbreviation are accepted as exact case/whitespace-normalized
aliases only inside that event. Supplied IDs must match and agree with labels.
Ambiguous labels, unknown teams, side reversals, duplicate events, non-finals and
unsupported ties fail closed. No substring matching, fuzzy matching, mascot
stripping or cross-league alias table is used. MLS three-way finals require
STATUS_FULL_TIME; extra-time/shootout finals are not substituted.

The fresh-board grader resolves probability orientation from the bound pick
side, never label equality. Binary and three-way Brier scores are summarized
separately. This does not create calibrated betting edges or grant action authority.

## Verification

- Offline regression suite: `python -m unittest discover -s tests -p test_diagnostic_winner_grading.py -v`.
- Retained October 22 assessment: all 15 winner identities resolved; only
  CFB:401871070 changes false to true; corrected record 10–5.
- Original assessment SHA-256:
  e0ba396add46b0edc78a1b2f4a5eb54a27663d4e7261d1ee17308f554431f0aa.
- Frozen forecast-board hash recorded by that assessment:
  00c76dd70e4c4ddc2faf6e3ed87bc1a82f5db3851b2cb57ad85a17701f89efa0.
  The board itself was absent from the retained bundle, so full forecast replay
  is not claimed. All existing per-game non-winner metrics remain unchanged.
- Local environment is a connector-restored partial checkout, not a complete
  repository. Its health run reports missing modules/data (262 FAIL / 3 WARN),
  so full repository health remains unverified; focused tests do not promote release.

Original immutable evidence and canonical ledger remain untouched. Draft PR
publication is not deployment: callers must use this replacement entry point,
and merge remains a separate approval.
