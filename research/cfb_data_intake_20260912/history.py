import json,urllib.request,hashlib,concurrent.futures,calendar,gzip
from pathlib import Path
from datetime import datetime,timezone
p=Path(__file__).parent/'history';p.mkdir(exist_ok=False)
jobs=[]
for season in range(2020,2026):
 for year,month in [(season,m) for m in range(8,13)]+[(season+1,1)]:
  for group in [80,81]:
   key=f'{season}_{year}{month:02}_{group}';dates=f'{year}{month:02}01-{year}{month:02}{calendar.monthrange(year,month)[1]}'
   jobs.append((key,f'https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates={dates}&groups={group}&limit=1000'))
def fetch(job):
 k,u=job
 try:
  raw=urllib.request.urlopen(u,timeout=20).read();b=json.loads(raw);events=b.get('events',[]);(p/(k+'.json.gz')).write_bytes(gzip.compress(raw,mtime=0));return {'key':k,'url':u,'retrieved_at':datetime.now(timezone.utc).isoformat(),'sha256':hashlib.sha256(raw).hexdigest(),'ok':True,'events':len(events),'possible_truncation':len(events)>=1000}
 except Exception as e:return {'key':k,'url':u,'ok':False,'error':str(e)}
with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:receipts=list(ex.map(fetch,jobs))
(p/'receipts.json').write_text(json.dumps(receipts,indent=2));print('requests',len(jobs),'success',sum(r['ok'] for r in receipts))
