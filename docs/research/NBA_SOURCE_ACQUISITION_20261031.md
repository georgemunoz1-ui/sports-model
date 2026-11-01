# NBA external-source acquisition review

Reviewed October 31 Pacific / November 1, 2026 UTC against draft PR #98,
commit `e16a2c3b835354a4994d681c6d550b8a5d4e11b1`. This is an acquisition
decision and a small collector extension, not a fitted-model result.

**Recommendation:** seek written clarification from Dunks & Threes, then use
its official API for a limited prospective research pilot if the answers and
subscription permit it. It is the only evaluated route that can populate the
existing D&T B1 identity. Do not buy access merely to discover that timestamp,
target or retention requirements cannot be met. SportsDataIO is a plausible
commercial alternative, but would require a separate preregistered experiment.

## Access and licensing comparison

Prices and terms below are public documentation observations, not an account
entitlement check or a provider's approval of this specific project.

| Route | Available product and access | Permitted-use boundary | Decision |
|---|---|---|---|
| D&T Basic / Premium | Advertised annual prices $24.95 / $49.95. Website access is distinct from API entitlement. The rendered text lists features without reliably preserving tier checkmarks; this review does not infer that Basic includes projected scores or downloads. | Premium downloads are for personal, internal, noncommercial analysis; redistribution and competing products require permission. | Do not automate a subscriber webpage as a substitute for API authorization. |
| D&T Premium + API | Advertised $250/year; documented API key route. Confirm that the purchased entitlement includes game predictions. | API permits personal/internal use subject to restrictions. Bulk retention beyond reasonable use, external raw or derived distribution, and predictive models used for commercial decisions—including betting—need the relevant written permission/agreement. | Preferred conditional route for this protocol. Keep restricted data out of public repositories and reports. |
| SportsDataIO BAKER | Commercial NBA score/statistic predictions through its JSON Query API; price quoted for the use case. | Commercial agreements can cover model inputs, derived analytics, storage and betting-related products. Post-termination retention and attribution are contractual. | Best alternative to request a sample and scoped quote from; not D&T B1. |
| SportsDataIO Discovery Lab / trial | Discovery Lab is next-day delayed; free-trial/development data are scrambled. | Personal-use and commercial products have different terms. | Neither route supplies the authentic pregame observations needed here. Synthetic integration work is a different purpose. |
| Massey public NBA predictions | Public predicted scores, win probability and favorite-oriented median MOV; nearby market columns are separately labeled. | No suitable automated-acquisition, archival or model-use grant was established in this review. Public visibility is insufficient. | Obtain permission and a documented export contract before designing a separate challenger. |
| Sportradar Basketball Probabilities | Licensed probability-feed add-on; pre-match winner probabilities. | The documented product is media-only and expressly prohibited for betting clients. | Wrong target and unsuitable documented license for this intended workflow; do not infer broader rights from a trial. |

