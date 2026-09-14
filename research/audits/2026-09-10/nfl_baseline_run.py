import csv,json,hashlib,datetime
from pathlib import Path
import numpy as np
import nfl_engine as engine
P=Path(__file__).parent
rows=list(csv.DictReader(open(P/'nfl_2025.csv')));assert len(rows)==272 and all(r['season']=='2025' and r['game_type']=='REG' for r in rows)
teams=sorted({r['home_team'] for r in rows}|{r['away_team'] for r in rows});idx={t:i for i,t in enumerate(teams)};matrix=np.zeros((32,32));rhs=np.zeros(32);stats={t:dict(games=0,points_for=0,points_against=0) for t in teams}
for r in rows:
 for side,opp in [('home','away'),('away','home')]:
  t,o=r[side+'_team'],r[opp+'_team'];pf,pa=float(r[side+'_score']),float(r[opp+'_score']);i,j=idx[t],idx[o];matrix[i,i]+=1;matrix[i,j]-=1;rhs[i]+=pf-pa
  stats[t]['games']+=1;stats[t]['points_for']+=pf;stats[t]['points_against']+=pa
ratings=np.linalg.lstsq(np.vstack([matrix,np.ones((1,32))]),np.r_[rhs,0],rcond=None)[0]
for t in teams:stats[t]['srs']=float(ratings[idx[t]])
event=json.load(open(P/'sources/nfl_schedule.json'))['events'][0];comp=event['competitions'][0];home=stats['LA'];away=stats['SF']
config={'home_field_points':1.8,'points_per_elo':.036,'margin_sd':13.5,'total_sd':10.5,'margin_logistic_scale':8.,'league_total_prior':44.}
snapshot={'event_id':event['id'],'home_team':'Los Angeles Rams','away_team':'San Francisco 49ers','home_elo':1500+home['srs']/.036,'away_elo':1500+away['srs']/.036,'neutral_site':bool(comp['neutralSite']),'home_adjustment_points':0.,'away_adjustment_points':0.,'total_prior':.5*(home['points_for']/home['games']+away['points_against']/away['games'])+.5*(away['points_for']/away['games']+home['points_against']/home['games'])}
now=datetime.datetime.now(datetime.timezone.utc).isoformat();assert now<event['date'].replace('Z','+00:00')
out={'scope':'BASELINE_DIAGNOSTIC','generated_at_utc':now,'game_start_utc':event['date'],'venue':comp['venue']['fullName'],'model_source_commit':'fb2183dad9fa092850714a2a508d217b25bfcebd','rating_method':'2025_REG_SRS_ZERO_SUM_LEAST_SQUARES_NO_HOME_ADJUSTMENT','history_sha256':hashlib.sha256((P/'nfl_2025.csv').read_bytes()).hexdigest(),'source_history_path':'data/nfl/source/2026-09-03_nflverse_regular_games.csv','snapshot':snapshot,'config':config,'forecast':engine.run(snapshot,config,100000),'input_limits':['PRIOR_SEASON_ONLY','QB_LINEUP_INJURY_UNBOUND','TRAVEL_REST_WEATHER_UNBOUND','NO_VALIDATED_OFFSEASON_CARRYOVER'],'market_inputs_used':False,'action_authority':False,'promotion_eligible':False}
out['artifact_sha256']=hashlib.sha256(json.dumps(out,sort_keys=True,separators=(',',':')).encode()).hexdigest();(P/'nfl_forecast.json').write_text(json.dumps(out,indent=2)+'\n');(P/'nfl_srs_state.json').write_text(json.dumps(stats,indent=2)+'\n');print(json.dumps(out,indent=2))
