# CFB point-in-time lineage infrastructure — September 18, 2026

## Delivered scope

**CFB lineage infrastructure pilot implemented and tested; no CFB model trained or promoted.** This is a separate namespace at `research/cfb_lineage/`, built from intact main `09ef320c2838b98951c5c336ba985c39bfd083e6`. NFL and existing CFB model code, defaults, frozen forecasts and ledgers were not changed. NFL PR39 remains a draft research challenger; the QB default is unchanged. The unverified NFL weekly-learning repair is not inherited or certified by this work.

Executed final implementation commit: `5113bce9eb970dcce4a0bc9b3c89900a3762c56f`.
Verification workflow: **35388318730**.
Actual test summary: **74 tests, zero errors, zero failures, zero skips**.

The scoped permanent instructions are retained in `research/cfb_lineage/AGENTS.md`. They require source-family separation, point-in-time eligibility, metric/identity contracts, immutable lineage and evidence-based feature/model promotion. ACTION OFF; dose 0.0; no merges.

## Four registry tables, not a column-count target

The generator exports explicit Parquet schemas and separate hashed configuration/contract files:

| Table | Actual real-data rows in this pilot | Meaning |
|---|---:|---|
| feature_definitions | 38 | Registered candidate definitions, not 38 implemented or fitted transforms |
| feature_observations | 0 | No current or historical predictive feature values manufactured |
| feature_model_paths | 0 | No fitted CFB model paths claimed |
| feature_evaluations | 0 | No ablation or predictive evaluation claimed |

The definitions cover ratings, efficiency, tempo, continuity, schedule/weather and matchup blocks. They retain source columns, family, units, orientation, transformation version, missingness policy, identity keys and definition hashes. The 38-feature core manifest is **REGISTERED_NOT_ACTIVATED**; required live-feature selection remains empty and explicitly blocked pending registered model training and block evaluation. A generated manifest is intent, not proof of model use.

All ten requested schema contracts were generated: schedule, PBP, team statistics, player identity, roster availability, weather, market, feature registry, state transition and forecast artifact. Structural schema validation is not a claim that all provider adapters or semantic checks are implemented. For example, live roster/weather acquisition and player crosswalks still require source-specific integration.

The model-path helper distinguishes standalone and ensemble paths. A standalone model is not forced into an ensemble, a zero-weight member is not active, and a nonzero coefficient or weight alone never establishes promotion. Nonlinear models cannot claim a fixed linear coefficient.

## Source families actually captured

Source capture workflow **35386151523** retained actual source bytes, current retrieval timestamps, release metadata, loader source, schema inventory, health and journal evidence. All 23 capture-manifest entries were independently verified after download.

| Captured 2026 release | Rows | Columns | Unique game IDs |
|---|---:|---:|---:|
| cfbfastR legacy PBP | 58,764 | 362 | 334 |
| ESPN-derived CFB PBP | 31,843 | 503 | 186 |
| CFB schedule release | 3,679 | 41 | 3,679 |
| Weekly ratings release | 2,007 | 16 | Not a game table |

The PBP families share 185 IDs. The legacy capture has 149 IDs absent from the ESPN capture; ESPN has one ID absent from legacy (`401858225`). Every PBP ID appears in the captured schedule release. **This is only an ID-set comparison, not independent complete-slate, team-orientation or final-score reconciliation.** The broad schedule has multiple classifications and future games; it is not declared an authoritative target-week FBS/FBS census.

The ratings file contains `through_week` values 1–15. It is retained as source discovery evidence, not admitted as a valid September 18 pregame rating panel. Neither a weekly label nor a current download establishes historical publication timing or freedom from future/revised values. No rating from this capture entered a prediction.

`load_cfb_pbp()` and `load_espn_cfb_pbp()` are explicitly separate families. The source documentation describes classic FBS PBP from 2014 onward and the ESPN family from 2004 onward. This pilot acquired the published release bytes through a Python source adapter; it did not execute the R package or silently interchange the datasets.

### Upstream model generation is also a dependency

The cfbfastR changelog documents builds that shared a package version while producing different EPA/WPA, and a shared model bundle that can refresh independently of a package update. The graph therefore distinguishes raw-data hash, loader commit, upstream model hash and rule-era contract. A finite EPA value does not establish compatibility. The captured data do not yet have independently pinned upstream model-generation provenance; EPA-derived predictive use remains blocked.

### CFBD access and ratings parameters

