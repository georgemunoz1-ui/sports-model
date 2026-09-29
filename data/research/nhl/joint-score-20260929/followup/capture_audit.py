import concurrent.futures as cf,json,pathlib,urllib.request,datetime,hashlib,gzip,re
P=pathlib.Path(__file__).resolve().parent; A=json.load(open(P.parent/'nhl-joint-20260929-v1/audit-predictions.json'));D=P/'pbp';D.mkdir(exist_ok=True)
def job(r):
 eid=r['event_id'].split(':')[1];u='https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/summary?event='+eid
 rec={'event_id':r['event_id'],'url':u,'retrieved_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'used_as_model_input':False}
 try:
  b=urllib.request.urlopen(u,timeout=25).read();(D/(eid+'.json.gz')).write_bytes(gzip.compress(b,mtime=0));rec['sha256']=hashlib.sha256(b).hexdigest();j=json.loads(b);c=j['header']['competitions'][0];s={x['homeAway']:int(x['score'])for x in c['competitors']};plays=j.get('plays',[]);goals=[x for x in plays if x.get('scoringPlay') and x.get('period',{}).get('number',99)<=4];expected=sum(r['outcome'][2:4])-(r['phase']=='SO');rec['score_reconciles']=s==dict(home=r['outcome'][2],away=r['outcome'][3]);rec['goal_census_reconciles']=len(goals)==expected;rec['complete']=bool(plays) and rec['score_reconciles'] and rec['goal_census_reconciles'] and c['status']['type']['completed'];matches=[x for x in goals if re.search(r'empty[ -]?net',json.dumps(x),re.I)];rec['explicit_empty_net_goals']=len(matches);rec['empty_net_status']='EXPLICIT_POSITIVE' if matches else 'NO_EXPLICIT_MARKER' if rec['complete'] else 'UNKNOWN';rec['marker_evidence']=[{'play_id':x['id'],'text':x['text']}for x in matches];rec['status']='CAPTURED'
 except Exception as e:rec.update(status='FAILED',error=str(e),empty_net_status='UNKNOWN')
 return rec
with cf.ThreadPoolExecutor(max_workers=12)as ex:
 out=list(ex.map(job,A))
(P/'empty-net-labels.json').write_text(json.dumps(out,indent=2));print(json.dumps({'captured':sum(r['status']=='CAPTURED'for r in out),'complete':sum(r.get('complete',False)for r in out),'explicit_positive':sum(r.get('empty_net_status')=='EXPLICIT_POSITIVE'for r in out),'n':len(out)}),flush=True)
