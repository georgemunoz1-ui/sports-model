# Diagnostic score distribution retention

This change preserves MLB's existing RNG order, engine probability, projection,
and numerical output hash. The card adapter now retains losslessly compressed
ordered home/away score pairs in `simulation.score_distribution`, together with
full SHA-256, little-endian int32 encoding, shape, integer quantiles, empirical
PMF counts, means, standard deviations, and margin/total correlation. Constant
vectors produce null correlation, not a fabricated zero.

The native MLB engine already computed margin/total quantiles. The adapter was
discarding them. Its simulated score pairs are nine-inning proxies; ties get a
winner-only draw without extra runs. Full-game run-line/total settlement remains
unsupported. Existing falsely broad `SUPPORTED_AFTER_LINE_ATTACH` labels in the
MLB adapter are replaced by explicit diagnostic-proxy labels.

`models.common.score_distributions_v1.reprice` accepts only integer or half
lines and a matching declared score period. A negative spread means home
favorite; home covers when home margin plus line is positive. Outputs separate
win, loss and push frequencies, plus probabilities conditional on no push.
These are empirical estimates, not exact population probabilities or bookmaker
de-vigging. When all draws push, conditional probabilities are null. Quarter
Asian lines and MLB full-game scope are rejected. No execution or action
authority is enabled.

MLS extraction uses the retained 0–12 renormalized independent-Poisson grid
draws, not Dixon-Coles. uint8 draws are converted to signed int64 before margin
and total arithmetic. CFB's refreshed causal-Elo arm contains Bernoulli winner
draws only. It cannot identify margin, total, or score distributions. No invented
pace, total prior, correlation, or drive-scoring probabilities are added.

The September 12 extraction workflow writes append-only diagnostic children:
MLB is deterministically replayed from frozen input/config identities and must
match each parent output hash; its newly retained draws are labeled reproduced,
not original pregame draw receipts. MLS uses original retained score bytes and
checks their hashes. Neither operation rewrites its parent forecast or uses
new source data, outcomes, or market prices.

Eight contract tests exercise retention/hash replay, uint8 underflow, integer
and half lines, push conditioning, all-push degeneracy, invalid score vectors,
hash tampering, and unsupported settlement periods. Passing these tests is
engineering evidence, not predictive or settlement validation.
