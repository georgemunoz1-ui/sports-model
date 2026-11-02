# Authentic CFB personnel sources: access, normalization, and remaining eligibility

Inspected November 1, 2026 Pacific / November 2 UTC. This change is stacked on
PR #100 at `86f30e08fcdedeea022c28a621d3dea48fd7a6c1`. It does not edit PR #99/#100's
personnel transforms, freshness rules, trust roots, coefficients, original
forecasts, refresh records, model defaults, or authorization documents.

## Actual result

Official SEC, ACC, and Big 12 report pages embed the HD Intelligence public report
application. The public client uses a read-only POST query at
`https://app.hdintelligence.com/api/get-publish-public`, with `sport=Football` and
the conference identifiers `SEC`, `ACC`, and `B12`. The SEC archive uses the
separate `/api/get-archive-public` read query. These paths were inspected in the
public embed's loaded client assets; no authenticated/internal endpoint was
called, no access denial was bypassed, and the query does not submit a report.

Initial source inspection returned HTTP 200 responses. The retained payloads were
subsequently inspected by the new adapter:

| Source | Current reports | Literal QB status rows | Future reports at inspection | Admitted personnel-v2 observations |
|---|---:|---:|---:|---:|
| SEC | 5 | 55 | 0 | 0 |
| ACC | 8 | 89 | 0 | 0 |
| Big 12 | 7 | 69 | 0 | 0 |
| SEC archive | 644 historical player rows, not current reports | Not classified by position in archive | Not established | 0 |

All 20 current reports concern October 30–31 games. The report feed contains
literal QB availability labels and provider-stated publication dates/times.
It does not identify the expected starter, supply prior pass-attempt count
ratios, or supply offense/defense returning-snap numerators and denominators.
Multiple quarterbacks can be listed available; that is not a starter selection.

The original complete retrieval receipts were not recorded for the exploratory
downloads. Their later imports therefore carry `retrieved_at_utc: null`, an
actual import timestamp, and `IMPORTED_RETAINED_BYTES`. File modification times,
HTTP Date, page creation dates, and scheduled reporting deadlines are not used
as original retrieval or observation evidence. This limitation prevents a
point-in-time claim even if another source later provides the missing features.

No actual source packet was submitted to the numerical challenger. No fitting,
new forecast, registration, refresh-chain write, grading, or qualification
occurred. The raw payloads include images and are not committed to this public
repository; execution metadata retains their actual SHA-256 values. Local
retention is not an independently verified durable archive.

## Implemented path and exercised boundary

`research/efficiency/cfb_personnel_sources.py` implements a separate ingestion
boundary. It preserves source identifiers, exact response hashes, literal QB
statuses, source JSON pointers, and report publication fields. It never converts
availability labels to participation probabilities, invents canonical IDs, or
converts returning production into snap counts. Its output deliberately has
`personnel_v2_evidence: null` and zero admissible observations.

Publication fields (`publishDate`, `postedTime`, `conferenceTimeZone`) are
interpreted using date-aware IANA timezones. Ambiguous/nonexistent daylight
saving times, missing timestamps, future publication claims, late reports,
duplicate QB rows, modified source bytes, conflicting receipt identities, and
malformed JSON are refused or quarantined. The provider's original observation
timestamp remains null. A provider-stated publication time is not an independent
historical attestation.

The archive exposes report-stage columns such as Initial and Game Day, team,
opponent, player, jersey and a week date. It does not provide original report
publication/observation timestamps or stable canonical event/player IDs.
Current downloads of that archive cannot pass PR #100's historical chronology
rules. No timestamp is reconstructed from the standard reporting calendar.

The CLI supports two explicit operations:

```bash
# Diagnostic inspection of existing bytes; no new retrieval claim.
python scripts/capture_cfb_personnel_sources.py \
  --conference SEC --kind current --raw /private/path/original-response.json \
  --output /private/path/new-inspection-directory

# Network acquisition remains blocked with the shipped empty permissions registry.
python scripts/capture_cfb_personnel_sources.py \
  --conference SEC --kind current --output /private/path/new-capture-directory
```

