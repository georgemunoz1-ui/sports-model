# Issue disposition — 2026-07-28

Every open issue, with what was actually done. **No engine value changed. No frozen artifact was
edited.** Phase-1 `7f827fd0…c12d2f` and the `KSIM-0727-U02` decision set `60fe448c…1279e2` both
re-verified unchanged.

## RESOLVED

| id | what was wrong | resolution |
|---|---|---|
| `ERBB-PLACEHOLDER-UNFLAGGED` | 8 pitcher-date rows carry `ER=0, BB=0` placeholders; the caveat lived in a README no code read | machine-readable `pitcher_logs/_placeholders.json`, all 8 verified against the logs; healthcheck **fails** on drift |
| `LOG-WIDTH-8-MISPARSE` | 8-field forward log was documented as *crashing* `sp_asof` | it was worse — `kprops._parse`'s `elif len(p)>=7` **silently** read ER as SO and BB as TBF. Exact-width dispatch everywhere; unknown widths now raise |
| `HFA-SPLIT` | `1.03` vs `1.005` with nothing naming the difference | `engine/hfa.py` single source of truth; both values imported, unchanged |
| E4 ID collision | two experiments both numbered E4 | favorite-fade keeps E4; lineup-aware → **E7**; `experiment_id_registry` added as authoritative |
| healthcheck log glob | `README_NOTE.txt` counted as a pitcher log and fed to the integrity scan | filtered via `_logfiles()` |
| healthcheck git label | printed "git working tree clean (2 dirty)" | relabelled to "git tree: N uncommitted path(s) (≤3 tolerated)" |
| lineage fragility | any engine edit broke a published KSIM hash with no legitimate path forward | **two separate verifiers** — A `verify_lineage.py` (FROZEN_LINEAGE, reads all inputs from commit `6d4a7c0`, exact hashes, **never** accepts a successor) and B `test_parse_equivalence.py` (SUCCESSOR_EQUIVALENCE, unrounded comparison against the frozen module, cannot alter A) |
| enrolment weakened provenance | the first fix let successor hashes satisfy the frozen check | reverted — enrolment removed from A entirely; see `LINEAGE-VERIFIER-SPLIT` |

### Three findings that came out of the fixes

**The HFA experiment supports neither value.** Full 2×2 factorial, `park_compare` **reseeded per
cell** (n=27): OLD/1.03 **0.2413**, OLD/1.005 **0.2415**, NEW/1.03 **0.2404**, NEW/1.005 **0.2402**.
Noise floor, same cell (NEW/1.005) at four seeds: 0.2402 / 0.2408 / 0.2396 / 0.2404 — **range
0.0012**. The HFA main effect is **+0.0002 under OLD parks and −0.0002 under NEW** — opposite signs,
about six times smaller than single-cell seed noise. The park effect on Brier (~0.0011) is itself
comparable to that noise and also not established. Only the park effect on **total MAE**
(4.07/4.06 → 3.79/3.79 at both HFA levels, ~27× the 0.01 seed range) clears the noise — and that is
a totals metric while totals are NOT_READY. **No claim is made that the park change "carries the
gain" on any sides metric** (the earlier wording here said exactly that, and is withdrawn). HFA
stays **UNRESOLVED**; `1.005` is current only because it is what the live path has run since 7/20.

**`park_compare` was not reproducible.** It seeded once at module scope and never reseeded, so each
cell drew from wherever the previous cell left the stream — results depended on how many cells ran
and in what order. Two runs of NEW/1.03 genuinely gave **0.2404 and 0.2412**. Any HFA number quoted
before 2026-07-28 is not reproducible. `run()` now reseeds per cell; repeated same-config calls agree
exactly.

**Placeholder fields are not read by the current `E[K]` calculation** — `ER`/`BB` are log fields 2
and 4, `kprops._parse` reads `p[3]=SO` and `p[5]=TBF` — **assuming SO and TBF on those rows are
accurate.** Field-level non-use does not establish that the row, or the collection process behind it,
is trustworthy: the same fetch that left ER/BB unpopulated produced SO and TBF, and nothing
independently confirms them. The earlier word "orthogonal" overstated this and is withdrawn. The only
consumer reading ER/BB is `daily_card.py::sp_asof`.

