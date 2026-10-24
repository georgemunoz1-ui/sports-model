#!/usr/bin/env python3
"""Explicit context challenger operator and append-only diagnostic registry.

Always separate from the selected default. Runtime owns the clock. Missing
lineups block lineup/bullpen/calibrated arms while workload can continue.
"""
import argparse,fcntl,json,platform,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from research import mlb_postseason_context as C
from research.mlb_postseason_v1 import sha,digest,stamp,instant,save_once
from scripts import mlb_postseason_workflow as W
from scripts.mlb_postseason_audited import source_map
from scripts.evaluate_mlb_postseason_context import merge_players


def verify_run(path):
    path=Path(path).resolve();receipt=W.load(path/'receipt.json');f=W.load(path/'forecast.json')
    for name,h in receipt['artifact_hashes'].items():
        p=(path/name).resolve()
        if not p.is_relative_to(path) or sha(p)!=h:raise ValueError('FROZEN_ARTIFACT_MISMATCH')
    for name,h in f['code_pins'].items():
        p=(ROOT/name).resolve()
        if not p.is_relative_to(ROOT) or sha(p)!=h:raise ValueError('CODE_DRIFT_FOR_REPLAY')
    result,draws=C.simulate(f['inputs'],f['context'],f['stage'],f['n'],f['seed'],f['calibration_slope'])
    if result!=f['result']:raise ValueError('NUMERICAL_REPLAY_MISMATCH')
    for k,v in draws.items():
        if not np.array_equal(v,np.load(path/(k+'.npy'),allow_pickle=False)):raise ValueError('DRAW_REPLAY_MISMATCH')
    if receipt['pregame_research_capture'] and not instant(f['cutoff_utc'])<=instant(f['created_at_utc'])<=instant(receipt['writer_clock_utc'])<instant(f['inputs']['start_time_utc']):raise ValueError('WRITER_CHRONOLOGY')
    return {'run_id':receipt['run_id'],'exact_replay':True,'n':f['n'],'forecast_sha256':sha(path/'forecast.json'),'canonical_registration':False,'prospective_grade_eligible':False}


def verify_context(root,review):
    ctxroot=root/'context';report=W.load(ctxroot/'report.json')
    if report['package_sha256']!=sha(root/'package.json') or review['context_report_sha256']!=sha(ctxroot/'report.json'):raise ValueError('CONTEXT_BINDING')
    src=source_map(ctxroot,report,instant(stamp()))
    if max(instant(r['retrieved_at_utc']) for r,j in src.values())>instant(review['reviewed_at_utc']):raise ValueError('REVIEW_BEFORE_CONTEXT')
    rosters={int(k.split('_')[1]):j for k,(r,j) in src.items() if k.startswith('roster_')};ids=sorted({r['person']['id'] for j in rosters.values() for r in j['roster']})
    for offset in range(0,len(ids),12):
        expected=set(ids[offset:offset+12])
        for typ in ('R','F','D','L','W'):
            key=f'people_{offset}_{typ}'
            if key not in src or {p['id'] for p in src[key][1]['people']}!=expected:raise ValueError('PLAYER_SOURCE_CENSUS')
            # Endpoint must explicitly bind the requested season and phase.
            url=src[key][0]['url']
            if f'gameType={typ}' not in url:raise ValueError('PLAYER_SOURCE_PHASE')
    for tid in rosters:
        if 'transactions_'+str(tid) not in src:raise ValueError('TRANSACTIONS_SOURCE_MISSING')
    return rosters,merge_players({k:j for k,(r,j) in src.items()},'people_')


