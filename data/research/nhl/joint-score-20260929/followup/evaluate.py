"""Additive, post-screen diagnostic evaluation. Never refits or rewrites forecasts."""
import json,hashlib,datetime,collections,sys
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
P=Path(__file__).resolve().parent; B=P.parent/'nhl-joint-20260929-v1';sys.path.insert(0,str(P.parent/'sports-model'))
from scripts.run_nhl_joint_score_research import batch_weights
D=json.loads((B/'audit-predictions.json').read_text());M=json.loads((B/'evaluation-model.json').read_text());R={r['event']['event_id']:r for r in json.loads((B/'causal-rows.json').read_text())};z=np.array([r['outcome']for r in D]);margin=z[:,2]-z[:,3];q=np.array([r['probabilities']for r in D]); y=(margin>=2).astype(float);p=q[:,3];pool=np.array(M['outcomes']);b=float(np.mean(pool[:,2]-pool[:,3]>=2));w=batch_weights(M,[R[r['event_id']]['features']for r in D]);total=w@(pool[:,2]+pool[:,3]);fav=np.maximum(q[:,4],1-q[:,4])
def ll(p,y):
 p=np.clip(p,1e-12,1-1e-12);return -(y*np.log(p)+(1-y)*np.log1p(-p))
def metrics(mask,prob=p,target=y,baseline=b):
 if not np.any(mask):return {'n':0}
 a=prob[mask];o=target[mask];return {'n':int(mask.sum()),'mean_p':float(a.mean()),'observed':float(o.mean()),'brier':float(np.mean((a-o)**2)),'baseline_brier':float(np.mean((baseline-o)**2)),'delta_brier':float(np.mean((a-o)**2-(baseline-o)**2)),'log_loss':float(ll(a,o).mean()),'baseline_log_loss':float(ll(baseline,o).mean()),'delta_log_loss':float((ll(a,o)-ll(baseline,o)).mean())}
def bootstrap(delta,key='week',n=10000):
 groups=collections.defaultdict(list)
 for i,r in enumerate(D):
  d=datetime.datetime.fromisoformat(r['start']);groups[d.strftime('%G-%V')if key=='week'else d.strftime('%Y-%m')].append(i)
 blocks=list(groups.values());rng=np.random.default_rng(20260929);vals=[]
 for _ in range(n):
  ix=np.concatenate([blocks[i]for i in rng.integers(len(blocks),size=len(blocks))]);vals.append(float(delta[ix].mean()))
 return {'delta_convention':'challenger minus unconditional baseline; negative is better','mean_delta':float(delta.mean()),'ci95_percentile':np.quantile(vals,[.025,.975]).tolist(),'blocks':len(blocks),'resamples':n,'seed':20260929,'unit':key}
def reliability(prob,target):
 out=[]
 for i in range(10):
  lo=i/10;hi=(i+1)/10;mask=(prob>=lo)&((prob<hi)if i<9 else(prob<=hi));n=int(mask.sum())
  if not n:out.append({'low':lo,'high':hi,'n':0});continue
  a=float(prob[mask].mean());o=float(target[mask].mean());den=1+1.96**2/n;mid=(o+1.96**2/(2*n))/den;half=1.96*np.sqrt(o*(1-o)/n+1.96**2/(4*n*n))/den
  out.append({'low':lo,'high':hi,'n':n,'mean_p':a,'observed':o,'gap':a-o,'observed_wilson95_descriptive':[mid-half,mid+half]})
 return out
slices={name:metrics(mask)for name,mask in [('REG',z[:,4]==0),('OT',z[:,4]==1),('SO',z[:,4]==2),('one_goal',abs(margin)==1),('two_plus',abs(margin)>=2),('model_favorite_50_60',(fav>=.5)&(fav<.6)),('model_favorite_60_70',(fav>=.6)&(fav<.7)),('model_favorite_70_plus',fav>=.7),('predicted_total_below6',total<6),('predicted_total_6to7',(total>=6)&(total<7)),('predicted_total_7plus',total>=7)]}
labelpath=P/'empty-net-labels.json'
if labelpath.exists():
 L={r['event_id']:r for r in json.loads(labelpath.read_text())};complete=np.array([L[r['event_id']].get('complete',False)for r in D]);positive=np.array([L[r['event_id']].get('explicit_empty_net_goals',0)>0 for r in D]);slices.update(empty_net_explicit=metrics(complete&positive),empty_net_no_explicit_marker=metrics(complete&~positive),empty_net_unknown=metrics(~complete))
else:slices['empty_net_unknown']={'n':len(D),'status':'CAPTURE_PENDING'}
x=np.log(p/(1-p));fit=minimize(lambda v:float(ll(1/(1+np.exp(-np.clip(v[0]+v[1]*x,-40,40))),y).sum()),[0,1],method='BFGS')
rel=reliability(p,y);allmask=np.ones(len(D),bool);awayp=q[:,0];awayy=(margin<=-2).astype(float);awayb=float(np.mean(pool[:,2]-pool[:,3]<=-2))
out={'created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_prediction_sha256':hashlib.sha256((B/'audit-predictions.json').read_bytes()).hexdigest(),'frozen_model_sha256':hashlib.sha256((B/'evaluation-model.json').read_bytes()).hexdigest(),'n':len(D),'cohort':'2026 season, 1312 same-event games; original bandwidth selected on 2025; post-screen diagnostic extension; not untouched prospective evidence','home_minus1_5':metrics(allmask),'away_minus1_5':metrics(allmask,awayp,awayy,awayb),'home_minus1_5_brier_bootstrap':bootstrap((p-y)**2-(b-y)**2),'home_minus1_5_log_loss_bootstrap':bootstrap(ll(p,y)-ll(b,y)),'home_minus1_5_brier_month_sensitivity':bootstrap((p-y)**2-(b-y)**2,'month'),'home_minus1_5_reliability':rel,'away_minus1_5_reliability':reliability(awayp,awayy),'home_minus1_5_ece10':sum(r.get('n',0)*abs(r.get('gap',0))for r in rel)/len(D),'calibration_fit_diagnostic_only':{'intercept':float(fit.x[0]),'slope':float(fit.x[1]),'optimizer_success':bool(fit.success),'used_in_model':False},'error_slices_home_minus1_5':slices,'slice_cautions':['Outcome-conditioned one-goal, OT/SO and empty-net slices are descriptive, not unconditional calibration tests.','No-explicit-marker is not certified absence of an empty-net goal.','Favorite strength and total environment use frozen model probabilities/means, not sportsbook lines.','Wilson intervals are descriptive iid intervals; clustered uncertainty is supplied for aggregate paired deltas.','Multiple exploratory slices; no slice selected for model adjustment.'],'promotion':'HOLD','action_authority':False}
(P/'evaluation.json').write_text(json.dumps(out,indent=2,sort_keys=True));print(json.dumps({k:out[k]for k in ['home_minus1_5','home_minus1_5_brier_bootstrap','home_minus1_5_log_loss_bootstrap','home_minus1_5_ece10','calibration_fit_diagnostic_only']},indent=2))
