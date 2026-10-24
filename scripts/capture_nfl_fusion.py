#!/usr/bin/env python3
"""Research acquisition/build. Preserves raw sources; does not issue live forecasts."""
from __future__ import annotations
import argparse,concurrent.futures,datetime as dt,hashlib,importlib.metadata,json,os,pathlib,shutil,subprocess,sys,tarfile,urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from models.nfl.contextual import base_features as bf
from models.nfl.contextual.features import build_history
from models.nfl.contextual.model import fit,predict_frame,FAMILIES

def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def save(p,x):
    p=pathlib.Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:json.dump(x,f,indent=2,allow_nan=False)
def capture(job):
    path,url=job;record={'path':str(path),'source_url':url,'requested_at_utc':now()}
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'sports-model-source-research'}),timeout=120) as r:raw=r.read();headers=dict(r.headers)
        with path.open('xb') as f:f.write(raw)
        record.update(status='CAPTURED',sha256=sha(path),bytes=len(raw),headers=headers,retrieved_at_utc=now(),publication_time_verified=False)
    except Exception as exc:record.update(status='FAILED',error=repr(exc),retrieved_at_utc=now())
    return record

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--candidate-root',type=pathlib.Path,required=True);ap.add_argument('--output',type=pathlib.Path,required=True);a=ap.parse_args()
    out=a.output;out.mkdir(parents=True,exist_ok=False);raw=out/'raw';raw.mkdir();candidate=a.candidate_root
    protocol=json.loads((ROOT/'research/nfl_fusion/protocol.json').read_text());save(out/'protocol.json',protocol)
    save(out/'execution.json',{'started_at_utc':now(),'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'protocol_sha256':sha(out/'protocol.json'),'mode':'RETROSPECTIVE_RECONSTRUCTION_NOT_HISTORICAL_PIT_CERTIFICATION','action_authority':False})
    with (out/'code.tar.gz').open('xb') as f:subprocess.run(['git','archive','--format=tar.gz','HEAD'],cwd=ROOT,stdout=f,check=True)
    with tarfile.open(candidate/'data/research/candidate_methods_v1/sources.tar.gz') as t:t.extractall(raw/'candidate',filter='data')
    subprocess.run([sys.executable,'-m','research.candidate_methods.replay','data/research/candidate_methods_v1/verified_20260916'],cwd=candidate,check=True)
    shutil.copytree(candidate/'data/research/candidate_methods_v1/verified_20260916',out/'candidate_verified')
    shutil.copytree(candidate/'research/candidate_methods',out/'candidate_code')
    allgames=list((raw/'candidate').rglob('games.csv'));assert len(allgames)==1,'CANDIDATE_SCHEDULE_NOT_UNIQUE'
    games=pd.read_csv(allgames[0],low_memory=False);games=games[(games.game_type=='REG')&games.season.between(2015,2024)].copy()
    for c in ('home_team','away_team'):games[c]=games[c].replace(bf.TEAM_ALIASES)
    assert not games.game_id.duplicated().any()
    jobs=[]
    for y in range(2015,2025):
        for kind,name in [('pbp',f'play_by_play_{y}.csv.gz'),('injuries',f'injuries_{y}.csv'),('snap_counts',f'snap_counts_{y}.csv')]:jobs.append((raw/name,'https://github.com/nflverse/nflverse-data/releases/download/'+kind+'/'+name))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:receipts=list(pool.map(capture,jobs))
    save(out/'raw_source_receipts.json',receipts)
    if any(r['status']!='CAPTURED' for r in receipts):raise ValueError('HISTORICAL_SOURCE_CAPTURE_FAILED')
    parts=[];qbs=[]
    qcols={'passer_player_id','qb_dropback'};cols=set(bf.PBP_REQUIRED)|qcols
    for y in range(2015,2025):
        p=pd.read_csv(raw/f'play_by_play_{y}.csv.gz',usecols=lambda c:c in cols,low_memory=False)
        if 'no_play' not in p:p['no_play']=p.play_type.astype('string').str.lower().eq('no_play').fillna(False).astype('int8')
        for c in ('posteam','defteam'):p[c]=p[c].replace(bf.TEAM_ALIASES)
        p=p[(p.season_type=='REG')&p.game_id.isin(games.game_id)].copy()
        if p.duplicated(['game_id','play_id']).any():raise ValueError('DUPLICATE_HISTORICAL_PLAY')
        q=p[(p.qb_dropback==1)&(p.qb_kneel!=1)&(p.qb_spike!=1)&p.epa.notna()&p.passer_player_id.notna()]
        qbs.append(q.groupby(['game_id','season','week','passer_player_id']).epa.agg(epa_sum='sum',dropbacks='count').reset_index());parts.append(p)
        print('HISTORICAL_SOURCE',y,len(p),flush=True)
    pbp=pd.concat(parts,ignore_index=True);missing=set(games.game_id)-set(pbp.game_id)
    if missing:raise ValueError('MISSING_COMPLETED_GAME:'+str(sorted(missing)))
    base,base_audit=bf.build_weekly_features(games,pbp)
    injuries=pd.concat([pd.read_csv(raw/f'injuries_{y}.csv',low_memory=False) for y in range(2015,2025)],ignore_index=True)
    snaps=pd.concat([pd.read_csv(raw/f'snap_counts_{y}.csv',low_memory=False) for y in range(2015,2025)],ignore_index=True)
    airports=pd.read_csv(ROOT/'data/nfl/contextual_v1/sources/airports.csv').set_index('team').to_dict('index')
    history,state,audit=build_history(base,games,injuries[injuries.game_type=='REG'],snaps[snaps.game_type=='REG'],pd.concat(qbs,ignore_index=True),airports)
    history.to_csv(out/'history.csv',index=False);pd.concat(qbs,ignore_index=True).to_csv(out/'qb_aggregates.csv',index=False)
    games[['game_id','season','week','gameday','gametime','home_team','away_team','home_score','away_score']].to_csv(out/'historical_schedule.csv',index=False)
    save(out/'history_audit.json',{'base':base_audit,'context':audit,'feature_count':len(history.columns)-9,'source_pit_certified':False,'historical_weather_observed_not_forecast':True,'schedule_sha256':sha(allgames[0])})
    design=json.loads((ROOT/'data/nfl/contextual_v1/design.json').read_text());outputs=[]
    for arm in FAMILIES:
        for year in range(2019,2025):
            train=history[history.season<year];test=history[(history.season==year)&history.home_margin.notna()]
            model=fit(train,arm,design);pred=predict_frame(model,test)
            d=test[['game_id','season','week','home_win','home_margin','total_points']].copy();d['arm']='CONTEXT_'+arm.upper();d['trained_through_season']=year-1
            for c,t in [('p_home','home_win'),('pred_margin','home_margin'),('pred_total','total_points')]:d[c]=pred[t]
            outputs.append(d);save(out/'context_fits'/f'{arm}_{year}.json',model)
    pd.concat(outputs,ignore_index=True).to_csv(out/'context_oof.csv',index=False)
    # Actual package integration: derived outputs stay distinct from source bytes.
    import nflreadpy as nfl
    package=[]
    for name,func in [('pbp',nfl.load_pbp),('schedules',nfl.load_schedules),('player_stats',nfl.load_player_stats),('team_stats',nfl.load_team_stats),('rosters',nfl.load_rosters),('snap_counts',nfl.load_snap_counts),('depth_charts',nfl.load_depth_charts),('injuries',nfl.load_injuries)]:
        rec={'loader':'nflreadpy.'+func.__name__,'season':2026,'requested_at_utc':now(),'mode':'CURRENT_OBSERVATIONS_NOT_PREDICTIVE_FEATURES'}
        try:
            d=func(2026);p=out/'package_current'/f'{name}.parquet';p.parent.mkdir(parents=True,exist_ok=True);d.write_parquet(p)
            rec.update(status='CAPTURED_PACKAGE_OUTPUT',rows=d.height,columns=d.columns,path=str(p.relative_to(out)),sha256=sha(p),retrieved_at_utc=now(),raw_source_bytes=False)
        except Exception as exc:rec.update(status='FAILED',error=repr(exc),retrieved_at_utc=now())
        package.append(rec);print('PACKAGE',name,rec['status'],rec.get('rows'),flush=True)
    save(out/'package_receipts.json',package)
    versions={}
    for name in ('nflreadpy','polars','numpy','pandas','scipy','scikit-learn','pyarrow'):
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]=None
    save(out/'versions.json',versions)
    catalogue=[]
    for repo in ['nflverse/nflreadpy','nflverse/nflverse-data','nflverse/nflfastR','samhoppen/NFL_public','samhoppen/Fantasy-Evaluator','samhoppen/nflWAR_public','samhoppen/shank_wnba','shankapotomus/wnba-rapm']:
        name=repo.replace('/','__');rec=capture((out/'repo_metadata'/f'{name}.json','https://api.github.com/repos/'+repo));catalogue.append(rec)
    save(out/'repository_receipts.json',catalogue)
    save(out/'input_manifest.json',{str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()})
    print('BUILD_COMPLETE',len(history),'history rows',sum(len(d) for d in outputs),'OOF rows',flush=True)
if __name__=='__main__':main()
