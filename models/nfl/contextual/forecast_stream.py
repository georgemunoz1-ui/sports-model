"""Append-only local forecast stream; external Git anchoring is recorded separately."""
import datetime as dt,json,fcntl
from pathlib import Path
from .recovered_inference import digest,utc

def append_forecast_record(path,bundle,manifest_hash):
    now=dt.datetime.now(dt.timezone.utc)
    if bundle.get('mode')!='live' and now>=utc(bundle['event']['start_time_utc']):raise ValueError('STREAM_WRITER_AFTER_KICKOFF')
    if utc(bundle['cutoff_utc'])>now:raise ValueError('STREAM_FUTURE_CUTOFF')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+') as f:
        fcntl.flock(f,fcntl.LOCK_EX);f.seek(0);previous=None
        for line in f:
            row=json.loads(line);hash_=row.pop('record_hash')
            if row['previous_hash']!=previous or digest(row)!=hash_:raise ValueError('FORECAST_STREAM_CHAIN_INVALID')
            previous=hash_
        record={'created_at_utc':now.isoformat(),'event_id':bundle['event']['event_id'],'model_id':bundle['model_id'],
          'mode':bundle['mode'],'forecast_identity':bundle['identity'],'cutoff_utc':bundle['cutoff_utc'],
          'model_artifact_sha256':bundle['model_artifact_sha256'],'artifact_manifest_sha256':manifest_hash,
          'reporter_sha256':bundle.get('capability_report',{}).get('reporter_sha256'),
          'prediction':bundle['prediction'],'simulation':bundle['score_simulation'],'previous_hash':previous,
          'decision':'NO_BET_RESEARCH_ONLY','promotion_eligible':False,'external_anchor':'pending_git_commit'}
        record['record_hash']=digest(record);f.write(json.dumps(record,allow_nan=False)+'\n');f.flush()
        return record
