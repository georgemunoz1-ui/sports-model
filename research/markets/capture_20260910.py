import json,datetime,urllib.request,pathlib,hashlib
p=pathlib.Path("market-output");p.mkdir(exist_ok=True);receipt=[]
for league,sport,code in [("mlb","baseball","mlb"),("nfl","football","nfl"),("cfb","football","college-football"),("nba","basketball","nba"),("wnba","basketball","wnba"),("nhl","hockey","nhl"),("mls","soccer","usa.1")]:
 url="https://site.api.espn.com/apis/site/v2/sports/"+sport+"/"+code+"/scoreboard?dates=20260910&limit=1000"+("&groups=80" if league=="cfb" else "")
 with urllib.request.urlopen(url,timeout=40) as r:raw=r.read()
 (p/(league+".json")).write_bytes(raw)
 receipt.append(dict(league=league,url=url,observed_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),sha256=hashlib.sha256(raw).hexdigest()))
(p/"receipt.json").write_text(json.dumps(receipt,indent=2))
