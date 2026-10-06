#!/usr/bin/env python3
"""Add source-bound personnel/workload checks around the frozen postseason kernel.

This is an operator repair, not a numerical model increment. Current context is
captured and checked, but cannot be represented as USED by this limited model.
"""
import argparse
import datetime as dt
import json
import math
import platform
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.mlb_postseason_v1 import sha, stamp, instant, save_once
from scripts import mlb_postseason_workflow as W
from scripts.recovery_capture import capture
from scripts.prepare_mlb_official_current import innings_outs


def load(path):
    return json.loads(Path(path).read_text())


def source_map(root, report, now):
    result = {}
    for r in report['sources']:
        if r['kind'] in result:
            raise ValueError('DUPLICATE_SOURCE_KIND')
        path = (root / r['raw_path']).resolve()
        if (not path.is_relative_to(root.resolve()) or r['status'] != 'CAPTURED'
                or sha(path) != r['raw_sha256']):
            raise ValueError('SOURCE_BINDING')
        if not 0 <= (now - instant(r['retrieved_at_utc'])).total_seconds() <= 21600:
            raise ValueError('STALE_OR_FUTURE_SOURCE')
        result[r['kind']] = (r, load(path))
    return result


def collect_context(root, output):
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    p = load(root / 'package.json')
    sources = source_map(root / 'sources', load(root / 'sources/report.json'), instant(stamp()))
    specs = []
    teams, pitchers = set(), set()
    for e in p['events']:
        feed = sources['gamefeed_' + e['event_id'].split(':')[1]][1]
        for side in ('away', 'home'):
            teams.add(feed['gameData']['teams'][side]['id'])
            pitchers.add(e[side + '_pitcher_id'])
    for team in sorted(teams):
        specs.append(('mlb', 'roster_' + str(team), f'https://statsapi.mlb.com/api/v1/teams/{team}/roster?rosterType=active&date={p["slate_date"]}', 1))
    for pid in sorted(pitchers):
        for kind in ('F', 'D', 'L', 'W'):
            specs.append(('mlb', f'postseason_{pid}_{kind}', f'https://statsapi.mlb.com/api/v1/people/{pid}/stats?stats=gameLog&group=pitching&season={p["slate_date"][:4]}&gameType={kind}', 1))
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(lambda s: capture(output, s), specs))
    save_once(output / 'report.json', {'package_sha256': sha(root / 'package.json'),
              'sources': [r for r, data in rows], 'created_at_utc': stamp(),
              'used_as_model_input': False, 'role': 'CONTEXT_AUDIT_ONLY'})
    if any(data is None for r, data in rows):
        raise ValueError('CONTEXT_ACQUISITION_FAILED')


def finite(value):
    if isinstance(value, dict):
        for v in value.values(): finite(v)
    elif isinstance(value, list):
        for v in value: finite(v)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError('NONFINITE_INPUT')


def audit_event(e, feed, roster_by_team, history, now):
    """Hard failures are event-local. Omitted numerical features remain visible."""
    finite(e)
    if type(e['park_factor']) not in (float, int) or not .5 <= e['park_factor'] <= 1.5:
        raise ValueError('PARK_FACTOR_TYPE_OR_RANGE')
    day = dt.date.fromisoformat(e['slate_date'])
    if e['through_date'] != (day - dt.timedelta(days=1)).isoformat():
        raise ValueError('D1_FORM_MISSING')
    gd = feed['gameData']
    if (str(feed['gamePk']) != e['event_id'].split(':')[1]
            or gd['game']['type'] != e['game_type']
            or instant(gd['datetime']['dateTime']) != instant(e['start_time_utc'])):
        raise ValueError('FEED_EVENT_OR_START_CONFLICT')
    if now >= instant(e['start_time_utc']) or gd['status']['abstractGameState'] != 'Preview':
        raise ValueError('POST_START')
    row = {'event_id': e['event_id'], 'final_ready': False,
           'disposition': 'LIMITED_FEATURE_DIAGNOSTIC', 'sides': {},
           'used': ['prior_date_team_RF_RA', 'regular_season_starter_ERA_GS_K_BB', 'park_factor', 'frozen_HFA'],
           'not_used': ['batting_order', 'platoon', 'injury_effects', 'actual_bullpen_availability',
                        'postseason_starter_logs', 'announced_workload', 'weather'],
           'starter_innings_prior': {'mean': 5.4, 'sd': 1.3, 'clip': [2, 8]},
           'bullpen_model': 'TEAM_RA_LEAGUE_BLEND_NOT_CURRENT_RELIEVER_ROSTER',
           'weather_available_not_used': gd.get('weather'),
           'score_total_runline_supported': False}
    for side in ('away', 'home'):
        pid = e[side + '_pitcher_id']
        if type(pid) is not int or gd.get('probablePitchers', {}).get(side, {}).get('id') != pid:
            raise ValueError('STARTER_IDENTITY_CONFLICT')
        for k in ('era', 'gs', 'k', 'bb'):
            if type(e['sp_' + side][k]) not in (int, float): raise ValueError('STARTER_NUMERIC_TYPE')
        team = gd['teams'][side]['id']
        roster = roster_by_team[team]
        active = {r['person']['id'] for r in roster['roster'] if r['status']['code'] == 'A'}
        if pid not in active: raise ValueError('STARTER_ACTIVE_ROSTER_CONFLICT')
        box = feed['liveData']['boxscore']['teams'][side]
        order = box.get('battingOrder', [])
        if order and (len(order) != 9 or len(set(order)) != 9):
            raise ValueError('INVALID_BATTING_ORDER')
        if any(i not in active or 'ID' + str(i) not in box['players'] for i in order):
            raise ValueError('LINEUP_ROSTER_IDENTITY_CONFLICT')
        logs = []
        seen = set()
        for game in history[pid]:
            if game['date'] >= e['slate_date']: continue
            if game['player']['id'] != pid: raise ValueError('HISTORY_PITCHER_IDENTITY')
            key = str(game['game']['gamePk'])
            if key in seen: raise ValueError('DUPLICATE_PITCHER_GAME')
            seen.add(key)
            s = game['stat']; outs = innings_outs(s['inningsPitched'])
            if outs != s['outs']: raise ValueError('HISTORY_OUTS_MISMATCH')
            logs.append({'date': game['date'], 'game_type': game['gameType'], 'game_id': key,
                         'started': s['gamesStarted'], 'outs': outs,
                         'innings': outs / 3, 'pitches': s.get('numberOfPitches')})
        logs.sort(key=lambda x: (x['date'], x['game_id']))
        starts = [g for g in logs if g['started'] == 1][-5:]
        row['sides'][side] = {'pitcher_id': pid, 'pitcher': e[side + '_starter'],
                            'active_roster_match': True, 'lineup_status': 'POSTED_NOT_USED' if order else 'MISSING_NOT_USED',
                            'lineup_ids': order, 'lineup_names': [box['players']['ID' + str(i)]['person']['fullName'] for i in order],
                            'regular_season_GS_used': e['sp_' + side]['gs'],
                            'recent_appearances_not_used': logs[-5:],
                            'last_five_starts_mean_innings_not_used': sum(g['outs'] for g in starts) / (3 * len(starts)) if starts else None}
    return row


