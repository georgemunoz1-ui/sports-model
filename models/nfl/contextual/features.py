"""Shared historical/live context features. No market data or hand-set point effects.

Historical starter/report identities are retrospective source records; causal
feature ordering does not turn them into archived pregame observations.
"""
from __future__ import annotations
import datetime as dt
import math
import re
from collections import defaultdict, deque
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

GROUPS = ('QB','RB','WRTE','OL','DL','LB','DB')
ALIASES = {'JAC':'JAX','LAR':'LA','OAK':'LV','SD':'LAC','STL':'LA','WSH':'WAS'}
QB_FEATURES = ['qb_quality_diff','qb_quality_sum','qb_experience_diff','qb_change_diff','qb_unknown_count']
AVAIL_FEATURES = [f'{g}_{kind}_{direction}' for g in GROUPS for kind in ('out','questionable','doubtful','dnp','out_snap') for direction in ('diff','sum')] + ['report_missing_count','out_role_unknown_count']
TRAVEL_FEATURES = ['away_travel_1000km','away_east_hours','away_west_hours','away_early_body_clock','travel_unknown']
EAST = {'ATL','BAL','BUF','CAR','CIN','CLE','DET','IND','JAX','MIA','NE','NYG','NYJ','PHI','PIT','TB','WAS'}
CENTRAL = {'CHI','DAL','GB','HOU','KC','MIN','NO','TEN'}

def canonical(team): return ALIASES.get(str(team),str(team))
def name_key(value):
    return re.sub(r'[^a-z0-9]','',re.sub(r'\b(jr|sr|ii|iii|iv)\b','',str(value).lower()))
def group(position):
    p=str(position).upper()
    if p in {'QB'}:return 'QB'
    if p in {'RB','FB','HB'}:return 'RB'
    if p in {'WR','TE'}:return 'WRTE'
    if p in {'OL','OT','T','G','OG','C','LT','RT','LG','RG'}:return 'OL'
    if p in {'DL','DT','DE','NT','EDGE'}:return 'DL'
    if p in {'LB','ILB','OLB','MLB'}:return 'LB'
    if p in {'DB','CB','S','SS','FS','SAF'}:return 'DB'
    return None

def kickoff(row):
    # nflverse gametime is Eastern. Missing kickoff cannot admit dated reports.
    if pd.isna(row.get('gametime')):return None
    return dt.datetime.fromisoformat(str(row['gameday'])+'T'+str(row['gametime'])).replace(tzinfo=ZoneInfo('America/New_York')).astimezone(dt.timezone.utc)

