# Standing research-output request — September 23, 2026

The user requested event-specific manual validation and consistent daily model
output without having to ask again. The daily ChatGPT task was updated in the
same session. This supersedes its audit-only/no-numerical-output instruction.
It does not promote models, amend historical releases, authorize bets, accept
overdue risks, or change any frozen parameter or old forecast label.

Each run must acquire fresh source bytes and build a successor package. Retain
the previous package. Check the full official event census and classify every
event. Actual writer time governs POST_START; do not borrow a morning cutoff.
Review inputs and execute independent eligible leagues even when another league
or the historical release register remains RED.

## Two distinct decisions

1. Supported limited-feature research: run the selected engine when its required
   inputs, identities, source freshness, hashes and chronology hold. Disclose
   unpublished/unconsumed lineups, availability and weather. Retain actual draws,
   seeds and manifests. Use PROVISIONAL_RESEARCH/DIAGNOSTIC labels, never official
   eligibility or canonical prospective registration without that writer.
2. Full final-event validation: retain starter/lineup confirmation timestamps,
   injury effective/retrieval times, bullpen availability, venue weather and the
   final cutoff. Missing evidence remains NOT ESTABLISHED, even when (1) runs.
   An earlier check cannot confirm later changes. The daily morning schedule does
   not create a second background agent check at every evening cutoff.

The current V13 contract uses D-1 team form, observed starter ERA/GS/K/BB and
frozen park/HFA. Lineup, injury, weather and bullpen captures are review context,
not fitted numerical adjustments. Unknown or conflicted starter identities are
excluded by the reviewed-output wrapper. The V13 winner estimator is Monte Carlo
only; the separately computed d_logistic_2f challenger is not its analytic twin.
V13 run means do not establish full-game totals/run-line settlement.

## Reusable commands

Run `scripts/review_mlb_current_readiness.py --date YYYY-MM-DD --output UNIQUE`
then `scripts/mlb_research_review.py collect --readiness UNIQUE --output REVIEW`.
Inspect every event in REVIEW/review.json and its linked source bytes. Write an
agent review decision binding that review hash, actual review time, explicit
event IDs and rationale; this is not a human confirmation. Then run:

```
python scripts/mlb_research_review.py run --readiness UNIQUE --review REVIEW \
  --review-sha256 EXACT_HASH --approval AGENT_REVIEW.json --output NEW_RESULTS
```

The wrapper rejects changed or unknown starters, started games, code/state drift,
stale packages, mismatched review hashes and event feeds older than 30 minutes.
It retains separate dispositions and zero action authority. It cannot manufacture
a completed final-event validation from incomplete sources.

Other leagues use their current source-bound builders and adapters. NFL retains
the selected provisional QB research default; combined remains experimental and
B2 needs its own complete Week3+ registration. CFB's unresolved assimilation gate
remains labeled. WNBA uses FF7's separate target heads and explicitly discloses
unconsumed player availability. NBA/MLS/NHL may use the explicitly named initial
research paths; automatic defaults still refuse and NHL preseason is outside
the regular-season arm. Do not silently replace any arm with a fallback.

Historical release/health triage stays separate and cannot grant official
clearance. Source capture, tests, simulations and predictive validation are four
different claims. Action OFF; dose 0.0.
