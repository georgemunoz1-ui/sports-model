#!/usr/bin/env python3
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np,pandas as pd
from models.nfl.modes.core import devig,LIVE_FEATURES

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--oof',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(exist_ok=False,parents=True)
    path=a.source/'nfl_games.csv';g=pd.read_csv(path);g=g[(g.game_type=='REG')&g.season.between(2015,2025)&g.home_score.notna()&g.away_score.notna()].copy();full_count=len(g)
    ok=(g.home_moneyline.abs()>=100)&(g.away_moneyline.abs()>=100)&g.spread_line.notna()&g.total_line.notna();excluded=g.loc[~ok,['game_id','season']].to_dict('records');g=g[ok].copy()
    g['market_p_home']=[devig(h,a) for h,a in zip(g.home_moneyline,g.away_moneyline)];g['target']=np.where(g.home_score>g.away_score,1,np.where(g.home_score<g.away_score,0,2));g.to_csv(a.output/'games.csv',index=False)
    oof=pd.read_csv(a.oof);oof=oof[oof.arm=='combined'];market=oof.merge(g[['game_id','market_p_home','spread_line','total_line']],on='game_id',validate='one_to_one');market.to_csv(a.output/'market.csv',index=False)
    sources=[{'file':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()},{'file':str(a.oof),'sha256':hashlib.sha256(a.oof.read_bytes()).hexdigest()}];out=[];audit={}
    cols=['game_id','play_id','home_team','away_team','posteam','posteam_score','defteam_score','game_seconds_remaining','quarter_seconds_remaining','qtr','yardline_100','down','ydstogo','home_timeouts_remaining','away_timeouts_remaining']
    for year in range(2015,2026):
        path=a.source/f'play_by_play_{year}.csv.gz';d=pd.read_csv(path,usecols=cols,low_memory=False);raw=len(d)
        d=d.merge(g[g.season==year][['game_id','season','market_p_home','target']],on='game_id',validate='many_to_one')
        valid=d[cols[5:]].notna().all(axis=1)&d.posteam.isin(pd.concat([g.home_team,g.away_team]).unique())&d.qtr.between(1,5)&d.down.between(1,4)&d.yardline_100.between(0,100)&d.ydstogo.between(0,100)&d.home_timeouts_remaining.between(0,3)&d.away_timeouts_remaining.between(0,3)
        valid&=(d.posteam==d.home_team)|(d.posteam==d.away_team)
        # Every predictor is at the start of the play. Never total_home_score (post-play).
        d=d[valid].copy();q=d.qtr;sec=d.game_seconds_remaining;qr=d.quarter_seconds_remaining
        clock=((q<=4)&((sec-((4-q)*900+qr)).abs()<=1))|((q==5)&((sec-qr).abs()<=1));d=d[clock&qr.between(0,900)&sec.between(0,3600)].copy()
        # nflverse resets game_seconds_remaining to the OT period clock.
        # Canonical feature is regulation seconds remaining; retain OT clock separately.
        d.loc[d.qtr==5,'game_seconds_remaining']=0.0
        d['clock_minute']=(d.quarter_seconds_remaining//60).astype(int);d=d.sort_values(['game_id','play_id']).drop_duplicates(['game_id','qtr','clock_minute'],keep='first')
        ph=(d.posteam==d.home_team);h=np.where(ph,d.posteam_score,d.defteam_score);away=np.where(ph,d.defteam_score,d.posteam_score);margin=h-away;sec=d.game_seconds_remaining
        values=[h,away,margin,sec,d.quarter_seconds_remaining,d.qtr,ph.astype(float),d.yardline_100,d.down,d.ydstogo,d.home_timeouts_remaining,d.away_timeouts_remaining,np.log(d.market_p_home/(1-d.market_p_home)),margin/np.sqrt(sec/60+1),(2*ph.astype(float)-1)*(100-d.yardline_100)/100]
        f=d[['game_id','play_id','season','target','market_p_home']].copy()
        for name,v in zip(LIVE_FEATURES,values):f[name]=v
        out.append(f);audit[str(year)]={'source_rows':raw,'sampled_states':len(f),'games':f.game_id.nunique()};sources.append({'file':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()});print(year,audit[str(year)],flush=True)
    live=pd.concat(out,ignore_index=True);live.to_csv(a.output/'live.csv',index=False)
    result={'source_manifest':sources,'completed_games':full_count,'market_complete_games':len(g),'excluded_market_games':excluded,'sampled_live_states':len(live),'live_seasons':audit,'market_join_games':len(market),'features':LIVE_FEATURES,'historical_market_timestamp_status':'NOT_ARCHIVED','pbp_vintage':'CORRECTED_RETROSPECTIVE_NOT_ORIGINAL_LIVE_RECEIPTS','output_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in a.output.glob('*.csv')}}
    (a.output/'data_audit.json').write_text(json.dumps(result,indent=2))
if __name__=='__main__':main()
