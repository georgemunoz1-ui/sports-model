# NFL reporting-regime support gate (research only)

Base 3ef40f59f44179a077ae6f2ef6248cf1380fd7e7; no change to frozen parameters, features, model IDs, selected QB default or wagering authority. This draft integrates the support check in the shared NFL numerical runtime after existing source/chronology and weekly-state checks and before any arm prediction. The existing selected arm must pass its applicable check. Unsupported siblings emit explicit null prediction/refusal records; raw historical artifacts and offline numerical diagnostics remain unchanged. No implicit fallback or substitution. Enhanced pregame calls the same football path; live is separate and is not claimed covered by this gate. This is a new runtime code identity and may change future RNG identities even when analytic heads remain identical. Replay old artifacts at their own exact code revision.

## Certificate
- Fitted-model canonical JSON SHA-256: c1cdf49dbb1a98bbf2b3d4286042a316c132dc7d472f3138c3bbbb1e0cb1c3cd
- Packed-model Git blob: fa5f22c65ad23c278841b6f1260c9ad16f4402dd
- Original source archive SHA-256: e55d1f2bee4620c816e3ac28e96dedaa0ecb0568b1d59db3e42a069e83cb76f3 (see retained acquisition record at data/research/nfl_qb_margin_20261019/acquisition.json)
- Exact feature table SHA-256: 4e85683269768322d50d00966d432c37d4179d95bac76cd41fa5933d94ff4e5b
- Fitted sorted event-ID digest (newline delimited with terminal newline): 575684fd1565aeeb6e5aa1b1eb70db5d6acb51aea2b55241939d608e489efbb5
- Full feature population 2895 (2887 count zero, 8 count one); original complete-target fit population 2885 (2877 zero, 8 one, 0 two). Use the latter for the certificate.
- Independently recovered 42 manifest-bound archive members. Original history is reused, not attested PIT. Count zero means neither report flagged missing by the transform; it is not proof of exhaustive report coverage.

Policy: 0 passes support only; 1 is observed but not qualified; 2 unseen; invalid feature value and unknown fitted artifact using the indicator refuse. No new qualification of missing-aware or no-personnel challengers. New fitted artifacts require independently verified support evidence. The helper's seven local synthetic unit tests passed on the exact same helper bytes. Native runtime integration tests are added; full repository CI and real current-event replay have not been claimed at commit time.

Player-level source-readiness audit on the same archive: 58449 injury rows and 264774 snap rows; 52666 injury rows have parseable timezone-bearing modification stamps (not publication attestation); 37798 injury rows match a single PFR player ID and game in a same-week normalized name/team diagnostic join, 5 ambiguous and 20646 unmatched. This is not a verified GSIS/PFR crosswalk; no nonmatch is labeled inactive. No new feature fitting or player-level value estimates. Expected workload, true availability and replacement quality require distinct validated inputs.

Release controls remain unchanged. No historical record, model fit, selection threshold or canonical registry changed.

## November 27 successor integration addendum

The initial PR implementation above changed the frozen `runtime.py`. Its seven
helper and four native fixture tests passed, but protected-source preservation
and historical finding-evidence validation failed. This addendum supersedes the
initial integration route, not its recorded failure history.

The original runtime is restored exactly (SHA-256
`8951577d6edd2e2e37b370cafe9f90c205b9de8b6b59d9c1aba961f15760c15d`).
No historical evidence hash, frozen parameter, source pin, model default,
existing adapter or existing CLI is changed. The 671 source bindings in the
original acceptance receipt remain intact.

### Explicit successor path

- `models/nfl/contextual/runtime_reporting_support_v1.py` owns the new
  contextual-arm orchestration. It reuses the frozen feature and numerical
  helpers, but never calls the predecessor's all-arm `run`.
- `scripts/run_nfl_reporting_supported.py` is the explicit opt-in entry point.
  It resolves the existing selected-QB default, or honors an exact explicit
  model ID without fallback. Independent pregame research and retrospective
  replay are supported; enhanced/live modes are explicitly rejected.
- One owned input/feature snapshot binds the model, event, cutoff and features.
  Reporting admission precedes every contextual-arm prediction. The frozen
  feature constructor still computes an indicator-free recovered/base
  diagnostic; that is not an availability/combined-arm prediction.
- Unsupported selected arms refuse; unsupported sibling arms have null
  prediction/contribution records with a reason. Other events remain in the
  declared population and can complete independently.
- Fitted model IDs and coefficients stay unchanged. The successor/gate source
  hashes enter the observed prediction procedure and actual
  `market_blind_numeric.v2` RNG identity. A separate execution identity binds
  full provenance and admission. No predecessor forecast is fabricated.
- The complete run, including coverage, is staged before publication of the
  requested output directory. An interrupted coverage write retains an
  unpublished stage; retry uses the still-free final path without overwriting
  the retained stage. Explicit empty/padded identity arguments refuse before
  package access.

Retained-input example (research replay, not a November 27 forecast):

```bash
python scripts/run_nfl_reporting_supported.py \
  --date 2026-09-14 \
  --replay-cutoff-utc 2026-09-15T00:12:00Z \
  --simulations 100000 \
  --output /absolute/path/new-reporting-supported-replay
```

For new pregame execution, supply the real source-bound native package through
`NFL_CONTEXT_PACKAGE`, the actual schedule date and any required weekly-state
store/ID. Omit the replay flag. This command writes a local execution receipt;
it does not create canonical registration or grant publication/wagering
authority. Its existence does not migrate a daily-card dispatcher. Original
entry points remain frozen; this is not blanket coverage of all NFL callers.

### Verification scope

The focused suite has 29 tests: helper contracts, native contextual-arm refusal,
numeric equality, snapshot ownership, predecessor preservation, source/seed
identity, concurrent replay, actual CLI population/receipt checks, coverage-write
failure/retry and explicit-argument refusal. The retained final fixture has
100,000 winner draws, independently replayed exactly. See
`integration_receipt.json` for byte identities and broader local check results.
Hosted acceptance is determined from the exact current PR head, separately
from these local results. Neither establishes live readiness or improvement.

### Personnel finding and prerequisites

Every citation of the retained control comparison carries
`REUSED_RETROSPECTIVE_NOT_PIT_OR_CONFIRMATORY`. The tested personnel procedures
performed worse than independently fitted controls on the retained cohort;
unresolved chronology prevents a conclusion about a corrected, attested
personnel representation. Possible leakage does not strengthen the result.
The combined control removes the availability block while retaining QB inputs;
it did not establish superiority over the selected QB incumbent.

The general player-level redesign is blocked on historical availability,
accepted identities, complete active/inactive denominators and replacement
quality (acquisition plus estimation). Source capture can proceed under native
provider IDs before cross-provider identity integration. In particular, the
20,646 same-week injury/name-to-snap nonmatches above are not a certified
crosswalk failure rate, and no snap row does not imply inactive. Narrower
separately registered research may proceed only within its attested scope.
