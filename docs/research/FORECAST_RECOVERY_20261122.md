# Native forecast recovery — November 22, 2026

## Executed result

Fresh research inference produced 60 November 22 winner forecasts: 37 CBB, 11
NFL, seven NBA and five NHL. Two additional CFB previews cover November 24, the
next eligible CFB slate. Each selected forecast has 100,000 retained draws. CBB
retains paired score draws; the other winner simulations are Bernoulli
diagnostics. Eleven NFL selected-QB margin children additionally retain 100,000
margin draws per event.

All execution preceded the captured scheduled starts. Existing November 21
forecasts were preserved. Canonical registrations created: zero. Release remains
RED / HOLD, qualification NO_PICK, action OFF, official units zero.

The November 22 census has 68 fixtures. Four CBB games are outside the verified
D1 pair, West Florida has four prior verified games against the fixed minimum
of five, and three MLS playoff games are outside the native regular-season
population. MLB and WNBA have independently captured empty schedules. These
are explicit eligibility outcomes, not missing-package or quote-only success.

## Code changes

1. `models/nfl/contextual/starter_adjudication.py` accepts the ESPN `LAR` /
   nflverse `LA` equivalence only when the event's explicit reviewed binding
   names provider team ID `14` and `Los Angeles Rams`. It preserves the source,
   score, date, player and first-QB-play checks and the separate WSH/WAS review.
2. `scripts/refresh_cfb_fixed_fit.py` builds a fresh source-bound package while
   preserving the selected retained fitted heads, parameters and training
   cutoff. It verifies parent identity/code pins, complete consumed-file
   manifest coverage, source freshness, historical feature reconstruction,
   current feature reconstruction, duplicate IDs and prior-week state bounds.
   Output directories are exclusive. Failures write an explicit receipt.
3. `scripts/run_research_stage.py` records the exact argv, working directory,
   actual execution clocks, exit status, stdout/stderr hashes and output hashes.
   Expected outputs must be newly created. Timeout handling terminates the
   command's process group before freezing log hashes. The wrapper grants no
   execution or wagering authority and creates no forecast registrations.

The CBB source uses the existing research branch at
`aa9edae9c27d5309cc659b66513764fb01dd766b`; it is not silently substituted into
the consolidated main tree. A separately audited source-bound market adapter
handles current ESPN provider name `Draft Kings` with ID `100` and an explicit
DraftKings domain. Its diagnostic comparison leaves post-cutoff market admission
and schedule reconciliation holds intact.

## Reuse the CFB interface

Acquire current source bytes and receipts first. Supply the retained compatible
selected package as `--parent-package`; an empty or incompatible model package
is not a substitute. Use a new output root and an actual future slate date.

```bash
python scripts/refresh_cfb_fixed_fit.py \
  --repository /absolute/path/to/sports-model \
  --source /absolute/path/to/fresh-cfb-capture \
  --parent-package /absolute/path/to/retained-cfb-package.json \
  --date YYYY-MM-DD \
  --output /absolute/path/to/new-packages
```

The native `scripts/generate_card_force.py` then consumes the new package via
`SPORTS_RESEARCH_PACKAGE_DIR`, with an actual current cutoff, the requested slate,
100,000 simulations and `--identity-semantics market_blind_numeric.v2`. The source
receipt clocks must precede the cutoff; the native runner retains its own start,
freshness, scope and model-identity checks. The refresh itself does not run
inference and does not create another forecast edition.

To retain stage evidence around an existing approved native command:

```bash
python scripts/run_research_stage.py \
  --stage /absolute/path/to/new-stage \
  --cwd /absolute/path/to/sports-model \
  --expect-file /absolute/path/to/new-output.json \
  -- python scripts/native-command.py --native-arguments
```

The example's native command is a placeholder for the actual league command;
the wrapper does not choose a model, acquire inputs or grant authority. Secrets
must not be passed in argv. A retry uses a new stage/output directory.

## Verification

- The focused starter-adjudication and stage-execution suite passes 21 tests.
- An independent review passed the Rams binding and five additional integration
  cases, including an incorrect passing-table team identity.
- The real fixed-fit CFB refresh reconstructs all 36,901 pinned historical rows,
  assimilates 803 current finals, and produces the same two target feature rows,
  fitted heads, parameters and state as the first successful recovery.
- The retained CFB fitted-head digest is
  `70abd5e224dccd672d7a63ac8ee2c972c3ccd8ecd60c9c3739a943d3f7a5c03c`.
- Independent adversarial review reproduced and then verified corrections for
  empty/incomplete manifests, timeout descendants changing receipt-bound logs,
  and pre-existing outputs being mistaken for newly generated output.
- Native NBA/NHL analytical heads, consumed state and selected draw bytes replay
  exactly. Native CBB forecasts and all 3.7 million paired draws replay; 105
  priced product pairs recompute from frozen laws. NFL winner draws and child
  parent bindings, probability sums and pre-start execution windows verify.

These are execution and reproducibility checks. They do not establish a new
predictive edge or qualification pass.

## Preserved model and product limits

NBA/NHL native builders performed fresh deployment fits under their existing
fixed-hyperparameter procedures. CFB and NFL preserved fitted parameters. None
of these new packages replaced earlier frozen artifacts or promoted a default.

NBA/NHL still use the existing previous-UTC-day embargo and consumed-state rest
definition: newer observed completed games remain excluded on 19 of 24 current
team sides. Availability, minutes and goalies are not consumed. Their margin and
total point heads do not supply compatible exact-line probability distributions.

NFL state advances through completed Weeks 1–10, 150 games, leaving the partial
current week excluded. Expected starting QBs are source-bound expectations, not
final-inactive confirmations. Tampa Bay–Detroit is conditional on Baker Mayfield
playing. NFL winner probabilities are conditional on no tie; the Student-t
margin child is separate. Its spread ladder uses hypothetical handicaps, not
current market quotes. Neither selected football path supplies total probabilities.

## Integration status

The recovered packages and native runs are completed and exercised. The code in
this amendment is a reviewed recovery interface, not a deployed scheduled
acquisition service. The existing diagnostic workflow still requires an explicit
current package artifact. Future slates require actual reacquisition, compatible
package preparation and pre-start execution. MLS playoff support remains a
separate population/model dependency. No automatic merge or promotion.

## November 22 amendment — model version and immutable state

The owner-requested [model version and state contract](MODEL_VERSION_STATE_CONTRACT.md)
records the rule 3 identity requirements and the exact replacement text for
rule 5. A routine refresh retains the procedure version only when the recorded
parameters, residual bank, feature definitions, history/cutoff rules and
settlement logic match the recorded version. Actual state advances receive immutable
state hashes separately from model configuration, fitted parameters and event
input snapshots. A refresh provides no promotion or new validation credit.

The contract requires registry resolution and verification of retained state at
freeze time, the model version and short state prefix in HTML, and full digests
in JSON receipts. Its integration map and nine acceptance cases are planned.
This addition is documentation only: it does not claim that the shared, NFL,
CBB or external full-card paths already implement the new contract. Previously
executed recovery and its original frozen artifacts remain as recorded above.
