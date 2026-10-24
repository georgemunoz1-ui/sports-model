"""Synthetic artifact-graph demonstration, explicitly not a fitted CFB forecast."""
from __future__ import annotations
import datetime as dt
from .core import *
from .registry import *


def build_fixture(store: Store) -> dict:
    prior=(utc(now())-dt.timedelta(days=2)).isoformat()
    parent=seed_state(store,'synthetic-pilot',2026)
    transitions=[]
    for week in (1,2):
        gid=f'SYNTHETIC_CFB_W{week}'
        game=dict(event_id=gid,season=2026,week=week,home_id='TEST_HOME',away_id='TEST_AWAY',kickoff=prior,
                  neutral_site=False,home_division='FBS',away_division='FBS',status='FINAL',home_score=21,away_score=14)
        rows=[dict(event_id=gid,play_id=str(i),sequence=i,season=2026,week=week,home_id='TEST_HOME',away_id='TEST_AWAY',
                   posteam='TEST_HOME' if i==0 else 'TEST_AWAY',defteam='TEST_AWAY' if i==0 else 'TEST_HOME',eligible=True,
                   dropback=True,player_id='TEST_QB_HOME' if i==0 else 'TEST_QB_AWAY',epa=float(week) if i==0 else -.5,
                   home_score=21,away_score=14,available_at=prior) for i in (0,1)]
        src=store.source(canonical([game]),'cfb_fixture_schedule','fixture://synthetic-census',scope='SYNTHETIC_TEST')
        d=store.dataset([game],src,'cfb_fixture_schedule','fixture-census-v1')
        publish_schedule(store,d,f'synthetic-week-{week}',expected_scope='FBS_VS_FBS')
        psrc=store.source(canonical(rows),'cfb_fixture_pbp','fixture://synthetic-plays',scope='SYNTHETIC_TEST')
        pd=store.dataset(rows,psrc,'cfb_fixture_pbp','fixture-pbp-v1')
        result=update_week(store,parent,f'synthetic-week-{week}',[gid],pd,now());transitions.append(result)
        replay=update_week(store,parent,f'synthetic-week-{week}',[gid],pd,now())
        require(replay['status']=='REPLAY_NOOP' and replay['child_state_hash']==result['child_state_hash'],'FIXTURE_REPLAY_FAILED')
        parent=result['child_state_hash']
    definition=seal_definition(dict(feature_id='cfb.fixture.off_epa_observed.v1',display_name='Synthetic observation mean',sport='CFB',
        prediction_mode='RESEARCH',entity_grain='team_game',target_compatibility=['home_win_probability'],source_family='cfb_fixture_pbp',
        source_dataset='synthetic',source_columns=['epa'],source_endpoint_version='fixture-v1',identity_keys=['event_id','team_id'],
        availability_rule='prior_completed',lookback_rule='fixture_two_weeks',transform_version='observed_mean_v1',unit='EPA_PER_PLAY',
        orientation='OFFENSE_POSITIVE',missingness_policy='reject',eligible_competition='FBS_VS_FBS',status='CANDIDATE',owner='TEST',requires_denominator=True))
    fh=feature_set(store,'fixture-feature-set-v1',[definition],[definition['feature_id']])
    code=store.put('code',{'scope':'SYNTHETIC_FIXTURE_NO_TRAINING','version':'fixture-v1'})
    env=store.put('environment',{'scope':'SYNTHETIC_TEST'})
    training=store.put('training_dataset',{'scope':'SYNTHETIC_FIXTURE_NOT_TRAINED','rows':[]})
    model=store.put('model',{'sport':'CFB','feature_set_hash':fh,'target':'home_win_probability','available_at':now(),'fitted':False,'scope':'SYNTHETIC_TEST'},
                    {'feature_set':fh,'training_data':training,'code':code,'environment':env})
    calibration=store.put('calibration',{'target':'home_win_probability','available_at':now(),'fitted':False,'scope':'SYNTHETIC_TEST'},
                          {'model':model,'calibration_data':training})
    cutoff=now();event=dict(event_id='SYNTHETIC_CFB_W3',season=2026,week=3,home_id='TEST_HOME',away_id='TEST_AWAY',kickoff=(utc(cutoff)+dt.timedelta(days=1)).isoformat())
    s=store.node(parent)['payload'];state_metric=s['teams']['TEST_HOME'];source=store.node(psrc)['payload']
    row=dict(package_id='SYNTHETIC_PACKAGE',event_id=event['event_id'],season=2026,week=3,team_id='TEST_HOME',opponent_team_id='TEST_AWAY',home_away='HOME',
             feature_id=definition['feature_id'],feature_value_raw=state_metric['off_epa_sum']/state_metric['off_n'],feature_value_model=state_metric['off_epa_sum']/state_metric['off_n'],
             numerator=state_metric['off_epa_sum'],denominator=state_metric['off_n'],is_missing=False,missingness_reason=None,source_snapshot_id='fixture-pbp',
             source_content_hash=source['raw_hash'],source_max_event_time=prior,available_at=source['available_at'],forecast_cutoff=cutoff,as_of_eligible=True,
             transform_version=definition['transform_version'],feature_definition_hash=definition['definition_hash'],created_at=now(),validation_status='PASS')
    # Both weeks contribute; state graph retains the earlier source, not only the
    # last raw source. This fixture records all such dependencies on its state.
    feature=snapshot(store,fh,parent,event,[row],{'fixture-pbp':psrc},cutoff)
    projection={'home_win_probability_raw':.5,'home_win_probability':.5}
    forecast=freeze_forecast(store,feature,model,calibration,projection,mode='SYNTHETIC_TEST')
    return dict(scope='SYNTHETIC_CONTRACT_PROOF_NOT_PREDICTIVE_VALIDATION',forecast=forecast,features=feature,model=model,calibration=calibration,
                feature_set=fh,state=parent,transitions=transitions,definition=definition,row=row,event=event,source_hash=psrc,cutoff=cutoff,
                state_feature_value=row['feature_value_model'],proof=store.verify(forecast),live_forecasts=0,models_fitted=0,action_authority=False)
