"""Build verified fusion evidence. Run as python -m research.nfl_fusion.run."""
from __future__ import annotations
import argparse,datetime as dt,hashlib,json,os,pathlib,shutil
import numpy as np
import pandas as pd
from . import contracts as C
from . import ensemble as E

def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def save(p,value):
    p=pathlib.Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:json.dump(value,f,indent=2,allow_nan=False)

def audit_current(root,out):
    receipts=json.loads((root/'package_receipts.json').read_text());frames={};loaded=[]
    for r in receipts:
        if r['status']!='CAPTURED_PACKAGE_OUTPUT':continue
        p=root/r['path']
        if sha(p)!=r['sha256']:raise ValueError('PACKAGE_OUTPUT_HASH_MISMATCH')
        frames[p.stem]=pd.read_parquet(p);loaded.append(r)
    if not {'pbp','schedules'}.issubset(frames):raise ValueError('CURRENT_SCOPE_INPUTS_MISSING')
    g=frames['schedules'];g=g[g.game_type=='REG'];p=frames['pbp'];p=p[p.season_type=='REG']
    receipt=next(r for r in loaded if r['loader']=='nflreadpy.load_pbp')
    cutoff=max(r['retrieved_at_utc'] for r in loaded);rec={**receipt,'source_url':'nflreadpy.load_pbp(2026):DERIVED_PACKAGE_OUTPUT'}
    scoped,coverage=C.select_pbp_scope(p,g,cutoff,rec)
    rows=C.observations(scoped);save(out/'current_team_observations.json',rows)
    team=frames.get('team_stats');player=frames.get('player_stats');cross=[]
    fields=['completions','attempts','passing_yards','passing_tds','passing_interceptions','carries','rushing_yards','rushing_tds','receptions','receiving_yards','receiving_tds']
    if team is not None and player is not None:
        team=team[team.game_id.isin(coverage['expected_complete_game_ids'])].copy();player=player[player.game_id.isin(coverage['expected_complete_game_ids'])].copy()
        for d in (team,player):d['team']=d.team.map(C.canonical_team)
        if team.duplicated(['game_id','team']).any():raise ValueError('DUPLICATE_TEAM_STATS_KEY')
        if player.duplicated(['game_id','team','player_id']).any():raise ValueError('DUPLICATE_PLAYER_STATS_KEY')
        for f in fields:
            if f not in team or f not in player:continue
            totals=player.groupby(['game_id','team'])[f].sum(min_count=1)
            for row in team.to_dict('records'):
                key=(row['game_id'],row['team']);a=totals.get(key);b=row[f]
                ok=pd.notna(a) and pd.notna(b) and np.isclose(a,b,rtol=0,atol=1e-8)
                cross.append({'game_id':key[0],'team':key[1],'metric':f,'player_sum':float(a) if pd.notna(a) else None,'team_value':float(b) if pd.notna(b) else None,'passed':bool(ok)})
    snap=frames.get('snap_counts');snap_checks={}
    if snap is not None:
        for field in ('offense_pct','defense_pct','st_pct'):
            x=pd.to_numeric(snap[field],errors='coerce');bad=x.notna()&~x.between(0,1)
            snap_checks[field]={'observed':int(x.notna().sum()),'invalid_fraction':int(bad.sum()),'max':float(x.max()) if x.notna().any() else None}
    depth=frames.get('depth_charts');depth_summary={}
    if depth is not None:
        times=pd.to_datetime(depth.dt,utc=True,errors='coerce');valid=times.notna()&(times<=pd.Timestamp(cutoff));d=depth[valid].copy();d['_time']=times[valid]
        latest=d[d._time==d.groupby('team')._time.transform('max')]
        depth_summary={'source_rows':len(depth),'future_or_undated_rows_excluded':int((~valid).sum()),'latest_team_snapshot_rows':len(latest),'teams':int(latest.team.nunique()),'status':'CANDIDATE_DEPTH_NOT_GAME_CONFIRMED_STARTERS'}
    roster=frames.get('rosters');roster_summary={}
    if roster is not None and player is not None:
        known=set(roster.gsis_id.dropna().astype(str));observed=set(player.player_id.dropna().astype(str))
        roster_summary={'unique_roster_gsis_ids':len(known),'observed_player_ids':len(observed),'unmatched_observed_player_ids':sorted(observed-known),'scope':'ID_CROSSWALK_ONLY; CURRENT_TEAM_ROSTER_NOT_HISTORICAL_STARTER_TRUTH'}
    report={'package_outputs_verified':len(loaded),'cutoff_utc':cutoff,'coverage':coverage,'team_observation_rows':len(rows),'counting_stat_checks':len(cross),
            'counting_stat_mismatches':sum(not r['passed'] for r in cross),'counting_stat_scope':'SAME_PROVIDER_AGGREGATION_IDENTITY_NOT_INDEPENDENT_OFFICIAL_GAMEBOOK',
            'snap_fraction_checks':snap_checks,'depth':depth_summary,'roster_id_crosswalk':roster_summary,'current_metrics_active_in_forecast':False,'production_state_updated':False,
            'injury_publication_time_verified':False,'current_assimilation_status':'OBSERVED_ONLY; WEEKLY_CHAIN_REPAIR_UNVERIFIED',
            'exclusions':['market fields and vegas models','2026 outcomes from ensemble training','unfitted pace drive WAR and xYAC effects']}
    save(out/'current_metric_audit.json',report);save(out/'counting_stat_reconciliation.json',cross)
    return report

