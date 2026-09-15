"""Source-bound final availability and explanatory role audit; no new weights."""
from .features import name_key
from .recovered_inference import utc,digest

def final_availability(personnel,event,cutoff):
    report=personnel.get('final_inactive_report')
    if report is None:
        if personnel.get('final_inactives') == 'VERIFIED':
            raise ValueError('FINAL_INACTIVE_EVIDENCE_REQUIRED')
        return {'status':'PENDING','players':[],'numeric_scope':'NOT_CAPTURED'}
    if report.get('event_id')!=event['event_id']:raise ValueError('INACTIVE_EVENT_MISMATCH')
    if set(report.get('teams',{}))!={event['home_team'],event['away_team']}:raise ValueError('INACTIVE_TEAM_COVERAGE')
    if utc(report['retrieved_at_utc'])>utc(cutoff):raise ValueError('INACTIVES_AFTER_CUTOFF')
    if report.get('rows_sha256')!=digest(report['teams']):raise ValueError('INACTIVE_HASH_MISMATCH')
    rows=[]
    for team,entry in report['teams'].items():
        if not entry.get('source') or not entry.get('complete'):raise ValueError('INACTIVE_SOURCE_OR_COMPLETENESS')
        names=set()
        for player in entry['players']:
            key=name_key(player['player'])
            if key in names:raise ValueError('DUPLICATE_INACTIVE')
            names.add(key);rows.append({'team':team,**player})
        q=personnel.get('quarterbacks',{}).get(team,{})
        if name_key(q.get('name','')) in names:raise ValueError('EXPECTED_QB_INACTIVE:'+team)
    # Healthy scratches and emergency QBs are distinct from injury-report OUT.
    return {'status':'VERIFIED','players':rows,'source_hash':report['rows_sha256'],
            'numeric_scope':'EXISTING_INJURY_OUT_FEATURES_ONLY; HEALTHY_SCRATCH_AND_EMERGENCY_QB_TRANSFORMS_UNFITTED'}

def explain_roles(audit,roles,gameday,evidence):
    import datetime as dt
    result=[]
    for row in audit:
        row=dict(row);key=row['team']+'|'+name_key(row['player'])
        if row['prior_snap_share'] is not None:
            row['resolution_reason']='EXISTING_ELIGIBLE_SAME_TEAM_HISTORY'
        else:
            same=roles.get(key,[])
            other={k:v for k,v in roles.items() if k.split('|')[-1]==name_key(row['player']) and k!=key}
            if same:
                age=(dt.date.fromisoformat(gameday)-dt.date.fromisoformat(same[-1]['date'])).days
                row['latest_history_age_days']=age
                row['resolution_reason']='STALE_SAME_TEAM_HISTORY' if age>365 else 'AMBIGUOUS_OR_INELIGIBLE_HISTORY'
            elif other:
                row['resolution_reason']='PRIOR_TEAM_HISTORY_NOT_CURRENT_TEAM_ROLE'
                row['other_team_history']=other
            else:row['resolution_reason']='NO_HISTORY_IN_FITTED_REGULAR_SEASON_STATE'
            if key in evidence:row['source_bound_disposition']=evidence[key]
        result.append(row)
    return result
