"""Week 1 QB update using the existing historical dropback and retention rules."""
import copy
from .features import canonical
from .recovered_inference import digest

def prior(artifact,season):
    state=copy.deepcopy(artifact['state'])
    state_season=state['season'] if 'season' in state else max(artifact['arms']['combined']['training_seasons'])
    years=season-int(state_season)
    if years!=1:raise ValueError('QB_UPDATE_REQUIRES_NEXT_SEASON_START')
    for value in state['qb_ratings'].values():value['sum']*=.55;value['n']*=.55
    return {'qb_ratings':state['qb_ratings'],'last_qb':state['last_qb']}

def apply(artifact,evidence):
    if evidence['season']!=2026 or evidence['completed_week']!=1:raise ValueError('QB_UPDATE_SCOPE_REQUIRES_SEPARATE_WEEKLY_CHAIN')
    if evidence['parent_model_sha256']!=digest(artifact):raise ValueError('QB_PARENT_MODEL_MISMATCH')
    state=prior(artifact,evidence['season']);seen=set()
    for row in evidence['aggregates']:
        key=(row['game_id'],row['passer_player_id'])
        if key in seen:raise ValueError('DUPLICATE_QB_AGGREGATE')
        seen.add(key)
        if row['game_id'] not in evidence['completed_game_ids'] or row['dropbacks']<=0:raise ValueError('QB_AGGREGATE_BINDING')
        value=state['qb_ratings'].setdefault(row['passer_player_id'],{'sum':0.,'n':0.})
        value['sum']+=row['epa_sum'];value['n']+=row['dropbacks']
    state['last_qb'].update(evidence['completed_starters'])
    return state

def build(artifact,pbp,schedule,source_sha256):
    ids=schedule.game_id.tolist()
    if len(ids)!=16 or set(schedule.season)!={2026} or set(schedule.week)!={1}:raise ValueError('QB_WEEK1_COMPLETE_SCHEDULE_REQUIRED')
    d=pbp[pbp.game_id.isin(ids)]
    # Exactly the build_nfl_context.py convention; no new selected filters.
    d=d[(d.season_type=='REG')&(d.qb_dropback==1)&(d.qb_kneel!=1)&(d.qb_spike!=1)&d.epa.notna()&d.passer_player_id.notna()].drop_duplicates(['game_id','play_id'])
    rows=d.groupby(['game_id','passer_player_id']).epa.agg(epa_sum='sum',dropbacks='count').reset_index().to_dict('records')
    starters={}
    for row in schedule.to_dict('records'):
        for side in ('home','away'):
            q=row.get(side+'_qb_id')
            if not isinstance(q,str) or not q:raise ValueError('COMPLETED_STARTER_ID_REQUIRED')
            starters[canonical(row[side+'_team'])]=q
    ev={'season':2026,'completed_week':1,'parent_model_sha256':digest(artifact),'source_sha256':source_sha256,
        'completed_game_ids':ids,'completed_starters':starters,'aggregates':rows,
        'rule':'FROZEN_DROPBACK_FILTER_AND_0.55_OFFSEASON_RETENTION; AFTER_COMPLETE_WEEK'}
    state=apply(artifact,ev);ev['state_after_sha256']=digest(state)
    return ev

def verified(artifact,assimilation):
    ev=assimilation.get('qb_update')
    if not ev:raise ValueError('QB_WEEK1_ASSIMILATION_REQUIRED')
    if ev['source_sha256']!=assimilation['audit']['snapshot']['sha256']:raise ValueError('QB_SOURCE_MISMATCH')
    ids={r['game_id'] for r in assimilation['audit']['coverage']['rows']}
    if set(ev['completed_game_ids'])!=ids:raise ValueError('QB_COMPLETED_GAMES_MISMATCH')
    state=apply(artifact,ev)
    if digest(state)!=ev['state_after_sha256']:raise ValueError('QB_STATE_HASH_MISMATCH')
    return state
