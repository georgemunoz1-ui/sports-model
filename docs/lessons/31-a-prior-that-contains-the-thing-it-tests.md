# 31 — A prior that contains the event it is testing

I reported P = 0.000827 for the 8/21 MLB slate finishing 14 home wins in 15 games.

The number was wrong, and wrong in a way that flatters the finding. The home-win base rate I
plugged into the binomial was estimated over a window that *included 2026-08-21*. The very
cluster whose rarity I was testing had been folded into the parameter used to judge it. A single
extreme day pulls the base rate up, which makes the extreme day look less extreme, and the
p-value comes out too large — but the direction of the bias is not the point. The point is that
the quantity had no meaning at all: it was not the probability of anything under a prior that
existed before the observation.

Recomputed with a prior strictly earlier than 2026-08-21, p_home = 0.517160 over the pre-cutoff
canonical pool, the value is:

    P(X >= 14 | Bin(15, 0.517160)) = 0.000760

Both numbers are small. Nothing about the conclusion changed. That is exactly why the error was
easy to miss and worth writing down — a defect that does not move the verdict still corrupts the
record, and the next one may not be so harmless.

The owner also drew the sharper distinction I had blurred. Rarity is not contamination. A 14-1
day is an `EXTREME_INFLUENTIAL_CLUSTER` — it deserves an influence diagnostic, a leave-one-out
refit, and a note wherever it moves a number. It is `NOT_CONTAMINATED_BY_OUTCOME_ALONE`. Nothing
about the games was irregular; they were simply lopsided. Dropping data because the outcome was
surprising is outcome-conditioned deletion, and it biases every interval it touches.

Rule: any statistic that scores an observation must be computed from a parameter fitted strictly
before that observation. Write the cutoff into the call, not into a comment. And when a cluster
is extreme, quarantine its *influence*, never its existence.