## DECLARED AND ENFORCED (cannot be fixed, but can no longer be misused)

**`results.csv` `close_*` columns hold OPENING prices.** Declared in
`results_close_columns_contamination.json`; healthcheck fails if the contaminated date range grows
without declaration.

**Scope correction:** the issue stated *"All MLB 2026 rows dated 2026-07-19 through 2026-07-25."*
Actual: only **2026-07-24 and 2026-07-25, 30 rows**, carry populated `close_*` values. The earlier
range was overstated.

Columns were **not** renamed — that would break `sports/schema.py`'s fixed `FIELDS` contract and the
dated harness scripts that wrote the rows. No code computes CLV from them today, so the exposure is
future misuse, which the guard addresses.

## BLOCKED — network, and honestly unresolvable this session

`WebFetch` returns **HTTP 403 for every host tried** — `statsapi.mlb.com`, ESPN's API,
plaintextsports.com, and even Wikipedia. This is a blanket perimeter block, not a per-site refusal.
`WebSearch` works but returns model-summarised snippets.

- **`results.csv` not backfilled with 7/26–7/27 finals** (the standing `dataset freshness` warning).
  A row needs `game_id` (gamePk), venue and scores. WebSearch returned 7 of ~15 games for 7/26, with
  no gamePks, no venues, and no way to confirm completeness. Writing that in would be asserting
  numbers rather than sourcing them (**R1**), into the dataset the backtests read. **Not done
  deliberately.**
- **No closing price captured.** Still blocks E3 and E4. Unchanged.

## OPEN BY DESIGN — these are not defects to fix

- **`KPROP-EDGE-ARTIFACT`** — open, revised: the residual-line correlation is mechanically
  contaminated and is not an admissible edge metric. Resolution needs outcomes, not a code change.
- **`KPROP-OPENER-2`** — `E[TBF]` may not read what a low line signals. Real, and unaffected by the
  withdrawal of the "3.5 implies ~15 TBF" inversion.
- **`KPROP-INFO-TEST`** — pre-registered, awaiting outcomes.
- **`E6`** — pre-registration only, and **data-blocked**: no batter-level per-PA events, no HR
  counts, no BBE exist in this tree.
- **`SELECTOR-VERSION-UNTAGGED`** — historical ledger rows stay untagged on purpose (**R6**); no
  policy tag is invented for them.
- **`KBOARD-*`, statsapi swap, WebFetch staleness, 7/25 SO source defect** — records of past events.
  Rewriting them would falsify the record.
- **Probable-starter staleness / openers unhandled** — real and unfixed. Needs a design decision, not
  a patch; every 7/27 row is tagged `starter_confirmed_pregame: false`.

## Verification

All suites green: `kprops` PASS · `ingest_kquote` PASS · **verifier A** FROZEN_LINEAGE VERIFIED
(published hashes describe commit `6d4a7c0` exactly) · **verifier B** SUCCESSOR_EQUIVALENCE PASS
(unrounded `E[K]` bit-identical on 23/23 rows; layout fixtures for widths 7/8/10; malformed widths
3/6/9/11 all raise) · `policy_gate` PASS · healthcheck **0 fail**.

## Classification correction — DQ tag freeze

The tags were frozen `2026-07-28T01:40:27Z`, with **11 of 12 games already underway** (SEA@TEX by
425 min; BOS@ATH by 27 seconds). They are therefore **OUTCOME-BLINDED, POST-START SENSITIVITY
DEFINITION**, not a pregame pre-registration. `outcomes_inspected_at_freeze: false` is retained as a
process attestation only. Subset B is exploratory sensitivity analysis; neither A nor B is
confirmatory for this slate, and `KPROP-INFO-TEST` carries the same label. A future untouched slate
is required. Recorded append-only in `KSIM-0727-U02_dq_tags_CLASSIFICATION.json`.
