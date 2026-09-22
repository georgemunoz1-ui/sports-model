"""Frozen V13 on complete official current-season form and pitcher game logs."""
import hashlib,os,sys
from pathlib import Path
import numpy as np
from models.current import common
from models.nfl.contextual.recovered_inference import digest,utc


def forecast(event,ctx,n):
    from pipelines.cards.adapters.mlb import capture_sim
    sys.path.insert(0,str(common.ROOT/'harness'))
    import run_v13_historical as V
    p=ctx['package'];common.current(p,ctx['cutoff'])
    if event not in p['events'] or utc(event['start_time_utc'])<=utc(ctx['cutoff']):raise ValueError('EVENT_NOT_CURRENT_PREGAME')
    if not 1<=n<=1000000:raise ValueError('DRAW_COUNT_RANGE')
    a=p['team_state'][event['away_team']];h=p['team_state'][event['home_team']]
    sa=p['starter_state'][str(event['away_pitcher_id'])];sh=p['starter_state'][str(event['home_pitcher_id'])];pf=event['park_factor']
    limitations=list(p['limitations'])
    for side,s in [('away',sa),('home',sh)]:
        if s.get('treatment'):limitations.append(side.upper()+':'+s['treatment'])
    inputs={'sp_away':sa,'sp_home':sh,'away_form':a,'home_form':h,'park_factor':pf,'event_id':event['event_id'],'package_sha256':ctx['package_sha256'],'cutoff':ctx['cutoff'],'model_id':p['model_id'],'n':n}
    identity=digest(inputs);seed=int(identity[:16],16)
    sim,draws=capture_sim(V,sa,sh,a['rf'],a['ra'],h['rf'],h['ra'],pf,seed,n)
    challenger=V.candidate_p(a['rf'],a['ra'],h['rf'],h['ra'],sa['era'],sa['gs'],sh['era'],sh['gs'],V.load_candidate_beta())
    output=os.environ.get('SPORTS_RESEARCH_DRAW_OUTPUT') or os.environ.get('MLB_DRAW_OUTPUT')
    if not output:raise ValueError('DRAW_OUTPUT_REQUIRED')
    out=Path(output)/event['event_id'].replace(':','_');out.mkdir(parents=True,exist_ok=False)
    for name,data in draws.items():np.save(out/(name+'.npy'),data,allow_pickle=False)
    common.save(out/'inputs.json',inputs);common.save(out/'manifest.json',{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in out.iterdir()})
    home=sim['p_home']>=.5;prob=sim['p_home'] if home else 1-sim['p_home']
    p=dict(p,limitations=limitations)
    return {'model_id':p['model_id'],'model_winner':event['home_team'] if home else event['away_team'],'model_p':prob,'sim_p':prob,'analytic_p':None,'stochastic_sim_p':prob,'probability_estimator':'MONTE_CARLO_ONLY','forecast_tier':'REDUCED','data_quality':p['data_grade'],'dose':0.,'projected_home_runs':sim['proj_home'],'projected_away_runs':sim['proj_away'],'projected_total':None,'warnings':p['limitations'],'input_snapshot_hash':identity,'model_state_config_hash':p['model_sha256'],'model_input_snapshot':inputs,'diagnostics':{'simulation_model_id':'mlb.winner.CHAMPION_V13','sim_home_win':sim['p_home'],'analytic_home_win':challenger,'starter_status':'OFFICIAL_PROBABLE_NOT_CONFIRMED','model_lineage':p['model_lineage']},'simulation':{'count':n,'seed':seed,'draw_directory':str(out),'home_win_probability':sim['p_home'],'mc_standard_error':sim['mc_se']},'coverage_label':'OFFICIAL_CURRENT_INPUTS_FROZEN_V13_WINNER_RESEARCH','provenance':{'source_fetches':p['source_fetches']},'action_authority':False}
