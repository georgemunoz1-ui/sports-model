"""Post-start QB research reconstruction; never a forecast or registration.

Separates information availability from the real processing/review clock.
Uses unchanged fitted feature, head and Monte Carlo primitives. It cannot
publish into the prospective forecast stream or bypass the live runner.
"""
import datetime as dt
import hashlib
import json
import math
import re
import pandas as pd
from pathlib import Path
from . import weekly_state as ws
from .features import qb_features
from .recovered_inference import bind_context, predict, digest, bernoulli_simulation, utc


def _source_before(source, information_cutoff):
    receipt = source['receipt']
    if hashlib.sha256(source['text'].encode()).hexdigest() != receipt['sha256']:
        raise ValueError('RECONSTRUCTION_SOURCE_HASH')
    for field in ('retrieved_at_utc', 'available_at_utc', 'source_published_at_utc'):
        if (field == 'retrieved_at_utc' or receipt.get(field)) and utc(receipt[field]) > utc(information_cutoff):
            raise ValueError('RECONSTRUCTION_SOURCE_AFTER_INFORMATION_CUTOFF')


def run_qb(artifact, recovered, base, context, event, information_cutoff, *, seed_id, personnel_source, n=100000):
    created = dt.datetime.now(dt.timezone.utc).isoformat()
    if utc(information_cutoff) >= utc(event['start_time_utc']):
        raise ValueError('RECONSTRUCTION_INFORMATION_CUTOFF_NOT_PRESTART')
    if utc(created) < utc(event['start_time_utc']):
        raise ValueError('RECONSTRUCTION_POST_START_ONLY')
    if n != 100000:
        raise ValueError('RECONSTRUCTION_REQUIRES_100000_DRAWS')
    if base['game_id'] != event['event_id'] or (base['home_team'],base['away_team']) != (event['home_team'],event['away_team']):
        raise ValueError('RECONSTRUCTION_EVENT_BINDING')
    if any(base.get(k) is not None for k in ('home_score','away_score','result','total')):
        raise ValueError('RECONSTRUCTION_TARGET_OUTCOME_FORBIDDEN')
    # Verify the real newly built chain at the real clock. Do not backdate reviews.
    ev=context['weekly_state']
    state=ws.for_event(context,artifact,event,created)
    flow=ws.require_features(base,state,event)
    _source_before(personnel_source,information_cutoff)
    pr=personnel_source['receipt']; pj=json.loads(personnel_source['text'])
    header=pj['header']; competition=header['competitions'][0]
    schedule=ws._schedule(state['schedule_source'],state['season'],created)
    event_rows=schedule[schedule.game_id==event['event_id']]
    if len(event_rows)!=1: raise ValueError('RECONSTRUCTION_SCHEDULE_EVENT')
    scheduled=event_rows.iloc[0]
    expected_row=scheduled.to_dict()
    expected_row.update(home_score=None,away_score=None,temp=None,wind=None)
    expected_base=ws.bf._feature_row(pd.Series(expected_row),
        ws.bf.TeamState(**state['team_state'][event['home_team']]),
        ws.bf.TeamState(**state['team_state'][event['away_team']]))
    expected_base={k:None if isinstance(v,float) and not math.isfinite(v) else v for k,v in expected_base.items()}
    if digest(base)!=digest(expected_base):
        raise ValueError('RECONSTRUCTION_ARCHIVED_BASE_BINDING')
    if (str(header['id'])!=str(scheduled.espn) or utc(competition['date'])!=utc(event['start_time_utc'])
            or competition['status']['type']['completed']):
        raise ValueError('RECONSTRUCTION_PRESTART_PERSONNEL_EVENT')
    teams={t['homeAway']:t['team']['abbreviation'] for t in competition['competitors']}
    if any(teams[s]!=event[s+'_team'] for s in ('home','away')):
        raise ValueError('RECONSTRUCTION_PERSONNEL_TEAM')
    if (pr['source_url']!='https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event='+str(header['id'])
            or pr['sha256']!=context['personnel']['source_sha256']):
        raise ValueError('RECONSTRUCTION_PERSONNEL_SOURCE_BINDING')
    key=ev['state_id']; receipts=[]
    while True:
        node=ws._get(ev['store'],key)
        _source_before(node['schedule_source'],information_cutoff)
        receipts.append(node['schedule_source']['receipt'])
        if node['kind']=='seed':
            if key != seed_id: raise ValueError('RECONSTRUCTION_SEED_PIN')
            for r in node.get('starter_adjudications',[]):
                _source_before(r['evidence'],information_cutoff)
                receipts.append(r['evidence']['receipt'])
            for receipt in node['historical_seed']['source_receipts']:
                for clock in ('retrieved_at_utc','available_at_utc','source_published_at_utc'):
                    if receipt.get(clock) and utc(receipt[clock])>utc(information_cutoff):
                        raise ValueError('RECONSTRUCTION_HISTORICAL_SOURCE_AFTER_CUTOFF')
            break
        _source_before(node['pbp_source'],information_cutoff)
        receipts.append(node['pbp_source']['receipt']);key=node['parent_id']
    if event['event_id'] in state['consumed_game_ids']:
        raise ValueError('RECONSTRUCTION_TARGET_ALREADY_CONSUMED')
    if set(context)!={'weekly_state','personnel','rest'}:
        raise ValueError('RECONSTRUCTION_UNSUPPORTED_CONTEXT')
    rest=context['rest']; sr=state['schedule_source']['receipt']
    if (rest['source_sha256']!=sr['sha256'] or rest['source']!=sr['source_url']
            or rest['home_rest']!=scheduled.home_rest or rest['away_rest']!=scheduled.away_rest
            or rest['retrieved_at_utc']!=sr['retrieved_at_utc']):
        raise ValueError('RECONSTRUCTION_ARCHIVED_REST_BINDING')
    regular={k:v for k,v in context.items() if k!='weekly_state'}
    bound=bind_context(recovered,base,regular,information_cutoff,event['start_time_utc'])
    personnel=context['personnel']['state']; row={**base,'gameday':event['gameday']}
    for side in ('home','away'):
        q=personnel['quarterbacks'][event[side+'_team']]
        if not q.get('id') or q.get('game_status')=='OUT':
            raise ValueError('RECONSTRUCTION_EXPECTED_QB_INVALID')
        if (q['id']!=scheduled[side+'_qb_id'] or q.get('name')!=scheduled[side+'_qb_name']
                or not re.search(r'href="[^\"]*/id/'+re.escape(str(q.get('espn_id')))+
                    r'/[^\"]*">'+re.escape(q['name'])+r'</a>',pj.get('article',{}).get('story',''))):
            raise ValueError('RECONSTRUCTION_QB_CROSSWALK')
        row[side+'_qb_id']=q['id']
    features={**bound['features'],**qb_features(row,state['qb_state']['qb_ratings'],state['qb_state']['last_qb'])}
    params=artifact['arms']['qb']
    if set(features)!=set(params['feature_names']):
        raise ValueError('RECONSTRUCTION_QB_FEATURE_CONTRACT')
    fitted=predict(params,features)
    code={p:hashlib.sha256(Path(__file__).with_name(p).read_bytes()).hexdigest()
          for p in ('reconstruction.py','features.py','recovered_inference.py','weekly_state.py','starter_adjudication.py')}
    identity=digest({'kind':'POST_START_ARCHIVED_INPUT_RECONSTRUCTION','event':event,'base':base,
        'context':context,'features':features,'model':digest(artifact),'information_cutoff':information_cutoff,'code':code})
    draws,simulation=bernoulli_simulation(fitted['prediction']['home_win'],identity,n)
    result={'schema':'nfl.qb_reconstruction.v1','disposition':'POST_START_RESEARCH_RECONSTRUCTION',
        'created_at_utc':created,'information_cutoff_utc':information_cutoff,'event':event,
        'model_id':params['model_id'],'model_sha256':digest(artifact),'identity':identity,'code':code,
        'state_id':ev['state_id'],'seed_id':seed_id,'features':features,'feature_trace':fitted,
        'prediction':fitted['prediction'],'winner_simulation':simulation,'assimilation':flow,
        'source_receipts':receipts,'input_sha256':digest({'base':base,'context':context}),
        'personnel_source_receipt':pr,'expected_quarterbacks':personnel['quarterbacks'],
        'canonical_prospective_eligible':False,'publication_eligibility':'INELIGIBLE',
        'predictive_validation':'NOT_ASSESSED','action_authority':False,
        'limitations':['NOT_AN_ORIGINAL_PREGAME_FORECAST','POST_START_REVIEW_AND_CODE_REPAIR',
          'EXPECTED_QBS_FROM_ARCHIVED_PREVIEW_NOT_FINAL_INACTIVES','WEATHER_NOT_ACQUIRED',
          'INHERITED_HISTORICAL_SEED_SOURCE_RETRIEVAL_CLOCKS_UNAVAILABLE',
          'NO_JOINT_SCORE_OR_ATS_SIMULATION_FOR_SELECTED_QB_ARM','NO_PROSPECTIVE_GRADING']}
    return result,draws
