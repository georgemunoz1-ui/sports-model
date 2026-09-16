#!/usr/bin/env python3
"""Read-only eight-step trace of a frozen V2 forecast; writes a separate audit."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from models.nfl.contextual.model import load_artifact,simulate_joint
from models.nfl.contextual.joint_distribution import kernel,summary,contract
from models.nfl.contextual.recovered_inference import predict,digest

def audit(folder):
    folder=Path(folder);manifest=json.loads((folder/'manifest.json').read_text())
    for name,sha in manifest.items():
        if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=sha:raise ValueError('FROZEN_BYTES_CHANGED:'+name)
    f=json.loads((folder/'forecast.json').read_text());model=load_artifact(ROOT/'data/nfl/contextual_v1/model_packed.json')
    if digest(model)!=f['model_artifact_sha256']:raise ValueError('FROZEN_MODEL_MISMATCH')
    params=model['arms']['combined'];features={k:f['features'][k] for k in params['feature_names']};p=predict(params,features)['prediction']
    if p!=f['prediction']:raise ValueError('FROZEN_PREDICTION_NOT_REPRODUCED')
    args=(p['home_margin'],p['total_points'],p['home_win'],model['final_score_residuals'],model['simulation_v2']['tie_rate'])
    scores=np.load(folder/'score_draws.npy');replay,mc=simulate_joint(*args,f['identity'],len(scores))
    if not np.array_equal(scores,replay):raise ValueError('FROZEN_DRAWS_NOT_REPRODUCED')
    support,weights=kernel(*args);exact=summary(support,weights);margin=support[:,0]-support[:,1]
    return {'status':'EIGHT_STEP_TRACE_REPRODUCED','forecast_identity':f['identity'],'forecast_sha256':manifest['forecast.json'],
      'trace':[
       {'step':1,'object':'frozen source/features','feature_sha256':digest(features)},
       {'step':2,'object':'exact fitted coefficient artifact','model_sha256':digest(model)},
       {'step':3,'object':'separate logistic and Ridge heads','predictions':p},
       {'step':4,'object':'out-of-fold paired final-score residuals','count':len(model['final_score_residuals']),'sha256':digest(model['final_score_residuals'])},
       {'step':5,'object':'recenter residuals, add Ridge centers, clip nonnegative, round integer','support_sha256':digest(support.tolist())},
       {'step':6,'object':'stratify home/away/tie, assign fitted logistic and tie masses','tie_rate':args[-1]},
       {'step':7,'object':'exact weighted joint measure','summary':exact,'home_by_at_least_21':float(weights[margin>=21].sum()),'away_at_most_10':float(weights[support[:,1]<=10].sum()),'home_minus_2_5':contract(support,weights,'SPREAD','HOME',-2.5)},
       {'step':8,'object':'seeded sampler and draw hash','seed':mc['seed'],'sha256':mc['sha256'],'draws_identical':True,'draw_count':len(scores)}],
      'normal_sigma_parameter':None,'normal_backsolves_are_not_distribution_validation':True,
      'independent_calibration_validation':False,'old_forecast_modified':False,'action_authority':False}

def main():
    p=argparse.ArgumentParser();p.add_argument('--forecast',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=audit(a.forecast);a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as f:json.dump(result,f,indent=2,allow_nan=False)
    print(result['status'])
if __name__=='__main__':main()
