#!/usr/bin/env python3
"""Persist computational replays without labeling them new pregame forecasts."""
import argparse,datetime as dt,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np,pandas as pd
from models.nfl.contextual.model import load_artifact,simulate_joint
from models.nfl.contextual.recovered_inference import digest,bernoulli_simulation
from models.nfl.modes.core import ensemble,state_features,predict_live,categorical_simulation

def main():
 p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--fit',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(exist_ok=False,parents=True);market=load_artifact(a.data/'market_model.json');live=load_artifact(a.data/'live_model.json');r=pd.read_csv(a.fit/'market_evaluation_rows.csv').iloc[-1]
 fp={k:float(r[v]) for k,v in [('home_win','p_home'),('home_margin','pred_margin'),('total_points','pred_total')]};mp={k:float(r[v]) for k,v in [('home_win','market_p_home'),('home_margin','spread_line'),('total_points','total_line')]};pred=ensemble(market,fp,mp);identity=digest({'artifact':market,'event':r.game_id,'football':fp,'market':mp,'type':'HISTORICAL_REPLAY'})
 w,wi=bernoulli_simulation(pred['home_win'],identity,100000);ww,wwi=bernoulli_simulation(pred['home_win'],identity,100000);s,si=simulate_joint(pred['home_margin'],pred['total_points'],pred['home_win'],market['final_score_residuals'],market['tie_rate'],identity,100000);ss,ssi=simulate_joint(pred['home_margin'],pred['total_points'],pred['home_win'],market['final_score_residuals'],market['tie_rate'],identity,100000);assert np.array_equal(w,ww) and wi==wwi and np.array_equal(s,ss) and si==ssi
 fixture=json.loads((a.fit/'live_fixture.json').read_text());prob=predict_live(live['model'],state_features(fixture['state'],fixture['pregame_home_probability']))[0];li=digest({'artifact':live,'fixture':fixture,'type':'COMPUTATIONAL_REPLAY_NOT_HELDOUT_FORECAST'});ld,ls=categorical_simulation(prob,li,100000);ld2,ls2=categorical_simulation(prob,li,100000);assert np.array_equal(ld,ld2) and ls==ls2
 for name,arr in [('market_binary',w),('market_scores',s),('live_winner',ld)]:np.save(a.output/(name+'.npy'),arr,allow_pickle=False)
 result={'created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'record_type':'TECHNICAL_REPLAY_NOT_CURRENT_GAME_FORECAST','market':{'event_id':r.game_id,'prediction':pred,'binary_simulation':wi,'score_simulation':si,'replays_match':True,'artifact_sha256':digest(market)},'live':{'fixture':fixture,'analytic_three_way':dict(zip(['AWAY_WIN','HOME_WIN','TIE'],map(float,prob))),'simulation':ls,'replays_match':True,'artifact_sha256':digest(live),'accuracy_claim':False,'reason':'Deployment model includes fixture season; computational test only'}}
 (a.output/'verification.json').write_text(json.dumps(result,indent=2));(a.output/'manifest.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in a.output.iterdir() if p.is_file()},indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main()
