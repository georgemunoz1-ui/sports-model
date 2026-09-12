import json,pathlib,hashlib,re,sys,datetime,math,csv
import numpy as np
root=pathlib.Path(__file__).parent;sys.path.insert(0,str(root.parent/'cfb_context_fix'));from model import predict,MODEL_ID
out=root/'run';out.mkdir(exist_ok=False)
receipts=json.load(open(root/'receipts.json'));assert all(datetime.datetime.fromisoformat(r['retrieved_at'])<=datetime.datetime.now(datetime.timezone.utc) for r in receipts)
def parse_chart(path,col):
 lines=path.read_text().splitlines();records=[]
 for column in [0,1]:
  position=None;rank=0;slot=0
  for line in lines:
   cell=(line[:col] if column==0 else line[col:]).strip()
   if 'SPECIALISTS' in cell or 'SPECIAL TEAMS' in cell:break
   m=re.match(r'(?:(X-WR|H-WR|Z-WR|LT|LG|C|RG|RT|TE|QB|RB|WR|EDGE|DT|LB|NICKEL|CB|S|DE|NOSE|WILL|SAM|MIKE|BUCK|FS|BS|FC|BC)\s+)?(\d{1,2})\s+(.+)',cell)
   if not m:continue
   pos,num,tail=m.groups()
   if pos:position=pos;rank=0;slot+=1
   if not position:continue
   name=re.split(r'\s*\(|\s*\.\s*\.',tail)[0].strip().rstrip('.')
   if not name:continue
   rank+=1;records.append({'position':position,'slot':f'{column}_{slot}','printed_order':rank,'jersey':num,'name':name,'or_label':' OR' in name,'source_line':cell})
 return records
charts={}
for team,file,col,page in [('264','washington',108,10),('328','utah_state',91,4)]:
 records=parse_chart(root/(file+'_chart.txt'),col);qb=[r for r in records if r['position']=='QB'];expected='DEMOND WILLIAMS' if team=='264' else 'McCae Hillstead'
 assert qb and expected.lower() in qb[0]['name'].lower(),(team,qb)
 charts[team]={'team_id':team,'status':'OFFICIAL_PUBLISHED_DEPTH_CHART','page':page,'chart_scope':'2026-09-12_USU_AT_WASH','published_qb':qb[:2],'positions':records,'source_receipt':next(r for r in receipts if r['name']==file+'_notes.pdf'),'game_day_active_status':'NOT_CONFIRMED','player_impact_transform':None,'player_adjustment_points':None}
