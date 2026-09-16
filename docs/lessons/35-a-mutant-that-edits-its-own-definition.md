# 35 — A mutant that edits its own definition, and a suite that scores while broken

Two defects in the mutation harness itself, both found on 2026-08-25, both of the same family: the
test apparatus reporting success about work it did not do.

## The self-targeted mutant

`uncertainty_estimand` renamed `MIN_BLOCKS_FOR_DECISION` to `MIN_COMPUTABLE_CLUSTERS`. One mutant
still targeted the old name:

    ("the decision floor collapses, so k=2 sizes a bet",
     "MIN_BLOCKS_FOR_DECISION = 6", "MIN_BLOCKS_FOR_DECISION = 2"),

After the rename that string existed in exactly one place in the file — inside the mutant's own
definition. The runner does `src.replace(old, new, 1)` over the whole file, so it edited the MUTANTS
list, changed no behaviour, and the selftest passed. Reported: SURVIVED. Which reads as "this
fixture is decorative" and was in fact "this mutant tested nothing at all". The two look identical
in the output and have completely different remedies.

Fix: the runner splits the source at `MUTANTS = [` and refuses any pattern that does not occur in
the body above it, printing `SELF_TARGETED` rather than a verdict. It caught one of my own new
mutants on its very first run, in `module_manifest`, where a raw-string regex pattern did not match
the source literal it was aimed at.

## The suite that scored while broken

`module_manifest` printed `11/11 killed` while its own selftest was failing. Of course it did: a
mutant is "killed" when the selftest fails under mutation, and a selftest that already fails will
fail under every mutation. A broken fixture produces a perfect score.

Fix: the runner runs the unmutated selftest first and refuses to report anything if it does not
pass — `BASELINE_FAILING`, return False. Cheap, obvious in hindsight, and it had been absent from
every mutation suite in this repository since the first one.

## What both have in common

Neither defect is in the code under test. Both are in the machinery that reports on the code, and
both produce output that looks like evidence. Lesson 23 said the test harness is not exempt from
testing; this is the same rule one level further in — the *mutation* harness is not exempt either,
and its failure mode is specifically to emit numbers that read as reassurance.

Rule: any apparatus that reports a score must be able to report that it could not compute one.
`SELF_TARGETED` and `BASELINE_FAILING` are not error states, they are the honest outputs for the
cases where a score would be meaningless.
