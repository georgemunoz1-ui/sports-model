# 32 — A gate calibrated from its own input cannot fail

The owner asked for executable hold thresholds: not "a plausible level band" but the actual numbers,
by sport x market x price band, with their derivation.

My first implementation derived each stratum's band from the overrounds being judged. Observed
min/max, widened by an allowance factor, then check whether the board sits inside. It does. It
always does. A band fitted to a set of numbers contains those numbers by construction, and the
dispersion ceiling — observed spread times 1.75 — is by construction larger than the observed
spread. The gate could not reject anything it was ever shown.

It looked like a gate. It ran, it produced a verdict, the verdict was PASS, and the PASS meant
nothing at all. This is lesson 21's failure mode moved up a level: not a fixture that cannot fail,
but a *rule* that cannot fail.

The fix is that the stratum is looked up in a registered table and is never derived from the board
under test. `market_homogeneity()` calls `lookup_stratum()`; if no stratum is registered it refuses,
because an uncalibrated stratum is a refusal and never a wave-through. A mutant that restores the
self-calibration is now killed by a fixture.

Two things this surfaced that are worth keeping:

**The registered table is still calibrated from one board.** So judging *that* board against *this*
table is circular at the policy level, one step removed. It is labelled
`CALIBRATION_SOURCE_SELF_REFERENTIAL`, and the 8/24 board may not cite the level test as independent
evidence. The table becomes evidence when a second, independent capture passes through it. A
circularity you have labelled is survivable; one you have not is not.

**Refusing correctly changed an answer I liked.** Under the old hand-set band the WNBA board passed.
Under the derived policy no WNBA stratum can be calibrated at all — its two moneylines sit in
different price bands, so each band holds one quote. The old PASS was not a validation; it was the
invented band admitting whatever it met. Losing that PASS is the policy working.

Rule: a threshold may never be derived from the observation it will judge. If the only data
available is the data under test, the honest output is UNCALIBRATED, and UNCALIBRATED refuses.
