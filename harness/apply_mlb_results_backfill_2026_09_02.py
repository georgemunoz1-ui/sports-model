#!/usr/bin/env python3
"""Apply the 2026-08-24..2026-09-02 official MLB result backfill.

Tier-1 MLB.com evidence may replace an existing non-final/unscored schedule row
with the same stable gamePk (schedule-date shifts). Conflicting existing finals
remain a hard failure. Running twice is byte-idempotent.
"""
from __future__ import annotations
import argparse,csv,hashlib,io,json
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
RESULTS=BASE/'data/backfill/mlb/2026/results.csv'
EVIDENCE=[BASE/'data/mlb/evidence/backfill_2026-08-24.json',BASE/'data/mlb/evidence/backfill_2026-08-25_2026-09-01.json',BASE/'data/mlb/evidence/backfill_2026-09-02.json']
INGESTED_UTC='2026-09-03T07:15:00Z'; EXPECTED_START='2026-08-24'; EXPECTED_END='2026-09-02'; EXPECTED_NEW_GAMES=135
IDENTITY_FIELDS=('date','away','home','away_score','home_score','home_win','margin','total')
def sha256_bytes(b): return hashlib.sha256(b).hexdigest()
def load_evidence():
    games=[]; seen=set()
    for path in EVIDENCE:
        raw=path.read_bytes(); p=json.loads(raw); inherited=p.get('date'); assert p.get('source_tier')==1
        for x in p['games']:
            g=dict(x); g['date']=g.get('date') or inherited; g['evidence_path']=str(path.relative_to(BASE)); g['evidence_sha256']=sha256_bytes(raw)
            gid=str(g['gamePk']); assert gid.isdigit() and gid not in seen; seen.add(gid); assert gid in g['official_url'] and g['official_url'].startswith('https://www.mlb.com/gameday/')
            a,h=int(g['away_score']),int(g['home_score']); assert a!=h; assert g['winner']==(g['home'] if h>a else g['away']); games.append(g)
    ds=[g['date'] for g in games]; assert min(ds)==EXPECTED_START and max(ds)==EXPECTED_END and len(games)==EXPECTED_NEW_GAMES
    return games
def canonical_row(g,fields):
    a,h=int(g['away_score']),int(g['home_score']); v={'sport':'mlb','season':'2026','game_id':f"mlb:2026:{g['gamePk']}",'date':g['date'],'status':'final','away':g['away'],'home':g['home'],'away_score':str(a),'home_score':str(h),'home_win':'1' if h>a else '0','margin':str(h-a),'total':str(h+a),'neutral_site':str(int(g.get('neutral_site',0))),'venue':g['venue'],'close_ml_away':'','close_ml_home':'','close_spread_home':'','close_total':'','features_json':'','source':'MLB.com Gameday','ingested_utc':INGESTED_UTC,'source_tier':'1','result_status':'FINAL','evidence_path':g['evidence_path'],'evidence_sha256':g['evidence_sha256']}
    assert set(fields)==set(v),(set(fields)-set(v),set(v)-set(fields)); return {k:v[k] for k in fields}
def render(apply):
    with RESULTS.open(newline='',encoding='utf-8') as f: rd=csv.DictReader(f); fields=rd.fieldnames; rows=list(rd)
    assert fields; assert len(rows)==len({r['game_id'] for r in rows})
    generated=[canonical_row(g,fields) for g in load_evidence()]; byid={r['game_id']:r for r in rows}; additions=[]; replacements={}; overlaps=[]; conflicts=[]
    for new in generated:
        gid=new['game_id']; old=byid.get(gid)
        if old is None: additions.append(new); continue
        diffs={k:{'existing':old[k],'official':new[k]} for k in IDENTITY_FIELDS if old[k]!=new[k]}
        if not diffs: overlaps.append(gid); continue
        # Stable gamePk existed only as a schedule placeholder: official Tier-1 final supersedes it.
        if old.get('status')!='final' and old.get('away_score','')=='' and old.get('home_score','')=='': replacements[gid]=new
        else: conflicts.append({'game_id':gid,'existing_status':old.get('status'),'diffs':diffs})
    if conflicts: print(json.dumps({'status':'CONFLICT','conflicts':conflicts},sort_keys=True)); raise SystemExit(2)
    merged=[replacements.get(r['game_id'],r) for r in rows]+additions; merged.sort(key=lambda r:(r['date'],r['game_id']))
    assert len(merged)==len({r['game_id'] for r in merged}); assert max(r['date'] for r in merged if r['status']=='final')==EXPECTED_END
    b=io.StringIO(newline=''); w=csv.DictWriter(b,fieldnames=fields,lineterminator='\n'); w.writeheader(); w.writerows(merged); out=b.getvalue()
    print(json.dumps({'base_rows':len(rows),'evidence_games':len(generated),'existing_verified_overlaps':len(overlaps),'scheduled_rows_replaced':len(replacements),'new_rows':len(additions),'merged_rows':len(merged),'max_final_date':EXPECTED_END,'output_sha256':hashlib.sha256(out.encode()).hexdigest(),'mode':'apply' if apply else 'check'},sort_keys=True))
    if apply: RESULTS.write_text(out,encoding='utf-8',newline='')
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--apply',action='store_true'); a=p.parse_args(); render(a.apply)
