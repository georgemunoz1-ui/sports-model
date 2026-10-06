"""Separate postseason winner challengers; no incumbent mutation or action authority.

The enriched rate model is a hypothesis, not proof of improved prediction. Output
is winner-only: latent nine-inning runs are not a baseball settlement simulator.
"""
import datetime as dt
import math
import numpy as np
from research.mlb_postseason_v1 import V, digest, validate_inputs

ARMS={1:'mlb.postseason.context.workload.v2',2:'mlb.postseason.context.lineup.v3',3:'mlb.postseason.context.bullpen.v4',4:'mlb.postseason.context.temperature.v5'}


def number(x,low=0,high=1e9):
    if type(x) not in (int,float) or not math.isfinite(x) or not low<=x<=high:
        raise ValueError('INVALID_NUMBER')
    return x


def logs_before(player,group,day):
    rows=[];seen=set()
    for g in player.get('stats',[]):
        if g['group']['displayName']!=group or g['type']['displayName']!='gameLog': continue
        for r in g.get('splits',[]):
            if r['player']['id']!=player['id']: raise ValueError('PLAYER_LOG_IDENTITY')
            if r['gameType'] not in ('R','F','D','L','W') or r['date']>=day: continue
            key=str(r['game']['gamePk'])
            if key in seen: raise ValueError('DUPLICATE_PLAYER_GAME')
            seen.add(key);rows.append(r)
    return sorted(rows,key=lambda r:(r['date'],r['game']['gamePk']))


def pitching(player,day):
    rows=logs_before(player,'pitching',day)
    for r in rows:
        s=r['stat'];ip=str(s['inningsPitched']);whole,part=ip.split('.') if '.' in ip else (ip,'0')
        if part not in ('0','1','2') or 3*int(whole)+int(part)!=s['outs']: raise ValueError('OUTS_UNITS')
        for k in ('outs','earnedRuns','battersFaced','strikeOuts','baseOnBalls','gamesStarted','numberOfPitches'): number(s[k])
    return rows


def starter_profile(player,day):
    rows=[r for r in pitching(player,day) if r['gameType']=='R']
    totals={k:sum(r['stat'][k] for r in rows) for k in ('outs','earnedRuns','battersFaced','strikeOuts','baseOnBalls','gamesStarted')}
    if totals['outs']<3 or totals['battersFaced']<10 or totals['gamesStarted']<1: raise ValueError('STARTER_HISTORY_MISSING')
    return {'era':27*totals['earnedRuns']/totals['outs'],'gs':totals['gamesStarted'],'k':100*totals['strikeOuts']/totals['battersFaced'],'bb':100*totals['baseOnBalls']/totals['battersFaced'],'observed_game_ids':[str(r['game']['gamePk']) for r in rows]}


def workload(player,day,plan=None):
    rows=pitching(player,day);starts=[r for r in rows if r['stat']['gamesStarted']==1][-5:]
    if not starts: raise ValueError('WORKLOAD_START_HISTORY_MISSING')
    innings=np.array([r['stat']['outs']/3 for r in starts]);mean=(innings.sum()+3*5.4)/(len(innings)+3)
    variance=(sum((innings-mean)**2)+3*(1.3**2+(5.4-mean)**2))/(len(innings)+3)
    cap=8.;role='OBSERVED_START_DISTRIBUTION';bulk=None
    if plan:
        if plan['role'] not in ('STARTER','OPENER'): raise ValueError('UNSUPPORTED_ROLE')
        if plan['role']=='OPENER':
            number(plan['expected_innings'],.1,3);mean=plan['expected_innings'];cap=min(3,mean+1);role='SOURCE_REVIEWED_OPENER'
            if not plan.get('bulk_pitcher_id'): raise ValueError('OPENER_BULK_REQUIRED')
            bulk=plan['bulk_pitcher_id']
        if plan.get('pitch_cap') is not None:
            pitches=sum(r['stat']['numberOfPitches'] for r in starts);outs=sum(r['stat']['outs'] for r in starts)
            number(plan['pitch_cap'],1,150)
            cap=min(cap,plan['pitch_cap']/(pitches/outs)/3);mean=min(mean,cap)
    return {'mean':float(mean),'sd':float(max(.3,math.sqrt(variance))),'cap':cap,'role':role,'bulk_pitcher_id':bulk,'used_game_ids':[str(r['game']['gamePk']) for r in starts],'prior':{'starts':3,'mean':5.4,'sd':1.3}}


