#!/usr/bin/env python3
"""Reconcile a captured current week and optionally reconstruct historical state."""
import argparse,datetime as dt,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from models.nfl.contextual import base_features as bf
from models.nfl.contextual.assimilation import (run_nfl_assimilation_check,serialize_states,
    trace_feature_effects_into_forecasts,write_once,PBP_REQUIRED)
from models.nfl.contextual.recovered_inference import digest

def rebuild_history(source,output,params):
    source=Path(source);games=pd.read_csv(source/'nfl_games.csv',low_memory=False)
    games=games[(games.game_type=='REG') & games.season.between(2015,2025)].copy()
    for c in ['home_team','away_team']:games[c]=games[c].replace(bf.TEAM_ALIASES)
    states={};receipts=[];proof=None
    for year in range(2015,2026):
        path=source/f'play_by_play_{year}.csv.gz'
        pbp=pd.read_csv(path,usecols=lambda c:c in bf.PBP_REQUIRED,low_memory=False)
        if 'no_play' not in pbp:pbp['no_play']=pbp.play_type.astype('string').str.lower().eq('no_play').fillna(False).astype('int8')
        for c in ['posteam','defteam']:pbp[c]=pbp[c].replace(bf.TEAM_ALIASES)
        pbp=pbp[pbp.season_type=='REG'];plays,audit=bf._qualifying_plays(pbp)
        if year>2015:
            for state in states.values():state.shrink_offseason()
        for week,gw in games[games.season==year].groupby('week',sort=True):
            for team in set(gw.home_team)|set(gw.away_team):states.setdefault(team,bf.TeamState())
            before=__import__('copy').deepcopy(states)
            obs=bf._weekly_observations(gw,plays[plays.game_id.isin(gw.game_id)],states)
            for team,(record,n) in obs.items():states[team].update(record,n)
            if year==2025 and week==17:
                candidates=games[(games.season==2025)&(games.week==18)&((games.home_team=='KC')|(games.away_team=='KC'))]
                request=candidates.iloc[0].to_dict();request['home_score']=None;request['away_score']=None
                proof=trace_feature_effects_into_forecasts(before,states,request,params)
                proof['update_game_ids']=gw.game_id.tolist();proof['source_sha256']=bf.sha256_file(path)
                proof['historical_availability']='reconstruction from later archived source; NOT prospective'
                # Run the same receipt/reconciliation/update/forecast orchestrator on
                # a complete real historical week, not just a mathematical fixture.
                all_plays=pd.read_csv(path,usecols=lambda c:c in set(PBP_REQUIRED)|{'order_sequence'},low_memory=False)
                all_plays=all_plays[all_plays.game_id.isin(gw.game_id)].copy()
                for c in ['home_team','away_team','posteam','defteam']:all_plays[c]=all_plays[c].replace(bf.TEAM_ALIASES)
                derived=Path(output)/'historical_proof_source.csv';all_plays.to_csv(derived,index=False)
                receipt={'source_url':'derived-from:'+str(path),'retrieved_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
                  'sha256':bf.sha256_file(derived),'parent_raw_sha256':bf.sha256_file(path),
                  'derivation':'column projection + week17 selection + frozen team alias normalization',
                  'historical_pregame_availability':'NOT_CLAIMED'}
                check=run_nfl_assimilation_check(path=derived,receipt=receipt,schedule=gw,
                  cutoff=dt.datetime.now(dt.timezone.utc).isoformat(),archive=Path(output)/'proof_snapshots',
                  output=Path(output)/'historical_end_to_end',prior_states=before,forecast_requests=[request],params=params)
                proof['reconciled_end_to_end_status']=check['status']
                proof['reconciled_state_update_applied']=check['state_update_applied']
        receipts.append({'season':year,'sha256':bf.sha256_file(path),**audit})
        print('Rebuilt historical season',year,flush=True)
    for state in states.values():state.shrink_offseason()
    result={'schema':'nfl.reconstructed_week_start_state.v1','season':2026,'week':1,
      'states':serialize_states(states),'source_receipts':receipts,'schedule_sha256':bf.sha256_file(source/'nfl_games.csv'),
      'base_feature_code_sha256':bf.sha256_file(ROOT/'models/nfl/contextual/base_features.py'),
      'proof':proof,'state_sha256':digest(serialize_states(states))}
    write_once(Path(output)/'historical_state.json',result)
    return states

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--season',type=int,default=2026);p.add_argument('--week',type=int,default=1)
    p.add_argument('--historical-source',type=Path);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    records=json.loads((a.source/'receipt.json').read_text());receipt=next(r for r in records if r['filename']==f'play_by_play_{a.season}.csv')
    schedule_receipt=next(r for r in records if r['filename']=='games.csv')
    if bf.sha256_file(a.source/'games.csv')!=schedule_receipt['sha256']:raise ValueError('SCHEDULE_RAW_HASH_MISMATCH')
    all_games=pd.read_csv(a.source/'games.csv',low_memory=False);schedule=all_games.copy();schedule=schedule[(schedule.season==a.season)&(schedule.week==a.week)&(schedule.game_type=='REG')]
    from models.nfl.contextual.model import load_artifact
    model=load_artifact(ROOT/'data/nfl/contextual_v1/model_packed.json')
    params=model['arms']['base']
    states=rebuild_history(a.historical_source,a.output,params) if a.historical_source else None
    requests=all_games[(all_games.season==a.season)&(all_games.week==a.week+1)&(all_games.game_type=='REG')].to_dict('records')
    # Drop realized targets: this is a state sensitivity demonstration, not a fresh card.
    for request in requests:
        for key in ('home_score','away_score','result','total'):request[key]=None
    result=run_nfl_assimilation_check(path=a.source/receipt['filename'],receipt=receipt,schedule=schedule,
      cutoff=dt.datetime.now(dt.timezone.utc).isoformat(),archive=a.output/'snapshots',output=a.output/'current_week',prior_states=states,params=params,forecast_requests=requests)
    if result['state_update_applied']:
        from models.nfl.contextual.week2 import require_assimilation
        after=json.loads((a.output/'current_week/team_state.json').read_text())
        evidence={'audit':result,'state_before':serialize_states(states),'state_after':after,
          'base_feature_code_sha256':bf.sha256_file(ROOT/'models/nfl/contextual/base_features.py'),
          'schedule_receipt':schedule_receipt}
        from models.nfl.contextual.qb_assimilation import build,apply,prior
        from models.nfl.contextual.features import qb_features
        pbp=pd.read_csv(a.source/receipt['filename'],low_memory=False)
        evidence['qb_update']=build(model,pbp,schedule,receipt['sha256'])
        qb_before=prior(model,a.season);qb_after=apply(model,evidence['qb_update'])
        event_rows={};checks={};qb_traces={}
        for request in requests:
            row=bf._feature_row(pd.Series(request),bf.TeamState(**after[request['home_team']]),bf.TeamState(**after[request['away_team']]))
            row={k:(None if pd.isna(v) else v) for k,v in row.items()}
            event={'event_id':request['game_id'],'home_team':request['home_team'],'away_team':request['away_team'],
                   'gameday':request['gameday'],'gametime':request.get('gametime'),'location':request['location']}
            checks[event['event_id']]=require_assimilation(row,{'assimilation':evidence},event,result['cutoff_utc'])
            event_rows[event['event_id']]=row
            before_row=bf._feature_row(pd.Series(request),states[request['home_team']],states[request['away_team']])
            from models.nfl.contextual.recovered_inference import predict
            qb_params=model['arms']['qb']
            old={**before_row,**qb_features(request,qb_before['qb_ratings'],qb_before['last_qb'])}
            new={**row,**qb_features(request,qb_after['qb_ratings'],qb_after['last_qb'])}
            clean=lambda x:{k:None if pd.isna(x[k]) else float(x[k]) for k in qb_params['feature_names']}
            b,c=clean(old),clean(new);bp=predict(qb_params,b)['prediction'];cp=predict(qb_params,c)['prediction']
            qb_traces[event['event_id']]={'model_id':qb_params['model_id'],'before_features':b,'after_features':c,
              'prediction_before':bp,'prediction_after':cp,'delta':{k:cp[k]-bp[k] for k in bp},
              'scope':'STATE_SENSITIVITY_ONLY; SCHEDULE_QB_IDS_NOT_FRESH_CONFIRMED_STARTERS'}
        write_once(a.output/'week2_state_packet.json',{'scope':'STATE_ONLY_NOT_FRESH_PREGAME_CONTEXT',
          'forecast_parameter_model_id':params['model_id'],'forecast_parameter_sha256':digest(params),
          'assimilation':evidence,'event_base_rows':event_rows,'runtime_state_checks':checks,'default_qb_state_traces':qb_traces,
          'official_gamebook_clearance':False,'action_authority':False})
    if states:
        packet=json.loads((ROOT/'data/nfl/contextual_v1/event_package_v2.json').read_text());base=packet['event_inputs']['2026_01_DEN_KC']['base']
        game=schedule[schedule.game_id=='2026_01_DEN_KC'].iloc[0]
        rebuilt=bf._feature_row(game,states['KC'],states['DEN'])
        keys=[k for k in bf.MODEL_FEATURES if k not in {'temperature_f','wind_mph','weather_missing'}]
        differences={k:float(rebuilt[k])-float(base[k]) for k in keys}
        write_once(a.output/'mnf_state_reconstruction.json',{'event_id':'2026_01_DEN_KC','differences':differences,
          'max_absolute_difference':max(abs(v) for v in differences.values()),'comparison':'stored 10-decimal baseline vs rebuilt frozen transform',
          'week1_results_used_for_mnf':False})
    print(json.dumps({'status':result['status'],'coverage':result.get('coverage'),'state_update_applied':result['state_update_applied']},indent=2))

if __name__=='__main__':main()
