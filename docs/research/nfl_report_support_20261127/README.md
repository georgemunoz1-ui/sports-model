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
