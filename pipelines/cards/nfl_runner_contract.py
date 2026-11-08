"""Dated input and output contract for the opt-in integrated NFL research runner."""
import copy
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
from zoneinfo import ZoneInfo

import numpy as np

from models.nfl.contextual.recovered_inference import utc


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def write_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def load_package(args, cutoff, receipt):
    require(args.event_package is not None and args.event_package_sha256, 'NFL_PACKAGE_AND_PIN_REQUIRED')
    receipt['package_path'] = str(args.event_package.resolve())
    raw = args.event_package.read_bytes()
    receipt['package_sha256'] = sha(raw)
    require(receipt['package_sha256'] == args.event_package_sha256, 'NFL_PACKAGE_HASH_MISMATCH')
    package = json.loads(raw)
    require(package['schema'] == 'nfl.event_package.v1' and
            str(package.get('league', 'nfl')).lower() == 'nfl', 'NFL_PACKAGE_SCOPE_MISMATCH')
    require(package.get('action_authority', False) is False, 'NFL_PACKAGE_SCOPE_MISMATCH')
    require(args.date in package['covered_dates'], 'NFL_DATE_NOT_CAPTURED:' + args.date)
    require(utc(package['captured_at_utc']) <= cutoff, 'NFL_PACKAGE_AFTER_CUTOFF')
    require(args.mode == 'research_pregame' and args.simulations > 0, 'NFL_BOUND_RESEARCH_PREGAME_REQUIRED')
    require(isinstance(package['source_fetches'],list) and package['source_fetches'], 'NFL_SOURCE_RECEIPTS_REQUIRED')
    for source in package['source_fetches']:
        require(utc(source['fetched_at_utc']) <= cutoff, 'NFL_SOURCE_AFTER_CUTOFF')
    events = [e for e in package['events'] if e['gameday'] == args.date and
              (not args.event_id or e['event_id'] == args.event_id)]
    ids = [e['event_id'] for e in package['events']]
    require(len(set(ids)) == len(ids), 'NFL_DUPLICATE_EVENT_ID')
    require(events, 'NFL_REQUESTED_EVENT_NOT_CAPTURED' if args.event_id else 'NFL_EMPTY_DATED_PACKAGE')
    require(not args.home_spread or len(events) == 1, 'SPREAD_OVERLAY_REQUIRES_SINGLE_EVENT_SELECTION')
    require(not args.disclosures or args.event_id, 'DISCLOSURES_REQUIRE_EXPLICIT_EVENT_ID')
    return package, events


def validate_event(event, args, package, cutoff):
    eid = event['event_id']
    require(re.fullmatch(r'[0-9]{4}_[0-9]{2}_[A-Z0-9]+_[A-Z0-9]+', eid), 'NFL_INVALID_EVENT_ID')
    season, week, away, home = eid.split('_')
    require((away, home) == (event['away_team'], event['home_team']) and home != away, 'NFL_TEAM_BINDING')
    start = utc(event['start_time_utc'])
    scheduled = dt.datetime.fromisoformat(event['gameday'] + 'T' + event['gametime']).replace(
        tzinfo=ZoneInfo('America/New_York'))
    require(scheduled == start, 'NFL_START_TIME_BINDING')
    require(cutoff < start and (args.replay_cutoff_utc or dt.datetime.now(dt.timezone.utc) < start),
            'POST_START')
    packet = package['event_inputs'].get(eid)
    require(isinstance(packet, dict), 'NFL_EVENT_INPUT_MISSING')
    base = packet['base']
    require((str(base['season']), int(base['week']), base['game_id'], base['home_team'], base['away_team']) ==
            (season, int(week), eid, home, away), 'NFL_EVENT_INPUT_BINDING')
    state = packet['context'].get('weekly_state', {})
    if args.weekly_state_id or state or int(week) >= 3:
        require(args.weekly_state_store is not None and args.weekly_state_id,
                'NFL_EXPLICIT_WEEKLY_STORE_AND_ID_REQUIRED')
        require(args.weekly_state_id == state.get('state_id'), 'NFL_PACKAGE_WEEKLY_STATE_MISMATCH')
        from models.nfl.contextual.weekly_state import SCHEDULE_URL
        schedule_receipts = [r for r in package['source_fetches'] if r['source'] == SCHEDULE_URL]
        if len(schedule_receipts) != 1 or cutoff - utc(schedule_receipts[0]['fetched_at_utc']) > dt.timedelta(hours=6):
            raise ValueError('CURRENT_SCHEDULE_REFRESH_REQUIRED')
        require(re.fullmatch('[0-9a-f]{64}', os.environ.get('NFL_WEEKLY_STATE_SEED_SHA256', '')),
                'INDEPENDENT_OPERATOR_SEED_PIN_REQUIRED')
    return state.get('state_id')


