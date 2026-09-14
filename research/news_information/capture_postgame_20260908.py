import json,hashlib,datetime,pathlib,urllib.request
out=pathlib.Path("postgame-output");out.mkdir(exist_ok=True)
url="https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-09-08&hydrate=linescore"
with urllib.request.urlopen(url,timeout=40) as r: raw=r.read()
observed=datetime.datetime.now(datetime.timezone.utc).isoformat()
(out/"official_schedule.json").write_bytes(raw)
(out/"receipt.json").write_text(json.dumps({"url":url,"retrieved_at_utc":observed,"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"purpose":"POSTGAME_RESULTS_ONLY"},indent=2))
data=json.loads(raw)
print(json.dumps([{"id":g["gamePk"],"status":g["status"],"away":g["teams"]["away"],"home":g["teams"]["home"],"date":g["officialDate"]} for d in data["dates"] for g in d["games"]]))
