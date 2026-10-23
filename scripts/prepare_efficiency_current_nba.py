#!/usr/bin/env python3
"""Normalize captured ESPN current NBA finals/events; no invented historic observation times."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, pathlib

def timestamp(value):
    if not isinstance(value,str):raise ValueError('missing start time')
    return dt.datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(dt.timezone.utc).isoformat()

def source(rec):
    return {'source':rec['url'],'sha256':rec['sha256'],'retrieved_at_utc':rec['retrieved_at_utc'],'observed_at_utc':None}

def competitors(event):
    comp=event['competitions'][0]; rows=comp['competitors']
    if len(rows)!=2 or {r['homeAway'] for r in rows}!={'home','away'}:raise ValueError('ambiguous home/away')
    pairs={r['homeAway']:r for r in rows}
    if pairs['home']['team']['id']==pairs['away']['team']['id']:raise ValueError('duplicate team identity')
    return comp,pairs

def event_row(event,rec,season):
    comp,pairs=competitors(event)
    final=bool(comp.get('status',event.get('status',{})).get('type',{}).get('completed'))
    row={'event_id':'NBA:'+str(event['id']),'start_time_utc':timestamp(event.get('date',comp.get('date'))),
         'season':int(season),'neutral_site':bool(comp.get('neutralSite',False)),
         'final':final,'sources':[source(rec)],'historical_availability_proven':False}
    for side in ('home','away'):
        t=pairs[side];row[side+'_id']=str(t['team']['id']);row[side+'_team']=t['team']['displayName']
        if final: row[side+'_score']=int(t['score'])
    return row

def pair(value):
    a,b=value.split('-');return int(a),int(b)

def team_stats(team):
    s={v['name']:v['displayValue'] for v in team['statistics']}
    fg=pair(s['fieldGoalsMade-fieldGoalsAttempted']);tp=pair(s['threePointFieldGoalsMade-threePointFieldGoalsAttempted']);ft=pair(s['freeThrowsMade-freeThrowsAttempted'])
    return dict(fgm=fg[0],fga=fg[1],fg3m=tp[0],fg3a=tp[1],ftm=ft[0],fta=ft[1],orb=int(s['offensiveRebounds']),drb=int(s['defensiveRebounds']),tov=int(s['totalTurnovers']))

def main():
    p=argparse.ArgumentParser();p.add_argument('--capture-dir',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args()
    report=json.loads((a.capture_dir/'report.json').read_text());history=[];future={};excluded=[];now=dt.datetime.now(dt.timezone.utc)
    for r in report['sources']:
        if r['league']!='nba' or r['status']!='CAPTURED':continue
        raw=(a.capture_dir/r['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=r['sha256']:raise ValueError('source hash mismatch')
        j=json.loads(raw)
        if r['dataset']=='scoreboard':
            for e in j.get('events',[]):
                row=event_row(e,r,e['season']['year'])
                if not row['final'] and dt.datetime.fromisoformat(row['start_time_utc'])>now:
                    future[row['event_id']]=row
        elif r['dataset']=='summary':
            try:
                h=j['header'];row=event_row(h,r,h['season']['year'])
                if not row['final']:raise ValueError('not final')
                comp,pairs=competitors(h)
                periods={len(t['linescores']) for t in pairs.values()}
                if len(periods)!=1:raise ValueError('period line-score disagreement')
                row['periods']=periods.pop()
                if row['periods']<4:raise ValueError('incomplete regulation')
                row['duration_minutes']=48+5*(row['periods']-4)
                row['periods_source']='COMPLETED_COMPETITOR_LINESCORES'
                row['result_available_at_utc']=r['retrieved_at_utc'];row['availability_semantics']='FIRST_OBSERVED_BY_THIS_CAPTURE_NOT_GAME_END'
                byid={str(x['team']['id']):x for x in j['boxscore']['teams']}
                if set(byid)!={row['home_id'],row['away_id']}:raise ValueError('box team identity mismatch')
                for side in ('home','away'):
                    stats=team_stats(byid[row[side+'_id']]);row[side+'_stats']=stats
                    if 2*stats['fgm']+stats['fg3m']+stats['ftm']!=row[side+'_score']:raise ValueError('shooting score mismatch')
                player_teams={str(t['team']['id']):t for t in j['boxscore']['players']}
                row['minutes_decimal_places']=0
                row['overtime_periods']=row['periods']-4
                for side in ('home','away'):
                    block=player_teams[row[side+'_id']]['statistics'][0]
                    labels=block['labels'];players=[]
                    for athlete in block['athletes']:
                        vals=dict(zip(labels,athlete.get('stats',[])))
                        dnp=athlete.get('didNotPlay')
                        if not vals and dnp is not True:raise ValueError('missing active player production')
                        player={'player_id':str(athlete['athlete']['id']),'name':athlete['athlete']['displayName'],
                                'status':'DNP' if dnp else 'PLAYED','source_reason':athlete.get('reason')}
                        for target,label in [('points','PTS'),('minutes','MIN'),('orb','OREB'),('drb','DREB')]:
                            if label in vals:player[target]=int(vals[label])
                            elif dnp:player[target]=0
                            else:raise ValueError('missing player field '+label)
                        players.append(player)
                    row[side+'_players']=players
                history.append(row)
            except (ValueError,KeyError,TypeError) as e:excluded.append({'source':source(r),'reason':str(e),'event_id':r.get('event_id')})
    output={'schema':'nba-current-efficiency-normalized-v1','created_at_utc':now.isoformat(),'history':sorted(history,key=lambda x:x['start_time_utc']),'future_events':sorted(future.values(),key=lambda x:(x['start_time_utc'],x['event_id'])),'excluded':excluded,'action_authority':False}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as f:json.dump(output,f,indent=2)
    print(json.dumps({'history':len(history),'future_events':len(future),'excluded':excluded}))
if __name__=='__main__':main()
