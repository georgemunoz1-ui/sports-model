#!/usr/bin/env python3
"""Fit declared market ensemble and live three-way model on chronological windows."""
import argparse,base64,datetime as dt,gzip,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np,pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from models.nfl.modes.core import LIVE_FEATURES,export_hgb,predict_live
from models.nfl.contextual.recovered_inference import digest
from models.nfl.contextual.model import load_artifact

def pack(path,obj):
    raw=json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode();path.write_text(json.dumps({'encoding':'GZIP_BASE64','sha256':hashlib.sha256(raw).hexdigest(),'payload':base64.b64encode(gzip.compress(raw,mtime=0)).decode()}))
def binary_metrics(y,p):
    y=np.asarray(y);p=np.clip(np.asarray(p),1e-12,1-1e-12);ok=np.isfinite(y);y=y[ok];p=p[ok]
    return {'games':len(y),'brier':float(np.mean((p-y)**2)),'log_loss':float(np.mean(-y*np.log(p)-(1-y)*np.log1p(-p)))}
def softmax_temp(p,t):
    z=np.log(np.clip(p,1e-15,1))/t;z-=z.max(axis=1,keepdims=True);q=np.exp(z);return q/q.sum(axis=1,keepdims=True)
def live_metrics(frame,p):
    y=frame.target.to_numpy(int);brier=((p-np.eye(3)[y])**2).sum(axis=1);ll=-np.log(np.clip(p[np.arange(len(y)),y],1e-15,1));rows=pd.DataFrame({'game_id':frame.game_id.to_numpy(),'brier':brier,'log_loss':ll})
    games=rows.groupby('game_id')[['brier','log_loss']].mean();metrics={k:float(games[k].mean()) for k in games};metrics.update({'games':len(games),'states':len(frame),'tie_games':int(frame[frame.target==2].game_id.nunique())});return metrics,games

