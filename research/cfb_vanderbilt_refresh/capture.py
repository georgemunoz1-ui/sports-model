import json,hashlib,urllib.request,concurrent.futures
from pathlib import Path
from datetime import datetime,timezone
p=Path(__file__).parent/'sources';p.mkdir(exist_ok=False)
base='https://site.api.espn.com/apis/site/v2/sports/football/college-football/'
jobs=[('history',base+'scoreboard?dates=20260801-20260911&groups=80&limit=1000'),('event',base+'summary?event=401856684')]
def fetch(j):
 k,u=j
 try:
  raw=urllib.request.urlopen(u,timeout=20).read();(p/(k+'.json')).write_bytes(raw)
  return dict(key=k,url=u,retrieved_at=datetime.now(timezone.utc).isoformat(),sha256=hashlib.sha256(raw).hexdigest(),ok=True)
 except Exception as e:return dict(key=k,url=u,ok=False,error=str(e))
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:r=list(ex.map(fetch,jobs))
s=json.load(open(p/'history.json'));ids=[]
for e in s['events']:
 c=e['competitions'][0]
 if c['status']['type']['completed']:ids.append(e['id'])
with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:r+=list(ex.map(fetch,[(i,base+'summary?event='+i) for i in ids]))
(p/'receipts.json').write_text(json.dumps(r,indent=2));print(len(ids),sum(x['ok'] for x in r),'success')
