import json,hashlib,datetime,pathlib,urllib.request,subprocess,sys
out=pathlib.Path("prep-output");out.mkdir(exist_ok=True)
receipts=[]; failures=[]
def capture(label,url):
 try:
  with urllib.request.urlopen(url,timeout=40) as r: raw=r.read()
  (out/(label+".json")).write_bytes(raw)
  receipts.append(dict(label=label,url=url,retrieved_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)))
  return json.loads(raw)
 except Exception as e: failures.append(dict(label=label,error=str(e)));return {}
for league,sport,code in [("mlb","baseball","mlb"),("nfl","football","nfl"),("cfb","football","college-football"),("nba","basketball","nba"),("wnba","basketball","wnba"),("nhl","hockey","nhl"),("mls","soccer","usa.1")]:
 capture(league+"_schedule","https://site.api.espn.com/apis/site/v2/sports/"+sport+"/"+code+"/scoreboard?dates=20260910&limit=1000"+("&groups=80" if league=="cfb" else ""))
for date in ("2026-09-08","2026-09-09"):
 data=capture("mlb_"+date,"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date="+date)
 for d in data.get("dates",[]):
  for g in d["games"]:capture("box_"+str(g["gamePk"]),"https://statsapi.mlb.com/api/v1/game/"+str(g["gamePk"])+"/boxscore")
(out/"receipts.json").write_text(json.dumps(receipts,indent=2))
(out/"capture_failures.json").write_text(json.dumps(failures,indent=2))
for league in ("mlb","cfb"):
 cutoff=datetime.datetime.now(datetime.timezone.utc).isoformat()
 p=subprocess.run([sys.executable,"scripts/generate_card_force.py","--date","2026-09-10","--league",league,"--as-of-utc",cutoff,"--simulations","100000","--output-dir",str(out/league)],capture_output=True,text=True)
 (out/(league+"_generator.log")).write_text(p.stdout+"\n"+p.stderr)
 (out/(league+"_execution.json")).write_text(json.dumps(dict(exit_code=p.returncode,requested_cutoff=cutoff,action_authority=False)))
manifest={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob("*") if p.is_file()}
(out/"manifest.json").write_text(json.dumps(manifest,indent=2))
