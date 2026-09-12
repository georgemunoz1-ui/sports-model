import argparse
import csv,json,pathlib,hashlib,datetime,urllib.request
import numpy as np
from model import half_score,forecast,probabilities,MODEL_ID
parser=argparse.ArgumentParser();parser.add_argument('--state',required=True);parser.add_argument('--identities',required=True);parser.add_argument('--out',required=True);args=parser.parse_args()
root=pathlib.Path(__file__).parent;out=pathlib.Path(args.out);out.mkdir(exist_ok=False)
state=json.load(open(args.state)); history=[]; defects=[];receipts=json.load(open(root/'sources/receipts.json'))
for old in state['updates']:
 eid=old['event_id'];f=root/'sources'/(eid+'.json')
 try:
  raw=f.read_bytes();c=json.loads(raw)['header']['competitions'][0]
  if not c['status']['type']['completed']:raise ValueError('NOT_FINAL')
  h=next(x for x in c['competitors'] if x['homeAway']=='home');a=next(x for x in c['competitors'] if x['homeAway']=='away')
  if str(h['id'])!=old['home_id'] or str(a['id'])!=old['away_id']:raise ValueError('IDENTITY_CONFLICT')
  if int(h['score'])!=old['home_score'] or int(a['score'])!=old['away_score']:raise ValueError('FROZEN_HISTORY_RESULT_CONFLICT')
  if c['date'][:10]>='2026-09-12':raise ValueError('TARGET_DATE_HISTORY_EXCLUDED')
  history.append({'event_id':eid,'date':c['date'],'neutral':old['neutral_site'],'home_first_half':half_score(h),'away_first_half':half_score(a),'source_sha256':hashlib.sha256(raw).hexdigest()})
 except Exception as e:defects.append({'event_id':eid,'error':str(e)})
url='https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates=20260912-20260912&groups=80&limit=1000'
raw=urllib.request.urlopen(url,timeout=40).read();(out/'schedule.json').write_bytes(raw)
cutoff=datetime.datetime.now(datetime.timezone.utc); hb=json.dumps(history,sort_keys=True).encode();(out/'history.json').write_bytes(hb);ih=hashlib.sha256(hb).hexdigest()
ids={}
for r in csv.DictReader(open(args.identities)):
 for side in ('home','away'):ids[r[side+'_id']]=r[side+'_division']
rows=[]
for e in json.loads(raw)['events']:
 c=e['competitions'][0];h=next(x for x in c['competitors'] if x['homeAway']=='home');a=next(x for x in c['competitors'] if x['homeAway']=='away');r={'event_id':e['id'],'home':h['team']['displayName'],'away':a['team']['displayName'],'start':c['date'],'status':'BLOCKED'};rows.append(r)
 try:
  if c['status']['type']['state']!='pre' or datetime.datetime.fromisoformat(c['date'].replace('Z','+00:00'))<=datetime.datetime.now(datetime.timezone.utc):raise ValueError('STARTED')
  if ids.get(h['id'])!='fbs' or ids.get(a['id'])!='fbs':raise ValueError('FCS_BRIDGE_UNSUPPORTED')
  totals=[x['home_first_half']+x['away_first_half'] for x in history if x['neutral']==c.get('neutralSite',False)]
  pred,draws=forecast(totals,e['id'],ih);r.update(status='BASELINE_ONLY_UNCALIBRATED',**pred)
  # Compact, exact simulation outcome histogram; seed regenerates ordered draws.
  unique,counts=np.unique(draws,return_counts=True);r['simulation_histogram']={str(int(k)):int(v) for k,v in zip(unique,counts)}
  if h['team']['abbreviation']=='WASH' and a['team']['abbreviation']=='USU':
   r['market_comparison']={'period':'FIRST_HALF','line':30.5,'price':.51,'source':'USER_SCREENSHOT','quote_time':'UNKNOWN','model':probabilities(totals,30.5),'simulation':probabilities(draws,30.5),'value_established':False}
 except ValueError as e:r['reason']=str(e)
result={'model_id':MODEL_ID,'cutoff':cutoff.isoformat(),'numpy_version':np.__version__,'history_hash':ih,'history_games':len(history),'defects':defects,'source_receipts':receipts,'canonical_prospective_eligible':False,'action_authority':'OFF','limitations':['League baseline, no matchup-specific offense/defense/pace/QB/weather adjustments','Small early-season sample; tails limited to historical support','Historical summaries retrieved now, source-effective timestamps unavailable','No out-of-sample calibration or predictive advantage established'],'rows':rows}
(out/'bundle.json').write_text(json.dumps(result,indent=2,allow_nan=False))
lines=['# September 12 CFB first-half total baseline','',f'Cutoff {result["cutoff"]}. Actual quarter scores; 100,000 empirical simulations/game. Uncalibrated league baseline, not a matchup-specific forecast. Action OFF.','', '| Away @ Home | First-half mean | Median | P10–P90 | Simulation mean | Status |','|---|---:|---:|---|---:|---|']
for r in rows:
 q=r.get('quantiles',{});lines.append(f'| {r["away"]} @ {r["home"]} | {r.get("mean","—")} | {q.get("p50","—")} | {q.get("p10","—")}–{q.get("p90","—")} | {r.get("sim_mean","—")} | {r.get("reason",r["status"])} |')
(out/'report.md').write_text('\n'.join(lines));(out/'manifest.json').write_text(json.dumps({f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in out.iterdir()},indent=2))
print(json.dumps({'history':len(history),'defects':defects,'forecasts':sum('mean'in r for r in rows),'washington':[r for r in rows if 'Washington Huskies'==r['home']]},indent=2))