def run(root,review_path,contract_path,output,calibration_path=None):
    root=Path(root).resolve();output=Path(output).resolve();contract=W.load(contract_path);review=W.load(review_path)
    request={'package':sha(root/'package.json'),'context':sha(root/'context/report.json'),'review':sha(review_path),'contract':sha(contract_path),'calibration':sha(calibration_path) if calibration_path else None};rid=digest(request)
    output.mkdir(parents=True,exist_ok=True)
    with (output/'.writer.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);index=output/(rid+'.json')
        if index.exists():
            prior=W.load(index)
            for row in prior['runs']:verify_run(row['path'])
            return dict(prior,idempotent_lookup=True)
        if review.get('decision')!='ALLOW_LIMITED_FEATURE_RESEARCH_ONLY' or review.get('action_authority')is not False:raise ValueError('REVIEW_AUTHORITY')
        if review.get('challenger_contract_sha256')!=sha(contract_path) or contract['arms']!={str(k):v for k,v in C.ARMS.items()}:raise ValueError('CHALLENGER_IDENTITY')
        required={'research/mlb_postseason_context.py','scripts/run_mlb_postseason_context.py','scripts/evaluate_mlb_postseason_context.py','scripts/mlb_postseason_audited.py','scripts/mlb_postseason_workflow.py'}
        required.update(W.load(ROOT/'research/registrations/mlb_postseason_v1.json')['code_pins'])
        if not required.issubset(contract['code_pins']) or contract.get('count')!=100000 or contract.get('action_authority')is not False:raise ValueError('REQUIRED_CODE_OR_AUTHORITY_CONTRACT')
        for name,h in contract['code_pins'].items():
            p=(ROOT/name).resolve()
            if not p.is_relative_to(ROOT) or sha(p)!=h:raise ValueError('CHALLENGER_CODE_DRIFT')
        package,r=W.verify_package(root,ROOT/'research/registrations/mlb_postseason_v1.json',review_path)
        rosters,players=verify_context(root,review)
        source=source_map(root/'sources',W.load(root/'sources/report.json'),instant(stamp()));cal=None
        if calibration_path:
            cal=W.load(calibration_path)
            if cal['model_id']!=C.ARMS[4] or review.get('calibration_sha256')!=sha(calibration_path) or cal['design_sha256']!=contract['design_sha256']:raise ValueError('CALIBRATION_IDENTITY')
            if cal['training_cutoff']>=package['slate_date']:raise ValueError('CALIBRATION_LEAKAGE')
        runs=[];coverage=[]
        for e in package['events']:
            eid=e['event_id'];feed=source['gamefeed_'+eid.split(':')[1]][1]
            for stage in (1,2,3,4):
                try:
                    if instant(stamp())>=instant(e['start_time_utc']) or feed['gameData']['status']['abstractGameState']!='Preview':raise ValueError('POST_START')
                    if stage==4 and cal is None:raise ValueError('FITTED_CALIBRATION_NOT_BOUND')
                    if eid not in review['reviewed_event_ids']:raise ValueError('EVENT_REVIEW_MISSING')
                    manual=review['event_context'][eid]
                    if not manual.get('availability_review') or not manual.get('pitching_plan'):raise ValueError('MANUAL_CONTEXT_REVIEW_MISSING')
                    gd=feed['gameData']
                    if str(feed['gamePk'])!=eid.split(':')[1] or instant(gd['datetime']['dateTime'])!=instant(e['start_time_utc']) or gd['game']['type']!=e['game_type']:raise ValueError('EVENT_IDENTITY_CONFLICT')
                    feeds={};rr={}
                    for side in ('away','home'):
                        if gd['probablePitchers'][side]['id']!=e[side+'_pitcher_id']:raise ValueError('STARTER_IDENTITY')
                        rr[side]=rosters[gd['teams'][side]['id']];feeds[side]={'order':feed['liveData']['boxscore']['teams'][side].get('battingOrder',[])}
                    plans=manual.get('plans',{})
                    if any(p.get('role')=='OPENER' or p.get('pitch_cap') is not None for p in plans.values()):
                        if not manual.get('role_source_receipts'):raise ValueError('ANNOUNCED_ROLE_SOURCE_REQUIRED')
                        for rec in manual['role_source_receipts']:
                            file=(root/rec['path']).resolve()
                            if not file.is_relative_to(root) or sha(file)!=rec['sha256'] or instant(rec['captured_at_utc'])>instant(review['reviewed_at_utc']):raise ValueError('ROLE_SOURCE_BINDING')
                    ctx=C.build_context(e,feeds,rr,players,plans,manual.get('unavailable_ids'),stage);cutoff=stamp();slope=cal['slope'] if stage==4 else None
                    identity=digest({'request':request,'event':eid,'arm':C.ARMS[stage],'cutoff':cutoff,'context':ctx});seed=int(identity[:16],16);result,draws=C.simulate(e,ctx,stage,100000,seed,slope)
                    path=output/'runs'/identity;path.mkdir(parents=True,exist_ok=False)
                    for name,array in draws.items():np.save(path/(name+'.npy'),array,allow_pickle=False)
                    forecast={'model_id':C.ARMS[stage],'stage':stage,'inputs':e,'context':ctx,'calibration_slope':slope,'n':100000,'seed':seed,'cutoff_utc':cutoff,'created_at_utc':stamp(),'result':result,'code_pins':contract['code_pins'],'request':request,'runtime':{'python':platform.python_version(),'numpy':np.__version__},'used':['starter_workload']+(['lineup_identity_and_shrunk_OPS'] if stage>=2 else [])+(['roster_relief_strength_and_3day_pitch_load'] if stage>=3 else []),'not_used':['weather','platoon','defense','active_player_injury_severity','manager_choice_certainty'],'manual_review':manual,'official_release_eligible':False,'action_authority':False,'dose':0.}
                    save_once(path/'forecast.json',forecast);writer=stamp();pregame=instant(writer)<instant(e['start_time_utc'])
                    save_once(path/'receipt.json',{'run_id':identity,'writer_clock_utc':writer,'pregame_research_capture':pregame,'canonical_registration':False,'prospective_grade_eligible':False,'official_release_eligible':False,'action_authority':False,'artifact_hashes':{p.name:sha(p) for p in path.iterdir() if p.is_file()}})
                    v=verify_run(path);runs.append({'event_id':eid,'model_id':C.ARMS[stage],'path':str(path),'result':result,'verification':v});coverage.append({'event_id':eid,'stage':stage,'status':'PRE_START_DIAGNOSTIC_FREEZE' if pregame else 'POST_START'})
                except (ValueError,KeyError) as exc:coverage.append({'event_id':eid,'stage':stage,'status':'BLOCKED','reason':str(exc)})
        result={'request':request,'request_id':rid,'writer_clock_utc':stamp(),'coverage':coverage,'runs':runs,'official_release_eligible':False,'action_authority':False,'dose':0.};save_once(index,result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True);r=sub.add_parser('run')
    for name in ('root','review','contract','output'):r.add_argument('--'+name,required=True)
    r.add_argument('--calibration');v=sub.add_parser('verify');v.add_argument('--run',required=True);a=p.parse_args()
    result=verify_run(a.run) if a.cmd=='verify' else run(a.root,a.review,a.contract,a.output,a.calibration)
    print(json.dumps(result,indent=2))