def read_forecast(root, event, count, model_id, state_id, cutoff, model_digest):
    folder = root / event['event_id']
    manifest = json.loads((folder/'manifest.json').read_bytes())
    raw = (folder/'forecast.json').read_bytes()
    require(sha(raw) == manifest['forecast.json'], 'NFL_FORECAST_FILE_HASH_MISMATCH')
    f = json.loads(raw)
    require(f['event'] == event and f['model_id'] == model_id and f['model_artifact_sha256'] == model_digest
            and utc(f['cutoff_utc']) == cutoff,
            'NFL_FORECAST_IDENTITY_MISMATCH')
    require(f['schema'] == 'nfl.integrated_context_forecast.v1' and f['market_input'] is False and
            f['action_authority'] is False and f['canonical_prospective_eligible'] is False,
            'NFL_FORECAST_SCOPE_MISMATCH')
    if state_id:
        require((f.get('assimilation') or {}).get('state_id') == state_id, 'NFL_FORECAST_STATE_MISMATCH')
    sim = f['winner_simulation']
    with (folder/'winner_draws.npy').open('rb') as src:
        require(sha(src.read()) == manifest['winner_draws.npy'], 'NFL_DRAW_FILE_HASH_MISMATCH')
        src.seek(0)
        draws = np.load(src, allow_pickle=False)
    require(sim['count'] == count and draws.shape == (count,) and draws.dtype == np.uint8 and
            (draws <= 1).all() and sha(draws.tobytes()) == sim['sha256'] and
            float(draws.mean()) == sim['home_win_probability'], 'NFL_DRAW_READBACK_MISMATCH')
    pred = f['prediction']
    for key in ('home_win','home_margin','total_points'):
        require(type(pred[key]) in (float,int) and math.isfinite(pred[key]), 'NFL_INVALID_POINT_HEAD')
    p = pred['home_win']
    require(0 <= p <= 1, 'NFL_INVALID_WIN_PROBABILITY')
    home = p >= .5
    return {'forecast_status':'FORECAST_GENERATED', 'model_id':model_id, 'model_winner':event['home_team' if home else 'away_team'],
            'model_p':p if home else 1-p, 'sim_p':sim['home_win_probability'] if home else 1-sim['home_win_probability'],
            'projected_margin':pred['home_margin'] if home else -pred['home_margin'], 'projected_total':pred['total_points'],
            'point_head_basis':'INDEPENDENT_MARGIN_AND_TOTAL_HEADS', 'probability_scope':'BINARY_CONDITIONAL_ON_NON_TIE',
            'forecast_sha256':manifest['forecast.json'], 'draw_file_sha256':manifest['winner_draws.npy'],
            'n_simulations':count, 'weekly_state_id':state_id}


