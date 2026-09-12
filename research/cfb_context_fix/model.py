"""Team-conditioned research heads; availability gates are separate from numeric effects."""
import hashlib
import numpy as np
MODEL_ID='cfb.team_context_heads.v0_1.research'
def roster_state(raw):
 players=[p for g in raw.get('athletes',[]) for p in g.get('items',[])]
 return {'season':raw.get('season',{}).get('year'),'players':len(players),'quarterbacks':[{'id':p['id'],'name':p['displayName'],'roster_status':p.get('status',{}).get('name'),'injuries':p.get('injuries',[])} for p in players if p.get('position',{}).get('abbreviation')=='QB'],'starting_qb':'UNCONFIRMED','game_day_availability':'UNRESOLVED','roster_is_not_availability':True}
def fit(rows):
 if len(rows)<30:raise ValueError('INSUFFICIENT_HISTORY')
 x=np.array([[1,(r['home_elo_before']-r['away_elo_before'])/400] for r in rows]); y=np.array([r['home_score']-r['away_score'] for r in rows]);coef=np.linalg.lstsq(x,y,rcond=None)[0];sigma=float(np.sqrt(np.sum((y-x@coef)**2)/(len(y)-2)))
 ids=sorted({r[k] for r in rows for k in ('home_id','away_id')});idx={v:i for i,v in enumerate(ids)};n=len(ids)
 # Separate attack/concession effects on ACTUAL halftime team points, shrunk toward league mean.
 X=[];Y=[]
 for r in rows:
  for side,opp in [('home','away'),('away','home')]:
   z=np.zeros(1+2*n);z[0]=1;z[1+idx[r[side+'_id']]]=1;z[1+n+idx[r[opp+'_id']]]=1;X.append(z);Y.append(r[side+'_half'])
 X=np.array(X);Y=np.array(Y);penalty=np.eye(1+2*n)*5;penalty[0,0]=0;b=np.linalg.solve(X.T@X+penalty,X.T@Y)
 errors=np.array(Y-X@b).reshape(-1,2).sum(axis=1);total_sigma=float(np.std(errors,ddof=1))
 return {'margin_coef':coef.tolist(),'margin_sigma':sigma,'team_ids':ids,'half_coef':b.tolist(),'half_total_sigma':total_sigma,'n':len(rows),'ridge_penalty':5,'uncertainty_status':'IN_SAMPLE_RESIDUAL_SCALE_NOT_CALIBRATED'}
def predict(model,hid,aid,he,ae,event,ih,n=100000):
 ids=model['team_ids'];k=len(ids);b=np.array(model['half_coef'])
 def score(team,opp):return float(b[0]+(b[1+ids.index(team)] if team in ids else 0)+(b[1+k+ids.index(opp)] if opp in ids else 0))
 hm=score(hid,aid);am=score(aid,hid)
 if min(hm,am)<0:raise ValueError('NEGATIVE_SCORE_ESTIMATE')
 margin=float(np.array(model['margin_coef'])@np.array([1,(he-ae)/400]));total=hm+am
 seed=int.from_bytes(hashlib.sha256(f'{MODEL_ID}:{event}:{ih}:{n}'.encode()).digest()[:8],'big');rng=np.random.default_rng(seed)
 # Explicit continuity-corrected normal approximation, NOT a drive/football-score simulator.
 md=np.rint(rng.normal(margin,model['margin_sigma'],n)).astype('<i2');td=np.maximum(0,np.rint(rng.normal(total,model['half_total_sigma'],n))).astype('<i2')
 return {'full_game_home_margin':margin,'first_half_home_points':hm,'first_half_away_points':am,'first_half_total':total,'seed':seed,'n_sims':n,'margin_sigma':model['margin_sigma'],'half_total_sigma':model['half_total_sigma'],'margin_draws_sha256':hashlib.sha256(md.tobytes()).hexdigest(),'half_total_draws_sha256':hashlib.sha256(td.tobytes()).hexdigest(),'home_half_effect_vs_prior':hm-float(b[0]),'away_half_effect_vs_prior':am-float(b[0]),'team_history_present':{'home':hid in ids,'away':aid in ids}},md,td
