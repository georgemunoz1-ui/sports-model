"""Additive frozen-forecast postgame audit. Does not write a canonical grade/state ledger."""
import json,hashlib,math,datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
P=Path(__file__).resolve().parent;R=P.parent
load=lambda p:json.loads(Path(p).read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(name,x): (P/name).write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
def score(p,y):
 return {'p':float(p),'outcome':int(y),'brier':float((p-y)**2),'log_loss':float(-math.log(max(1e-15,p if y else 1-p))),'direction_correct':bool((p>.5)==bool(y))}
def agg(rows):
 return {'n':len(rows),'direction_correct':sum(x['direction_correct']for x in rows),'brier':float(np.mean([x['brier']for x in rows])),'log_loss':float(np.mean([x['log_loss']for x in rows]))} if rows else None
receipts=load(P/'source-receipts.json');details=load(P/'detail-receipts.json');census=load(P/'event-census.json')
rec=next(x for x in receipts if x['kind']=='official_0929');sched=load(P/'sources'/rec['raw_path']);games=[g for w in sched['gameWeek']if w['date']=='2026-09-29'for g in w['games']]
old=load(R/'nhl-results/diagnostic_card.json');board=load(R/'nhl-joint-20260929-v1/board.json');market=load(R/'nhl-joint-market-comparison.json');ledger=load(R/'nhl-joint-followup-20260929/prospective-ledger.json');registry=load(R/'nhl-joint-followup-20260929/registry.json')
checks=[]
for e in registry['entries']:
 for file,h in e['hashes'].items():
  path=R/'nhl-joint-20260929-v1/forecasts'/e['forecast_directory']/file
  checks.append({'path':str(path.relative_to(R)),'expected':h,'actual':sha(path),'match':h==sha(path)})
assert all(x['match']for x in checks)
model=load(R/'nhl-joint-20260929-v1/model.json');outcomes=np.asarray(model['outcomes']);baseline=float(np.mean(outcomes[:,2]-outcomes[:,3]>1.5))
rows=[]
for g in games:
 h,a=g['homeTeam'],g['awayTeam'];home,away=h['abbrev'],a['abbrev'];hs,aws=int(h['score']),int(a['score']);m=hs-aws;t=hs+aws
 e=next(e for e in census if e['league']=='nhl' and any(c['team']['abbreviation']==home for c in e['competitors']) and any(c['team']['abbreviation']==away for c in e['competitors']))
 assert e['status']['type']['completed'];assert {c['team']['abbreviation']:int(c['score'])for c in e['competitors']}=={home:hs,away:aws}
 eid='NHL:'+e['id'];f=next(f for f in old['forecasts']if f['event_id']==eid);assert f['home_team']==h['placeName']['default']+' '+h['commonName']['default'] if 'commonName'in h else True
 assert abs(f['grading']['analytic_p_home']-(f['analytic_p'] if f['model_winner']==f['home_team'] else 1-f['analytic_p']))<1e-12
 pbprec=next(x for x in details if x['kind']==str(g['id'])+'_play-by-play');pbp=load(P/'sources'/pbprec['raw_path']);goals=[x for x in pbp['plays']if x.get('typeDescKey')=='goal']
 en=[]
 for goal in goals:
  d=goal['details'];s=str(goal.get('situationCode','')).zfill(4);scoring_home=d['eventOwnerTeamId']==h['id'];empty=s[0]=='0' if scoring_home else s[-1]=='0'
  if empty:en.append({'period':goal['periodDescriptor'],'time':goal['timeInPeriod'],'scoring_team':home if scoring_home else away,'score':[d['awayScore'],d['homeScore']],'situationCode':s,'goalieInNetId':d.get('goalieInNetId')})
 r={'event_id':eid,'official_event_id':g['id'],'matchup':away+' @ '+home,'home':home,'away':away,'final':{home:hs,away:aws},'phase':g['gameOutcome']['lastPeriodType'],'actual_home_margin':m,'actual_total':t,'result_reconciliation':'OFFICIAL_NHL_ESPN_AGREE','sources':[rec['raw_sha256'],e['source_sha256'],pbprec['raw_sha256']],'one_goal':abs(m)==1,'empty_net_goals':en,'original_winner':score(f['grading']['analytic_p_home'],hs>aws),'original_simulation':score(f['grading']['stochastic_sim_p_home'],hs>aws),'original_forecast_sha256':sha(R/'nhl-results/diagnostic_card.json'),'original_strict_prospective_eligible':f['grading']['eligible_for_prospective_grading'],'original_model_id':f['model_id']}
 j=next((x for x in board['forecasts']if x['event']['event_id']==eid),None)
 if j:
  l=next(x for x in ledger['events']if x['event_id']==eid);q=next(x for x in market['rows']if x['event_id']==eid);an=j['analytic'];sim=j['simulation'];d=np.load(R/'nhl-joint-20260929-v1/forecasts'/Path(j['path']).name/'joint_score_draws.npy');assert d.shape==(100000,5);assert hashlib.sha256(d.tobytes()).hexdigest()==j['draw_sha256'];assert abs(float(np.mean(d[:,2]>d[:,3]))-sim['home_win'])<1e-12
  r['joint']={'model_id':j['model_id'],'forecast_sha256':l['forecast_sha256'],'draw_raw_sha256':j['draw_sha256'],'seed':j['seed'],'draw_count':j['count'],'strict_prospective_time_eligible':l['strict_prospective_time_eligible'],'registration_status':'TIMING_ELIGIBLE_RESEARCH'if l['strict_prospective_time_eligible']else'ARCHIVAL_LATE','winner':score(an['home_win'],m>0),'winner_simulation':score(sim['home_win'],m>0),'home_minus1_5_primary':score(an['home_minus1_5'],m>1.5),'home_minus1_5_unconditional_baseline':score(baseline,m>1.5),'margin_mean':an['margin_mean'],'margin_absolute_error':abs(an['margin_mean']-m),'total_mean':an['total_mean'],'total_absolute_error':abs(an['total_mean']-t),'total_interval80':an['total_interval80'],'total_interval80_contains_actual':an['total_interval80'][0]<=t<=an['total_interval80'][1],'empirical_sim_total_ge_observed':float(np.mean(d[:,2]+d[:,3]>=t))}
  r['market']={'eligibility':'CONDITIONAL_DIAGNOSTIC_ONLY_UNVERIFIED_CAPTURE_TIME_AND_BOOK_BINDING','used_as_model_input':False,'home_moneyline':score(q['moneyline'][home]['market_no_vig'],m>0)}
  cv=q['cover'][home];r['joint']['quoted_home_cover']={'team':home,'line':cv['line'],**score(cv['model'],m+cv['line']>0),'simulation_p':cv['sim']};r['market']['quoted_home_cover']=score(cv['market_no_vig'],m+cv['line']>0)
  best=max(q['cover'],key=lambda k:q['cover'][k]['model']);bb=q['cover'][best]; r['joint']['preferred_cover']={'team':best,'line':bb['line'],**score(bb['model'],(m if best==home else -m)+bb['line']>0),'simulation_p':bb['sim']}
  tot=q['total'];r['joint']['quoted_over']={'line':tot['line'],**score(tot['model']['over'],t>tot['line']),'simulation_p':tot['sim']['over']};r['market']['quoted_over']=score(tot['market_over_no_vig'],t>tot['line'])
  direction='over'if tot['model']['over']>.5 else'under';r['joint']['preferred_total']={'direction':direction,'line':tot['line'],**score(tot['model'][direction],t>tot['line']if direction=='over'else t<tot['line']),'simulation_p':tot['sim'][direction]}
 rows.append(r)
summary={'original_all5':agg([r['original_winner']for r in rows]),'baseline_training_rows':len(outcomes),'baseline_home_minus1_5':baseline,'baseline_model_sha256':sha(R/'nhl-joint-20260929-v1/model.json')}
for label,subset in [('paired4',[r for r in rows if 'joint'in r]),('strict_joint3',[r for r in rows if r.get('joint',{}).get('strict_prospective_time_eligible')])]:
 s={'original_winner':agg([r['original_winner']for r in subset]),'joint_winner':agg([r['joint']['winner']for r in subset]),'joint_primary_home_minus1_5':agg([r['joint']['home_minus1_5_primary']for r in subset]),'unconditional_home_minus1_5':agg([r['joint']['home_minus1_5_unconditional_baseline']for r in subset]),'quoted_cover':agg([r['joint']['quoted_home_cover']for r in subset]),'quoted_total':agg([r['joint']['quoted_over']for r in subset]),'conditional_market_winner':agg([r['market']['home_moneyline']for r in subset]),'conditional_market_cover':agg([r['market']['quoted_home_cover']for r in subset]),'conditional_market_total':agg([r['market']['quoted_over']for r in subset])}
 s['delta_joint_minus_original_win_brier']=s['joint_winner']['brier']-s['original_winner']['brier'];s['delta_primary_minus_baseline_brier']=s['joint_primary_home_minus1_5']['brier']-s['unconditional_home_minus1_5']['brier'];summary[label]=s
# Monday last eligible frozen version. Existing research grade is referenced, never appended again.
F=R/'monday-primary/results-keenum/2026_03_PHI_CHI';nf=load(F/'forecast.json');mf=load(F/'qb_margin_calibrated/forecast.json');mq=load(R/'monday-primary/benchmarks/market-comparison.json');support=np.array(mf['margin_support']);weights=np.array(mf['margin_weights']);md=np.load(F/'qb_margin_calibrated/margin_draws.npy');assert hashlib.sha256(md.tobytes()).hexdigest()==mf['simulation']['raw_sha256']
pcover=float(weights[support < -3.5].sum());phi=1-nf['prediction']['home_win'];monday={'event_id':'2026_03_PHI_CHI','final':{'CHI':27,'PHI':7},'selected_qb':'Case Keenum','model_id':nf['model_id'],'forecast_sha256':sha(F/'forecast.json'),'margin_forecast_sha256':sha(F/'qb_margin_calibrated/forecast.json'),'cutoff_utc':nf['cutoff_utc'],'phi_win':score(phi,False),'phi_win_simulation':score(1-nf['winner_simulation']['home_win_probability'],False),'market_phi_win':score(mq['phi_win_no_vig'],False),'phi_cover_minus3_5':score(pcover,False),'phi_cover_simulation_p':float(np.mean(md < -3.5)),'market_phi_cover':score(mq['phi_cover_no_vig'],False),'mean_phi_margin':-mf['model_summary']['mean_home_margin'],'actual_phi_margin':-20,'absolute_margin_error':20-mf['model_summary']['mean_home_margin'],'phi_margin_central80':[-mf['model_summary']['quantiles_05_10_50_90_95'][3],-mf['model_summary']['quantiles_05_10_50_90_95'][1]],'probability_chi_win_by_at_least20':float(weights[support>=20].sum()),'total_forecast_grade':'UNSUPPORTED_NOT_GRADED','market_grade':'CONDITIONAL_DIAGNOSTIC_SETTLEMENT_UNVERIFIED','existing_grade_receipt':load(R/'monday-grade.json'),'duplicate_grade_appended':False,'counterfactual_graded':False,'parent_completed_week':2,'official_gamebook_clearance':False}
# Explicit source match for Monday.
ne=next(e for e in census if e['league']=='nfl');assert {c['team']['abbreviation']:int(c['score'])for c in ne['competitors']}==monday['final'];monday['fresh_result_source_sha256']=ne['source_sha256']
slices={}
for key,pred in [('one_goal',lambda r:r['one_goal']),('multi_goal',lambda r:not r['one_goal']),('OT_SO',lambda r:r['phase']in['OT','SO']),('regulation',lambda r:r['phase']=='REG'),('empty_net_present',lambda r:bool(r['empty_net_goals'])),('empty_net_absent',lambda r:not r['empty_net_goals']),('market_favorite_65plus',lambda r:max(r['market']['home_moneyline']['p'],1-r['market']['home_moneyline']['p'])>=.65),('market_favorite_under65',lambda r:max(r['market']['home_moneyline']['p'],1-r['market']['home_moneyline']['p'])<.65),('quoted_total5_5',lambda r:r['joint']['quoted_over']['line']==5.5),('quoted_total6_5',lambda r:r['joint']['quoted_over']['line']==6.5)]:
 ss=[r for r in rows if 'joint'in r and pred(r)];slices[key]={'events':[r['event_id']for r in ss],'winner':agg([r['joint']['winner']for r in ss]),'cover':agg([r['joint']['quoted_home_cover']for r in ss]),'total':agg([r['joint']['quoted_over']for r in ss]),'interpretation':'DESCRIPTIVE_TINY_SAMPLE_NOT_SUBGROUP_VALIDATION'}
result={'schema':'postgame_frozen_forecast_audit.v1','created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'dates_pacific':['2026-09-28','2026-09-29'],'nhl':rows,'nhl_summary':summary,'nhl_slices':slices,'nfl':monday,'integrity':{'checks':checks,'matched':sum(x['match']for x in checks),'original_forecasts_changed':False},'canonical_grading_ledger_written':False,'model_state_advanced':False,'model_parameters_changed':False,'action':'OFF','dose':0.0,'official_release_eligible':False}
save('analysis.json',result);save('event-id-reconciliation.json',[{k:r[k]for k in ['event_id','official_event_id','matchup','final','sources']}for r in rows]);print(json.dumps({'summary':summary,'nfl':{k:v for k,v in monday.items()if k not in ['existing_grade_receipt']},'nhl_brief':[{k:r[k]for k in ['matchup','final','phase','empty_net_goals']}for r in rows]},indent=2))
