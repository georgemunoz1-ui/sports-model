# 25 — The direction was the whole effect

**2026-08-23. Found by running the owner's required directional audit on the only paired evidence
that exists.**

Thirty paired games, v1 (all-CAP baseline) against v2 (starter-informed), on the two dates where
both were registered on the same slate. The aggregate looks like a result:

| | record | Brier | log-loss |
|---|---|---|---|
| baseline | 16–14 | .249422 | .692060 |
| challenger | 18–12 | .240078 | .672942 |

Mean paired ΔBrier −0.0093, 70% of games improved, slate-clustered 95% interval [−0.0157, −0.0030]
excluding zero. Every headline points the same way.

Then split it by the direction the challenger moved:

| | n | challenger | baseline | mean ΔBrier |
|---|---|---|---|---|
| moved toward home | 19 | 13–6 | 9–10 | **−0.0212** |
| moved toward away | 11 | 5–6 | 7–4 | **+0.0112** |

**All of it is on the home side.** Where the challenger moved toward the away team it was *worse*
than the baseline — worse on Brier, worse on log-loss, and 5–6 against the baseline's 7–4. Across
these two nights home teams went 22–8.

So the honest statement is not "starter information improved the forecast by 3.7%". It is: *the
challenger acquired home-side exposure on two home-heavy nights, and on this sample that is
indistinguishable from having acquired starter information.* The interval excluding zero does not
help — a confound does not become a signal by being consistent.

The owner predicted this before the numbers existed, from four flips on one night. The audit was
required unconditionally, not "when something looks suspicious," and that is the only reason it ran:
the aggregate gave no hint. Nothing in ΔBrier, the improvement rate, or the confidence interval
would have prompted anyone to look.

**The rule:** a directional split is not a robustness check you run after a result looks strange. It
is part of the result. An aggregate that has not been split by the direction of the model's own
movement has not been evaluated — it has been summarised.

Two smaller things from the same build, both about intervals:

- The first slate bootstrap drew with `state % n` from a linear congruential generator. **The low
  bits of an LCG are not random.** With two slates it resampled the same night every single draw and
  returned a *zero-width interval* — the most confident possible output, produced by a generator
  that was not generating. A wrong interval is worse than no interval, because it is quotable.
- The baseline's calibration slope came back **negative** (−0.57). The tempting read is
  "anti-predictive". With AUC 0.509 the correct read is "no discrimination, and the sign is noise".
  It also means the promotion criterion *no material calibration regression* passes trivially here —
  almost anything beats a slope of −0.57 — so on this sample that criterion is evidence of nothing.
  **A criterion that cannot fail against a weak comparator is not a criterion.**
