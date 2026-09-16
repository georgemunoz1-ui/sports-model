"""Prospective Week 2 policy. No model promotion and no retrospective relabeling."""
from pathlib import Path
import hashlib,json,math
import pandas as pd
from . import base_features as bf
from .assimilation import serialize_states
from .recovered_inference import digest,utc

ROOT=Path(__file__).resolve().parents[3]
POLICY=ROOT/'data/nfl/contextual_v1/week2_policy.json'
STATE_FEATURES=tuple(bf.MODEL_FEATURES[:7]+['state_experience_min_log','state_experience_diff_log'])

def policy():
    p=json.loads(POLICY.read_text())
    evidence=ROOT/p['screen_evidence_path']
    if hashlib.sha256(evidence.read_bytes()).hexdigest()!=p['screen_evidence_sha256']:
        raise ValueError('HEADLINE_SCREEN_EVIDENCE_CHANGED_REVIEW_REQUIRED')
    metrics=json.loads(evidence.read_text())['metrics']
    best=min(metrics,key=lambda a:(metrics[a]['all']['brier'],metrics[a]['all']['log_loss'],-metrics[a]['all']['winner_accuracy']))
    if p['default_reference_model']!=f'nfl.integrated_context.{best}.v1.research':
        raise ValueError('DEFAULT_DOES_NOT_MATCH_DECLARED_SELECTION_RULE')
    from pipelines.cards.selection import require_default
    require_default("nfl",p["default_reference_model"])
    return p

def applies(base,event):
    # Bind week to the canonical event ID; a mislabeled base cannot bypass gates.
    season,week=map(int,event['event_id'].split('_')[:2])
    if (int(base['season']),int(base['week']))!=(season,week):
        raise ValueError('EVENT_SEASON_WEEK_BINDING')
    return (season,week)>=(2026,2)

def selection(model_id,*,headline=False):
    p=policy();status=p['models'].get(model_id,'UNSCREENED')
    if headline and status not in {'PASSED','SELECTED_DEFAULT'}:raise ValueError('HEADLINE_NOT_ELIGIBLE:'+status+':'+model_id)
    return {'policy_id':p['policy_id'],'policy_sha256':digest(p),'screen_status':status,
            'presentation_role':'DEFAULT_RESEARCH_MODEL' if status=='SELECTED_DEFAULT' else 'REFERENCE_ONLY' if status=='REFERENCE' else 'EXPERIMENTAL_ONLY',
            'headline_eligible':status in {'PASSED','SELECTED_DEFAULT'},'official_eligible':False,'action_authority':False}

def require_assimilation(base,context,event,cutoff):
    """Recompute state-derived features, rather than accepting an 'assimilated' flag.

    Source audit remains research evidence. This does not authenticate an external
    registration or replace independent official gamebook reconciliation.
    """
    ev=context.get('assimilation')
    if not ev:raise ValueError('WEEK2_ASSIMILATION_EVIDENCE_REQUIRED')
    report=ev['audit'];before=ev['state_before'];after=ev['state_after']
    if report['status']!='reconciled' or report['state_update_applied'] is not True:
        raise ValueError('WEEK2_STATE_NOT_UPDATED')
    if utc(report['cutoff_utc'])>utc(cutoff):raise ValueError('ASSIMILATION_AFTER_CUTOFF')
    snapshot=report['snapshot']
    if utc(snapshot['retrieved_at_utc'])>utc(cutoff) or not snapshot.get('sha256') or not snapshot.get('source_url'):
        raise ValueError('ASSIMILATION_SOURCE_INVALID')
    for state,key in [(before,'state_before_sha256'),(after,'state_after_sha256')]:
        if digest(state)!=report[key]:raise ValueError('ASSIMILATION_STATE_HASH_MISMATCH')
    if digest(before)==digest(after):raise ValueError('ASSIMILATION_STATE_UNCHANGED')
    cov=report['coverage'];rows=cov['rows']
    if not cov['weekly_state_update_eligible'] or not rows or any(not x['state_update_eligible'] for x in rows):
        raise ValueError('ASSIMILATION_WEEK_INCOMPLETE')
    previous=(int(base['season']),int(base['week'])-1)
    ids=[x['game_id'] for x in rows]
    if len(ids)!=len(set(ids)) or any(tuple(map(int,g.split('_')[:2]))!=previous for g in ids):
        raise ValueError('ASSIMILATION_WRONG_WEEK')
    if previous==(2026,1) and len(ids)!=16:raise ValueError('WEEK1_REQUIRES_16_FINALS')
    if ev.get('base_feature_code_sha256')!=hashlib.sha256(Path(bf.__file__).read_bytes()).hexdigest():
        raise ValueError('ASSIMILATION_TRANSFORM_MISMATCH')
    game=pd.Series({'home_score':None,'away_score':None,'roof':None,'temp':None,'wind':None,'home_rest':None,'away_rest':None,**base,'gameday':event['gameday'],'gametime':event['gametime'],'location':event.get('location','Home')})
    def features(states):return bf._feature_row(game,bf.TeamState(**states[event['home_team']]),bf.TeamState(**states[event['away_team']]))
    old,new=features(before),features(after)
    for key in STATE_FEATURES:
        if not math.isclose(float(base[key]),float(new[key]),rel_tol=1e-8,abs_tol=1e-8):
            raise ValueError('ASSIMILATION_NOT_ACTIVE_IN_RUN:'+key)
    return {'status':'VERIFIED_RESEARCH_STATE_FLOW','source_sha256':snapshot['sha256'],
            'state_before_sha256':digest(before),'state_after_sha256':digest(after),
            'feature_changes':{k:{'before':float(old[k]),'after':float(new[k])} for k in STATE_FEATURES if old[k]!=new[k]},
            'official_gamebook_clearance':False}

def coherence(prediction,joint=None):
    sign=lambda v:1 if v>0 else -1 if v<0 else 0
    signs={'binary_head':sign(prediction['home_win']-.5),'ridge_margin_head':sign(prediction['home_margin'])}
    if joint:signs['joint_mean_margin']=sign(joint['mean_margin'])
    return {'home_oriented_signs':signs,'cross_head_direction_disagreement':len(set(signs.values()))>1,
            'separate_heads_are_not_joint_expectations':True,
            'same_distribution_mean_and_majority_sign_need_not_match':True,
            'calibration_established':False}
