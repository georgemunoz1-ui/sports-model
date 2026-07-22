import csv, sys, glob, os
BASE="data/backfill/mlb/2026"
rows=list(csv.DictReader(open(f"{BASE}/results.csv")))
def pk(r): return r["game_id"].split(":")[-1]
# map gamePk -> (date, away_name, home_name)
res={}
for r in rows:
    res[pk(r)]=(r["date"], r["away"], r["home"])
WINS={
 "w01":("2026-03-25","2026-03-31"),"w02":("2026-04-01","2026-04-07"),"w03":("2026-04-08","2026-04-14"),
 "w04":("2026-04-15","2026-04-21"),"w05":("2026-04-22","2026-04-28"),"w06":("2026-04-29","2026-05-05"),
 "w07":("2026-05-06","2026-05-12"),"w08":("2026-05-13","2026-05-19"),"w09":("2026-05-20","2026-05-26"),
 "w10":("2026-05-27","2026-06-02"),"w11":("2026-06-03","2026-06-09"),"w12":("2026-06-10","2026-06-16"),
 "w13":("2026-06-17","2026-06-23"),"w14":("2026-06-24","2026-06-30"),"w15":("2026-07-01","2026-07-07"),
 "w16":("2026-07-08","2026-07-14"),"w17":("2026-07-15","2026-07-19"),
}
targets=sys.argv[1:] or sorted(WINS)
for w in targets:
    path=f"{BASE}/_win/{w}.txt"
    if not os.path.exists(path):
        print(f"{w}: MISSING FILE"); continue
    s,e=WINS[w]
    expect={p for p,(d,a,h) in res.items() if s<=d<=e}
    lines=[l.rstrip("\n") for l in open(path) if l.strip()]
    mal=[l for l in lines if len(l.split("|"))!=9]
    if mal:
        for m in mal: print("   MALFORMED(",len(m.split('|')),"):", m)
    pks=[l.split("|")[0] for l in lines]
    dup=len(pks)-len(set(pks))
    # conflicting dupes: same gamePk, different starter tuple
    from collections import defaultdict
    byp=defaultdict(set)
    for l in lines:
        p=(l.split("|")+[""]*9)[:9]; byp[p[0]].add((p[5],p[6],p[7],p[8]))
    conflict=[g for g,v in byp.items() if len(v)>1]
    notin=[p for p in set(pks) if p not in res]
    missing=[p for p in expect if p not in set(pks)]
    # out-of-window: pk is a real results gamePk but its date is outside this window
    oow=[p for p in set(pks) if p in res and not (s<=res[p][0]<=e)]
    # team-name mismatch vs results (for gamePks that ARE in results)
    tmm=[]
    for l in lines:
        p=l.split("|")
        if p[0] in res:
            d,a,h=res[p[0]]
            if a!=p[2] or h!=p[3]: tmm.append(p[0])
    print(f"{w} [{s}..{e}] lines={len(lines)} expect={len(expect)} distinct={len(set(pks))} "
          f"mal={len(mal)} dup={dup} conflictDupe={len(conflict)} notInResults={len(notin)} "
          f"missing={len(missing)} teamMismatch={len(set(tmm))} outOfWin={len(oow)}")
    if oow: print("   outOfWindow:", [(p,res[p][0]) for p in oow][:8])
    if notin: print("   notInResults:", notin[:8])
    if missing: print("   missing:", missing[:8])
    if conflict: print("   conflictDupe:", conflict[:8])
    if tmm: print("   teamMismatch:", list(set(tmm))[:8])