def batting(player,day):
    rows=logs_before(player,'hitting',day);keys=('atBats','hits','doubles','triples','homeRuns','baseOnBalls','hitByPitch','sacFlies','plateAppearances')
    t={k:sum(number(r['stat'][k]) for r in rows) for k in keys}
    den=t['atBats']+t['baseOnBalls']+t['hitByPitch']+t['sacFlies']
    ops=((t['hits']+t['baseOnBalls']+t['hitByPitch'])/den+(t['hits']+t['doubles']+2*t['triples']+3*t['homeRuns'])/t['atBats']) if den and t['atBats'] else .720
    return {'ops':(ops*t['plateAppearances']+.720*100)/(t['plateAppearances']+100),'pa':t['plateAppearances'],'observed_games':len(rows)}


def lineup_factor(order,roster,players,day,unavailable):
    if len(order)!=9 or len(set(order))!=9: raise ValueError('NINE_CONFIRMED_BATTERS_REQUIRED')
    eligible={r['person']['id'] for r in roster['roster'] if r['status']['code']=='A'}
    if any(i not in eligible or i in unavailable for i in order): raise ValueError('LINEUP_AVAILABILITY_CONFLICT')
    stats={i:batting(players[i],day) for i in eligible if i in players}
    if any(i not in stats for i in order): raise ValueError('BATTER_HISTORY_SOURCE_MISSING')
    # All roster bats supply comparison baseline, including unavailable players:
    # removing a batter from the lineup is counted once, never a second injury penalty.
    pa=sum(s['pa'] for s in stats.values())
    if pa<=0: raise ValueError('TEAM_BATTER_REFERENCE_MISSING')
    reference=sum(s['ops']*s['pa'] for s in stats.values())/pa
    actual=sum(stats[i]['ops'] for i in order)/9
    return {'factor':float(np.clip(actual/reference,.75,1.25)),'lineup_ops':actual,'roster_reference_ops':reference,'player_ids':order,'players':{str(i):stats[i] for i in order},'unavailable_ids':sorted(unavailable),'method':'SHRUNK_OPS_LINEUP_RATIO_NO_DUPLICATE_INJURY_PENALTY'}


def bullpen(roster,players,day,starter_id,unavailable,bulk_id=None):
    rows=[];cut=dt.date.fromisoformat(day)
    for entry in roster['roster']:
        pid=entry['person']['id']
        if entry['position']['abbreviation']!='P' or entry['status']['code']!='A' or pid in unavailable or pid in (starter_id,bulk_id): continue
        if pid not in players: raise ValueError('BULLPEN_PLAYER_SOURCE_MISSING')
        games=pitching(players[pid],day);relief=[r for r in games if r['stat']['gamesStarted']==0]
        if not relief: continue
        outs=sum(r['stat']['outs'] for r in relief);er=sum(r['stat']['earnedRuns'] for r in relief)
        recent=[r for r in games if 0<(cut-dt.date.fromisoformat(r['date'])).days<=3]
        pitches=sum(r['stat']['numberOfPitches'] for r in recent)
        rate=(er*27+4.2*60)/(outs+60);weight=max(1,outs)/(1+pitches/60)
        rows.append({'id':pid,'relief_outs':outs,'era_shrunk':rate,'pitches_prior_3_days':pitches,'weight':weight,'recent_game_ids':[str(r['game']['gamePk']) for r in recent]})
    if not rows: raise ValueError('BULLPEN_POOL_MISSING')
    return {'rate':sum(r['weight']*r['era_shrunk'] for r in rows)/sum(r['weight'] for r in rows),'members':rows,'excluded_unavailable_ids':sorted(unavailable),'availability':'WORKLOAD_WEIGHT_NOT_MANAGER_CONFIRMATION'}


def build_context(e,feeds,rosters,players,plans=None,unavailable=None,stage=3):
    result={};day=e['slate_date'];plans=plans or {};unavailable=unavailable or {}
    for side in ('away','home'):
        pid=e[side+'_pitcher_id'];order=feeds[side]['order'];roster=rosters[side];missing=set(unavailable.get(side,[]));plan=plans.get(side)
        if pid in missing: raise ValueError('STARTER_UNAVAILABLE')
        active={x['person']['id'] for x in roster['roster'] if x['status']['code']=='A'}
        if pid not in active: raise ValueError('STARTER_ROSTER_CONFLICT')
        w=workload(players[pid],day,plan);bulk=None
        if w['bulk_pitcher_id']:
            bid=w['bulk_pitcher_id']
            if bid not in active or bid in missing or bid==pid: raise ValueError('BULK_ROSTER_CONFLICT')
            number(plan['bulk_expected_innings'],.1,8)
            games=pitching(players[bid],day);outs=sum(r['stat']['outs'] for r in games);er=sum(r['stat']['earnedRuns'] for r in games)
            if outs<=0: raise ValueError('BULK_HISTORY_MISSING')
            bulk={'id':bid,'mean':plan['bulk_expected_innings'],'rate':(27*er+60*4.2)/(outs+60)}
        result[side]={'workload':w,'bulk':bulk,'lineup':lineup_factor(order,roster,players,day,missing) if stage>=2 else None,'bullpen':bullpen(roster,players,day,pid,missing,w['bulk_pitcher_id']) if stage>=3 else None}
    return result


