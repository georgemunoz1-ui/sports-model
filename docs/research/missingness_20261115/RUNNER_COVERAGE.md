# Runner coverage repair — November 15, 2026

## Reproduced gap

At PR #117 head `14ccf3edacd6a5ad1463b66bbdd08582aab589e7`, the inventory check passed while omitting four executable paths: the direct CFB Monte Carlo CLI, direct MLB Monte Carlo CLI, selected-QB NFL margin CLI, and `python -m sportsim` alias. Its discovery rule only enumerated `scripts/run_*.py`.

The first three direct model CLIs could write new diagnostic outputs without the missingness receipts emitted by their separate shared/integrated routes. They remained research-only; this finding does not establish a betting-authority bypass.

## Changes

- Discover Python entry points by AST in scripts, models, research, sportsim, and pipelines; include declared console entry points and literal workflow Python commands with their working directories. This checkout has 133 classified entry points.
- Bind 20 workflows containing inline Python to their source hashes. An inline-code edit or new inline workflow requires renewed inventory review. Arbitrary dynamic shell indirection remains a manual review obligation.
- Classify historical studies, data acquisition, state preparation, grading/registration, review, and support operations separately. Preserve the retained historical engine snapshot with an exact source hash and an audited successor.
- Add CLI-only receipt hooks to the direct CFB and MLB engines. Each writes the original native forecast payload and a separate hash-bound `.missingness.json` sidecar. Native inference functions, fitted state, distributions, RNG and seed policy are unchanged. Output files use exclusive creation.
- Record actual prior replacements, missing schedule booleans, rating fallbacks and global residual-width fallback without claiming caller-supplied values are authenticated sporting observations. Failed captures, unresolved event identity and duplicate source evidence cannot enter the CLI's model call.
- Add the existing NFL child-receipt hook to the direct selected-QB margin CLI. Its unsupported child sensitivity stays explicit.

The static inventory proves classification coverage only. It explicitly returns `runtime_invocation_verified_by_inventory: false`; executable tests supply separate invocation evidence. None of these changes reviews a feature contract, sets a sensitivity limit, promotes a model, or enables a release.

## Verification

The old inventory gap was exercised before the repair: its original filename test passed while the four paths were absent. New tests add non-`run_` executable files, a console command without a main guard, a workflow script outside the normal source roots, and inline Python; all require classification.

Actual native CFB and MLB CLI calls retain the exact corresponding native output fields and hashes apart from the pre-existing wall-clock timestamp. Tests read back the sidecars, verify the reported fallbacks, reject forecast tampering, preserve existing output bytes, and prove failed inputs do not reach the simulation kernel. The direct NFL margin CLI executes its real build/persist path and writes a separately scoped child receipt; an injected receipt failure fails the CLI.

The companion CBB, joint-volatility, combination, personnel, freshness and routing branches are listed with exact dependencies in `entrypoints.json`; their separate heads are not certified by this checkout. Integration must extend and exercise this inventory on the actual combined revision.

Model-specific statistical support, reviewed contracts and thresholds, authorized witnesses, forward monitoring, and protected deployment remain separate requirements. Native diagnostic receipts retain `HOLD_PENDING_SCOPE_REVIEW`, release ineligibility and action OFF.
