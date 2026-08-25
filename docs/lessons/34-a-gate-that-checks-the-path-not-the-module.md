# 34 — "The selftest passes" is true of any module at that path

While implementing the readiness standard I created `harness/acquisition_ladder.py` with a
`cat > ... <<EOF`. A module of that name already existed — the 2026-08-22 acquisition state machine,
with its own docstring, its own contract and its own fixtures. I destroyed it.

Every gate stayed green.

The healthcheck sweeps a list of module names and asserts that `python3 harness/<name>.py
--selftest` exits zero. That assertion is true of *any* module sitting at that path with a passing
selftest. It does not check that the module is still the module it was. A replacement that happens
to be well-tested is indistinguishable from the original, and mine was: 11/11 mutants on a file that
had just deleted someone else's work.

I only noticed because `grep -n acquisition_ladder harness/healthcheck.py` returned two lines, and I
stopped to ask why a module appeared twice in one list.

The fix is a two-part one:

**Restore and rename.** `git checkout HEAD -- harness/acquisition_ladder.py` brought the original
back untouched, and the new module went to `harness/route_ladder_v1.py`. The two are genuinely
different things — one is a state machine over acquisition outcomes, the other is a seven-rung route
ladder with authority tiers — and they should never have shared a name.

**Make the collision visible.** Every module's selftest now prints a banner naming itself, and the
healthcheck asserts that the banner names the file it came from. A module overwritten by a different
module fails that check immediately, because the replacement announces its own name. It is the
cheapest possible tell and it costs one string comparison.

The general rule: a gate that verifies a *property* of whatever occupies a path has not verified the
*identity* of what occupies it. Registered-artifact immutability already worked this way for data —
hashes are checked against a registry, not merely "the file parses". Code had no equivalent. Now it
does, at least for the one property that matters most: this file is still the file it claims to be.

And the smaller lesson, which is the one I keep relearning: `cat >` is `rm` with extra steps. Check
whether the path exists before writing to it, especially when the name is a natural one that someone
else would also have chosen.
