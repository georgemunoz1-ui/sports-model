import csv, os, glob
from collections import defaultdict
BASE="data/backfill/mlb/2026"; WINDIR=f"{BASE}/_win"

# team full name -> abbreviation (authoritative, from statsapi)
abbr={}
for ln in open(f"{WINDIR}/teams_abbrev.txt"):
    ln=ln.strip()
    if ln: n,a=ln.split("|"); abbr[n]=a

# results.csv: gamePk -> (date, away_name, home_name, venue)
res={}
for r in csv.DictReader(open(f"{BASE}/results.csv")):
    pk=r["game_id"].split(":")[-1]; res[pk]=(r["date"],r["away"],r["home"],r["venue"])

WINS={
 "w01":("2026-03-25","2026-03-31"),"w02":("2026-04-01","2026-04-07"),"w03":("2026-04-08","2026-04-14"),
 "w04":("2026-04-15","2026-04-21"),"w05":("2026-04-22","2026-04-28"),"w06":("2026-04-29","2026-05-05"),
 "w07":("2026-05-06","2026-05-12"),"w08":("2026-05-13","2026-05-19"),"w09":("2026-05-20","2026-05-26"),
 "w10":("2026-05-27","2026-06-02"),"w11":("2026-06-03","2026-06-09"),"w12":("2026-06-10","2026-06-16"),
 "w13":("2026-06-17","2026-06-23"),"w14":("2026-06-24","2026-06-30"),"w15":("2026-07-01","2026-07-07"),
 "w16":("2026-07-08","2026-07-14"),"w17":("2026-07-15","2026-07-19"),
}
def win_of(date):
    for w,(s,e) in WINS.items():
        if s<=date<=e: return w
    return None

# gather all candidate starter tuples per gamePk, tagged by whether from the correct window
cands=defaultdict(list)   # gamePk -> list of (from_correct_window, (asp_id,asp_name,hsp_id,hsp_name))
for f in sorted(glob.glob(f"{WINDIR}/w??.txt")):
    wname=os.path.basename(f)[:-4]
    for ln in open(f):
        ln=ln.rstrip("\n")
        if not ln.strip(): continue
        p=(ln.split("|")+[""]*9)[:9]
        gp=p[0]
        if gp not in res: continue          # drop non-results gamePks (e.g. All-Star Game)
        sp=(p[5],p[6],p[7],p[8])
        cw=(win_of(res[gp][0])==wname)
        cands[gp].append((cw,sp))

# doubleheader partner map from results: (date,away,home) with >1 gamePk
grp=defaultdict(list)
for gp,(d,a,h,v) in res.items(): grp[(d,a,h)].append(gp)
partner={}
for key,pks in grp.items():
    if len(pks)==2:
        partner[pks[0]]=pks[1]; partner[pks[1]]=pks[0]

# optional authoritative override file (single-game fetch results): gamePk|date|away|home|aspid|aspname|hspid|hspname
override={}
rpath=f"{WINDIR}/resolve.txt"
if os.path.exists(rpath):
    for ln in open(rpath):
        ln=ln.strip()
        if not ln: continue
        p=ln.split("|")
        if len(p)>=8 and p[0] in res: override[p[0]]=(p[4],p[5],p[6],p[7])

def choose(gp):
    # 1) authoritative override wins
    if gp in override: return override[gp]
    cw=[sp for c,sp in cands[gp] if c]           # correct-window candidates
    other=[sp for c,sp in cands[gp] if not c]
    pool=cw or other
    uniq=list(dict.fromkeys(pool))
    if len(uniq)==1: return uniq[0]
    # 2) conflict: prefer the candidate sharing the FEWEST pitchers with the DH partner
    part=partner.get(gp)
    if part:
        psp=choose_simple(part)
        pset={psp[0],psp[2]}-{""}
        uniq.sort(key=lambda sp: len({sp[0],sp[2]} & pset))
    return uniq[0]                                # min-overlap, else deterministic first

def choose_simple(gp):
    cw=[sp for c,sp in cands[gp] if c] or [sp for c,sp in cands[gp] if not c]
    uniq=list(dict.fromkeys(cw))
    return uniq[0] if uniq else ("","","","")

# build starters.csv (one row per results gamePk, deduped by construction)
out=[]; unresolved=[]
for gp,(d,a,h,v) in res.items():
    sp=choose(gp)
    if len(list(dict.fromkeys([s for c,s in cands[gp]])))>1 and gp not in override:
        unresolved.append(gp)
    out.append((gp,d,abbr.get(a,a),abbr.get(h,h),v,sp[0],sp[1],sp[2],sp[3]))
out.sort(key=lambda x:(x[1],x[0]))
with open(f"{BASE}/starters.csv","w") as fo:
    fo.write("gamePk|date|away|home|venue|asp_id|asp_name|hsp_id|hsp_name\n")
    for o in out: fo.write("|".join(o)+"\n")

both=sum(1 for o in out if o[5] and o[7])
miss=sum(1 for o in out if not o[5] or not o[7])
print(f"starters.csv rows={len(out)} bothStarters={both} missing>=1={miss}")
print(f"conflicted gamePks resolved-by-heuristic (no override): {len(unresolved)} -> {sorted(unresolved)}")

# build pitchers.csv: distinct (id,name) from both starter columns
pit={}
for o in out:
    for i,n in ((o[5],o[6]),(o[7],o[8])):
        if i and i not in pit: pit[i]=n
with open(f"{BASE}/pitchers.csv","w") as fo:
    fo.write("id,name\n")
    for i,n in sorted(pit.items()): fo.write(f"{i},{n}\n")
print(f"pitchers.csv unique={len(pit)}")
