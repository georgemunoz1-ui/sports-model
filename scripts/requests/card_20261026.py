"""One-off current-source October 26 card; no main/default/wager changes.
Reuse existing model/preparation/settlement runners. Actual acquisition and execution
receipts are retained. Expiring Actions delivery is not permanent archival.
"""
from __future__ import annotations
import ast, concurrent.futures as cf, datetime as dt, hashlib, json, os, csv
from pathlib import Path
import subprocess, sys, traceback, urllib.request, zipfile
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
DAY='2026-10-26';PIN='527409a9aa48b554a03aecd01b5b87ac66bc9baa'
LEAGUE=sys.argv[1];TZ=ZoneInfo('America/Los_Angeles')
# Reuse the exact earlier acquisition/distribution orchestration definitions only.
# Its former top-level dated execution is NOT executed. Existing model files are unchanged.
prior=subprocess.check_output(['git','show','37f977bad0ae23d17af89a09a951e214a8136f14:scripts/requests/run_20261024.py'],cwd=ROOT,text=True)
body=ast.parse(prior).body; stop=next(i for i,n in enumerate(body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='result' for t in n.targets))
ns={'__file__':str(__file__),'__name__':'retained_orchestration_helpers'}
exec(compile(ast.Module(body=body[:stop],type_ignores=[]),'retained_orchestration_helpers','exec'),ns)
ns['DAY']=DAY;ns['PIN']=PIN
OUT=ns['OUT'];sha=ns['sha'];save_json=ns['save_json'];utc=ns['utc'];capture=ns['capture'];seal=ns['seal'];cmd=ns['cmd'];current=ns['current']
(OUT/'reused_helper_source.py').write_text(prior)
result=dict(schema='sports.current_card_execution.v1',date=DAY,league=LEAGUE,timezone='America/Los_Angeles',source_pin=PIN,execution_commit=os.environ.get('GITHUB_SHA'),run_id=os.environ.get('GITHUB_RUN_ID'),started_at_utc=utc(),action_authority=False,live_allocation_units=0,model_defaults_changed=False,canonical_registrations=0,forecasts=[],blockers=[])

