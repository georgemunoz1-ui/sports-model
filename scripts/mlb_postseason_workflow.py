#!/usr/bin/env python3
"""Collect/review/run/verify a separate MLB postseason research card.

No automatic approval, default selection, official release, or live forecasts.
Frozen mathematical model and its original registration stay unchanged.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import contextlib
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from research.mlb_postseason_v1 import MODEL_ID,sha,digest,stamp,instant,save_once,run_event,simulate
from scripts.prepare_mlb_postseason import prepare
from scripts.recovery_capture import capture


def load(p):return json.loads(Path(p).read_text())


def collect(root,day):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False)
    date=dt.date.fromisoformat(day);prior=date-dt.timedelta(days=1)
    if date>dt.datetime.now(dt.timezone.utc).astimezone(ZoneInfo('America/Los_Angeles')).date():
        raise ValueError('FUTURE_SLATE_NOT_SUPPORTED')
    specs=[('mlb','season',f'https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate={date.year}-03-01&endDate={prior}',1),('mlb','today',f'https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={day}&hydrate=probablePitcher,venue',1)]
    with ThreadPoolExecutor(max_workers=4)as ex:rr=list(ex.map(lambda s:capture(root/'sources',s),specs))
    if any(j is None for r,j in rr):
        save_once(root/'sources/report.json',{'sources':[r for r,j in rr]});raise ValueError('SCHEDULE_CAPTURE_FAILED')
    games=[g for d in rr[1][1]['dates']for g in d['games']]
    ids={t['probablePitcher']['id']for g in games for t in g['teams'].values()if t.get('probablePitcher')}
    specs=[('mlb','gamefeed_'+str(g['gamePk']),f'https://statsapi.mlb.com/api/v1.1/game/{g["gamePk"]}/feed/live',1)for g in games]
    specs += [('mlb','pitcher_'+str(i),f'https://statsapi.mlb.com/api/v1/people/{i}/stats?stats=gameLog&group=pitching&season={date.year}',1)for i in sorted(ids)]
    with ThreadPoolExecutor(max_workers=6)as ex:rr+=list(ex.map(lambda s:capture(root/'sources',s),specs))
    save_once(root/'sources/report.json',{'sources':[r for r,j in rr],'completed_at_utc':stamp()})
    prepare(root,day)
    return inspect(root)


def inspect(root):
    root=Path(root);p=load(root/'package.json')
    return {'package_sha256':sha(root/'package.json'),'events':[{k:x[k]for k in ('event_id','away_team','home_team','away_starter','home_starter','start_time_utc','captured_status','through_date')}for x in p['events']],'context_available_not_used':p['context_available_not_used'],'review_required':True,'model_id':p['model_id']}


def verify_package(root,contract_path,review_path):
    root=Path(root).resolve();p=load(root/'package.json');c=load(contract_path);r=load(review_path);now=instant(stamp())
    if c['model_id']!=MODEL_ID or p['model_id']!=MODEL_ID or c['count']!=100000:
        raise ValueError('CONTRACT_IDENTITY')
    if r.get('decision')!='ALLOW_LIMITED_FEATURE_RESEARCH_ONLY' or r.get('action_authority')is not False:
        raise ValueError('AGENT_REVIEW_NOT_APPROVED')
    if r.get('package_sha256')!=sha(root/'package.json') or r.get('contract_sha256')!=sha(contract_path):
        raise ValueError('REVIEW_BINDING_MISMATCH')
    if not isinstance(r.get('evidence'),dict) or not r['evidence']:
        raise ValueError('REVIEW_EVIDENCE_MISSING')
    if not p.get('source_receipts') or p.get('action_authority')is not False:
        raise ValueError('SOURCE_OR_AUTHORITY')
    for x in p['source_receipts']:
        path=(root/'sources'/x['raw_path']).resolve()
        if not path.is_relative_to(root/'sources') or x.get('status')!='CAPTURED' or sha(path)!=x['raw_sha256']:
            raise ValueError('SOURCE_HASH_OR_PATH')
        if not 0<=(now-instant(x['retrieved_at_utc'])).total_seconds()<=21600:
            raise ValueError('STALE_OR_FUTURE_SOURCE')
    if not max(instant(x['retrieved_at_utc'])for x in p['source_receipts'])<=instant(r['reviewed_at_utc'])<=now:
        raise ValueError('REVIEW_CHRONOLOGY')
    for name,h in c['code_pins'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or sha(path)!=h:raise ValueError('MODEL_CODE_DRIFT')
    if sha(ROOT/'research/mlb_postseason_v1.py')!=c['code_pins'].get('research/mlb_postseason_v1.py'):
        raise ValueError('KERNEL_PIN_MISSING')
    # Rebuild all numerical features from retained source bytes. Hashes alone
    # cannot establish that a hand-edited feature value came from its source.
    with tempfile.TemporaryDirectory()as d:
        q=Path(d);(q/'sources').symlink_to(root/'sources',target_is_directory=True)
        with contextlib.redirect_stdout(io.StringIO()):prepare(q,p['slate_date'])
        rebuilt=load(q/'package.json')
    for key in ('events','team_state','consumed_finals','source_receipts','context_available_not_used'):
        if rebuilt[key]!=p[key]:raise ValueError('SOURCE_FEATURE_REBUILD_MISMATCH:'+key)
    if any(x['date']>=p['slate_date']for x in p['consumed_finals'].values()):
        raise ValueError('SAME_DAY_FINAL')
    return p,r


def verify_run(path):
    path=Path(path);r=load(path/'forecast.json');receipt=load(path/'receipt.json')
    for name,h in receipt['artifact_hashes'].items():
        f=(path/name).resolve()
        if not f.is_relative_to(path.resolve()) or sha(f)!=h:raise ValueError('FROZEN_ARTIFACT_MISMATCH')
    replay,draws=simulate(r['used_inputs'],r['n'],r['seed'])
    if any(r[k]!=v for k,v in replay.items()):raise ValueError('NUMERICAL_REPLAY_MISMATCH')
    for name,value in draws.items():
        if not np.array_equal(np.load(path/(name+'.npy'),allow_pickle=False),value):raise ValueError('DRAW_REPLAY_MISMATCH')
    if receipt['pregame_research_capture']:
        if not instant(r['cutoff_utc'])<=instant(r['created_at_utc'])<=instant(receipt['writer_clock_utc'])<instant(r['start_time_utc']):
            raise ValueError('PREGAME_WRITER_CHRONOLOGY')
    return {'run_id':receipt['run_id'],'forecast_sha256':sha(path/'forecast.json'),'exact_replay':True,'n':r['n'],'canonical_registration':False,'prospective_grade_eligible':False}


def run(root,contract,review,output):
    root=Path(root).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    request={'package':sha(root/'package.json'),'contract':sha(contract),'review':sha(review),'runner_sha256':sha(__file__),'policy':'PREGAME_ONLY_NO_RETIMING'}
    rid=digest(request);index=output/(rid+'.json')
    with (output/'.writer.lock').open('a')as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if index.exists():
            result=load(index)
            for row in result['runs']:verify_run(row['path'])
            return dict(result,idempotent_lookup=True)
        p,r=verify_package(root,contract,review);rows=[];coverage=[]
        for x in p['events']:
            if x['event_id']not in r['reviewed_event_ids']:
                coverage.append({'event_id':x['event_id'],'status':'BLOCKED_AGENT_REVIEW_MISSING'});continue
            if instant(x['start_time_utc'])<=instant(stamp()) or x['captured_status']!='Preview':
                coverage.append({'event_id':x['event_id'],'status':'POST_START_NOT_RERUN'});continue
            row=run_event(x,output/'runs',root/'package.json',contract,review)
            verify_run(row['path']);rows.append(row);coverage.append({'event_id':x['event_id'],'status':row['receipt']['status']})
        result={'request_id':rid,'request':request,'writer_clock_utc':stamp(),'runs':rows,'coverage':coverage,'action_authority':False,'official_release_eligible':False,'runtime':{'python':sys.version,'numpy':np.__version__}}
        save_once(index,result)
        return result


def grade(run_paths,result_path,receipt_path,output):
    """Append-only result reconciliation; never override frozen grading flags."""
    j=load(result_path);source=load(receipt_path)
    if source['raw_sha256']!=sha(result_path) or source['status']!='CAPTURED':raise ValueError('RESULT_SOURCE_MISMATCH')
    games={str(g['gamePk']):g for d in j['dates']for g in d['games']};rows=[]
    for path in run_paths:
        path=Path(path);v=verify_run(path);r=load(path/'forecast.json');f=load(path/'receipt.json');g=games.get(r['event_id'].split(':')[-1])
        status='RESULT_UNAVAILABLE';score=None
        if g and g['status']['abstractGameState']=='Final':
            from harness.mlb_form_state import normalize_team
            if normalize_team(g['teams']['home']['team']['name'])!=r['home'] or normalize_team(g['teams']['away']['team']['name'])!=r['away']:raise ValueError('RESULT_EVENT_IDENTITY')
            score={s:g['teams'][s]['score']for s in ('away','home')};status='NOT_GRADE_ELIGIBLE' if not f['prospective_grade_eligible'] else 'UNSUPPORTED_REGISTRY_ROUTE'
        elif g:status='PENDING_FINAL'
        rows.append({'event_id':r['event_id'],'forecast_sha256':v['forecast_sha256'],'result_sha256':source['raw_sha256'],'score':score,'status':status,'grade':None,'reason':'Frozen prospective-grade eligibility is never upgraded by reconciliation.'})
    value={'created_at_utc':stamp(),'rows':rows,'scored_forecasts':0,'action_authority':False};save_once(output,value);return value


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
    c=sub.add_parser('collect');c.add_argument('--root',type=Path,required=True);c.add_argument('--date',required=True)
    i=sub.add_parser('inspect');i.add_argument('--root',type=Path,required=True)
    r=sub.add_parser('run');r.add_argument('--root',type=Path,required=True);r.add_argument('--contract',type=Path,required=True);r.add_argument('--review',type=Path,required=True);r.add_argument('--output',type=Path,required=True)
    v=sub.add_parser('verify');v.add_argument('--run',type=Path,required=True)
    g=sub.add_parser('grade');g.add_argument('--run',type=Path,action='append',required=True);g.add_argument('--results',type=Path,required=True);g.add_argument('--receipt',type=Path,required=True);g.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.cmd=='collect':z=collect(a.root,a.date)
    elif a.cmd=='inspect':z=inspect(a.root)
    elif a.cmd=='run':z=run(a.root,a.contract.resolve(),a.review.resolve(),a.output)
    elif a.cmd=='verify':z=verify_run(a.run)
    else:z=grade(a.run,a.results,a.receipt,a.output)
    print(json.dumps(z,indent=2,allow_nan=False))

if __name__=='__main__':main()
