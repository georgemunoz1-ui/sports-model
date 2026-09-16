# Consolidated model access

The default `main` contains the operational models and the previously separate research engines. Select defaults by held-out evidence using `python scripts/model_defaults.py`; software test counts do not select a forecasting champion. Other models remain accessible as explicitly named research implementations.

## Setup

Use Python 3.12 in a virtual environment, then:

```bash
python -m pip install -r requirements-consolidated.txt
python -m pip install --no-deps -e .
python scripts/model_defaults.py
python -m pytest tests -q
```

## Entry points

| Sport / capability | Tested default or research implementation | Access |
|---|---|---|
| NFL | Selected QB winner arm; combined remains experimental | `python scripts/run_nfl_integrated.py --help`; [Week 2 assimilation](NFL_WEEK2_REPAIR.md) |
| MLB | Selected V13 winner estimator with acquired current inputs | `python scripts/prepare_mlb_current.py --help`; `python scripts/generate_card_force.py --league mlb --help`; [current packet contract](MLB_CURRENT_PATH.md) |
| WNBA | Selected FF7 ridge model | `pipelines.cards.selected.wnba_predict` delegates to `harness.wnba_model_v1.predict_slate`; requires its fitted state and feature frame |
| CFB | Selected FBS form model; separate Week 1 context model | `harness/cfb_v1_port.py`; [selection scope](MODEL_DEFAULT_SELECTION.md). Restored margin adapter is a separate research model and is not silently substituted for the selected winner arm. |
| NBA | Restored efficiency simulation / card adapter; no evidence-cleared default | `models.nba.efficiency_monte_carlo_v1`; `pipelines.cards.adapters.nba`; default selector explicitly blocks unvalidated automatic selection |
| NFL/NBA/MLB/NHL standalone simulation | sportsim research engines, ratings, season and chronological backtests | `python -m sportsim --help`; [usage and input formats](SPORTSIM_RESEARCH.md). Synthetic demo is not a current forecast. |
| Alternative MLB Gamma-Poisson | Preserved research adapter | `pipelines.cards.adapters.mlb_gamma_poisson_research`; original current-data and missing-starter guards retained |
| WNBA efficiency simulation | Separate research engine | `models.wnba.efficiency_monte_carlo_v1_1` |
| MLS | Recovery/source tooling; no verified default engine | `scripts/recovery_capture.py`; `scripts/recovery_features.py` |

## Current-input requirement

Merging code does not refresh schedules, starters, rosters, injuries or weather. The September 14 MLB package remains immutable. Its old code/input pins intentionally reject the consolidated tree; build a **new** package from freshly acquired evidence before a new board. Do not change old packet hashes to clear that gate. Week 2 NFL needs the documented Week 1 assimilation proof plus fresh event/personnel context.

A selected default is distinct from official release eligibility and action permission. Research and diagnostic entry points are usable without claiming official clearance. Action authority remains OFF. Hardware/software tests do not establish predictive calibration, current input completeness or prospective registration.

## Merge resolutions

- PR9 freshness repair retained; later audit entries preserved.
- PR10 simulation specification retained.
- PR11 release/backfill work retained; PR26 provenance-marked parser fixture and stronger ingestion regression assertions take precedence over its older self-tests.
- PR12 recovery and simulation tools retained; its Gamma-Poisson adapter has an explicit research name so it cannot replace the newer MLB default. Its strict timestamp and no-self-registration fixes are integrated into the shared card generator.
- PR16 checks every MLB feature row, not only the first 50.
- PR1 sportsim available independently; does not become an automatic official default.
- PR13–15 historical evidence retains original eligibility labels; PR26–30 operational repairs and selected defaults retained.

Tests cover repository unit/contract/simulation behavior. They do not validate external source availability, all live league adapters, betting profitability, or official release acceptance. The full health report lists remaining external evidence/recovery blockers separately.
