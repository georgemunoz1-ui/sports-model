"""Reproducible isolated candidate experiment; explicit input files, no downloads."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import numpy as np
import pandas as pd
import scipy
from scipy.special import ndtr
import sklearn
import xgboost
from research.offline_benchmark import paired_day_bootstrap
from .features import nfl_history, pbp_features
from .methods import (check_partitions, choose_model, fit_sigmoid, probability_metrics,
                      export_model, lineup_quality, verify_source)


def write(path, value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def evaluate(rows, protocol, out):
    spec=protocol['nfl']; predictions=[];folds=[]
    arms={'ridge_base':('ridge',spec['baseline_features']),
          'ridge_coaching':('ridge',spec['baseline_features']+spec['coaching_features']),
          'xgb_base':('xgb',spec['baseline_features'])}
    for year in spec['development_test_seasons']:
        train=rows[rows.season<=year-3]
        tune=rows[rows.season==year-2]
        cal=rows[rows.season==year-1]
        test=rows[rows.season==year]
        check_partitions(train,tune,cal,test)
        f={'test_season':year,'train_n':len(train),'tune_n':len(tune),'calibration_n':len(cal),
           'test_n':len(test),'partitions':{name:d.game_id.tolist() for name,d in [('train',train),('tune',tune),('calibration',cal),('test',test)]},'arms':{}}
        for name,(kind,features) in arms.items():
            grid=[{'alpha':a} for a in spec['ridge_alpha_grid']] if kind=='ridge' else [dict(spec['xgb_fixed'],**g) for g in spec['xgb_grid']]
            model,config,tuning=choose_model(kind,grid,protocol['seed'],train[features],train.target_margin,
                                             tune[features],tune.target_margin)
            sigma=float(np.sqrt(np.mean((train.target_margin-model.predict(train[features]))**2)))
            if sigma<=0: raise ValueError('nonpositive residual scale')
            calibrator=fit_sigmoid(model.predict(cal[features]),cal.target_margin)
            margin=model.predict(test[features])
            raw=ndtr(margin/sigma)
            calibrated=calibrator.predict_proba(margin[:,None])[:,1]
            f['arms'][name]={'features':features,'chosen':config,'tune_grid_mae':tuning,
                'train_residual_sigma':sigma,'calibration_coefficient':float(calibrator.coef_[0,0]),
                'calibration_intercept':float(calibrator.intercept_[0]),
                'model_path':f'models/{year}_{name}.json'}
            export_model(model,features,out/'models'/f'{year}_{name}.json')
            for j,r in enumerate(test.itertuples()):
                predictions.append({'game_id':r.game_id,'date':r.date,'season':year,'arm':name,
                    'target_margin':r.target_margin,'predicted_margin':float(margin[j]),
                    'p_home_raw':float(raw[j]),'p_home_calibrated':float(calibrated[j])})
        folds.append(f)
    pred=pd.DataFrame(predictions);pred.to_csv(out/'predictions.csv',index=False)
    results={}
    for name,d in pred.groupby('arm'):
        e=d.predicted_margin-d.target_margin
        results[name]={'n':len(d),'mae':float(abs(e).mean()),'rmse':float(np.sqrt((e*e).mean())),
            'raw_probability':probability_metrics(d.target_margin,d.p_home_raw),
            'sigmoid_probability':probability_metrics(d.target_margin,d.p_home_calibrated),
            'season_mae':{str(y):float(abs(g.predicted_margin-g.target_margin).mean()) for y,g in d.groupby('season')}}
    base=pred[pred.arm=='ridge_base'].set_index('game_id')
    contrasts={}
    for name in ['ridge_coaching','xgb_base']:
        other=pred[pred.arm==name].set_index('game_id')
        contrasts[name+'_minus_ridge_base']=paired_day_bootstrap(base.index.tolist(),base.date.to_dict(),
            abs(base.predicted_margin-base.target_margin).to_dict(),
            abs(other.predicted_margin-other.target_margin).to_dict(),protocol['seed'],draws=2000)
    write(out/'folds.json',folds)
    return {'status':'FITTED_RESEARCH_ONLY','pit_status':spec['pit_status'],
        'promotion':False,'sealed_seasons':spec['sealed_seasons'],
        'scores':results,'mae_contrasts':contrasts,
        'interpretation':'Development diagnostics against a simple lagged scoring baseline, not the current integrated model. Same-year prior completed games update features; fitted models remain frozen. No market-performance claim.'}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--sources',type=Path,required=True)
    ap.add_argument('--nfl-sources',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();out=args.output
    if out.exists():raise ValueError('output must be new; preserved results are immutable')
    out.mkdir(parents=True);(out/'models').mkdir()
    protocol_path=Path(__file__).with_name('protocol.json')
    protocol=json.loads(protocol_path.read_text())
    manifest=json.loads((Path(__file__).parent/'source_manifest.json').read_text())
    resolved={}
    for r in manifest:
        root=args.nfl_sources if r['filename'] in ('games.csv','play_by_play_2026.csv') else args.sources
        path=root/r['filename'];verify_source(path,r['sha256']);resolved[r['filename']]=path
    callers=pd.read_csv(resolved['playcallers.csv']); games=pd.read_csv(resolved['games.csv'])
    rows=nfl_history(games,callers);rows.to_csv(out/'nfl_historical_features.csv',index=False)
    observed,players=pbp_features(pd.read_csv(resolved['play_by_play_2026.csv'],low_memory=False))
    observed.to_csv(out/'nfl_week1_team_observations.csv',index=False)
    players.to_csv(out/'nfl_week1_player_hvt.csv',index=False)
    wnba=pd.read_csv(resolved['wnba_stints_2026.csv'])
    quality=lineup_quality(wnba)
    if quality['status']=='PASS':
        raise ValueError('WNBA gate unexpectedly passed: register separate historical evaluation before fitting')
    write(out/'wnba_quality.json',quality)
    result=evaluate(rows,protocol,out)
    result['week1']={'games':int(observed.game_id.nunique()),'team_rows':len(observed),'player_hvt_rows':len(players),
        'status':'OBSERVED_ONLY_NOT_FITTED_OR_USED','earliest_evidence_at':'2026-09-15T22:19:57.664095+00:00'}
    result['wnba']={'status':'FIT_BLOCKED_SOURCE_QUALITY','quality':quality,'production_used':False}
    result['protocol_sha256']=hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    result['versions']={'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,
        'scipy':scipy.__version__,'sklearn':sklearn.__version__,'xgboost':xgboost.__version__}
    result['source_manifest']=manifest
    write(out/'results.json',result)
    artifacts={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file()}
    code={str(p.relative_to(Path(__file__).parents[2])):hashlib.sha256(p.read_bytes()).hexdigest()
          for p in sorted(Path(__file__).parent.glob('*.py'))}
    code['research/offline_benchmark.py']=hashlib.sha256((Path(__file__).parents[1]/'offline_benchmark.py').read_bytes()).hexdigest()
    write(out/'manifest.json',{'artifacts':artifacts,'code':code,'action_authority':'OFF'})
    print(json.dumps({'nfl':{k:{m:v[m] for m in ['n','mae','rmse']} for k,v in result['scores'].items()},
         'wnba':quality,'week1':result['week1'],'mae_contrasts':result['mae_contrasts']},indent=2))


if __name__=='__main__':main()
