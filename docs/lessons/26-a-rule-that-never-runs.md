# 26 — A rule that never runs

**2026-08-23. Found by auditing the owner's never-adapt list against what the healthcheck actually
executes.**

The owner named ten things that must never adapt automatically. Writing the list down took a minute.
Checking it took one script, and the script found a gap immediately:

> `same_book_devig_requirement` — the 2026-08-03 ruling that cross-book best-odds de-vig is INVALID
> for market probability — was on the never-adapt list with **no enforcing module running in the
> healthcheck**.

The guard was not missing. `freshness_gates.py` carries
`_BEST_ODDS_BASES = ("best_odds", "best_price", "best_available", "best_line", "cross_book")`
and a full passing selftest for it. The module had simply never been added to the healthcheck's
selftest loop. The rule was documented, implemented, tested — and never executed.

That is the shape worth remembering. **A rule that is present, correct, and never run is
indistinguishable from a rule that works.** It reviews well. It greps well. It appears in the design
document. It catches nothing.

The corroborating evidence was sitting in my own record and I had not connected it: three cross-book
de-vig bypasses have been caught this month, every one of them by hand. Not one was caught by the
guard built to catch them. I had read that as "the rule keeps getting tested by circumstance."
The correct reading was "the rule has never fired, and something is wrong with that."

**Three consequences, now enforced:**

1. A do-not-change list is worth nothing unless something checks it. `never_adapt_audit.py` binds
   each of the ten items to a module and **fails when that module does not appear in the
   healthcheck**. Existence on disk is not enough — the audit's own fixture proves it fails against
   a healthcheck that runs nothing.
2. The default is refusal. In the adaptive register, a quantity that is not listed cannot be updated
   at any speed, because an unregistered quantity is an unaudited one. Adding a knob requires
   declaring what layer it belongs to first.
3. The never-adapt list is not the slowest layer. It sits outside the mechanism. A formal model
   release cannot touch it either — a release is not an owner decision about governance, and a drift
   alarm that could relax a deadband would be a system widening its own permissions exactly when it
   is performing worst.

**And one from the same build, about tests rather than rules.** The drift monitor's "healthy window"
fixture — the one asserting that a good model trips no alarms — was not healthy. It assigned
probabilities *from* the outcomes, which gave it a calibration slope far above 1 and a directional
Brier gap that was pure confounding. It fired alarms on its own tail. A fixture that is supposed to
represent *nothing wrong* has to be built with more care than the ones representing failures,
because a broken failure-fixture fails loudly and a broken healthy-fixture just makes the alarms
look oversensitive until someone loosens them.
