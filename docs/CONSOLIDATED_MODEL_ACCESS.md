# Consolidated model access

Updated October 23, 2026 Pacific / October 24 UTC. The consolidated source is `main`; see [current status](CURRENT_STATUS.md) for the inspected commit and evidence boundaries. The old guide is preserved in [history](history/2026-10-23-status-refresh/CONSOLIDATED_MODEL_ACCESS.md).

## Setup and inspection

Use a complete checkout and Python 3.12:

```bash
python -m pip install -r requirements-consolidated.txt
python -m pip install --no-deps -e .
python scripts/model_defaults.py
python -m pytest tests research/tests -q
python harness/healthcheck.py
```

Software tests and health are separate commands. Retain both outputs; a partial source restoration cannot certify full repository health. Commands below are usage examples, not executions performed by this documentation update.

## Real entry points

| Capability | Entry point | Boundary |
|---|---|---|
| Shared seven-league card | `scripts/generate_card_force.py` | Valid fresh source-bound package; post-start events cannot receive new pregame forecasts |
| NFL selected QB and explicit research arms | `scripts/run_nfl_integrated.py` | Selected QB winner is distinct from combined, enhanced-pregame and live modes |
| CFB/NBA experiments | `scripts/run_efficiency_experiments.py` | Separate efficiency/personnel/joint stages and real chronological controls |
| CFB/NBA selector evaluation | `scripts/evaluate_efficiency_selection.py` | Frozen protocol, retained run, same-event population; no automatic threshold optimization |
| Opt-in shared-card efficiency SHADOW | `--efficiency-research-config` on shared card | Fitted candidate states/history configuration; local receipts, not canonical registration |
| Shared discrete-distribution research | `scripts/cross_sport_distribution_research.py` | Explicit compatible parent, product and settlement; does not infer a law from a win probability |
| MC precision research | `scripts/run_mc_precision_research.py --allow-research` | Numerical simulation precision, not predictive accuracy |
| Separate NBA direction-repair shadow | `scripts/run_nba_efficiency_shadow.py --allow-research` | Requires supplied fitted state; not the PR #78 possession-efficiency experiment |
| Research selection/evaluation | `scripts/run_research_selection.py`, `scripts/evaluate_research_selections.py` | Raw evidence retained when selection fails; publication/wagering OFF |
| Canonical registration/results/grading | `scripts/canonical_forecasts.py`, `scripts/canonical_results.py` | Genuine pre-start upload/receipt validation; no retrospective registration |
| Standalone sportsim | `python -m sportsim --help` | Separate research/demo engine, not a selected operational default |

CFB and WNBA **current shared-card adapters are present**. NBA/NHL/MLS have explicit initial research adapters; that is different from a verified automatic default. [Default boundaries](MODEL_DEFAULT_SELECTION.md).

## Run the two independent historical experiments

Supply actual normalized source-bound history files; the repository does not manufacture them from these example paths. Use fresh output directories.

```bash
python scripts/run_efficiency_experiments.py \
  --league cfb --history /absolute/path/cfb-bound-history.json \
  --stages efficiency personnel joint --bootstrap-count 2000 \
  --output-dir output/cfb-efficiency-unique-run

python scripts/run_efficiency_experiments.py \
  --league nba --history /absolute/path/nba-bound-history.json \
  --stages efficiency personnel joint --bootstrap-count 2000 \
  --output-dir output/nba-efficiency-unique-run

python scripts/evaluate_efficiency_selection.py \
  --run output/nba-efficiency-unique-run \
  --protocol docs/research/efficiency_2026_10_23/selection_protocol_v1.json \
  --output output/nba-selection-unique-run
```

Read the protocol schema before reuse; an existing inspected protocol does not turn a new tuned analysis into confirmation. Missing authenticated personnel inputs produce an explicit blocked stage, not a fabricated zero effect. Earlier repaired runs remain diagnostic. Source preparation tools include `acquire_efficiency_history.py`, `capture_efficiency_current.py`, `prepare_cfb_efficiency_history.py` and `prepare_efficiency_current_nba.py` under `scripts/`.

## Shared-card candidate integration

After verifying the package and candidate configuration:

```bash
SPORTS_RESEARCH_PACKAGE_DIR=/absolute/path/packages \
python scripts/generate_card_force.py \
  --league nba --date YYYY-MM-DD --initial-research-baselines \
  --simulations 100000 \
  --efficiency-research-config /absolute/path/nba-shadow-config.json \
  --output-dir output/nba-card-unique-run
```

The configuration binds fitted states and source history; it is not a switch that fits a model. The candidate outputs are separate from the original baseline card. Use `--help` for the exact current CLI contract. The current default numerical identity is `market_blind_numeric.v2`; explicit `legacy.v1` remains available for original replay. Never overwrite old forecasts or alter their code/input pins to make them run.

For NFL, use a fresh package through `NFL_CONTEXT_PACKAGE`. Explicit combined-arm spread diagnostics require `--model-id nfl.integrated_context.combined.v1.research --home-spread HANDICAP`; this does not create a selected-QB spread product. Market-informed and live modes require their separate packets. [NFL guide](NFL_CONTEXT_INTEGRATION.md), [market/live guide](NFL_MARKET_LIVE_MODELS.md).

## Evidence and output interpretation

Shared output includes `diagnostic_card.json`, Markdown/CSV, retained draws, disclosures and research selection sidecars. Opt-in efficiency output adds its own run and component receipts. Keep model, simulation and market observations separate; a Bernoulli winner simulation is not a score simulation. Record unique events separately from multiple stages/versions.

Current-data acquisition, scheduled execution, verified archive upload and canonical grading each require their own acceptance. See [runtime status](ALL_MODELS_CURRENT_RUNTIME.md), [archive contract](CI_STORAGE_ARCHIVE.md) and [executed run IDs](research/efficiency_2026_10_23/INTEGRATION_STATUS.md). None of these commands changes model promotion or wagering authority.