def features_registry(root,model,out):
    history=pd.read_csv(root/'history.csv');rows=[];heads={}
    for a in E.CONTEXT:
        key=a.removeprefix('CONTEXT_').lower();params=json.loads((root/'context_fits'/f'{key}_2024.json').read_text());heads[a]=params
    all_names=heads['CONTEXT_COMBINED']['feature_names']
    for name in all_names:
        usage=[]
        for target,head in model['heads'].items():
            for arm,w in zip(head['arms'],head['weights']):
                if arm not in heads or name not in heads[arm]['feature_names']:continue
                ix=heads[arm]['feature_names'].index(name);coef=heads[arm]['heads'][target]['coefficient'][ix]
                usage.append({'target':target,'arm':arm,'ensemble_weight':w,'base_coefficient':coef,'numerically_active':bool(w>1e-10 and coef!=0)})
        rows.append({'feature':name,'finite_historical_rows':int(np.isfinite(history[name]).sum()),'missing_historical_rows':int(history[name].isna().sum()),
                     'implemented':True,'fitted':True,'used_in_historical_ensemble':any(x['numerically_active'] for x in usage),'used_in_current_forecast':False,'usage':usage})
    prior=json.loads((root/'candidate_code/candidate_registry.json').read_text())
    report={'schema':'nfl.feature_utilization.v1','context_feature_count':len(rows),'context_features':rows,'prior_candidate_families':prior['candidates'],
            'registered_does_not_mean_active':True,'additional_ensembled_arms':E.CANDIDATES,
            'additional_arms_definition':'Previously fitted lagged-scoring Ridge, coaching Ridge, and XGBoost; not WNBA/fantasy ratings or market-influenced composites',
            'source_repositories':['nflverse/nflverse-data','nflverse/nflreadpy','samhoppen/NFL_public','samhoppen/Fantasy-Evaluator','samhoppen/nflWAR_public','samhoppen/shank_wnba','shankapotomus/wnba-rapm'],
            'unfitted_or_incompatible_remain_blocked':['drive outcome/expected drive points','pace over expectation','nflWAR replacement effects','WNBA RAPM','Toto','TabICL','Granite'],
            'same_feature_in_several_models_not_independent_evidence':True}
    save(out/'feature_registry.json',report);save(out/'metric_dictionary.json',C.METRIC_DICTIONARY)
    return len(rows)