def run_bound(args, execute):
    """Write the evidence and the final exit status from the same result."""
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        print('NEW_NFL_RUN_OUTPUT_REQUIRED: ' + str(exc), file=sys.stderr)
        return 2
    receipt = {'schema':'nfl.runner_receipt.v1', 'date':args.date, 'league':'nfl','status':'BLOCKED',
               'requested_package_sha256':args.event_package_sha256, 'package_sha256':None,
               'canonical_prospective_eligible':False, 'action_authority':False, 'events':[]}
    card = {'league':'nfl', 'card_date':args.date, 'action_authority':False,
            'authority':'SHADOW_ONLY', 'canonical_prospective_eligible':False, 'actionable':False, 'simulation_count':args.simulations,
            'population':'REQUESTED_PACKAGE_EVENTS', 'forecasts':[]}
    try:
        now = dt.datetime.now(dt.timezone.utc)
        require(not (args.as_of_utc and args.replay_cutoff_utc), 'NFL_CONFLICTING_CUTOFFS')
        cutoff = utc(args.as_of_utc or args.replay_cutoff_utc or now.isoformat())
        require(cutoff <= now, 'NFL_FUTURE_CUTOFF')
        package, events = load_package(args,cutoff,receipt)
        receipt.update(cutoff_utc=cutoff.isoformat(),
                       execution_mode='RETROSPECTIVE_DIAGNOSTIC' if args.replay_cutoff_utc else 'PREGAME_DIAGNOSTIC')
        card.update(as_of_utc=cutoff.isoformat(),execution_mode=receipt['execution_mode'])
        from pipelines.cards.adapters import nfl
        model_id = args.model_id or json.loads((nfl.DATA/'runtime.json').read_bytes())['default_research_model']
        completed = 0
        for e in events:
            row = {k:e.get(k) for k in ('event_id','home_team','away_team','start_time_utc')}
            row['action_authority'] = False
            evidence = {'event_id':e['event_id'], 'status':'BLOCKED'}
            try:
                state_id = validate_event(e,args,package,cutoff)
                scoped = copy.copy(args)
                scoped.event_id = e['event_id']
                scoped.as_of_utc = cutoff.isoformat()
                execute(scoped,package)
                row.update(read_forecast(args.output,e,args.simulations,model_id,state_id,cutoff,package['model_digest']))
                row['stochastic_sim_p'] = row['sim_p']
                evidence.update(status='COMPLETED',forecast_sha256=row['forecast_sha256'],draw_file_sha256=row['draw_file_sha256'])
                completed += 1
            except (Exception, SystemExit) as exc:
                # One native refusal (or failed product subprocess) leaves other events runnable.
                evidence['reason'] = (f'NFL_NATIVE_EXIT_{exc.code}' if isinstance(exc,SystemExit)
                                      else str(exc) or type(exc).__name__)
                print(f"{e['event_id']}: {type(exc).__name__}: {exc}", file=sys.stderr)
                row.update(forecast_status='POST_START' if evidence['reason']=='POST_START' else 'BLOCKED',
                           refusal_reason=evidence['reason'])
            card['forecasts'].append(row)
            receipt['events'].append(evidence)
        from pipelines.cards.recipient_card import write_recipient_card, verify_recipient_card
        card.update(scheduled_game_count=len(events), forecast_count=completed,
                    generated_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        write_new(args.output/'diagnostic_card.json',card)
        readback=json.loads((args.output/'diagnostic_card.json').read_bytes())
        require(readback == card, 'NFL_DIAGNOSTIC_CARD_READBACK_MISMATCH')
        html = args.output/'diagnostic_card.html'
        write_recipient_card(card,html)
        verify_recipient_card(card,html)
        receipt.update(status='COMPLETED' if completed==len(events) else 'PARTIAL' if completed else 'BLOCKED',
                       card_sha256=sha((args.output/'diagnostic_card.json').read_bytes()),html_sha256=sha(html.read_bytes()))
    except Exception as exc:  # Package or presentation failure blocks the entire run.
        receipt['reason'] = str(exc) or type(exc).__name__
    write_new(args.output/'nfl_runner_receipt.json',receipt)
    print(json.dumps({'status':receipt['status'],'receipt':str(args.output/'nfl_runner_receipt.json')}))
    return 0 if receipt['status']=='COMPLETED' else 2
