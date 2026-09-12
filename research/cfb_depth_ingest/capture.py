import pathlib,urllib.request,json,hashlib,datetime,concurrent.futures
root=pathlib.Path(__file__).parent
urls={'washington_notes':'https://s3.us-east-2.amazonaws.com/sidearm.nextgen.sites/washington.sidearmsports.com/documents/2026/9/7/FBRel_2026_2_USU.pdf','utah_state_notes':'https://gohuskies.com/documents/download/2026/9/7/2._Utah_State_Football_Game_Notes_vs._Washington.pdf','event':'https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event=401858446'}
def fetch(k):
 b=urllib.request.urlopen(urls[k],timeout=20).read();f=root/(k+('.json' if k=='event' else '.pdf'));f.write_bytes(b);return {'name':f.name,'url':urls[k],'retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:r=list(ex.map(fetch,urls))
(root/'receipts.json').write_text(json.dumps(r,indent=2));print(r)