The official Python client **cfbd 5.27.1** imports successfully in a dedicated acquisition environment; GamesApi, RatingsApi and ApiClient were checked. The unauthenticated games request returned **HTTP 401** and is retained as a failed request receipt. Authenticated acquisition was not performed in this run; this does not assert that the owner has no API key elsewhere.

The inspected SRS, expanded SRS, SP+ and FPI endpoints do not expose an arbitrary `week` parameter like Elo. The request helper refuses such unsupported week queries instead of inventing historical snapshot semantics. CORE has its own through-week/model metadata and is not treated as an interchangeable Elo query. SRS/Elo/SP+/FPI, Massey and Versus remain separate candidate roles; no external rating was assigned a permanent model weight. Expanded SRS availability does not validate an FBS/FCS bridge.

## Immutable artifact graph

`core.Store` uses SHA-256-addressed immutable objects and semantic-ID bindings. Atomic file publication uses a temporary file, fsync, hard link and directory fsync. A SQLite transaction serializes transition registration and a parent-head compare-and-swap. Immutable reference/transition tables reject update/delete operations. Graph verification resolves every ancestor and rechecks raw bytes, with explicit CFB sport scope.

Implemented graph nodes include raw source, canonical dataset, schedule registry, weekly observation state, feature definition/set/snapshot, model, calibration and forecast. The pilot includes real-source graph verification and a complete **22-node synthetic graph** spanning two weekly observation transitions and a later synthetic feature/forecast artifact.

The synthetic prediction is explicitly `SYNTHETIC_TEST`, with unfitted model/calibration placeholders and no simulation. It demonstrates graph/contract behavior, **not a fitted CFB probability, predictive accuracy, or real later-forecast consumption**. Postgame evaluation linkage and the real forecast runner still require integration.

A hash chain proves byte integrity and recorded ancestry. It does not independently authenticate source truth, prove that a provider published a value historically, certify licensing, or prove an arbitrary submitted projection was produced by a model. The current forecast function validates and freezes a supplied research output; it is not a new inference engine.

## Weekly-state tests and limits

The implemented updater is a **CFB team/QB observation accumulator**, not NFL weights, a new strength-rating model, or an approved live pipeline. It accumulates observed offensive EPA, defensive EPA allowed and QB dropback observations with explicit denominators. Missing EPA is not a zero-valued observation.

The update boundary resolves a previously registered schedule rather than trusting a caller's list. The separate publisher compares enrolled canonical JSON with its raw source census. The current publisher adapter supports source-bound canonical JSON and test fixtures; **an independently verified CFBD/cfbfastR complete-week publisher adapter remains unfinished**.

Synthetic acceptance cases verify:

- Full incomplete or postponed weeks are WITHHELD, with no child state published.
- Truncated requests and truncated enrollment against an intact raw census are rejected.
- Out-of-week PBP is rejected before aggregation; missing games, duplicate play IDs/sequences, wrong teams/weeks, future availability and mismatched final scores fail.
- Same transition against the same parent returns the exact existing child with REPLAY_NOOP.
- Applying a processed game to its child state rejects it; changed content requires source-revision reconciliation.
- Four concurrent identical requests publish only one child.
- Week 1 then Week 2 uses the same team/QB accumulator without a cloned special-case branch.
- FBS/FCS mixing and changing PBP families within a lineage are blocked.

These tests establish local prototype behavior under the tested fixtures. They do not establish production recovery, distributed exactly-once behavior, licensed/authoritative schedules, or a real completed-week-to-later-forecast acceptance run.

## Feature signs, timing and units

The snapshot gate rejects late source/state/model/calibration availability, wrong definitions/transforms/source families, ambiguous team orientation, unknown units/signs, invalid probabilities and denominators, missing required features and observations already marked ineligible. A post-cutoff observation cannot be relabeled ordinary missingness to enter a forecast.

One specification correction was necessary: `home_off_epa - away_def_epa_allowed` cannot generally be labeled home-favorable positive. Increasing an opponent's EPA allowed represents a weaker defense, but subtraction would lower the claimed favorable score. The tested diagnostic contrast is:

`(home_off_epa + away_def_epa_allowed) - (away_off_epa + home_def_epa_allowed)`

This has the intended monotonic signs. It remains an **unfitted directional contrast**, not a calibrated expected-score or win-probability equation. No coefficient or probability was hand-adjusted.

## DVC and MLflow were actually exercised

