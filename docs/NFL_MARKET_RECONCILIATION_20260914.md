# NFL integration and market reconciliation — September 14, 2026

This review uses the frozen PR #19 DEN@KC output, not a new forecast. The
new runtime selector was replayed only to verify implementation. All five
analytic outputs match the old artifact exactly; the old manifest still verifies.

## Capability corrections

The original restored 18-feature EPA arm and the PR #19 integrated arm are
separate fitted model identities. The latter applies newly fitted personnel,
practice, workload and travel proxies. Calling those integrated effects absent
would be incorrect; calling them recovered historical coefficients would also
be incorrect. A 100-column matrix is not 100 fully observed current facts.

The same feature family can be present in the matrix, rely on a proxy or missing
indicator, and have different coefficients in each target head. Output coverage
now records those distinctions. Final inactives and actual itinerary/workload
were unresolved in the frozen event package.

## Latest pasted board

Source: user-transcribed Covers/Novig display. Quote capture timestamp, executable
price semantics, fees and settlement contract are unverified. No live refresh
or new source retrieval is claimed. Its predicted-score column is a separate
third-party projection, not our output and not the winner quote.

| Quantity | Frozen integrated model | Pasted board |
|---|---:|---:|
| Denver-oriented center | +0.80579 | +0.85 from 21.88 minus 21.03 |
| Total center | 47.11972 | 42.91 from predicted scores |
| Listed total contract | — | 43.5 |
| Denver binary non-tie win probability | 54.52166% | displayed winner 45% |
| Kansas City binary non-tie probability | 45.47834% | displayed winner 56% |

The displayed winner pair sums to 101%. Proportional normalization produces
DEN 44.55446% / KC 55.44554%, assuming comparable mutually exclusive prices.
Thus the analytic DEN gap is +9.96720 percentage points, conditional on compatible
target/settlement semantics. It is not fee-adjusted EV. The word Novig is the
operator label and does not establish that these displayed percentages sum to 1.
The third-party score center favors Denver while the winner quotes favor KC.
There is no requirement that separate model projections and prices agree.

Frozen score simulation remains DEN 54.33% / KC 45.292% / tie 0.378%.
Conditioning that simulation on a non-tie yields DEN 54.53615%; do not subtract
a binary benchmark from the unconditional score probability without stating the
target mismatch. The simulated outcome weights were aligned to the logistic
probability by construction, so agreement is not independent validation.

## Additional historical uncertainty check

Paired Brier changes are arm minus refitted 18-feature base; negative is better.
These are post-hoc descriptive 10,000-replicate season-block bootstrap intervals
on the existing 1,865 non-tie OOF games (2019–2025), not a new pristine holdout or
promotion test. No multiple-comparison adjustment is applied. Only seven season
blocks are available; known historical identity/publication-time limitations remain.

| Arm | Brier change | 95% interval |
|---|---:|---:|
| qb | -0.006697 | [-0.009449, -0.003410] |
| availability | +0.006726 | [+0.004553, +0.008967] |
| travel | -0.000079 | [-0.001316, +0.001111] |
| combined | +0.001423 | [-0.002535, +0.005453] |

QB has the strongest reported signal; its 2025 season delta was adverse despite
aggregate improvement. Travel also has a positive aggregate point estimate,
but it is tiny and its interval crosses zero. The full combination does not
support an accuracy-upgrade claim. Availability was adverse in every evaluated
season; that motivates a separately designed investigation, not causal attribution
or automatic deletion from the combined model.

## Interface changes

Existing fitted arms can now be selected explicitly by model ID. Binary inference
and simulations follow that arm. Joint score simulations remain attached to the
combined arm's frozen residual bank and are unavailable for other arms until they
have their own recorded bank. Unsupported model IDs never fall back silently.
The supported mode is explicitly research_pregame. Proposed official, market-aware,
live and postgame inference modes have availability labels; this patch does not
claim to build their model families. Historical research commands remain separate.

Validation: 18 tests passed, two exact 100,000-draw combined replays matched,
all five analytic predictions unchanged, original forecast manifest unchanged.
No coefficients, forecast selection verdicts or old outputs were modified.
