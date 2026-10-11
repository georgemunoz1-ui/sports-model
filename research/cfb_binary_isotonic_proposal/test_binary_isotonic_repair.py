import json
import numpy as np
import pytest
from sklearn.isotonic import IsotonicRegression
import original_calibration as old
import binary_isotonic_repair as fixed

def test_legacy_reproduction_wrong_threshold_and_bypass():
 x=[.1]*125+[.2]*125+[.8]*125+[.9]*125;y=[1]*125+[0]*125+[0]*125+[1]*125
 assert old.gate_method(500)=='PLATT'
 assert old.fit('ISOTONIC',x,y)['predict'](.2)==1
 assert IsotonicRegression().fit(x,y).predict([.2])[0]==pytest.approx(1/3)

def inputs(n=12000):
 x=(np.arange(n)%10+.5)/10
 y=(np.arange(n)//10)%2
 rows=[{'event_id':str(i),'base_fit_cutoff':'2022-01-01T00:00:00Z','forecast_cutoff':'2024-01-01T00:00:00Z','start_time_utc':'2024-01-02T00:00:00Z','result_available_at':'2024-01-03T00:00:00Z','prediction_kind':'CHRONOLOGICAL_OUT_OF_TIME'} for i in range(n)]
 return x,y,rows

def run(x,y,rows,**extra):
 return fixed.fit(x,y,base_model_id=extra.pop('base_model_id','cfb.binary.fixture.v1.home_win.full_game_ot'),calibration_rows=rows,fitted_at='2024-02-01T00:00:00Z',base_training_event_ids=['old'],**extra)

def test_repaired_weighted_ties_match_sklearn():
 x,y,r=inputs();w=1+np.arange(len(x))%3
 a=run(x,y,r,sample_weight=w);p=np.linspace(0,1,101)
 expected=IsotonicRegression(increasing=True,y_min=0,y_max=1,out_of_bounds='clip').fit(x,y,sample_weight=w).predict(p)
 assert np.array_equal(fixed.predict(a,p,expected_base_model_id='cfb.binary.fixture.v1.home_win.full_game_ot'),expected)
 assert a['independent_event_n']==12000

def test_eligibility_and_duplicate_refusals():
 x,y,r=inputs(500)
 with pytest.raises(ValueError):run(x,y,r)
 x,y,r=inputs();r[-1]['event_id']=r[0]['event_id']
 with pytest.raises(ValueError):run(x,y,r)
 x,y,r=inputs();x[:]=.5
 with pytest.raises(ValueError):run(x,y,r)

def test_chronology_and_hash_refusals():
 x,y,r=inputs();r[0]['base_fit_cutoff']='2024-01-02T00:00:00Z'
 with pytest.raises(ValueError):run(x,y,r)
 x,y,r=inputs();a=run(x,y,r);a['y'][0]=.123
 with pytest.raises(ValueError):fixed.predict(a,[.2],expected_base_model_id='cfb.binary.fixture.v1.home_win.full_game_ot')


def test_model_binding_and_serialized_replay():
 x,y,r=inputs();a=run(x,y,r);base_id='cfb.binary.fixture.v1.home_win.full_game_ot'
 assert a['base_model_id']==base_id
 restored=json.loads(json.dumps(a))
 assert np.array_equal(fixed.predict(a,[.2,.8],expected_base_model_id=base_id),fixed.predict(restored,[.2,.8],expected_base_model_id=base_id))
 with pytest.raises(ValueError,match='BASE_MODEL_ID_MISMATCH'):
  fixed.predict(a,[.2],expected_base_model_id='cfb.other_version.home_win.full_game_ot')
 with pytest.raises(TypeError):fixed.predict(a,[.2])
 with pytest.raises(TypeError):fixed.fit(x,y,calibration_rows=r,fitted_at='2024-02-01T00:00:00Z',base_training_event_ids=['old'])
 for invalid in ('',' ',None,' padded '):
  with pytest.raises(ValueError,match='BASE_MODEL_ID_REQUIRED'):run(x,y,r,base_model_id=invalid)
  with pytest.raises(ValueError,match='EXPECTED_BASE_MODEL_ID_REQUIRED'):fixed.predict(a,[.2],expected_base_model_id=invalid)
