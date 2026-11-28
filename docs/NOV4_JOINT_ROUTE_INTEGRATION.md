# Explicit joint-volatility card routing

This branch integrates the exact PR #105 research files at
`629ed150612a56f2dabaecdecaab7019af3e7630` into a separate, opt-in card route.
It does not change the numerical matrix implementation, fit bytes, selected
defaults, prior point forecasts, cutoff gates or wagering authority.

The November 3 incident was a routing/disclosure failure: the saved card used
legacy empirical distributions and did not invoke the matrix. In a later
compatibility attempt the NHL matrix correctly refused the original cutoff
because its fit time was later. This route does not backdate or repair that
historical forecast. Future executions must satisfy the ordinary matrix gates.

## Shared runner

Add `--volatility-research-config path/to/config.json` to the existing
`scripts/generate_card_force.py` invocation. The parent winner card remains
unchanged; the resulting Markdown visibly reports requested and executed
routes, event/arm coverage, refusals, actual paired draws and no fallback.

The config keeps PR #105's `sports.volatility_card_config.research.v1` schema:
SHA-256 pinned models, information set, action authority false and optional
quoted contracts. If the displayed winner model has a different parent ID,
explicitly supply a compatible point-parent card:

```json
{
  "schema": "sports.volatility_card_config.research.v1",
  "action_authority": false,
  "information_set": "RECONSTRUCTED_PROVIDER_FINALS_FIXED_PARENT",
  "parent_card": {"path": "fixed-point-parent.json", "sha256": "ACTUAL_FILE_SHA256"},
  "models": [{"path": "nhl-empirical.json", "sha256": "ACTUAL_FILE_SHA256"}],
  "contracts": []
}
```

Paths are relative to the config. The explicit parent must match the displayed
card's league, card date, event set and kickoff timestamps. Its original model
identity, point means, cutoff and generation time are passed unchanged into the
matrix adapter. A matching ID alone does not clear the adapter's chronology,
feature, information-set, code-hash, fitted-state and settlement checks.

Existing frozen cards can invoke the same receipt route separately:

```bash
python scripts/run_volatility_card_receipted.py \
  --card /absolute/path/displayed-card.json \
  --config /absolute/path/joint-config.json \
  --output /absolute/path/new-joint-output \
  --simulations 100000
```

An empty `models` list visibly reports FIT_REQUIRED; it never creates a fit or
switches to legacy distributions. Malformed or missing configs produce an
explicit refusal receipt. Failed requested research returns exit code 2. A
separately requested legacy distribution remains its own experiment, never an
automatic substitute for the requested joint route.

## Retained evidence and display

- `route_receipt.json`: actual checkout SHA, dirty working tree and source
  hashes; process argv; original displayed and explicit parent file/row hashes;
  both clocks; config and fitted-artifact identities; invocation/completion
  times; per-market availability/refusal; actual paired draw counts; output
  hashes; fallback false.
- `joint/volatility_report.json` and `.npz` arrays: PR #105's exact distributions,
  paired samples, seeds, hashes and research limitations.
- `card_with_research_routes.json`: new display successor with route coverage;
  the original `diagnostic_card.json` remains unchanged. Existing explicit
  research route summaries are preserved.

Completed paired distributions with no configured quotes are visibly marked
`DISTRIBUTION_ONLY_NO_QUOTE`, not quoted betting forecasts. A failed partial
write retains pair-file counts and is marked FAILED; orphaned draws do not
become valid forecasts. Existing output directories are never overwritten.

Focused tests include a synthetic 100,000-draw paired replay, shared CLI display,
explicit-parent matching, future-fit/missing-head rejection, missing/malformed
config receipts, duplicate-fit refusal, FIT_REQUIRED, and overwrite protection.
These are engineering checks, not evidence of predictive improvement. Full
release health remains a separate RED constraint. This integration is a
research branch, not deployment, promotion or prospective registration.
