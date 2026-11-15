#!/usr/bin/env python3
"""Checked successor for the frozen V13 tracking CLI. New research editions only."""
import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipelines.cards import derived_missingness as M

MODEL = 'ml.v13_1.hfa1005.card.s722n30000'
PRODUCTS = ['winner','run_line','total','starter_strikeouts']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(day, slate, output):
    date.fromisoformat(day)
    slate,output = Path(slate).resolve(),Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source=ROOT/'harness/daily_card.py'
    pin=json.loads((ROOT/'harness/model_registry_pins.json').read_bytes())['sources']['harness/daily_card.py']['current']
    board={'schema':'mlb.legacy_tracking_missingness.v1','date':day,'native_source_sha256':pin,
           'status':'BLOCKED','rows':[],'coverage':[],'action_authority':False,'allocated_units':0,
           'input_vintage':'Local files as read at execution. Historical availability and opponent starter evidence require separate verification.',
           'wagering_status':'OFF'}
    try:
        if sha(source)!=pin:
            raise ValueError('LEGACY_V13_SOURCE_PIN')
        slate_bytes = slate.read_bytes()
        board['slate_sha256']=hashlib.sha256(slate_bytes).hexdigest()
        lines=[x.split('|') for x in slate_bytes.decode().splitlines() if x.strip()]
        if not lines:
            raise ValueError('EMPTY_SLATE_WITHOUT_SCHEDULE_EVIDENCE')
        counts=Counter(fields[0] for fields in lines)
        kept=[]
        for ordinal, fields in enumerate(lines):
            event_id=fields[0].strip()
            reason=None
            if len(fields)!=6 or not event_id or not all(fields[1:4]) or fields[1]==fields[2]:
                reason='INVALID_SLATE_ROW'
            elif counts[fields[0]]!=1:
                reason='DUPLICATE_EVENT_ID'
            entry={'event_id':event_id or None,'ordinal':ordinal,'reason':reason}
            board['coverage'].append(entry)
            if reason is None:
                kept.append(fields)
        if not kept:
            raise ValueError('NO_IDENTIFIABLE_SLATE_ROWS')
        cwd,argv,path_before=Path.cwd(),sys.argv,list(sys.path)
        with tempfile.TemporaryDirectory() as temp:
            subset=Path(temp)/'slate.psv'
            subset.write_text('\n'.join('|'.join(row) for row in kept)+'\n')
            raw_path=Path(temp)/'card.json'
            try:
                sys.argv=[str(source),day,str(subset),'--out',str(raw_path)]
                with redirect_stdout(io.StringIO()):
                    native=runpy.run_path(str(source), run_name='__main__')
            finally:
                sys.argv=argv
                sys.path[:]=path_before
                os.chdir(cwd)
            raw=json.loads(raw_path.read_bytes())
        if [r['gamePk'] for r in raw['rows']]!=[f[0] for f in kept] or sha(source)!=pin:
            raise ValueError('LEGACY_MODEL_READBACK_MISMATCH')
        for row in raw['rows']:
            evidence={}
            for side,team,slot in [('away',row['away'],'asp'),('home',row['home'],'hsp')]:
                profile=native['sp_asof'](row[slot])
                pitcher_id = native['IDS'].get(native['_norm'](row[slot]))
                log = ROOT/'data/backfill/mlb/2026/pitcher_logs'/f'{pitcher_id}.txt'
                evidence[side]={'team':team,'starter':row[slot],'profile_available':profile is not None,
                    'pitcher_identity_resolved':bool(pitcher_id),'pitcher_log_sha256':sha(log) if log.is_file() else None,
                    'starter_unavailable_uses_registered_cap':profile is None,
                    'team_games_in_source':native['g'].get(team,0),
                    'runs_for_used':native['team_rf'](team),'runs_against_used':native['team_ra'](team),
                    'team_league_fallback': not native['g'].get(team)}
            venue=native['venue_of'].get(row['home'])
            evidence.update(park_lookup=venue,park_default_1_applied=venue not in native['PARK'],
                            global_draw_stream_seed=722,draws_per_event=30000,
                            result_file_sha256=sha(ROOT/'data/backfill/mlb/2026/results.csv'),
                            pitcher_index_sha256=sha(ROOT/'data/backfill/mlb/2026/pitchers.csv'),
                            park_file_sha256=sha(ROOT/'data/backfill/mlb/2026/park_factors.json'),source_pin=pin)
            checked={**row,'qualification':'NO_PICK','allocation_units':0}
            M.attach(checked,'mlb',row['gamePk'],MODEL,PRODUCTS,inputs=evidence,
                     method='Frozen V13 tracking simulation; global stream consumed in admitted slate order',
                     missing=['Population support and cutoff-specific source vintage unverified'])
            board['rows'].append(checked)
        board['status']='PARTIAL' if len(kept)!=len(lines) else 'COMPLETED'
    except (OSError,ValueError,KeyError,IndexError,TypeError) as exc:
        board['reason']=str(exc)
    for entry in board['coverage']:
        if entry['event_id']:
            M.attach(entry,'mlb',entry['event_id'],MODEL,PRODUCTS,inputs={'date':day,'slate_sha256':board.get('slate_sha256')},
                     method='Declared slate coverage', missing=[entry['reason'] or board.get('reason')] if entry['reason'] or board.get('reason') else [])
    board.update(created_at_utc=datetime.now(timezone.utc).isoformat())
    dest=output/'tracking_card.json'
    with dest.open('x') as stream:
        json.dump(board,stream,indent=2,allow_nan=False)
    readback=json.loads(dest.read_bytes())
    if readback!=board:
        raise ValueError('LEGACY_TRACKING_PUBLICATION_READBACK')
    for row in readback['rows']:
        M.check(row,'mlb',row['gamePk'],MODEL,PRODUCTS)
    for row in readback['coverage']:
        if row['event_id']:
            M.check(row,'mlb',row['event_id'],MODEL,PRODUCTS)
    return readback


