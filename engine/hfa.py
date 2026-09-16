"""Single source of truth for the home-field-advantage multiplier.

Why this file exists (HFA-SPLIT, resolved 2026-07-28). Two values were hard-coded across the
tree with nothing naming the difference, so V13's P(win) was not traceable to a formula:

    1.03    engine/v13_1.py, v13_1_pooled.py, v13_2_pitcher_index.py, card_2026_07_19.py
    1.005   harness/daily_card.py, engine/score_and_calibrate.py, calibrate.py, card_2026_07_20.py

This was NOT an accident and NOT a bug: it is a VERSION SPLIT. engine/park_compare.py is the
experiment that produced it, and card_2026_07_20.py's docstring records the adoption
("New data-derived parks + HFA 1.005"). The two families are the pre- and post-7/20 calibrations.

WHAT THE EVIDENCE ACTUALLY SAYS — full 2x2 factorial, engine/park_compare.py RESEEDED per cell
(seed 1319), pooled 7/17+7/18, n = 27:

    parks   hfa      Brier    dir     totals        tot MAE
    OLD     1.03     0.2413   17-9    10-15 (40%)   4.07
    OLD     1.005    0.2415   16-10    9-16 (36%)   4.06
    NEW     1.03     0.2404   16-10   11-14 (44%)   3.79
    NEW     1.005    0.2402   16-10   12-13 (48%)   3.79

MONTE CARLO NOISE FLOOR — the SAME cell (NEW/1.005) at four seeds:

    0.2402, 0.2408, 0.2396, 0.2404   ->  range 0.0012 on Brier, 3.78-3.79 on total MAE

**The HFA value is UNRESOLVED. This experiment supports NEITHER 1.03 nor 1.005.**
The HFA main effect is +0.0002 under OLD parks and -0.0002 under NEW parks -- opposite signs, and
roughly SIX TIMES SMALLER than the 0.0012 seed-to-seed range of a single cell. It is noise.

On Brier the park effect (~0.0011) is itself comparable to that 0.0012 noise range and is likewise
not established. The one effect that clears the noise is the park effect on TOTAL MAE: 4.07/4.06 ->
3.79/3.79, consistent at both HFA levels and ~27x the 0.01 seed range. But that is a totals metric,
totals are NOT_READY, and it says nothing about HFA. No claim is made here that the park change
"carries the gain" on any sides metric.

Under R4, n=27 moves no verdict in any direction.

REPRODUCIBILITY NOTE: until 2026-07-28 park_compare seeded once at module scope and never reseeded,
so each cell drew from wherever the previous cell left the stream and results depended on how many
cells were run and in what order. Two runs of the same configuration genuinely disagreed
(NEW/1.03 gave 0.2404 and 0.2412). Any HFA number quoted before that date is not reproducible.

So CURRENT is 1.005 because that is what the live path has been running since 7/20 and changing
it now would be an unregistered formula change (R3) -- NOT because it was shown to be better.
Whether 1.005 or 1.03 is closer to the truth is UNRESOLVED and needs a pre-registered test on a
real sample, not n=27.

Live paths import CURRENT. The v13_1 lineage imports V13_1_LEGACY, so the split is now explicit
and named rather than two unexplained literals. Dated one-off cards (card_2026_07_19.py,
card_2026_07_20.py) keep their literals: they are records of what was run on those dates and
rewriting them would falsify the record (R6).
"""

from __future__ import annotations

#: Live value, used by the current card path. Provenance above: adopted 7/20 alongside the
#: data-derived park factors, NOT independently validated.
CURRENT = 1.005

#: The v13_1 lineage's value. Kept as a named constant so the divergence is legible in code.
V13_1_LEGACY = 1.03

#: Values considered live-or-legacy. healthcheck scans for stray literals outside this set.
KNOWN = (CURRENT, V13_1_LEGACY)

STATUS = "UNRESOLVED — neither value is empirically supported over the other (n=27, Brier delta 0.0004)"