Sources: [D&T subscriptions](https://dunksandthrees.com/subscribe),
[D&T terms](https://dunksandthrees.com/terms),
[SportsDataIO NBA coverage](https://sportsdata.io/developers/coverages/nba),
[SportsDataIO licensing](https://sportsdata.io/help/data-rights-and-licensing-questions),
[SportsDataIO product tiers](https://sportsdata.io/developers),
[Massey NBA column definitions](https://masseyratings.com/nba/games),
[Sportradar probabilities license](https://developer.sportradar.com/basketball/reference/global-basketball-probabilities-feeds).
D&T subscriptions renew annually and are nonrefundable; an API subscription
does not grant every downstream use. These terms require an owner decision on
the intended use, not an automatic legal conclusion from the collector.

## Timing, target and version comparison

| Source | Pregame timing evidence | Version and margin definition | Integration requirement |
|---|---|---|---|
| D&T v2 | `update_dt` is the last prediction update; its example is naive. `game_dttm` alone is documented as Eastern. No original-vintage query or timeliness guarantee was established. | `p_home_mov` is predicted home margin; season-neutral margin is a separate field. OT inclusion and mean/median interpretation need confirmation. API v2 is not an exact forecast-build identifier. | Existing adapter, explicit timezone-aware provider instant, scheduled status, exact IDs and score consistency; no guessed timezone or probability-to-margin conversion. |
| SportsDataIO BAKER | Documentation describes hourly game-day simulations through game start, refreshed for injuries/lineups. Cadence is not proof that a given response existed before cutoff. | Obtain generation/build identifiers, provider publication timestamps, immutable revisions, and a full-game-OT expected-margin contract. Those were not established from the public material reviewed. | New provider adapter and experiment; confirm whether a team-score expectation difference is available and whether any betting-market inputs enter predictions. Exclude “Best Bets” and odds feeds. |
| Massey | Public display has no independently verified response-level publication time or immutable vintage/build guarantee in the reviewed material. | Favorite median MOV is not automatically a signed home expected margin. Predicted score differences and rounded displays cannot silently redefine the target. | Licensed export, orientation/OT/estimator contract, original snapshot clock and distinct model identity. |
| Sportradar | Prematch and live products must remain distinct; a pre-match label alone does not prove our pre-cutoff receipt. | Winner probability is not a point margin. Exact model revisions and a compatible margin feed were not verified. | A different permitted product and explicit identity would be necessary; no conversion or integration is implemented. |

Sources: [D&T v2 contract](https://dunksandthrees.com/api/v2/documentation)
and the provider pages linked above. The API specifies Authorization-header
keys, JSON responses and 90 requests/minute. None of those facts proves a
particular subscriber response will have qualifying clocks or values.

[D&T methodology](https://dunksandthrees.com/about/epm) identifies 2026–27 as
the current model's first live season, 2024–25 and 2025–26 as original then-live
predictions, and other seasons as current-model re-predictions. It describes
more frequent updates near tip-off. These are different evidence populations;
historical availability is not established by a present-day download.
`provider_build_id` remains null. A new documented generation must form a
separate fit stratum; do not silently relabel it as the existing generation.
Provider claims of accuracy are not validation of this combination procedure.

## Compatibility with the frozen experiment

The target remains `home_minus_away_full_game_ot_points` and the protocol hash
remains `08c8657de9b9b763dbf79450c17b4797c22edda5e282156e7f2e30377550bf38`.

| Arm | Can receive new eligible observations without changing its definition? |
|---|---|
| B0 | Yes, by importing the exact original point-parent forecast and its original lineage and clocks. Do not rerun or retime it to match a later B1. |
| B1 | Conditionally: original live D&T forecasts from the documented generation, compatible target, permitted acquisition, verified provider time and retained pre-cutoff bytes. A subscription alone is insufficient. |
| C1 | Conditionally, once complete eligible B0/B1 pairs exist. Fixed formula, penalties, minimum 100 distinct completed fitting events, one permitted version stratum and earlier-label requirements remain unchanged. |
| C2 | Not ready with the retained DOM evidence. It needs the same three Databallr factor differences with independently supported provider time and origin; C1 must also be evaluated on that same complete population. |

`source_eligible` in the existing software means the technical receipt and
chronology audit passed. It does not verify licensing, OT semantics or independent
timestamp attestation. The collector previously stamped the protocol target into
normalized records; that label is not provider confirmation of the definition.
New reports make this distinction explicit; this patch neither blesses existing
records nor silently changes their eligibility rules.

Provider confirmation that naive clocks have a particular timezone could support
a future, evidence-bound parser revision without changing the target. This patch
does not add an arbitrary timezone override. A provider's failure to supply
compatible semantics cannot be repaired by weakening the frozen protocol.

The independent-market restriction remains. Existing B0 generation and C1/C2
inputs are unchanged. Absence of market fields in an API response does not prove
the provider's model is market-independent; ask for that confirmation separately.
Alternative providers, market-derived margins, current reconstructed historical
predictions, zero-filled factors and converted win probabilities are not B1.

## Databallr: what would establish provenance

[Databallr terms](https://databallr.com/terms-of-service), updated October 2,
2026, provide personal noncommercial website access and restrict copying,
commercial use and reverse engineering. No adequate automated export/retention
permission was established. First obtain written permission for the proposed
factor acquisition, immutable retention and internal model research.

Then obtain a provider-documented export or authenticated response containing:

1. The same NBA season, Full Season/Overall/Per 100 controls, zero luck
   adjustments, exact team identities and positive-good six-factor definition.
2. A provider computation/publication instant with timezone, data-through boundary,
   and explanation of when that exact snapshot became available to subscribers.
3. A snapshot/revision identifier binding those clocks to the exact factor bytes,
   including correction and definition-change semantics.
4. A verifiable acquisition origin and pre-cutoff receipt, retained immutably
   with independent archival timing appropriate to prospective registration.

Field names above are requirements, not a claim that such an endpoint exists.
A signed provider export tied to exact bytes could also be assessed. HTTP Date,
ETag, cache age, browser observation time, local import time, and a screenshot
of a date are insufficient substitutes for documented provider-as-of provenance.
Do not retrospectively attach an unrelated fresh timestamp to the old DOM.
The actual replay validator rejects its missing provider time and unverified
browser-import origin, so a future documented adapter needs a separately tested
extraction-replay path. C2 feature definitions need not change if the export
proves the same inputs; a different factor definition requires a successor.

## Implemented integration changes

| Exact integration point | Change |
|---|---|
| `research/nba_pregame_capture.py:http_transport` | Explicit `Accept: application/json` on the documented predictions API, keeping key scope and no-redirect behavior. |
| `capture_http` | Retain `Retry-After` on rate-limit responses; still one attempt, no automatic retry or fallback. |
| `run_capture` | Optional `acquisition_profile="dunks-api"` requests only ESPN schedule, D&T methodology and credentialed D&T API. No public projection-page or Databallr request. Incompatible DOM imports fail before writes/requests. Legacy default stays available. |
| `normalize` | Distinguish a source not requested from an HTTP shell. No numerical, timestamp or eligibility change. |
| Report and CLI | Show acquisition profile, technical eligibility scope and `source_qualification=NOT_ASSESSED`. No credential purchase, permission inference, fit or promotion. |
| `tests/test_nba_pregame_capture.py` | Nine added regression tests, including multiple denial/timing subcases, request allowlisting, key isolation and unchanged B0/B1 results. |

After rights, entitlement and source semantics are resolved, the supported
command is:

```bash
python scripts/capture_nba_combination_sources.py \
  --date YYYY-MM-DD --output /new/private/capture-directory \
  --baseline /path/to/original/point_parent_card.json \
  --acquisition-profile dunks-api
```

Configure `DUNKS_AND_THREES_API_KEY` through the execution environment's secret
facility, never in source control or chat. The profile implies API acquisition;
missing credentials produce no API request. Schedule and methodology requests
may still run. Partial collection retains evidence and exits 2, including when
C1 passes but C2 is unavailable. The API profile is not a licensing gate.

For prospective enrollment, predeclare one capture opportunity/selection rule
per event and preserve every refresh in a new directory. Complete capture before
the existing tip-off-minus-five-minute deadline; preserve older B0 separately.
Do not select among revisions after seeing results, count refreshes as new events,
or feed duplicate event identities into a fit. Independent archive receipts and
canonical registration must be established separately. No scheduler is deployed.

## Exercise and remaining decisions

80 focused tests passed (the original 71 plus nine new tests). The existing CI
workflow runs the expanded file. Authenticated success is tested with synthetic
fixtures only. The full health check remains RED: four existing failures and six
warnings, including archive/recovery/historical-release/standing-health debt.

Read-only replay verified **98 retained files**, all raw receipt bindings and
the original B0 records in both October 30 runs. Their union is **10 distinct
events**, not 20. Each still has zero accessible D&T margin values, 10 Databallr
event pairs and **zero C1/C2 eligible observations**. Nothing in the archive
changed. The final run is `nba-pregame-8c057dfba8d749e2b1c59a74fac856a5`.
See [replay results](nba_source_acquisition_20261031/retained-replay.json),
[replay command](nba_source_acquisition_20261031/replay_retained.py),
[test output](nba_source_acquisition_20261031/focused-tests.log), and
[preservation check](nba_source_acquisition_20261031/checkout-and-preservation.json).
All 1,704 protected tracked data/card/model/state/authority/experiment files are
unchanged against PR #98. No genuine authenticated acquisition was attempted;
the dedicated credential is absent. No fit, new prediction or promotion occurred.

Owner involvement is needed for a subscription purchase and secret configuration,
and to specify whether the intended use is strictly internal research or a future
commercial/betting decision system. Before purchasing, request provider answers
covering the exact use/retention/distribution scope; endpoint entitlement;
publication-clock timezone; OT and estimator semantics; original revisions and
generation-change identifiers; and market inputs. These are a proposed inquiry
scope, not a message sent on the owner's behalf. For Databallr, request the rights
and provenance contract above. No account was created, purchase made, provider
contacted or credential configured.

Software implementation: **completed and exercised**. Current-source qualification:
**blocked by named provider/owner dependencies**. Predictive evaluation:
**not ready**; it requires genuine earlier fitting observations and genuinely
later chronological out-of-sample comparisons. Wagering authority remains **OFF**.
