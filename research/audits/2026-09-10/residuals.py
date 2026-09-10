import json,statistics
from pathlib import Path
P=Path(__file__).parent
recon={(r['date'],r['event_id']):r for r in json.load(open(P/'starter_reconciliation.json'))};rows=[]
for day in (8,9):
 for r in json.load(open(P.parent/f'postgame_sep{day}/analysis.json'))['games']:
  r=dict(r,date=f'2026-09-{day:02d}');r['starter_match']=recon[(r['date'],r['event_id'])]['starter_match_state'];p=max(r['fixed_home_p'],1-r['fixed_home_p']);r['strength']='NEAR_EVEN' if p<.55 else 'MODEST' if p<.65 else 'STRONG' if p<.75 else 'EXTREME';r['team_run_mae']=(abs(r['projected_home']-r['actual_home'])+abs(r['projected_away']-r['actual_away']))/2;r['margin_bias']=(r['projected_home']-r['projected_away'])-(r['actual_home']-r['actual_away']);rows.append(r)
def score(a):
 return dict(n=len(a),**{k:statistics.mean(r[k] for r in a) for k in ['fixed_brier','mc_brier','fixed_log_loss','mc_log_loss','team_run_mae','total_error','margin_error','total_bias','margin_bias','delta_brier','delta_log_loss']},interval_coverage=None)
slices={'all':score(rows),'lineup_UNBOUND':score(rows),'bullpen_AVAILABILITY_UNBOUND':score(rows),'weather_roof_UNBOUND':score(rows),'schedule_rest_UNVERIFIED':score(rows)}
for key in ['starter_match','strength']:
 for v in sorted({r[key] for r in rows}):slices[key+':'+v]=score([r for r in rows if r[key]==v])
(P/'quality_residuals.json').write_text(json.dumps({'scope':'EXPLORATORY_POST_HOC_SLICES_NOT_PROMOTION_TEST','definitions':{'strength':'max(Fixed p,1-p); boundaries .55,.65,.75','interval_coverage':'UNAVAILABLE_ORIGINAL_CARD_DROPPED_QUANTILES','bound':'Starter ID match only, not complete information quality'},'slices':slices},indent=2)+'\n')
