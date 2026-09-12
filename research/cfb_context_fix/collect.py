import argparse
import pathlib,json,csv,urllib.request,datetime,concurrent.futures,hashlib
parser=argparse.ArgumentParser();parser.add_argument('--identities',default=str(pathlib.Path(__file__).parent.parent/'cfb_empirical_margin/run_02/identities.csv'));parser.add_argument('--output',required=True);args=parser.parse_args();root=pathlib.Path(args.output);root.mkdir(exist_ok=False)
base='https://site.api.espn.com/apis/site/v2/sports/football/college-football/'
def fetch(key,url):
 t=datetime.datetime.now(datetime.timezone.utc).isoformat()
 try:
  b=urllib.request.urlopen(url,timeout=18).read();(root/(key+'.json')).write_bytes(b);return {'key':key,'url':url,'retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'sha256':hashlib.sha256(b).hexdigest(),'ok':True}
 except Exception as e:return {'key':key,'url':url,'attempted_at':t,'ok':False,'error':str(e)}
sr=fetch('schedule',base+'scoreboard?dates=20260912-20260912&groups=80&limit=1000');events=json.load(open(root/'schedule.json'))['events'];ids={}
for r in csv.DictReader(open(args.identities)):
 for side in ['home','away']:ids[r[side+'_id']]=r[side+'_division']
teams=set()
for e in events:
 c=e['competitions'][0]
 if c['status']['type']['state']=='pre' and all(ids.get(x['id'])=='fbs' for x in c['competitors']):teams.update(x['id'] for x in c['competitors'])
jobs=[(t+'_'+kind,base+'teams/'+t+'/'+kind+'?season=2026') for t in sorted(teams) for kind in ['roster','statistics','depthcharts']]
with concurrent.futures.ThreadPoolExecutor(max_workers=14) as ex: receipts=[sr]+list(ex.map(lambda j:fetch(*j),jobs))
(root/'receipts.json').write_text(json.dumps(receipts,indent=2));print('teams',len(teams),'receipts',len(receipts),'success',sum(x['ok'] for x in receipts))
