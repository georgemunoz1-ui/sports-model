# E6 — HR log-odds shrinkage in a log5 event model · PRE-REGISTRATION

**Status:** PRE-REGISTERED (hypothesis only). **NOT implemented. NOT run. DATA-BLOCKED.**
**Engine unchanged.** No V11, v12 or V13 file is touched by this document. Formula changes are
frozen; this is recorded as a separate hypothesis, which is the only form it may take.

**R7 commitment:** the parameter, the normalisation scheme, the guards and the adoption rule below
are fixed BEFORE any result is seen. Changing any of them after this doc is committed re-labels the
run exploratory.

**ID note:** `E4` is currently assigned twice in `state.json.experiment_queue` (lineup-aware offense;
V13-vs-moneyline). That collision is pre-existing and is **not** resolved here — this experiment
takes **E6** to avoid compounding it.

---

## 0. What this supersedes

Two analytical claims previously attached to this construction are **withdrawn and replaced**. Per
R6 the originals are not erased; they are superseded here.

| # | withdrawn claim | replacement |
|---|---|---|
| 1 | log-odds interpolation is "less violent at the extremes" than probability interpolation | **not a universal property** — see §3 |
| 2 | independent binary log5 "may not normalise" | **stronger**: it generally does not, and the standard fix silently destroys the shrinkage target — see §4 |

## 1. The algebra that is CORRECT

The construction under review:

```python
raw = {}
for e in EVENTS:
    orr = _odds(b[e]) * _odds(p[e]) / _odds(L[e])
    if e == "HR" and hr_shrink > 0:
        orr = orr ** (1 - hr_shrink) * _odds(L["HR"]) ** hr_shrink
    raw[e] = orr / (1 + orr)
```

Both steps are algebraically sound and are **not** what this document disputes.

- **log5 in odds form is exact.** log5 is
  `(bp/L) / ( bp/L + (1−b)(1−p)/(1−L) )`, whose odds are
  `[b/(1−b)]·[p/(1−p)]·[(1−L)/L] = odds(b)·odds(p)/odds(L)`. The line is the identity, not an
  approximation.
- **The shrink line is weighted geometric interpolation in odds space**, identical to
  `h = logistic((1−s)·logit(q_HR) + s·logit(L_HR))` where `q_HR` is the unshrunk log5 output.
  Verified: `odds(h) = odds(q)^(1−s) · odds(L)^s` reproduces to 8 decimal places.
- `orr/(1+orr)` is the odds→probability inverse.

## 2. Hypotheses

- **H1:** shrinking the log5 HR probability toward league in log-odds space, with the target
  preserved through normalisation, improves out-of-sample HR-rate calibration relative to unshrunk
  log5.
- **H0 (null, default, retained by default):** the shrink adds no out-of-sample improvement; any
  apparent gain is absorbed sample noise or a calibration error better fixed by a calibration layer
  (§5.4).

## 3. Correction 1 — what log-odds interpolation actually gives you

**Withdrawn:** that it is "less violent at the extremes" than probability-space interpolation.
That is true only in a special case and false in general.

Interpolating between `q` and `L` at `s = 0.5`:

| endpoints | linear | log-odds | behaviour |
|---|---|---|---|
| q=0.001 → L=0.030 (both near 0) | 0.01550 | 0.00553 | moves **less** than linear |
| q=0.999 → L=0.970 (both near 1) | 0.98450 | 0.99447 | moves **less** than linear |
| q=0.500 → L=0.030 | 0.26500 | 0.14956 | moves **more** than linear |
| q=0.500 → L=0.001 | 0.25050 | **0.03067** | moves **far more** than linear |

When both endpoints sit near the same boundary, log-odds interpolation is gentler. When the
endpoints are far apart **in log-odds space** it is dramatically more aggressive — 0.500→0.001 lands
at 0.031 where linear lands at 0.251, an 8× difference. "Less violent at the extremes" describes the
first two rows and is contradicted by the last two.

**The defensible properties, and the only ones claimed here:**

1. **Bounded** — `logistic: ℝ → (0,1)`, so the result is a valid probability for any real
   interpolation, with no clipping needed on the output.
2. **Preserves the endpoints** — `s=0 → q` exactly, `s=1 → L` exactly. Verified to machine
   precision.
3. **Interpolates geometrically in odds space** —
   `odds(h) = odds(q)^(1−s) · odds(L)^s`, i.e. a weighted geometric mean of odds, equivalently a
   weighted arithmetic mean of log-odds.

Property 3 is the substantive one: it is a statement about *what* the interpolation is, not a claim
that it is safer.

## 4. Correction 2 — the normalisation defect is stronger than "may not sum to one"

