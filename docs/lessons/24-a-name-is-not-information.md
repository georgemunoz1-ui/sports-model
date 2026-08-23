# 24 — A name is not information

**2026-08-23. Found while implementing the owner's ALL_CAP_BASELINE class.**

Five committed cards had **zero** resolved starter slots — 08-17, 08-18, 08-19, 08-21, 08-22 —
and every one of them was written, read and graded through the same path as a fully-resolved card.
Nothing in the repo measured starter-slot resolution, so nothing could tell the difference.

The sharper version is worse than "some cards were all-CAP". **42 slots across the history printed
a real pitcher's name while feeding the model league-average stats.** `cards/2026-08-19_card.json`
shows *Jackson Jobe* and *AJ Smith-Shawver* and is 0/30 resolved. A reader seeing names concludes
the card knows who is pitching. It does not. The name came from the schedule; the stats came from
the CAP fallback because the registry missed.

> The name is cosmetic. The stats are the input. Classify on the input.

Three corollaries, each now a fixture and a mutant:

1. **Never classify from a flag.** Cards carry a row-level `capped` boolean, but it spans two slots
   and cannot distinguish all-CAP from partial. A card asserting `capped: false` while carrying CAP
   stats is classified all-CAP anyway. A card does not get to describe itself.
2. **Zero is a value.** The CAP signature is `{era 4.20, gs 0, k 22.0, bb 8.5}`. The first scan read
   it with `x or default`, and because `gs` is `0` — falsy — it reported **zero CAP slots across all
   35 cards**. A detector that finds nothing is indistinguishable from a clean repo. The only reason
   this was caught is that I already knew 8/22 was all-CAP and the scan disagreed with me.
3. **A label is not a class.** `v1` names a slot in the day's build sequence. On 08-18, 08-19 and
   08-21 it happens to be the all-CAP baseline; on 08-20 it is a card with 17 of 18 slots resolved.
   Anything pooled on the label pools whatever the label happened to mean that day.

The last one is the one that would have done real damage. It did not, this time: the four cohorts in
the owner's pooled 32-21 all turn out to be the same class, so the pooled figure survives its own
audit. That is luck, not design — and the *reason* it could be checked at all is that the class is
now computed rather than assumed.

**And a check that could not fail.** The new gate's class-drift rule looked proven: mutate it and the
suite went red. It went red because the drift fixture *also* changed the action authority, and the
authority rule caught it. The drift rule itself was never tested. Isolating it required a drift
between two classes that both map to `NONE`, where only the drift comparison can fire. Lesson 23 said
the harness is not exempt; this is the specific shape — **a fixture that exercises two rules at once
proves the stricter one and decorates the other.**
