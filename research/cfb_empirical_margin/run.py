"""New diagnostic snapshot; requires archived state and captures a current schedule."""
import csv
import json,hashlib,datetime,pathlib,urllib.request,argparse
import numpy as np
from cfb_empirical_margin import distribution,simulate,cover,MODEL_ID
p=argparse.ArgumentParser();p.add_argument('--identities',required=True);p.add_argument('--state',required=True);p.add_argument('--date',required=True);p.add_argument('--out',required=True);a=p.parse_args()
out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=False)
b=pathlib.Path(a.state).read_bytes();s=json.loads(b);ih=hashlib.sha256(b).hexdigest();(out/'state.json').write_bytes(b)
url=f'https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates={a.date.replace("-","")}-{a.date.replace("-","")}&groups=80&limit=1000'
raw=urllib.request.urlopen(url,timeout=40).read();(out/'schedule.json').write_bytes(raw)
identities={}
for row in csv.DictReader(open(a.identities)):
 for side in ('home','away'):
  key=row[side+'_id'];value=(row[side+'_team'],row[side+'_division'])
  if key in identities and identities[key]!=value:raise ValueError('IDENTITY_CONFLICT')
  identities[key]=value
(out/'identities.csv').write_bytes(pathlib.Path(a.identities).read_bytes())
now=datetime.datetime.now(datetime.timezone.utc);rows=[]
if datetime.datetime.fromisoformat(s['cutoff_utc'].replace('Z','+00:00')) > now:raise ValueError('FUTURE_STATE')
for e in json.loads(raw)['events']:
 c=e['competitions'][0]; h=next(t for t in c['competitors'] if t['homeAway']=='home');aw=next(t for t in c['competitors'] if t['homeAway']=='away');hn=h['team']['displayName'];an=aw['team']['displayName']
 r={'event_id':e['id'],'home':hn,'away':an,'status':'BLOCKED'};rows.append(r)
 try:
  if c['status']['type']['state']!='pre' or datetime.datetime.fromisoformat(c['date'].replace('Z','+00:00'))<=datetime.datetime.now(datetime.timezone.utc):raise ValueError('STARTED_OR_START_TIME_PASSED')
  hk,hd=identities[h['team']['id']];ak,ad=identities[aw['team']['id']]
  if hd!='fbs' or ad!='fbs':raise ValueError('FCS_BRIDGE_UNSUPPORTED')
  if hk not in s['team_elo'] or ak not in s['team_elo']:raise ValueError('MISSING_FBS_RATING')
  m,w,diag=distribution(s['updates'],s['team_elo'][hk],s['team_elo'][ak],c.get('neutralSite',False),s['parameters']['home_advantage'])
  draws,seed=simulate(m,w,e['id'],ih);data=draws.tobytes();(out/(e['id']+'.bin')).write_bytes(data)
  r.update(status='DIAGNOSTIC_UNCALIBRATED',model_margin=float(m@w),sim_margin=float(draws.mean()),seed=seed,n_sims=len(draws),draws_sha256=hashlib.sha256(data).hexdigest(),**diag)
  # Separate market overlay: odds never enter distribution or simulation.
  odds=next((o for o in c.get('odds',[]) if 'DraftKings' in o.get('provider',{}).get('name','')),None)
  if odds:
   home_fav=odds.get('homeTeamOdds',{}).get('favorite')
   if home_fav is None:raise ValueError('MARKET_ORIENTATION_UNRESOLVED')
   line=abs(float(odds['spread']))*(-1 if home_fav else 1)
   r.update(book='DraftKings via ESPN',home_line=line,model_cover=cover(m,line,w),sim_cover=cover(draws,line))
  else:r['market_status']='NO_QUOTE'
 except (ValueError,KeyError) as ex:r['reason']=str(ex)
result={'model_id':MODEL_ID,'generated_at_utc':now.isoformat(),'input_state_cutoff':s['cutoff_utc'],'input_hash':ih,'numpy_version':np.__version__,'source_url':url,'canonical_prospective_eligible':False,'action_authority':'OFF','rows':rows}
(out/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False))
lines=['# CFB diagnostic spread-cover comparison','',f'New run: {now.isoformat()}. State vintage: {s["cutoff_utc"]}.', '', 'Experimental empirical final-margin model, not the morning winner-only model. Same-venue historical sample only; no calibration or predictive improvement established. Current injury/QB/travel effects unresolved. Probabilities are conditional on this small historical distribution, not market-implied probabilities. Market quotes: DraftKings via ESPN; capture is not a certified closing line.','', '| Away @ Home | Home line | Model home cover | 100K home cover | Push (MC) | Status |','|---|---:|---:|---:|---:|---|']
for r in rows:
 q=r.get('sim_cover');v=r.get('model_cover');lines.append(f'| {r["away"]} @ {r["home"]} | {r.get("home_line","—")} | '+(f'{v["home_cover"]:.1%} | {q["home_cover"]:.1%} | {q["push"]:.1%}' if q else '— | — | —')+f' | {r.get("reason",r["status"])} |')
(out/'report.md').write_text('\n'.join(lines)+'\n')
manifest={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in out.iterdir() if f.is_file()};(out/'manifest.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps({'rows':len(rows),'forecasts':sum(r['status']=='DIAGNOSTIC_UNCALIBRATED' for r in rows),'quoted':sum('sim_cover' in r for r in rows),'out':str(out)}))