def simulate(e,context,stage,n,seed,slope=None):
    validate_inputs(e)
    if stage not in ARMS: raise ValueError('UNKNOWN_ARM')
    if type(n)is not int or not 1<=n<=1000000: raise ValueError('DRAW_COUNT')
    if stage==4: number(slope,.25,2)
    rng=np.random.default_rng(seed);ips={};pens={};off={};staff={}
    for side in ('away','home'):
        c=context[side];w=c['workload']
        for k in ('mean','sd','cap'): number(w[k],.01,9)
        ips[side]=np.clip(rng.normal(w['mean'],w['sd'],n),.1,w['cap'])
        pens[side]=c['bullpen']['rate'] if stage>=3 else .55*e[side+'_form']['ra']+.45*V.LG_RPG
        number(pens[side],.01,30)
        off[side]=e[side+'_form']['rf']/V.LG_RPG*(c['lineup']['factor'] if stage>=2 else 1)
        sp=e['sp_'+side];rate=V.rs(sp['era'],sp['gs'],sp['k'],sp['bb']);bulk=c['bulk']
        bulk_ip=np.minimum(np.maximum(0,9-ips[side]),bulk['mean']) if bulk else 0
        staff[side]=rate*ips[side]+(bulk['rate']*bulk_ip if bulk else 0)+pens[side]*(9-ips[side]-bulk_ip)
    ma=staff['home']/9*off['away']*(1+(e['park_factor']-1)*V.bipf(e['sp_home']['k'],e['sp_home']['bb'])/V.LG_BIP)
    mh=staff['away']/9*off['home']*(1+(e['park_factor']-1)*V.bipf(e['sp_away']['k'],e['sp_away']['bb'])/V.LG_BIP)*V.HFA
    sa=float(np.clip(1.8+(e['sp_home']['k']-V.LG_K)*.16,1.2,6));sh=float(np.clip(1.8+(e['sp_away']['k']-V.LG_K)*.16,1.2,6))
    ra=rng.poisson(rng.gamma(sa,np.maximum(ma,.3)/sa));rh=rng.poisson(rng.gamma(sh,np.maximum(mh,.3)/sh));home=rh>ra;pending=np.flatnonzero(ra==rh)
    for _ in range(200):
        if not len(pending): break
        a=rng.poisson(pens['home']*off['away']*e['park_factor']/9,len(pending));h=rng.poisson(pens['away']*off['home']*e['park_factor']*V.HFA/9,len(pending));done=a!=h;home[pending[done]]=h[done]>a[done];pending=pending[~done]
    if len(pending): raise ValueError('EXTRAS_UNRESOLVED')
    raw=float(home.mean());p=raw
    draws={'home_win_raw':home,'away_starter_innings':ips['away'],'home_starter_innings':ips['home']}
    if stage==4:
        # Calibration is a distinct winner estimator; it is not a score rescale.
        p=calibrate(raw,slope);crng=np.random.default_rng(np.random.SeedSequence([seed,61006]));draws['home_win_calibrated']=crng.random(n)<p
    sim_p=float(draws.get('home_win_calibrated',home).mean())
    return {'model_id':ARMS[stage],'home_win_probability':p,'simulation_home_win_probability':sim_p,'raw_home_win_probability':raw,'n':n,'seed':seed,'rng':'NumPy PCG64','context_sha256':digest(context),'mc_se':math.sqrt(sim_p*(1-sim_p)/n),'predictive_validation':'UNVALIDATED','official_release_eligible':False,'action_authority':False,'dose':0.,'supported_products':['winner diagnostic'],'score_total_runline_outputs':None},draws


def calibrate(p,slope):
    number(p,0,1);number(slope,.25,2)
    if p in (0,1): return float(p)
    return float(1/(1+math.exp(-slope*math.log(p/(1-p)))))