def run_coordinator(day, input_path, output, *, simulations=30000):
    """Retain event isolation around the legacy coordinator's keyed per-game RNG."""
    from unittest.mock import patch
    date.fromisoformat(day)
    if type(simulations) != int or simulations <= 0:
        raise ValueError('POSITIVE_SIMULATIONS_REQUIRED')
    input_path, output = Path(input_path).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    board={'schema':'mlb.legacy_daily_cycle_missingness.v1','date':day,'rows':[],
           'source_sha256':None,'status':'BLOCKED','qualification':'NO_PICK','action_authority':False,
           'allocated_units':0,'limits':'Historical PIT and complete canonical schedule remain unverified.'}
    cwd,path_before=Path.cwd(),list(sys.path)
    model_id='mlb.winner.CHAMPION_V13'
    products=['winner','home_margin','total']
    try:
        raw=input_path.read_bytes()
        board['source_sha256']=hashlib.sha256(raw).hexdigest()
        source=json.loads(raw)
        if source.get('date_et') != day:
            raise ValueError('COORDINATOR_DATE_MISMATCH')
        relay,extra=source['relay_events'],source.get('extra',[])
        if not isinstance(relay,list) or not isinstance(extra,list):
            raise ValueError('SCHEDULE_INPUT_TYPE')
        events=[(r,True) for r in relay]+[(r,False) for r in extra]
        if not events:
            raise ValueError('EMPTY_SLATE_WITHOUT_SCHEDULE_EVIDENCE')
        counts=Counter(r.get('event') for r,_ in events if isinstance(r,dict))
        sys.path.insert(0,str(ROOT/'harness'))
        import mlb_daily_coordinator as C
        import build_board_0825 as B
        board['coordinator_sha256']=sha(ROOT/'harness/mlb_daily_coordinator.py')
        for event,in_relay in events:
            key=event.get('event') if isinstance(event,dict) else None
            row={'event_id':key,'qualification':'NO_PICK','action_authority':False,'status':'BLOCKED'}
            inputs={'source_sha256':board['source_sha256'], 'coordinator_sha256':board['coordinator_sha256']}
            if not isinstance(key,str) or not key.strip():
                row['reason']='UNRESOLVED_EVENT_IDENTITY'
                board['rows'].append(row)
                continue
            try:
                if counts[key]!=1:
                    raise ValueError('DUPLICATE_EVENT_IDENTITY')
                with patch.object(B,'SLATE_DATE',day):
                    child = C.run(day, [event] if in_relay else [], extra=[] if in_relay else [event], trials=simulations)
                game,=child['games']
                row.update(forecast=game['forecast'],snapshot=game['snapshot'])
                if row['forecast'].get('p_home') is None:
                    raise ValueError('NO_FORECAST:'+','.join(game['forecast'].get('mathematical_reason',[])))
                inputs.update(starter_dispositions=game['snapshot']['starter_dispositions'],
                              registered_cap_slots=game['snapshot']['starter_slots_capped'],
                              information_dose=game['snapshot']['resolved_information_dose'],
                              lineup_state=game['forecast']['uncertainty']['lineup'],
                              seed=game['forecast']['seed'],simulations=simulations)
                overlay = {k:v for k,v in game['overlay'].items() if k not in ('execution_state','why')}
                row.update(status='DIAGNOSTIC', research_market=overlay)
            except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
                row['reason']=str(exc)
            M.attach(row,'mlb',key,model_id,products,inputs=inputs,
                     method='Starter freshness, registered caps, team form and reports from the frozen coordinator; fitted qualification pending.',
                     missing=[row['reason']] if row['status']=='BLOCKED' else ['LINEUP_NOT_POSTED','HISTORICAL_SUPPORT_UNVERIFIED'])
            board['rows'].append(row)
        completed=sum(r['status']=='DIAGNOSTIC' for r in board['rows'])
        board['status']='COMPLETED' if completed==len(events) else 'PARTIAL' if completed else 'BLOCKED'
    except (OSError,ValueError,TypeError,KeyError) as exc:
        board['reason']=str(exc)
    finally:
        os.chdir(cwd)
        sys.path[:]=path_before
    board['created_at_utc']=datetime.now(timezone.utc).isoformat()
    path=output/'tracking_card.json'
    with path.open('x') as stream:
        json.dump(board,stream,indent=2,allow_nan=False)
    saved=json.loads(path.read_bytes())
    if saved!=board:
        raise ValueError('COORDINATOR_PUBLICATION_READBACK')
    for row in saved['rows']:
        if row['event_id']:
            M.check(row,'mlb',row['event_id'],model_id,products)
    return saved


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('date');p.add_argument('slate',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--coordinator', action='store_true', help='Read a date_et/relay_events/extra JSON and run the keyed daily coordinator')
    a=p.parse_args()
    report=(run_coordinator if a.coordinator else run)(a.date,a.slate,a.output)
    print(json.dumps({'status':report['status'],'card':str(a.output/'tracking_card.json')}))
    raise SystemExit(0 if report['status']=='COMPLETED' else 2)
