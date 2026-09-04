#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
def validate(s):
 v=[]
 if s.get('artifact_type')!='cfb_margin_model_state_v1':v.append('BAD_ARTIFACT_TYPE')
 td=s.get('training_data',{});p=s.get('parameters',{});r=s.get('residual_model',{});q=s.get('validation',{})
 if td.get('n_games',0)<1000:v.append('INSUFFICIENT_SAMPLE')
 if not str(td.get('dataset_hash','')).startswith('sha256:'):v.append('MISSING_DATA_HASH')
 for k in ('intercept','elo_diff_coefficient','neutral_site_coefficient','conference_game_coefficient'):
  if k not in p or not math.isfinite(float(p[k])):v.append('INVALID_PARAMETER_'+k.upper())
 if abs(float(p.get('elo_diff_coefficient',0)))<1e-9:v.append('ZERO_ELO_COEFFICIENT')
 if not math.isfinite(float(r.get('global_sigma',0))) or float(r.get('global_sigma',0))<=0:v.append('INVALID_SIGMA')
 for k in ('margin_mae','margin_rmse','ml_brier_induced_by_margin_sim'):
  if k not in q or not math.isfinite(float(q[k])):v.append('MISSING_VALIDATION_'+k.upper())
 if not s.get('code_commit') or s.get('code_commit')=='UNKNOWN':v.append('MISSING_CODE_COMMIT')
 return v
def main():
 ap=argparse.ArgumentParser();ap.add_argument('path');a=ap.parse_args();s=json.load(open(a.path));v=validate(s)
 if v:raise SystemExit('MODEL_STATE_INVALID:'+','.join(v))
 print('cfb margin model state: PASS')
if __name__=='__main__':main()
