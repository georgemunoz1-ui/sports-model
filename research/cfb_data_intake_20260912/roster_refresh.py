import json,urllib.request,hashlib,concurrent.futures
from pathlib import Path
from datetime import datetime,timezone
p=Path(__file__).parent/'rosters_complete';p.mkdir(exist_ok=False)
ids=[f.name.split('_')[0] for f in Path('cfb_live_2139').glob('*_roster.json')]
def fetch(t):
 u=f'https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{t}/roster?season=2026&limit=1000'
 try:
  b=urllib.request.urlopen(u,timeout=20).read();d=json.loads(b);(p/f'{t}_roster.json').write_bytes(b);n=sum(len(x.get('items',[])) for x in d.get('athletes',[]));return dict(key=t+'_roster',url=u,sha256=hashlib.sha256(b).hexdigest(),retrieved_at=datetime.now(timezone.utc).isoformat(),ok=True,player_count=n,completeness='UNVERIFIED_AGAINST_OFFICIAL_ROSTER',possible_truncation=n>=1000)
 except Exception as e:return dict(key=t+'_roster',url=u,ok=False,error=str(e))
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:r=list(ex.map(fetch,ids))
(p/'receipts.json').write_text(json.dumps(r,indent=2));print('success',sum(x['ok'] for x in r),'players',sum(x.get('player_count',0) for x in r))
