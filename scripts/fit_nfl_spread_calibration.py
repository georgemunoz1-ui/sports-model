#!/usr/bin/env python3
"""Chronological ATS calibration; no retrospective promotion or test tuning."""
import argparse,datetime,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np,pandas as pd
from scipy.optimize import minimize
from models.nfl.contextual.spread_calibration import (MODEL_ID,REFERENCE_ID,CLASSES,
    exact_kernel_margin,cdf_bounds,probabilities_from_bounds)

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(path,obj):
    with Path(path).open('x') as f:json.dump(obj,f,indent=2,allow_nan=False)
def metric_arrays(y,p):
    return ((p-np.eye(3)[y])**2).sum(1),-np.log(np.clip(p[np.arange(len(y)),y],1e-15,1))
def metrics(y,p):
    b,l=metric_arrays(y,p);mask=y!=1;pc=p[mask,0]/(p[mask,0]+p[mask,2]);yy=(y[mask]==0).astype(float)
    return {'games':len(y),'pushes':int((y==1).sum()),'three_way_brier':float(b.mean()),'three_way_log_loss':float(l.mean()),
            'nonpush_games':int(mask.sum()),'conditional_nonpush_brier':float(np.mean((pc-yy)**2)),
            'conditional_nonpush_log_loss':float(np.mean(-yy*np.log(np.clip(pc,1e-15,1))-(1-yy)*np.log(np.clip(1-pc,1e-15,1)))),
            'predicted_push_rate':float(p[:,1].mean()),'observed_push_rate':float((y==1).mean())}
