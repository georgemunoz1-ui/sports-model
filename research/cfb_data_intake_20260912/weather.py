import urllib.request,json,hashlib,concurrent.futures
from pathlib import Path
from datetime import datetime,timezone
p=Path(__file__).parent/'weather';p.mkdir(exist_ok=True)
def get(k,lat,lon):
 out=[]
 for suffix,u in [('point',f'https://api.weather.gov/points/{lat},{lon}')]:
  try:
   req=urllib.request.Request(u,headers={'User-Agent':'sports-model-research (diagnostic forecast)'});b=urllib.request.urlopen(req,timeout=15).read();(p/f'{k}_{suffix}.json').write_bytes(b);out.append(dict(key=k+'_'+suffix,url=u,sha256=hashlib.sha256(b).hexdigest(),retrieved_at=datetime.now(timezone.utc).isoformat(),ok=True));url=json.loads(b)['properties']['forecastHourly'];b=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'sports-model-research'}),timeout=15).read();(p/f'{k}_hourly.json').write_bytes(b);out.append(dict(key=k+'_hourly',url=url,sha256=hashlib.sha256(b).hexdigest(),retrieved_at=datetime.now(timezone.utc).isoformat(),ok=True))
  except Exception as e:out.append(dict(key=k,url=u,ok=False,error=str(e)))
 return out
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:r=sum(ex.map(lambda x:get(*x),[('austin',30.2849,-97.7325),('atlanta',33.7725,-84.3928),('iowa_city',41.6587,-91.5511)]),[])
(p/'receipts.json').write_text(json.dumps(r,indent=2));print([(x['key'],x['ok']) for x in r])
