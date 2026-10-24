"""Observational NFL features; raw market columns never enter the returned schema."""
from collections import defaultdict, deque
import numpy as np
import pandas as pd

TEAM_ALIASES = {'OAK':'LV','SD':'LAC','STL':'LA','LAR':'LA'}


def team(value):
    return TEAM_ALIASES.get(value,value)


def nfl_history(games, callers):
    """Lagged last-eight scoring and coaching continuity; date-batched updates.

    Source captured retrospectively: ordering is safe but historical source availability
    is unverified. Caller on current game is a retrospective metadata assumption.
    No fabricated known_at timestamps or PIT certificate is generated.
    """
    g = games.copy()
    if g.game_id.duplicated().any() or callers.duplicated(['game_id','team']).any():
        raise ValueError('duplicate games or caller keys')
    g = g[(g.game_type=='REG') & (g.season>=1999) & (g.season<=2024)].copy()
    if g[['gameday','home_score','away_score']].isna().any().any():
        raise ValueError('missing historical date or final score')
    c = callers.copy();c['team']=c.team.map(team)
    if c.duplicated(['game_id','team']).any(): raise ValueError('ambiguous normalized caller key')
    lookup = c.set_index(['game_id','team'])
    history=defaultdict(lambda:deque(maxlen=8)); coach_history=defaultdict(list)
    output=[]
    for date, day in g.sort_values(['gameday','game_id']).groupby('gameday',sort=True):
        pending=[]
        for r in day.itertuples():
            row={'game_id':r.game_id,'date':date,'season':int(r.season),'week':int(r.week),
                 'target_margin':float(r.home_score-r.away_score)}
            for side,score,allowed in [('home',r.home_score,r.away_score),('away',r.away_score,r.home_score)]:
                t=team(getattr(r,side+'_team')); row[side+'_team']=t
                h=history[t]; row[side+'_prior_n']=len(h)
                row[side+'_prior_for']=float(np.mean([x[0] for x in h])) if h else None
                row[side+'_prior_against']=float(np.mean([x[1] for x in h])) if h else None
                key=(r.game_id,t)
                coaches=lookup.loc[key] if key in lookup.index else None
                prior=coach_history[t]
                for role,name in [('coach','head_coach'),('oc','off_play_caller'),('dc','def_play_caller')]:
                    current=coaches[name] if coaches is not None else None
                    valid=current is not None and not pd.isna(current)
                    row[f'{side}_{role}_changed']=int(current!=prior[-1][name]) if valid and prior and prior[-1].get(name) is not None else None
                    if role=='coach':
                        row[f'{side}_coach_prior_games']=sum(x.get(name)==current for x in prior) if valid else None
                pending.append((t,(float(score),float(allowed)),coaches.to_dict() if coaches is not None else {}))
            output.append(row)
        # No earlier game on the same date can become a feature for a later game that day.
        for t,scores,coaches in pending:
            history[t].append(scores);coach_history[t].append(coaches)
    return pd.DataFrame(output).query('season >= 2000').reset_index(drop=True)


def pbp_features(raw):
    required=['game_id','play_id','order_sequence','posteam','play_type','epa','success',
              'pass_attempt','rush_attempt','sack','interception','fumble_lost','down',
              'score_differential','qtr','game_seconds_remaining','drive','timeout',
              'out_of_bounds','incomplete_pass','touchdown','penalty','complete_pass',
              'yardline_100','receiver_player_id','rusher_player_id','yards_after_catch',
              'xyac_mean_yardage','play_deleted']
    if not set(required)<=set(raw): raise ValueError('missing PBP columns')
    p=raw[required].copy()
    if p.duplicated(['game_id','play_id']).any(): raise ValueError('duplicate play')
    if p.order_sequence.isna().any() or p.duplicated(['game_id','order_sequence']).any():
        raise ValueError('ambiguous play ordering')
    p=p.sort_values(['game_id','order_sequence'])
    # Shift BEFORE dropping non-scrimmage plays so intervening stoppages break the chain.
    previous=p.groupby('game_id').shift(1)
    elapsed=previous.game_seconds_remaining-p.game_seconds_remaining
    running=(p.posteam==previous.posteam)&(p.qtr==previous.qtr)&(p.drive==previous.drive)
    running &= p.play_type.isin(['pass','run']) & previous.play_type.isin(['pass','run'])
    for col in ['timeout','out_of_bounds','incomplete_pass','touchdown','penalty','play_deleted']:
        running &= previous[col].eq(0)
    running &= elapsed.between(0,40) & p.play_deleted.eq(0)
    p['elapsed_running_clock']=elapsed.where(running)
    p=p[(p.play_deleted==0)&p.play_type.isin(['pass','run'])&p.posteam.notna()].copy()
    p['hvt_reception']=p.complete_pass.eq(1)
    p['hvt_rush']=p.rush_attempt.eq(1)&p.yardline_100.le(10)
    rows=[]
    for (game,t),d in p.groupby(['game_id','posteam']):
        r={'game_id':game,'team':team(t),'plays':len(d)}
        masks={'all':pd.Series(True,index=d.index),'early_down':d.down.isin([1,2]),
               'pass':d.pass_attempt.eq(1),'rush':d.rush_attempt.eq(1),
               'third_down':d.down.eq(3),'red_zone':d.yardline_100.le(20)}
        for prefix,mask in masks.items():
            r[prefix+'_n']=int(mask.sum())
            for col in ['epa','success']:
                v=d.loc[mask,col];r[prefix+'_'+col+'_n']=int(v.notna().sum())
                r[prefix+'_'+col]=float(v.mean()) if v.notna().any() else None
        neutral=d[d.score_differential.abs().le(8)&d.qtr.le(3)]
        r['neutral_n']=len(neutral)
        r['neutral_pass_rate']=float(neutral.pass_attempt.mean()) if len(neutral) else None
        r['sacks']=int(d.sack.sum());r['turnovers']=int((d.interception.eq(1)|d.fumble_lost.eq(1)).sum())
        pace=d.elapsed_running_clock.dropna();r['running_clock_n']=len(pace)
        r['running_clock_seconds']=float(pace.mean()) if len(pace) else None
        r['high_value_touches']=int(d.hvt_reception.sum()+d.hvt_rush.sum())
        targets=d.loc[d.pass_attempt.eq(1)&d.receiver_player_id.notna(),'receiver_player_id'].value_counts()
        r['identified_targets']=int(targets.sum())
        r['target_hhi']=float(((targets/targets.sum())**2).sum()) if targets.sum() else None
        r['top_target_share']=float(targets.max()/targets.sum()) if targets.sum() else None
        xy=d[d.complete_pass.eq(1)][['yards_after_catch','xyac_mean_yardage']].dropna()
        r['yac_residual_n']=len(xy)
        r['mean_yac_minus_expected']=float((xy.yards_after_catch-xy.xyac_mean_yardage).mean()) if len(xy) else None
        rows.append(r)
    players=[]
    for col,mask,kind in [('receiver_player_id',p.hvt_reception,'receptions'),('rusher_player_id',p.hvt_rush,'rushes_inside10')]:
        selected=p[mask]
        if selected[col].isna().any():raise ValueError('missing player identity for HVT')
        for (game,t,pid),n in selected.groupby(['game_id','posteam',col]).size().items():
            players.append({'game_id':game,'team':team(t),'player_id':pid,'touch_type':kind,'count':int(n)})
    return pd.DataFrame(rows),pd.DataFrame(players)
