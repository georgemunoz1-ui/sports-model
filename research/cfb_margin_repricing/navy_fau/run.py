import json,sys,hashlib
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reprice_push_v2 import reprice_with_push
from reprice import margin_quantiles,reprice_cfb_total
p=Path(sys.argv[1]);raw=p.read_bytes();b=json.loads(raw);r=next(x for x in b['rows'] if x['event_id']=='401862703');m=r['model'];rng=np.random.default_rng(m['seed']);draws=np.rint(rng.normal(m['full_game_home_margin'],m['margin_sigma'],m['n_sims'])).astype('<i2')
assert hashlib.sha256(draws.tobytes()).hexdigest()==m['margin_draws_sha256']
u,c=np.unique(draws,return_counts=True);assert {str(int(k)):int(v) for k,v in zip(u,c)}==r['full_margin_histogram']
half=np.maximum(0,np.rint(rng.normal(m['first_half_total'],m['half_total_sigma'],m['n_sims']))).astype('<i2');assert hashlib.sha256(half.tobytes()).hexdigest()==m['half_total_draws_sha256']
out=dict(record_type='FROZEN_FORECAST_REPRICING_NOT_NEW_FORECAST',generated_at=datetime.now(timezone.utc).isoformat(),event_id=r['event_id'],home=r['home'],away=r['away'],start=r['start'],forecast_cutoff=b['cutoff'],rating_vintage=r['model_rating_vintage'],model_id=b['model_id'],parent_sha256=hashlib.sha256(raw).hexdigest(),seed=m['seed'],draws_sha256=m['margin_draws_sha256'],model_navy_margin=-m['full_game_home_margin'],simulation_navy_margin=-float(draws.mean()),navy_margin_quantiles={f'p{k}':int(np.quantile(-draws,k/100,method='inverted_cdf')) for k in [10,25,50,75,90]},spread=reprice_with_push(r,4,research_only=True),screenshot_prices={'navy_minus4':-112,'fau_plus4':-108,'navy_moneyline':-198,'fau_moneyline':164,'total':59.5,'quote_timestamp':None},full_game_total=reprice_cfb_total(59.5),first_half={'fau_points':m['first_half_home_points'],'navy_points':m['first_half_away_points'],'model_total':m['first_half_total'],'simulation_total':float(half.mean()),'quantiles':{f'p{k}':int(np.quantile(half,k/100,method='inverted_cdf')) for k in [10,25,50,75,90]},'team_history_present':m['team_history_present'],'not_full_game_total':True},current_inputs=r['current_context'],validation={'tests_passed':17,'exact_seeded_margin_replay':True,'exact_seeded_half_replay':True,'parent_unchanged':True},action_authority='OFF',canonical_prospective_eligible=False)
assert p.read_bytes()==raw
with open(sys.argv[2],'x') as f:json.dump(out,f,indent=2,allow_nan=False)
print(json.dumps({k:v for k,v in out.items() if k!='current_inputs'},indent=2))