def main():
    p=argparse.ArgumentParser();p.add_argument('--inputs',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--skip-package-audit',action='store_true');a=p.parse_args()
    root=a.inputs;out=a.output;out.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((root/'distribution_manifest.json').read_text())
    for name,h in manifest.items():
        path=(root/name).resolve()
        if not path.is_relative_to(root.resolve()) or sha(path)!=h:raise ValueError('INPUT_MANIFEST_MISMATCH:'+name)
    protocol=json.loads((root/'protocol.json').read_text());frame=E.align(pd.read_csv(root/'context_oof.csv'),pd.read_csv(root/'candidate_verified/predictions.csv'),pd.read_csv(root/'historical_schedule.csv'))
    model=E.fit(frame[frame.season<=2022],protocol);save(out/'ensemble_model.json',model)
    # Freeze before evaluating the test split. No parameter changes after this point.
    save(out/'model_freeze.json',{'created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'model_sha256':sha(out/'ensemble_model.json'),'protocol_sha256':C.digest(protocol),'scope':'RETROSPECTIVE_RESEARCH','current_forecasts_generated':0})
    test=frame[frame.season.between(*protocol['evaluation_years'])].copy();pred=E.predict_frame(model,test)
    cols=['p__'+x for x in E.CONTEXT+E.CANDIDATES];ml=test.home_win.notna();y=test.loc[ml,'home_win'].to_numpy(float)
    candidates={'CONTEXT_QB':test['p__CONTEXT_QB'].to_numpy(),'UNIFORM_AVAILABLE_COMPATIBLE_ARMS':test[cols].mean(axis=1).to_numpy(),
                'LEARNED_RAW':pred.home_win_raw.to_numpy(),'LEARNED_CALIBRATED':pred.home_win.to_numpy()}
    scores={};rels={}
    for name,probs in candidates.items():scores[name]=E.binary_score(y,probs[ml]);rels[name]=E.reliability(y,probs[ml])
    delta=(pred.loc[ml,'home_win'].to_numpy()-y)**2-(test.loc[ml,'p__CONTEXT_QB'].to_numpy()-y)**2
    ci=E.paired_interval(test.loc[ml],delta,protocol['bootstrap']['seed']);base=scores['CONTEXT_QB'];ens=scores['LEARNED_CALIBRATED']
    pass_screen=ens['brier']-base['brier']<=-.002 and ens['log_loss']<=base['log_loss'] and ci['ci95'][1]<0
    points={}
    for target,prefix in [('home_margin','m'),('total_points','t')]:
        truth=test[target].to_numpy();b=test[prefix+'__CONTEXT_QB'].to_numpy();e=pred[target].to_numpy()
        points[target]={'n':len(truth),'baseline_mae':float(abs(truth-b).mean()),'ensemble_mae':float(abs(truth-e).mean()),'delta_mae':float((abs(truth-e)-abs(truth-b)).mean()),'ensemble_rmse':float(np.sqrt(((truth-e)**2).mean()))}
    # Independently reloaded coefficients must replay exactly, without refitting.
    replay=E.predict_frame(json.loads((out/'ensemble_model.json').read_text()),test)
    if not np.array_equal(pred.to_numpy(),replay.to_numpy()):raise ValueError('COEFFICIENT_REPLAY_MISMATCH')
    detail=test[['game_id','season','week','home_team','away_team','home_win','home_margin','total_points']].copy()
    for n,x in candidates.items():detail[n]=x
    detail['ensemble_margin']=pred.home_margin;detail['ensemble_total']=pred.total_points;detail.to_csv(out/'evaluation_predictions.csv',index=False)
    draws,sim=E.simulate_binary(float(pred.iloc[0].home_win),'HISTORICAL_REPLAY:'+str(test.iloc[0].game_id)+':'+C.digest(model))
    again,sim2=E.simulate_binary(float(pred.iloc[0].home_win),'HISTORICAL_REPLAY:'+str(test.iloc[0].game_id)+':'+C.digest(model))
    if not np.array_equal(draws,again) or sim!=sim2:raise ValueError('DRAW_REPLAY_MISMATCH')
    np.save(out/'historical_replay_winner_draws.npy',draws,allow_pickle=False);save(out/'simulation_replay.json',{**sim,'event_id':test.iloc[0].game_id,'postgame_diagnostic_not_pregame':True})
    count=features_registry(root,model,out)
    current={'status':'NOT_RUN_LOCAL_NO_PARQUET_ENGINE'} if a.skip_package_audit else audit_current(root,out)
    result={'schema':'nfl.ensemble_evaluation.v1','completed_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'matched_common_games':len(frame),'test_games':len(test),'binary_test_games':int(ml.sum()),
            'test_years':protocol['evaluation_years'],'probability_scores':scores,'point_scores':points,'paired_brier_comparison':ci,'primary_improvement_screen_passed':bool(pass_screen),
            'weights':{k:dict(zip(v['arms'],v['weights'])) for k,v in model['heads'].items()},'calibration':model['heads']['home_win']['calibration'],
            'prediction_replay_exact':True,'simulation_replay_exact':True,'context_features_registered':count,'input_hashes_verified':len(manifest),'current_package_audit':current,
            'historical_pit_certified':False,'evidence':'REUSED_RETROSPECTIVE_SCREEN; NOT_NEW_PROSPECTIVE_ACCURACY','official_release_eligible':False,'promotion':False,'action_authority':False,'dose':0.0}
    save(out/'evaluation.json',result);save(out/'reliability.json',rels)
    save(out/'result_manifest.json',{str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()})
    print(json.dumps({k:result[k] for k in ['matched_common_games','test_games','probability_scores','point_scores','primary_improvement_screen_passed','weights','context_features_registered','current_package_audit']},indent=2))
if __name__=='__main__':main()
