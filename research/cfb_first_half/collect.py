import argparse
import json,pathlib,urllib.request,concurrent.futures,datetime,time
parser=argparse.ArgumentParser();parser.add_argument('--state',required=True);args=parser.parse_args()
out=pathlib.Path(__file__).parent/'sources';out.mkdir(exist_ok=False)
s=json.load(open(args.state))
def get(eid):
 url='https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event='+eid
 try:
  b=urllib.request.urlopen(url,timeout=18).read();(out/(eid+'.json')).write_bytes(b)
  return {'event_id':eid,'url':url,'retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'ok':True}
 except Exception as e:return {'event_id':eid,'ok':False,'error':str(e)}
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:r=list(ex.map(get,[x['event_id'] for x in s['updates']]))
(out/'receipts.json').write_text(json.dumps(r,indent=2));print('received',sum(x['ok'] for x in r),'of',len(r))