def run_cmd(args,label,env=None):
    before=utc(); p=subprocess.run([sys.executable,*args],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (OUT/(label+'.log')).write_text(p.stdout)
    save_json(OUT/(label+'.receipt.json'),dict(command=[sys.executable,*args],started_at_utc=before,completed_at_utc=utc(),returncode=p.returncode,log_sha256=sha(OUT/(label+'.log'))))
    print('COMMAND',label,p.returncode,p.stdout[-1400:],flush=True)
    return p.returncode

def safe_extract(archive,where):
    where.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        for n in z.namelist():
            if Path(n).is_absolute() or '..' in Path(n).parts:raise ValueError('ZIP_PATH')
        z.extractall(where)

def scoped_events(sources):
    return [r['event'] for r in sources.values() if dt.datetime.fromisoformat(r['event']['date'].replace('Z','+00:00')).astimezone(TZ).date().isoformat()==DAY]


def annotate_poststart_card(card_path):
    card=json.loads(card_path.read_text())
    generated=dt.datetime.fromisoformat(card['generated_at_utc'].replace('Z','+00:00'))
    card['generation_mode']='POST_START_RETROSPECTIVE_AUDIT'
    card['prospective_grading_eligible']=False
    card['actionable']=False
    card['authority']='SHADOW_ONLY'
    card['post_start_audit']={
        'label':'CREATED_AFTER_TARGET_DATE_GAMES_STARTED',
        'target_date':DAY,
        'generated_at_utc':card['generated_at_utc'],
        'prospective_grading_eligible':False,
        'canonical_registration_permitted':False,
        'score_and_live_stat_inputs_used_for_target_event_forecasts':False,
        'current_source_snapshots_are_not_historical_point_in_time_evidence':True
    }
    post_count=0
    for row in card.get('forecasts',[]):
        row['action_authority']=False
        row['action_status']='SHADOW_ONLY'
        row['warnings']=list(dict.fromkeys(list(row.get('warnings',[]))+['POST_START_RETROSPECTIVE_AUDIT_ONLY','NOT_ELIGIBLE_FOR_PROSPECTIVE_GRADING']))
        start=dt.datetime.fromisoformat(row['start_time_utc'].replace('Z','+00:00'))
        if start<=generated: post_count+=1
        grading=row.setdefault('grading',{})
        grading['awaiting_outcome']=False
        grading['eligible_for_prospective_grading']=False
        grading['eligibility_reason']='POST_START_RETROSPECTIVE_AUDIT_ONLY'
        grading['actual_result']=None
        grading['home_won']=None
        grading['brier_analytic']=None
        grading['brier_sim']=None
        grading['log_loss_analytic']=None
        grading['log_loss_sim']=None
    card['post_start_audit']['events_started_by_generation']=post_count
    card['post_start_audit']['event_count']=len(card.get('forecasts',[]))
    card_path.write_text(json.dumps(card,sort_keys=True,indent=2)+'\\n')
    md=card_path.with_name('diagnostic_card.md')
    if md.exists():
        with md.open('a') as h:
            h.write('\\n\\n## RETROSPECTIVE BACKFILL — NOT A PREGAME RELEASE\\n')
            h.write(f'Generated at {card["generated_at_utc"]}; target date {DAY}. This card was generated after games had started. ')
            h.write('Current provider snapshots were used for event identity only; live target-game score/stat fields were excluded from forecast inputs. ')
            h.write('Historical point-in-time availability is not established. All rows are ineligible for prospective grading and action authority is OFF.\\n')
    csv_path=card_path.with_name('diagnostic_card.csv')
    if csv_path.exists():
        with csv_path.open(newline='') as h: rows=list(csv.DictReader(h))
        fields=list(rows[0].keys()) if rows else []
        if 'post_start_audit' not in fields: fields.append('post_start_audit')
        with csv_path.open('w',newline='') as h:
            w=csv.DictWriter(h,fieldnames=fields,extrasaction='ignore');w.writeheader()
            for r in rows:
                r['post_start_audit']='true'
                r['grading_eligible']='False'
                r['warnings']=';'.join(dict.fromkeys([x for x in r.get('warnings','').split(';') if x]+['POST_START_RETROSPECTIVE_AUDIT_ONLY','NOT_ELIGIBLE_FOR_PROSPECTIVE_GRADING']))
                w.writerow(r)
    return card

def nba_nhl():
    current_dir,report,sources=current(LEAGUE)
    result['schedule']=report['schedule'];result['current_source_count']=len(report['sources'])
    if report['schedule']['schedule_status']!='PROVIDER_SCHEDULE_CAPTURED':
        reason=str(report['schedule'].get('reason',''))
        if os.environ.get('SPORTS_POSTSTART_AUDIT')!='1' or report['schedule'].get('schedule_status')!='SCHEDULE_UNKNOWN' or not reason.startswith('PROVIDER_EVENT_REVISION:'):
            raise ValueError('SCHEDULE_CAPTURE_FAILED:'+reason)
        # Audit-only reconciliation: use retained raw provider event identities (ID, teams, start),
        # never live score/stat fields as forecast inputs. Keep the original source report unchanged.
        result['schedule_reconciliation']={'status':'POST_START_IDENTITY_ONLY','reason':reason,'source_event_count':len(scoped_events(sources)),'score_fields_used_for_forecast':False}
    if not scoped_events(sources):result['status']='NO_EVENTS_IN_CAPTURED_PROVIDER_SCOPE';return
    packages=OUT/'packages'
    if LEAGUE=='nba':
        history=OUT/'history'
        cmd(['scripts/capture_team_histories.py','--league','nba','--nba-current-bundle',str(current_dir),'--output',str(history)],'history')
        cmd(['scripts/requests/prepare_initial_baselines_audit.py','--league','nba','--history',str(history),'--current',str(current_dir),'--nba-acquisition-scope',str(history/'nba_acquisition_scope.json'),'--output',str(packages)],'prepare')
    else:
        history,scope=ns['nhl_history']()
        cmd(['scripts/requests/prepare_initial_baselines_audit.py','--league','nhl','--history',str(history),'--current',str(current_dir),'--season-scope',str(scope),'--output',str(packages)],'prepare')
    env={**os.environ,'SPORTS_RESEARCH_PACKAGE_DIR':str(packages)}
    run_cmd(['scripts/requests/generate_card_force_audit.py','--league',LEAGUE,'--date',DAY,'--simulations','100000','--initial-research-baselines','--output-dir',str(OUT/'card')],'inference',env)
    card_path=OUT/'card/diagnostic_card.json'
    card=annotate_poststart_card(card_path)
    pkg=json.loads((packages/LEAGUE/'package.json').read_text())
    events=[e for e in pkg['events'] if e['slate_date']==DAY and any(f.get('event_id')==e['event_id'] and f.get('forecast_status')=='FORECAST_GENERATED' for f in card['forecasts'])]
    result.update(input_cutoff_utc=card['as_of_utc'],card_sha256=sha(OUT/'card/diagnostic_card.json'),package_sha256=sha(packages/LEAGUE/'package.json'),model_lineage=pkg['model_lineage'])
    ds=None
    try:ds=ns['distributions'](LEAGUE,packages,events)
    except Exception as e:
        result['blockers'].append('DISTRIBUTION:'+str(e));(OUT/'distribution-error.txt').write_text(traceback.format_exc())
    from models.common import discrete_research as D
    from models.nfl.contextual.recovered_inference import bernoulli_simulation
    import numpy as np
    for f in card['forecasts']:
        if f.get('forecast_status')!='FORECAST_GENERATED':result['blockers'].append(f);continue
        r={k:f.get(k) for k in ('event_id','home_team','away_team','start_time_utc','model_id','model_winner','analytic_p','sim_p','projected_total')}
        r.update(home_margin=f['diagnostics']['home_margin'],home_win=f['diagnostics']['home_win'],warnings=f.get('warnings',[]),period='FULL_GAME',input_cutoff_utc=card['as_of_utc'],distributions={})
        ad=np.load(Path(f['simulation']['draw_directory'])/'winner_draws.npy');re,_=bernoulli_simulation(f['diagnostics']['home_win'],f['numerical_identity']['identity_sha256'],100000)
        assert np.array_equal(ad,re);r['winner_draws_exact_replay']=True
        raw=sources.get(f['event_id'].split(':')[-1])
        r['market_source_status']='MISSING' if raw is None else 'POST_START_SOURCE_FOR_IDENTITY_ONLY'
        if raw:
            assert D.stamp(raw['event']['date'])==D.stamp(f['start_time_utc'])
            r['market_source_receipt']={'source_sha256':raw.get('source_sha256'),'retrieved_at_utc':raw.get('retrieved_at_utc'),'payload_outcome_fields_excluded':True}
        if ds:
            r['distributions']={d['product']:d for x in ds['results'] if x['event_id']==f['event_id'] for d in [x['distribution']]}
        result['forecasts'].append(r)
    result['generation_mode']='POST_START_RETROSPECTIVE_AUDIT';result['prospective_grading_eligible']=False;result['action_authority']=False;result['canonical_registrations']=0;result['live_allocation_units']=0
    result['status']='POST_START_RETROSPECTIVE_AUDIT_ONLY' if not result['blockers'] else 'PARTIAL_RETROSPECTIVE_AUDIT_WITH_SCOPED_BLOCKERS'

def scope_only():
    result['schedule']={}
    for league in ('cfb','mlb','wnba','mls','nfl'):
        try:
            _,report,raw=current(league)
            result['schedule'][league]=dict(schedule=report['schedule'],events=scoped_events(raw),source_count=len(report['sources']))
        except Exception as e:result['schedule'][league]=dict(status='ACQUISITION_BLOCKED',reason=str(e))
    result['status']='SCHEDULE_SCOPE_ONLY'

def nfl():
    import pandas as pd
    from models.nfl.contextual import weekly_state as ws
    from models.nfl.contextual.model import load_artifact
    from scripts.prepare_nfl_weekly_events import build
    current_dir,report,sources=current('nfl');result['schedule']=report['schedule']
    result['current_events']=scoped_events(sources)
    # Source-only frozen Week1 seed. Its archived code is never imported.
    archive=OUT/'seed-evidence.zip'
    with archive.open('xb') as handle:subprocess.run(['gh','api','repos/georgemunoz1-ui/sports-model/actions/artifacts/10525312986/zip'],stdout=handle,check=True)
    if sha(archive)!='12babe78049b69d07e41dfd4568b36c9f0fe41d511d73dd796364f7a19b52074':raise ValueError('HISTORICAL_SEED_ARCHIVE_HASH')
    frozen=OUT/'frozen-seed';safe_extract(archive,frozen)
    from scripts.verify_nfl_weekly_sources import manifest
    manifest(frozen,'completed_manifest.json')
    seed_data=json.loads((frozen/'historical_state.json').read_text());result['seed_source_archive_sha256']=sha(archive)
    def acquire(url,name):
        start=utc()
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'sports-model-research-source/1.0'}),timeout=90) as response:raw=response.read()
        path=OUT/'nfl-sources'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        receipt=dict(source_url=url,requested_at_utc=start,retrieved_at_utc=utc(),sha256=sha(path),filename=name)
        save_json(OUT/'nfl-sources'/(name+'.receipt.json'),receipt)
        return ws.capture(path,receipt)
    schedule=acquire(ws.SCHEDULE_URL,'games.csv')
    pbp=acquire('https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2026.csv','play_by_play_2026.csv')
    frame=pd.read_csv(OUT/'nfl-sources/games.csv',low_memory=False)
    selected=frame[(frame.season==2026)&(frame.game_type=='REG')&(frame.gameday.astype(str)==DAY)]
    if selected.empty:raise ValueError('NO_REQUESTED_DAY_IN_NFLVERSE_SCHEDULE')
    weeks=set(int(x) for x in selected.week);assert len(weeks)==1;target_week=next(iter(weeks));result['target_week']=target_week
    # Reuse only the prior explicitly reviewed historical starter correction if still applicable.
    resolutions=[];review=json.loads((ROOT/'data/nfl/starter_adjudications_20260922/review.json').read_text())
    g=frame[frame.game_id==review['game_id']]
    if len(g)==1:
        g=g.iloc[0];side='home' if g.home_team==review['team'] else 'away'
        if g[side+'_qb_id']==review['expected_schedule_qb_id']:
            rec,data=capture(OUT/'starter-review',('nfl','retained_review_reverification',review['evidence_receipt']['source_url'],2))
            if rec['status']!='CAPTURED':raise ValueError('HISTORICAL_STARTER_REVIEW_REACQUISITION_FAILED')
            r={k:v for k,v in review.items() if k not in ('evidence_receipt','raw_path','source_artifact_id','source_archive_sha256')}
            r['reviewed_at_utc']=utc();r['reviewed_by']='Prior named resolution revalidated against fresh source by existing strict apply() contract'
            r['evidence']={'text':(OUT/'starter-review'/rec['raw_path']).read_text(),'receipt':{'source_url':rec['url'],'sha256':rec['raw_sha256'],'retrieved_at_utc':rec['retrieved_at_utc']}}
            resolutions.append(r)
    save_json(OUT/'starter-resolutions.json',resolutions)
    model=load_artifact(ROOT/'data/nfl/contextual_v1/model_packed.json');store=OUT/'weekly-state';cutoff=utc()
    seed=ws.initialize(store,seed_data,schedule,model,cutoff,starter_adjudications=resolutions);parent=seed;result['state_transitions']=[]
    result['seed_id']=seed
    for week in range(1,target_week):
        try:parent=ws.advance(store,parent,seed,model,schedule,pbp,week,cutoff)
        except Exception:
            from scripts.validate_current_nfl_weekly_state import starter_conflicts
            result['starter_conflicts']=starter_conflicts(OUT/'nfl-sources/games.csv',OUT/'nfl-sources/play_by_play_2026.csv',2026,week)
            raise
        state=ws.load_verified(store,parent,model,cutoff,seed)
        result['state_transitions'].append(dict(week=week,state_id=parent,consumed_games=len(state['consumed_game_ids'])))
        print('STATE_WEEK',week,len(state['consumed_game_ids']),flush=True)
    os.environ['NFL_WEEKLY_STATE_SEED_SHA256']=seed
    package_path=OUT/'event_package.json';package=build(store,parent,seed,package_path)
    result.update(package_sha256=sha(package_path),state_id=parent,package_limitations=package['limitations'],completed_state_week=target_week-1)
    env={**os.environ,'NFL_CONTEXT_PACKAGE':str(package_path),'NFL_WEEKLY_STATE_SEED_SHA256':seed}
    # Each event is isolated: one refusal cannot silently discard unrelated games.
    events=[e for e in package['events'] if e['gameday']==DAY]
    def one(e):
        eid=e['event_id'];base=['scripts/run_nfl_integrated.py','--date',DAY,'--event-id',eid,'--simulations','100000','--weekly-state-store',str(store),'--weekly-state-id',parent]
        selected_rc=run_cmd([*base,'--output',str(OUT/'selected'),'--margin-model','data/nfl/qb_margin_full_support_v1/runtime.json'],'selected-'+eid,env)
        combined_rc=run_cmd([*base,'--output',str(OUT/'combined'),'--model-id','nfl.integrated_context.combined.v1.research'],'combined-'+eid,env)
        return dict(event=e,selected_returncode=selected_rc,combined_returncode=combined_rc)
    with cf.ThreadPoolExecutor(max_workers=3) as pool:result['event_executions']=list(pool.map(one,events))
    for executed in result['event_executions']:
        e=executed['event'];eid=e['event_id'];f=OUT/'selected'/eid/'forecast.json'
        if not f.exists():result['blockers'].append(dict(event_id=eid,reason='SELECTED_RUN_FAILED'));continue
        forecast=json.loads(f.read_text());schedule_row=selected[selected.game_id==eid].iloc[0]
        r=dict(event=e,forecast=forecast,selected_forecast_sha256=sha(f),quarterbacks={s:{'id':schedule_row.get(s+'_qb_id'),'name':schedule_row.get(s+'_qb_name'),'status':'CURRENT_SCHEDULE_ASSIGNMENT_NOT_FINAL_ACTIVE_CONFIRMATION'} for s in ('home','away')},market_source_status='MISSING')
        for source in sources.values():
            pe=source['event'];comp=pe['competitions'][0];teams={c['homeAway']:c['team']['abbreviation'] for c in comp['competitors']}
            aliases={'WSH':'WAS'};teams={s:aliases.get(t,t) for s,t in teams.items()}
            if teams.get('home')==e['home_team'] and teams.get('away')==e['away_team'] and dt.datetime.fromisoformat(pe['date'].replace('Z','+00:00'))==dt.datetime.fromisoformat(e['start_time_utc'].replace('Z','+00:00')):
                r['market_source_receipt']={'source_sha256':source.get('source_sha256'),'retrieved_at_utc':source.get('retrieved_at_utc'),'payload_outcome_fields_excluded':True};r['market_source_status']='POST_START_SOURCE_FOR_IDENTITY_ONLY';break
        margin_dir=OUT/'selected'/eid/'margin_distribution'
        r['margin_files']=[str(p.relative_to(OUT)) for p in margin_dir.glob('*.json')]
        f2=OUT/'combined'/eid/'forecast.json'
        if f2.exists():r['combined_forecast']=json.loads(f2.read_text());r['combined_forecast_sha256']=sha(f2)
        result['forecasts'].append(r)
    result['generation_mode']='POST_START_RETROSPECTIVE_AUDIT';result['prospective_grading_eligible']=False;result['action_authority']=False;result['canonical_registrations']=0;result['live_allocation_units']=0
    for item in result['forecasts']:
        for key in ('forecast','combined_forecast'):
            f=item.get(key)
            if not isinstance(f,dict): continue
            f['action_authority']=False;f['canonical_prospective_eligible']=False
            f['warnings']=list(dict.fromkeys(list(f.get('warnings',[]))+['POST_START_RETROSPECTIVE_AUDIT_ONLY','NOT_ELIGIBLE_FOR_PROSPECTIVE_GRADING']))
    result['status']='POST_START_RETROSPECTIVE_AUDIT_ONLY' if len(result['forecasts'])==len(events) else 'PARTIAL_RETROSPECTIVE_AUDIT_WITH_SCOPED_BLOCKERS'

try:
    if LEAGUE in ('nba','nhl'):nba_nhl()
    elif LEAGUE=='nfl':nfl()
    elif LEAGUE=='scope':scope_only()
    else:raise ValueError('UNSUPPORTED_JOB')
except Exception as exc:
    result['status']='BLOCKED';result['blockers'].append(type(exc).__name__+':'+str(exc));(OUT/'error.txt').write_text(traceback.format_exc());print(traceback.format_exc(),flush=True)
finally:
    result['completed_at_utc']=utc();save_json(OUT/'summary.json',result);seal(OUT)
    print('RUN_SUMMARY',json.dumps({k:v for k,v in result.items() if k not in ('forecasts','current_events','schedule')},default=str),flush=True)
    print('FORECAST_COUNT',len(result['forecasts']),'SUMMARY_SHA256',sha(OUT/'summary.json'),flush=True)
    archive=OUT.parent/(LEAGUE+'-evidence.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(OUT.rglob('*')):
            if p.is_file():z.write(p,str(p.relative_to(OUT)))
    print('ARCHIVE',str(archive),sha(archive),archive.stat().st_size,flush=True)
if result['status']=='BLOCKED':sys.exit(2)
