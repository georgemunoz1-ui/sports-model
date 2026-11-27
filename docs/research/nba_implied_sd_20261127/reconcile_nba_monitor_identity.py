"""Independent archive readback, not execution of original implied-SD monitor."""
from pathlib import Path
import io,json,hashlib,zipfile,math
from datetime import datetime,timezone
from scipy.stats import binomtest,binom
import numpy as np
D=Path('/mnt/data')
def sha(b):return hashlib.sha256(b).hexdigest()
def digest(v):return sha(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def get(p):return json.loads(p.read_bytes())
def close(a,b):return math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12)
def calc(head,features,names):
 x=np.array([np.nan if features[k] is None else features[k] for k in names]);x=np.where(np.isnan(x),head['impute'],x)
 y=float(np.dot((x-np.array(head['mean']))/head['scale'],head['coefficient'])+head['intercept']);return 1/(1+math.exp(-y)) if head['kind']=='logistic' else y
orig=D/'NBA-2026-11-27-Implied-SD-Diagnostic.json'; raw=D/'NBA-2026-11-27-Implied-SD-Diagnostic-Rows.jsonl'; board=D/'November-27-Early-Pregame-Card.json'; zpath=D/'evidence/November-27-Card-and-Source-Evidence.zip'
r=get(orig); rows=[json.loads(s) for s in raw.read_text().splitlines()]; b=get(board); by={x['event_id']:x for x in b['rows'] if x['league']=='NBA'}
assert len(rows)==len(by)==11 and len({x['event_id'] for x in rows})==11
assert sha(raw.read_bytes())==r['rows_sha256'] and sha(board.read_bytes())==r['source_card_sha256']
archive_sha=sha(zpath.read_bytes());assert archive_sha=='979a3cd56be69bdba9022204fbe4cf09a1b6bf06d317cc4a35adae51e05e9b2b'
with zipfile.ZipFile(zpath) as outer:
 zb=outer.read('November-27-NBA-Evidence.zip')
with zipfile.ZipFile(io.BytesIO(zb)) as inner:
 pp='pro27/packages/nba/package.json';cp='pro27/cards/nba/diagnostic_card.json';pb=inner.read(pp);cb=inner.read(cp);p=json.loads(pb);card=json.loads(cb);native={x['event_id']:x for x in card['forecasts']}
 assert len(native)==11 and set(native)==set(by)
 fit=p['fitted_model']; st=p['team_state']; prior=p['prior']; combined=digest({'model':fit,'state':st,'prior':prior}); assert combined==p['model_sha256']
 fit_hash=digest(fit); head_hash=digest({k:fit[k] for k in ['winner','margin']}); state_hash=digest(st); prior_hash=digest(prior); fs=[]; procs=set(); checks=0
 for row in rows:
  eid=row['event_id']; nr=native[eid]; br=by[eid]; se=br['evidence']['selected']; numeric_path='pro27/cards/nba/draws/'+eid.replace(':','_')+'.semantic-v2/numeric_inputs.json'; n=json.loads(inner.read(numeric_path)); ni=n['numerical_identity']
  assert sha(pb)==se['package_sha256'] and sha(cb)==se['parent_file_sha256']==row['parent_file_sha256']
  assert row['state_config_hash']==nr['model_state_config_hash']==combined
  assert ni==nr['numerical_identity'] and ni['event_id']==eid and ni['model_id']==row['model_id']
  assert digest({k:v for k,v in ni.items() if k!='identity_sha256'})==ni['identity_sha256']
  assert digest(n['fitted_state'])==ni['fitted_state_sha256']
  assert {k:v for k,v in n['fitted_state'].items() if k!='transform_code'}==fit
  assert digest(n['features'])==ni['feature_sha256']==row['input_snapshot_hash']
  assert n['features']==nr['model_input_snapshot']
  assert close(calc(fit['winner'],n['features'],p['feature_names']),row['p_home']) and close(calc(fit['margin'],n['features'],p['feature_names']),row['home_margin'])
  assert close(row['p_home'],br['p_home']) and close(row['home_margin'],br['home_margin'])
  procs.add((nr['forecast_procedure_id'],ni['feature_procedure_id'],ni['calibration_procedure_id'],ni['semantic_runtime_sha256'],ni['fitted_state_sha256']))
  fs.append({**row,'fitted_parameter_hash':fit_hash,'winner_margin_parameter_hash':head_hash,'input_state_hash':state_hash,'prior_configuration_hash':prior_hash,'native_numeric_fitted_state_sha256':ni['fitted_state_sha256'],'forecast_procedure_id':nr['forecast_procedure_id'],'feature_procedure_id':ni['feature_procedure_id'],'calibration_procedure_id':ni['calibration_procedure_id'],'numerical_identity_sha256':ni['identity_sha256'],'archive_numeric_inputs_path':numeric_path})
 assert len(procs)==1
 out=D/'NBA-2026-11-27-Implied-SD-Identity-Bound-Rows.jsonl';out.write_text(''.join(json.dumps(v,sort_keys=True,allow_nan=False)+'\n' for v in fs)); proc=next(iter(procs))
 result={'schema':'independent.implied_sd_identity_reconciliation.v1','scope':r['scope']+'; independent archive identity and numerical head replay; not a baseline admission, monitor integration, or prospective receipt','slate':r['slate'],'reconciled_at_utc':datetime.now(timezone.utc).isoformat(),'repo_source_inspection_ref':'4f499e5af44222632bc7256e10532d14bea191c0','original_diagnostic_sha256':sha(orig.read_bytes()),'original_rows_sha256':r['rows_sha256'],'source_card_sha256':r['source_card_sha256'],'outer_archive_sha256':archive_sha,'nested_archive_sha256':sha(zb),'package_path':pp,'package_sha256':sha(pb),'native_card_path':cp,'native_card_sha256':sha(cb),'model_id':p['model_id'],'model_state_config_hash':combined,'fitted_parameter_hash':fit_hash,'winner_margin_parameter_hash':head_hash,'input_state_hash':state_hash,'prior_configuration_hash':prior_hash,'feature_names_sha256':digest(p['feature_names']),'forecast_procedure_id':proc[0],'feature_procedure_id':proc[1],'calibration_procedure_id':proc[2],'semantic_runtime_sha256':proc[3],'native_numeric_fitted_state_sha256':proc[4],'training_cutoff_utc':p['training_cutoff_utc'],'identity_bound_rows_file':out.name,'identity_bound_rows_sha256':sha(out.read_bytes()),'rows_verified':len(fs),'status':'PARAMETER_AND_INPUT_STATE_IDENTITIES_RECOVERED','drift_status':'NOT_EVALUATED','baseline_admission':'NOT_ESTABLISHED','reason':'One retained slate only; original monitor and tests not recovered; comparable prior series not verified; fixed-fit vs refit-procedure policy unresolved','action_authority':False,'official_units':0.0,'binomial_reference_only':{'assumption':'Independent Bernoulli flags (illustrative, overlapping rolling windows violate independence)','n':14,'nominal_rate':.05,'p_zero_flags':float(binom.pmf(0,14,.05)),'p_at_least_three_flags':float(binom.sf(2,14,.05)),'exact_95_intervals':[{ 'flags':k,'rate':k/14,'interval':list(binomtest(k,14).proportion_ci())} for k in range(4)]}}
 receipt=D/'NBA-2026-11-27-Implied-SD-Identity-Reconciliation.json'; receipt.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
 print(json.dumps(result,indent=2))
