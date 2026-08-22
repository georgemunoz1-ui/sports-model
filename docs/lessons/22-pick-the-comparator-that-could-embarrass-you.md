# 22 — Pick the comparator that could embarrass you

**Rule:** when defending a model's score, compare it against the strongest cheap alternative, not
the weakest one. Flat-50% is not a baseline; it is a floor almost nothing fails.

**Incident (2026-08-21/22).** The v2 cohort scored Brier .23062 on the 8/21 MLB slate. The owner
pointed out that home teams went 14-1 and an always-pick-home heuristic would have gone 14-1,
beating v2's 10-5 outright. I accepted the win-loss point and then wrote: *"Brier still beats
flat-50% (.23062 vs .25000) so the probabilities held some information."*

That defence chose its own opponent. The comparator that matters is the one a person could compute
with no model at all: the season home-win base rate. Over the 1919 finals strictly before that
slate it was .5242, and on the slate it scored Brier **.22959** and log loss **.65229** — better
than v2 on both, and better on win-loss. v2 cleared **no** baseline that night.

**What makes this a rule and not a scolding:** the weak comparator was not chosen dishonestly. It
was chosen because it was the one already in the report. A baseline that has to be remembered is a
baseline that gets remembered when it flatters. So the fix is mechanical — the frozen baseline set
is computed on the same games every settlement, automatically, and the expanding home prior is one
of its six required rows. A missing row is a gate failure.

**Also record the fragility.** The prior's Brier edge over v2 is .00103 on n=15 and reverses under
4 of 15 single-game flips. So the claim is NOT "the base rate forecasts better." It is the negative
one: v2 beat nothing here, and the number offered as evidence that it did was measured against the
wrong opponent. State the negative claim; it is the one the evidence supports.

See: docs/experiments/2026-08-22_DAILY_BASELINES_REPAIR.json, lesson 20 (check the base rate before
crediting the model), lesson 21 (a passing selftest is not a proven fixture).
