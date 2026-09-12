"""Explicit OOD extrapolation experiment. Never a supported forecast or bridge repair."""
import hashlib,json,math,sys
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
root=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(exist_ok=False)
paths={'ratings':root/'repair_0912/remote/run-20260912T110254Z/cfb_assimilated_state.json','model':root/'cfb_context_fix/results_02/model.json','parent':root/'cfb_context_fix/results_02/bundle.json'}
raw={k:p.read_bytes() for k,p in paths.items()};src={k:json.loads(v) for k,v in raw.items()};hashes={k:hashlib.sha256(v).hexdigest() for k,v in raw.items()}
r=next(r for r in src['parent']['rows'] if r['event_id']=='401858223');assert r['reason']=='FCS_BRIDGE_UNSUPPORTED'
e=src['ratings']['team_elo'];m=src['model'];mu=m['margin_coef'][0]+m['margin_coef'][1]*(e['SMU']-e['UC Davis'])/400;sigma=m['margin_sigma']
identity='cfb.fbs_margin_cross_division_extrapolation.test.v1';seed=int.from_bytes(hashlib.sha256((identity+':401858223:'+json.dumps(hashes,sort_keys=True)+':100000').encode()).digest()[:8],'big')
rng=np.random.default_rng(seed);draws=np.rint(rng.normal(mu,sigma,100000)).astype('<i2');line=-34.5
p=.5*math.erfc(-(mu+line)/(sigma*math.sqrt(2)));values,counts=np.unique(draws,return_counts=True)
b={'model_id':identity,'generated_at_utc':datetime.now(timezone.utc).isoformat(),'event_id':r['event_id'],'home':r['home'],'away':r['away'],'scheduled_start':r['start'],'status':'OOD_EXTRAPOLATION_TEST_NOT_SUPPORTED_FORECAST','parent_status':r['reason'],'source_hashes':hashes,'rating_cutoff':src['ratings']['cutoff_utc'],'source_forecast_cutoff':src['parent']['cutoff'],'ratings':{'SMU':e['SMU'],'UC Davis':e['UC Davis']},'formula':'frozen FBS intercept + frozen FBS slope * (home_elo-away_elo)/400','margin_coef':m['margin_coef'],'margin_sigma':sigma,'expected_home_margin':mu,'home_line':line,'model_home_cover':p,'sim_home_cover':float(np.mean(draws+line>0)),'p_push':0.,'n_sims':100000,'seed':seed,'draws_dtype':'<i2','draws_sha256':hashlib.sha256(draws.tobytes()).hexdigest(),'margin_quantiles':{f'p{q}':int(np.quantile(draws,q/100,method='inverted_cdf')) for q in [10,25,50,75,90]},'margin_histogram':{str(int(x)):int(y) for x,y in zip(values,counts)},'full_game_total':{'line':59.5,'status':'UNSUPPORTED','p_over':None,'p_under':None},'market_source':'USER_SUPPLIED_NOT_VERIFIED','market_observed_at':None,'price':None,'canonical_prospective_eligible':False,'action_authority':'OFF','limitations':['FBS_ONLY_TRAINING','FCS_FBS_RATING_SCALE_UNRECONCILED','NO_PLAYER_IMPACT','UNCALIBRATED_RESIDUAL_SCALE','NOT_A_LIVE_UPDATE','NO_BRIDGE_REPAIR_OR_PROMOTION']}
assert all(paths[k].read_bytes()==v for k,v in raw.items())
assert np.array_equal(draws,np.rint(np.random.default_rng(seed).normal(mu,sigma,100000)).astype('<i2'))
(out/'bundle.json').write_text(json.dumps(b,indent=2,allow_nan=False)+'\n');(out/'draws.bin').write_bytes(draws.tobytes())
print(json.dumps({k:v for k,v in b.items() if k!='margin_histogram'},indent=2))
