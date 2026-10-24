# Shared roster evidence and forecast boundaries

The roster pipeline covers NFL, CFB, NBA, WNBA, MLB, NHL and MLS. It captures
membership and reported injuries using stable, sport-scoped provider IDs. It
does **not** make a team-history model roster-aware or fit replacement effects.

## Run and verify

```sh
python scripts/prepare_rosters.py --output output/rosters-UNIQUE \
  --cfb-schedule PATH_TO_CURRENT_CFB_SCHEDULE.parquet
python scripts/generate_card_force.py --date YYYY-MM-DD --league nba \
  --initial-research-baselines --roster-bundle output/rosters-UNIQUE/bundle.json \
  --output-dir output/card-UNIQUE
python scripts/run_nfl_integrated.py --date YYYY-MM-DD \
  --roster-bundle output/rosters-UNIQUE/bundle.json --output output/nfl-UNIQUE
```

Use `--sport` repeatedly to acquire selected leagues. Without a CFB schedule the
scope is all teams returned by the provider, not an asserted FBS census. With a
schedule, every FBS ID and exact team name must match the provider directory;
the complete schedule and its hash remain in the bundle. Every request, failure
and duplicate membership remains in the ledger. Exit 2 means acquisition or
membership conflicts remain; independent valid teams can still be inspected.

`--resume` only completes a partial acquisition. It preserves receipt timestamps
and refuses to overwrite valid files. Use a **new directory** to refresh inputs.
Load `bundle.json` through `sports.rosters.load_bundle`, which rebuilds every
normalized player row from retained bytes and checks census and scope coverage.
Hashes prove integrity, not independent provider correctness.

All roster requests explicitly use `limit=1000`; responses at that limit are
rejected pending pagination. The default CFB endpoint silently capped the October
20 discovery at 100 players per team. Those first snapshots are superseded as
incomplete; the larger-limit capture is the acceptance input.

Use the actual forecast cutoff after acquisition. Census receipt, roster receipt
and provider timestamp must all precede the cutoff and be no older than six
hours. Event start, season and exact team identity are checked independently.
Current sources cannot reconstruct a past forecast cutoff. Numeric IDs from
different providers are never interchangeable; an explicit crosswalk must use
`home_roster_team_id` / `away_roster_team_id` and agree with the source team name.
No fuzzy player or team joins are performed.

The shared card and canonical NFL runner attach a hash-bound `roster_coverage`
report. Missing data is `ACQUIRE_REQUIRED`; invalid/stale/conflicting data is
`BLOCKED`; good membership data is `AVAILABLE_NOT_USED`. The existing NFL
selected-arm capability trace is preserved. MLB's starting-pitcher scope is
identified separately from lineup/bullpen effects.

Add `--require-roster-aware` when a product requires full personnel impacts.
It fails **before simulation** because no current parent has a registered full
roster transform. This gate cannot be bypassed with a caller-supplied `used=true`
label. Ordinary diagnostic forecasts keep their parent probabilities and expose
the missing capability. This change does not promote a model or change wagering.

For preserved cards, use `scripts/audit_roster_cards.py --bundle BUNDLE --card CARD
--output NEW_REPORT`. It reports both the original cutoff and current review
cutoff, rejects duplicate event/model rows, and does not regenerate forecasts or
retroactively attach newly acquired information to a frozen card.

## Numerical work still required

| Sport | Existing selected numerical personnel scope | Remaining fitted model work |
|---|---|---|
| NFL | QB arm uses QB history/change; other arms retain their own traces | Non-QB replacements, full depth/inactives/workload; do not promote combined effects |
| CFB | Team Elo/form only | QB, transfer/depth identity, positional snaps and replacement effects |
| NBA | Team scoring/rest history only | Current rotation minutes, opportunity sharing, offensive and defensive player impacts |
| WNBA | Frozen team box/form/rest transform | Same rotation/player effects; postseason eligibility remains separate |
| MLB | Starting pitchers and team offense | Batting order, bullpen availability and lineup effects; PR #58's failed holdout stays unpromoted |
| NHL | Team scoring/rest history only | Confirmed starting goalie, skater ice time and special-team/replacement effects |
| MLS | Team scoring/rest history only | Starting XI, keeper, suspensions, substitutions and player effects |

Roster `Active` means provider membership status. It never proves a player will
play. Missing injury rows never mean healthy; the injury census remains
unverified. Expected lineup, confirmed lineup, playing probabilities and expected
workload are not manufactured. An official source conflict stays visible until
an auditable resolution is bound; source precedence cannot be replaced by
first-match-wins behavior.

`validate_rotation` checks explicit conditional scenarios: NBA 240 and WNBA 200
regulation minutes; football snaps in separate offense/defense/special-team
groups; NHL skater/goalie groups; MLB integer outs or plate appearances; MLS
minutes. Budgets are conserved; out players, duplicate IDs, wrong units and
nonfinite values fail. It does not infer scenario weights or numerical impacts.
`membership_delta` records observed additions/removals between two snapshots,
without inventing transaction effective dates.

Before fitting each sport, preregister one challenger with the exact parent,
targets, exposure transform, train/calibration/test windows and promotion rules.
Require event-level **pregame** personnel snapshots, prior-only player stats,
parent OOF predictions and roster/transaction identities. Current reconstructed
rosters cannot fill historical availability fields. Fit player effects and
replacement rules on the training window only. Evaluate matched events with
season-opener/turnover/injury slices, counts and uncertainty, then freeze a
prospective trial. No external model percentages, arbitrary preseason blending,
confidence caps or manual injury point deductions enter this layer.

## Acceptance boundary

The focused suite exercises source tampering and re-sealing, stale/future and
post-start evidence, season and ID mismatches, ambiguous memberships, response
caps, all seven parser shapes, scenario budgets, immutable resume and the card's
pre-simulation refusal. The workflow runs these checks without artifact uploads,
so an upload quota cannot substitute for or prevent the contract test result.
Current-source evidence and exact test counts are recorded in the dated release
report. These checks establish infrastructure behavior, not predictive validity.
