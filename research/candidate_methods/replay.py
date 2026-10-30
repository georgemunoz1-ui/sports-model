"""Verify retained artifact hashes and replay fitted predictions without retraining."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.special import expit, ndtr
from .methods import verify_source
from research.replay_controls import equivalent


def replay(directory):
    directory=Path(directory)
    manifest=json.loads((directory/'manifest.json').read_text())
    for name,sha in manifest['artifacts'].items(): verify_source(directory/name,sha)
    history=pd.read_csv(directory/'nfl_historical_features.csv').set_index('game_id')
    recorded=pd.read_csv(directory/'predictions.csv')
    max_error=0.;checked=0
    for fold in json.loads((directory/'folds.json').read_text()):
        for arm,spec in fold['arms'].items():
            expected=recorded[(recorded.season==fold['test_season'])&(recorded.arm==arm)]
            x=history.loc[expected.game_id,spec['features']]
            path=directory/spec['model_path']
            if arm.startswith('xgb'):
                from xgboost import XGBRegressor
                model=XGBRegressor();model.load_model(path);mu=model.predict(x)
            else:
                model=json.loads(path.read_text());a=x.to_numpy(dtype=float);missing=np.isnan(a)
                a=np.where(missing,np.array(model['imputation_statistics']),a)
                a=np.column_stack([a,missing[:,model['missing_indicator_columns']]])
                a=(a-model['scale_mean'])/model['scale_scale']
                mu=a@model['coef']+model['intercept']
            raw=ndtr(mu/spec['train_residual_sigma'])
            calibrated=expit(mu.astype(float)*spec['calibration_coefficient']+spec['calibration_intercept'])
            for actual, column in [(mu,'predicted_margin'),(raw,'p_home_raw'),(calibrated,'p_home_calibrated')]:
                equivalent(actual.tolist(), expected[column].to_numpy().tolist(), abs_tol=1e-10)
                delta=float(np.max(np.abs(actual-expected[column].to_numpy())))
                if delta>1e-10:raise ValueError(f'prediction replay mismatch: {arm} {column} {delta}')
                max_error=max(max_error,delta)
            checked+=len(expected)
    return {'status':'PASS','artifact_hashes_verified':len(manifest['artifacts']),
            'model_event_predictions':checked,'max_absolute_prediction_error':max_error,
            'tolerance':1e-10,'retrained':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);args=p.parse_args()
    print(json.dumps(replay(args.directory),indent=2))
