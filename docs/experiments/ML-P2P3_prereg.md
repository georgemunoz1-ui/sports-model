# ML-P2 baselines + ML-P3 ablations · PRE-REGISTRATION

**Status: PRE-REGISTERED, committed BEFORE any run.** Every population, split, model spec, metric
and decision rule below is fixed blind. Changing any of them after this commit re-labels the
affected run exploratory. Owner authorization: "phase 2 and 3 authorized", 2026-07-28.

## Population

The **1,345 evaluation-eligible rows** of the P1B firewall dataset, vintage
`431e689cf629e3952354f417de4825caee4907f5ca490a376a940a75ae40d203` (pinned; a different vintage
voids this pre-registration). Eligibility was fixed by the firewall before this document existed:
starter resolved post-hoc via starters.csv, both SP features present (tbf≥10 strictly before
slate), strict `date < slate_date` features throughout. This population is **smaller than the
n=1461 verdict population** because the firewall excludes low-data starters that the old enrich
kept with null fields — a deliberate difference, recorded here, not a surprise later.

## Splits

- **Burn-in:** all rows before 2026-05-04 — train-only, never tested.
- **Development test weeks (8):** Mondays 05-04, 05-11, 05-18, 05-25, 06-01, 06-08, 06-15, 06-22;
  each week tests [Mon..Sun], training on ALL eligible rows strictly before that Monday
  (expanding window).
- **SEALED HOLDOUT: 2026-06-29 through 2026-07-19 (3 weeks).** Not scored, not inspected, not
  summarized in P2. It opens exactly once, only after a P3 candidate is frozen in writing, and
  whatever it says is final for that candidate (R7/R4 discipline). If no candidate is frozen, it
  stays sealed.

## Models (P2)

| id | spec |
|---|---|
| (a) `v13_p2eval` | The production V13 MC formula (identical arithmetic to the verdict scorer: same `rs`, `bipf`, gamma-Poisson, tie-break; HFA is an explicit parameter, **1.005 for P2**), run on firewall features. RNG: `per_row_reset` — `default_rng(7_000_000 + global_row_index)` so every row's number is split-independent and reproducible. n=4000 sims/row. Registered identity `ml.v13_1.p2eval.hfa_param.n4000.per_row_reset`. No fitting, so "training" does not apply; it is evaluated on test weeks only. |
| (b) `const_0500` | p(home)=0.500 always. |
| (c) `home_base_rate` | p(home)=home-win rate of the training window. |
| (d) `logistic_2f` | `logit(p) = β0 + β1·((h_rf−h_ra)−(a_rf−a_ra)) + β2·(shrunk(a_era,a_gs)−shrunk(h_era,h_gs))`, `shrunk(e,g)=w·e+(1−w)·4.20, w=g/(g+8)` — the exact spec frozen in the Phase-1 deliverable. Fit by Newton's method on the training window only, refit per split. |

**Market benchmark:** honest status — the only stored ML prices are the 7/24–7/25 openings in
`close_*`, which do not overlap the eligible population (SP resolution ends 7/19). **The de-vigged
market benchmark is therefore UNAVAILABLE for this evaluation and is reported as such, not
approximated.** The standing reference stays the historical n=73 study (~0.238 Brier) as context
only, never as a scored column.

## Metrics (per split and pooled over dev weeks)

n · Brier · log loss · calibration intercept & slope (logistic recalibration of y on logit(p),
fit on the pooled dev test rows) · reliability by decile (pooled) · accuracy (secondary).

## Decision rule (frozen)

A model is a **P3 candidate input** only if, pooled over the 8 dev weeks, it (i) beats (b) AND (c)
on Brier, and (ii) is not worse than (a). **Nothing promotes regardless of result** — ML stays
NO_PROMOTE; this phase produces measurements and a possible frozen candidate for the holdout,
nothing else. No model is selected from one week or from in-sample fit.

## P3 — ablations (one active at a time)

Framework: change exactly one thing relative to (a); score on the SAME dev splits; compare pooled
Brier/log loss/calibration; the complement of any improved slice is always reported
(narrative-repair guard). Pre-registered queue, in order:

- **A1 — HFA level.** (a) with HFA=1.03 instead of 1.005. Everything else identical, including
  RNG stream, so the difference is the multiplier alone, paired per row. Decision statistic:
  ΔBrier pooled, with the park_compare noise floor (±0.0012 at n=27; expected far tighter at
  n≈700 paired rows) as the reference scale. This finally addresses HFA-SPLIT with a real sample.
- **A2 — per-pitcher IP prior.** Replace the global IP~N(5.4,1.3) with
  N(mean_IP_asof, 1.3) per starter, mean from strictly-before starts, floor 2.0 / cap 8.0,
  shrunk to 5.4 with w=gs/(gs+6). Tests the opener/short-start failure mode (KPROP-OPENER-2,
  D-B family). Runs ONLY after A1 completes and closes.
- Later (pre-registered as ideas only, no specs frozen): bullpen availability, ERBB repair
  (moot on this population — placeholders postdate it).

**Candidate freeze rule:** a candidate = (a) plus any subset of CLOSED, individually-improving
ablations, declared in writing with its exact config hash BEFORE the holdout opens. One holdout
opening, total.

## Prohibitions carried forward

No market inputs to any model. No formula changes to production paths. No gate movement, no
ledger entries, no promotion, $0. Every result artifact stamps model identity, HFA parameter,
dataset vintage, and split id.
