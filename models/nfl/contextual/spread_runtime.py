"""Source-bound spread calibration overlay; frozen generation stays untouched."""
import datetime as dt,hashlib,json
from pathlib import Path
import numpy as np
from .recovered_inference import digest,utc
from .spread_calibration import (MODEL_ID,REFERENCE_ID,margin_distribution,price_spread,
    calibrated_distribution,simulate_margins)
ROOT=Path(__file__).resolve().parents[3]

def load_calibrator():
    p=ROOT/'data/nfl/spread_calibration_v1';r=json.loads((p/'runtime.json').read_text())
    path=p/r['model_file'];raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=r['model_sha256']:raise ValueError('CALIBRATOR_HASH_MISMATCH')
    model=json.loads(raw)
    if model['model_id']!=MODEL_ID or model['reference_model_id']!=REFERENCE_ID:raise ValueError('CALIBRATOR_MODEL_ID')
    # Bind evaluation conclusions as well as the fitted coefficients.
    ep=p/r['evaluation_file']
    if hashlib.sha256(ep.read_bytes()).hexdigest()!=r['evaluation_sha256']:raise ValueError('CALIBRATION_EVALUATION_HASH')
    return model,json.loads(ep.read_text())

def build_overlay(forecast,scores,home_handicaps,*,n=100000,model=None,evaluation=None):
    if model is None:model,evaluation=load_calibrator()
    now=dt.datetime.now(dt.timezone.utc)
    if utc(model['fitted_at_utc'])>now:raise ValueError('CALIBRATOR_FROM_FUTURE')
    if forecast['model_id']!=REFERENCE_ID or forecast.get('mode','research_pregame')!='research_pregame':raise ValueError('CALIBRATOR_REFERENCE_MISMATCH')
    if utc(forecast['cutoff_utc'])>now:raise ValueError('FORECAST_FROM_FUTURE')
    p=ROOT/'data/nfl/contextual_v1/model_packed.json'
    if hashlib.sha256(p.read_bytes()).hexdigest()!=model['reference_packed_artifact_sha256']:raise ValueError('CALIBRATOR_FOOTBALL_ARTIFACT_MISMATCH')
    from .model import load_artifact
    if digest(load_artifact(p))!=forecast['model_artifact_sha256']:raise ValueError('FORECAST_FOOTBALL_ARTIFACT_MISMATCH')
    scores=np.asarray(scores)
    if scores.ndim!=2 or scores.shape[1]!=2 or len(scores)==0 or not np.isfinite(scores).all() or (scores<0).any() or (scores!=np.rint(scores)).any():raise ValueError('INTEGER_FINAL_SCORE_ARRAY')
    summary=forecast['score_simulation']
    if summary['distribution']!='OUTCOME_ALIGNED_FINAL_SCORE_KERNEL_V2' or summary['target']!='FINAL_SCORE_INCLUDING_OVERTIME':raise ValueError('SCORE_TARGET_MISMATCH')
    if len(scores)!=summary['n'] or hashlib.sha256(scores.tobytes()).hexdigest()!=summary['sha256']:raise ValueError('SAVED_SCORE_ARRAY_HASH_MISMATCH')
    lines=list(home_handicaps)
    if not lines:raise ValueError('SPREAD_REQUIRED')
    margins=scores[:,0].astype(np.int64)-scores[:,1].astype(np.int64);support,mass=margin_distribution(margins)
    a,b=model['intercept'],model['slope'];cm,cw=calibrated_distribution(support,mass,a,b)
    # Seed does not depend on requested lines or prices; all alternate lines share draws.
    identity={'forecast_identity':forecast['identity'],'score_sha256':summary['sha256'],'calibrator_digest':digest(model),'n':n}
    seed=int(digest(identity)[:16],16);draws,sim=simulate_margins(cm,cw,seed,n)
    dm,dw=margin_distribution(draws);rows=[]
    for line in lines:
        for side in ['HOME','AWAY']:
            raw=price_spread(support,mass,line,side=side)
            cp=price_spread(support,mass,line,side=side,intercept=a,slope=b)
            mc=price_spread(dm,dw,line,side=side)
            rows.append({'team':forecast['event'][side.lower()+'_team'],'side':side,'handicap':float(line if side=='HOME' else -line),
                'raw':raw,'calibrated':cp,'calibrated_simulation':mc,
                'conditional_nonpush_probability':cp['win']/(cp['win']+cp['loss']) if cp['win']+cp['loss']>0 else None,
                'integer_line_warning':'PUSH_RELIABILITY_WORSENED_IN_HELDOUT_TEST' if line%1==0 else None})
    overlay={'schema':'nfl.spread_calibration_overlay.v1','created_at_utc':now.isoformat(),'information_regime':'NEW_RESEARCH_CALIBRATION_OF_FROZEN_FORECAST',
        'event':forecast['event'],'source_forecast_cutoff_utc':forecast['cutoff_utc'],'source_forecast_identity':forecast['identity'],
        'source_forecast_content_digest':digest(forecast),'source_score_array_sha256':summary['sha256'],'calibrator_digest':digest(model),
        'calibrator_id':MODEL_ID,'calibrator_fitted_at_utc':model['fitted_at_utc'],'reference_model_id':REFERENCE_ID,
        'calibrator_existed_at_original_forecast_cutoff':utc(model['fitted_at_utc'])<=utc(forecast['cutoff_utc']),
        'computed_before_kickoff':now<utc(forecast['event']['start_time_utc']),'original_forecast_mutated':False,
        'contracts':rows,'simulation':sim,'retrospective_screen_passed':evaluation['retrospective_screen_passed'],
        'calibration_reliability_established':False,'market_superiority_established':False,'canonical_prospective_eligible':False,
        'action_authority':False,'warnings':['REUSED_RETROSPECTIVE_HISTORY','CALIBRATED_NONPUSH_BRIER_WORSE_THAN_MARKET_BENCHMARK',
            'INTEGER_PUSH_RELIABILITY_WORSENED','CURRENT_PROBABILITIES_ARE_RESEARCH_TRANSFORM_NOT_ORIGINAL_FORECAST',
            'TOTAL_AND_FIRST_HALF_NOT_CALIBRATED','PRICES_FEES_AND_EXECUTION_NOT_EVALUATED']}
    return overlay,draws

def persist_overlay(folder,overlay,draws):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    (folder/'overlay.json').write_text(json.dumps(overlay,indent=2,allow_nan=False))
    np.save(folder/'calibrated_margin_draws.npy',draws,allow_pickle=False)
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2))
