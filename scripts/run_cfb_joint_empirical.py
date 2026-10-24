#!/usr/bin/env python3
"""Fit/evaluate or explicitly run the isolated empirical joint-score challenger."""
import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from models.cfb.joint_empirical_v1 import fit, distribution, summarize, simulate, digest, MODEL_ID
from models.current.cfb import feature_row
from models.current.common import save, current


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def data(features, history):
    f=pd.read_parquet(features)
    paths=sorted(history.glob('*.parquet'))
    if not paths:raise ValueError('HISTORICAL_SCORE_FILES_REQUIRED')
    raw=pd.concat([pd.read_parquet(p) for p in paths],ignore_index=True)
    raw=raw[raw.completed & raw.home_points.notna() & raw.away_points.notna()]
    if raw.game_id.duplicated().any():raise ValueError('DUPLICATE_SOURCE_ID')
    joined=f.merge(raw[['game_id','home_team','away_team','home_points','away_points']],on=['game_id','home_team','away_team'],validate='one_to_one',how='left')
    if joined[['home_points','away_points']].isna().any().any():raise ValueError('SOURCE_SCORE_JOIN_INCOMPLETE')
    if not np.array_equal(joined.home_points-joined.away_points,joined.home_margin):raise ValueError('SOURCE_MARGIN_MISMATCH')
    c=joined[(joined.home_division=='fbs')&(joined.away_division=='fbs')&(joined.week>=2)&(joined.season>=2006)].copy()
    c=c.sort_values(['kick','game_id'],kind='stable')
    return c,{'features_sha256':sha(features),'score_sources':{p.name:sha(p)for p in paths},'rows':len(c),'scope':'FBS_VS_FBS_WEEK2_PLUS'}


def evaluate(frame,names):
    tr=frame[frame.season<=2023];ev=frame[frame.season>=2024]
    state=fit(tr,names,pd.to_datetime(ev.kick,utc=True).min().isoformat())
    baseline=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),LogisticRegression(C=1,max_iter=2000)).fit(tr[names],(tr.home_margin>0).astype(int))
    bp=baseline.predict_proba(ev[names])[:,1];rows=[]
    for i,(_,r)in enumerate(ev.iterrows()):
        scores,_=distribution(state,[None if pd.isna(r[k])else float(r[k])for k in names]);s=summarize(scores)
        actual=np.array([r.home_points,r.away_points]);rows.append({'event_id':str(r.game_id),'season':int(r.season),'week':int(r.week),'y':int(r.home_margin>0),'p':s['home_win'],'control_p':float(bp[i]),'margin':s['home_margin'],'actual_margin':float(r.home_margin),'total':s['total'],'actual_total':float(actual.sum()),'total_interval90_hit':bool(s['total_quantiles'][0]<=actual.sum()<=s['total_quantiles'][-1]),'margin_interval90_hit':bool(s['margin_quantiles'][0]<=r.home_margin<=s['margin_quantiles'][-1])})
    def metrics(rows):
        y=np.array([r['y']for r in rows]);p=np.array([r['p']for r in rows]);b=np.array([r['control_p']for r in rows]);clip=lambda x:np.clip(x,1e-6,1-1e-6)
        ll=lambda x:float(np.mean(-y*np.log(clip(x))-(1-y)*np.log(1-clip(x))))
        return {'n':len(rows),'joint_brier':float(np.mean((p-y)**2)),'control_brier':float(np.mean((b-y)**2)),'joint_log_loss':ll(p),'control_log_loss':ll(b),'margin_mae':float(np.mean([abs(r['margin']-r['actual_margin'])for r in rows])),'total_mae':float(np.mean([abs(r['total']-r['actual_total'])for r in rows])),'margin_central80_coverage':float(np.mean([r['margin_interval90_hit']for r in rows])),'total_central80_coverage':float(np.mean([r['total_interval90_hit']for r in rows]))}
    delta=np.array([(r['p']-r['y'])**2-(r['control_p']-r['y'])**2 for r in rows]);groups={};
    for i,r in enumerate(rows):groups.setdefault((r['season'],r['week']),[]).append(i)
    ids=list(groups);rng=np.random.default_rng(20261003);boots=[]
    for _ in range(2000):
        ix=np.concatenate([groups[ids[i]]for i in rng.integers(len(ids),size=len(ids))]);boots.append(float(delta[ix].mean()))
    return {'design':'FIXED_TRAIN_THROUGH_2023_EVALUATE_2024_2025','training_rows':len(tr),'overall':metrics(rows),'by_season':{str(s):metrics([r for r in rows if r['season']==s])for s in sorted(set(r['season']for r in rows))},'paired_week_cluster_delta_brier_ci95':np.quantile(boots,[.025,.975]).tolist(),'promotion':'NOT_PROMOTED','source_pit':'HISTORICAL_RECONSTRUCTION_NOT_UNTOUCHED_HOLDOUT','cover_total_probability_calibration':'NOT_ESTABLISHED_NO_MATCHED_HISTORICAL_QUOTES'},rows


