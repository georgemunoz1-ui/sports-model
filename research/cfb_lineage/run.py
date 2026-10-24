"""Executed source/registry/storage pilot, not a CFB modeling or forecast run."""
from __future__ import annotations
import argparse,datetime as dt,hashlib,importlib.metadata,json,os
from pathlib import Path
import shutil,subprocess,sys
import pandas as pd
import yaml
from .core import Store,canonical,digest,now,require
from .registry import export_tables,feature_set,TABLES
from .catalogue import definitions,SOURCE_POLICIES
from .schemas import SCHEMAS
from .fixture import build_fixture


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:json.dump(value,f,indent=2,allow_nan=False)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked(args,cwd,log):
    with Path(log).open('w') as f:
        result=subprocess.run(args,cwd=cwd,stdout=f,stderr=subprocess.STDOUT,timeout=300)
    require(result.returncode==0,'COMMAND_FAILED',command=args,exit=result.returncode,log=str(log))


def source_audit(capture,out,store):
    manifest=json.loads((capture/'manifest.json').read_text())
    for rel,h in manifest.items():
        p=(capture/rel).resolve()
        require(p.is_relative_to(capture.resolve()) and sha(p)==h,'CAPTURE_HASH_MISMATCH',path=rel)
    receipts=json.loads((capture/'receipts.json').read_text());report=[];sets={};sources={};paths=[]
    for r in receipts:
        if r['status']!='CAPTURED' or 'source_family' not in r:continue
        p=capture/'raw'/r['name'];family={'cfbfastR_cfb_pbp':'cfbfastR_legacy_pbp','espn_cfb_pbp':'espn_cfb_pbp','cfb_schedules':'cfbd_schedule_release','cfb_ratings_weekly':'cfb_ratings_weekly'}[r['source_family']]
        body=p.read_bytes();require(hashlib.sha256(body).hexdigest()==r['sha256'],'RAW_RECEIPT_MISMATCH')
        raw=store.blob(body)
        h=store.put('raw_source',{'raw_hash':raw,'source_family':family,'source_url':r['url'],'retrieved_at':r['retrieved_at'],'available_at':r['retrieved_at'],
            'receipt':r,'upstream_capture_manifest_hash':sha(capture/'manifest.json'),'imported_at':now(),'historical_as_of_certified':False,
            'upstream_model_hash':None,'license_approval':'NOT_REVIEWED','evidence_scope':'REAL_SOURCE_CAPTURE_NOT_PREGAME_FEATURE'})
        store.bind('source:'+r['name'],h);sources[family]=h
        d=pd.read_parquet(p);info={'family':family,'source_hash':raw,'source_node_hash':h,'rows':len(d),'columns':len(d.columns),'unique_game_ids':None,
            'mode':'SOURCE_AUDIT_ONLY','predictive_feature_rows_created':0,'upstream_model_generation_verified':False}
        if 'game_id' in d:
            ids=set(d.game_id.dropna().map(lambda v:str(int(v)) if isinstance(v,(int,float)) else str(v)));sets[family]=ids;info['unique_game_ids']=len(ids)
        if 'EPA' in d:info['epa_present_rows']=int(d.EPA.notna().sum())
        if family=='cfbd_schedule_release':
            info['completed_rows']=int(d.completed.fillna(False).sum())
            info['home_divisions']=d.home_division.fillna('UNKNOWN').astype(str).value_counts().to_dict()
            info['away_divisions']=d.away_division.fillna('UNKNOWN').astype(str).value_counts().to_dict()
            info['start_time_tbd_rows']=int(d.start_time_tbd.fillna(True).sum())
        if family=='cfb_ratings_weekly':
            info['effective_weeks']=sorted(int(x) for x in d.through_week.dropna().unique())
            info['publication_time_verified']=False
        info['column_names']=[str(c) for c in d.columns];report.append(info);paths.append(p)
    require(len(report)==4,'EXPECTED_FOUR_SOURCE_FAMILIES')
    legacy=sets['cfbfastR_legacy_pbp'];espn=sets['espn_cfb_pbp'];scheduled=sets['cfbd_schedule_release']
    coverage={'legacy_unique_games':len(legacy),'espn_unique_games':len(espn),'shared_game_ids':len(legacy&espn),
              'legacy_only_game_ids':sorted(legacy-espn),'espn_only_game_ids':sorted(espn-legacy),
              'legacy_ids_not_in_schedule_release':sorted(legacy-scheduled),'espn_ids_not_in_schedule_release':sorted(espn-scheduled),
              'meaning':'ID_SET_COMPARISON_ONLY; NO_TEAM_OR_FINAL_SCORE_RECONCILIATION_CLAIM','families_merged':False}
    auth=[r for r in receipts if r['name']=='cfbd-games-no-auth.json']
    save(out/'source_audit.json',{'families':report,'coverage':coverage,'direct_cfbd_attempt':auth,'verified_capture_manifest_entries':len(manifest),
        'source_failures':[r for r in receipts if r['status']!='CAPTURED'],'live_ready':False})
    root=store.put('source_inventory',{'rows':report,'scope':'REAL_SOURCE_SCHEMA_AUDIT'},sources)
    save(out/'source_graph_verification.json',store.verify(root))
    return report,coverage,root,paths


