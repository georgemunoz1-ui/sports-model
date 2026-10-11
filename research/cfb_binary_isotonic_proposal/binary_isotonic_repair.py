"""Isolated numerical repair proposal for dormant binary helper, never a CDF map.

Independent gate and evidence-aware entry point. Does not modify registered code.
"""
from datetime import datetime
import hashlib,json
from pathlib import Path
import numpy as np
import sklearn
from sklearn.isotonic import IsotonicRegression

def stamp(x):
 d=datetime.fromisoformat(x.replace('Z','+00:00'))
 if d.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
 return d

def fit(scores,labels,*,base_model_id,calibration_rows,fitted_at,base_training_event_ids,sample_weight=None):
 if not isinstance(base_model_id,str) or not base_model_id.strip() or base_model_id!=base_model_id.strip():raise ValueError('BASE_MODEL_ID_REQUIRED')
 x=np.asarray(scores,float);y=np.asarray(labels,float)
 n=len(x)
 if x.ndim!=1 or y.shape!=x.shape or len(calibration_rows)!=n or not np.isfinite(x).all() or not np.isfinite(y).all() or np.any((x<0)|(x>1)) or np.any((y!=0)&(y!=1)):
  raise ValueError('BINARY_INPUT_INVALID')
 ids=[r['event_id'] for r in calibration_rows]
 if len(set(ids))!=n:raise ValueError('DUPLICATE_EVENT')
 if n<=10000:raise ValueError('ISOTONIC_REQUIRES_MORE_THAN_10000_INDEPENDENT_EVENTS')
 counts=np.bincount(np.minimum((x*10).astype(int),9),minlength=10)
 if min(counts)<500:raise ValueError('BROAD_BALANCED_BUCKET_COVERAGE_REQUIRED')
 for i in range(10):
  yi=y[np.minimum((x*10).astype(int),9)==i]
  if len(np.unique(yi))<2:raise ValueError('BOTH_LABELS_PER_BUCKET_REQUIRED')
 if set(ids)&set(base_training_event_ids):raise ValueError('TRAIN_CALIBRATION_OVERLAP')
 for r in calibration_rows:
  if not stamp(r['base_fit_cutoff'])<stamp(r['forecast_cutoff'])<stamp(r['start_time_utc'])<=stamp(r['result_available_at'])<stamp(fitted_at):
   raise ValueError('CHRONOLOGY_INVALID')
  if r.get('prediction_kind')!='CHRONOLOGICAL_OUT_OF_TIME':raise ValueError('OOS_REQUIRED')
 w=np.ones(n) if sample_weight is None else np.asarray(sample_weight,float)
 if w.shape!=x.shape or not np.isfinite(w).all() or np.any(w<=0):raise ValueError('WEIGHTS_INVALID')
 model=IsotonicRegression(increasing=True,y_min=0,y_max=1,out_of_bounds='clip').fit(x,y,sample_weight=w)
 result={'schema':'binary.isotonic.repair.proposal.v2','base_model_id':base_model_id,'method':'ISOTONIC','x':model.X_thresholds_.tolist(),'y':model.y_thresholds_.tolist(),
         'independent_event_n':n,'bucket_n':counts.tolist(),'training_event_ids':sorted(ids),'fit_as_of_utc':fitted_at,
         'out_of_bounds':'clip','increasing':True,'sklearn_version':sklearn.__version__,
         'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
         'historical_availability_status':'UNVERIFIED_INPUT_METADATA_NOT_SOURCE_PROOF',
         'training_sha256':hashlib.sha256(json.dumps({'x':x.tolist(),'y':y.tolist(),'w':w.tolist(),'rows':calibration_rows},sort_keys=True).encode()).hexdigest(),
         'status':'DORMANT_REPAIR_PROPOSAL_NOT_REGISTERED'}
 result['artifact_sha256']=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
 return result

def predict(model,scores,*,expected_base_model_id):
 if not isinstance(expected_base_model_id,str) or not expected_base_model_id.strip() or expected_base_model_id!=expected_base_model_id.strip():raise ValueError('EXPECTED_BASE_MODEL_ID_REQUIRED')
 a=dict(model);h=a.pop('artifact_sha256',None)
 if hashlib.sha256(json.dumps(a,sort_keys=True).encode()).hexdigest()!=h:raise ValueError('HASH_INVALID')
 if a.get('schema')!='binary.isotonic.repair.proposal.v2':raise ValueError('SCHEMA_INVALID')
 if a.get('base_model_id')!=expected_base_model_id:raise ValueError('BASE_MODEL_ID_MISMATCH')
 if a.get('code_sha256')!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():raise ValueError('CODE_DRIFT')
 knots=np.asarray(a['x'],float);values=np.asarray(a['y'],float)
 if knots.ndim!=1 or knots.shape!=values.shape or not len(knots) or not np.isfinite(knots).all() or not np.isfinite(values).all() or np.any(np.diff(knots)<=0) or np.any(np.diff(values)<0) or np.any((knots<0)|(knots>1)|(values<0)|(values>1)):raise ValueError('KNOTS_INVALID')
 x=np.asarray(scores,float)
 if not np.isfinite(x).all() or np.any((x<0)|(x>1)):raise ValueError('PROBABILITY_RANGE')
 return np.interp(x,model['x'],model['y'])
