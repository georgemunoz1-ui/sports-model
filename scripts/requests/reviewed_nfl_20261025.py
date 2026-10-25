"""Review named NFL source conflicts using existing strict adjudication contracts.
Preserves first attempt. No fitted model, runtime, defaults or canonical edits.
"""
from __future__ import annotations
import concurrent.futures as cf,copy,datetime as dt,hashlib,json,os,re,subprocess,sys,traceback,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from scripts.recovery_capture import capture,save_json,utc
from models.nfl.contextual import weekly_state as ws
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.starter_adjudication import apply
from scripts.prepare_nfl_weekly_events import build
from scripts.verify_nfl_weekly_sources import manifest
import pandas as pd
DAY='2026-10-25';OUT=ROOT/'run-output/nfl-reviewed';OUT.mkdir(parents=True,exist_ok=False)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def extract(p,d):
 d.mkdir(parents=True,exist_ok=False)
 with zipfile.ZipFile(p) as z:
  assert all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in z.namelist())
  z.extractall(d)
def read(p):return json.loads(p.read_text())
def command(args,label,env):
 started=utc();p=subprocess.run([sys.executable,*args],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 (OUT/(label+'.log')).write_text(p.stdout)
 save_json(OUT/(label+'.receipt.json'),dict(command=[sys.executable,*args],started_at_utc=started,completed_at_utc=utc(),returncode=p.returncode,log_sha256=sha(OUT/(label+'.log'))))
 print(label,p.returncode,p.stdout[-800:],flush=True);return p.returncode
R=dict(schema='nfl.current_reviewed_execution.v1',date=DAY,source_pin='527409a9aa48b554a03aecd01b5b87ac66bc9baa',run_id=os.environ.get('GITHUB_RUN_ID'),execution_commit=os.environ.get('GITHUB_SHA'),started_at_utc=utc(),forecasts=[],blockers=[],action_authority=False,canonical_registrations=0)
try:
 archive=OUT/'original-attempt.zip'
 with archive.open('xb') as f:subprocess.run(['gh','api','repos/georgemunoz1-ui/sports-model/actions/artifacts/12595248424/zip'],stdout=f,check=True)
 assert sha(archive)=='f09c898a2189c246450b1eb14178d1e8817ca8e60054b9d371a2b8f73ba15293'
 outer=OUT/'original-outer';extract(archive,outer);original=OUT/'original-attempt';extract(outer/'nfl-evidence.zip',original)
 manifest(original,'manifest.json');frozen=original/'frozen-seed';manifest(frozen,'completed_manifest.json')
 sources=original/'nfl-sources';schedule=ws.capture(sources/'games.csv',read(sources/'games.csv.receipt.json'));pbp=ws.capture(sources/'play_by_play_2026.csv',read(sources/'play_by_play_2026.csv.receipt.json'))
 games=pd.read_csv(sources/'games.csv',low_memory=False);plays=pd.read_csv(sources/'play_by_play_2026.csv',low_memory=False)
 # These exact event/team/player mappings were identified and explicitly reviewed,
 # not selected by a max-dropback or most-favorable-probability heuristic.
 named=[('2026_02_CAR_ATL','ATL','Cooper Rush','00-0033662','C.Rush','STALE_SCHEDULE_STARTER'),('2026_03_SEA_WAS','WAS','Marcus Mariota','00-0032268','M.Mariota','STALE_SCHEDULE_STARTER'),('2026_03_SEA_WAS','SEA','Sam Darnold','00-0034869','S.Darnold','STALE_SCHEDULE_STARTER'),('2026_04_NYJ_CHI','CHI','Tyson Bagent','00-0038416','T.Bagent','NOMINAL_STARTER_NO_DROPBACKS'),('2026_04_LAC_SEA','SEA','Sam Darnold','00-0034869','S.Darnold','STALE_SCHEDULE_STARTER'),('2026_05_SF_SEA','SEA','Sam Darnold','00-0034869','S.Darnold','STALE_SCHEDULE_STARTER'),('2026_06_SEA_DEN','SEA','Sam Darnold','00-0034869','S.Darnold','STALE_SCHEDULE_STARTER')]
 reviews=[];review_sources={}
 alias={'provider_code':'WSH','canonical_code':'WAS','provider_team_id':'28','provider_display_name':'Washington Commanders'}
 for gid,team,player,qid,pbpname,kind in named:
  g=games[games.game_id==gid];assert len(g)==1;g=g.iloc[0];eid=str(g.espn);side='home' if g.home_team==team else 'away'
  if eid not in review_sources:
   rec,j=capture(OUT/'historical-review',('nfl','named_starter_source_review','https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event='+eid,2));assert rec['status']=='CAPTURED'
   text=(OUT/'historical-review'/rec['raw_path']).read_text();review_sources[eid]=(rec,j,text)
  rec,j,text=review_sources[eid]
  athletes=[a for t in j['boxscore']['players'] if ('WAS' if t['team']['abbreviation']=='WSH' else t['team']['abbreviation'])==team for st in t['statistics'] if st['name']=='passing' for a in st['athletes'] if a['athlete']['displayName']==player]
  assert len(athletes)==1,(gid,player)
  r=dict(game_id=gid,team=team,expected_schedule_qb_id=g[side+'_qb_id'],qb_id=qid,espn_event_id=eid,espn_athlete_id=str(athletes[0]['athlete']['id']),player_name=player,pbp_player_name=pbpname,resolution_kind=kind,reviewed_at_utc=utc(),reviewed_by='Named source reconciliation; actual ESPN box and first-dropback identity checked by unmodified starter_adjudication.apply',review_reason='Resolve explicitly identified historical schedule/active-passer conflict; raw source bytes and nominal starter retained',evidence={'text':text,'receipt':{'source_url':rec['url'],'sha256':rec['raw_sha256'],'retrieved_at_utc':rec['retrieved_at_utc']}})
  if 'WAS' in (g.home_team,g.away_team):r['provider_team_binding_review']=alias
  if kind=='NOMINAL_STARTER_NO_DROPBACKS':
   story=j.get('article',{}).get('story','');nominal=g[side+'_qb_name'];segments=[part for part in re.split(r'(?<=[.!?])\s+|</p>',story) if nominal in part]
   assert segments,'NOMINAL_STARTER_ARTICLE_EVIDENCE_MISSING'
   r['nominal_starter_evidence_excerpt']=segments[0];r['nominal_starter_player_name']=nominal
  # Validate each reviewed resolution independently before allowing it into a seed.
  apply(games[games.game_id==gid],plays[plays.game_id==gid],[r],utc());reviews.append(r)
  print('REVIEWED',gid,team,g[side+'_qb_name'],'->',player,kind,'ESPN',r['espn_athlete_id'],r.get('nominal_starter_evidence_excerpt',''),flush=True)
 save_json(OUT/'source-bound-reviews.json',reviews);R['review_count']=len(reviews)
 model=load_artifact(ROOT/'data/nfl/contextual_v1/model_packed.json');cutoff=utc();store=OUT/'weekly-state'
 seed=ws.initialize(store,read(frozen/'historical_state.json'),schedule,model,cutoff,starter_adjudications=reviews);parent=seed;R['seed_id']=seed;R['transitions']=[]
 for week in range(1,7):
  parent=ws.advance(store,parent,seed,model,schedule,pbp,week,cutoff);state=ws.load_verified(store,parent,model,cutoff,seed)
  R['transitions'].append(dict(week=week,state_id=parent,consumed_games=len(state['consumed_game_ids'])));print('STATE_WEEK',week,len(state['consumed_game_ids']),flush=True)
 os.environ['NFL_WEEKLY_STATE_SEED_SHA256']=seed
 package_path=OUT/'schedule_assignment_package.json';package=build(store,parent,seed,package_path)
 # Preserve schedule-only package, then create a new source-bound personnel snapshot.
 package=copy.deepcopy(package);target='2026_07_TB_CAR';packet=package['event_inputs'][target]
 assert packet['context']['personnel']['state']['quarterbacks']['TB']['id']=='00-0041251'
 url='https://www.buccaneers.com/news/october-2026-updates'
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 sports-model-source-review'}),timeout=45) as response:raw=response.read()
 html=raw.decode();assert 'Baker Mayfield Expected to Start' in html and 'ready to go' in html and 'Oct 23, 2026' in html,'CURRENT_QB_PRIMARY_EVIDENCE_MISSING'
 source_path=OUT/'buccaneers-current-qb.html';source_path.write_bytes(raw);retrieved=utc()
 candidates=[]
 for s in ('home','away'):
  candidates.extend(games.loc[(games.season==2026)&(games[s+'_team']=='TB')&(games[s+'_qb_name']=='Baker Mayfield'),s+'_qb_id'].dropna().unique().tolist())
 assert set(candidates)=={'00-0034855'},'CURRENT_QB_CROSSWALK_CONFLICT'
 personal=packet['context']['personnel'];original_personal=copy.deepcopy(personal)
 personal['source']=url;personal['source_sha256']=sha(source_path);personal['retrieved_at_utc']=retrieved;personal['available_by_utc']=retrieved
 personal['state']['quarterbacks']['TB']={'id':'00-0034855','game_status':'QUESTIONABLE','confirmation':'OFFICIAL_TEAM_EXPECTED_STARTER_NOT_FINAL_INACTIVE_CLEARANCE','player_name':'Baker Mayfield'}
 personal['state']['quarterback_source_bindings']={'CAR':{'source_url':original_personal['source'],'source_sha256':original_personal['source_sha256'],'retrieved_at_utc':original_personal['retrieved_at_utc']},'TB':{'source_url':url,'source_sha256':sha(source_path),'retrieved_at_utc':retrieved,'gsis_crosswalk_source_sha256':schedule['receipt']['sha256']}}
 package['captured_at_utc']=utc();package['source_fetches'].append({'source':url,'sha256':sha(source_path),'fetched_at_utc':retrieved})
 package['limitations'].append('TB_BAKER_MAYFIELD_OFFICIAL_EXPECTED_STARTER_REPLACES_STALE_SCHEDULE_JALON_DANIELS; FINAL_CLEARANCE_PENDING')
 package['parent_schedule_package_sha256']=sha(package_path)
 revised=OUT/'reviewed_current_package.json';save_json(revised,package)
 R.update(package_sha256=sha(revised),state_id=parent,current_qb_source={'url':url,'sha256':sha(source_path),'retrieved_at_utc':retrieved,'old_id':'00-0041251','new_id':'00-0034855'},input_cutoff_utc=package['captured_at_utc'])
 env={**os.environ,'NFL_CONTEXT_PACKAGE':str(revised),'NFL_WEEKLY_STATE_SEED_SHA256':seed}
 events=[e for e in package['events'] if e['gameday']==DAY]
 def run(e):
  eid=e['event_id'];base=['scripts/run_nfl_integrated.py','--date',DAY,'--event-id',eid,'--simulations','100000','--weekly-state-store',str(store),'--weekly-state-id',parent]
  rc=command([*base,'--output',str(OUT/'selected'),'--margin-model','data/nfl/qb_margin_full_support_v1/runtime.json'],'selected-'+eid,env)
  rc2=command([*base,'--output',str(OUT/'combined'),'--model-id','nfl.integrated_context.combined.v1.research'],'combined-'+eid,env)
  return {'event_id':eid,'selected_returncode':rc,'combined_returncode':rc2}
 # Serial writes preserve the runner's shared append-only stream ordering.
 R['event_executions']=[run(e) for e in events]
 market=read(original/'current-nfl/events.json')['nfl']
 for e in events:
  eid=e['event_id'];p=OUT/'selected'/eid/'forecast.json'
  if not p.exists():R['blockers'].append({'event_id':eid,'reason':'SELECTED_CLI_FAILED'});continue
  f=read(p);r={'event':e,'forecast':f,'forecast_sha256':sha(p),'quarterbacks':package['event_inputs'][eid]['context']['personnel']['state']['quarterbacks'],'market_source_status':'MISSING'}
  for v in market.values():
   pe=v['event'];sides={c['homeAway']:c['team']['abbreviation'] for c in pe['competitions'][0]['competitors']};sides={k:({'WSH':'WAS'}.get(v,v)) for k,v in sides.items()}
   if sides=={'home':e['home_team'],'away':e['away_team']} and ws.utc(pe['date'])==ws.utc(e['start_time_utc']):r['market_raw']=v;r['market_source_status']='CAPTURED_EXACT_TEAMS_AND_KICKOFF';break
  c=OUT/'combined'/eid/'forecast.json'
  if c.exists():r['combined_forecast']=read(c);r['combined_forecast_sha256']=sha(c)
  R['forecasts'].append(r)
 R['status']='EXECUTED_RESEARCH_ONLY' if len(R['forecasts'])==len(events) else 'PARTIAL_WITH_SCOPED_BLOCKERS'
except Exception as e:R['status']='BLOCKED';R['blockers'].append(type(e).__name__+':'+str(e));(OUT/'error.txt').write_text(traceback.format_exc());print(traceback.format_exc(),flush=True)
finally:
 R['completed_at_utc']=utc();save_json(OUT/'summary.json',R)
 save_json(OUT/'manifest.json',{str(p.relative_to(OUT)):sha(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='manifest.json'})
 archive=OUT.parent/'nfl-reviewed-evidence.zip'
 with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for p in sorted(OUT.rglob('*')):
   if p.is_file():z.write(p,str(p.relative_to(OUT)))
 print('FINAL',R['status'],len(R['forecasts']),R['blockers'],'ARCHIVE_SHA256',sha(archive),flush=True)
if R['status']=='BLOCKED':sys.exit(2)
