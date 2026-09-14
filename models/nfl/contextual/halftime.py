"""Dedicated pregame half/remaining-score research model; no market predictors.

Four targets share a same-game OOF residual row. Remaining scores include OT.
Integer rounding is NOT a fitted NFL key-number or scoring-event model.
"""
import hashlib
import json
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

TARGETS = ['h1_home', 'h1_away', 'remaining_home', 'remaining_away']
MODEL_ID = 'nfl.halftime_joint_ridge.v1.research'

def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, allow_nan=False).encode()).hexdigest()

def fit(frame, names, alpha=50.0, scaled=False):
    y = frame[TARGETS].to_numpy(float)
    if scaled:
        # Full-game Ridge predictions split equally: deliberately simple comparator.
        y = np.column_stack([y[:, 0]+y[:, 2], y[:, 1]+y[:, 3]])
    pipe = make_pipeline(SimpleImputer(strategy='median', keep_empty_features=True),
                         StandardScaler(), Ridge(alpha=alpha))
    pipe.fit(frame[names], y)
    imp, scale, model = [v for _, v in pipe.steps]
    return {'model_id': MODEL_ID if not scaled else 'nfl.halftime_scaled_baseline.v1',
            'feature_names': names, 'impute': imp.statistics_.tolist(),
            'center': scale.mean_.tolist(), 'scale': scale.scale_.tolist(),
            'coefficient': model.coef_.tolist(), 'intercept': model.intercept_.tolist(),
            'scaled': scaled, 'alpha': alpha, 'training_games': len(frame),
            'training_seasons': sorted(map(int, frame.season.unique()))}

def predict(params, frame):
    x = frame[params['feature_names']].to_numpy(float)
    if np.isinf(x).any():
        raise ValueError('INFINITE_FEATURE')
    x = (np.where(np.isnan(x), params['impute'], x)-params['center'])/params['scale']
    y = x @ np.asarray(params['coefficient']).T + params['intercept']
    if params['scaled']:
        y = np.column_stack([y/2, y/2])
    return np.maximum(0, y)

def support(means, residuals):
    means, r = np.asarray(means, float), np.asarray(residuals, float)
    if means.shape != (4,) or r.ndim != 2 or r.shape[1] != 4 or len(r)<100:
        raise ValueError('JOINT_SHAPE_OR_SAMPLE_SIZE')
    if not np.isfinite(means).all() or not np.isfinite(r).all() or (means<0).any():
        raise ValueError('INVALID_JOINT_INPUT')
    # Shared row retains empirical covariance across teams and halves.
    return np.rint(np.maximum(0, means+r-r.mean(axis=0))).astype('<i2')

def sample(means, residuals, identity, n=100000):
    if n < 100000:
        raise ValueError('MINIMUM_100000_DRAWS')
    s = support(means, residuals)
    seed = int(digest({'identity': identity, 'n': n, 'model_id': MODEL_ID})[:16],16)
    result = s[np.random.default_rng(seed).integers(len(s),size=n)]
    return result, {'seed': seed, 'n': n, 'columns': TARGETS,
                    'sha256': hashlib.sha256(result.tobytes()).hexdigest()}

def quantities(scores):
    s = np.asarray(scores)
    if s.ndim!=2 or s.shape[1]!=4 or not np.isfinite(s).all() or (s<0).any() or (s!=np.rint(s)).any():
        raise ValueError('INTEGER_NONNEGATIVE_PERIOD_SCORES_REQUIRED')
    h, a, rh, ra = s.astype(np.int64).T
    return {'h1_home_margin': h-a, 'h1_total': h+a,
            'fg_home_margin': h+rh-a-ra, 'fg_total': h+a+rh+ra}

def probabilities(scores):
    q = quantities(scores); m=q['h1_home_margin']; f=q['fg_home_margin']; t=q['h1_total']
    a=(m<1.5); b=(f<2.5)
    return {'h1_away_win': float(np.mean(m<0)), 'h1_home_win': float(np.mean(m>0)),
            'h1_tie': float(np.mean(m==0)), 'h1_away_plus_1_5': float(a.mean()),
            'h1_home_minus_1_5': float(np.mean(m>1.5)),
            'h1_under_20_5': float(np.mean(t<20.5)), 'h1_over_20_5': float(np.mean(t>20.5)),
            'fg_away_plus_2_5': float(b.mean()), 'combo_away_plus_2_5_and_h1_plus_1_5': float(np.mean(a&b)),
            'h1_cover_given_fg_cover': float(np.mean(a[b])) if b.any() else None,
            'fg_away_win': float(np.mean(f<0)), 'fg_home_win': float(np.mean(f>0)), 'fg_tie': float(np.mean(f==0))}

