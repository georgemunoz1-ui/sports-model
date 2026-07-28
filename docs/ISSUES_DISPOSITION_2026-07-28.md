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

### Two findings that came out of the fixes

**The HFA trim is not supported by its own experiment.** Re-running `engine/park_compare.py`
(n=27): OLD parks/1.03 Brier **0.2413**, NEW parks/1.03 **0.2404**, NEW parks/1.005 **0.2408**. On
Brier, `1.005` is **0.0004 worse** than `1.03` on the same park set. The *park* change carries the
improvement (total MAE 4.07 → 3.80); the HFA change does not. Totals 44%→48% is one game in 25.
Under R4 none of this moves a verdict. `1.005` is current because it is what the live path has run
since 7/20 — **not** because it won. Which value is right is **UNRESOLVED**.

**Placeholder contamination does not reach `E[K]`.** `ER`/`BB` are log fields 2 and 4;
`kprops._parse` reads `p[3]=SO` and `p[5]=TBF`. Real for ERA, orthogonal to the K projection. The
only consumer that reads ER/BB is `daily_card.py::sp_asof`.

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
