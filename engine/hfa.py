"""Single source of truth for the home-field-advantage multiplier.

Why this file exists (HFA-SPLIT, resolved 2026-07-28). Two values were hard-coded across the
tree with nothing naming the difference, so V13's P(win) was not traceable to a formula:

    1.03    engine/v13_1.py, v13_1_pooled.py, v13_2_pitcher_index.py, card_2026_07_19.py
    1.005   harness/daily_card.py, engine/score_and_calibrate.py, calibrate.py, card_2026_07_20.py

This was NOT an accident and NOT a bug: it is a VERSION SPLIT. engine/park_compare.py is the
experiment that produced it, and card_2026_07_20.py's docstring records the adoption
("New data-derived parks + HFA 1.005"). The two families are the pre- and post-7/20 calibrations.

WHAT THE EVIDENCE ACTUALLY SAYS — re-run 2026-07-28, engine/park_compare.py, pooled 7/17+7/18:

    OLD parks (hand)  hfa 1.03    Brier 0.2413 | dir 17-9  | totals 10-15 (40%) | tot MAE 4.07
    NEW parks (data)  hfa 1.03    Brier 0.2404 | dir 16-10 | totals 11-14 (44%) | tot MAE 3.80
    NEW parks trimmed hfa 1.005   Brier 0.2408 | dir 16-10 | totals 12-13 (48%) | tot MAE 3.80

    n = 27.

**The HFA trim is not empirically supported.** On Brier, 1.005 is 0.0004 WORSE than 1.03 on the
same park set. The park change carries the improvement (MAE 4.07 -> 3.80); the HFA change does
not, and moves the wrong way on the headline metric. Totals hit rate rises 44% -> 48%, but that
is 1 game out of 25 at n=27. Under R4, none of this moves a verdict in either direction.

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
