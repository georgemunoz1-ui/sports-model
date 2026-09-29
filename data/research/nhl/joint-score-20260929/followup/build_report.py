from pathlib import Path
import json,datetime
P=Path(__file__).resolve().parent;E=json.loads((P/'evaluation.json').read_text());V=json.loads((P/'validation.json').read_text());R=json.loads((P/'prospective-ledger.json').read_text());A=json.loads((P/'personnel-acquisition.json').read_text());B=P.parent/'nhl-joint-20260929-v1';old=json.loads((B/'audit-2026.json').read_text())
lines=['# NHL joint-score recovery and validation — September 29, 2026','',f'Report written {datetime.datetime.now(datetime.timezone.utc).isoformat()}. Research only; action OFF, dose 0.0.','',
'## Completed and remaining','',
'| Request | Executed result | Remaining |','|---|---|---|',
'| Persistent evidence and registry | 15 immutable research entries; full original archive committed, 45/45 Git blob hashes verified | Library file service still returns transfer_failed; canonical main registry not changed |',
'| Exact settlement binding | Official DraftKings rule text reviewed: full-game OT included, one shootout goal added | Screenshot book/jurisdiction and applicable version not proven; book_rules_bound remains false |',
'| Bootstrap | 10,000 paired ISO-week resamples, 26 blocks; monthly sensitivity also executed | Retrospective, not prospective or market superiority |',
'| Log loss/reliability | Both home and away −1.5 metrics and fixed-decile reliability; diagnostic calibration fit | No calibration coefficients applied |',
'| Error slices | One-goal, REG/OT/SO, frozen-model favorite strength, predicted scoring environment; PBP marker audit below | No-marker is not certified absence; sparse slices cannot support decisions |',
'| Goalie/player increment | Separate acquisition contract, source paths, actual capture receipts, 10 input-gate tests | Official roster requests failed HTTP 403; no confirmed goalies, no fitted personnel effects |',
'| Prospective evaluation | Immutable evaluation protocol and 15-entry ledger; 14 entries timing eligible, zero grades | Collect finals and bound market snapshots; Montreal–Toronto excluded from strict prospective cohort |',
'| Arm separation | Initial winner-only model and joint-score challenger remain distinct | No promotion, blend or action authority |','',
'## Evidence identities','',
'- Registry commit: [1263fe95](https://github.com/georgemunoz1-ui/sports-model/commit/1263fe95d3fe766364aee295f66adf2dddab0e78).',
'- Frozen archive: [73288361](https://github.com/georgemunoz1-ui/sports-model/tree/732883617df2dea08d76ba627b6cea2510472732/data/research/nhl/joint-score-20260929/archive).',
'- Original archive SHA256: `f8978a1772d8a8030b3a27ce3f5b5ecbdd63c5081010a12156e78257ad5d978c`.',
'- Publication clock: September 29 23:05:22 UTC / 4:05:22 p.m. Pacific. Montreal–Toronto retained schedule start is 23:00 UTC; screenshot says 23:10. Conservative earlier schedule controls registration eligibility. Original local forecasts were frozen at 22:46 UTC; late persistence is not backdated.',
'- Research branch registration does not rewrite `canonical_registration:false` in old artifacts, change defaults or confer official clearance.',
f'- Verified {V["original_manifest_files_verified"]} original manifest files unchanged and 15/15 seed/draw replays exact. These are reproducibility checks, not predictive validation.','',
'## Same-population historical evaluation','',
'Training: 4,804 games, seasons 2021–2024. Bandwidth chosen on 1,312 season-2025 games. Audit: 1,312 season-2026 games. The 2026 cohort had previously been viewed in aggregate and is not untouched prospective evidence. Historical point-in-time source availability is unproven. Unconditional comparator uses training outcomes only; it is neither the old winner-only model nor the market.','',
'| Home −1.5 metric | Challenger | Unconditional training baseline | Difference |','|---|---:|---:|---:|']
m=E['home_minus1_5']
for title,a,b in [('Brier','brier','baseline_brier'),('Log loss','log_loss','baseline_log_loss')]:lines.append(f'| {title} | {m[a]:.8f} | {m[b]:.8f} | {m[a]-m[b]:+.8f} |')
for k in ['home_minus1_5_brier_bootstrap','home_minus1_5_log_loss_bootstrap','home_minus1_5_brier_month_sensitivity']:
 d=E[k];lines+=['',f'{k}: 95% percentile interval {d["ci95_percentile"]}; {d["blocks"]} {d["unit"]} blocks, 10,000 resamples, PCG64 seed 20260929. Negative challenger-minus-baseline is better.']
