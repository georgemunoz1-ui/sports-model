import csv, os, glob
from collections import defaultdict, Counter
BASE="data/backfill/mlb/2026"; RAW=f"{BASE}/_win/raw"; LOGS=f"{BASE}/pitcher_logs"
os.makedirs(LOGS,exist_ok=True)

def readpipe(path):
    out=[]
    with open(path) as f:
        hdr=f.readline().rstrip("\n").split("|")
        for ln in f:
            p=ln.rstrip("\n").split("|")
            if len(p)==len(hdr): out.append(dict(zip(hdr,p)))
    return out

# pitcher id -> modal team abbrev (from starters.csv, which uses abbrevs)
pt=defaultdict(Counter)
for r in readpipe(f"{BASE}/starters.csv"):
    if r["asp_id"]: pt[r["asp_id"]][r["away"]]+=1
    if r["hsp_id"]: pt[r["hsp_id"]][r["home"]]+=1
pteam={pid:c.most_common(1)[0][0] for pid,c in pt.items()}

# team full name -> abbrev
abbr={}
for ln in open(f"{BASE}/_win/teams_abbrev.txt"):
    ln=ln.strip()
    if ln: n,a=ln.split("|"); abbr[n]=a

# results: (date, team_abbr) -> (opp_abbr, HA)
resg={}
for r in csv.DictReader(open(f"{BASE}/results.csv")):
    d=r["date"]; a=abbr.get(r["away"],r["away"]); h=abbr.get(r["home"],r["home"])
    resg[(d,a)]=(h,"A"); resg[(d,h)]=(a,"H")

conv=0
for f in sorted(glob.glob(f"{RAW}/*.raw")):
    pid=os.path.basename(f)[:-4]
    team=pteam.get(pid,"")
    seen=set(); lines=[]
    for ln in open(f):
        ln=ln.strip()
        if not ln or ln.upper().startswith("COUNT"): continue
        p=ln.split("|")
        if len(p)<8: continue
        date,ha,ip,er,so,bb,tbf,gs=p[0],p[1],p[2],p[3],p[4],p[5],p[6],p[7]
        if not (len(date)==10 and date[4]=="-"): continue
        if date in seen: continue
        seen.add(date)
        if (date,team) in resg: opp,HA=resg[(date,team)]
        else: opp,HA=("", "H" if ha.strip().upper().startswith("H") else "A")
        isStart="1" if gs.strip() in ("1","1.0") else "0"
        lines.append(f"{date}|{team}|{opp}|{HA}|{ip}|{er}|{so}|{bb}|{tbf}|{isStart}")
    lines.sort()
    with open(f"{LOGS}/{pid}.txt","w") as fo:
        fo.write("\n".join(lines)+("\n" if lines else ""))
    conv+=1
print(f"converted {conv} raw -> txt ; total cached txt: {len(glob.glob(f'{LOGS}/*.txt'))}")
