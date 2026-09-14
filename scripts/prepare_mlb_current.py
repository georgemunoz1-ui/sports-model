#!/usr/bin/env python3
"""Build an immutable current MLB research packet from retained acquired sources."""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pipelines.mlb.current import assimilate,digest,instant

def prepare(staged_directory,events_file,output,target_date):
    staged=Path(staged_directory);source=Path(events_file);out=Path(output)
    manifest=json.loads((staged/'manifest.json').read_text())
    for name,h in manifest.items():
        if digest(staged/name)!=h:raise ValueError('STAGED_DIGEST_MISMATCH:'+name)
    evidence=json.loads(source.read_text());now=dt.datetime.now(dt.timezone.utc).isoformat()
    if evidence['slate_date']!=target_date or instant(evidence['retrieved_at'])>instant(now):raise ValueError('EVENT_EVIDENCE_DATE')
    events=evidence['events'];ids=set()
    staged_slate=[r for r in json.loads((staged/'events.json').read_text()) if r['league']=='mlb' and r['slate_date']==target_date and r['status']=='scheduled']
    if len(events)!=evidence['expected_games'] or len(events)!=len(staged_slate):raise ValueError('SCHEDULE_COVERAGE_MISMATCH')
    for e in events:
        if e['event_id'] in ids or e['home_team']==e['away_team']:raise ValueError('EVENT_IDENTITY_CONFLICT')
        ids.add(e['event_id'])
        if not str(e['game_pk']).isdigit() or e['event_id']!='MLB:'+str(e['game_pk']):raise ValueError('OFFICIAL_GAME_ID_REQUIRED')
        if not e.get('away_starter') or not e.get('home_starter'):raise ValueError('STARTER_IDENTITY_MISSING')
        if not any(r['away']==e['source_away_name'] and r['home']==e['source_home_name'] and instant(r['start_utc'])==instant(e['start_time_utc']) for r in staged_slate):raise ValueError('SCHEDULE_ORIENTATION_OR_START_CONFLICT')
    form=assimilate(ROOT/'data/backfill/mlb/2026/results.csv',staged/'events.json',target_date,now)
    for e in events:
        if any(t not in form['teams'] for t in (e['away_team'],e['home_team'])):raise ValueError('TEAM_FORM_ABSENT')
    out.mkdir(parents=True,exist_ok=False)
    (out/'form.json').write_text(json.dumps(form,indent=2)+'\n')
    (out/'events-source.json').write_bytes(source.read_bytes())
    paths=[out/'form.json',out/'events-source.json',staged/'events.json',ROOT/'data/backfill/mlb/2026/results.csv',ROOT/'data/backfill/mlb/2026/pitchers.csv',ROOT/'data/backfill/mlb/2026/park_factors.json',ROOT/'data/mlb/ml_asof/p3_candidate_config.json']
    paths+=list((ROOT/'harness').glob('*.py'))+list((ROOT/'engine').glob('*.py'))+list((ROOT/'data/backfill/mlb/2026/pitcher_logs').glob('*'))
    paths+=[ROOT/'pipelines/cards/adapters/mlb.py',ROOT/'pipelines/mlb/current.py',ROOT/'scripts/prepare_mlb_current.py']
    pins={str(p.resolve().relative_to(ROOT)):digest(p) for p in paths if p.is_file()}
    package={'schema':'mlb.current_package.research.v1','model_profile':'V13_AND_FROZEN_D_LOGISTIC_2F; NOT_PHASE1_1','slate_date':target_date,'captured_at':now,'ttl_hours':6,'events':events,'form_path':str((out/'form.json').resolve().relative_to(ROOT)),'pins':pins,'source_fetches':[{'source':evidence['source'],'fetched_at_utc':evidence['retrieved_at'],'sha256':digest(out/'events-source.json')},{'source':'retained staged MLB results','fetched_at_utc':max(r['retrieved_at'] for r in form['rows'] if r.get('retrieved_at')),'sha256':digest(staged/'events.json')}],'canonical_prospective_eligible':False}
    (out/'package.json').write_text(json.dumps(package,indent=2)+'\n')
    return {'schema':'mlb.current_runtime.v1','package_path':str((out/'package.json').resolve().relative_to(ROOT)),'package_sha256':digest(out/'package.json'),'model_profile':package['model_profile'],'research_only':True}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--staged-directory',type=Path,required=True);p.add_argument('--events-file',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--target-date',required=True);p.add_argument('--activate',action='store_true');a=p.parse_args()
    config=prepare(a.staged_directory,a.events_file,a.output,a.target_date)
    if a.activate:
        import os
        runtime=ROOT/'data/mlb/current_v1/runtime.json'
        temp=runtime.with_suffix('.tmp')
        temp.write_text(json.dumps(config,indent=2)+'\n')
        os.replace(temp,runtime)
    print(json.dumps(config,indent=2))
