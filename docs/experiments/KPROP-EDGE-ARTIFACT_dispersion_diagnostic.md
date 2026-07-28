# KPROP-EDGE-ARTIFACT — dispersion diagnostic · **EXPLORATORY**

**Status: EXPLORATORY DIAGNOSTIC. No selector change. No formula change. Engine untouched.**
`KPROP-EDGE-ARTIFACT` stays **OPEN**. Nothing here promotes, demotes or reweights any play, and the
frozen `KSIM-0727-U02` decision set is unmodified.

Board: the 23 frozen `KSIM-2026-07-27` rows against the `KSIM-0727-U02` capture. `L` is the
cross-book mean posted line per pitcher. **n = 23. Exploratory.**

---

## 1. The identity, stated correctly

Let `X = E[K]`, `L` = posted line, `R = X − L`.

```
                 ρ_XL·σ_X − σ_L
corr(R,L) = ───────────────────────────────
            √(σ_X² + σ_L² − 2·ρ_XL·σ_X·σ_L)
```

Observed board moments:

| | |
|---|---|
| `σ_X` | 0.8504 |
| `σ_L` | 1.0170 |
| `ρ_XL` | 0.7916 |
| `corr(R,L)` observed | **−0.5518** |

Substituting: `(0.7916·0.8504 − 1.0170) / √(0.7232 + 1.0343 − 2·0.7916·0.8504·1.0170)`
`= −0.3438 / 0.6230 = −0.5518`.

### 1.1 Correction to the earlier claim

An earlier report said the dispersion gap **alone** predicts −0.5518. **That was wrong and is
withdrawn.** `σ_X < σ_L` on its own does not determine `corr(R,L)`; the identity requires all three
moments, including the observed `ρ_XL = 0.7916`. The arithmetic used `ρ_XL` even though the wording
claimed otherwise.

**And what the reconstruction is, precisely:** inserting observed board moments and recovering the
observed correlation is an **in-sample algebraic reconstruction** — an identity closing on itself.
It is **not** independent evidence that under-dispersion *caused* the relationship. Nothing here
could have come out differently; that is the nature of an identity.

## 2. Equivalent regression form

```
cov(R,L) = (β_X~L − 1) · var(L)
```

`β_X~L = ρ_XL·σ_X/σ_L = **0.6620**`, so `cov(R,L) = (0.6620 − 1)·1.0343 = −0.3497`, matching the
observed −0.3497 exactly.

**A slope below one mechanically makes residuals negatively associated with line height.** `R` and
`L` share the variable `L` by construction, so they are coupled before any question of information
arises.

## 3. What this establishes — and what it does not

**Establishes:** the residual-versus-line correlation is mathematically coupled through a shared
variable and through projection compression (`β < 1`). **It therefore cannot demonstrate edge**, in
either direction, and must not be cited as evidence of one.

**Does NOT establish:** that the projection contains no incremental information. A compressed
estimator can still carry real signal. The coupling makes `corr(R,L)` an *inadmissible metric*; it
does not adjudicate the underlying question. Ruling on information requires the outcome tests in §5,
not this diagnostic.

## 4. Revised issue text

`KPROP-EDGE-ARTIFACT` remains **OPEN**, revised to:

> The observed residual-line correlation is mechanically contaminated by shared-variable coupling
> and projection compression; it is not an admissible edge metric.

## 5. After-outcomes test plan (pre-registered here, NOT yet run)

Does the projection add information **beyond the market**?

1. Compare an outcome model using **market line + two-sided prices** against one that adds `E[K]`.
2. **Orthogonalise:** `U = E[K] − fitted_E[K](market information)`.
3. Test whether `U` predicts **actual K minus the market forecast**.
4. Compare **held-out MAE and NLL** — *not* residual-versus-line correlation, which §3 rules
   inadmissible.
5. Treat **n ≈ 23 as exploratory** throughout. No verdict moves on it (R4).

**Market forecast construction:** use a **price-adjusted** market forecast wherever complete
two-sided prices exist. A half-point line on its own is only a coarse market estimate — it locates
the market between two integers and says nothing about where inside that interval, which the prices
do carry.

## 6. Data-quality tags — frozen BEFORE outcomes

`data/mlb/props/evidence/2026-07-27/KSIM-0727-U02_dq_tags.json`, frozen `2026-07-28T01:40:27Z`,
sha256 `7c004cf4a75579c18c97426dd096edbe1013714e0f490b0a16b383d5e800f39f`, with
`outcomes_inspected_at_freeze: false`. Per-row tags: log age, placeholder contamination, pre-game
starter confirmation, opener/workload risk.

**Reporting contract:**

- **A — all 23 frozen rows.** Operational pipeline performance. **This is the headline.** It
  includes every stale log, unconfirmed starter and opener risk, because that is what the pipeline
  actually emits.
- **B — the pre-tagged `data_valid_subset_B`.** **Sensitivity analysis only**, never the headline.
  Membership is fixed by that file and **may not be redefined after results** are seen.

Subset B rule, fixed in advance: `log_age_days ≤ 21` **and** not placeholder-contaminated **and**
`opener_workload_risk ≠ HIGH` **and** `gs ≥ 10`. **B = 15 of 23.**

Two observations available now, both outcome-independent:

- **Placeholder contamination does not reach `E[K]`.** The `ER=0, BB=0` placeholders occupy fields 2
  and 4 of the 7-field log; `kprops._parse` reads `p[3]=SO` and `p[5]=TBF` only. Real for ERA,
  orthogonal to the K projection. The subset-B clause is retained anyway as a conservative,
  non-binding filter.
- **Three of the four fired rows fall OUTSIDE subset B** — Alvarez, Perkins and Imai are all
  `opener_workload_risk = HIGH`; only Peterson is inside. Determined by a rule fixed before any
  outcome was inspected. It is a flag for where the selector concentrates, not a result.

## 7. Withdrawn claim

> "Market 3.5 implies approximately 15 batters faced."

**Withdrawn.** A 3.5 strikeout line reflects the market's **joint** expectation over workload,
strikeout rate, the outcome distribution and pricing. TBF cannot be uniquely recovered from a line
without separately specifying a market K-rate and a probability model. The earlier statement
inverted a single number into a quantity that is not identified from it.

The underlying concern — that `E[TBF]` may not read what a low line is signalling
(`KPROP-OPENER-2`) — stands on its own and is unaffected by this withdrawal.
