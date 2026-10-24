#!/usr/bin/env python3
"""Real-time, two-phase research input seal and reproducible inference.

GitHub uploads the input archive before the execution job starts. This is an
operational research receipt, not a canonical release authorization.
"""
from __future__ import annotations
import argparse,datetime as dt,hashlib,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from models.nfl.contextual.recovered_inference import digest,utc
from models.nfl.contextual.assimilation import write_once
EVENT='2026_02_DET_BUF';MODEL='nfl.integrated_context.qb.v1.research'

def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,reason):
    if not ok:raise ValueError(reason)
def command(args):return subprocess.check_output(args,cwd=ROOT,text=True).strip()
def verify_manifest(root,manifest):
    for name,expected in manifest.items():
        path=(root/name).resolve();require(path.is_relative_to(root.resolve()),'UNSAFE_MANIFEST_PATH')
        require(path.is_file() and sha(path)==expected,'MANIFEST_MISMATCH:'+name)
def code_pins():
    folders=['models/nfl','pipelines/cards']
    paths=[p for folder in folders for p in (ROOT/folder).rglob('*.py')]
    paths += [ROOT/'scripts/run_nfl_integrated.py',ROOT/'scripts/prepare_nfl_event.py',ROOT/'scripts/prepare_det_buf_20260917.py',ROOT/'scripts/seal_det_buf_20260917.py']
    paths += list((ROOT/'data/nfl/contextual_v1').glob('*.json'))+list((ROOT/'data/model_selection').glob('*.json'))
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted(set(paths))}
def preflight(folder,seal=None):
    event=json.loads((folder/'event.json').read_text())
    require(event['event_id']==EVENT,'EVENT_BINDING')
    require(utc(now())<utc(event['start_time_utc']),'NOT_PREGAME')
    if seal is not None:
        record=dict(seal);claimed=record.pop('record_hash');require(digest(record)==claimed,'WRITER_HASH_MISMATCH')
        require(utc(seal['created_at_utc'])<=utc(now()),'FUTURE_WRITER')
        require(seal['source_commit']==command(['git','rev-parse','HEAD']),'CODE_COMMIT_CHANGED')
        require(code_pins()==seal['code_and_model_pins'],'CODE_OR_MODEL_CHANGED')
    return event

def prepare(folder):
    event=preflight(folder)
    require((folder/'event_package.json').is_file(),'PACKAGE_MISSING')
    code=folder/'code.tar.gz'
    with code.open('xb') as stream:subprocess.run(['git','archive','--format=tar.gz','HEAD'],cwd=ROOT,stdout=stream,check=True)
    require(command(['git','diff','--name-only'])=='','DIRTY_TRACKED_CODE')
    manifest={str(p.relative_to(folder)):sha(p) for p in sorted(folder.rglob('*')) if p.is_file()}
    write_once(folder/'input_manifest.json',manifest)
    stamp=now()
    record={'schema':'nfl.research_preexecution_seal.v1','created_at_utc':stamp,'event_id':EVENT,'start_time_utc':event['start_time_utc'],'source_commit':command(['git','rev-parse','HEAD']),'github_run_id':os.environ.get('GITHUB_RUN_ID'),'package_sha256':sha(folder/'event_package.json'),'input_manifest_sha256':sha(folder/'input_manifest.json'),'code_archive_sha256':sha(code),'code_and_model_pins':code_pins(),'model_id':MODEL,'simulations':100000,'mode':'research_pregame','canonical_prospective_eligible':False,'official_release_eligible':False,'action_authority':False,'dose':0.0,'previous_hash':None,'registration_scope':'REAL_WRITER_BEFORE_INFERENCE; EXTERNAL_INPUT_ARTIFACT_UPLOAD_REQUIRED_BEFORE_EXECUTION'}
    record['record_hash']=digest(record);write_once(folder/'writer_seal.json',record)
    print(json.dumps({'stage':'INPUT_SEALED_NOT_RUN','writer':stamp,'seal_sha256':sha(folder/'writer_seal.json'),'package_sha256':record['package_sha256'],'input_manifest_sha256':record['input_manifest_sha256']}))

