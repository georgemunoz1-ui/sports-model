# 29. A null quoted from memory is a fabricated number

2026-08-23. I reported that the WNBA champion's perfect AUC on four games "happens about 4% of the
time under a coin flip". The owner checked it. It is 25%.

The 4% was 1/24 — the probability of one specific ordering of four items. That is not the test and
was never the test. With one positive among four observations, a perfect AUC requires only that the
single positive outrank the three negatives, which under exchangeable random scores happens with
probability 1/C(4,1) = 25%. A separate question, the fair-coin probability of a 4–0 directional
record, is 1/16 = 6.25%. Three different numbers, three different statistics, one set of four games.

R1 says never invent a number: missing data is null plus a flag. I had been applying that to
results, prices and features, and not to *test statistics* — as though a null were a piece of
general knowledge rather than a quantity computed from this subgroup's own shape. It is not. A null
depends on n, on the split between positives and negatives, and on which statistic is being tested,
and none of those are things to recall. Quoting one from memory produced a claim six times more
impressive than the truth, in the direction that flattered the finding, which is the direction these
errors always go.

So the nulls are computed now: `evaluation_standard.auc_null_probability` and
`directional_null_probability`, exact, from the subgroup's own counts, with one mutant that
reproduces the 1/24 error and a fixture that kills it. A small-sample claim cites the computed null
or does not get made.

The general rule: **any number that would change a reader's confidence must be computed or cited,
not recalled** — and a p-value, a null, a threshold and a base rate are all such numbers.
