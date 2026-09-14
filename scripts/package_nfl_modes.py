#!/usr/bin/env python3
import argparse,base64,datetime as dt,gzip,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.recovered_inference import digest

def main():
 p=argparse.ArgumentParser();p.add_argument('--fit',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(exist_ok=True,parents=True);manifest=json.loads((a.fit/'fit_manifest.json').read_text());entries={}
 for mode,name in [('enhanced_pregame','market'),('live','live')]:
  source=a.fit/(name+'_model.json');artifact=load_artifact(source);artifact['fit_completed_at_utc']=manifest['completed_at_utc'];artifact['deployment_packaged_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat();artifact['source_fit_artifact_sha256']=hashlib.sha256(source.read_bytes()).hexdigest();raw=json.dumps(artifact,sort_keys=True,separators=(',',':'),allow_nan=False).encode();path=a.output/(name+'_model.json')
  with path.open('x') as f:json.dump({'encoding':'GZIP_BASE64','sha256':hashlib.sha256(raw).hexdigest(),'payload':base64.b64encode(gzip.compress(raw,mtime=0)).decode()},f)
  entries[mode]={'file':path.name,'model_id':artifact['model_id'],'model_digest':digest(artifact),'prediction_status':'FITTED_RESEARCH_NOT_PRODUCTION_PROMOTION'}
 with (a.output/'runtime.json').open('x') as f:json.dump({'schema':'nfl.operating_modes.v1','models':entries,'silent_fallback':False,'live_current_game_state_required':True,'official_pregame_model':None},f,indent=2)
if __name__=='__main__':main()