The second command was exercised: it exits 2 with
`CFB_SOURCE_USE_NOT_CLEARED:SEC:automated_capture`, records zero network requests
in its refusal result, and creates no output directory. After a reviewed rights
grant exists, the implemented transport makes one bounded public read query,
rejects redirects, preserves bytes and writer-owned times, and records failures.
That licensed live acquisition route has **not** been exercised. This change
does not deploy a polling service.

The repository-pinned `cfb_personnel_source_permissions.json` ships with no
grants. Capture, model use and public redistribution are separate scopes. A
future grant needs a retained hash-bound rights document, reviewed exact origin,
validity window and review record. This check validates the identity of a
reviewed grant; software cannot establish the legal sufficiency of a license.
The separate PR #100 historical clock-authority file remains unchanged and empty.

## Primary-source inventory

| Source | Useful data and timing | Historical availability | Access and permitted-use finding |
|---|---|---|---|
| [SEC official reports](https://www.secsports.com/fbreports), [archive](https://www.secsports.com/fbreports-archive), [policy](https://www.secsports.com/reports) | Official availability statuses; public provider payload includes report publication fields. No original observation time, expected-starter declaration or snap ratios in exercised bytes. | Public archive exercised: 644 rows, without original timing proof. | Public visibility verified. The site links [Disney terms](https://disneytermsofuse.com/english/), which restrict automated extraction and AI/model-related use. Do not infer a license for the embedded third-party feed from public access. Further automated capture/model use remains disabled pending source-specific rights review. |
| [ACC reporting policy](https://admin.theacc.com/sports/2025/8/28/availability-reporting.aspx), [current report](https://theacc.com/sports/2025/8/28/availability-reporting-football.aspx) | Availability reports start three nights before conference football games and include a report two hours before kickoff. Provider payload exposes date/time/timezone. | Official archive linked, but not separately exercised in this task. | Public embed verified; a separate HDI automated-use/model-use grant was not established. No rights-clearance claim. |
| [Big 12 reporting policy](https://big12sports.com/sports/2025/8/21/availability-reporting.aspx), [current report](https://big12sports.com/sports/2025/8/14/FBreporting.aspx) | Daily reports begin three days before the game; policy states 9 p.m. CT updates and a final report 90 minutes before kickoff. Status definitions are provider policy labels, not a validated fitted participation model. | Previous-report link available; historical query not exercised for Big 12. | Public embed verified; automated/model-use rights remain unestablished. Correct source identifier is B12; exploratory use of “Big 12” returned 400 and was corrected from the official embed URL. |
| [Big Ten 2026 policy](https://bigten.org/news/2026/8/28/big-ten-announces-changes-to-football-availability-reporting-process.aspx) | Three pregame daily reports and a final two hours before kickoff, for conference games. | No historical payload exercised here. | Official policy accessible; no Big Ten acquisition adapter or feed permission claimed. |
| [CFBD API data availability](https://api.collegefootballdata.com/data-availability), [authentication](https://api.collegefootballdata.com/getting-started), [terms](https://collegefootballdata.com/terms) | Player usage and box-score statistics can support participation research. Returning production is documented as a forward-looking preseason dataset from 2014 onward; it is not offense/defense snap-count evidence. | Broad historical seasons available; documentation warns of corrections and incomplete fields. Current access does not prove original historical publication. | An API key is required; configured credential presence check was false. Terms permit private caching/model training and derived outputs, but prohibit bulk raw redistribution. No key was created, purchased, or requested; no authenticated request was made. |
| [Sportradar NCAAFB rosters](https://developer.sportradar.com/football/docs/ncaafb-ig-rosters), [Game Roster reference](https://developer.sportradar.com/football/reference/ncaafb-game-roster), [API basics](https://developer.sportradar.com/football/docs/ncaafb-ig-api-basics) | Stable game/player GUIDs, declared game roster, participation status and live in-game status. Documentation recommends game feeds near kickoff. Live/postgame “started” or “played” must not be used as earlier expected-QB evidence. | Season availability feed and contracted coverage must be checked; no account/feed exercised. | Account/API key and license required; configured credential presence check was false. Snap-count coverage and permission for this project remain unverified. |
| [PFF API reference](https://developer.pff.com/reference/), [access](https://developer.pff.com/), [terms](https://www.pff.com/terms) | Public reference documents player snap summaries; every data endpoint requires Pro. Actual college snap coverage and source-vintage fields were not inspected with authenticated data. | Not established for this project/account. | No configured credential. Current terms restrict personal/public/commercial/data/AI uses; consumer API access cannot be assumed to authorize this public repository and model workflow. No PFF data capture, purchase or integration was attempted. |

These are findings from the cited documents and exercised access, not a legal
opinion or an assertion that no other source exists. The automated-use gate is a
concrete source dependency rather than a substitute for the technical gates.

## Next future event and unresolved requirements

The earliest upcoming CFB matchup verified from both schools is **Ohio at Akron,
Tuesday November 3, 2026, 7 p.m. Eastern / 4 p.m. Pacific**. Ohio's
[October 31 preview](https://ohiobobcats.com/news/2026/10/31/ohio-football-begins-midweek-maction-at-akron)
and Akron's [October 26 announcement](https://gozips.com/news/2026/10/26/footballs-clash-with-ohio-to-be-televised-on-espn2)
agree on the matchup and time. Ohio's native game-center identity is
[9722](https://ohiobobcats.com/game-center/9722); it has not been crosswalked to a
canonical repository event ID. The SEC's earliest November 7 game is
[Texas at Missouri at noon Eastern](https://www.secsports.com/news/2026/10/sec-football-on-tv-nov-7).
Neither is declared eligible merely because it is scheduled in the future.

No complete admissible personnel-v2 packet exists in the exercised evidence for
these future events. A valid path still needs:

1. A source grant covering automated acquisition, private retention and model use.
2. Exact canonical event/team/player reconciliation, original observation time,
   publication/availability time, and real pre-cutoff retrieval receipts.
3. Source-confirmed expected quarterback designation, prior attempt counts,
   offensive/defensive returning-snap counts and declared populations, and the
   separate source-bound participation assumption required by PR #99.
4. Independently trustworthy chronology/source-authentication evidence. Empty
   clock trust roots are not provisioned by this source adapter.
5. Separately, an eligible frozen personnel-v2 parent fit with authentic
   historical feature/label and training provenance. Current source success
   cannot repair missing parent-model history or create an eligible fitted state.
6. Prospective same-event logging and chronological out-of-sample evaluation
   against the unchanged baseline before any challenger promotion.

Returning starters, returning production, player usage, dressed/played status
and actual offense/defense snap counts remain different quantities. A different
available feature would require a separately identified experiment and new
evaluation; it cannot silently substitute for the existing v2 definition.

## Verification

The new adapter tests and unchanged personnel-v2/freshness suites are recorded in
`acceptance-tests.txt`, `acceptance-tests.xml`, and `EXECUTION.json`. Fixtures are
explicitly TEST_ONLY synthetic engineering data, never real observations or
predictive events. The public execution report contains counts, source hashes,
actual import times, code identity and limitations; restricted source bodies
remain outside the public git tree. All previously tracked files are compared
to the exact PR #100 parent, with only an append to the progress journal allowed.

Execution is **completed diagnostic source inspection**. Licensed live capture
is **implemented but not exercised**, and blocked by unprovisioned source rights.
Personnel research admission and qualified predictive events remain **zero**.
Predictive validation is unassessed, publication is ineligible, and wagering
authority is OFF.
