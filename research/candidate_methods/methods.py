"""Train-only preprocessing, ordered evaluation and strict source/lineup contracts."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.linear_model import Ridge, LogisticRegression
from research.offline_benchmark import validate_rows


def verify_source(path, expected_sha256):
    got = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if got != expected_sha256:
        raise ValueError(f'source hash mismatch: {path}')
    return got


def verified_pit_rows(rows, feature_names):
    """Use existing strict per-feature timestamp/market firewall; no timestamp invention."""
    return validate_rows(rows, feature_names)


def check_partitions(train, tune, calibration, test):
    """Whole-event chronological partitions, including multiple rows per event."""
    parts = [train, tune, calibration, test]
    for part in parts:
        if len(part) == 0 or part[['game_id', 'date']].isna().any().any():
            raise ValueError('empty or unidentified partition')
        if part.groupby('game_id').date.nunique().max() != 1:
            raise ValueError('event has inconsistent dates')
    for i, a in enumerate(parts):
        for b in parts[i+1:]:
            if set(a.game_id) & set(b.game_id):
                raise ValueError('event split between partitions')
            if pd.to_datetime(a.date).max() >= pd.to_datetime(b.date).min():
                raise ValueError('nonchronological partitions')


def estimator(kind, config, seed):
    if kind == 'ridge':
        model = Ridge(alpha=config['alpha'])
        # Both imputation statistics and scaling are fitted only inside the training call.
        return Pipeline([('missing', SimpleImputer(strategy='median', add_indicator=True,
                                                   keep_empty_features=True)),
                         ('scale', StandardScaler()), ('model', model)])
    if kind == 'xgb':
        from xgboost import XGBRegressor
        return Pipeline([('model', XGBRegressor(objective='reg:squarederror',
                              random_state=seed, tree_method='hist', **config))])
    raise ValueError('unknown model')


def choose_model(kind, grid, seed, train_x, train_y, tune_x, tune_y):
    candidates = []
    for config in grid:
        model = estimator(kind, config, seed)
        model.fit(train_x, train_y)
        mae = float(np.mean(np.abs(model.predict(tune_x) - tune_y)))
        candidates.append((mae, config, model))
    index = min(range(len(candidates)), key=lambda i: candidates[i][0])
    return candidates[index][2], candidates[index][1], [x[0] for x in candidates]


def fit_sigmoid(predicted_margins, margins):
    predicted_margins, margins = np.asarray(predicted_margins), np.asarray(margins)
    mask = margins != 0
    y = (margins[mask] > 0).astype(int)
    if len(np.unique(y)) != 2:
        raise ValueError('calibration needs both classes')
    return LogisticRegression(C=1, solver='lbfgs').fit(predicted_margins[mask, None], y)


def probability_metrics(margins, probabilities):
    y = np.asarray(margins)
    p = np.asarray(probabilities)
    if len(y) != len(p) or not np.isfinite(p).all() or ((p <= 0) | (p >= 1)).any():
        raise ValueError('finite open-interval probability for every row required')
    mask = y != 0
    y, p = (y[mask] > 0).astype(int), p[mask]
    if not len(y):
        raise ValueError('no non-tie outcomes')
    bins = []
    for lo in np.arange(0, 1, .1):
        inside = (p >= lo) & (p < lo+.1)
        bins.append({'lower':round(float(lo),1), 'n':int(inside.sum()),
                     'mean_probability':float(p[inside].mean()) if inside.any() else None,
                     'observed_frequency':float(y[inside].mean()) if inside.any() else None})
    return {'n':len(y),'ties_excluded':int((~mask).sum()),
            'brier_home':float(np.mean((p-y)**2)),
            'log_loss':float(-np.mean(y*np.log(p)+(1-y)*np.log1p(-p))),
            'reliability_bins':bins}


def export_model(model, features, output):
    """Portable artifact: JSON only; do not load arbitrary pickle objects."""
    output = Path(output)
    m = model.named_steps['model']
    if hasattr(m, 'get_booster'):
        m.save_model(output)
        return
    imp, scale = model.named_steps['missing'], model.named_steps['scale']
    output.write_text(json.dumps({'features':features,
        'imputation_statistics':imp.statistics_.tolist(),
        'missing_indicator_columns':imp.indicator_.features_.tolist(),
        'scaled_feature_order':imp.get_feature_names_out().tolist(),
        'scale_mean':scale.mean_.tolist(), 'scale_scale':scale.scale_.tolist(),
        'coef':m.coef_.tolist(),'intercept':float(m.intercept_)},indent=2,allow_nan=False)+'\n')


def lineup_quality(rows):
    cols = [f'{side}_p{i}' for side in ('off','def') for i in range(1,6)]
    required = cols + ['game_id','poss_id','points','fgm','fg3m','ftm','game_date']
    if not set(required) <= set(rows):
        return {'status':'BLOCKED','missing_columns':sorted(set(required)-set(rows))}
    points = pd.to_numeric(rows.points, errors='coerce')
    identity = 2*rows.fgm + rows.fg3m + rows.ftm
    problems = {
        'duplicate_game_possession':int(rows.duplicated(['game_id','poss_id']).sum()),
        'missing_player':int(rows[cols].isna().any(axis=1).sum()),
        'nonunique_ten_players':int((rows[cols].nunique(axis=1) != 10).sum()),
        'invalid_points':int((points.isna() | (points<0) | (points>5) | (points%1!=0)).sum()),
        'scoring_identity_mismatch':int((points != identity).sum()),
        'invalid_date':int(pd.to_datetime(rows.game_date,errors='coerce').isna().sum())}
    return {'status':'BLOCKED' if any(problems.values()) else 'PASS',
            'n':len(rows),'games':int(rows.game_id.nunique()),'problems':problems,
            'max_points':float(points.max())}


def lineup_design(rows, players=None):
    quality = lineup_quality(rows)
    if quality['status'] != 'PASS':
        raise ValueError('lineup data gate: '+json.dumps(quality))
    cols = [f'{side}_p{i}' for side in ('off','def') for i in range(1,6)]
    found = set(rows[cols].astype(str).to_numpy().ravel())
    players = sorted(found) if players is None else list(players)
    if len(players)!=len(set(players)) or found-set(players):
        raise ValueError('duplicate vocabulary or unmodeled player; no silent zero effect')
    index = {p:i for i,p in enumerate(players)}
    X = np.zeros((len(rows),2*len(players)))
    for j, values in enumerate(rows[cols].astype(str).to_numpy()):
        for p in values[:5]: X[j,index[p]]=1
        for p in values[5:]: X[j,len(players)+index[p]]=-1
    return X, players


def fit_rapm(rows, alpha=100):
    X, players = lineup_design(rows)
    model = Ridge(alpha=alpha).fit(X, 100*rows.points.to_numpy())
    return model, players


def lineup_effect(coefficients, minute_shares):
    """Shares are minutes/game divided by game minutes, summing to FIVE players."""
    if set(coefficients)!=set(minute_shares) or not np.isclose(sum(minute_shares.values()),5):
        raise ValueError('complete player effects and exposure sum five required')
    if any(not np.isfinite(x) or x<0 or x>1 for x in minute_shares.values()):
        raise ValueError('invalid minute share')
    return float(sum(coefficients[k]*v for k,v in minute_shares.items()))
