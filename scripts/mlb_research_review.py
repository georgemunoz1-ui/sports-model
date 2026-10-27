#!/usr/bin/env python3
"""Review event evidence, then execute explicitly reviewed limited-feature research.

No official release, promotion, prospective registration, or wager authority.
The collect and run phases are separate so an agent can inspect actual evidence.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models.current import common
from scripts.recovery_capture import capture, save_json
from scripts.verify_nfl_weekly_sources import manifest

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def now():
    return dt.datetime.now(dt.timezone.utc)

def blockers(event, feed, package, clock):
    failures = []
    gd = feed.get('gameData', {})
    if str(feed.get('gamePk')) != event['event_id'].split(':')[1]:
        failures.append('EVENT_ID_MISMATCH')
    if common.utc(event['start_time_utc']) <= clock or gd.get('status', {}).get('abstractGameState') != 'Preview':
        failures.append('POST_START_OR_NOT_PREVIEW')
    if gd.get('datetime', {}).get('dateTime') != event['start_time_utc']:
        failures.append('START_TIME_CHANGED')
    for side in ('away', 'home'):
        pid = event[side+'_pitcher_id']
        if not isinstance(pid, int):
            failures.append(side.upper()+'_STARTER_UNKNOWN')
        elif gd.get('probablePitchers', {}).get(side, {}).get('id') != pid:
            failures.append(side.upper()+'_STARTER_CHANGED')
        elif str(pid) not in package['starter_state'] or package['starter_state'][str(pid)].get('treatment'):
            failures.append(side.upper()+'_OBSERVED_STARTER_PROFILE_MISSING')
    return failures

def collect(readiness, output):
    output.mkdir(parents=True, exist_ok=False)
    manifest(readiness, 'manifest.json')
    r = json.loads((readiness/'readiness.json').read_text())
    if r['errors'] or r['source_failures']:
        raise ValueError('READINESS_SOURCE_OR_PBP_FAILURE')
    os.environ['SPORTS_RESEARCH_PACKAGE_DIR'] = str((readiness/'packages').resolve())
    package, ph = common.load('mlb')
    common.current(package, now().isoformat())
    source = readiness/'sources'
    receipts = json.loads((source/'report.json').read_text())['sources']
    gamefeeds = {}
    for rec in receipts:
        if rec['kind'] == 'current_event_feed':
            j = json.loads((source/rec['raw_path']).read_text())
            gamefeeds['MLB:'+str(j['gamePk'])] = (j, rec)
    team_ids = sorted({t['id'] for j, rec in gamefeeds.values() for t in j['gameData']['teams'].values()})
    day = r['requested_date']
    specs = [('mlb', 'official_roster', f'https://statsapi.mlb.com/api/v1/teams/{tid}/roster?rosterType=fullRoster&season={day[:4]}', 1) for tid in team_ids]
    specs += [('mlb', 'official_transactions', f'https://statsapi.mlb.com/api/v1/transactions?startDate={day}&endDate={day}', 1),
              ('mlb', 'provider_injuries', 'https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/injuries?limit=1000', 2)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        captured = list(pool.map(lambda s: capture(output, s), specs))
    save_json(output/'sources.json', {'sources':[rec for rec, j in captured]})
    rosters = {int(rec['url'].split('/teams/')[1].split('/')[0]): (j, rec) for rec,j in captured if rec['kind']=='official_roster' and j}
    injuries = next(((j,rec) for rec,j in captured if rec['kind']=='provider_injuries' and j), (None,None))
    usage = {}
    for rec in receipts:
        if rec['kind'] != 'prior_day_pbp': continue
        j = json.loads((source/rec['raw_path']).read_text())
        for side, box in j['liveData']['boxscore']['teams'].items():
            tid = box['team']['id']
            for pid in box['pitchers']:
                pl = box['players']['ID'+str(pid)]
                s = pl['stats']['pitching']
                usage.setdefault(tid, []).append({'player_id':pid,'name':pl['person']['fullName'], 'pitches':s.get('numberOfPitches'), 'outs':s.get('outs'), 'games_started':s.get('gamesStarted'), 'source_sha256':rec['raw_sha256']})
    events = {e['event_id']:e for e in package['events']}
    rows=[]
    clock=now()
    for disposition in r['event_dispositions']:
        eid=disposition['event_id']; feed,fr=gamefeeds[eid]; gd=feed['gameData']; e=events.get(eid)
        row={'event_id':eid,'start_time_utc':disposition['start_time_utc'],
             'feed_sha256':fr['raw_sha256'],'feed_retrieved_at_utc':fr['retrieved_at_utc'],
             'provider_confirmation_time':None,'provider_confirmation_time_status':'NOT_SUPPLIED',
             'weather_available_not_consumed':gd.get('weather',{}),'teams':{},
             'mandatory_research_blockers':blockers(e,feed,package,clock) if e else ['EVENT_NOT_IN_CURRENT_PACKAGE'],
             'full_event_validation_complete':False,'official_release_eligible':False}
        for side in ('away','home'):
            tid=gd['teams'][side]['id']; box=feed['liveData']['boxscore']['teams'][side]
            roster, rr=rosters.get(tid,({},{})); pid=gd.get('probablePitchers',{}).get(side,{}).get('id')
            match=next((x for x in roster.get('roster',[]) if x['person']['id']==pid),None)
            posted=box.get('battingOrder',[])
            if len(posted) not in (0,9) or len(set(posted))!=len(posted): row['mandatory_research_blockers'].append(side.upper()+'_LINEUP_IDENTITY_CONFLICT')
            if match and match.get('status',{}).get('code')!='A':row['mandatory_research_blockers'].append(side.upper()+'_PROBABLE_STARTER_ROSTER_NOT_ACTIVE')
            row['teams'][side]={'team':gd['teams'][side]['name'],'starter':gd.get('probablePitchers',{}).get(side),
                'starter_state':'STARTER_UNKNOWN' if pid is None else 'OFFICIAL_PROBABLE_NOT_CONFIRMED',
                'roster_status':match.get('status') if match else None,
                'roster_retrieved_at_utc':rr.get('retrieved_at_utc'),'lineup_player_ids':posted,
                'lineup_status':'POSTED_IN_OFFICIAL_FEED' if len(posted)==9 else 'UNPUBLISHED_IN_CAPTURE',
                'lineup_observed_at_utc':fr['retrieved_at_utc'] if posted else None,
                'prior_day_pitcher_usage_available_not_consumed':usage.get(tid,[]),
                'bullpen_full_availability':'NOT_ESTABLISHED',
                'roster_nonactive':[x for x in roster.get('roster',[]) if x.get('status',{}).get('code')!='A']}
        row['injury_source_retrieved_at_utc']=injuries[1]['retrieved_at_utc'] if injuries[1] else None
        row['injury_numeric_effect']='NOT_CONSUMED_BY_SELECTED_MODEL'
        row['full_validation_remaining']=['CONFIRMED_STARTER_TIMESTAMPS','COMPLETE_INJURY_EFFECTIVE_TIMES','FULL_BULLPEN_AVAILABILITY','FINAL_EVENT_CUTOFF_RECHECK']
        if any(t['lineup_status']!='POSTED_IN_OFFICIAL_FEED' for t in row['teams'].values()):row['full_validation_remaining'].append('BOTH_POSTED_LINEUPS')
        if not row['weather_available_not_consumed']:row['full_validation_remaining'].append('VENUE_WEATHER')
        for side in ('away','home'):
            if row['teams'][side].get('starter') is None and side.upper()+'_STARTER_UNKNOWN' not in row['mandatory_research_blockers']:
                row['mandatory_research_blockers'].append(side.upper()+'_STARTER_UNKNOWN')
        rows.append(row)
    # Attach only provider quotes that exactly match official home/away identities and start time.
    def quote_line(value):
        if value is None: return None
        if isinstance(value,(int,float)): return float(value)
        value=str(value).strip().lower()
        if value.startswith('o') or value.startswith('u'): value=value[1:]
        try: return float(value)
        except (TypeError,ValueError): return None
    for row in rows:
        row['market_quotes'] = []
        row['market_quote_status'] = 'MISSING_CURRENT_QUOTE'
        target_start = common.utc(row['start_time_utc'])
        target_home = row['teams']['home']['team'].strip().lower()
        target_away = row['teams']['away']['team'].strip().lower()
        for rec in receipts:
            if rec.get('kind') != 'provider_schedule' or 'baseball/mlb' not in rec.get('url','') or rec.get('status') != 'CAPTURED':
                continue
            raw_path = source / rec['raw_path']
            if not raw_path.exists(): continue
            try: payload = json.loads(raw_path.read_text())
            except Exception: continue
            for pe in payload.get('events',[]):
                comps = pe.get('competitions') or []
                if not comps: continue
                comp = comps[0]
                by_side = {x.get('homeAway'):x.get('team',{}).get('displayName') for x in comp.get('competitors',[])}
                if (str(by_side.get('home','')).strip().lower() != target_home or
                    str(by_side.get('away','')).strip().lower() != target_away):
                    continue
                try:
                    if common.utc(pe['date']) != target_start: continue
                except Exception:
                    continue
                for odds in comp.get('odds',[]):
                    ps = odds.get('pointSpread',{}); total = odds.get('total',{}); ml = odds.get('moneyline',{})
                    quote = {
                        'provider_event_id':pe.get('id'),'provider_event_name':pe.get('name'),
                        'book':odds.get('provider',{}).get('name'),
                        'source':'ESPN provider scoreboard snapshot',
                        'quote_timestamp_utc':rec.get('retrieved_at_utc'),
                        'provider_observed_at_utc':None,
                        'source_sha256':rec.get('raw_sha256'),
                        'home_line':quote_line(ps.get('home',{}).get('close',{}).get('line')),
                        'away_line':quote_line(ps.get('away',{}).get('close',{}).get('line')),
                        'home_odds':ps.get('home',{}).get('close',{}).get('odds'),
                        'away_odds':ps.get('away',{}).get('close',{}).get('odds'),
                        'total_over_line':quote_line(total.get('over',{}).get('close',{}).get('line')),
                        'total_under_line':quote_line(total.get('under',{}).get('close',{}).get('line')),
                        'total_over_odds':total.get('over',{}).get('close',{}).get('odds'),
                        'total_under_odds':total.get('under',{}).get('close',{}).get('odds'),
                        'moneyline_home_odds':ml.get('home',{}).get('close',{}).get('odds'),
                        'moneyline_away_odds':ml.get('away',{}).get('close',{}).get('odds')
                    }
                    quote['spread_line_status'] = 'CAPTURED' if quote['home_line'] is not None and quote['away_line'] is not None else 'MISSING'
                    quote['spread_odds_status'] = 'CAPTURED' if quote['home_odds'] is not None and quote['away_odds'] is not None else 'MISSING'
                    row['market_quotes'].append(quote)
        if row['market_quotes']:
            row['market_quote_status'] = 'CAPTURED'
    report={'schema':'mlb.agent_review_input.v1','created_at_utc':clock.isoformat(),'package_sha256':ph,
        'readiness_manifest_sha256':sha(readiness/'manifest.json'),'events':rows,
        'available_not_used':['lineup','roster/injury','weather','prior_day_bullpen_usage'],
        'used':['D-1_team_form','starter_ERA_GS_K_BB','frozen_park_and_HFA'],
        'source_failures':[rec for rec,j in captured if not j], 'action_authority':False}
    save_json(output/'review.json',report)
    save_json(output/'manifest.json',{str(f.relative_to(output)):sha(f) for f in output.rglob('*') if f.is_file()})
    print(json.dumps({'review_sha256':sha(output/'review.json'),'events':[{'id':e['event_id'],'blockers':e['mandatory_research_blockers'],'lineups':[t['lineup_status'] for t in e['teams'].values()]} for e in rows]},indent=2))

def run(readiness, review, expected, approval, output):
    from pipelines.cards.adapters import mlb
    import numpy as np
    if sha(review/'review.json')!=expected:raise ValueError('REVIEW_HASH_MISMATCH')
    manifest(readiness,'manifest.json');manifest(review,'manifest.json')
    reviewed=json.loads((review/'review.json').read_text());approval=json.loads(approval.read_text())
    if approval['review_sha256']!=expected or approval['decision']!='LIMITED_FEATURE_RESEARCH_ONLY':raise ValueError('REVIEW_DECISION_MISMATCH')
    if not 0 <= (now()-common.utc(approval['reviewed_at_utc'])).total_seconds() <= 1800:raise ValueError('REVIEW_TIME_STALE_OR_FUTURE')
    output.mkdir(parents=True,exist_ok=False)
    os.environ['SPORTS_RESEARCH_PACKAGE_DIR']=str((readiness/'packages').resolve())
    os.environ['SPORTS_RESEARCH_DRAW_OUTPUT']=str((output/'draws').resolve())
    package,ph=common.load('mlb')
    if ph!=reviewed['package_sha256']:raise ValueError('REVIEW_PACKAGE_MISMATCH')
    approved=set(approval['approved_event_ids']);known={e['event_id'] for e in reviewed['events']}
    if not approved<=known:raise ValueError('APPROVAL_UNKNOWN_EVENT')
    cutoff=now().isoformat();common.current(package,cutoff)
    for row in reviewed['events']:
        if row['event_id'] in approved and not 0 <= (common.utc(cutoff)-common.utc(row['feed_retrieved_at_utc'])).total_seconds() <= 1800:
            raise ValueError('EVENT_FEED_STALE_OR_FUTURE:'+row['event_id'])
    save_json(output/'agent-review.json',approval)
    rows=[];events={e['event_id']:e for e in package['events']}
    for source_row in reviewed['events']:
        row=dict(source_row); eid=row['event_id']; e=events.get(eid)
        event_start=common.utc(row['start_time_utc'])
        post_start=event_start <= common.utc(cutoff)
        row['disposition']='POST_START' if post_start else 'PRE_START'
        row['winner_status']='UNAVAILABLE'
        row['winner_gate']='EVENT_NOT_IN_CURRENT_PACKAGE' if e is None else 'LIMITED_FEATURE_RESEARCH_NOT_APPROVED'
        row['forecast']=None
        row['cover']={
            'status':'POST_START' if post_start else 'UNAVAILABLE',
            'disposition':'POST_START' if post_start else 'PRE_START',
            'gate':'START_TIME_PASSED_BEFORE_CUTOFF' if post_start else 'UNSUPPORTED_SETTLEMENT',
            'selected_winner_model':'mlb.v13_and_d_logistic_2f.research.v1',
            'distribution_arm':None,
            'parent_model_id':None,
            'settlement_horizon':'UNSUPPORTED_SETTLEMENT',
            'adapter_limitation':'V13_TIE_PROXY_NOT_FULL_EXTRA_INNINGS',
            'market_quotes':row.get('market_quotes',[]),
            'predictive_validation':'NOT_ESTABLISHED',
            'action_authority':False
        }
        if post_start:
            row['winner_status']='POST_START'
            rows.append(row); continue
        if e is None:
            row['winner_gate']='EVENT_NOT_IN_CURRENT_PACKAGE'
            row['cover']['gate']='UNSUPPORTED_SETTLEMENT'
            row['cover']['additional_gate']='EVENT_NOT_IN_CURRENT_PACKAGE'
            row['cover']['next_evidence']='Registered postseason package/event adapter and a full-game run distribution with explicit extra-inning settlement; source-bound starter confirmation is also required.'
            rows.append(row); continue
        if eid not in approved or row['mandatory_research_blockers']:
            row['winner_status']='UNAVAILABLE'
            row['winner_gate']='RESEARCH_INPUT_BLOCKER' if row['mandatory_research_blockers'] else 'NOT_APPROVED_FOR_EXECUTION'
            row['cover']['gate']='UNSUPPORTED_SETTLEMENT'
            row['cover']['additional_gate']=row['winner_gate']
            row['cover']['next_evidence']='Resolve the exact winner-input gate and register a compatible full-game runline distribution arm; do not infer cover from win probability.'
            rows.append(row); continue
        if common.utc(e['start_time_utc'])<=now():
            row['disposition']='POST_START';row['winner_status']='POST_START'
            row['cover']={'status':'POST_START','disposition':'POST_START','gate':'START_TIME_PASSED_BEFORE_CUTOFF','action_authority':False}
            rows.append(row);continue
        try:
            raw=mlb.forecast_event(e,mlb.build_context([e],cutoff),100000)
            directory=Path(raw['simulation']['draw_directory']);draws=np.load(directory/'hw.npy',allow_pickle=False)
            if len(draws)!=100000 or float(draws.mean())!=raw['simulation']['home_win_probability']:
                raise ValueError('DRAW_REPLAY_MISMATCH')
            created=now()
            if created>=common.utc(e['start_time_utc']):
                row['disposition']='POST_START';row['winner_status']='POST_START'
                row['cover']={'status':'POST_START','disposition':'POST_START','gate':'START_TIME_PASSED_BEFORE_CUTOFF','action_authority':False}
            else:
                row['disposition']='PRE_START';row['winner_status']='NUMERICAL_RESEARCH_OUTPUT'
                row['forecast']=raw;row['cutoff_utc']=cutoff;row['created_at_utc']=created.isoformat()
                row['canonical_prospective_registration']=False
                row['registration_reason']='LOCAL_DIAGNOSTIC_RECORD_NOT_CANONICAL_WRITER_REGISTRATION'
                row['cover']={
                    'status':'UNAVAILABLE','disposition':'PRE_START','gate':'UNSUPPORTED_SETTLEMENT',
                    'selected_winner_model':raw.get('model_id'),
                    'distribution_arm':None,'parent_model_id':None,
                    'settlement_horizon':'UNSUPPORTED_SETTLEMENT',
                    'adapter_limitation':raw.get('spread_or_runline'),
                    'market_quotes':row.get('market_quotes',[]),
                    'predictive_validation':'NOT_ESTABLISHED','action_authority':False,
                    'next_evidence':'Registered full-game runline distribution and explicit extra-inning settlement contract; do not infer from winner draws.'
                }
                save_json(output/'events'/(eid.replace(':','_')+'.json'),row)
        except Exception as exc:
            row['winner_status']='UNAVAILABLE'
            row['winner_gate']='EXECUTION_ERROR:'+type(exc).__name__+':'+str(exc)
            row['cover']['status']='UNAVAILABLE'
            row['cover']['gate']='UNSUPPORTED_SETTLEMENT'
            row['cover']['additional_gate']=row['winner_gate']
            row['execution_error']=type(exc).__name__+':'+str(exc)
        rows.append(row)
    blockers_out=[{'event_id':r['event_id'],'winner_gate':r.get('winner_gate'),'cover_gate':(r.get('cover') or {}).get('gate'),
                   'additional_gate':(r.get('cover') or {}).get('additional_gate')} for r in rows
                  if r.get('winner_status') in ('UNAVAILABLE','POST_START') or (r.get('cover') or {}).get('status')=='UNAVAILABLE']
    result={'schema':'mlb.reviewed_research_board.v1','status':'PARTIAL_RESEARCH_WITH_SCOPED_BLOCKERS' if blockers_out else 'EXECUTED_RESEARCH_ONLY',
            'package_sha256':ph,'review_sha256':expected,
            'cutoff_utc':cutoff,'created_at_utc':now().isoformat(),'events':rows,
            'blockers':blockers_out,
            'cover_coverage':{'expected_events':len(rows),
                              'completed':sum(1 for r in rows if (r.get('cover') or {}).get('status')=='COMPLETED'),
                              'blocked':sum(1 for r in rows if (r.get('cover') or {}).get('status')=='UNAVAILABLE'),
                              'post_start':sum(1 for r in rows if (r.get('cover') or {}).get('status')=='POST_START')},
            'official_release_eligible':False,'action_authority':False,'dose':0.0}
    save_json(output/'board.json',result)
    save_json(output/'summary.json',result)
    save_json(output/'manifest.json',{str(f.relative_to(output)):sha(f) for f in output.rglob('*') if f.is_file()})
    print(json.dumps([{'id':r['event_id'],'disposition':r['disposition'],'winner_status':r.get('winner_status'),
                       'winner':(r.get('forecast') or {}).get('model_winner'),
                       'model_p':(r.get('forecast') or {}).get('model_p'),
                       'sim_p':(r.get('forecast') or {}).get('sim_p'),
                       'cover':r.get('cover'),'winner_gate':r.get('winner_gate'),
                       'error':r.get('execution_error')} for r in rows],indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['collect','run']);p.add_argument('--readiness',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--review',type=Path);p.add_argument('--review-sha256');p.add_argument('--approval',type=Path);a=p.parse_args()
    if a.phase=='collect':collect(a.readiness,a.output)
    else:run(a.readiness,a.review,a.review_sha256,a.approval,a.output)