def storage_smoke(out,registry,source_paths):
    """Exercise real DVC and MLflow locally. No hosted service or trained model."""
    root=out/'dvc_smoke';root.mkdir();data=root/'artifacts';data.mkdir()
    shutil.copytree(registry,data/'registry')
    raw=data/'raw';raw.mkdir()
    for p in source_paths:shutil.copyfile(p,raw/p.name)
    hashes={str(p.relative_to(data)):sha(p) for p in data.rglob('*') if p.is_file()}
    save(root/'expected.json',hashes)
    (root/'verify.py').write_text("import pathlib,json,hashlib\np=pathlib.Path('artifacts');expected=json.load(open('expected.json'))\nfor rel,h in expected.items():\n assert hashlib.sha256((p/rel).read_bytes()).hexdigest()==h,rel\npathlib.Path('verified.json').write_text(json.dumps({'status':'PASS','files':len(expected)}))\n")
    (root/'dvc.yaml').write_text(yaml.safe_dump({'stages':{'verify_hashes':{'cmd':sys.executable+' verify.py','deps':['artifacts','expected.json','verify.py'],'outs':['verified.json']}}},sort_keys=False))
    commands=[['git','init','-q'],['dvc','init','-q'],['dvc','add','artifacts'],['dvc','repro'],['dvc','repro']]
    for i,cmd in enumerate(commands):checked(cmd,root,out/f'dvc_command_{i}.txt')
    status=subprocess.check_output(['dvc','status','--json'],cwd=root,text=True,timeout=120)
    require(json.loads(status)=={},'DVC_DIRTY_AFTER_REPLAY',status=status)
    save(out/'dvc_proof.json',{'status':'PASS','tracked_source_and_registry_files':len(hashes),'status_json':json.loads(status),'pipeline_lock_hash':sha(root/'dvc.lock'),
        'data_pointer_hash':sha(root/'artifacts.dvc'),'remote_configured':False,'scope':'LOCAL_SCRATCH_PIPELINE_NOT_PRODUCTION_REBUILD','two_repro_calls_completed':True})
    import mlflow
    mlflow.set_tracking_uri('sqlite:///'+str((out/'mlflow.sqlite').resolve()))
    client=mlflow.MlflowClient();eid=client.create_experiment('CFB_LINEAGE_INFRASTRUCTURE_ONLY',artifact_location=(out/'mlflow_artifacts').resolve().as_uri())
    d=pd.read_parquet(registry/'feature_definitions.parquet')[['feature_id','source_family','definition_hash']]
    dataset=mlflow.data.from_pandas(d,source=str((registry/'feature_definitions.parquet').resolve()),name='cfb_definitions_candidate_v1')
    with mlflow.start_run(experiment_id=eid,run_name='source-registry-audit-no-training') as run:
        mlflow.log_input(dataset,context='registry_integrity_audit')
        mlflow.set_tags({'sport':'CFB','run_role':'INFRASTRUCTURE_NOT_MODEL_TRAINING','action_authority':'OFF','predictive_validation':'NOT_RUN'})
        mlflow.log_params({'definitions_file_sha256':sha(registry/'feature_definitions.parquet'),'dvc_lock_sha256':sha(root/'dvc.lock'),
            'code_commit':os.environ.get('GITHUB_SHA','LOCAL_UNCOMMITTED_NOT_RELEASED'),'feature_set_manifest_sha256':sha(out/'configs/cfb_pregame_core_v1.yaml')})
        mlflow.log_metrics({'registered_definitions':len(d),'trained_models':0,'live_forecasts':0})
        mlflow.log_artifact(str(out/'source_audit.json'));mlflow.log_artifact(str(out/'configs/cfb_pregame_core_v1.yaml'))
        rid=run.info.run_id
    got=client.get_run(rid);require(got.info.status=='FINISHED' and len(got.inputs.dataset_inputs)==1,'MLFLOW_DATASET_LINK_FAILED')
    save(out/'mlflow_proof.json',{'status':'PASS','run_id':rid,'experiment_id':eid,'dataset_digest':dataset.digest,'dataset_inputs':1,
         'scope':'LOCAL_SQLITE_INFRASTRUCTURE_RUN','hosted_tracking_connected':False,'trained_models_registered':0,'model_metrics_not_logged':True})
    # Keep actual .dvc files, dvc.lock and MLflow DB/artifacts. Large raw bodies
    # already exist in source capture; do not claim this slim evidence is a remote cache.
    shutil.rmtree(root/'artifacts');shutil.rmtree(root/'.dvc/cache',ignore_errors=True);shutil.rmtree(root/'.git',ignore_errors=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--capture',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--storage-smoke',action='store_true');a=p.parse_args()
    out=a.output;out.mkdir(parents=True,exist_ok=False);store=Store(out/'graph')
    source,coverage,source_root,paths=source_audit(a.capture,out,store)
    defs=definitions();set_hash=feature_set(store,'cfb_pregame_core_v1',defs,[])
    registry_rows=[{**d,'definition_json':d} for d in defs]
    table_manifest=export_tables(out/'registry',{'feature_definitions':registry_rows})
    save(out/'configs/source_families.json',SOURCE_POLICIES)
    config={'feature_set_id':'cfb_pregame_core_v1','feature_set_artifact_hash':set_hash,'sport':'CFB','mode':'RESEARCH_DEFINITION_ONLY',
        'status':'REGISTERED_NOT_ACTIVATED','feature_ids':[d['feature_id'] for d in defs],'required_features':[],
        'required_feature_selection_status':'BLOCKED_PENDING_TRAINING_AND_PREDECLARED_ABLATION','market_input':False,'action_authority':False,
        'mixed_pbp_families':False,'definitions_content_hash':digest(defs)}
    (out/'configs/cfb_pregame_core_v1.yaml').write_text(yaml.safe_dump(config,sort_keys=False))
    for name,schema in SCHEMAS.items():save(out/'contracts'/(name+'.json'),schema)
    save(out/'feature_set_graph_verification.json',store.verify(set_hash))
    synthetic=build_fixture(Store(out/'synthetic_fixture_graph'));save(out/'synthetic_graph_proof.json',synthetic)
    if a.storage_smoke:storage_smoke(out,out/'registry',paths)
    versions={}
    for name in ('pandas','pyarrow','jsonschema','PyYAML','cfbd','dvc','mlflow'):
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]=None
    save(out/'versions.json',versions)
    result={'completed_at':now(),'role':'CFB_LINEAGE_INFRASTRUCTURE_PILOT','source_families_captured':len(source),'registered_features':len(defs),'contracts':len(SCHEMAS),
        'registry_rows':{k:v['rows'] for k,v in table_manifest.items()},'source_game_id_overlap':coverage,'synthetic_graph_nodes':synthetic['proof']['node_count'],
        'real_model_paths':0,'trained_cfb_models':0,'live_forecasts':0,'live_state_updates':0,'cfbd_authenticated_acquisition':'NOT_RUN; UNAUTHENTICATED_PROBE_RETURNED_401',
        'feature_ablation':'NOT_RUN','predictive_accuracy':'NOT_EVALUATED','nfl_default_modified':False,'action_authority':False,'dose':0.,
        'blockers':['CFBD authorized capture not available in this run','Independent complete-week provider binding not approved','Upstream EPA model generation and historical PIT not pinned',
                    'Historical metric transforms, model fitting and ablations not completed','Prospective state-to-real-forecast proof not completed','Production global health remains RED'],
        'storage_smoke_requested':a.storage_smoke}
    save(out/'completion.json',result)
    save(out/'manifest.json',{str(f.relative_to(out)):sha(f) for f in sorted(out.rglob('*')) if f.is_file()})
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