def travel_features(row, airports):
    h,a=canonical(row['home_team']),canonical(row['away_team']);year=int(row['season'])
    out=dict.fromkeys(TRAVEL_FEATURES,0.0)
    old=lambda t:(t=='LA' and year<2016) or (t=='LAC' and year<2017) or (t=='LV' and year<2020)
    if str(row.get('location','Home')).lower()!='home' or h not in airports or a not in airports or old(h) or old(a):
        out['travel_unknown']=1.;return out
    ah,aa=airports[h],airports[a]
    p1,p2=map(math.radians,[aa['latitude'],ah['latitude']]);dl=math.radians(ah['longitude']-aa['longitude'])
    hav=math.sin((p2-p1)/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    out['away_travel_1000km']=6371.0088*2*math.asin(math.sqrt(min(1,hav)))/1000
    def zone(t):return ZoneInfo('America/New_York' if t in EAST else 'America/Chicago' if t in CENTRAL else 'America/Denver' if t=='DEN' else 'America/Phoenix' if t=='ARI' else 'America/Los_Angeles')
    stamp=kickoff(row)
    if stamp is None:out['travel_unknown']=1.;return out
    shift=(stamp.astimezone(zone(h)).utcoffset()-stamp.astimezone(zone(a)).utcoffset()).total_seconds()/3600
    out['away_east_hours']=max(shift,0);out['away_west_hours']=max(-shift,0)
    body=stamp.astimezone(zone(a));out['away_early_body_clock']=float(body.hour<12)
    return out

def qb_features(row, ratings, last_qb):
    vals=[]
    for side in ('home','away'):
        q=row.get(side+'_qb_id');known=isinstance(q,str) and bool(q)
        s=ratings.get(q,{'sum':0.,'n':0.}) if known else {'sum':0.,'n':0.}
        prev=last_qb.get(canonical(row[side+'_team']))
        vals.append((s['sum']/(s['n']+300.),math.log1p(s['n']),float(known and prev is not None and prev!=q),float(not known)))
    h,a=vals
    return dict(zip(QB_FEATURES,[h[0]-a[0],h[0]+a[0],h[1]-a[1],h[2]-a[2],h[3]+a[3]]))

def availability_features(row, reports, prior_roles):
    """No active/unrestricted inference from a blank designation or full practice.

    A prior snap share is a role proxy, not tonight's promised snap share. Only
    exact team+normalized-name matches are admitted; ambiguous names remain null.
    """
    teams=[];audit=[];unknown_roles=0;missing=0
    for side in ('home','away'):
        team=canonical(row[side+'_team']);rows=reports.get(team)
        missing+=int(rows is None)
        values={f'{g}_{k}':0. for g in GROUPS for k in ('out','questionable','doubtful','dnp','out_snap')}
        seen=set()
        for r in rows or []:
            key=str(r.get('gsis_id') or name_key(r['full_name']))
            if key in seen:raise ValueError('DUPLICATE_PLAYER_REPORT:'+team+':'+key)
            seen.add(key);g=group(r.get('position'));status=str(r.get('report_status','')).upper()
            if g is None:continue
            for k in ('out','questionable','doubtful'):
                values[g+'_'+k]+=float(status==k.upper())
            practice=str(r.get('practice_status','')).upper()
            values[g+'_dnp']+=float(practice in {'DNP','DID NOT PARTICIPATE IN PRACTICE'})
            role=None
            if status=='OUT':
                hist=prior_roles.get(team+'|'+name_key(r['full_name']),[])
                ids={h['id'] for h in hist}
                if hist and len(ids)==1:
                    age=(dt.date.fromisoformat(str(row['gameday']))-dt.date.fromisoformat(hist[-1]['date'])).days
                    if 0<age<=365:role=float(np.mean([v['share'] for v in list(hist)[-4:]]))
                if role is None:unknown_roles+=1
                else:values[g+'_out_snap']+=role
                audit.append({'team':team,'player':r['full_name'],'group':g,'status':status,'prior_snap_share':role,'role_state':'PRIOR_ROLE_PROXY' if role is not None else 'UNKNOWN'})
        teams.append(values)
    out={}
    for key in teams[0]:
        out[key+'_diff']=teams[0][key]-teams[1][key];out[key+'_sum']=teams[0][key]+teams[1][key]
    out['report_missing_count']=float(missing);out['out_role_unknown_count']=float(unknown_roles)
    return out,audit

def prepare_reports(frame, row):
    """Exclude known post-kickoff modifications; do not infer missing timestamps."""
    out={};late=0;unknown_time=0;start=kickoff(row)
    for team in [canonical(row['home_team']),canonical(row['away_team'])]:
        records=[]
        sub=frame[frame.team.map(canonical)==team]
        for r in sub.to_dict('records'):
            raw=r.get('date_modified')
            if pd.notna(raw) and raw:
                stamp=pd.Timestamp(raw)
                if stamp.tzinfo is None:unknown_time+=1
                elif start is None or stamp.to_pydatetime()>=start:late+=1;continue
            else:unknown_time+=1
            r={k:(None if pd.isna(v) else v) for k,v in r.items()}
            records.append(r)
        # A report may be updated several times in one week. Latest verified
        # pre-kickoff timestamp wins; unresolved undated conflicts are excluded.
        grouped=defaultdict(list)
        for r in records:grouped[str(r.get('gsis_id') or name_key(r['full_name']))].append(r)
        selected=[]
        for variants in grouped.values():
            if len(variants)==1:selected.append(variants[0]);continue
            dated=[r for r in variants if r.get('date_modified') and pd.Timestamp(r['date_modified']).tzinfo is not None]
            if len(dated)==len(variants):
                newest=max(pd.Timestamp(r['date_modified']) for r in dated)
                same=[r for r in dated if pd.Timestamp(r['date_modified'])==newest]
            else:same=variants
            signatures={(r.get('position'),r.get('report_status'),r.get('practice_status')) for r in same}
            if len(signatures)==1:selected.append(same[0])
            else:late+=len(variants)  # quarantine conflicting source records
        if selected:out[team]=selected
    return out,late,unknown_time

def build_history(base, games, injury, snaps, qb_games, airports):
    """Weekly state snapshot before any outcome/snap/QB updates in that week."""
    schedules=games.set_index('game_id',verify_integrity=True)
    injuries={(int(y),int(w)):g for (y,w),g in injury.groupby(['season','week'])}
    snap_groups={(int(y),int(w)):g for (y,w),g in snaps.groupby(['season','week'])}
    qb_groups={(int(y),int(w)):g for (y,w),g in qb_games.groupby(['season','week'])}
    ratings={};last_qb={};roles=defaultdict(lambda:deque(maxlen=4));output=[];audit={'late_reports_excluded':0,'report_rows_missing_publication':0};season=None
    for (year,week),rows in base.groupby(['season','week'],sort=True):
        if season is not None and year!=season:
            for v in ratings.values():v['sum']*=.55;v['n']*=.55
        season=year
        for _,b in rows.iterrows():
            if b.game_id not in schedules.index:raise ValueError('GAME_JOIN_MISSING')
            r=schedules.loc[b.game_id].to_dict();r['game_id']=b.game_id
            report,late,missing_time=prepare_reports(injuries.get((year,week),pd.DataFrame(columns=['team'])),r)
            av,_=availability_features(r,report,roles)
            output.append({**b.to_dict(),**qb_features(r,ratings,last_qb),**av,**travel_features(r,airports)})
            audit['late_reports_excluded']+=late;audit['report_rows_missing_publication']+=missing_time
        # Only completed historical games; never update state from a scheduled row.
        played={b.game_id for _,b in rows.iterrows() if pd.notna(b.get('home_margin'))}
        for r in qb_groups.get((year,week),pd.DataFrame()).to_dict('records'):
            if r['game_id'] not in played:continue
            q=r['passer_player_id'];v=ratings.setdefault(q,{'sum':0.,'n':0.});v['sum']+=r['epa_sum'];v['n']+=r['dropbacks']
        for gid in played:
            r=schedules.loc[gid]
            for side in ('home','away'):
                q=r.get(side+'_qb_id')
                if isinstance(q,str):last_qb[canonical(r[side+'_team'])]=q
        for r in snap_groups.get((year,week),pd.DataFrame()).to_dict('records'):
            if r['game_id'] not in played:continue
            team=canonical(r['team']);date=str(schedules.loc[r['game_id'],'gameday'])
            roles[team+'|'+name_key(r['player'])].append({'id':r['pfr_player_id'],'share':max(float(r['offense_pct']),float(r['defense_pct'])),'date':date})
    return pd.DataFrame(output),{'qb_ratings':ratings,'last_qb':last_qb,'roles':dict(roles),'season':int(season),'feature_state_as_of':'AFTER_LAST_INCLUDED_COMPLETED_WEEK','qb_offseason_retention_for_next_season':.55},audit
