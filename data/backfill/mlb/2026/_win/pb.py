import csv, os, glob, sys, json
from collections import defaultdict, Counter
BASE="data/backfill/mlb/2026"; RAW=f"{BASE}/_win/raw"; LOGS=f"{BASE}/pitcher_logs"
os.makedirs(RAW,exist_ok=True); os.makedirs(LOGS,exist_ok=True)

def readpipe(path):
    out=[]
    with open(path) as f:
        hdr=f.readline().rstrip("\n").split("|")
        for ln in f:
            p=ln.rstrip("\n").split("|")
            if len(p)==len(hdr): out.append(dict(zip(hdr,p)))
    return out

S=readpipe(f"{BASE}/starters.csv")
pt=defaultdict(Counter); startdates=defaultdict(set)
for r in S:
    if r["asp_id"]: pt[r["asp_id"]][r["away"]]+=1; startdates[r["asp_id"]].add(r["date"])
    if r["hsp_id"]: pt[r["hsp_id"]][r["home"]]+=1; startdates[r["hsp_id"]].add(r["date"])
pteam={pid:c.most_common(1)[0][0] for pid,c in pt.items()}
abbr={}
for ln in open(f"{BASE}/_win/teams_abbrev.txt"):
    ln=ln.strip()
    if ln: n,a=ln.split("|"); abbr[n]=a
resg={}
for r in csv.DictReader(open(f"{BASE}/results.csv")):
    d=r["date"]; a=abbr.get(r["away"],r["away"]); h=abbr.get(r["home"],r["home"])
    resg[(d,a)]=(h,"A"); resg[(d,h)]=(a,"H")

def isdate(d): return len(d)==10 and d[4]=="-"

# 1) split batch file: sections "@@A id" (date|IP|ER|SO|GS), "@@B id" (date|BB|TBF), "@@F id" (date|HA|IP|ER|SO|BB|TBF|GS)
if len(sys.argv)>1 and os.path.exists(sys.argv[1]):
    cur=None; typ=None; buf=defaultdict(list)
    for ln in open(sys.argv[1]):
        s=ln.rstrip("\n")
        if s.startswith("@@"):
            parts=s[2:].split(); typ=parts[0]; cur=parts[1]; continue
        if cur and s.strip() and not s.upper().startswith("COUNT"):
            ext={"A":"a","B":"b","F":"raw"}[typ]
            buf[(cur,ext)].append(s)
    for (pid,ext),ls in buf.items():
        with open(f"{RAW}/{pid}.{ext}","a") as fo: fo.write("\n".join(ls)+"\n")

# 2) convert: merge per-pitcher stats by date from .a/.b/.raw ; emit full 10-field lines
ids=set(os.path.basename(f).rsplit(".",1)[0] for f in glob.glob(f"{RAW}/*.a")+glob.glob(f"{RAW}/*.b")+glob.glob(f"{RAW}/*.raw"))
for pid in ids:
    team=pteam.get(pid,"")
    st=defaultdict(dict)   # date -> {ip,er,so,bb,tbf,gs}
    p=f"{RAW}/{pid}.raw"
    if os.path.exists(p):
        for ln in open(p):
            q=ln.strip().split("|")
            if len(q)>=8 and isdate(q[0]):
                st[q[0]].update(ip=q[2],er=q[3],so=q[4],bb=q[5],tbf=q[6],gs=q[7])
    p=f"{RAW}/{pid}.a"
    if os.path.exists(p):
        for ln in open(p):
            q=ln.strip().split("|")
            if len(q)>=5 and isdate(q[0]):
                st[q[0]].update(ip=q[1],er=q[2],so=q[3],gs=q[4])
    p=f"{RAW}/{pid}.b"
    if os.path.exists(p):
        for ln in open(p):
            q=ln.strip().split("|")
            if len(q)>=3 and isdate(q[0]):
                st[q[0]].update(bb=q[1],tbf=q[2])
    lines=[]
    for date in sorted(st):
        d=st[date]
        if not all(k in d for k in ("ip","er","so","bb","tbf","gs")): continue
        if (date,team) in resg: opp,HA=resg[(date,team)]
        else: opp,HA=("","")
        isStart="1" if str(d["gs"]).strip() in ("1","1.0") else "0"
        lines.append(f"{date}|{team}|{opp}|{HA}|{d['ip']}|{d['er']}|{d['so']}|{d['bb']}|{d['tbf']}|{isStart}")
    if lines:
        with open(f"{LOGS}/{pid}.txt","w") as fo: fo.write("\n".join(lines)+"\n")

# 3) validate vs known start dates
cached=sorted(os.path.basename(f)[:-4] for f in glob.glob(f"{LOGS}/*.txt"))
incomplete=[]
for pid in cached:
    logdates={ln.split("|")[0] for ln in open(f"{LOGS}/{pid}.txt") if isdate(ln.split("|")[0])}
    miss=sorted(startdates.get(pid,set())-logdates)
    if miss: incomplete.append((pid,max(logdates) if logdates else "none",len(miss),miss[-1]))
complete=[c for c in cached if c not in {i[0] for i in incomplete}]
print(f"cached txt: {len(cached)} | COMPLETE: {len(complete)} | incomplete: {len(incomplete)}")
for pid,last,nm,lm in incomplete[:50]: print(f"  INC {pid} lastlog={last} missStarts={nm} lastMiss={lm}")
try:
    m=json.load(open(f"{BASE.split('/mlb')[0]}/manifest.json"))
    m["sports"]["mlb"]["enrich"]["logs_cached"]=len(complete)
    m["sports"]["mlb"]["enrich"]["logs_partial"]=len(incomplete)
    json.dump(m,open(f"{BASE.split('/mlb')[0]}/manifest.json","w"),indent=1)
except Exception as e: print("manifest skip:",e)