lines+=['',f'The original broader four-margin-category delta remains {old["paired_week_bootstrap"]["four_margin_vs_unconditional"]}; its interval crosses zero. The winner improvement interval also crosses zero. Secondary puck-line gains do not establish overall superiority.','',
f'Average home −1.5 prediction: {100*m["mean_p"]:.2f}%; observed: {100*m["observed"]:.2f}%. Fixed-decile ECE: {100*E["home_minus1_5_ece10"]:.2f} percentage points. Diagnostic calibration fit: intercept {E["calibration_fit_diagnostic_only"]["intercept"]:.3f}, slope {E["calibration_fit_diagnostic_only"]["slope"]:.3f}; NOT applied.','',
'| Probability bin | Games | Mean forecast | Observed cover |','|---|---:|---:|---:|']
for r in E['home_minus1_5_reliability']:
 if r['n']:lines.append(f'| {r["low"]:.0%}–{r["high"]:.0%} | {r["n"]} | {r["mean_p"]:.2%} | {r["observed"]:.2%} |')
lines+=['','## Error slices','', 'Home −1.5; descriptive slices. Outcome-conditioned slices cannot be interpreted as unconditional calibration. No retuning based on these post-screen results.','', '| Slice | N | Brier | ΔBrier | Log loss |','|---|---:|---:|---:|---:|']
for name,r in E['error_slices_home_minus1_5'].items():
 if 'brier'in r:lines.append(f'| {name} | {r["n"]} | {r["brier"]:.6f} | {r["delta_brier"]:+.6f} | {r["log_loss"]:.6f} |')
 else:lines.append(f'| {name} | {r["n"]} | NOT ESTABLISHED | — | — |')
if (P/'empty-net-labels.json').exists():
 l=json.loads((P/'empty-net-labels.json').read_text());lines+=['',f'PBP acquisition: {sum(x["status"]=="CAPTURED"for x in l)}/{len(l)} captured, {sum(x.get("complete",False)for x in l)} final-score and goal-census reconciled. Explicit Empty Net markers are from provider play fields. No explicit marker remains a proxy-negative group, not official absence certification. All raw source bytes are preserved; no forecast input changed.']
lines+=['','## Personnel and settlement boundaries','',f'Actual personnel acquisition: {sum(x["status"]=="CAPTURED"for x in A)}/{len(A)} sources captured (15 event summaries plus one injury feed); 24 official roster requests returned HTTP 403. All confirmed-goalie fields remain null. Data captured after original cutoff cannot be retroactively consumed. The acquisition-only contract requires source/effective/retrieval/review timestamps before cutoff, official source, player/team IDs, bytes hash and manual review. No effect estimated or forecast adjusted.','',
'[DraftKings official hockey rules](https://sportsbook.draftkings.com/es/help/sport-rules/hockey), document dated August 26, 2025, retrieved September 29, 2026: ordinary full-game markets include OT; NHL shootout settlement adds one goal to the winning side and total. Regulation/60-minute/period and Winning Margin props have different treatment. Interruption/void clauses need separate handling. This verifies conditional compatibility only; screenshots do not establish the exact operator/jurisdiction/rule version.','',
'## Prospective discipline','',
'14 frozen entries have durable publication before their retained scheduled start. Montreal–Toronto is archival-late. Zero entries are graded in this follow-up. Missing market quotes remain null. The protocol requires same-game paired comparisons, frozen versions, independently reconciled finals, idempotent grades and append-only corrections. No promotion conclusion before 500 timing-eligible grades over at least eight weeks and independent review; this minimum is not a pass. Personnel remains its own acquisition increment. Original winner-only and joint-score models remain separate.','',
'Next evidence: exact sportsbook/jurisdiction binding; official pre-cutoff goalie/player source confirmations; prospective final-source grades. Neither the Vancouver discrepancy nor this retrospective result changes model selection or action authority.','',
'`accepted_risk_release_override:false` · `official_release_eligible:false` · **Action OFF; dose 0.0.**']
(P/'REPORT.md').write_text('\n'.join(lines)+'\n')
print('REPORT.md written')