def run(package,state,date,output,quote_path=None):
    p=json.loads(package.read_text());cutoff=dt.datetime.now(dt.timezone.utc).isoformat();current(p,cutoff)
    if pd.Timestamp(state['training_cutoff'])>pd.Timestamp(cutoff):raise ValueError('FUTURE_JOINT_STATE')
    if state['features']!=p['feature_names']:raise ValueError('FEATURE_ORDER_MISMATCH')
    for name,h in p['code_pins'].items():
        if sha(ROOT/name)!=h:raise ValueError('RUNTIME_CODE_DRIFT:'+name)
    if digest({'model':p['fitted_model'],'state':p['team_state'],'parameters':p['parameters']})!=p['model_sha256']:raise ValueError('PACKAGE_STATE_HASH')
    quotes=json.loads(quote_path.read_text())if quote_path else {};rows=[];blocked=[]
    for e in p['events']:
        if e['slate_date']!=date:continue
        if dt.datetime.fromisoformat(e['start_time_utc'].replace('Z','+00:00'))<=dt.datetime.now(dt.timezone.utc):blocked.append({'event_id':e['event_id'],'disposition':'POST_START'});continue
        if e['division_scope']!='FBS_VS_FBS' or e['week']<2:raise ValueError('UNSUPPORTED_POPULATION')
        x=feature_row(p['team_state'],e,p['parameters']);scores,trace=distribution(state,[x[k]for k in state['features']]);q=quotes.get(e['event_id'],{})
        if q:raise ValueError('QUOTE_SOURCE_AND_SETTLEMENT_ADAPTER_NOT_IMPLEMENTED')
        identity=digest({'event':e,'package':sha(package),'state':state['state_sha256'],'features':x,'cutoff':cutoff,'model_id':MODEL_ID});draws,meta=simulate(scores,identity)
        folder=output/'draws'/e['event_id'].replace(':','_');folder.mkdir(parents=True)
        np.save(folder/'score_support.npy',scores,allow_pickle=False);np.save(folder/'score_draws.npy',draws,allow_pickle=False)
        line_grid={str(h):{'analytic':summarize(scores,h)['home_cover'],'simulation':summarize(draws,h)['home_cover']}for h in np.arange(-35,35.5,.5)}
        total_grid={str(t):{'analytic':summarize(scores,total_line=t)['over'],'simulation':summarize(draws,total_line=t)['over']}for t in np.arange(20,90.5,.5)}
        row={'event':e,'model_id':MODEL_ID,'analytic':summarize(scores),'simulation':summarize(draws),'simulation_metadata':meta,'feature_values':x,'consumed_state_sha256':p['model_sha256'],'package_sha256':sha(package),'joint_state_sha256':state['state_sha256'],'trace':trace,'hypothetical_home_handicap_curve':line_grid,'hypothetical_total_curve':total_grid,'market_comparison':None,'official_release_eligible':False,'action_authority':False,'disposition':'PRE_START_DIAGNOSTIC'}
        save(folder/'forecast.json',row);save(folder/'manifest.json',{f.name:sha(f)for f in folder.iterdir()if f.is_file()});rows.append(row)
    board={'model_id':MODEL_ID,'date':date,'cutoff':cutoff,'forecasts':rows,'blocked_events':blocked,'restrictions':state['limitations'],'context_used':{'weather':False,'player_availability':False},'prospective_registration':False,'official_release_eligible':False,'action_authority':False}
    save(output/'board.json',board);return board


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--features',type=Path,required=True);ap.add_argument('--history',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--package',type=Path);ap.add_argument('--date');a=ap.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    from harness.cfb_v1_port import FEATURES
    c,sources=data(a.features,a.history);save(a.output/'sources.json',sources)
    evaluation,rows=evaluate(c,FEATURES);save(a.output/'evaluation.json',evaluation);save(a.output/'evaluation_rows.json',rows)
    state=fit(c,FEATURES,dt.datetime.now(dt.timezone.utc).isoformat());save(a.output/'joint_state.json',state)
    if a.package:
        if not a.date:raise ValueError('DATE_REQUIRED')
        board=run(a.package,state,a.date,a.output/'forecast');print('FORECASTS',len(board['forecasts']))
    print(json.dumps(evaluation,indent=2))


if __name__=='__main__':main()