(out/'depth_state.json').write_text(json.dumps(charts,indent=2))
roster=json.load(open(root.parent/'cfb_context_fix/capture/264_roster.json'));names=[p['displayName'] for g in roster['athletes'] for p in g['items']];conflict={'team_id':'264','official_qb':'Demond Williams Jr.','in_captured_espn_roster':any('demond williams' in x.lower() for x in names),'disposition':'OFFICIAL_DEPTH_CHART_PREFERRED_FOR_PUBLISHED_ORDER; ESPN_SNAPSHOT_INCOMPLETE; NO_CANONICAL_PLAYER_ID_INVENTED'}
assert not conflict['in_captured_espn_roster'];(out/'defects.json').write_text(json.dumps([conflict],indent=2))
e=json.load(open(root/'event.json'));c=e['header']['competitions'][0];teams={x['homeAway']:x['id'] for x in c['competitors']};assert teams=={'home':'264','away':'328'}
now=datetime.datetime.now(datetime.timezone.utc);start=datetime.datetime.fromisoformat(c['date'].replace('Z','+00:00'))
if c['status']['type']['state']!='pre' or now>=start:raise ValueError('POST_START_FORECAST_BLOCKED')
model=json.load(open(root.parent/'cfb_context_fix/results_02/model.json'));state=json.load(open(root.parent/'cfb_ats_patch/run_02/state.json'));he=state['team_elo']['Washington'];ae=state['team_elo']['Utah State']
evidence={'depth_state':charts,'trained_model':model,'home_elo':he,'away_elo':ae,'numerical_rating_vintage':state['cutoff_utc']};ih=hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest();p,md,td=predict(model,'264','328',he,ae,'401858446',ih)
(out/'inputs.json').write_text(json.dumps(evidence,indent=2));(out/'full_margin.bin').write_bytes(md.tobytes());(out/'first_half_total.bin').write_bytes(td.tobytes())
bundle={'schema':'depth_bound_diagnostic.v1','model_id':MODEL_ID,'event_id':'401858446','cutoff':now.isoformat(),'start':start.isoformat(),'home':'Washington','away':'Utah State','status':'SOURCE_CONFLICT_BASELINE_WITH_OFFICIAL_DEPTH_STATE','action_authority':'OFF','canonical_prospective_eligible':False,'input_sha256':ih,'code_sha256':hashlib.sha256((root/'ingest_run.py').read_bytes()).hexdigest(),'numeric_engine_sha256':hashlib.sha256((root.parent/'cfb_context_fix/model.py').read_bytes()).hexdigest(),'numpy_version':np.__version__,'projection':p,'depth_state':charts,'roster_conflict':conflict,'numerical_effect_of_depth_ingestion':'NONE_NO_TRAINED_PLAYER_IMPACT_TRANSFORM','market_quote':{'source':'USER_SCREENSHOTS','period':'FIRST_HALF','line':30.5,'under_price':.51,'observed_at':'UNKNOWN','freshness':'NOT_RECONFIRMED'},'first_half_under_30_5':{'model':.5*(1+math.erf((30.5-p['first_half_total'])/p['half_total_sigma']/2**.5)),'simulation':float(np.mean(td<30.5)),'push':0.0,'value_established':False},'limitations':['In-sample residual variance, uncalibrated','Utah State attack term uses prior fallback','Game-day availability, weather, travel and player impact not resolved']}
(out/'bundle.json').write_text(json.dumps(bundle,indent=2));report=f'''# USU at Washington — official depth-chart ingestion and new diagnostic

Cutoff: {now.isoformat()}; kickoff: {start.isoformat()}.

Official published QBs: Washington Demond Williams Jr. / Elijah Brown; Utah State McCae Hillstead / Grady Brosterhous. These are published orders, not guaranteed game-day active status. The incomplete ESPN Washington roster is flagged and preserved.

| Forecast | Value |
|---|---:|
| Washington full-game expected margin | {p['full_game_home_margin']:.2f} |
| Washington first-half points | {p['first_half_home_points']:.2f} |
| Utah State first-half points | {p['first_half_away_points']:.2f} |
| First-half expected total | {p['first_half_total']:.2f} |
| Model Under 30.5 | {bundle['first_half_under_30_5']['model']:.2%} |
| 100K simulation Under 30.5 | {bundle['first_half_under_30_5']['simulation']:.2%} |

Depth charts improve identity/state evidence. They do not change numeric means without a trained player-impact transform. In-sample residual uncertainty remains uncalibrated; first-half validation did not beat baseline. Utah State attack history falls back to prior. No betting value or action authority established. Old forecasts unchanged.
''';(out/'report.md').write_text(report)
with (out/'forecast.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=['event_id','cutoff','home','away','home_margin','first_half_total','model_under_30_5','sim_under_30_5']);w.writeheader();w.writerow({'event_id':bundle['event_id'],'cutoff':bundle['cutoff'],'home':'Washington','away':'Utah State','home_margin':p['full_game_home_margin'],'first_half_total':p['first_half_total'],'model_under_30_5':bundle['first_half_under_30_5']['model'],'sim_under_30_5':bundle['first_half_under_30_5']['simulation']})
(out/'manifest.json').write_text(json.dumps({f.name:{'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in out.iterdir()},indent=2));print(json.dumps({'cutoff':bundle['cutoff'],'positions':{k:len(v['positions']) for k,v in charts.items()},'under':bundle['first_half_under_30_5']},indent=2))