def execute(folder,artifact_id,artifact_digest):
    seal=json.loads((folder/'writer_seal.json').read_text());event=preflight(folder,seal)
    require(sha(folder/'input_manifest.json')==seal['input_manifest_sha256'],'INPUT_MANIFEST_CHANGED')
    verify_manifest(folder,json.loads((folder/'input_manifest.json').read_text()))
    require(bool(artifact_id) and len(artifact_digest.removeprefix('sha256:'))==64,'EXTERNAL_ARTIFACT_ANCHOR_REQUIRED')
    require(command(['git','diff','--name-only'])=='','DIRTY_TRACKED_CODE')
    write_once(folder/'execution_start.json',{'created_at_utc':now(),'preexecution_writer_hash':seal['record_hash'],'preexecution_writer_file_sha256':sha(folder/'writer_seal.json'),'external_input_artifact_id':artifact_id,'external_input_artifact_sha256':artifact_digest,'github_run_id':os.environ.get('GITHUB_RUN_ID'),'external_receipt_scope':'GitHub immutable artifact uploaded in prerequisite job; not independent source-authorship or canonical-release clearance','official_release_eligible':False,'action_authority':False})
    env={**os.environ,'NFL_CONTEXT_PACKAGE':str((folder/'event_package.json').resolve())}
    for label in ['primary','replay']:
        cmd=[sys.executable,'scripts/run_nfl_integrated.py','--date','2026-09-17','--event-id',EVENT,'--output',str(folder/label),'--simulations','100000']
        with (folder/(label+'.stdout.txt')).open('x') as log:subprocess.run(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    primary=folder/'primary'/EVENT;replay=folder/'replay'/EVENT
    for path in [primary,replay]:verify_manifest(path,json.loads((path/'manifest.json').read_text()))
    first=json.loads((primary/'forecast.json').read_text());second=json.loads((replay/'forecast.json').read_text())
    a=np.load(primary/'winner_draws.npy',allow_pickle=False);b=np.load(replay/'winner_draws.npy',allow_pickle=False)
    require(first['model_id']==second['model_id']==MODEL,'DEFAULT_MODEL_CHANGED')
    require(first['identity']==second['identity'],'REPLAY_IDENTITY_MISMATCH')
    require(np.array_equal(a,b) and a.shape==(100000,),'REPLAY_ARRAY_MISMATCH')
    require(sha(primary/'winner_draws.npy')==sha(replay/'winner_draws.npy'),'REPLAY_FILE_BYTES_MISMATCH')
    require(first['prediction']==second['prediction'],'REPLAY_PREDICTION_MISMATCH')
    require(first['winner_simulation']==second['winner_simulation'],'REPLAY_SEED_OR_STATS_MISMATCH')
    require(first['action_authority'] is False and first['canonical_prospective_eligible'] is False,'AUTHORITY_ESCALATION')
    require(first['assimilation']['status']=='VERIFIED_RESEARCH_STATE_FLOW','STATE_FLOW_NOT_VERIFIED')
    require(first['audit']['final_availability']['status']=='VERIFIED','FINAL_INACTIVES_NOT_VERIFIED')
    require(not (primary/'score_draws.npy').exists(),'QB_ARM_BORROWED_SCORE_KERNEL')
    verify_manifest(folder,json.loads((folder/'input_manifest.json').read_text()))
    verify={'status':'PASS','verified_at_utc':now(),'draw_count':int(a.size),'home_win_draws':int(a.sum()),'away_win_draws':int(a.size-a.sum()),'winner_draws_file_sha256':sha(primary/'winner_draws.npy'),'draws_raw_sha256':hashlib.sha256(a.tobytes()).hexdigest(),'exact_replay':True,'input_hashes_unchanged':True,'forecast_identity':first['identity'],'source_commit':seal['source_commit'],'preexecution_writer_utc':seal['created_at_utc'],'primary_cutoff_utc':first['cutoff_utc'],'primary_registration':json.loads((primary/'registration.jsonl').read_text()),'model_id':MODEL,'analytical_prediction':first['prediction'],'winner_simulation':first['winner_simulation'],'analytic_comparisons':{arm:v['prediction'] for arm,v in first['arms'].items()},'assimilation':first['assimilation'],'coherence':first['coherence'],'score_simulation':first['score_simulation'],'external_input_artifact_id':artifact_id,'external_input_artifact_sha256':artifact_digest,'official_release_eligible':False,'action_authority':False,'dose':0.0}
    write_once(folder/'verification.json',verify)
    manifest={str(p.relative_to(folder)):sha(p) for p in sorted(folder.rglob('*')) if p.is_file()}
    write_once(folder/'completed_manifest.json',manifest)
    compact={k:verify[k] for k in ['status','model_id','home_win_draws','away_win_draws','analytical_prediction','winner_simulation','exact_replay','primary_cutoff_utc','preexecution_writer_utc','forecast_identity','official_release_eligible','action_authority','dose']}
    compact['completed_manifest_sha256']=sha(folder/'completed_manifest.json')
    write_once(folder/'COMPLETION.json',compact)
    print(json.dumps(compact,indent=2))

def main():
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','execute']);p.add_argument('--folder',type=Path,required=True);p.add_argument('--artifact-id');p.add_argument('--artifact-digest');a=p.parse_args()
    if a.phase=='prepare':prepare(a.folder)
    else:execute(a.folder,a.artifact_id,a.artifact_digest)
if __name__=='__main__':main()
