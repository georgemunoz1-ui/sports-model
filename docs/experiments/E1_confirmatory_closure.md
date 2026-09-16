# E1 confirmatory replay — CLOSED AS UNRECOVERABLE (2026-07-24)

Per Taco red-gate: the pre-registered confirmatory required **exact identity** with the original
experiment-of-record — `set(E1 row_id) == set(baseline_1759 row_id)` and `len == 1,759`. That
identity cannot be met. This document records the search and the permanent closure.

## Search performed (all sources)
1. **Git history — all commits:** earliest commit is the harness bootstrap (55f91ea). No backtest
   script, no 1,759-row table, no population hash was ever committed.
2. **Git history — all blobs across every commit:** the only files ever mentioning "1759" are
   kprops.py (a header comment), progress.md, state.json, and two HTML reports — all reference the
   *number*, none contain the *row set*.
3. **Filesystem rowcount scan** (every csv/json for 1,755–1,765 data rows): the only match is my own
   `e1_score_pop.csv`. No pre-existing ~1,759-row artifact.
4. **Backup bundles** (`/tmp/sportsmodel_backup_2026-07-22.bundle`, `-07-23.bundle`): git bundles of
   this same repo, which never held the table.
5. **Session transcript:** located the actual backtest run (2026-07-18) and its code.

## What the transcript shows (why it is unrecoverable)
The backtest that produced "n=1759, MAE 1.92" did this:
```
for f in glob(pitcher_logs/*.txt):
    for date,ip,so,tbf,gs in parse(f):
        if gs and cst>=5:
            ek = krate*etbf
            proj.append(ek); act.append(so); naive.append(...)   # ANONYMOUS parallel arrays
        ...
print(f"Backtest starts (>=5 prior GS): n={n}  MAE projection {mae:.2f} ...")
```
- It appended to **anonymous parallel arrays** — **no pitcher_id, no gamePk, no date** was ever
  captured, even in memory. Only summary statistics were printed. There is nothing to recover.
- It applied **no date horizon** — it used every ≥5-prior-GS start in the logs **as they existed on
  2026-07-18**, before the 7/17–7/23 appends and before the Sale phantom-row repair.

## MAE-drift explanation (evidence-based; supersedes the earlier "2 Sale starts" claim)
The historical baseline MAE ≈ **1.92** was computed on the **7/18-vintage logs, no horizon, ~310
logs at that time**. My reconstruction's **1.849** used the **7/24-vintage logs (corrected + grown),
≤7/19 horizon**. These are **different populations on different data vintages** — the ~0.07 drift is
a population/vintage difference, NOT the removal of two ordinary Sale starts. Taco was correct that
the drift is too large for a 2-row edit.

## Conclusion
The exact 1,759 row IDs are **permanently unrecoverable** (never stored; underlying data vintage
mutated). The **original confirmatory replay is CLOSED as unrecoverable.** It cannot be re-run as a
confirmatory test.

## Doubleheader provenance (resolved factually, not manufactured)
The two 7/19 rows (Yamamoto 808967, Schlittler 693645, LAD@NYY DH) had ambiguous gamePk under
K-total matching. Resolved by fetching each pitcher's statsapi gamelog: **both = gamePk 823523**
(they started game 1 against each other). This replaces the earlier deterministic min-gamePk
placeholder with confirmed provenance.

## Status of the 1,757 run and the path to a real confirmatory
- The **1,757-row result is EXPLORATORY** (corrected-population sensitivity), not confirmatory. It
  supports the conservative NO-PROMOTE decision; it is **not** a confirmatory experiment result.
- The already-observed 1,757 rows **cannot be reused as confirmatory evidence** (they've been seen).
- **Any future confirmatory E1-R must be pre-registered against an untouched FORWARD holdout** —
  starts not yet played — with the frozen method/thresholds, scored once.
