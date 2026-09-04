#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, subprocess
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

ALIASES={
 'target':['home_margin_final','margin','home_margin','score_margin','margin_home'],
 'home_score':['home_score','home_points','home_score_final'], 'away_score':['away_score','away_points','away_score_final'],
 'home_elo':['home_elo_pre','elo_home','home_elo','home_pregame_elo'], 'away_elo':['away_elo_pre','elo_away','away_elo','away_pregame_elo'],
 'neutral':['neutral_site','neutral','neutral_site_indicator'], 'week':['week','season_week'],
 'home_field':['home_field_indicator','home_field','is_home']}
def pick(cols,key,required=False):
    for x in ALIASES[key]:
        if x in cols:return x
    if required: raise SystemExit(f'MISSING_COLUMN:{key}; available={sorted(cols)}')
    return None
def sha256(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return 'sha256:'+h.hexdigest()
def git_commit():
    try:return subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    except Exception:return 'UNKNOWN'

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--train-data',required=True); ap.add_argument('--output',required=True); ap.add_argument('--validation-output',required=True); ap.add_argument('--as-of',required=True)
    a=ap.parse_args(); p=Path(a.train_data); df=pd.read_parquet(p); cols=set(df.columns)
    he,ae=pick(cols,'home_elo',True),pick(cols,'away_elo',True); target=pick(cols,'target')
    if not target:
        hs,aws=pick(cols,'home_score'),pick(cols,'away_score')
        if not hs or not aws: raise SystemExit(f'MISSING_MARGIN_TARGET; available={sorted(cols)}')
        df['_target']=pd.to_numeric(df[hs],errors='coerce')-pd.to_numeric(df[aws],errors='coerce'); target='_target'
    neutral=pick(cols,'neutral'); week=pick(cols,'week'); hf=pick(cols,'home_field')
    work=pd.DataFrame({'y':pd.to_numeric(df[target],errors='coerce'),'elo_diff':pd.to_numeric(df[he],errors='coerce')-pd.to_numeric(df[ae],errors='coerce')})
    work['home_field']=pd.to_numeric(df[hf],errors='coerce').fillna(1.0) if hf else 1.0
    work['neutral']=pd.to_numeric(df[neutral],errors='coerce').fillna(0.0) if neutral else 0.0
    work['week']=pd.to_numeric(df[week],errors='coerce') if week else np.nan; work=work.dropna(subset=['y','elo_diff'])
    if len(work)<1000: raise SystemExit(f'INSUFFICIENT_TRAINING_ROWS:{len(work)}')
    # Chronological proxy: preserve source row order; last 20% untouched validation. Dataset lineage must itself be PIT/chronological.
    cut=int(len(work)*.8); tr,va=work.iloc[:cut],work.iloc[cut:]
    X=np.column_stack([np.ones(len(tr)),tr.elo_diff,tr.home_field,tr.neutral]); beta,*_=np.linalg.lstsq(X,tr.y.to_numpy(),rcond=None)
    def pred(z):return np.column_stack([np.ones(len(z)),z.elo_diff,z.home_field,z.neutral])@beta
    pv=pred(va); resid=va.y.to_numpy()-pv; sigma=float(np.sqrt(np.mean(resid**2))); mae=float(np.mean(np.abs(resid))); rmse=sigma
    if sigma<=0 or not np.isfinite(sigma):raise SystemExit('INVALID_RESIDUAL_SCALE')
    weekly={}
    if va.week.notna().any():
        for w,g in va.assign(resid=resid).dropna(subset=['week']).groupby('week'):
            if len(g)>=200: weekly[str(int(w))]=float(np.sqrt(np.mean(g.resid.to_numpy()**2)))
    sim_win=0.5*(1+np.vectorize(__import__('math').erf)(pv/(sigma*np.sqrt(2))))
    ywin=(va.y.to_numpy()>0).astype(float); brier=float(np.mean((sim_win-ywin)**2))
    now=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    state={'artifact_type':'cfb_margin_model_state_v1','model_id':'cfb.margin_distribution.v1','version':'1.0.0','trained_at_utc':now,'as_of_utc':a.as_of,'code_commit':git_commit(),'training_data':{'dataset_id':p.name,'dataset_hash':sha256(p),'n_games':int(len(work)),'n_train':int(len(tr)),'n_validation':int(len(va)),'population':'FBS_vs_FBS_only','target':'home_final_margin'},'feature_schema':{'version':'cfb_margin_features_v1','features':['elo_diff_pre','home_field_indicator','neutral_site_indicator']},'parameters':{'intercept':float(beta[0]),'elo_diff_coefficient':float(beta[1]),'home_field_coefficient':float(beta[2]),'neutral_site_coefficient':float(beta[3])},'residual_model':{'distribution':'normal_margin_v1','global_sigma':sigma,'segment_sigma_by_week':weekly},'validation':{'method':'chronological_holdout_last_20pct','n_games':int(len(va)),'margin_mae':mae,'margin_rmse':rmse,'ml_brier_induced_by_margin_sim':brier},'status':'SHADOW_CANDIDATE'}
    if abs(state['parameters']['elo_diff_coefficient'])<1e-9:raise SystemExit('PLACEHOLDER_OR_ZERO_ELO_COEFFICIENT')
    Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps(state,indent=2)+'\n')
    Path(a.validation_output).parent.mkdir(parents=True,exist_ok=True); Path(a.validation_output).write_text(json.dumps(state['validation'],indent=2)+'\n')
    print(json.dumps({'status':'PASS','output':a.output,'n_games':len(work),'mae':mae,'rmse':rmse,'ml_brier':brier,'sigma':sigma}))
if __name__=='__main__':main()
