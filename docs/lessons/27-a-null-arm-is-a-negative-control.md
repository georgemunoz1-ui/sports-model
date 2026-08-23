# 27. An arm that equals the arm it is meant to beat is a negative control, not coverage

2026-08-23. The board carried three rows for every WNBA game and one row for the NFL game, and the
summary called it a three-arm board. The owner read it correctly in one pass: WNBA's challenger
*was* the baseline — 0.567 in all four games, to the digit — and NFL had one arm.

The count was right. Three rows is three rows. What the count cannot see is that every paired
difference in those three rows is exactly zero, so the comparison cannot come out any way but tied.
A negative control is a useful thing to run. It is not challenger coverage, and reporting it as
coverage describes the shape of the table instead of its information content.

The same board proved the rule is per ESTIMAND and not per sport. On the winner estimand the MLB
challenger genuinely differs from the baseline. On the TOTAL estimand the baseline row carried the
challenger's projected total in all fifteen games, identical to the third decimal — so the same
sport is 3/3 on one estimand and a null challenger on the other. A sport-level verdict would have
said "MLB 3/3" and buried it.

The rule now: coverage is counted per sport AND per estimand, an arm byte-identical to the baseline
across every paired game is `BASELINE_EQUIVALENT_NULL`, and `COMPLETE_THREE_ARM` is refused while
any declared sport is short an arm or any arm is baseline-equivalent anywhere. The test is exact
equality, not a tolerance: one differing game is a real challenger, and a tolerance would let me
declare a working arm null to tidy up a table.

Corollary found while writing the check: the same baseline arm reported p_home 0.5252 in all fifteen
games while projecting the AWAY team to outscore the home team in six of them. Two unrelated numbers
were wearing one arm's name — a league-mean home probability and a score projection borrowed from
the challenger. Nothing in the pipeline compared an arm's winner probability with its own score
projection, because nothing was asked to.
