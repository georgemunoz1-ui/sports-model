"""MLS-only source scope review: provider code 13846 is bound to exact league metadata.
No generic season-code relaxation or model/default change. Original refusal retained.
"""
from __future__ import annotations
import hashlib,json,os,subprocess,sys,traceback,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from scripts.recovery_capture import save_json,utc
from scripts.verify_nfl_weekly_sources import manifest
OUT=ROOT/'run-output/mls-reviewed';OUT.mkdir(parents=True,exist_ok=False)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def extract(p,d):
 d.mkdir(parents=True,exist_ok=False)
 with zipfile.ZipFile(p) as z:
  assert all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in z.namelist());z.extractall(d)
def load(p):return json.loads(p.read_text())
def run(args,label,env=None):
 t=utc();p=subprocess.run([sys.executable,*args],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 (OUT/(label+'.log')).write_text(p.stdout);save_json(OUT/(label+'.receipt.json'),{'command':[sys.executable,*args],'started':t,'ended':utc(),'returncode':p.returncode,'log_sha256':sha(OUT/(label+'.log'))});print(label,p.returncode,p.stdout[-800:],flush=True)
 if p.returncode:raise ValueError(label+':FAILED')
r={'schema':'mls.source_scoped_current_run.v1','date':'2026-10-25','run_id':os.environ.get('GITHUB_RUN_ID'),'execution_commit':os.environ.get('GITHUB_SHA'),'source_pin':'527409a9aa48b554a03aecd01b5b87ac66bc9baa','started_at_utc':utc(),'forecasts':[],'blockers':[],'action_authority':False}
try:
 arc=OUT/'scope-original.zip'
 with arc.open('xb') as f:subprocess.run(['gh','api','repos/georgemunoz1-ui/sports-model/actions/artifacts/12596016633/zip'],stdout=f,check=True)
 assert sha(arc)=='5aa4c9149f47c8662954b7c9d93ab65f637fa2a935049b036905decd9f6d05dd'
 outer=OUT/'scope-outer';extract(arc,outer);source=OUT/'scope';extract(outer/'scope-evidence.zip',source);manifest(source,'manifest.json')
 current=source/'current-mls';report=load(current/'report.json');events=load(current/'events.json')['mls'];bindings=[]
 for rec in report['sources']:
  assert rec['status']=='CAPTURED'
  path=current/rec['raw_path'];assert sha(path)==rec['raw_sha256'];j=load(path)
  league=[l for l in j['leagues'] if str(l['id'])=='770' and l['slug']=='usa.1' and l['name']=='MLS'];assert len(league)==1
  season=league[0]['season'];typ=season['type'];assert season['year']==2026 and typ['type']==13846 and typ['name']=='Regular Season'
  for e in j.get('events',[]):assert e['season']=={'year':2026,'type':13846,'slug':'regular-season'}
  bindings.append({'source_sha256':rec['raw_sha256'],'retrieved_at_utc':rec['retrieved_at_utc'],'league_id':'770','slug':'usa.1','year':2026,'type_code':13846,'type_name':'Regular Season'})
 save_json(OUT/'scope-review.json',{'prior_generic_refusal':report['schedule'],'disposition':'EXPLICIT_MLS_LEAGUE_ID_AND_SEASON_METADATA_VERIFIED','source_bindings':bindings,'global_parser_changed':False})
 history=OUT/'history';packages=OUT/'packages'
 run(['scripts/capture_team_histories.py','--league','mls','--output',str(history)],'history')
 run(['scripts/prepare_initial_baselines.py','--league','mls','--history',str(history),'--current',str(current),'--output',str(packages)],'prepare')
 env={**os.environ,'SPORTS_RESEARCH_PACKAGE_DIR':str(packages)}
 run(['scripts/generate_card_force.py','--league','mls','--date','2026-10-25','--initial-research-baselines','--simulations','100000','--output-dir',str(OUT/'card')],'inference',env)
 card=load(OUT/'card/diagnostic_card.json');r['input_cutoff_utc']=card['as_of_utc'];r['card_sha256']=sha(OUT/'card/diagnostic_card.json');r['package_sha256']=sha(packages/'mls/package.json')
 for f in card['forecasts']:
  if f.get('forecast_status')!='FORECAST_GENERATED':r['blockers'].append(f);continue
  raw=events[f['event_id'].split(':')[-1]];r['forecasts'].append({'forecast':f,'market_raw':raw})
 r['status']='EXECUTED_RESEARCH_ONLY' if r['forecasts'] else 'NO_FORECASTS'
except Exception as e:r['status']='BLOCKED';r['blockers'].append(type(e).__name__+':'+str(e));(OUT/'error.txt').write_text(traceback.format_exc());print(traceback.format_exc(),flush=True)
finally:
 r['completed_at_utc']=utc();save_json(OUT/'summary.json',r);save_json(OUT/'manifest.json',{str(p.relative_to(OUT)):sha(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='manifest.json'})
 archive=OUT.parent/'mls-reviewed-evidence.zip'
 with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for p in OUT.rglob('*'):
   if p.is_file():z.write(p,str(p.relative_to(OUT)))
 print('FINAL',r['status'],len(r['forecasts']),r['blockers'],'ARCHIVE_SHA256',sha(archive),flush=True)
if r['status']=='BLOCKED':sys.exit(2)
