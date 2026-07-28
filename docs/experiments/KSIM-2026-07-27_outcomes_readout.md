# KSIM-2026-07-27 — outcomes readout · **EXPLORATORY, single-source, POST-START-tagged slate**

Source: operator paste, sha256 `858d6262…3f10`, **ONE SOURCE** (extract:
`data/mlb/box/2026-07-27_extract.json`). Frozen artifacts untouched; nothing here enters a ledger
or moves the gate (0/100 under dp-2026-07-27). Under **R4, no verdict moves on anything below.**

## Slate facts that changed the picture

- **CLE@CIN postponed** (to 7/28): Cecconi and Burns are NO_CONTEST. 21 of 23 cohort rows resolved.
- **The flagged opener risk materialized.** Alvarez (tagged `opener_workload_risk=HIGH` in the
  pre-outcome DQ tags) **did not start** — Eddy Yean opened, Alvarez threw 4.1 bulk innings.
  Imai (also HIGH) started and lasted **0.2 IP** (4 BB). Two of the four HIGH-risk arms failed in
  exactly the tagged mode. `KPROP-OPENER-2` gains two instances. n small; direction only.

## Model vs market on actual strikeouts (n=21 pitched)

| | MAE all 21 | MAE starters only (20) | closer count |
|---|---|---|---|
| model E[K] | 1.381 | **1.357** | 11 |
| market-implied λ | **1.352** | 1.393 | 10 |

**A tie, read either way.** The market edges the model with Alvarez included; drop the one arm that
didn't start and the model edges the market. Nothing here separates them at n=21 — which is itself
notable, since the model runs on logs a median of 18 days stale. Exploratory; this is the
descriptive first pass of `KPROP-INFO-TEST`, not the pre-registered orthogonalisation test, which
still requires a future untouched slate.

## The four shadow signals (EVIDENCE_DEFICIENT_SHADOW — descriptive only)

| pitcher | signal | actual K | result |
|---|---|---|---|
| David Peterson | OVER 3.5 MGM +120 | 3 | **LOSS** |
| Tatsuya Imai | UNDER 6.5 FD −150 | 1 | **WIN** |
| Jack Perkins | OVER 4.5 MGM −120 | 4 | **LOSS** |
| Andrew Alvarez | OVER 3.5 BR +100 | 3 | **BOOK-RULE DEPENDENT** — LOSS if action, VOID if must-start (did not start); BetRivers' rule is not known to this repo, so neither branch is asserted (R1) |

Descriptive record **1-2 (+1 open)**; notional P/L −1.33u if the Alvarez branch is action, −0.33u
if void ($0 real). **All three OVERs lost; the lone UNDER won** — direction-consistent with D-B
(the `etbf` prior dragging low-GS arms toward full-start workloads), and on the fired rows the
market was closer to the outcome on 3 of 4. n=4. Nothing moves.

## Counterfactual replay scoring (sides/totals were display-only; this is bookkeeping, not a record)

The post-slate replay's sides went **4-7** against results (market picks went 6-5); its totals
leans went **2-9**. Its two largest disagreements with the market — TOR@WSH (+12.0) and PHI@MIA
(+11.9) — **both lost**, and the biggest totals leans (TOR@WSH 12.7 vs 9.5–10.0, BOS@ATH 12.3 vs
9.5) both went under by wide margins. These numbers cannot enter any forward-tracking ledger: the
replay was generated after the games. They are recorded to prevent the opposite temptation — quietly
forgetting a bad counterfactual. Sides remain NO_PROMOTE; totals remain NOT_READY; nothing here is
evidence in either direction at n=11.

## Data-quality events logged

- SEA@TEX Team Pitching aggregate SO=9 vs individual sum 10 and opposing-batter sum 10 → aggregate
  overruled 2-of-3 (same defect class as 7/25 LAD@NYM).
- Zac Thornton (excluded pre-freeze, GS=3) started and threw 6.1 IP / 5 SO. The exclusion rule cost
  nothing here — he was never priced by us — but the GS floor's behaviour on rising arms is worth a
  look on a future slate.
- `results.csv` still not backfilled: the paste carries no gamePks or venues (R1; same blocker as
  7/26). Dataset-freshness warning stands.
