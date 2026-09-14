#!/usr/bin/env python3
"""Later-year interval checks using only residuals from earlier OOF years."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np,pandas as pd

def main():
    p=argparse.ArgumentParser();p.add_argument('--fit',type=Path,required=True);a=p.parse_args();allpred=pd.read_csv(a.fit/'oof_predictions.csv');history=pd.read_csv(a.fit/'features.csv');full=allpred[allpred.arm=='combined'];rows=[];unsupported=[]
    for year in range(2020,2026):
        prior=full[full.season<year];train=history[(history.season<year)&history.home_margin.notna()];tie=((train.home_margin==0).sum()+.5)/(len(train)+1)
        pool=np.column_stack([(prior.home_margin+prior.total_points-prior.pred_margin-prior.pred_total)/2,(prior.total_points-prior.home_margin-prior.pred_total+prior.pred_margin)/2]);pool-=pool.mean(axis=0)
        for r in full[full.season==year].itertuples():
            centers=np.array([(r.pred_total+r.pred_margin)/2,(r.pred_total-r.pred_margin)/2]);s=np.rint(np.maximum(0,centers+pool));m=s[:,0]-s[:,1];t=s.sum(axis=1);sign=np.sign(m);prob=np.array([(1-tie)*r.p_home,(1-tie)*(1-r.p_home),tie]);weights=np.zeros(len(s));bad=False
            for tag,w in zip([1,-1,0],prob):
                mask=sign==tag
                if not mask.any():bad=True;break
                weights[mask]=w/mask.sum()
            if bad:unsupported.append({'game_id':r.game_id,'reason':'CONDITIONAL_SCORE_SUPPORT_MISSING'});continue
            row={'game_id':r.game_id,'season':year,'residual_max_season':int(prior.season.max()),'three_way_brier':float(np.sum((prob-np.array([r.home_margin>0,r.home_margin<0,r.home_margin==0]))**2))}
            for kind,values,actual in [('margin',m,r.home_margin),('total',t,r.total_points)]:
                order=np.argsort(values);v=values[order];cdf=np.cumsum(weights[order]);lo=v[min(np.searchsorted(cdf,.1),len(v)-1)];hi=v[min(np.searchsorted(cdf,.9),len(v)-1)]
                row[kind+'_80_cover']=bool(lo<=actual<=hi);row[kind+'_80_width']=float(hi-lo)
            rows.append(row)
    d=pd.DataFrame(rows);d.to_csv(a.fit/'score_kernel_chronological_checks.csv',index=False)
    result={'population':'2020_TO_2025; each residual pool strictly earlier than evaluated season','games_supported':len(d),'unsupported':unsupported,'three_way_brier':float(d.three_way_brier.mean()),'margin_80_coverage':float(d.margin_80_cover.mean()),'margin_80_width':float(d.margin_80_width.mean()),'total_80_coverage':float(d.total_80_cover.mean()),'total_80_width':float(d.total_80_width.mean()),'status':'SECONDARY_RETROSPECTIVE_DIAGNOSTIC_NOT_CALIBRATION_CERTIFICATION'}
    (a.fit/'score_kernel_evaluation.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='unsupported'},indent=2));print('unsupported',len(unsupported))
if __name__=='__main__':main()
