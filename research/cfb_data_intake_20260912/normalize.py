"""Normalize captured evidence; no model fit, rating assumption, or market feature."""
import json,gzip,hashlib,collections
from pathlib import Path
from datetime import datetime,timezone
P=Path(__file__).parent;L=P.parent/'cfb_live_2139';O=P/'normalized';O.mkdir(exist_ok=True)
def dump(name,obj):
 b=json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode();(O/name).write_bytes(b);return hashlib.sha256(b).hexdigest()
rows={};conflicts=[];bad=[];dupes=0
for f in sorted((P/'history').glob('*.gz')):
 raw=gzip.decompress(f.read_bytes());d=json.loads(raw);sha=hashlib.sha256(raw).hexdigest()
 for e in d.get('events',[]):
  if not e.get('competitions'):bad.append({'event_id':e.get('id'),'reason':'missing_competitions','source':f.name});continue
  c=e['competitions'][0]
  if not c.get('status',e.get('status',{})).get('type',{}).get('completed'):continue
  try:
   sides={x['homeAway']:x for x in c['competitors']};teams={}
   for side in ['home','away']:
    x=sides[side];v=float(x['score']);assert v>=0 and v.is_integer();qs={int(q['period']):float(q.get('value',q.get('displayValue'))) for q in x.get('linescores',[])}
    assert all(v>=0 and v.is_integer() for v in qs.values())
    teams[side]=dict(team_id=x['team']['id'],name=x['team']['displayName'],score=int(v),period_scores=qs,half_points=int(qs[1]+qs[2]) if 1 in qs and 2 in qs else None,historical_division=None)
   if any(t['period_scores'] and sum(t['period_scores'].values())!=t['score'] for t in teams.values()):bad.append({'event_id':e['id'],'reason':'quarter_final_mismatch'});continue
   row=dict(event_id=e['id'],date=e['date'],season=e.get('season'),neutral_site=c.get('neutralSite'),venue=c.get('venue',{}).get('fullName'),**teams)
   if e['id'] in rows:
    dupes+=1
    if rows[e['id']]['data']!=row:conflicts.append(e['id'])
    rows[e['id']]['source_hashes'].append(sha)
   else:rows[e['id']]=dict(data=row,source_hashes=[sha])
  except Exception as ex:bad.append({'event_id':e.get('id'),'reason':str(ex)})
clean=[v for k,v in rows.items() if k not in set(conflicts)]
clean.sort(key=lambda r:(r['data']['date'],r['data']['event_id']))
dump('historical_results.json',clean)
receipts=json.load(open(L/'receipts.json'));receipts += json.load(open(P/'rosters_complete'/'receipts.json'));bykey={x['key']:x for x in receipts};states=[]
for f in sorted(L.glob('*_roster.json')):
 tid=f.name.split('_')[0];rf=P/'rosters_complete'/f.name;rf=rf if rf.exists() else f;r=json.loads(rf.read_bytes());s=json.load(open(L/f'{tid}_statistics.json'));dc=json.load(open(L/f'{tid}_depthcharts.json'))
 players=[]
 for group in r.get('athletes',[]):
  for a in group.get('items',[]):players.append({k:a.get(k) for k in ['id','fullName','position','experience','status','injuries']})
 stats={c['name']:{v['name']:v.get('value') for v in c.get('stats',[])} for c in s.get('results',{}).get('stats',{}).get('categories',[])}
 states.append(dict(team_id=tid,season=r.get('season'),source_timestamp=r.get('timestamp'),retrieved_at=bykey.get(tid+'_roster',{}).get('retrieved_at'),players=players,season_statistics=stats,depth_chart_available=bool(dc.get('depthcharts')),starter_binding='UNRESOLVED',player_impact_applied=False,roster_completeness='NOT_RECONCILED_WITH_OFFICIAL',source_hashes={kind:hashlib.sha256((rf if kind=='roster' else L/f'{tid}_{kind}.json').read_bytes()).hexdigest() for kind in ['roster','statistics','depthcharts']}))
dump('team_state.json',states)
schedule=json.load(open(L/'schedule.json'));slate=[]
for e in schedule.get('events',[]):
 c=e['competitions'][0];slate.append(dict(event_id=e['id'],date=e['date'],name=e['name'],status=c.get('status',e.get('status')),neutral_site=c.get('neutralSite'),venue=c.get('venue'),teams=[dict(team_id=x['team']['id'],home_away=x['homeAway'],name=x['team']['displayName']) for x in c['competitors']]))
dump('slate.json',slate)
summary=dict(generated_at=datetime.now(timezone.utc).isoformat(),teams=len(states),players=sum(len(x['players']) for x in states),teams_with_statistics=sum(bool(x['season_statistics']) for x in states),api_depth_charts=sum(x['depth_chart_available'] for x in states),schedule_events=len(slate),historical_final_events=len(clean),historical_duplicate_captures=dupes,historical_conflicts=sorted(set(conflicts)),historical_invalid=bad,by_season=dict(collections.Counter(str(x['data']['season']['year']) for x in clean)),history_half_covered=sum(all(x['data'][side]['half_points'] is not None for side in ['home','away']) for x in clean),historical_division_audit='PENDING',historical_pregame_snapshots=False,market_features_used=False,predictive_improvement='NOT_ESTABLISHED',new_forecast_run=False,action_authority='OFF')
dump('summary.json',summary)
# Store exact normalized bytes in deterministic gzip for efficient remote persistence.
for f in O.glob('*.json'):(O/(f.name+'.gz')).write_bytes(gzip.compress(f.read_bytes(),mtime=0))
print(json.dumps(summary,indent=2))