**Applying binary log5 independently to mutually exclusive events generally produces probabilities
that do not sum to one.** Each event is computed in its own two-outcome universe (`e` vs `not e`),
so nothing couples them. This is structural and holds even when `b`, `p` and `L` each sum to one
exactly.

**And the usual repair destroys the thing the shrinkage was for.** Dividing every event by
`Σ raw[j]` rescales HR along with everything else, so the delivered HR rate is **not** the value the
shrinkage formula produced.

Worked example — **synthetic illustrative inputs, not measured data**; `EVENTS = {HR, 3B, 2B, 1B,
BB, K, OUT}`, `b`, `p`, `L` each summing to 1.000, `hr_shrink = 0.40`:

```
sum(raw)                          = 0.992512      (excess -0.007488)
shrinkage formula target h        = 0.036381
after global renormalisation      = 0.036655
DRIFT                             = +0.000274     (+0.75% relative)
```

The magnitude is data-dependent — it grows as `b` and `p` diverge from `L` — but the **direction of
the defect is not**: whatever `hr_shrink` is tuned to deliver, global renormalisation delivers
something else. The consequence is interpretive: **the direct binary-logit interpretation of
`hr_shrink` does not survive downstream normalisation. The parameter could still be estimated
end-to-end against the final normalised distribution, but it would no longer mean the stated
interpolation weight.** Normalisation changes interpretation; it does not by itself demonstrate
statistical non-identifiability.

### 4.1 Pre-committed fix (scheme A, ANCHOR_HR)

```
h     = logistic( (1 − s)·logit(q_HR) + s·logit(L_HR) )
P(HR) = h
P(e)  = (1 − h) · raw[e] / Σ_{j ≠ HR} raw[j]        for every non-HR event e
```

Verified on the example above: `P(HR)` reproduces `h` to `+0.00e+00`, the distribution sums to
`1.000000000000`, and the non-HR events keep their relative proportions exactly.

**Stated cost, not hidden:** this privileges HR as the anchored event and makes every other event
absorb the entire normalisation error. That is a modelling choice, not a derivation. Whichever event
is anchored, some event absorbs the residual.

### 4.2 Alternative (scheme B, MULTINOMIAL)

Construct the whole event distribution jointly with multinomial log-odds / softmax over a reference
category, so normalisation is built in and no event is privileged. Shrinkage then applies in that
parameterisation. This is cleaner but is a different model, not a patch.

### 4.3 R7 — the scheme is an architecture fork and MUST be pre-committed

A and B are a **model-architecture fork and a researcher degree of freedom**, not a second numeric
free parameter: they are different models, not two settings of one knob. Choosing between them
*after* seeing which calibrates better is exactly the degree of freedom pre-registration exists to
remove. **E6 pre-commits to scheme A (ANCHOR_HR)**, and assigning scheme B to a separate experiment
with its own pre-registration remains the correct control. Likewise, the normalisation fix is a
*correctness* repair
rather than a tuning knob — but it still changes outputs, so it cannot be slipped into a frozen
formula without going through this process.

## 5. `hr_shrink = HR_K/(BBE + HR_K)` is NOT adopted

Read as the standard shrinkage weight `s = K/(n + K)` with prior strength `HR_K` and sample size
`BBE`. **Four questions must be answered before any value is proposed.** Until then `hr_shrink` has
no pre-registered value and E6 cannot run.

**5.1 Are `b` and `p` already regressed?** If they are already empirical-Bayes shrunk toward league
— the K engine does exactly this, `krate = (SO + L·80)/(TBF + 80)` — then shrinking again toward the
same target is **double shrinkage**, and total pull is `1 − (1 − w₁)(1 − s)`, not `s`. Required
deliverable: the prior weight already embedded in `b` and `p`, per input, before `s` is chosen.

**5.2 Is HR modelled per PA or conditional on BBE?** The two are not interchangeable and the
denominator gives the game away. `BBE` is the natural sample size for `HR | BBE` (HR per batted
ball). If HR is modelled **per PA**, the sample size is `PA`, and `BBE` mixes units — the shrink
would be indexed by a denominator the quantity is not defined on. If HR is genuinely conditional on
BBE, the event distribution must be built as `P(BBE) × P(HR | BBE)`, which is **not** what the code
in §1 does — that code treats HR as a per-PA event alongside K and BB.

**5.3 How are hitter and pitcher sample uncertainty combined?** log5 consumes `b[e]` *and* `p[e]`,
each with its own sample size, but `hr_shrink` is a single scalar. One number cannot represent two
independent uncertainties. Either shrink `b` and `p` separately before log5 (which folds into 5.1),
or state and justify the combination rule (e.g. harmonic mean of effective sample sizes). Silently
using one side's `BBE` shrinks against the wrong denominator.

