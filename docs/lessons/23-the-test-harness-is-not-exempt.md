# 23 — The test harness is not exempt

**Rule:** every discipline you apply to the code applies to the thing that tests the code. A fixture
whose result is never read, and a mutant that does not actually delete a rule, are both decoration —
and they are harder to spot than a decorative fixture because the suite reports green either way.

Lesson 21 says a fixture that cannot fail is decoration. This is the layer above it: a fixture that
*can* fail, but whose failure never reaches the verdict, is worse — it looks like coverage, it costs
real work to write, and it certifies nothing.

**Three instances, all found on 2026-08-22, all in my own work:**

1. **Fixtures below the verdict.** The ten falsification fixtures the owner specified for
   `starter_attribution` were appended below an existing `if fails: print(FAIL); return 1`. They ran
   only when everything else passed, appended their failures to a list nobody read again, and the
   function printed PASS unconditionally afterwards. Every mutant those ten fixtures guard
   *survived*, and the mutation report said so — which is the only reason it was caught. The verdict
   now sits below every fixture, and a fixture asserts that ordering by reading its own source.

2. **Mutants that do not delete the rule.** `out["x"] = None or (…)` is `out["x"] = (…)`. Adding a
   field to a hash payload leaves the covered data in the payload. Dropping `model_id` from a
   binding leaves model identity inside the `seed_input` string that is also in the payload. Each of
   these "survived", each looked like a decorative fixture, and each was actually a broken mutant.
   A mutant must be verified to have *applied and changed behaviour*, not just to have matched.

3. **The mutation harness patching itself.** The mutant list quotes the code it patches, so a naive
   `replace(old, new, 1)` rewrote the *list entry* instead of the function whenever the target was
   defined below the list. Two real mutants became no-ops and were reported as survivors.

**The generalisation:** when a check and the thing it checks live in one file, ask which one your
edit actually landed in. When a suite reports a survivor, the first hypothesis is a broken mutant,
the second is a decorative fixture, and only the third is a defect in the code — and you have to
distinguish them by running something, not by reading.

**Corollary on overlapping rules.** Several survivors turned out to be two gate rules covering for
each other: delete the omission check and the order check still catches the pop; delete the
coverage-verdict check and the set-equality check still catches the lie. That is not a weak fixture
and not a defect — it is redundancy. The fix is a fixture per rule that *only that rule* can
satisfy, so each is proven load-bearing on its own.

See: lesson 21, `harness/starter_attribution.py --mutants`, `harness/daily_baselines.py --mutants`,
docs/experiments/2026-08-22_STARTER_ATTRIBUTION_ACCEPTANCE_CONTRACT.json
