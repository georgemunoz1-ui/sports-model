#!/usr/bin/env python3
"""Build, chronologically evaluate, and run a dedicated joint-half research arm."""
import argparse,datetime as dt,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from models.nfl.contextual.halftime import TARGETS,MODEL_ID,digest,fit,predict,support,sample,probabilities,metrics,quantities

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,obj):p.write_text(json.dumps(obj,indent=2,allow_nan=False))

def extract(source,features,output):
    cols=['game_id','play_id','qtr','home_team','away_team','total_home_score','total_away_score','posteam','posteam_score','defteam_score']
    rows=[];excluded=[];sources=[]
    for year in range(2015,2026):
        path=source/f'play_by_play_{year}.csv.gz';d=pd.read_csv(path,usecols=cols,low_memory=False)
        # Provider row order is chronological; play_id is NOT (inserted timeouts
        # and corrections can have later IDs than subsequent scoring plays).
        d=d[d.game_id.isin(features.loc[features.season==year,'game_id'])]
        for gid,g in d.groupby('game_id',sort=False):
            a=g[(g.qtr<=2)&g.total_home_score.notna()&g.total_away_score.notna()]
            b=g[(g.qtr==3)&g.posteam.isin([g.home_team.iloc[0],g.away_team.iloc[0]])&g.posteam_score.notna()&g.defteam_score.notna()]
            if a.empty or b.empty:excluded.append({'game_id':gid,'reason':'NO_HALF_BOUNDARY'});continue
            last=a.iloc[-1];first=b.iloc[0];ph=first.posteam==first.home_team
            h,a1=float(last.total_home_score),float(last.total_away_score)
            hcheck=float(first.posteam_score if ph else first.defteam_score);acheck=float(first.defteam_score if ph else first.posteam_score)
            if (h,a1)!=(hcheck,acheck):excluded.append({'game_id':gid,'reason':'HALF_BOUNDARY_DISAGREEMENT','q2':[h,a1],'q3':[hcheck,acheck]});continue
            rows.append({'game_id':gid,'h1_home':h,'h1_away':a1,'last_q2_play_id':float(last.play_id),'first_q3_play_id':float(first.play_id)})
        sources.append({'path':str(path),'sha256':sha(path)});print('Extracted',year,flush=True)
    labels=pd.DataFrame(rows)
    merged=features.merge(labels,on='game_id',validate='one_to_one')
    merged['remaining_home']=(merged.total_points+merged.home_margin)/2-merged.h1_home
    merged['remaining_away']=(merged.total_points-merged.home_margin)/2-merged.h1_away
    good=(merged[TARGETS]>=0).all(axis=1)&(merged[TARGETS]==np.rint(merged[TARGETS])).all(axis=1)
    excluded.extend({'game_id':x,'reason':'INVALID_PERIOD_SCORE'} for x in merged.loc[~good,'game_id'])
    merged=merged[good].copy()
    missing=sorted(set(features.game_id)-set(merged.game_id))
    merged.to_csv(output/'joined_features_targets.csv',index=False)
    save(output/'data_audit.json',{'input_games':len(features),'usable_games':len(merged),'excluded_games':missing,'boundary_failures':excluded,'sources':sources,
         'label_rule':'LAST_Q2_POSTPLAY_SCORES_MATCH_FIRST_Q3_PREPLAY_SCORES','vintage':'CORRECTED_RETROSPECTIVE; FEATURE_AVAILABILITY_NOT_FULLY_ARCHIVED'})
    return merged

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--features',type=Path,required=True);p.add_argument('--forecast',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(exist_ok=False,parents=True)
    forecast=json.loads(a.forecast.read_text());names=list(forecast['features'])
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    design={'model_id':MODEL_ID,'created_at_utc':now,'registration':'LOCAL_RESEARCH_DESIGN_BEFORE_EXTRACTION_AND_EVALUATION','features':names,'targets':TARGETS,
       'fit':'MEDIAN_IMPUTATION_STANDARD_SCALER_RIDGE_ALPHA_50_FIXED','initial_training':'2015_2018','oof_residuals':'EXPANDING_YEAR_2019_2022',
       'evaluation':'FROZEN_2022_FIT_AND_2019_2022_OOF_RESIDUALS_EVALUATE_2023_2025','baseline':'SAME_FEATURES_FULL_GAME_RIDGE_HALVED',
       'primary':'FIRST_HALF_MARGIN_CRPS','secondary':['FIRST_HALF_TOTAL_CRPS','WINNER_3WAY_BRIER','FIXED_LINE_PROBES'],
       'line_probes':'1H_AWAY_PLUS_1.5_AND_TOTAL20.5_AND_FG_AWAY_PLUS2.5; NOT_HISTORICAL_MARKET_QUOTES',
       'promotion':'NONE; REPORT_FIXED_SPEC_RESULT_REGARDLESS_OF_SIGN','deployment':'REFIT_MEAN_THROUGH_2025; RESIDUALS_ALL_EXPANDING_OOF_2019_2025',
       'distribution':'SAME_GAME_FOUR_DIMENSION_OOF_RESIDUAL; REMOVE_POOL_MEAN; CLIP_AT_ZERO_ROUND_TO_INTEGER; REMAINING_INCLUDES_OT',
       'preserve_existing_forecast':sha(a.forecast),'feature_table_sha256':sha(a.features),'action_authority':False,'market_inputs':False}
    save(a.output/'design.json',design)
    # Additive research entry; no mutation of historical model status.
    state_path=ROOT/'state.json';state=json.loads(state_path.read_text());state.setdefault('nfl_halftime_research_designs',[]).append({'design_sha256':digest(design),'path':str(a.output/'design.json'),'created_at_utc':now,'status':'DESIGN_FROZEN_LOCAL_RESEARCH'})
    save(state_path,state)
    frame=extract(a.source,pd.read_csv(a.features),a.output)
    eval_rows=[];oof_all={};models={}
    for scaled in [False,True]:
        label='dedicated' if not scaled else 'scaled_full_game';res=[];res_year=[];oofrows=[]
        for year in range(2019,2026):
            tr=frame[frame.season<year];te=frame[frame.season==year]
            model=fit(tr,names,scaled=scaled);means=predict(model,te);errors=te[TARGETS].to_numpy(float)-means
            res.extend(errors);res_year.extend([year]*len(te))
            for gid,m,r in zip(te.game_id,means,errors):oofrows.append({'game_id':gid,'season':year,'means':m.tolist(),'residuals':r.tolist()})
        bank=np.asarray(res);yr=np.asarray(res_year)
        frozen=fit(frame[frame.season<=2022],names,scaled=scaled);test=frame[frame.season>=2023];means=predict(frozen,test)
        for row,mean in zip(test.itertuples(),means):
            stats=metrics(support(mean,bank[yr<=2022]),[getattr(row,t) for t in TARGETS])
            eval_rows.append({'game_id':row.game_id,'season':int(row.season),'arm':label,**stats})
        models[label]=fit(frame,names,scaled=scaled);oof_all[label]=bank.tolist()
        save(a.output/(label+'_oof.json'),oofrows)
        print('Fit/evaluated',label,'games',len(test),flush=True)
    ev=pd.DataFrame(eval_rows);ev.to_csv(a.output/'evaluation_games.csv',index=False)
    metrics_cols=[c for c in ev.columns if c not in ['game_id','season','arm']]
    summary={k:{c:float(v[c].mean()) for c in metrics_cols} for k,v in ev.groupby('arm')}
    summary['evaluation_games']=int(ev.game_id.nunique());summary['seasons']=[2023,2024,2025]
    summary['per_season']=ev.groupby(['arm','season'])[metrics_cols].mean().reset_index().to_dict('records')
    paired=ev.pivot(index=['game_id','season'],columns='arm',values='h1_margin_crps');delta=paired.dedicated-paired.scaled_full_game
    season_delta=delta.groupby('season').agg(['sum','count']).to_numpy();rng=np.random.default_rng(20260914);ids=rng.integers(3,size=(10000,3));boot=season_delta[ids].sum(axis=1)
    summary['primary_delta']=float(delta.mean());summary['season_bootstrap_95_ci']=(np.quantile(boot[:,0]/boot[:,1],[.025,.975])).tolist();summary['bootstrap_warning']='ONLY_THREE_SEASONS; REUSED_RETROSPECTIVE_DATA'
    reliability=[]
    for arm,v in ev.groupby('arm'):
        for key in ['h1_under_20_5','h1_away_plus_1_5','combo_away_plus_2_5_and_h1_plus_1_5']:
            buckets=np.minimum((v[key+'_p']*10).astype(int),9)
            for b in sorted(buckets.unique()):
                z=v[buckets==b];reliability.append({'arm':arm,'probe':key,'bin':int(b),'games':len(z),'predicted':float(z[key+'_p'].mean()),'observed':float(z[key+'_y'].mean())})
    summary['reliability_fixed_line_probes']=reliability
    save(a.output/'evaluation.json',summary)
    params=models['dedicated'];artifact={'model':params,'residuals':oof_all['dedicated'],'design_sha256':digest(design),'fit_completed_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'feature_table_sha256':sha(a.features)}
    save(a.output/'model.json',artifact)
    x=pd.DataFrame([forecast['features']]);mean=predict(params,x)[0]
    identity={'event':forecast['event'],'source_forecast_sha256':sha(a.forecast),'artifact_sha256':sha(a.output/'model.json'),'code_sha256':sha(ROOT/'models/nfl/contextual/halftime.py')}
    draws,info=sample(mean,artifact['residuals'],identity);replay,_=sample(mean,artifact['residuals'],identity)
    if not np.array_equal(draws,replay):raise ValueError('REPLAY_FAILED')
    if sha(a.forecast)!=design['preserve_existing_forecast']:raise ValueError('FROZEN_FORECAST_CHANGED')
    if dt.datetime.now(dt.timezone.utc)>=dt.datetime.fromisoformat(forecast['event']['start_time_utc'].replace('Z','+00:00')):raise ValueError('KICKOFF_CROSSED')
    np.save(a.output/'period_score_draws.npy',draws,allow_pickle=False)
    exact=probabilities(support(mean,artifact['residuals']));sim=probabilities(draws);q=quantities(draws)
    result={'model_id':MODEL_ID,'event':forecast['event'],'created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'input_information_cutoff_utc':forecast['cutoff_utc'],'identity':identity,'simulation':info,'exact_empirical_kernel_probabilities':exact,'simulation_probabilities':sim,
       'period_centers':dict(zip(TARGETS,map(float,mean))),'simulation_means':{k:float(v.mean()) for k,v in q.items()},
       'sampled_leg_correlation':float(np.corrcoef(q['h1_home_margin']<1.5,q['fg_home_margin']<2.5)[0,1]),
       'feature_count':len(names),'features':forecast['features'],'source_audit':forecast['audit'],'replay_verified':True,'frozen_forecast_unchanged':True,
       'independent_product_diagnostic':sim['h1_away_plus_1_5']*sim['fg_away_plus_2_5'],
       'market_capture':{'source':'USER_SCREENSHOTS_IMG7885_7886_7887; CAPTURE_DATE_TIMEZONE_NOT_VERIFIED','combo_price':.391,'h1_under_price':.50,'h1_over_price':.51,'fees_and_execution_verified':False},
       'limitations':['NEW_RESEARCH_ARM_NOT_PROMOTED','FULL_GAME_MARGINAL_DIFFERS_FROM_PRIOR_CALIBRATED_ARM','HALFTIME_AND_JOINT_CALIBRATION_NOT_ESTABLISHED','NO_HISTORICAL_1H_ODDS_ARCHIVE','EMPIRICAL_INTEGER_ROUNDING_NOT_NFL_KEY_NUMBER_MODEL','CORRECTED_HISTORICAL_SOURCE_PIT_LIMITATIONS','FINAL_TIE_AND_OT_SETTLEMENT_UNVALIDATED'],'action_authority':False}
    save(a.output/'forecast.json',result)
    save(a.output/'manifest.json',{str(p.relative_to(a.output)):sha(p) for p in a.output.rglob('*') if p.is_file()})
    print(json.dumps({'probabilities':sim,'exact':exact,'means':result['simulation_means'],'evaluation':{k:v for k,v in summary.items() if k not in ['per_season','reliability_fixed_line_probes']}},indent=2))

if __name__=='__main__':main()