def crps(samples, actual):
    x=np.sort(np.asarray(samples,float)); n=len(x)
    return float(np.mean(abs(x-actual))-np.dot(2*np.arange(1,n+1)-n-1,x)/(n*n))

def metrics(scores, actual):
    q=quantities(scores); h,a,rh,ra=actual
    margin=h-a; total=h+a
    p=np.array([np.mean(q['h1_home_margin']<0), np.mean(q['h1_home_margin']==0), np.mean(q['h1_home_margin']>0)])
    y=np.array([margin<0,margin==0,margin>0],float)
    # Jeffreys smoothing only for log-score stability; recorded explicitly.
    plog=(p*len(scores)+0.5)/(len(scores)+1.5)
    probe=probabilities(scores)
    result={'h1_margin_crps':crps(q['h1_home_margin'],margin),'h1_total_crps':crps(q['h1_total'],total),
            'h1_winner_brier_3way':float(np.sum((p-y)**2)), 'h1_winner_log_loss':float(-np.log(plog[y.astype(bool)][0])),
            'h1_margin_mae':float(abs(np.mean(q['h1_home_margin'])-margin)),
            'h1_total_mae':float(abs(np.mean(q['h1_total'])-total)),
            'h1_tie_pred':float(p[1]),'h1_tie_actual':float(margin==0)}
    for key,target in [('h1_under_20_5',total<20.5), ('h1_away_plus_1_5',margin<1.5),
                       ('combo_away_plus_2_5_and_h1_plus_1_5',(margin<1.5) and (h+rh-a-ra<2.5))]:
        result[key+'_p']=probe[key];result[key+'_y']=float(target);result[key+'_brier']=(probe[key]-float(target))**2
    return result

def run_artifact(artifact_path, football, output, n=100000):
    """Explicit canonical-runner extension; never replaces the football output."""
    import datetime as dt
    from pathlib import Path
    import pandas as pd
    path=Path(artifact_path); artifact=json.loads(path.read_text())
    if artifact['model']['model_id']!=MODEL_ID:
        raise ValueError('EXACT_HALFTIME_MODEL_ID_REQUIRED')
    if football['model_id']!='nfl.integrated_context.combined.v1.research' or football.get('market_input'):
        raise ValueError('FOOTBALL_ONLY_COMBINED_FEATURE_SOURCE_REQUIRED')
    now=dt.datetime.now(dt.timezone.utc)
    kickoff=dt.datetime.fromisoformat(football['event']['start_time_utc'].replace('Z','+00:00'))
    if now>=kickoff:raise ValueError('HALFTIME_PREGAME_ONLY')
    if dt.datetime.fromisoformat(artifact['fit_completed_at_utc'].replace('Z','+00:00'))>now:
        raise ValueError('FUTURE_ARTIFACT')
    if max(artifact['model']['training_seasons'])>=int(football['event']['event_id'].split('_')[0]):
        raise ValueError('TRAINING_SEASON_NOT_PRIOR')
    names=artifact['model']['feature_names']
    if set(names)!=set(football['features']):raise ValueError('FEATURE_SCHEMA_MISMATCH')
    mean=predict(artifact['model'],pd.DataFrame([football['features']]))[0]
    identity={'event':football['event'],'football_identity':football['identity'],
              'artifact_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
              'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    scores,sim=sample(mean,artifact['residuals'],identity,n)
    replay,_=sample(mean,artifact['residuals'],identity,n)
    if not np.array_equal(scores,replay):raise ValueError('HALFTIME_REPLAY_FAILED')
    result={'model_id':MODEL_ID,'event':football['event'],'created_at_utc':now.isoformat(),
            'input_information_cutoff_utc':football['cutoff_utc'],'identity':identity,'simulation':sim,
            'simulation_probabilities':probabilities(scores),
            'exact_empirical_kernel_probabilities':probabilities(support(mean,artifact['residuals'])),
            'period_centers':dict(zip(TARGETS,map(float,mean))),
            'source_audit':football['audit'],'feature_count':len(names),'replay_verified':True,
            'research_only':True,'action_authority':False,
            'warnings':['NEW_JOINT_ARM_WITH_DISTINCT_FULL_GAME_MARGINAL','NOT_MARKET_CALIBRATED',
                        'HALFTIME_TIE_MASS_UNDERESTIMATED_IN_EVALUATION','FINAL_TIE_OT_UNVALIDATED',
                        'DEDICATED_MODEL_DID_NOT_BEAT_SCALED_BENCHMARK']}
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    np.save(out/'period_score_draws.npy',scores,allow_pickle=False)
    (out/'forecast.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    (out/'manifest.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()},indent=2))
    return result
