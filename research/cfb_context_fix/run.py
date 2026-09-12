import argparse
import pathlib,json,csv,hashlib,datetime,math
import numpy as np
from model import fit,predict,roster_state,MODEL_ID
root=pathlib.Path(__file__).parent
parser=argparse.ArgumentParser();parser.add_argument('--state',default=str(root.parent/'cfb_empirical_margin/run_02/state.json'));parser.add_argument('--identities',default=str(root.parent/'cfb_empirical_margin/run_02/identities.csv'));parser.add_argument('--half-history',default=str(root.parent/'cfb_first_half/results/history.json'));parser.add_argument('--capture',default=str(root/'capture'));parser.add_argument('--output',required=True);args=parser.parse_args();capture=pathlib.Path(args.capture);out=pathlib.Path(args.output);out.mkdir(exist_ok=False)
state=json.load(open(args.state));halves={x['event_id']:x for x in json.load(open(args.half_history))};rows=[]
for x in state['updates']:
 if x['event_id'] in halves and not x['neutral_site']:
  r=dict(x);r['home_half']=halves[x['event_id']]['home_first_half'];r['away_half']=halves[x['event_id']]['away_first_half'];rows.append(r)
rows.sort(key=lambda x:(x['start_time_utc'],x['event_id']))
train,test=rows[:-12],rows[-12:]; fm=fit(train); val=[]; trainmargin=np.mean([x['home_score']-x['away_score'] for x in train]);traintotal=np.mean([x['home_half']+x['away_half'] for x in train])
for x in test:
 p,_,_=predict(fm,x['home_id'],x['away_id'],x['home_elo_before'],x['away_elo_before'],x['event_id'],'validation')
 val.append({'event_id':x['event_id'],'margin_error':abs(p['full_game_home_margin']-(x['home_score']-x['away_score'])),'baseline_margin_error':abs(trainmargin-(x['home_score']-x['away_score'])),'half_total_error':abs(p['first_half_total']-x['home_half']-x['away_half']),'baseline_half_total_error':abs(traintotal-x['home_half']-x['away_half'])})
validation={'n_train':len(train),'n_test':len(test),'scope':'ONE_CHRONOLOGICAL_SPLIT_NOT_PREDICTIVE_VALIDATION','metrics':{k:float(np.mean([x[k] for x in val])) for k in ['margin_error','baseline_margin_error','half_total_error','baseline_half_total_error']},'rows':val}
trained=fit(rows);(out/'training.json').write_text(json.dumps(rows,indent=2));(out/'model.json').write_text(json.dumps(trained,indent=2));(out/'validation.json').write_text(json.dumps(validation,indent=2));ih=hashlib.sha256(json.dumps({'rows':rows,'model':trained},sort_keys=True).encode()).hexdigest()
identity={}
for r in csv.DictReader(open(args.identities)):
 for side in ['home','away']:identity[r[side+'_id']]=(r[side+'_team'],r[side+'_division'])
