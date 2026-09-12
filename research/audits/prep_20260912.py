import json,hashlib,datetime,pathlib,urllib.request,subprocess,sys,concurrent.futures
out=pathlib.Path("prep-20260912-output");out.mkdir(exist_ok=False)
def capture(item):
 date,league,sport,code=item
 url=f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{code}/scoreboard?dates={date.replace('-','')}&limit=1000"+("&groups=80" if league=="cfb" else "")
 try:
  raw=urllib.request.urlopen(url,timeout=45).read()
  path=f"{date}_{league}.json";(out/path).write_bytes(raw)
  return dict(path=path,url=url,retrieved_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),sha256=hashlib.sha256(raw).hexdigest())
 except Exception as e:return dict(date=date,league=league,error=str(e))
leagues=[("mlb","baseball","mlb"),("cfb","football","college-football"),("nfl","football","nfl"),("nba","basketball","nba"),("wnba","basketball","wnba"),("nhl","hockey","nhl"),("mls","soccer","usa.1")]
receipts=list(concurrent.futures.ThreadPoolExecutor(8).map(capture,[(d,*l) for d in ["2026-09-11","2026-09-12"] for l in leagues]))
(out/"receipts.json").write_text(json.dumps(receipts,indent=2))
for league in ["mlb","cfb"]:
 cutoff=datetime.datetime.now(datetime.timezone.utc).isoformat()
 p=subprocess.run([sys.executable,"scripts/generate_card_force.py","--date","2026-09-12","--league",league,"--as-of-utc",cutoff,"--simulations","100000","--output-dir",str(out/league)],capture_output=True,text=True)
 (out/(league+"_execution.json")).write_text(json.dumps(dict(exit_code=p.returncode,cutoff=cutoff,stdout=p.stdout,stderr=p.stderr)))
for f in ["AGENTS.md","state.json","docs/progress.md","data/cfb/source/2026-09-03_cfb_schedule.csv","data/models/cfb/cfb_margin_model_state_v1.json"]:
 p=pathlib.Path(f)
 if p.exists():
  dest=out/"code_inputs"/f;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes())
(out/"manifest.json").write_text(json.dumps({str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob("*") if p.is_file()},indent=2))
