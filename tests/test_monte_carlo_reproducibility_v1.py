import json
from models.cfb.monte_carlo_v1 import run as cfb_run
from models.mlb.monte_carlo_v1 import run as mlb_run

def scrub(x):
 x=json.loads(json.dumps(x));x.pop('generated_at_utc',None);return x

def test_cfb_same_inputs_same_seed_same_output():
 state={"model_id":"cfb.margin_distribution.v1","version":"1","code_commit":"abc","parameters":{"intercept":6.4,"elo_diff_coefficient":.068,"neutral_site_coefficient":1.8,"conference_game_coefficient":-7.7},"residual_model":{"global_sigma":18.1,"segment_sigma_by_week":{"1":20.2}}}
 snap={"event_id":"E1","game_start_utc":"2026-09-05T00:00:00Z","home_team":"H","away_team":"A","home_division":"fbs","away_division":"fbs","week":1,"neutral_site":False,"conference_game":False,"home_elo_pre":1600.,"away_elo_pre":1500.,"elo_diff_with_home_advantage":100.,"rating_source_home":"test","rating_source_away":"test","population":"FBS_VS_FBS"}
 a=cfb_run(snap,state,50000);b=cfb_run(snap,state,50000)
 assert a['simulation']['random_seed']==b['simulation']['random_seed']
 assert a['output_hash']==b['output_hash']
 assert scrub(a)==scrub(b)

def test_mlb_same_inputs_same_seed_same_output():
 snap={"event_id":"M1","away_sp":{"era":4.0,"gs":20,"k":23,"bb":8},"home_sp":{"era":3.5,"gs":20,"k":25,"bb":7},"away_rf_pg":4.4,"away_ra_pg":4.5,"home_rf_pg":4.7,"home_ra_pg":4.1,"park_factor":1.0}
 cfg={"version":"1.0.0","market_features_used":False}
 a=mlb_run(snap,cfg,50000);b=mlb_run(snap,cfg,50000)
 assert a['random_seed']==b['random_seed']
 assert a['output_hash']==b['output_hash']
 assert scrub(a)==scrub(b)