receipts=json.load(open(root/'capture/receipts.json'));cutoff=datetime.datetime.now(datetime.timezone.utc);games=[]
# Re-use real source schedule; writer clock additionally blocks starts passed during acquisition.
schedule=json.load(open(root/'capture/schedule.json'))
for e in schedule['events']:
 c=e['competitions'][0];h=next(x for x in c['competitors'] if x['homeAway']=='home');a=next(x for x in c['competitors'] if x['homeAway']=='away');hid,aid=h['id'],a['id'];g={'event_id':e['id'],'home':h['team']['displayName'],'away':a['team']['displayName'],'start':c['date'],'status':'BLOCKED','primary_current_roster_forecast':'UNAVAILABLE','roster_adjustment_points':None};games.append(g)
 try:
  if c['status']['type']['state']!='pre' or datetime.datetime.fromisoformat(c['date'].replace('Z','+00:00'))<=datetime.datetime.now(datetime.timezone.utc):raise ValueError('STARTED')
  if any(identity.get(t,('',None))[1]!='fbs' for t in (hid,aid)):raise ValueError('FCS_BRIDGE_UNSUPPORTED')
  if c.get('neutralSite'):raise ValueError('NEUTRAL_VENUE_UNSUPPORTED')
  g['current_context']={}
  for side,t in [('home',hid),('away',aid)]:
   f=capture/(t+'_roster.json');ctx=roster_state(json.load(open(f))) if f.exists() else roster_state({})
   d=capture/(t+'_depthcharts.json');depth=json.load(open(d)) if d.exists() else {};ctx['depthchart_status']='CAPTURED_UNPARSED' if depth.get('depthchart') or depth.get('depthcharts') else 'UNAVAILABLE'
   st=capture/(t+'_statistics.json');stats=json.load(open(st)) if st.exists() else {};ctx['current_season_team_stats']={c['name']:{z['name']:z.get('value') for z in c.get('stats',[])} for c in stats.get('results',{}).get('stats',{}).get('categories',[]) if c['name'] in ['passing','rushing','scoring','general']};ctx['stats_used_as_predictive_features']=False;ctx['weather']='UNRESOLVED';ctx['travel']='UNRESOLVED';g['current_context'][side]=ctx
  hn,an=identity[hid][0],identity[aid][0];p,md,td=predict(trained,hid,aid,state['team_elo'][hn],state['team_elo'][an],e['id'],ih)
  g.update(status='TEAM_CONDITIONED_DIAGNOSTIC_UNVALIDATED',model=p,model_rating_vintage=state['cutoff_utc'],impact_transform=MODEL_ID,simulation_method='ROUNDED_NORMAL_APPROXIMATION_NOT_DRIVE_SIMULATOR')
  for name,draw in [('full_margin',md),('first_half_total',td)]:
   values,counts=np.unique(draw,return_counts=True);g[name+'_histogram']={str(int(k)):int(v) for k,v in zip(values,counts)}
  odds=next((o for o in c.get('odds',[]) if 'DraftKings' in o.get('provider',{}).get('name','')),None)
  if odds and odds.get('homeTeamOdds',{}).get('favorite') is not None:
   line=abs(float(odds['spread']))*(-1 if odds['homeTeamOdds']['favorite'] else 1);g['market']={'book':'DraftKings via ESPN','home_spread':line}
   if line%1==0:g['market']['cover_status']='WHOLE_NUMBER_ATS_UNSUPPORTED_NORMAL_APPROXIMATION'
   else:
    g['market']['sim_home_cover']=float(np.mean(md+line>0));z=(p['full_game_home_margin']+line)/p['margin_sigma'];g['market']['model_home_cover']=.5*(1+math.erf(z/2**.5))
  if hid=='264' and aid=='328':g['user_first_half_quote']={'line':30.5,'price':.51,'quote_time':'UNKNOWN','sim_under':float(np.mean(td<30.5)),'model_under':.5*(1+math.erf((30.5-p['first_half_total'])/p['half_total_sigma']/2**.5)),'action':'OFF','value_established':False}
 except (KeyError,ValueError) as ex:g['reason']=str(ex)
bundle={'model_id':MODEL_ID,'cutoff':cutoff.isoformat(),'source_receipts':receipts,'numpy_version':np.__version__,'input_hash':ih,'action_authority':'OFF','canonical_prospective_eligible':False,'primary_current_roster_forecast':'BLOCKED_UNCONFIRMED_STARTERS_AND_UNTRAINED_PLAYER_IMPACTS','validation':validation,'rows':games};(out/'bundle.json').write_text(json.dumps(bundle,indent=2,allow_nan=False))
lines=['# CFB team-conditioned research refresh','',f'Cutoff: {cutoff.isoformat()}. All 80 games retained. Current-roster primary forecasts remain unavailable: starting QB/game availability unconfirmed and player impact model untrained. These are team-conditioned research diagnostics; not validated selections.','', '| Away @ Home | Full-game home margin | First-half total | Home spread | Model cover | Sim cover | Status |','|---|---:|---:|---:|---:|---:|---|']
for g in games:
 p=g.get('model',{});m=g.get('market',{});lines.append(f'| {g["away"]} @ {g["home"]} | '+(f'{p["full_game_home_margin"]:.2f} | {p["first_half_total"]:.2f}' if p else '— | —')+f' | {m.get("home_spread","—")} | '+(f'{m["model_home_cover"]:.1%} | {m["sim_home_cover"]:.1%}' if 'model_home_cover'in m else '— | —')+f' | {g.get("reason",g["status"])} |')
(out/'report.md').write_text('\n'.join(lines));(out/'manifest.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir()},indent=2))
print(json.dumps({'validation':validation['metrics'],'training':len(rows),'forecasts':sum('model'in g for g in games),'washington':[{'status':g['status'],'model':g.get('model'),'quote':g.get('user_first_half_quote'),'qbs':{s:c['quarterbacks'] for s,c in g.get('current_context',{}).items()}} for g in games if g['home']=='Washington Huskies']},indent=2))
