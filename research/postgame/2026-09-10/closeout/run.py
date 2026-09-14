import json, urllib.request, datetime, hashlib, pathlib, concurrent.futures, csv, math
P=pathlib.Path(__file__).parent
def fetch(item):
 league,sport,code=item
 url=f'https://site.api.espn.com/apis/site/v2/sports/{sport}/{code}/scoreboard?dates=20260910&limit=1000'+('&groups=80' if league=='cfb' else '')
 raw=urllib.request.urlopen(url,timeout=45).read(); json.loads(raw)
 (P/f'{league}.json').write_bytes(raw)
 return dict(league=league,url=url,retrieved_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),sha256=hashlib.sha256(raw).hexdigest())
items=[('mlb','baseball','mlb'),('nfl','football','nfl'),('cfb','football','college-football'),('nba','basketball','nba'),('wnba','basketball','wnba'),('nhl','hockey','nhl'),('mls','soccer','usa.1')]
receipts=list(concurrent.futures.ThreadPoolExecutor(7).map(fetch,items))
(P/'receipts.json').write_text(json.dumps(receipts,indent=2))
rows=[]
for league,_,_ in items:
 for e in json.loads((P/f'{league}.json').read_text())['events']:
  c=e['competitions'][0]; sides={x['homeAway']:x for x in c['competitors']}
  rows.append(dict(league=league,event_id=e['id'],name=e['name'],date=e['date'],final=e['status']['type']['completed'],home=sides['home']['team']['displayName'],away=sides['away']['team']['displayName'],home_score=int(sides['home']['score']),away_score=int(sides['away']['score']),halftime_total=sum(x['value'] for t in sides.values() for x in t.get('linescores',[]) if x.get('period',99)<=2) if league=='nfl' else None))
(P/'outcomes.json').write_text(json.dumps(rows,indent=2))
forecasts=list(csv.DictReader(open(P.parent/'forensic_0910/sources/mlb/diagnostic_card.csv')))
grades=[]
def score(p,y): return {'brier':(p-y)**2,'log_loss':-math.log(p if y else 1-p),'correct':int((p>.5)==bool(y))}
for f in forecasts:
 r=next(r for r in rows if r['league']=='mlb' and r['home']==f['home_team'] and r['away']==f['away_team']); assert r['final']
 y=int(r['home_score']>r['away_score']); margin=r['home_score']-r['away_score']; total=r['home_score']+r['away_score']
 g=dict(r,forecast_event_id=f['event_id'],model_p_home=float(f['analytic_p_home']),sim_p_home=float(f['stochastic_sim_p_home']),projected_home=float(f['projected_home_runs']),projected_away=float(f['projected_away_runs']),projected_total=float(f['projected_total']),projected_margin=float(f['projected_margin']))
 g.update(fixed=score(g['model_p_home'],y),gamma=score(g['sim_p_home'],y),total_abs_error=abs(total-g['projected_total']),margin_abs_error=abs(margin-g['projected_margin']))
 grades.append(g)
summary={a:{m:sum(g[a][m] for g in grades)/(1 if m=='correct' else len(grades)) for m in ['correct','brier','log_loss']} for a in ['fixed','gamma']}
summary.update(total_mae=sum(g['total_abs_error'] for g in grades)/len(grades),margin_mae=sum(g['margin_abs_error'] for g in grades)/len(grades))
n=json.loads((P.parent/'forensic_0910/nfl_forecast.json').read_text()); r=next(r for r in rows if r['event_id']==n['snapshot']['event_id']); assert r['final']
f=n['forecast']; y=int(r['home_score']>r['away_score'])
nfl=dict(r,model=score(f['model_p'],y),sim=score(f['sim_p'],y),margin_abs_error=abs(f['projected_margin']-(r['home_score']-r['away_score'])),total_abs_error=abs(f['projected_total']-r['home_score']-r['away_score']),first_half_under_24_5=r['halftime_total']<24.5)
result=dict(scope='DIAGNOSTIC_POSTGAME',slate_date='2026-09-10',mlb=grades,mlb_summary=summary,nfl=nfl,action_authority=False,canonical_prospective_eligibility=False)
(P/'grades.json').write_text(json.dumps(result,indent=2))
print(json.dumps(dict(outcomes=rows,mlb_summary=summary,nfl=nfl),indent=2))
