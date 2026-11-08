# Dated research runner contracts

The diagnostic workflow accepts a requested league, slate date and cutoff. A supplied artifact is restored into a new directory, its archive digest is checked, and the actual runner receives the package path and its file digest. The selected forecasting and settlement code owns the numerical outputs.

| League | Runtime | Contract boundary |
|---|---|---|
| MLB | Shared | Selected Monte Carlo winner. Explicit current package or the existing pinned legacy MLB route. |
| CFB and WNBA | Shared | Existing population rules and fitted heads. |
| NBA, NHL and MLS | Shared | Explicit initial-research opt-in. MLS retains the draw as a third possible result. |
| NFL | Dedicated integrated runner | A pinned event package and, for weekly-state events, a verified store and state ID with an independently supplied seed pin. Binary winner probabilities are conditional on a decisive result. |
| Men's CBB | Unavailable on the base revision | The workflow records a refusal. The separate draft research implementation has its own inputs and grading contract. |

For shared current packages, pass `--event-package` and `--event-package-sha256` to `scripts/generate_card_force.py`. The package file must be the league's `package.json`. The generator checks the Pacific slate date, enumerated events and loaded model context against that file. The two explicit package arguments also select the strict mode of `scripts/run_nfl_integrated.py`. Native NFL inputs retain their league-specific game day and kickoff convention. Operational schedule corrections must carry their own verified source evidence before packaging.

A successful forecast appears under its original event ID. A failed matchup with a known ID carries a reason. Failures that precede schedule enumeration stay at run level. A mixed NFL run retains its verified numerical rows and exits 2. The shared generator also exits 2 for coverage incidents.

The final workflow gate checks the generator exit, package identity, scheduled event set, row contents and the static HTML. A zero generator exit cannot erase a blocked receipt. A passing diagnostic artifact must be downloaded by artifact ID and checked against its staged manifest and visible card before any eligible registration step. A diagnostic run does not establish recipient acknowledgment. Missing inputs, unsupported paths and empty numerical tests do not earn numerical runtime acceptance.

`scripts/verify_all_current_runtimes.py` reports all eight league statuses and exits nonzero when any required league is unverified. Use `--required-leagues` to limit an experiment explicitly. The legacy hosted six-league recovery check declares that scope and retains its separate historical NFL check.

## Local evidence

- Six shared adapters each completed a 100,000-draw synthetic matchup and a deterministic rerun through the native CLI. These controls exercise handoffs and retained arrays.
- A dated Denver–Kansas City NFL replay exercised the dedicated path. In a mixed test the valid event survived a sibling refusal and the process returned 2.
- The original November 8 NBA and NHL archives reproduced 700,000 and 600,000 winner draws. The separate CBB archive reconciled 37 events, comprising 30 forecasts, seven refusals and 3,000,000 paired scores. Historical readback does not activate CBB on this branch.
- Independent offline Chromium checks on retained MLB, NBA and NHL cards verified the visible fields of all 23 rows at desktop and phone widths, with scripts enabled and disabled.

Run `python -m pytest tests research/tests -q` for local regression coverage. Production acquisition, authenticated registration, delivery, predictive qualification and the November 8 NFL slate have separate acceptance criteria.
