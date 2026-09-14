import csv, hashlib, json, math, statistics, zipfile
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
def sha(raw): return hashlib.sha256(raw).hexdigest()
def digest(obj): return sha(json.dumps(obj,sort_keys=True,separators=(',',':')).encode())
archive = ROOT / 'forecast.zip'
assert sha(archive.read_bytes()) == 'f37858c9f976c356e17c1bf7c47d87831faed84adf801869053897d17a48d26b'
with zipfile.ZipFile(archive) as z:
    frozen_bytes = z.read('diagnostic_card.json')
    card = json.loads(frozen_bytes)
source = (ROOT/'official_schedule.json').read_bytes()
receipt = json.loads((ROOT/'receipt.json').read_text())
assert sha(source) == receipt['sha256'] and len(source) == receipt['bytes']
games = [g for d in json.loads(source)['dates'] for g in d['games']]
by_id = {str(g['gamePk']):g for g in games}
assert len(by_id) == len(games) == len(card['forecasts']) == 15
assert set(by_id) == {r['event_id'] for r in card['forecasts']}
rows, arm_rows = [], []
for f in card['forecasts']:
    g=by_id[f['event_id']]
    assert g['officialDate'] == card['card_date'] == '2026-09-09'
    for side in ('home','away'): assert g['teams'][side]['team']['name'] == f[side+'_team']
    assert g['status']['abstractGameState'] == 'Final', 'Nonfinal result: do not grade'
    h,a=(g['teams'][s]['score'] for s in ('home','away'))
    assert h != a
    y=int(h>a); p=f['grading']['analytic_p_home']; q=f['grading']['stochastic_sim_p_home']
    assert all(math.isfinite(v) and 0<v<1 for v in (p,q))
    r={'event_id':f['event_id'],'away':f['away_team'],'home':f['home_team'],
       'actual_away':a,'actual_home':h,'projected_away':f['projected_away_runs'],
       'projected_home':f['projected_home_runs'],'fixed_home_p':p,'mc_home_p':q,
       'fixed_correct':int((p>0.5)==bool(y)), 'mc_correct':int((q>0.5)==bool(y)),
       'fixed_brier':(p-y)**2,'mc_brier':(q-y)**2,
       'fixed_log_loss':-math.log(p if y else 1-p),'mc_log_loss':-math.log(q if y else 1-q),
       'margin_error':abs(f['projected_margin']-(h-a)),
       'total_error':abs(f['projected_total']-(h+a)),
       'total_bias':f['projected_total']-(h+a),
       'data_quality':f['data_quality'],'divergence':f['analytic_sim_divergence'],
       'starter_fallback':any('STARTER_PRIOR_FALLBACK' in w for w in f['warnings'])}
    r['delta_brier']=r['mc_brier']-r['fixed_brier'];r['delta_log_loss']=r['mc_log_loss']-r['fixed_log_loss']
    rows.append(r)
    for arm,prob in [('fixed_poisson',p),('gamma_poisson_mc',q)]:
        item={'schema_version':'mlb_diagnostic_grade.v1','forecast_run_id':34330917567,
              'forecast_archive_sha256':sha(archive.read_bytes()),'forecast_card_sha256':sha(frozen_bytes),
              'frozen_row_output_hash':f['provenance']['output_hash'],'arm_id':arm,'event_id':f['event_id'],
              'home_win_probability':prob,'home_win_actual':y,'actual_home_runs':h,'actual_away_runs':a,
              'brier':(prob-y)**2,'log_loss':-math.log(prob if y else 1-prob),
              'result_source_sha256':sha(source),'result_observed_at_utc':receipt['retrieved_at_utc'],
              'graded_at_utc':datetime.now(timezone.utc).isoformat(),
              'evidence_scope':'DIAGNOSTIC_ONLY','canonical_prospective_eligible':False,
              'promotion_eligible':False,'action_authority':False,'quality':f['data_quality']}
        item['grade_id']=digest({k:v for k,v in item.items() if k!='graded_at_utc'})
        arm_rows.append(item)
def summary(pop):
    if not pop:return {'n':0}
    out={'n':len(pop)}
    for key in ('fixed_correct','mc_correct'):out[key]=sum(r[key] for r in pop)
    for key in ('fixed_brier','mc_brier','fixed_log_loss','mc_log_loss','delta_brier','delta_log_loss','margin_error','total_error','total_bias'):
        out[key]=statistics.mean(r[key] for r in pop)
    return out
report={'scope':'DIAGNOSTIC_ONLY','forecast_run_id':34330917567,'forecast_archive_sha256':sha(archive.read_bytes()),
        'result_source_sha256':sha(source),'all_games':summary(rows),
        'starter_bound':summary([r for r in rows if not r['starter_fallback']]),
        'starter_fallback':summary([r for r in rows if r['starter_fallback']]),
        'critical_divergence':summary([r for r in rows if r['divergence']=='CRITICAL']),
        'date_clusters':1,'confidence_interval':'NOT_ESTIMATED_SINGLE_DATE_CLUSTER',
        'market_comparison':'UNAVAILABLE_NO_FROZEN_MARKET','promotion_eligible':False,
        'games':rows}
for name,value in [('analysis.json',report),('diagnostic_arm_grades.json',arm_rows)]:
    dest=ROOT/name
    if dest.exists():raise FileExistsError(dest)
    dest.write_text(json.dumps(value,indent=2)+'\n')
with (ROOT/'game_grades.csv').open('x',newline='') as f:
    w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
lines=['# September 9 MLB postgame diagnostic','',
       'Frozen forecast run 34330917567. Official results matched by gamePk, date and home/away.',
       'No model rerun, forecast mutation, market settlement or promotion. One date cluster.',
       '', '| Game | Final (away–home) | Fixed P(home) | MC P(home) | Fixed correct | MC correct |',
       '|---|---:|---:|---:|---:|---:|']
for r in rows:lines.append(f"| {r['away']} @ {r['home']} | {r['actual_away']}–{r['actual_home']} | {r['fixed_home_p']:.1%} | {r['mc_home_p']:.1%} | {r['fixed_correct']} | {r['mc_correct']} |")
lines += ['', '## Summary', '', '```json',json.dumps({k:v for k,v in report.items() if k!='games'},indent=2),'```',
          '', 'The 30 arm rows are a separate diagnostic child record, not an append to the PR17 canonical ledger.',
          'Score errors refer to the frozen displayed run means; they are not run-line/total market settlement.',
          'No raw simulation quantile arrays are present in this source ZIP, so interval coverage is not computed.']
(ROOT/'report.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='games'},indent=2))
