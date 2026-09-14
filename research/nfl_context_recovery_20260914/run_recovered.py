"""Reproducible restored EPA inference + separately labeled simulation bridges."""
import datetime as dt
import hashlib
import json
import math
import sys
from pathlib import Path
import numpy as np
from scipy.optimize import root
from scipy.special import ndtr
from numpy.polynomial.hermite import hermgauss
from recovered_pipeline import ROOT,predict,bind_context,bernoulli_simulation,digest

sys.path.insert(0,str(ROOT/'recovered_drive'))
from sportsim.sports.nfl import NFLSimulator,NFLConfig
from sportsim.core.types import TeamRating

def drive_bridge(margin,total,identity,n=100000):
    """Restore the legacy drive engine as a *separate* experimental distribution.

    The two attack multipliers numerically match regulation scoring expectations
    to EPA score centers. This bridge does not claim the inherited overtime rule
    is exact or that the final-score distribution is calibrated.
    """
    config=NFLConfig();sim=NFLSimulator(config)
    nodes,weights=hermgauss(32);env=np.maximum(1+math.sqrt(2)*config.env_sd*nodes,.3);weights=weights/math.sqrt(math.pi)
    # Exact expected count for the rounded normal base drives (tail beyond 30 negligible).
    mean_base=6*ndtr((6.5-config.drives_per_team)/config.drives_sd)
    mean_base+=sum(k*(ndtr((k+.5-config.drives_per_team)/config.drives_sd)-ndtr((k-.5-config.drives_per_team)/config.drives_sd)) for k in range(7,31))
    count=mean_base+.5
    td_points=6+2*config.two_point_attempt_rate*config.two_point_success+(1-config.two_point_attempt_rate)*config.xp_success
    def expected(logstrength):
        strength=np.exp(logstrength)
        h=sim._drive_probs(strength[0]*env);a=sim._drive_probs(strength[1]*env)
        def off(v):return np.dot(weights,v[0]*td_points+v[1]*3)
        def defense(v):return np.dot(weights,v[2]*(6+config.xp_success)+v[3]*2)
        return count*np.array([off(h)+defense(a),off(a)+defense(h)])
    target=np.array([(total+margin)/2,(total-margin)/2])
    if (target<=0).any():raise ValueError('NONPOSITIVE_SCORE_CENTER')
    solution=root(lambda x:expected(x)-target,[0.,0.])
    if not solution.success or np.max(np.abs(expected(solution.x)-target))>1e-8:raise ValueError('DRIVE_MEAN_MATCH_FAILURE')
    strengths=np.exp(solution.x)
    # HFA is already in fitted means. Set rating inputs to cancel the engine's
    # own HFA multiplier, so it is never applied twice.
    home=TeamRating(team='KC',attack=float(strengths[0]/math.sqrt(config.home_factor)))
    away=TeamRating(team='DEN',attack=float(strengths[1]*math.sqrt(config.home_factor)))
    seed=int(digest({'identity':identity,'kind':'RECOVERED_DRIVE_BRIDGE','n':n})[:16],16)
    samples=sim.simulate(home,away,n=n,rng=seed)
    arr=np.column_stack([samples.home,samples.away,samples.ot]).astype('<i2')
    h=float((samples.margin>0).mean());a=float((samples.margin<0).mean());tie=float((samples.margin==0).mean())
    return arr,{'seed':seed,'count':n,'home_win':h,'away_win':a,'tie':tie,'home_win_conditional_no_tie':h/(h+a),'mean_home_points':float(samples.home.mean()),'mean_away_points':float(samples.away.mean()),'mean_margin':float(samples.margin.mean()),'mean_total':float(samples.total.mean()),'regulation_score_targets':target.tolist(),'expected_regulation_scores':expected(solution.x).tolist(),'rating_attack_inputs':[home.attack,away.attack],'sha256':hashlib.sha256(arr.tobytes()).hexdigest(),'identity':'nfl.recovered_drive_mean_bridge.v1.research','inherited_source_commit':'19391558f866ae580defd7940794ce5914c04d91','parameters_fitted_to_history':False,'overtime':'INHERITED_TWO_DRIVES_PER_TEAM_APPROXIMATION_NOT_RULE_EXACT','full_game_settlement_validated':False,'margin_quantiles':np.quantile(samples.margin,[.1,.25,.5,.75,.9]).tolist(),'total_quantiles':np.quantile(samples.total,[.1,.25,.5,.75,.9]).tolist()}

def main():
    params=json.loads((ROOT/'fitted_parameters.json').read_text());row=json.loads((ROOT/'frozen_feature_row.json').read_text())[0]
    context=json.loads((ROOT/'current_context.json').read_text());spec=json.loads((ROOT/'spec.json').read_text())
    cutoff=dt.datetime.now(dt.timezone.utc).isoformat()
    result=bind_context(params,row,context,cutoff,spec['start_utc'])
    identity=digest({'parameter_sha256':hashlib.sha256((ROOT/'fitted_parameters.json').read_bytes()).hexdigest(),'features':result['features'],'context':context,'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    p=result['current']['prediction'];binary,binary_info=bernoulli_simulation(p['home_win'],identity)
    arr,info=drive_bridge(p['home_margin'],p['total_points'],identity)
    replay,replay_info=drive_bridge(p['home_margin'],p['total_points'],identity)
    assert np.array_equal(arr,replay) and info==replay_info
    assert np.array_equal(binary,bernoulli_simulation(p['home_win'],identity)[0])
    out=ROOT/'results_final';out.mkdir(exist_ok=False)
    np.save(out/'winner_draws.npy',binary,allow_pickle=False);np.save(out/'drive_scores.npy',arr,allow_pickle=False)
    bundle={'event_id':row['game_id'],'cutoff_utc':cutoff,'start_utc':spec['start_utc'],'source_model_id':params['model_id'],'model_artifact_sha256':params['artifact_sha256'],'source_training_seasons':params['training_seasons'],'identity':identity,**result,'winner_simulation':binary_info,'drive_simulation':info,'new_fit':False,'new_simulation_bridge':True,'canonical_prospective_eligible':False,'market_input':False,'personnel_numerically_applied':False,'travel_numerically_applied':False,'weather_numerically_applied':True,'rest_feature_applied':True,'replay_exact':True}
    (out/'bundle.json').write_text(json.dumps(bundle,indent=2,allow_nan=False))
    (out/'registration.jsonl').write_text(json.dumps({'created_at_utc':cutoff,'type':'LOCAL_RESEARCH_RUN','bundle_sha256':hashlib.sha256((out/'bundle.json').read_bytes()).hexdigest(),'spec_sha256':hashlib.sha256((ROOT/'spec.json').read_bytes()).hexdigest(),'canonical_prospective_eligible':False})+'\n')
    print(json.dumps({'prediction':p,'winner_simulation':binary_info,'drive_simulation':info,'changes':result['context_contribution_changes']},indent=2))

if __name__=='__main__':main()
