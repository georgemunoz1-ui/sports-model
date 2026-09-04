#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, subprocess
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

ALIASES={'target':['home_margin_final','home_margin','margin','score_margin','margin_home'],'elo_diff':['elo_diff_with_home_advantage','elo_diff_pre','elo_diff'],'neutral':['neutral_site','neutral','neutral_site_indicator'],'conference':['conference_game','is_conference_game'],'week':['week','season_week']}
def pick(cols,key,required=False):
 for x in ALIASES[key]:
  if x in cols:return x
 if required:raise SystemExit(f'MISSING_COLUMN:{key}; available={sorted(cols)}')
 return None
def sha256(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return 'sha256:'+h.hexdigest()
def git_commit():return subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--train-data',required=True);ap.add_argument('--output',required=True);ap.add_argument('--validation-output',required=True);ap.add_argument('--as-of',required=True);a=ap.parse_args()
 p=Path(a.train_data);df=pd.read_parquet(p);cols=set(df.columns);target=pick(cols,'target',True);ed=pick(cols,'elo_diff',True);neutral=pick(cols,'neutral');conf=pick(cols,'conference');week=pick(cols,'week')
 w=pd.DataFrame({'y':pd.to_numeric(df[target],errors='coerce'),'elo_diff':pd.to_numeric(df[ed],errors='coerce')})
 w['neutral']=pd.to_numeric(df[neutral],errors='coerce').fillna(0) if neutral else 0.;w['conference']=pd.to_numeric(df[conf],errors='coerce').fillna(0) if conf else 0.;w['week']=pd.to_numeric(df[week],errors='coerce') if week else np.nan;w=w.dropna(subset=['y','elo_diff'])
 if len(w)<1000:raise SystemExit(f'INSUFFICIENT_TRAINING_ROWS:{len(w)}')
 # Existing artifact is already a causal PIT feature table. Preserve its chronological order and hold out final 20%.
 cut=int(len(w)*.8);tr,va=w.iloc[:cut],w.iloc[cut:]
 X=np.column_stack([np.ones(len(tr)),tr.elo_diff,tr.neutral,tr.conference]);beta,*_=np.linalg.lstsq(X,tr.y.to_numpy(),rcond=None)
 pv=np.column_stack([np.ones(len(va)),va.elo_diff,va.neutral,va.conference])@beta;resid=va.y.to_numpy()-pv
 sigma=float(np.sqrt(np.mean(resid**2)));mae=float(np.mean(np.abs(resid)));rmse=sigma
 if sigma<=0 or not np.isfinite(sigma):raise SystemExit('INVALID_RESIDUAL_SCALE')
 weekly={}
 for wk,g in va.assign(resid=resid).dropna(subset=['week']).groupby('week'):
  if len(g)>=200:weekly[str(int(wk))]=float(np.sqrt(np.mean(g.resid.to_numpy()**2)))
 erf=np.vectorize(__import__('math').erf);simwin=.5*(1+erf(pv/(sigma*np.sqrt(2))));ywin=(va.y.to_numpy()>0).astype(float);brier=float(np.mean((simwin-ywin)**2))
 now=datetime.now(timezone.utc).isoformat().replace('+00:00','Z');commit=git_commit()
 state={'artifact_type':'cfb_margin_model_state_v1','model_id':'cfb.margin_distribution.v1','version':'1.0.0','trained_at_utc':now,'as_of_utc':a.as_of,'code_commit':commit,'training_data':{'dataset_id':p.name,'dataset_hash':sha256(p),'n_games':int(len(w)),'n_train':int(len(tr)),'n_validation':int(len(va)),'population':'FBS_vs_FBS_only','target':'home_final_margin','point_in_time_semantics':'source cfb_v1_features causal pregame rows'},'feature_schema':{'version':'cfb_margin_features_v1','features':['elo_diff_with_home_advantage','neutral_site','conference_game']},'parameters':{'intercept':float(beta[0]),'elo_diff_coefficient':float(beta[1]),'neutral_site_coefficient':float(beta[2]),'conference_game_coefficient':float(beta[3]),'home_advantage_embedded_in_elo_diff':True},'residual_model':{'distribution':'normal_margin_v1','global_sigma':sigma,'segment_sigma_by_week':weekly},'validation':{'method':'chronological_holdout_last_20pct','n_games':int(len(va)),'margin_mae':mae,'margin_rmse':rmse,'ml_brier_induced_by_margin_sim':brier},'status':'SHADOW_CANDIDATE'}
 if abs(float(beta[1]))<1e-9:raise SystemExit('PLACEHOLDER_OR_ZERO_ELO_COEFFICIENT')
 Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(state,indent=2)+'\n');Path(a.validation_output).parent.mkdir(parents=True,exist_ok=True);Path(a.validation_output).write_text(json.dumps(state['validation'],indent=2)+'\n')
 print(json.dumps({'status':'PASS','n_games':len(w),'mae':mae,'rmse':rmse,'ml_brier':brier,'sigma':sigma,'parameters':state['parameters']}))
if __name__=='__main__':main()
