# Navy at FAU — whole-point spread research diagnostic

User-authorized opt-in extension: integer spreads now return separate cover/loss/push probabilities under the existing rounded-normal approximation. It does not change the frozen forecast, distribution, or earlier utility's default gate. This is mathematical settlement extraction, not validation of football key-number probabilities. Full-game totals and production/action use remain unsupported.

Frozen model cfb.team_context_heads.v0_1.research, cutoff September12 19:09:15Z (12:09 PDT); ratings vintage11:02:55Z. Child generated21:55:52Z. Event401862703, Navy away, FAU home, scheduled23:30Z. User screenshot: Navy-4(-112), FAU+4(-108), total59.5, NavyML-198/FAU+164; quote capture time unknown. No live quote refresh implied.

| Target | Model | 100K simulation |
|---|---:|---:|
| Navy margin | +2.47963 | +2.51687 |
| Navy -4 cover |45.95462%|46.026%|
| FAU +4 cover |52.04570%|52.018%|
| Push (Navy by exactly4) |1.99968%|1.956%|
| Navy cover conditional on no push |46.89232%|46.94423%|
| FAU cover conditional on no push |53.10768%|53.05577%|

Counts:46026 Navy covers,52018 FAU covers,1956 pushes; sum100000. Never redistribute pushes and call it no-vig. Conditional probabilities refer only to non-push outcomes. For integer threshold k, rounded-normal push mass is CDF(k+.5)-CDF(k-.5); half-point results retain the existing CDF threshold.

Navy-oriented P10/P25/P50/P75/P90 margins:-23/-11/+2/+16/+28. Large uncertainty is inherited and uncalibrated. The fitted +13.97038 home intercept is still under audit. Model-market margin gap is1.52037 points, not established predictive advantage.

First-half-only estimates: Navy16.84246, FAU13.41388, total30.25634; simulated total30.22010, P10/P90=21/39. Navy has no retained team halftime observation in this fitted dataset, FAU does; Navy's own effect falls back to the prior while opponent effects remain. This is not a full-game score forecast and must not be doubled into total59.5 probabilities.

Starting QB/game-day availability, weather/travel and roster impacts were unresolved in the parent. The later data intake did not alter these means. No new current-roster forecast or calibration claim.

17 tests pass, including8 new push tests and9 existing tests. Both original seeded100K margin and halftime arrays reproduce to full SHA-256; margin histogram matches exactly. Parent bytes unchanged. Repository-wide CI not claimed. ActionOFF; canonical prospective eligibilityfalse.

Run from root:
`python research/cfb_margin_repricing/navy_fau/run.py research/cfb_context_fix/results_02/bundle.json /tmp/navy_fau_new_result.json`
Output creation is exclusive. Source NumPy version must match parent for exact replay.