def run(root, context, contract, review, output):
    root, context, output = map(Path, (root, context, output))
    if output.exists():
        raise ValueError('OUTPUT_MUST_BE_NEW_USE_VERIFY_FOR_REPLAY')
    p, r = W.verify_package(root, contract, review)
    ctx = load(context / 'report.json'); now = instant(stamp())
    if ctx['package_sha256'] != sha(root / 'package.json') or r.get('context_report_sha256') != sha(context / 'report.json'):
        raise ValueError('CONTEXT_REVIEW_BINDING')
    src = source_map(root / 'sources', load(root / 'sources/report.json'), now)
    extra = source_map(context, ctx, now)
    if max(instant(rec['retrieved_at_utc']) for rec, data in extra.values()) > instant(r['reviewed_at_utc']):
        raise ValueError('CONTEXT_REVIEW_CHRONOLOGY')
    rosters = {int(k.split('_')[1]): data for k, (rec, data) in extra.items() if k.startswith('roster_')}
    history = {}
    for k, (rec, data) in {**src, **extra}.items():
        if k.startswith(('pitcher_', 'postseason_')):
            pid = int(k.split('_')[1]); history.setdefault(pid, [])
            history[pid].extend(s for group in data.get('stats', []) for s in group.get('splits', []))
    output.mkdir(parents=True, exist_ok=False)
    rows, runs = [], []
    for e in p['events']:
        eid = e['event_id']
        try:
            if eid not in r['reviewed_event_ids']: raise ValueError('AGENT_REVIEW_MISSING')
            for side in ('away', 'home'):
                pid=e[side+'_pitcher_id']
                if any(f'postseason_{pid}_{phase}' not in extra for phase in ('F','D','L','W')):
                    raise ValueError('POSTSEASON_CONTEXT_CENSUS_MISSING')
            manual = r.get('event_context', {}).get(eid, {})
            if not all(isinstance(manual.get(k), str) and manual[k].strip() for k in ('pitching_plan', 'availability_review')):
                raise ValueError('EVENT_CONTEXT_REVIEW_MISSING')
            row = audit_event(e, src['gamefeed_' + eid.split(':')[1]][1], rosters, history, instant(stamp()))
            row['manual_review'] = manual
            run_row = W.run_event(e, output / 'runs', root / 'package.json', contract, review)
            row['verification'] = W.verify_run(run_row['path'])
            row['forecast_path'] = run_row['path']; runs.append(run_row)
        except (ValueError, KeyError) as exc:
            row = {'event_id': eid, 'disposition': 'BLOCKED', 'reason': str(exc), 'final_ready': False}
        rows.append(row)
    result = {'created_at_utc': stamp(), 'schema': 'mlb.postseason.operational_audit.v1',
              'code_sha256': sha(__file__), 'package_sha256': sha(root / 'package.json'),
              'context_report_sha256': sha(context / 'report.json'), 'review_sha256': sha(review),
              'rows': rows, 'runs': runs, 'official_release_eligible': False,
              'action_authority': False, 'dose': 0.0, 'predictive_validation': 'UNVALIDATED'}
    result['execution_code_pins'] = {str(Path(m.__file__).resolve().relative_to(ROOT)): sha(m.__file__)
          for m in list(sys.modules.values()) if getattr(m, '__file__', None)
          and Path(m.__file__).resolve().is_relative_to(ROOT) and Path(m.__file__).is_file()}
    result['runtime'] = {'python': platform.python_version(), 'numpy': W.np.__version__}
    save_once(output / 'audit.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('collect-context'); c.add_argument('--root', type=Path, required=True); c.add_argument('--output', type=Path, required=True)
    r = sub.add_parser('run')
    for key in ('root', 'context', 'contract', 'review', 'output'): r.add_argument('--' + key, type=Path, required=True)
    a = parser.parse_args()
    if a.command == 'collect-context': collect_context(a.root.resolve(), a.output.resolve())
    else:
        result = run(a.root.resolve(), a.context.resolve(), a.contract.resolve(), a.review.resolve(), a.output.resolve())
        print(json.dumps({'rows': result['rows'], 'runs': len(result['runs'])}, indent=2))


if __name__ == '__main__': main()
