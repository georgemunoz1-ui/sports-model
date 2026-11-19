# Football child-output imports and clock provenance: research plan

**Status:** PLAN ONLY — proposed amendment.  
**Authority:** RED / HOLD · NO_PICK · ACTION_OFF · 0 official units.  
**Inspected code baseline:** `5e204c1aa7bb06b64684b81dd71472265d91a786`.  
**Amends:** the plan introduced at `01a3c8496d4ac98397b8bd374b52b55a811e4ca3`.

This document specifies future implementation and research work. It does not establish that an importer, fitted distribution, validation gate, or prospective registration has been completed.

## 1. Purpose and frozen reference

The first implementation change will bring football card assembly under version control, import separately identified child outputs, and preserve independent clock metadata.

The frozen reference is `Sports-Card-2026-11-19.json`, with SHA-256:

```text
f96cd3f06e23e9c943b3f4dea129c8024ba8a4debd703599f4fcd1287a1de0be
```

Its football products are:

| Fixture | Existing output | Unavailable output |
|---|---|---|
| Rice at Temple | Selected CFB winner probability and margin point estimate | Spread probability, total point head, and total probability |
| Indianapolis at Houston | Selected NFL conditional-on-no-tie winner, separately identified margin-child probabilities, and total point estimate | Selected-QB total probability and joint-score distribution |

These absences remain explicit until a compatible research artifact and its supporting evidence exist. An importer does not create a fitted distribution or confer predictive qualification.

## 2. Established execution and assembly paths

### CFB

The selected native path is:

- `scripts/generate_card_force.py`
- `pipelines/cards/adapters/cfb.py`
- `models/current/cfb.py`

