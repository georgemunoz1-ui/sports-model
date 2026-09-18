"""Generic chronological QB state chain using the frozen dropback update rule."""
import copy
from .features import canonical
from .recovered_inference import digest

def offseason_prior(artifact,season):
    state=copy.deepcopy(artifact['state'])
    state_season=state['season'] if 'season' in state else max(artifact['arms']['combined']['training_seasons'])
    years=int(season)-int(state_season)
    if years!=1:raise ValueError('QB_UPDATE_REQUIRES_NEXT_SEASON_START')
    for value in state['qb_ratings'].values():value['sum']*=.55;value['n']*=.55
    return {'season':int(season),'completed_week':0,'qb_ratings':state['qb_ratings'],'last_qb':state['last_qb'],'processed_player_games':[]}

def prior(artifact,season):
    state=offseason_prior(artifact,season)
    return {'qb_ratings':state['qb_ratings'],'last_qb':state['last_qb']}

def apply_to_parent(parent,evidence):
    if int(evidence['season'])!=int(parent['season']) or int(evidence['completed_week'])!=int(parent['completed_week'])+1:
        raise ValueError('QB_WEEKLY_CHAIN_PARENT_MISMATCH')
    state={'season':int(parent['season']),'completed_week':int(evidence['completed_week']),
           'qb_ratings':copy.deepcopy(parent['qb_ratings']),'last_qb':copy.deepcopy(parent['last_qb']),
           'processed_player_games':list(parent.get('processed_player_games',[]))}
    seen=set(tuple(x) for x in state['processed_player_games']);batch=set()
    for row in evidence['aggregates']:
        key=(str(row['game_id']),str(row['passer_player_id']))
        if key in seen:raise ValueError('DUPLICATE_QB_STATE_TRANSITION:'+':'.join(key))
        if key in batch:raise ValueError('DUPLICATE_QB_AGGREGATE')
        batch.add(key)
        if row['game_id'] not in evidence['completed_game_ids'] or row['dropbacks']<=0:raise ValueError('QB_AGGREGATE_BINDING')
        value=state['qb_ratings'].setdefault(row['passer_player_id'],{'sum':0.,'n':0.})
        value['sum']+=row['epa_sum'];value['n']+=row['dropbacks']
    state['processed_player_games'].extend([list(x) for x in sorted(batch)])
    state['last_qb'].update(evidence['completed_starters'])
    return state

def apply(artifact,evidence):
    """Compatibility entry point for the frozen Week1->Week2 package."""
    if evidence['parent_model_sha256']!=digest(artifact):raise ValueError('QB_PARENT_MODEL_MISMATCH')
    if int(evidence['season'])!=2026 or int(evidence['completed_week'])!=1:raise ValueError('QB_UPDATE_SCOPE_REQUIRES_EXPLICIT_PARENT_STATE')
    state=apply_to_parent(offseason_prior(artifact,evidence['season']),evidence)
    return {'qb_ratings':state['qb_ratings'],'last_qb':state['last_qb']}

def build_from_parent(parent,pbp,schedule,source_sha256,*,authoritative_schedule_binding=None):
    from .assimilation import authoritative_schedule_binding as bind,validate_schedule_binding,scope_pbp_to_schedule
    binding=validate_schedule_binding(schedule,authoritative_schedule_binding) if authoritative_schedule_binding else bind(schedule)
    expected_week=int(parent['completed_week'])+1
    if binding['season']!=int(parent['season']) or binding['week']!=expected_week:raise ValueError('QB_WEEKLY_CHAIN_SCHEDULE_MISMATCH')
    if not schedule[['home_score','away_score']].notna().all().all():raise ValueError('QB_WEEK_NOT_COMPLETE')
    d,_=scope_pbp_to_schedule(pbp,schedule,reject_out_of_scope=True)
    d=d[(d.season_type=='REG')&(d.qb_dropback==1)&(d.qb_kneel!=1)&(d.qb_spike!=1)&d.epa.notna()&d.passer_player_id.notna()].drop_duplicates(['game_id','play_id'])
    rows=d.groupby(['game_id','passer_player_id']).epa.agg(epa_sum='sum',dropbacks='count').reset_index().to_dict('records')
    starters={}
    for row in schedule.to_dict('records'):
        for side in ('home','away'):
            q=row.get(side+'_qb_id')
            if not isinstance(q,str) or not q:raise ValueError('COMPLETED_STARTER_ID_REQUIRED')
            starters[canonical(row[side+'_team'])]=q
    ev={'season':binding['season'],'completed_week':binding['week'],'source_sha256':source_sha256,
        'completed_game_ids':binding['game_ids'],'completed_starters':starters,'aggregates':rows,
        'parent_qb_state_sha256':digest(parent),'authoritative_schedule_binding':binding,
        'rule':'FROZEN_DROPBACK_FILTER; OFFSEASON_RETENTION_ONLY_IN_SEASON_INITIALIZATION; GENERIC_WEEKLY_CHAIN'}
    state=apply_to_parent(parent,ev);ev['state_after_sha256']=digest(state)
    return ev,state

def build(artifact,pbp,schedule,source_sha256):
    """Compatibility builder for Week1. New weeks use build_from_parent."""
    ids=schedule.game_id.tolist()
    if len(ids)!=16 or set(schedule.season)!={2026} or set(schedule.week)!={1}:raise ValueError('QB_WEEK1_COMPLETE_SCHEDULE_REQUIRED')
    parent=offseason_prior(artifact,2026)
    ev,state=build_from_parent(parent,pbp,schedule,source_sha256)
    ev['parent_model_sha256']=digest(artifact)
    compat={'qb_ratings':state['qb_ratings'],'last_qb':state['last_qb']}
    ev['state_after_sha256']=digest(compat)
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
