#!/usr/bin/env python3
"""Replay pinned real sources without importing code from the audited branches."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from models.nfl.contextual import weekly_state as ws
from models.nfl.contextual.assimilation import advance_states, serialize_states
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.recovered_inference import digest


def manifest(root, name):
    m=json.loads((root/name).read_text())
    for rel,h in m.items():
        p=(root/rel).resolve()
        if not p.is_relative_to(root.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest()!=h:
            raise ValueError('ARTIFACT_MANIFEST_MISMATCH:'+rel)
    return len(m)


def main():
    p=argparse.ArgumentParser();p.add_argument('--frozen',type=Path,required=True);p.add_argument('--capture',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    checks={'frozen_manifest_entries':manifest(a.frozen,'completed_manifest.json'),'capture_manifest_entries':manifest(a.capture,'manifest.json')}
    receipts={r['filename']:r for r in json.loads((a.capture/'sources/receipt.json').read_text())}
    schedule=ws.capture(a.capture/'sources/games.csv',receipts['games.csv'])
    pbp=ws.capture(a.capture/'sources/play_by_play_2026.csv',receipts['play_by_play_2026.csv'])
    model=load_artifact(ROOT/'data/nfl/contextual_v1/model_packed.json')
    historical=json.loads((a.frozen/'historical_state.json').read_text())
    stamp=dt.datetime.now(dt.timezone.utc).isoformat();store=a.output/'state'
    seed=ws.initialize(store,historical,schedule,model,stamp)
    first=ws.advance(store,seed,seed,model,schedule,pbp,1,stamp)
    state=ws.load_verified(store,first,model,stamp,seed)
    original=json.loads((a.frozen/'context.json').read_text())['assimilation']
    checks['team_state_equals_frozen_week1']=state['team_state']==original['state_after']
    from models.nfl.contextual.qb_assimilation import verified
    checks['qb_state_equals_frozen_week1']=state['qb_state']==verified(model,original)
    if not checks['team_state_equals_frozen_week1'] or not checks['qb_state_equals_frozen_week1']:
        raise AssertionError('Frozen rules replay differs; investigate before acceptance')
    checks['identical_retry_same_state_id']=ws.advance(store,seed,seed,model,schedule,pbp,1,stamp)==first
    before=(store/'HEAD').read_bytes()
    try:ws.advance(store,first,seed,model,schedule,pbp,1,stamp)
    except ValueError as e:checks['repeated_week_refusal']=str(e)
    else:raise AssertionError('Repeated week accepted')
    # Use full supplied Week2 schedule; a single completed game must not release.
    try:ws.advance(store,first,seed,model,schedule,pbp,2,stamp)
    except ValueError as e:
        if not str(e).startswith('WEEK_INCOMPLETE_OR_CONFLICTED'):raise
        checks['week2_release']='BLOCKED_INCOMPLETE_REAL_SOURCE'
    else:raise AssertionError('Pinned one-final Week2 source unexpectedly released')
    frame=pd.read_csv(a.capture/'sources/games.csv',low_memory=False)
    truncated=frame[frame.game_id=='2026_02_DET_BUF'].to_csv(index=False)
    cut={'text':truncated,'receipt':{**schedule['receipt'],'sha256':hashlib.sha256(truncated.encode()).hexdigest()}}
    try:ws.advance(store,first,seed,model,cut,pbp,2,stamp)
    except ValueError as e:checks['truncated_schedule_refusal']=str(e)
    else:raise AssertionError('Truncated schedule accepted')
    if (store/'HEAD').read_bytes()!=before:raise AssertionError('Rejected update mutated HEAD')
    checks.update({'seed_id':seed,'state_id':first,'completed_week':state['completed_week'],
                   'pbp_sha256':pbp['receipt']['sha256'],'schedule_sha256':schedule['receipt']['sha256'],
                   'source_game_count':int(pd.read_csv(a.capture/'sources/play_by_play_2026.csv',usecols=['game_id']).game_id.nunique()),
                   'code':ws.code_identity(),'current_week3_state':'NOT_CREATED',
                   'scope':'REAL_SOURCE_RETROSPECTIVE_REPLAY; NOT_CURRENT_LIVE_STATE',
                   'action_authority':False,'checks_passed':True})
    (a.output/'acceptance.json').write_text(json.dumps(checks,indent=2)+'\n');print(json.dumps(checks,indent=2))


if __name__=='__main__':main()