def main():
    p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True);p.add_argument('--design',type=Path,required=True);p.add_argument('--football-model',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(exist_ok=False,parents=True);design=json.loads(a.design.read_text());start=dt.datetime.now(dt.timezone.utc).isoformat();D=design['market'];m=pd.read_csv(a.dataset/'market.csv');dev=m[m.season.isin(D['selection_seasons'])];test=m[m.season.isin(D['evaluation_seasons'])];weights={};surface={}
    for target,fc,mc,y in [('home_win','p_home','market_p_home','home_win'),('home_margin','pred_margin','spread_line','home_margin'),('total_points','pred_total','total_line','total_points')]:
        rows=[]
        for w in D['weight_grid']:
            pred=w*dev[fc]+(1-w)*dev[mc];objective=float(((pred-dev[y])**2).mean()) if target=='home_win' else float(abs(pred-dev[y]).mean());rows.append({'football_weight':w,'objective':objective})
        chosen=min(rows,key=lambda r:(r['objective'],r['football_weight']));weights[target]=chosen['football_weight'];surface[target]=rows
    # Freeze chosen weights before accessing evaluation metrics.
    selection={'selected_weights':weights,'surface':surface,'selected_at_utc':dt.datetime.now(dt.timezone.utc).isoformat()};(a.output/'market_selection.json').write_text(json.dumps(selection,indent=2))
    pred=pd.DataFrame(index=test.index)
    for t,fc,mc in [('home_win','p_home','market_p_home'),('home_margin','pred_margin','spread_line'),('total_points','pred_total','total_line')]:pred[t]=weights[t]*test[fc]+(1-weights[t])*test[mc]
    metrics={name:binary_metrics(test.home_win,pr) for name,pr in [('football',test.p_home),('market',test.market_p_home),('ensemble',pred.home_win)]}
    for name,margin,total in [('football',test.pred_margin,test.pred_total),('market',test.spread_line,test.total_line),('ensemble',pred.home_margin,pred.total_points)]:metrics[name].update({'margin_mae':float(abs(margin-test.home_margin).mean()),'margin_rmse':float(np.sqrt(((margin-test.home_margin)**2).mean())),'total_mae':float(abs(total-test.total_points).mean())})
    mask=test.home_win.notna();seasons=test.loc[mask,'season'];u=sorted(seasons.unique());delta=((pred.home_win-test.home_win)**2-(test.market_p_home-test.home_win)**2)[mask];sums=np.array([delta[seasons==s].sum() for s in u]);counts=np.array([(seasons==s).sum() for s in u]);rng=np.random.default_rng(design['bootstrap']['seed']);ix=rng.integers(len(u),size=(10000,len(u)));ci=np.quantile(sums[ix].sum(1)/counts[ix].sum(1),[.025,.975]).tolist()
    dm=weights['home_margin']*dev.pred_margin+(1-weights['home_margin'])*dev.spread_line;tot=weights['total_points']*dev.pred_total+(1-weights['total_points'])*dev.total_line;resid=np.column_stack([(dev.home_margin+dev.total_points-dm-tot)/2,(dev.total_points-dev.home_margin+dm-tot)/2]);tie=(dev.home_win.isna().sum()+.5)/(len(dev)+1)
    market={'schema':'nfl.market_ensemble.v1','model_id':D['model_id'],'design_sha256':digest(design),'weights':weights,'football_model_id':D['football_arm'],'football_artifact_sha256':digest(load_artifact(a.football_model)),'final_score_residuals':resid.tolist(),'tie_rate':float(tie),'residual_fit_seasons':D['selection_seasons'],'market_input':True,'research_only':True,'training_quote_semantics':D['historical_quote_time'],'input_targets':'BINARY_NON_TIE_PROBABILITY; FINAL_MARGIN_AND_TOTAL'}
    pack(a.output/'market_model.json',market);r=test.copy()
    for c in pred:r['ensemble_'+c]=pred[c]
    r.to_csv(a.output/'market_evaluation_rows.csv',index=False)
    market_eval={'selection':selection,'evaluation_seasons':D['evaluation_seasons'],'metrics':metrics,'paired_brier_ensemble_minus_market':float(delta.mean()),'paired_season_bootstrap_95_ci':ci,'screen_passed':metrics['ensemble']['brier']<=min(metrics['football']['brier'],metrics['market']['brier'])-.002 and ci[1]<0 and metrics['ensemble']['log_loss']<=metrics['market']['log_loss'],'promotion':False}
    (a.output/'market_evaluation.json').write_text(json.dumps(market_eval,indent=2));print('MARKET',json.dumps(market_eval),flush=True)
    L=design['live'];f=pd.read_csv(a.dataset/'live.csv');train=f[f.season.isin(L['fit_seasons'])];cal=f[f.season.isin(L['temperature_selection_seasons'])];test=f[f.season.isin(L['evaluation_seasons'])]
    def fit(frame):
        est=HistGradientBoostingClassifier(**{k:L[k] for k in ['learning_rate','max_iter','max_leaf_nodes','min_samples_leaf','l2_regularization','early_stopping','random_state']});counts=frame.groupby('game_id').game_id.transform('count');weight=len(frame)/(frame.game_id.nunique()*counts)
        est.fit(frame[LIVE_FEATURES].to_numpy(float),frame.target.to_numpy(int),sample_weight=weight.to_numpy());return est
    est=fit(train);print('LIVE temporal fit complete',len(train),flush=True);raw=est.predict_proba(cal[LIVE_FEATURES].to_numpy(float));surface=[]
    for t in L['temperature_grid']:
        met,_=live_metrics(cal,softmax_temp(raw,t));surface.append({'temperature':t,**met})
    temp=min(surface,key=lambda r:(r['log_loss'],abs(r['temperature']-1),r['temperature']))['temperature'];(a.output/'live_selection.json').write_text(json.dumps({'selected_temperature':temp,'surface':surface,'selected_at_utc':dt.datetime.now(dt.timezone.utc).isoformat()},indent=2))
    # Evaluation now uses the fixed pre-2021 model and 2021-22 temperature.
    pp=softmax_temp(est.predict_proba(test[LIVE_FEATURES].to_numpy(float)),temp);unique_train=train.drop_duplicates('game_id');tie=(sum(unique_train.target==2)+.5)/(len(unique_train)+1);mp=test.market_p_home.to_numpy();prior=np.column_stack([(1-tie)*(1-mp),(1-tie)*mp,np.full(len(test),tie)])
    mm,gg=live_metrics(test,pp);bm,bg=live_metrics(test,prior);dd=(gg.brier-bg.brier).to_numpy();rng=np.random.default_rng(design['bootstrap']['seed']);boots=[]
    for _ in range(100):boots.extend(dd[rng.integers(len(dd),size=(100,len(dd)))].mean(1))
    ci=np.quantile(boots,[.025,.975]).tolist();period={str(q):live_metrics(test[test.quarter==q],pp[(test.quarter==q).to_numpy()])[0] for q in sorted(test.quarter.unique())}
    calibration=[]
    for lo in np.arange(0,1,.1):
        mask=(pp[:,1]>=lo)&(pp[:,1]<lo+.1);subset=test[mask]
        if len(subset):calibration.append({'bin_low':float(lo),'states':len(subset),'mean_home_p':float(pp[mask,1].mean()),'observed_home_win_rate':float((subset.target==1).mean()),'aggregation':'STATE_WEIGHTED_DESCRIPTIVE'})
    export=export_hgb(est,temp);idx=np.linspace(0,len(test)-1,min(1000,len(test)),dtype=int);err=float(abs(predict_live(export,test[LIVE_FEATURES].to_numpy(float)[idx])-pp[idx]).max())
    if err>1e-12:raise ValueError('LIVE_EXPORT_REPRODUCTION:'+str(err))
    live_eval={'metrics':mm,'pregame_market_baseline':bm,'paired_game_brier_delta':float(dd.mean()),'game_block_bootstrap_95_ci':ci,'screen_passed':dd.mean()<=-.01 and ci[1]<0 and mm['log_loss']<bm['log_loss'],'temperature':temp,'export_max_absolute_probability_error':err,'by_quarter':period,'calibration_bins':calibration,'training_seasons':L['fit_seasons'],'calibration_seasons':L['temperature_selection_seasons'],'evaluation_seasons':L['evaluation_seasons'],'promotion':False,'live_vs_pregame_comparison':'VALUE_OF_OBSERVING_GAME_STATE; NOT_EQUAL_INFORMATION_MODEL_SUPERIORITY'}
    r=test[['game_id','play_id','season','target','quarter']].copy()
    for i,c in enumerate(['away','home','tie']):r['p_'+c]=pp[:,i];r['prior_'+c]=prior[:,i]
    r.to_csv(a.output/'live_evaluation_rows.csv',index=False);gg.assign(prior_brier=bg.brier,prior_log_loss=bg.log_loss).to_csv(a.output/'live_game_metrics.csv');(a.output/'live_evaluation.json').write_text(json.dumps(live_eval,indent=2));print('LIVE EVAL',json.dumps(live_eval),flush=True)
    final=fit(f[f.season.isin(L['final_fit_seasons'])]);final_export=export_hgb(final,temp);testx=test[LIVE_FEATURES].to_numpy(float)[idx];err=float(abs(predict_live(final_export,testx)-softmax_temp(final.predict_proba(testx),temp)).max());assert err<1e-12
    live={'schema':'nfl.live_state_hgb.v1','model_id':L['model_id'],'design_sha256':digest(design),'model':final_export,'training_seasons':L['final_fit_seasons'],'training_states':len(f),'training_games':int(f.game_id.nunique()),'export_max_error':err,'market_input':True,'research_only':True,'target_classes':['AWAY_WIN','HOME_WIN','TIE'],'prediction_target':L['target'],'max_input_age_seconds':L['live_input_max_age_seconds'],'limitations':['HISTORICAL_CORRECTED_PBP_NOT_ORIGINAL_LIVE_RECEIPTS','NO_DIRECT_OVERTIME_POSSESSION_ENTITLEMENT_FEATURE','PREGAME_MARKET_PRIOR_NOT_LIVE_ODDS','REQUIRES_PREPLAY_SCRIMMAGE_STATE','WINNER_ONLY_NOT_SCORE_OR_DRIVE_SIMULATOR']}
    pack(a.output/'live_model.json',live)
    fixture=f[f.season==2025].iloc[-1];state={'home_score':int(fixture.home_score),'away_score':int(fixture.away_score),'seconds_remaining':float(fixture.seconds_remaining),'quarter_seconds_remaining':float(fixture.quarter_seconds_remaining),'quarter':int(fixture.quarter),'possession':'HOME' if fixture.possession_home else 'AWAY','yardline_100':float(fixture.yardline_100),'down':int(fixture.down),'yards_to_go':float(fixture.yards_to_go),'home_timeouts':int(fixture.home_timeouts),'away_timeouts':int(fixture.away_timeouts)}
    (a.output/'live_fixture.json').write_text(json.dumps({'event_id':fixture.game_id,'play_id':float(fixture.play_id),'state':state,'pregame_home_probability':float(fixture.market_p_home),'use':'HISTORICAL_COMPUTATIONAL_REPLAY; NO_ASOF_LIVE_CLAIM'},indent=2))
    (a.output/'fit_manifest.json').write_text(json.dumps({'started_at_utc':start,'completed_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'design_sha256':digest(design),'data_audit_sha256':hashlib.sha256((a.dataset/'data_audit.json').read_bytes()).hexdigest(),'outputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in a.output.iterdir() if p.is_file()}},indent=2));print('FINAL MODEL FIT COMPLETE',flush=True)
if __name__=='__main__':main()