The selected CFB implementation produces logistic winner and ridge margin heads and explicitly returns no total head. Its winner-only simulations cannot supply spread or total probabilities. [Selected CFB implementation](https://github.com/georgemunoz1-ui/sports-model/blob/5e204c1aa7bb06b64684b81dd71472265d91a786/models/current/cfb.py)

### NFL

The selected-QB margin child uses:

- `scripts/run_nfl_integrated.py`
- `models/nfl/contextual/margin_distribution.py`
- `models/common/margin_challenger.py`

The November 19 spread child is `nfl.margin.full_support.research.ad4017ccf0663e24`. It does not use the legacy placeholder adapter in `pipelines/margins/nfl.py`. Refitting that legacy adapter is therefore outside the integration fix for today’s selected-QB output. [Current NFL margin adapter](https://github.com/georgemunoz1-ui/sports-model/blob/5e204c1aa7bb06b64684b81dd71472265d91a786/models/nfl/contextual/margin_distribution.py)

### Existing distribution hooks

The shared and NFL runners already support `--distribution-research-config`, using `pipelines/cards/distribution_research.py`. The retained-card command in `scripts/cross_sport_distribution_research.py` provides another route for compatible child evaluation.

These paths require matching parent identities and fitted artifacts. They produce separate research outputs; they do not establish a joint-score law or automatic inclusion in the delivered card. [Distribution integration](https://github.com/georgemunoz1-ui/sports-model/blob/5e204c1aa7bb06b64684b81dd71472265d91a786/pipelines/cards/distribution_research.py)

### Delivered card assembly

The November 19 delivered card was composed by the session-local `nov19-card/root/assemble_card.py`, outside the repository.

Its `football_row()` imports football winners and point estimates, but imports a spread probability only for NFL. It has no CFB distribution importer and no football total-probability importer.

The inspected assembler’s SHA-256 is:

```text
7ff2689cf12096854986b58e2b872604efb5dcf4a1ec301e914841cdf8779476
```

The implementation must retain this source and its provenance as a reference while introducing a repository-owned interface.

## 3. Implementation scope

### C1. Versioned football assembly interface

Bring the football normalization and assembly behavior into a repository-owned interface with an explicit schema version.

The interface must identify the event, product, parent forecast, child distribution, contract evaluation, quote edition, and source artifacts separately. Preserve existing selected winner and point-head values at source precision.

The external assembler is now a known entry point. Selecting the permanent module location is an implementation decision, not an unresolved discovery task.

### C2. Child-output importers

Add CFB and NFL importers for supported, separately identified child outputs.

Importers must verify schema, event, parent model and procedure, parent forecast hash, child model, fitted-artifact identity, product, settlement rules, and required source hashes. Market lines enter contract evaluation after forecast generation; they do not become model-fitting inputs.

Reuse the existing distribution hooks where their contracts fit. Do not activate a different parent or silently fit a model during import.

Keep analytic probabilities, Monte Carlo estimates, point estimates, and joint-score outputs distinguishable.

### C3. Clock metadata

Preserve these clocks independently:

- Information cutoff.
- Native inference generation, when evidenced.
- Local artifact receipt creation.
- Card assembly.
- Scheduled start.
- Canonical registration, when supported by its receipt.

The existing NFL bridge maps a local receipt’s `created_at_utc` into `generated_at_utc`. Correct that mapping under the agreed ledger semantics. A local receipt remains evidence of receipt creation; it is not canonical registration.

Unknown generation time remains null with an explicit provenance status. Define how missing clock evidence affects each eligibility decision. Do not rely on incidental parsing exceptions or infer generation from assembly.

Sources: [NFL artifact writer](https://github.com/georgemunoz1-ui/sports-model/blob/5e204c1aa7bb06b64684b81dd71472265d91a786/models/nfl/contextual/runtime.py), [NFL bridge](https://github.com/georgemunoz1-ui/sports-model/blob/5e204c1aa7bb06b64684b81dd71472265d91a786/pipelines/cards/distribution_research.py).

### C4. Integration acceptance

Exercise the seven cases in Section 4. Use clearly labeled synthetic fixtures for capabilities that do not yet have an admissible fitted artifact. Synthetic integration success does not establish live model support.

### C5. Separate fitted-model research

Track CFB margin fitting, football total distributions, joint-score candidates, and predictive qualification separately from the importer work.

A future candidate must declare its parent procedure, training population, feature transforms, information set, residual lineage, settlement convention, fit policy, and chronological evaluation design.

No baseline total is authorized for publication by this plan. No new distribution implementation or dependency on PR #105 or #106 is assumed merely because related code exists.

## 4. Seven implementation acceptance cases

All cases below are **planned; not executed by this documentation amendment**.

| Case | Required result |
|---|---|
| **1. Child identity and integrity** | Verify schema, event, parent model/procedure, parent forecast hash, product, settlement, fitted artifact, and required source hashes. Refuse a mismatched child with an explicit reason while retaining independently valid products. Never substitute the aggregate card hash for a missing native artifact hash. |
| **2. Quote editions and forecast identity** | A price-only refresh creates a new quote snapshot while preserving forecast, distribution, and contract-evaluation identities. A changed line creates a new contract evaluation against the same frozen distribution. Preserve retained draw hashes, label draw-based repricing as Monte Carlo, and count each forecast once within a cohort. |
| **3. Exact contracts and probability semantics** | Preserve signed line, side, full-game scope, overtime/tie rules, probability basis, and source precision. Check supported win/push/loss probabilities sum to one within a declared tolerance. Test whole-number and half-point settlement. Keep NFL conditional winner probabilities separate from unconditional margin probabilities and point-only totals. |
| **4. Unsupported or unavailable products** | Missing compatible fits, missing point heads, unsupported settlement, and missing required provenance produce null probabilities with distinct reasons. Do not infer dispersion, insert a stub probability, select another parent, or suppress an independently valid winner. |
| **5. Native-to-card parity** | Imported analytic probabilities equal the retained native report at source precision. Display rounding is explicit and does not alter stored values. Monte Carlo values remain separate. Selected parent winner and point heads are preserved. Repeated assembly from identical inputs is deterministic. |
| **6. Independent clocks** | Preserve cutoff, native generation, local receipt, assembly, scheduled start, and canonical registration with their evidence status. Unknown generation remains null. Define the eligibility outcome for missing clock evidence explicitly. A metadata repair does not create prospective registration. |
| **7. Frozen-artifact preservation** | Verify the November 19 card and retained source artifacts against their original hashes before and after the integration exercise. Corrected metadata and newly derived companions receive new versions and lineage. Original forecasts, probabilities, results, and registration status remain intact. |

## 5. Research evidence and unresolved prerequisites

### CFB dispersion and margin artifacts

`data/cfb/model/cfb_margin_sd_schedule.json` reports 10,818 out-of-fold residuals, pooled measured SD 16.7157, and weekly values with a thin-sample fallback. The referenced residual source is `data/cfb/model/cfb_v1_oof.parquet`.

This establishes that measured dispersion data exists. Compatibility with the selected current parent, training chronology, source bindings, and settlement treatment still requires verification. The stale “tonight is Week 1” note does not describe November 19.

The recorded skew and kurtosis are historical diagnostics. They do not prove Gaussian conditional residuals or qualified cover probabilities. [Dispersion schedule](https://github.com/georgemunoz1-ui/sports-model/blob/5e204c1aa7bb06b64684b81dd71472265d91a786/data/cfb/model/cfb_margin_sd_schedule.json)

### Existing joint-score research

An existing CFB empirical joint-score challenger has a distinct identity and a recorded failed winner screen. Its existence should inform future research without being treated as an approved substitute.

The available NFL joint-score residual bank is specific to the combined arm. It cannot be attached to the selected QB arm without changing the model and establishing compatible evidence. [CFB capability report](https://github.com/georgemunoz1-ui/sports-model/blob/5e204c1aa7bb06b64684b81dd71472265d91a786/docs/CFB_CAPABILITY_REPAIR_20261003.md), [NFL runtime restrictions](https://github.com/georgemunoz1-ui/sports-model/blob/5e204c1aa7bb06b64684b81dd71472265d91a786/models/nfl/contextual/runtime.py).

### NFL qualification

The selected-QB margin child’s recorded primary CRPS comparison remains inconclusive: difference −0.007908, 95% interval [−0.022664, +0.011302], aggregate screen `NOT_PASSED`. Its deployed all-history refit was not directly evaluated.

PR #69 was merged on October 24, 2026. That code merge does not alter these predictive limitations. [Bound evaluation](https://github.com/georgemunoz1-ui/sports-model/blob/5e204c1aa7bb06b64684b81dd71472265d91a786/data/nfl/qb_margin_full_support_v1/fit_01/evaluation.json), [PR #69](https://github.com/georgemunoz1-ui/sports-model/pull/69).

### Market comparison

Reuse `research/evaluate_discrete_products.py` where applicable. It already implements contract-matched no-vig comparisons and chronology checks.

Qualification still requires eligible, source-bound quotes for the exact evaluated arms and contracts. An NFL market evaluation for a different arm does not establish evidence for the selected QB margin child.

Compare equivalent probability targets. For refunded pushes, retain unconditional win/push/loss probabilities and evaluate the appropriate conditional non-push market comparison. Report distribution scores and interval coverage against suitable distribution baselines separately. [Existing evaluator](https://github.com/georgemunoz1-ui/sports-model/blob/5e204c1aa7bb06b64684b81dd71472265d91a786/research/evaluate_discrete_products.py)

## 6. Sensitivity interpretation

The Temple calculations using assumed sigma values and placeholder key-number weights remain illustrative sensitivities.

The measured schedule is evidence for investigating dispersion and artifact lineage. It does not convert the 52.8–52.9% examples into selected-model forecasts.

Those illustrative grids retain positive tied-final mass, so their raw positive-margin probabilities are not directly comparable to a decisive-winner head. Removing tied mass would change both winner and cover probabilities and requires explicit settlement treatment.

No validated range for the missing selected-parent cover probability has been established.

## 7. Completion and authority

Completion of the documentation amendment requires a docs-only diff and a PR description consistent with this scope.

Completion of the later integration requires evidence for all seven acceptance cases, review of the exact implementation revision, and applicable CI checks. Integration success establishes correct ingestion and reporting within its tested scope.

Predictive validation, publication eligibility, prospective registration, and wagering authority remain separate decisions.

No automatic model promotion, probability cap, fade rule, frozen-forecast rewrite, canonical registration, or wagering enablement is authorized.

**RED / HOLD · NO_PICK · ACTION_OFF · 0 official units.**
