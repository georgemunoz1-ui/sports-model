#!/usr/bin/env python3
"""Additional descriptive intervals from frozen OOF predictions; no fitting."""
import argparse,datetime as dt,hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd

def main():
    p=argparse.ArgumentParser();p.add_argument('--oof',type=Path,required=True);p.add_argument('--design',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    frame=pd.read_csv(a.oof);design=json.loads(a.design.read_text());ref=frame[frame.arm=='base'].set_index('game_id');mask=ref.home_win.notna();seasons=ref.loc[mask,'season'];unique=sorted(map(int,seasons.unique()))
    seed=design['screen']['bootstrap_seed'];idx=np.random.default_rng(seed).integers(len(unique),size=(10000,len(unique)));counts=np.array([(seasons==s).sum() for s in unique]);out={}
    for arm in ['qb','availability','travel','combined']:
        row=frame[frame.arm==arm].set_index('game_id')
        if not ref.index.equals(row.index) or not row.home_win.equals(ref.home_win):raise ValueError('MATCHED_OUTCOMES_REQUIRED')
        delta=((row.p_home-ref.home_win)**2-(ref.p_home-ref.home_win)**2)[mask]
        sums=np.array([delta[seasons==s].sum() for s in unique]);boots=sums[idx].sum(axis=1)/counts[idx].sum(axis=1)
        out[arm]={'brier_delta_vs_base':float(delta.mean()),'season_block_bootstrap_95_ci':np.quantile(boots,[.025,.975]).tolist(),'per_season_delta':{str(s):float(delta[seasons==s].mean()) for s in unique}}
    result={'created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'evidence':'POST_HOC_DESCRIPTIVE_INTERVALS_ON_REUSED_HISTORY; NO_NEW_PROMOTION_DECISION','oof_sha256':hashlib.sha256(a.oof.read_bytes()).hexdigest(),'design_sha256':hashlib.sha256(a.design.read_bytes()).hexdigest(),'non_tie_games':int(mask.sum()),'seasons':unique,'bootstrap_seed':seed,'bootstrap_replicates':10000,'bootstrap_unit':'SEASON; GAME_WEIGHTED_PAIRED_DELTA','multiple_comparison_adjustment':False,'arms':out}
    serialized=json.dumps(result,indent=2,allow_nan=False)
    with a.output.open('x') as f:f.write(serialized)
    print(json.dumps(out,indent=2))
if __name__=='__main__':main()