def reliability(y,p):
    rows=[]
    for k,name in enumerate(CLASSES):
        for i in range(10):
            mask=(p[:,k]>=i/10)&((p[:,k]<(i+1)/10) if i<9 else (p[:,k]<=1))
            n=int(mask.sum())
            if not n:continue
            hits=int((y[mask]==k).sum());q=hits/n;z=1.959963984540054;center=(q+z*z/(2*n))/(1+z*z/n);half=z*np.sqrt(q*(1-q)/n+z*z/(4*n*n))/(1+z*z/n)
            rows.append({'class':name,'bin_low':i/10,'bin_high':(i+1)/10,'games':n,'mean_probability':float(p[mask,k].mean()),'observed_rate':q,'wilson_95_interval_descriptive':[float(center-half),float(center+half)]})
    return rows

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--design',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    d=json.loads(a.design.read_text());a.output.mkdir(parents=True,exist_ok=False)
    for path,h in d['input_sha256'].items():
        if digest(ROOT/path)!=h:raise ValueError('INPUT_HASH_CHANGED:'+path)
    allpred=pd.read_csv(ROOT/'data/nfl/contextual_v1/fit_03/oof_predictions.csv');full=allpred[allpred.arm=='combined'].copy()
    hist=pd.read_csv(ROOT/'data/nfl/contextual_v1/fit_03/features.csv');games=pd.read_csv(ROOT/'data/nfl/modes_v1/dataset_02/games.csv')
    assert not full.game_id.duplicated().any() and not games.game_id.duplicated().any()
    lookup=games.set_index('game_id');rows=[];exclusions=[]
    for year in d['calibration_fit_seasons']+d['evaluation_seasons']:
        prior=full[full.season<year];train=hist[(hist.season<year)&hist.home_margin.notna()]
        assert len(prior)>=100 and prior.season.max()<year and train.season.max()<year
        tie=((train.home_margin==0).sum()+.5)/(len(train)+1)
        residuals=np.column_stack([(prior.home_margin+prior.total_points-prior.pred_margin-prior.pred_total)/2,
                                   (prior.total_points-prior.home_margin-prior.pred_total+prior.pred_margin)/2])
        for game in full[full.season==year].itertuples():
            reason=None
            if game.game_id not in lookup.index:reason='MISSING_MARKET_GAME'
            else:
                market=lookup.loc[game.game_id];line=market.spread_line
                if market.game_type!='REG':reason='NOT_REGULAR_SEASON'
                elif not np.isfinite([line,market.home_score,market.away_score]).all():reason='MISSING_LINE_OR_FINAL'
                elif line*2!=round(line*2):reason='INVALID_LINE'
            if reason:exclusions.append({'game_id':game.game_id,'reason':reason});continue
            assert game.home_margin==market.home_score-market.away_score and game.total_points==market.home_score+market.away_score
            try:support,mass=exact_kernel_margin(game.pred_margin,game.pred_total,game.p_home,residuals,tie)
            except ValueError as e:
                if str(e)!='CONDITIONAL_SCORE_SUPPORT_MISSING':raise
                exclusions.append({'game_id':game.game_id,'reason':str(e)});continue
            bounds=cdf_bounds(support,mass,-float(line));v=game.home_margin-line;target=0 if v>0 else 1 if v==0 else 2
            rows.append({'game_id':game.game_id,'season':year,'week':int(game.week),'home_team':market.home_team,'away_team':market.away_team,
                'home_handicap':-float(line),'actual_home_margin':float(game.home_margin),'pred_margin':float(game.pred_margin),'pred_total':float(game.pred_total),
                'cdf_below':float(bounds[0]),'cdf_at':float(bounds[1]),'target':target,'residual_max_season':int(prior.season.max()),
                'residual_count':len(prior),'tie_rate_prior':float(tie),'home_spread_odds':float(market.home_spread_odds),'away_spread_odds':float(market.away_spread_odds)})
    frame=pd.DataFrame(rows);dev=frame[frame.season.isin(d['calibration_fit_seasons'])];test=frame[frame.season.isin(d['evaluation_seasons'])]
    assert set(dev.game_id).isdisjoint(test.game_id) and dev.season.max()<test.season.min()
    bounds=dev[['cdf_below','cdf_at']].to_numpy();y=dev.target.to_numpy(int)
    def objective(theta):
        p=probabilities_from_bounds(bounds,theta[0],np.exp(theta[1]));nll=metric_arrays(y,p)[1].mean()
        return nll+.01*float(np.dot(theta,theta))
    opt=minimize(objective,np.array(d['calibrator']['initial']),method='L-BFGS-B',bounds=d['calibrator']['bounds'],options={'maxiter':1000,'ftol':1e-12,'gtol':1e-8})
    if not opt.success:raise ValueError('FIT_FAILED:'+opt.message)
    intercept=float(opt.x[0]);slope=float(np.exp(opt.x[1]))
    model={'schema':'nfl.spread_cdf_calibration.v1','model_id':MODEL_ID,'reference_model_id':REFERENCE_ID,'intercept':intercept,'slope':slope,
        'formula':'G(F)=sigmoid(intercept+slope*logit(F)); exact endpoints','fit_seasons':d['calibration_fit_seasons'],'fit_games':len(dev),
        'fitted_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'fit_objective':float(opt.fun),'optimization_success':bool(opt.success),
        'design_sha256':digest(a.design),'input_sha256':d['input_sha256'],'reference_packed_artifact_sha256':digest(ROOT/'data/nfl/contextual_v1/model_packed.json'),
        'research_only':True,'promotion':False,'period':'FULL_GAME','prediction_target':'FINAL_HOME_MARGIN_CDF_INCLUDING_OVERTIME',
        'calibration_fit_method':'FIXED_PENALIZED_MONOTONE_SIGMOID_CDF','historical_line_timestamps':'UNVERIFIED','canonical_prospective_eligible':False}
    # The coefficient artifact is frozen before test scoring; it is not refit after evaluation.
    write(a.output/'model.json',model)
    bp=probabilities_from_bounds(test[['cdf_below','cdf_at']].to_numpy());cp=probabilities_from_bounds(test[['cdf_below','cdf_at']].to_numpy(),intercept,slope);yt=test.target.to_numpy(int)
    raw=metrics(yt,bp);cal=metrics(yt,cp);b0,l0=metric_arrays(yt,bp);b1,l1=metric_arrays(yt,cp);delta=b1-b0
    seeds=d['uncertainty']['seed'];rng=np.random.default_rng(seeds);seasons=sorted(test.season.unique());sums=np.array([delta[test.season.to_numpy()==s].sum() for s in seasons]);counts=np.array([(test.season==s).sum() for s in seasons]);ix=rng.integers(len(seasons),size=(10000,len(seasons)));season_ci=np.quantile(sums[ix].sum(1)/counts[ix].sum(1),[.025,.975]).tolist()
    boot=[]
    for _ in range(100):boot.extend(delta[rng.integers(len(delta),size=(100,len(delta)))].mean(1))
    game_ci=np.quantile(boot,[.025,.975]).tolist()
    per_season=[{'season':int(s),'games':int((test.season==s).sum()),'paired_three_way_brier_delta':float(delta[test.season.to_numpy()==s].mean())} for s in seasons]
    odds_ok=np.isfinite(test[['home_spread_odds','away_spread_odds']]).all(axis=1)&(test.home_spread_odds.abs()>=100)&(test.away_spread_odds.abs()>=100)&(test.target!=1)
    def implied(o):return np.where(o<0,-o/(100-o),100/(100+o))
    oo=test[odds_ok];ph=implied(oo.home_spread_odds.to_numpy());pa=implied(oo.away_spread_odds.to_numpy());market_p=ph/(ph+pa);market_y=(oo.target.to_numpy()==0).astype(float)
    market={'games':len(oo),'conditional_nonpush_brier':float(np.mean((market_p-market_y)**2)),'scope':'Same historical line and odds; quote time unknown; not executable edge evidence'}
    groups={}
    masks={'Week1':test.week==1,'integer_line':test.home_handicap%1==0,'half_point_line':test.home_handicap%1!=0,
           'key_3':test.home_handicap.abs()==3,'key_7':test.home_handicap.abs()==7,'small_line_abs_le_3':test.home_handicap.abs()<=3,
           'home_underdog':test.home_handicap>0,'home_favorite':test.home_handicap<0}
    for name,mask in masks.items():
        if mask.any():groups[name]={'raw':metrics(yt[mask],bp[mask]),'calibrated':metrics(yt[mask],cp[mask])}
    gate=cal['three_way_brier']<=raw['three_way_brier']-d['primary']['minimum_improvement'] and season_ci[1]<0 and cal['three_way_log_loss']<=raw['three_way_log_loss']
    evaluation={'status':'COMPLETED_REUSED_RETROSPECTIVE_SCREEN','evaluation_seasons':list(map(int,seasons)),'raw':raw,'calibrated':cal,
        'paired_three_way_brier_delta':float(delta.mean()),'season_block_95_ci':season_ci,'game_block_95_ci_secondary':game_ci,
        'retrospective_screen_passed':bool(gate),'production_promotion':False,'calibration_reliability_established':False,'market_benchmark':market,
        'per_season':per_season,'subgroups_descriptive_only':groups,'reliability':{'raw':reliability(yt,bp),'calibrated':reliability(yt,cp)},
        'limitations':['Reused history; no prospective spread evidence.','Corrected historical inputs and untimestamped odds are not an archived pregame feed.',
                       'Three test seasons limit season-bootstrap inference.','CDF transform preserves mass support and cannot fix absent score outcomes.',
                       'A lower Brier score alone does not establish calibration.','No total, first-half, live, or EV validation claim.']}
    out=test.copy()
    for i,name in enumerate(['cover','push','fail']):out['raw_'+name]=bp[:,i];out['calibrated_'+name]=cp[:,i]
    out['paired_brier_delta']=delta;out.to_csv(a.output/'evaluation_rows.csv',index=False)
    frame.to_csv(a.output/'calibration_dataset.csv',index=False)
    devmetrics={'raw':metrics(y,probabilities_from_bounds(bounds)),'calibrated':metrics(y,probabilities_from_bounds(bounds,intercept,slope))}
    write(a.output/'development_metrics.json',devmetrics);write(a.output/'evaluation.json',evaluation)
    write(a.output/'exclusions.json',{'excluded':exclusions,'forecast_games_considered':int(full.season.isin(d['calibration_fit_seasons']+d['evaluation_seasons']).sum()),'included':len(frame)})
    write(a.output/'manifest.json',{'created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'design_sha256':digest(a.design),
        'code_sha256':{str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),ROOT/'models/nfl/contextual/spread_calibration.py']},
        'outputs':{p.name:digest(p) for p in a.output.iterdir() if p.is_file()}})
    print(json.dumps({'fit':{'intercept':intercept,'slope':slope,'games':len(dev)},'raw':raw,'calibrated':cal,'delta':float(delta.mean()),'season_ci':season_ci,'screen':bool(gate),'market':market,'exclusions':exclusions},indent=2),flush=True)
if __name__=='__main__':main()
