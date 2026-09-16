#!/usr/bin/env python3
"""Build causal context features and fit fixed chronological comparison arms."""
from __future__ import annotations
import argparse,datetime as dt,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from models.nfl.contextual.features import build_history
from models.nfl.contextual.model import fit,predict_frame,score,FAMILIES
from models.nfl.contextual.recovered_inference import digest

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--recovered-root',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    data=ROOT/'data/nfl/contextual_v1';sources=data/'sources';design=json.loads((data/'design.json').read_text())
    if args.output.exists():raise ValueError('OUTPUT_EXISTS')
    args.output.mkdir(parents=True)
    source=args.recovered_root/'data/nfl/source/nflverse_2026-08-10T1930Z'
    featurepath=args.recovered_root/'data/nfl/model/runs/2026-08-10_nflverse_2015_2025_oof_v2/features.csv'
    base=pd.read_csv(featurepath);base=base[base.season.between(2015,2025)].copy()
    games=pd.read_csv(source/'nfl_games.csv')
    # Explicit column allowlist at source boundary; market columns never leave it.
    games=games[['game_id','season','week','game_type','gameday','gametime','home_team','away_team','location','home_qb_id','away_qb_id']]
    manifest=json.loads((sources/'manifest.json').read_text())
    if any('error' in r for r in manifest):raise ValueError('SOURCE_DOWNLOAD_INCOMPLETE')
    for r in manifest:
        if hashlib.sha256((sources/r['file']).read_bytes()).hexdigest()!=r['sha256']:raise ValueError('SOURCE_HASH')
    injuries=pd.concat([pd.read_csv(sources/f'injuries_{y}.csv') for y in range(2015,2026)],ignore_index=True)
    snaps=pd.concat([pd.read_csv(sources/f'snap_counts_{y}.csv') for y in range(2015,2026)],ignore_index=True)
    injuries=injuries[injuries.game_type=='REG'];snaps=snaps[snaps.game_type=='REG']
    pbp_aggregate=[];pbp_sources=[]
    cols=['game_id','season','week','season_type','passer_player_id','qb_dropback','epa','qb_kneel','qb_spike','play_id']
    for year in range(2015,2026):
        path=source/f'play_by_play_{year}.csv.gz';d=pd.read_csv(path,usecols=cols,low_memory=False)
        d=d[(d.season_type=='REG') & (d.qb_dropback==1)&(d.qb_kneel!=1)&(d.qb_spike!=1)&d.epa.notna()&d.passer_player_id.notna()].drop_duplicates(['game_id','play_id'])
        g=d.groupby(['game_id','season','week','passer_player_id']).epa.agg(epa_sum='sum',dropbacks='count').reset_index();pbp_aggregate.append(g)
        pbp_sources.append({'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'rows_used':len(d)})
        print('QB history',year,len(d),flush=True)
    qbs=pd.concat(pbp_aggregate,ignore_index=True)
    airports=pd.read_csv(sources/'airports.csv').set_index('team').to_dict('index')
    history,state,audit=build_history(base,games,injuries,snaps,qbs,airports)
    state['roles']={k:list(v) for k,v in state['roles'].items()}
    history.to_csv(args.output/'features.csv',index=False);qbs.to_csv(args.output/'qb_game_aggregates.csv',index=False)
    (args.output/'state.json').write_text(json.dumps(state,allow_nan=False))
    audit.update({'games':len(history),'injury_rows':len(injuries),'snap_rows':len(snaps),'qb_game_rows':len(qbs),'feature_sha256':hashlib.sha256((args.output/'features.csv').read_bytes()).hexdigest(),'source_manifest':manifest,'pbp_sources':pbp_sources,'base_feature_sha256':hashlib.sha256(featurepath.read_bytes()).hexdigest(),'design_sha256':digest(design),'historical_PIT_claim':False})
    (args.output/'data_audit.json').write_text(json.dumps(audit,indent=2))
    outputs=[];params={}
    for arm in FAMILIES:
        for year in range(2019,2026):
            train=history[history.season<year];test=history[(history.season==year)&history.home_margin.notna()]
            fitted=fit(train,arm,design);p=predict_frame(fitted,test)
            out=test[['game_id','season','week','home_win','home_margin','total_points']].copy();out['arm']=arm
            for name,t in [('p_home','home_win'),('pred_margin','home_margin'),('pred_total','total_points')]:out[name]=p[t]
            outputs.append(out);print('Fold',arm,year,len(train),len(test),flush=True)
        params[arm]=fit(history,arm,design)
    oof=pd.concat(outputs,ignore_index=True);oof.to_csv(args.output/'oof_predictions.csv',index=False)
    metrics={arm:{'all':score(g),'week1':score(g[g.week==1]),'weeks1to4':score(g[g.week<=4])} for arm,g in oof.groupby('arm')}
    ref=oof[oof.arm=='base'].set_index('game_id');full=oof[oof.arm=='combined'].set_index('game_id')
    if not ref.index.equals(full.index):raise ValueError('ARM_POPULATION_MISMATCH')
    binary=ref.home_win.notna();d=((full.p_home-ref.home_win)**2-(ref.p_home-ref.home_win)**2)[binary]
    seasons=ref.loc[binary,'season'];unique=sorted(seasons.unique());rng=np.random.default_rng(design['screen']['bootstrap_seed'])
    sums=np.array([d[seasons==s].sum() for s in unique]);counts=np.array([(seasons==s).sum() for s in unique]);idx=rng.integers(len(unique),size=(10000,len(unique)))
    boots=sums[idx].sum(axis=1)/counts[idx].sum(axis=1);ci=np.quantile(boots,[.025,.975]).tolist()
    delta={k:metrics['combined']['all'][k]-metrics['base']['all'][k] for k in ['brier','log_loss','margin_mae','total_mae']}
    passed=delta['brier']<=-.002 and ci[1]<0 and delta['log_loss']<=0 and delta['margin_mae']<=.1
    report={'metrics':metrics,'combined_minus_refit_base':delta,'paired_brier_season_bootstrap_95_ci':ci,'screen_passed':passed,'promotion':False,'evidence':'REUSED_RETROSPECTIVE; report/start identity not archived pregame','completed_at_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    (args.output/'evaluation.json').write_text(json.dumps(report,indent=2))
    # Prior-year-only residual evaluation is possible from saved per-game OOF rows.
    residuals=np.column_stack([(full.home_margin+full.total_points-full.pred_margin-full.pred_total)/2,(full.total_points-full.home_margin-full.pred_total+full.pred_margin)/2])
    artifact={'schema':'nfl.integrated_context.v1','arms':params,'design':design,'source_audit_sha256':digest(audit),'final_score_residuals':residuals.tolist(),'residual_seasons':full.season.astype(int).tolist(),'state':state,'airports':airports,'research_only':True,'promotion':False}
    (args.output/'model.json').write_text(json.dumps(artifact,allow_nan=False))
    print(json.dumps({'metrics':metrics,'delta':delta,'ci':ci,'screen_passed':passed},indent=2))

if __name__=='__main__':main()
