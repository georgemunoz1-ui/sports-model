"""Current selected CFB incumbent with exact recovered EWMA/Elo feature semantics."""
import math
from models.current import common
from models.current.linear import predict
from pipelines.cards.selection import require_default

def feature_row(state,event,params):
    from models.nfl.contextual.recovered_inference import utc
    h,a=event['home_team'],event['away_team'];season=event['season'];kick=utc(event['start_time_utc'])
    def elo(t):
        value=state['elo'].get(t,1500.)
        return 1500+(value-1500)*params['regress'] if t in state['last_season'] and state['last_season'][t]!=season else value
    def rest(t):return (kick-utc(state['last'][t])).days if t in state['last'] else None
    rh,ra=rest(h),rest(a)
    return {'elo_diff_with_home_advantage':elo(h)+(0 if event['neutral_site'] else params['hfa'])-elo(a),
        'home_ewma_points_for':state['ewpf'].get(h),'home_ewma_points_against':state['ewpa'].get(h),
        'away_ewma_points_for':state['ewpf'].get(a),'away_ewma_points_against':state['ewpa'].get(a),
        'home_ewma_margin':state['ewm'].get(h),'away_ewma_margin':state['ewm'].get(a),
        'rest_days_diff':rh-ra if rh is not None and ra is not None else None,
        'neutral_site':float(event['neutral_site']),'conference_game':float(event['conference_game'])}

def forecast(event,ctx,n):
    p=ctx['package'];require_default('cfb',p['model_id'],week=event['week'],division=event['division_scope'])
    x=feature_row(p['team_state'],event,p['parameters']);values=[x[k] for k in p['feature_names']]
    return common.emit(event,ctx,x,predict(p['fitted_model']['winner'],values),predict(p['fitted_model']['margin'],values),None,n,
        limitations=['TOTAL_HEAD_NOT_FITTED_FOR_SELECTED_CFB_ARM','CURRENT_FCS_INTERNAL_SCHEDULE_COVERAGE_UNVERIFIED'])
