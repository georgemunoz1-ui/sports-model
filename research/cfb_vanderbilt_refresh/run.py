import json,csv,hashlib,math,sys
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
root=Path(__file__).parent;src=root/'sources';out=root/'run_02';out.mkdir(exist_ok=False)
div={}
for r in csv.DictReader(open('cfb_ats_patch/run_02/identities.csv')):
 for side in ['home','away']:div[r[side+'_id']]=r[side+'_division']
rows=[];excluded=[]
for rec in json.load(open(src/'receipts.json')):
 if not rec['ok'] or not rec['key'].isdigit():continue
 b=json.load(open(src/(rec['key']+'.json')));c=b['header']['competitions'][0]
 try:
  if not c['status']['type']['completed'] or c['date']>='2026-09-12':raise ValueError('NOT_ELIGIBLE_FINAL')
  h=next(x for x in c['competitors'] if x['homeAway']=='home');a=next(x for x in c['competitors'] if x['homeAway']=='away')
  def half(t):
   ls=t['linescores']
   if len(ls)<4:raise ValueError('QUARTERS_MISSING')
   vals=[float(x['value'] if 'value' in x else x['displayValue']) for x in ls]
   if any(not x.is_integer() or x<0 for x in vals):raise ValueError('INVALID_QUARTERS')
   if sum(vals)!=float(t['score']):raise ValueError('QUARTER_FINAL_MISMATCH')
   return sum(vals[:2])
  hid=h['team']['id'];aid=a['team']['id']
  if div.get(hid) not in ['fbs','fcs'] or div.get(aid) not in ['fbs','fcs']:raise ValueError('DIVISION_UNKNOWN')
  rows.append(dict(event_id=c['id'],date=c['date'],home_id=hid,away_id=aid,home_half=half(h),away_half=half(a),home_div=div[hid],away_div=div[aid],source_sha256=rec['sha256']))
 except (KeyError,ValueError) as e:excluded.append({'event_id':rec['key'],'reason':str(e)})
rows.sort(key=lambda r:(r['date'],r['event_id']))
assert len(rows)>=40

def fit(rs):
 ids=sorted({r[k] for r in rs for k in ['home_id','away_id']});X=[];Y=[]
 def design(team,opp,td,od):
  z=np.zeros(3+2*len(ids));z[:3]=[1,td=='fcs',od=='fcs']
  if team in ids:z[3+ids.index(team)]=1
  if opp in ids:z[3+len(ids)+ids.index(opp)]=1
  return z
 for r in rs:
  for s,o in [('home','away'),('away','home')]:X.append(design(r[s+'_id'],r[o+'_id'],r[s+'_div'],r[o+'_div']));Y.append(r[s+'_half'])
 X=np.array(X);Y=np.array(Y);reg=np.eye(X.shape[1])*5;reg[0,0]=0;beta=np.linalg.solve(X.T@X+reg,X.T@Y)
 res=(Y-X@beta).reshape(-1,2).sum(axis=1);sigma=float(np.std(res,ddof=1))
 return ids,beta,sigma,design
ids,beta,sig,design=fit(rows[:-12]);err=[];base=np.mean([r['home_half']+r['away_half'] for r in rows[:-12]])
for r in rows[-12:]:
 pred=sum(float(design(r[s+'_id'],r[o+'_id'],r[s+'_div'],r[o+'_div'])@beta) for s,o in [('home','away'),('away','home')]);actual=r['home_half']+r['away_half'];err.append({'event_id':r['event_id'],'error':pred-actual,'baseline_error':base-actual})
validation={'n_train':len(rows)-12,'n_test':12,'mae':float(np.mean([abs(x['error']) for x in err])),'baseline_mae':float(np.mean([abs(x['baseline_error']) for x in err])),'status':'SMALL_CHRONOLOGICAL_DIAGNOSTIC_NOT_VALIDATION','rows':err}
ids,beta,sig,design=fit(rows)
hm=float(design('238','48','fbs','fbs')@beta);am=float(design('48','238','fbs','fbs')@beta);assert min(hm,am)>=0
parent=Path('cfb_context_fix/results_02/bundle.json');parentraw=parent.read_bytes();pb=json.loads(parentraw);old=next(r for r in pb['rows'] if r['event_id']=='401856684')
now=datetime.now(timezone.utc);start=datetime.fromisoformat(old['start'].replace('Z','+00:00'));protocol=json.load(open(root/'protocol.json'))
params={'ids':ids,'beta':beta.tolist(),'half_total_sigma':sig,'ridge':5};ih=hashlib.sha256(json.dumps({'rows':rows,'params':params},sort_keys=True).encode()).hexdigest();seed=int.from_bytes(hashlib.sha256((protocol['model_id']+':401856684:'+ih+':100000').encode()).digest()[:8],'big');draw=np.maximum(0,np.rint(np.random.default_rng(seed).normal(hm+am,sig,100000))).astype('<i2')
b={'model_id':protocol['model_id'],'event_id':old['event_id'],'generated_at':now.isoformat(),'scheduled_start':old['start'],'timing_status':'PREGAME_LOCAL_DIAGNOSTIC' if now<start else 'POST_START_RESEARCH_ONLY_NOT_PREGAME','history_end':'2026-09-11','n_history':len(rows),'team_history':{tid:[r for r in rows if tid in [r['home_id'],r['away_id']]] for tid in ['238','48']},'first_half_home_points':hm,'first_half_away_points':am,'first_half_total':hm+am,'first_half_total_quantiles':{f'p{q}':int(np.quantile(draw,q/100,method='inverted_cdf')) for q in [10,25,50,75,90]},'in_sample_sigma_uncalibrated':sig,'validation':validation,'seed':seed,'n_sims':100000,'numpy_version':np.__version__,'draws_sha256':hashlib.sha256(draw.tobytes()).hexdigest(),'input_hash':ih,'parent_sha256':hashlib.sha256(parentraw).hexdigest(),'full_game_margin_frozen_unchanged':old['model']['full_game_home_margin'],'full_game_total':'UNSUPPORTED','whole_number_spread':'UNSUPPORTED','roster_adjustment_points':None,'action_authority':'OFF','canonical_prospective_eligible':False,'limitations':['ONE_GAME_PER_TEAM','OPPONENT_DIVISION_OFFSET_UNVALIDATED','CURRENT_ROSTER_IMPACT_ABSENT','IN_SAMPLE_VARIANCE_UNCALIBRATED','NO_MARKET_INPUTS','NO_NEW_FULL_GAME_FORECAST']}
for name,obj in [('bundle',b),('training',rows),('parameters',params),('excluded',excluded)]: (out/(name+'.json')).write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')
(out/'first_half_total.bin').write_bytes(draw.tobytes());assert parent.read_bytes()==parentraw
assert np.array_equal(draw,np.maximum(0,np.rint(np.random.default_rng(seed).normal(hm+am,sig,100000))).astype('<i2'))
print(json.dumps({k:v for k,v in b.items() if k not in ['validation','team_history']},indent=2));print('validation',validation['mae'],validation['baseline_mae']);print('team_history',b['team_history'])