**5.4 Is the target sampling uncertainty or calibration correction?** These demand different
functional forms and are routinely conflated:
- **sampling uncertainty** → `K/(n+K)`, decays to 0 as `n → ∞`, `K` derived from a beta-binomial /
  variance decomposition rather than fitted to outcomes;
- **calibration correction** → a fitted slope on out-of-sample predictions that **does not decay
  with n**, and whose correct home is a calibration layer, not a per-event shrink toward league.

A single `hr_shrink` fitted to outcomes absorbs both and will not generalise. **Which one is being
corrected must be declared before fitting.**

## 6. Guards (mandatory, and part of the pre-registration)

```
assert 0.0 <= hr_shrink <= 1.0
EPS = 1e-6
p_clipped = min(max(p, EPS), 1.0 - EPS)   # applied to b[e], p[e], L[e] BEFORE _odds()
```

- **`0 ≤ hr_shrink ≤ 1`.** Outside the unit interval the geometric interpolation **extrapolates**:
  `s > 1` overshoots past `L`, `s < 0` pushes away from it. `K/(n+K)` is automatically in range only
  when `K ≥ 0` and `n ≥ 0`; a negative, `NaN` or missing `n` breaks that silently. Assert, do not
  assume.
- **Clip before `_odds()`.** `_odds(p) = p/(1−p)` **divides by zero at `p = 1`** and returns `0` at
  `p = 0`. `_odds(L[e])` sits in a **denominator**, so `L[e] = 0` — a plausible value for a rare
  event with a short as-of window, e.g. `3B` early in a season — raises rather than degrades.
  **Exact boundary probabilities can produce division by zero, infinity or NaN depending on scalar
  versus array arithmetic and subsequent operations.** The required invariant is therefore stated as
  an invariant rather than as a predicted failure mode: **after clipping, every intermediate and
  every output must be finite**, and a non-finite value anywhere is a hard failure. Note that a
  non-finite `raw[e]` also contaminates `Σ raw`, so the blast radius is not confined to the
  offending event.
- Rare-event note: clipping at `EPS` is itself a floor on the model's resolution for events rarer
  than `EPS`. It is a guard against undefined arithmetic, not a substitute for a prior.

## 7. Data prerequisite — **BLOCKING. The data does not exist in this repo.**

Verified against the working tree, not assumed:

- `data/backfill/mlb/2026/pitcher_logs/*.txt` are 7-field: `date|IP|H|SO|BB|TBF|GS`. **No HR. No
  batted-ball events.**
- `data/mlb/team_gamelogs/*.json` are `[gamePk, date, AB, BB, SO]`, **team-level only**.
- `data/mlb/team_batting_asof/` is team aggregate.
- **There is no batter-level per-PA event data, no HR counts, and no BBE anywhere in the tree.**

E6 therefore requires a genuinely new data acquisition — per-PA or per-batted-ball outcomes for both
batter and pitcher — before it is runnable at all. This is a larger prerequisite than E1's
(which needed only team K-rate aggregates). **Until that data exists, E6 stays a recorded hypothesis
and nothing else.**

## 8. Untouched test set — required, and specified in advance

E1's confirmatory run was closed as **UNRECOVERABLE** because row IDs were never stored: the
backtest kept anonymous arrays and the data vintage mutated underneath it
(`docs/experiments/E1_confirmatory_closure.md`). E6 does not get to repeat that.

- **Forward holdout only.** No in-sample refit, no reusing any window touched while specifying
  `hr_shrink`.
- **Row IDs stored at generation time** (`batter_id|pitcher_id|gamePk|PA_index`), with the data
  vintage hash, so the population is reconstructible later.
- **Strict as-of**: `b`, `p`, `L` and every sample size use only games strictly before the date.
- The window used to answer §5.1–5.4 is **burned** — it can never serve as the test.

## 9. Adoption rule (pre-committed)

Adopt only if **all** hold on the untouched forward holdout:
1. HR-rate calibration slope moves toward 1.0 and lands in `[0.9, 1.1]`;
2. HR Brier / log-loss does not degrade;
3. the full event distribution sums to 1.0 within `1e-9` on every PA, and `P(HR)` reproduces `h`
   exactly (§4.1);
4. non-HR event calibration does not degrade — the anchored scheme pushes the normalisation residual
   onto them, and §4.1's stated cost has to be measured, not assumed;
5. no guard in §6 ever fires on real data (a firing guard means the inputs are wrong, not that the
   guard is generous).

Otherwise **retain H0**.

## 10. Status

**Not implemented anywhere.** `engine/` is unchanged. `hr_shrink` appears in no source file in this
repo — the code in §1 is external to it. The only log5 in the tree is E1's opponent-K adjustment
(`harness/e1_replay.py:32`, `harness/e1_anecdote_check.py:20`), which is frozen and unrelated to HR.