The first verification attempt, run **35387526735**, stopped during dependency resolution: CFBD 5.27.1 requires Pydantic 1, while MLflow 3.12 requires Pydantic 2. No passing tests were claimed for that failed attempt. Acquisition and tracking now run in separate environments with both full dependency inventories retained; the tracker environment passed `pip check`.

### DVC 3.67.1

An isolated Git/DVC scratch project tracked nine source/registry files, executed `dvc repro` twice, and returned clean `dvc status --json` before cleanup. The captured lock hash is `d84db36dd769846488435cfc41d5ae5991e7783d16ea45d15ce5e1470d624eb6`.

The proof retains dvc.yaml, dvc.lock, pointer files and command logs. No remote was configured. Duplicate scratch raw files/cache were removed after the check because exact raw objects remain in the source capture and artifact graph. The slim scratch directory is not claimed to be a self-contained remote DVC backup; rerun the pilot with the supplied source capture to rematerialize it.

### MLflow 3.12.0

A local SQLite tracking run logged the candidate-definition dataset, its metadata/digest, DVC/configuration hashes, audit artifacts and zero trained-model/live-forecast counts. Its input-dataset link and FINISHED status were read back successfully.

Run ID: `b3d7aa349c3c4490aa7255dfdc4ba9d0`. Dataset digest: `c89615ca`.

The database and artifacts are retained. No hosted tracking service was connected, no predictive metrics were fabricated, and no trained model was registered. This is an infrastructure tracking test, not the requested future CFB baseline bake-off.

## Verification and reproducibility

Final workflow **35388318730**, executed commit `5113bce9eb970dcce4a0bc9b3c89900a3762c56f`, completed every checked step. The downloaded archive has **74 tests / 0 errors / 0 failures / 0 skips**. All **135 outer manifest entries** and **123 nested pilot entries** matched their hashes after download; nested counts overlap and are not independent additional artifacts.

| Archive | Artifact ID | SHA-256 |
|---|---|---|
| Source capture, run35386151523 | 10564046686 | `2f5d5483f0471dc904bea8afdedf6b5252d6088cc28111c3e1ed170ff7aa2587` |
| Final verification, run35388318730 | 10564593197 | `0374acbb755b25d3cea02520ccd138b0f61e122d9de9d56f127e2c6897d0f609` |

GitHub artifacts expire December 17, 2026. Downloaded archives are provided for separate retention; permanent offsite storage is not claimed.

Use Python 3.12, separate acquisition and tracking environments, and the extracted captured-source archive:

```bash
# Optional isolated official API-client environment; no token is committed.
python -m venv .venv-cfb-acquisition
.venv-cfb-acquisition/bin/pip install -r research/cfb_lineage/acquisition-requirements.txt

# Separate registry/tracking environment.
python -m venv .venv-cfb-lineage
.venv-cfb-lineage/bin/pip install -r research/cfb_lineage/requirements.txt
.venv-cfb-lineage/bin/python -m unittest discover -s tests -p 'test_cfb_lineage*.py' -v
.venv-cfb-lineage/bin/python -m research.cfb_lineage.run \
  --capture /absolute/path/to/extracted/source-capture \
  --output /absolute/path/to/NEW-output-directory --storage-smoke
```

New output directories are required. New executions retain their actual creation times and local tracking IDs; byte-identical timestamps across independent executions are neither expected nor invented.

## Remaining acceptance conditions

The broader build remains incomplete in explicit, separate ways: authorized current CFBD acquisition; independent complete-week source binding and canonical team/player crosswalks; upstream EPA/WPA model and rule-era provenance; historical as-of feature construction; predeclared CFB model training/calibration/ablation; rated-model versus market bake-off; actual forecast/simulation/evaluation integration; and a real weekly-state-to-later-forecast proof. None is cleared by the 74 infrastructure tests.

Global health remains **RED, four failures and nine warnings** in the retained source-run health evidence, with STALE_SNAPSHOT readiness. Archive, recovery, historical-release and standing-health obligations remain open. No default, past forecast, real-money ledger or action authority changed. This research implementation is not action-grade.

## Primary source references

- https://cfbfastr.sportsdataverse.org/reference/load_cfb_pbp.html
- https://cfbfastr.sportsdataverse.org/news/index.html
- https://api.collegefootballdata.com/api/ratings
- https://github.com/CFBD/cfbd-python
- https://doc.dvc.org/user-guide/project-structure/dvcyaml-files
- https://mlflow.org/docs/latest/api_reference/python_api/mlflow.data.html

Source-specific row counts and execution results above come from the preserved, hash-verified source and verification archives, not from documentation examples.
