import urllib.request,json,pathlib,datetime,hashlib,gzip,concurrent.futures as cf
P=pathlib.Path(__file__).resolve().parent;D=P/'personnel';D.mkdir(exist_ok=True)
contract=P/'personnel-contract.json';h=hashlib.sha256(contract.read_bytes()).hexdigest();seal={'registered_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'contract_sha256':h,'used_as_model_input':False};(P/'personnel-contract-seal.json').write_text(json.dumps(seal,indent=2))
board=json.load(open(P.parent/'nhl-joint-20260929-v1/board.json'))['forecasts'];jobs=[('injuries','https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries')]
for f in board:jobs.append((f['event']['event_id'].replace(':','-'),'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/summary?event='+f['event']['event_id'].split(':')[1]))
for a in ['MTL','TOR','NYR','BOS','VAN','EDM','CHI','VGK','PIT','PHI','NYI','LAK','COL','BUF','CBJ','NJD','TBL','MIN','NSH','SEA','CGY','UTA','FLA','SJS']:jobs.append(('roster-'+a,'https://api-web.nhle.com/v1/roster/'+a+'/20262027'))
def get(j):
 name,url=j;r={'id':name,'url':url,'retrieved_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'contract_sha256':h,'used_as_model_input':False}
 try:
  raw=urllib.request.urlopen(url,timeout=15).read();(D/(name+'.json.gz')).write_bytes(gzip.compress(raw,mtime=0));r.update(status='CAPTURED',raw_sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
  d=json.loads(raw)
  if name.startswith('NHL-'):r.update(event_state=d.get('header',{}).get('competitions',[{}])[0].get('status',{}).get('type',{}).get('state'),injury_groups_available=len(d.get('injuries',[])),confirmed_goalie=None,confirmation_status='UNKNOWN_REQUIRES_SOURCE_BOUND_MANUAL_CONFIRMATION')
 except Exception as e:r.update(status='FAILED',error=str(e))
 return r
with cf.ThreadPoolExecutor(max_workers=6)as ex:out=list(ex.map(get,jobs))
(P/'personnel-acquisition.json').write_text(json.dumps(out,indent=2));print({'captured':sum(x['status']=='CAPTURED'for x in out),'requested':len(out),'confirmed_goalies':0,'used_as_model_input':False})
