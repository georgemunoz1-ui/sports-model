"""Ingest a pipe-delimited raw file into canonical MLB results.csv (idempotent, de-duped).
Raw line format: date|gamePk|away|home|away_score|home_score|status|venue   (scores blank if none)
Usage: python3 sports/ingest_mlb.py <rawfile>
"""
import sys, os, datetime
sys.path.insert(0, os.path.dirname(__file__))
import schema
OUT = "data/backfill/mlb/2026/results.csv"
def norm_status(s):
    s=(s or "").strip().lower()
    if "final" in s or "completed" in s: return "final"
    if "postpon" in s: return "postponed"
    if "suspend" in s: return "suspended"
    if "cancel" in s: return "postponed"
    return "scheduled"
def run(rawfile):
    rows=[]; now=datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    for ln in open(rawfile):
        ln=ln.strip()
        if not ln or ln.startswith("#") or ln.lower().startswith("date|"): continue
        p=[x.strip() for x in ln.split("|")]
        if len(p)<6: continue
        date,pk,away,home=p[0],p[1],p[2],p[3]
        asc=p[4] if len(p)>4 and p[4] not in ("","-","None") else None
        hsc=p[5] if len(p)>5 and p[5] not in ("","-","None") else None
        status=norm_status(p[6] if len(p)>6 else "final")
        venue=p[7] if len(p)>7 else ""
        rows.append(schema.make_row("mlb",2026,f"mlb:2026:{pk}",date,status,away,home,
            asc,hsc,venue=venue,source="statsapi",ingested_utc=now))
    added,dup=schema.append_rows(OUT,rows)
    v=schema.verify_file(OUT)
    print(f"ingested {rawfile}: +{added} new, {dup} dupes | file now {v['finals']} finals / {v['rows']} rows | span {v['date_min']}..{v['date_max']} | postponed {v['postponed']} | dupe_ids {v['dupe_ids']}")
if __name__=="__main__": run(sys.argv[1])
