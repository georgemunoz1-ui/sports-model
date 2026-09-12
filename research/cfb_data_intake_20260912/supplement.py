import json,urllib.request,hashlib,concurrent.futures,calendar,gzip,re,subprocess
from pathlib import Path
from datetime import datetime,timezone
p=Path(__file__).parent
jobs=[]
for month in range(2,6):
 for group in [80,81]:
  jobs.append((f'history/spring2021_{month}_{group}',f'https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates=2021{month:02}01-2021{month:02}{calendar.monthrange(2021,month)[1]}&groups={group}&limit=1000','json.gz'))
for name in ['gt_depth','tennessee_notes','iowa_notes']:
 s=(p/'official'/f'{name}.html').read_text();u=re.search(r'https://storage.googleapis.com/[^\s"<>]+\.pdf',s).group();jobs.append(('official/'+name+'_resolved',u,'pdf'))
def fetch(j):
 k,u,ext=j
 try:
  raw=urllib.request.urlopen(u,timeout=25).read();dest=p/(k+'.'+ext)
  if ext=='json.gz':
   d=json.loads(raw);dest.write_bytes(gzip.compress(raw,mtime=0));n=len(d.get('events',[]))
  else:
   assert raw.startswith(b'%PDF');dest.write_bytes(raw);subprocess.run(['pdftotext','-layout',str(dest),str(dest.with_suffix('.txt'))],check=True);n=None
  return dict(key=k,url=u,retrieved_at=datetime.now(timezone.utc).isoformat(),sha256=hashlib.sha256(raw).hexdigest(),ok=True,events=n)
 except Exception as e:return dict(key=k,url=u,ok=False,error=str(e))
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:r=list(ex.map(fetch,jobs))
(p/'supplement_receipts.json').write_text(json.dumps(r,indent=2));print([(x['key'],x['ok'],x.get('events')) for x in r])
