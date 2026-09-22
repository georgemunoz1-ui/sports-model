"""Explicit initial research baselines, separate from tested default selection."""
import datetime as dt
import hashlib
import os
from pathlib import Path
import numpy as np
from scipy.stats import skellam
from models.current import common
from models.current.linear import predict
from models.nfl.contextual.recovered_inference import digest,utc
IDS={l:f'{l}.initial_causal_score.research.v1' for l in ('nba','nhl','mls')}
FEATURES=['home_for','home_against','away_for','away_against','home_rest','away_rest','home_cold','away_cold','neutral']


def feature(state,event,prior):
    out=[]
    for side in ('home','away'):
        s=state.get(event[side+'_id'],{'n':0,'for':prior,'against':prior,'last':None})
        w=s['n']/(s['n']+10)
        out.extend([w*s['for']+(1-w)*prior,w*s['against']+(1-w)*prior])
    for side in ('home','away'):
        s=state.get(event[side+'_id'],{})
        out.append(min(14,max(0,(utc(event['start_time_utc'])-utc(s['last'])).total_seconds()/86400)) if s.get('last') else 14.)
    out.extend([float(state.get(event[s+'_id'],{}).get('n',0)<10) for s in ('home','away')]);out.append(float(event['neutral_site']))
    return dict(zip(FEATURES,out))


def update(state,event):
    for side,other in [('home','away'),('away','home')]:
        tid=event[side+'_id'];pf=event[side+'_score'];pa=event[other+'_score'];s=state.get(tid)
        if s is None:state[tid]={'n':1,'for':float(pf),'against':float(pa),'last':event['start_time_utc']}
        else:s.update(n=s['n']+1,**{'for':.9*s['for']+.1*pf,'against':.9*s['against']+.1*pa,'last':event['start_time_utc']})


def probabilities(fitted,x,league):
    if league!='mls':
        p=predict(fitted['winner'],x);return [1-p,p]
    h=predict(fitted['home_goals'],x);a=predict(fitted['away_goals'],x)
    return [float(skellam.cdf(-1,h,a)),float(skellam.pmf(0,h,a)),float(skellam.sf(0,h,a))]


def forecast(event,ctx,n):
    p=ctx['package'];league=p['league']
    if os.environ.get('SPORTS_INITIAL_BASELINES')!='1':raise ValueError('EXPLICIT_INITIAL_RESEARCH_OPT_IN_REQUIRED')
    if p['model_id']!=IDS[league]:raise ValueError('INITIAL_MODEL_IDENTITY')
    x=feature(p['team_state'],event,p['prior']);v=list(x.values());fit=p['fitted_model']
    if league!='mls':return common.emit(event,ctx,x,probabilities(fit,v,league)[1],predict(fit['margin'],v),predict(fit['total'],v),n,limitations=['INITIAL_RESEARCH_BASELINE_NOT_ACCURACY_DEFAULT'])
    common.current(p,ctx['cutoff'])
    if event not in p['events'] or utc(event['start_time_utc'])<=utc(ctx['cutoff']):raise ValueError('EVENT_NOT_CURRENT_PREGAME')
    if not 1<=n<=1000000:raise ValueError('DRAW_COUNT_RANGE')
    probs=probabilities(fit,v,league);h=predict(fit['home_goals'],v);a=predict(fit['away_goals'],v)
    identity=digest({'event':event,'features':x,'package':ctx['package_sha256'],'cutoff':ctx['cutoff'],'n':n});seed=int(identity[:16],16)
    rng=np.random.default_rng(seed);hd=rng.poisson(h,n);ad=rng.poisson(a,n);counts=np.array([(ad>hd).sum(),(ad==hd).sum(),(hd>ad).sum()])/n
    output=os.environ.get('SPORTS_RESEARCH_DRAW_OUTPUT')
    if not output:raise ValueError('SPORTS_RESEARCH_DRAW_OUTPUT_REQUIRED')
    out=Path(output)/event['event_id'].replace(':','_');out.mkdir(parents=True,exist_ok=False)
    np.save(out/'home_goals.npy',hd,allow_pickle=False);np.save(out/'away_goals.npy',ad,allow_pickle=False)
    common.save(out/'inputs.json',{'identity':identity,'features':x,'home_lambda':h,'away_lambda':a,'model_sha256':p['model_sha256']})
    common.save(out/'manifest.json',{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in out.iterdir()})
    idx=int(np.argmax(probs));winner=[event['away_team'],'Draw',event['home_team']][idx]
    return {'model_id':p['model_id'],'model_winner':winner,'model_p':probs[idx],'sim_p':float(counts[idx]),'analytic_p':probs[idx],'stochastic_sim_p':float(counts[idx]),'projected_home_points':h,'projected_away_points':a,'projected_total':h+a,'projected_margin':None,'forecast_tier':'BASELINE','dose':0.,'action_authority':False,'data_quality':p['data_grade'],'coverage_label':'REGULATION_1X2_INITIAL_RESEARCH','model_input_snapshot':x,'input_snapshot_hash':digest(x),'model_state_config_hash':p['model_sha256'],'warnings':p['limitations'],'diagnostics':{'outcome_order':['away','draw','home'],'analytic_probabilities':probs,'simulation_probabilities':counts.tolist(),'model_lineage':p['model_lineage']},'simulation':{'count':n,'seed':seed,'draw_directory':str(out),'joint_scores':'INDEPENDENT_POISSON_REGULATION'},'provenance':{'source_fetches':p['source_fetches']}}
