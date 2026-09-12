import urllib.request,concurrent.futures,hashlib,json,subprocess
from pathlib import Path
from datetime import datetime,timezone
from html.parser import HTMLParser
class TextParser(HTMLParser):
 def __init__(self):super().__init__();self.parts=[]
 def handle_data(self,data):self.parts.append(data)
def htmltext(raw):
 parser=TextParser();parser.feed(raw.decode("utf-8",errors="replace"));return " ".join(parser.parts)
p=Path(__file__).parent/'official';p.mkdir(exist_ok=False)
jobs=[('texas_notes','https://texaslonghorns.com/documents/download/2026/9/7/02_-_OSU.pdf'),('gt_notes','https://utsports.com/documents/download/2026/9/8/2026_GT_FB_Game_Notes__Tenn_.pdf'),('gt_depth','https://ramblinwreck.com/documents/13c1d72d-fb59-4794-bdcf-49bcd9ce4fbe.pdf'),('tennessee_notes','https://ramblinwreck.com/documents/e08bfc77-1f84-4d21-a36f-3b8c85f2a24a.pdf'),('iowa_notes','https://hawkeyesports.com/news/2026/09/7/notes-iowa-corn-cy-hawk-series-vs-iowa-state090726'),('tennessee_updates','https://utsports.com/news/2026/9/7/football-carters-return-adds-to-excitement-for-primetime-matchup-at-georgia-tech'),('texas_game','https://texaslonghorns.com/game-center/22495'),('isu_roster','https://cyclones.com/sports/football/roster/raynor-jaylen/14403')]
def fetch(j):
 k,u=j
 try:
  req=urllib.request.Request(u,headers={'User-Agent':'SportsResearch contact research@example.com'})
  raw=urllib.request.urlopen(req,timeout=20).read();pdf=raw.startswith(b'%PDF');name=k+('.pdf' if pdf else '.html');(p/name).write_bytes(raw)
  if pdf:subprocess.run(['pdftotext','-layout',str(p/name),str(p/(k+'.txt'))],check=True)
  else:(p/(k+'.txt')).write_text(htmltext(raw))
  return {'key':k,'url':u,'path':name,'retrieved_at':datetime.now(timezone.utc).isoformat(),'sha256':hashlib.sha256(raw).hexdigest(),'ok':True,'pdf':pdf}
 except Exception as e:return {'key':k,'url':u,'ok':False,'error':str(e)}
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:r=list(ex.map(fetch,jobs))
(p/'receipts.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))
