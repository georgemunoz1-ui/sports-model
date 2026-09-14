#!/usr/bin/env python3
"""Rebuild current sports state from an explicit, immutable acquisition bundle.

Acquire through the environment's approved web/GitHub tools first. An empty or
failed acquisition stays unacquired; this command never invents a slate.
"""
import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.current_sports_data import (LEAGUES, immutable_json, instant, league_status,
    local_date, parse_sports_extract, receipt, reconcile, slate_clock)


def wnba_box(path, rec):
    j = json.loads(path.read_text())
    header = j['header']
    competition = header['competitions'][0]
    if int(header['season']['type']) != 2:
        raise ValueError('WNBA_NON_REGULAR_SEASON')
    if not competition['status']['type']['completed']:
        raise ValueError('WNBA_NOT_FINAL')
    if instant(competition['date']) >= instant(rec['retrieved_at']):
        raise ValueError('WNBA_FUTURE_FINAL')
    sides = {c['homeAway']: c for c in competition['competitors']}
    box = {str(t['team']['id']): t for t in j['boxscore']['teams']}
    rename = {'NY': 'NYL', 'LA': 'LAS', 'GS': 'GSV', 'POR': 'PDX', 'WSH': 'WAS', 'LV': 'LVA'}
    result = {'gid': str(header['id']), 'season': int(header['season']['year']),
              'utc_instant': competition['date'], 'et_date': local_date(competition['date'], 'America/New_York'),
              'source_sha256': rec['sha256'], 'retrieved_at': rec['retrieved_at'],
              'source_available_at': rec['source_available_at']}
    result['date'] = result['et_date']
    for side, slot, score_key in [('home', 'H', 'hpts'), ('away', 'A', 'apts')]:
        c = sides[side]
        tm = box[str(c['team']['id'])]
        stats = {s['name']: s['displayValue'] for s in tm['statistics']}
        ab = c['team']['abbreviation']
        result[side] = rename.get(ab, ab)
        row = {'team': result[side], 'pts': int(c['score'])}
        for key, pair in [('fieldGoalsMade-fieldGoalsAttempted', ('fgm', 'fga')),
                          ('threePointFieldGoalsMade-threePointFieldGoalsAttempted', ('fg3m', 'fg3a')),
                          ('freeThrowsMade-freeThrowsAttempted', ('ftm', 'fta'))]:
            made, attempted = map(int, stats[key].split('-'))
            if not 0 <= made <= attempted:
                raise ValueError('INVALID_BOX_COUNTS')
            row[pair[0]], row[pair[1]] = made, attempted
        row['oreb'], row['tov'] = int(stats['offensiveRebounds']), int(stats['totalTurnovers'])
        if 2 * row['fgm'] + row['fg3m'] + row['ftm'] != row['pts']:
            raise ValueError('BOX_SCORE_POINTS_MISMATCH')
        result[slot], result[score_key] = row, row['pts']
    return result


def cfb_score_observations(text, rec):
    """Capture complete four-quarter rows only; incomplete/OT layouts stay raw.

    These observations are not a complete FBS census or a play-by-play feature
    backfill. Do not invent kickoff times from scoreboard calendar headings.
    """
    text = re.sub(r'L\d+: ?', '\n', text)
    text = re.sub(r'\ue200cite\ue202[^†\ue201]*†([^\ue201]*)\ue201', r'\1', text)
    teams = []
    pattern = re.compile(r'([^\n]+)\n+\([^\n]+\)\n+(\d+)\n+(\d+)\n+(\d+)\n+(\d+)\n+(\d+)')
    for m in pattern.finditer(text):
        headings = re.findall(r'### (\w+, \w+ \d+, \d{4})', text[:m.start()])
        if not headings:
            continue
        points = list(map(int, m.groups()[1:]))
        if sum(points[:4]) != points[4]:
            continue
        day = dt.datetime.strptime(headings[-1], '%A, %B %d, %Y').date().isoformat()
        teams.append({'team': m[1].strip(' *'), 'date': day, 'quarter_points': points[:4], 'total': points[4], 'source_sha256': rec['sha256']})
    return teams


def mls_schedule_extract(text, rec):
    """ESPN table is HOME then AWAY. Unspecified time zones remain unresolved."""
    text = re.sub(r'\ue200cite\ue202[^†\ue201]*†([^\ue201]*)\ue201', r'\1', text)
    text = re.sub(r'L\d+: ?', '\n', text)
    day, rows = None, []
    for raw in text.splitlines():
        line = raw.strip()
        if re.fullmatch(r'\w+, \w+ \d+, \d{4}', line):
            day = dt.datetime.strptime(line, '%A, %B %d, %Y').date().isoformat()
        if not day or ' | ' not in line:
            continue
        parts = [x.strip() for x in line.split('|')]
        if len(parts) < 4:
            continue
        final = re.fullmatch(r'(\d+)\s*-\s*(\d+)\s+(.+)', parts[1])
        upcoming = re.fullmatch(r'v\s+(.+)', parts[1])
        if final and parts[2] == 'FT':
            away, hpts, apts, status = final[3], int(final[1]), int(final[2]), 'final'
        elif upcoming:
            away, hpts, apts, status = upcoming[1], None, None, 'scheduled'
        else:
            continue
        import hashlib
        key = '|'.join(('mls',day,away,parts[0]))
        rows.append({'event_id':'derived:' + hashlib.sha256(key.encode()).hexdigest()[:24],
                     'provider_event_id':None, 'league':'mls', 'slate_date':day,
                     'date_timezone':'source_calendar_timezone_unresolved', 'start_utc':None,
                     'away':away, 'home':parts[0], 'away_score':apts, 'home_score':hpts,
                     'status':status, 'source_sha256':rec['sha256'], 'retrieved_at':rec['retrieved_at'],
                     'historical_pregame_eligible':False, 'venue':parts[3] if final else (parts[4] if len(parts)>4 else None)})
    return rows


def build(bundle, output, as_of=None, date=None, historical=False, timezone='America/Los_Angeles'):
    cfg = json.loads((bundle / 'acquisition.json').read_text())
    clock = slate_clock(as_of, date, timezone, historical)
    events, receipts, new_boxes, cfb_observations = [], [], [], []
    for item in cfg['sources']:
        path = (bundle / item['path']).resolve()
        if not path.is_relative_to(bundle.resolve()):
            raise ValueError('SOURCE_OUTSIDE_BUNDLE')
        rec = receipt(path, item['source'], item['retrieved_at'], item.get('source_available_at'), item.get('representation', 'tool_extract'))
        if rec['sha256'] != item['sha256']:
            raise ValueError('SOURCE_DIGEST_MISMATCH: ' + item['path'])
        if instant(rec['retrieved_at']) > instant(clock['as_of_utc']):
            raise ValueError('CAPTURE_AFTER_RUN_CUTOFF')
        rec['path'] = item['path']
        receipts.append(rec)
        if item.get('parser') == 'sports_extract':
            events.extend(parse_sports_extract(path.read_text(), item['league'], rec))
        elif item.get('parser') == 'cfb_observations':
            cfb_observations.extend(cfb_score_observations(path.read_text(), rec))
        elif item.get('parser') == 'mls_schedule':
            events.extend(mls_schedule_extract(path.read_text(), rec))
        elif item.get('parser') == 'wnba_box':
            g = wnba_box(path, rec)
            new_boxes.append(g)
            events.append({'event_id': 'espn:wnba:' + g['gid'], 'provider_event_id': g['gid'],
                           'league': 'wnba', 'away': g['away'], 'home': g['home'],
                           'start_utc': instant(g['utc_instant']).isoformat(),
                           'slate_date': local_date(g['utc_instant'], timezone),
                           'status': 'final', 'away_score': g['apts'], 'home_score': g['hpts'],
                           'source_sha256': rec['sha256'], 'retrieved_at': rec['retrieved_at']})
    for event in events:
        if event.get('start_utc'):
            event['source_slate_date'] = event['slate_date']
            event['slate_date'] = local_date(event['start_utc'], timezone)
            event['date_timezone'] = timezone
    events, conflicts = reconcile(events)
    mlb_reconciliation = None
    if cfg.get('mlb_prior_results'):
        from collections import defaultdict
        old = list(csv.DictReader((bundle / cfg['mlb_prior_results']).open()))
        index = defaultdict(list)
        for row in old:
            index[(row['date'], row['away'], row['home'])].append(row)
        categories = {k:[] for k in ('new_observation','matching_existing','missing_prior_score','ambiguous_doubleheader','score_conflict')}
        for event in (e for e in events if e['league']=='mlb' and e['status']=='final'):
            prior_rows = index.get((event['slate_date'],event['away_code'],event['home_code']),[])
            if not prior_rows:
                category = 'new_observation'
            elif len(prior_rows)>1:
                category = 'ambiguous_doubleheader'
            elif not prior_rows[0]['away_score'] or not prior_rows[0]['home_score']:
                category = 'missing_prior_score'
            elif (float(prior_rows[0]['away_score']),float(prior_rows[0]['home_score'])) == (event['away_score'],event['home_score']):
                category = 'matching_existing'
            else:
                category = 'score_conflict'
            categories[category].append({'observation':event,'prior_game_ids':[r['game_id'] for r in prior_rows]})
        mlb_reconciliation = {'counts':{k:len(v) for k,v in categories.items()}, 'categories':categories,
                              'previous_last_result_date':max(r['date'] for r in old if r['status']=='final'),
                              'canonical_results_modified':False,
                              'reason':'Tool extract lacks provider game IDs; observations require schedule-ID binding before canonical grading.'}
    # Preserve legacy regular-season inputs, quarantine exhibition team IDs.
    extension = None
    if cfg.get('wnba_prior_extension'):
        prior_path = bundle / cfg['wnba_prior_extension']
        prior = json.loads(prior_path.read_text())
        allowed = {'ATL','CHI','CON','DAL','GSV','IND','LAS','LVA','LV','MIN','NYL','PDX','PHX','SEA','TOR','WAS'}
        quarantined = [g for g in prior['games'] if g['home'] not in allowed or g['away'] not in allowed]
        keep = {g['gid']: g for g in prior['games'] if g not in quarantined}
        for g in new_boxes:
            if g['gid'] in keep:
                raise ValueError('WNBA_EXISTING_GAME_REQUIRES_REVISION_RECONCILIATION')
            keep[g['gid']] = g
        extension = {'schema': 'ops.espn_extension.current.v1', 'date_timezone': 'America/New_York',
                     'cutoff_exclusive': prior['cutoff_exclusive'], 'games': sorted(keep.values(), key=lambda g:(g['date'],g['gid'])),
                     'quarantined': quarantined, 'prior_extension_sha256': next(r['sha256'] for r in receipts if r['path'] == cfg['wnba_prior_extension']),
                     'new_game_count': len(new_boxes), 'model_refitted': False,
                     'historical_availability': 'Mixed source revisions; no automatic pregame eligibility'}
    digests = {r['sha256'] for r in receipts}
    statuses = []
    for league in LEAGUES:
        coverage = dict(cfg.get('leagues', {}).get(league, {}).get('coverage', {}))
        if coverage.get('source_sha256') not in digests:
            coverage['complete'] = False
        coverage['conflicts'] = sum(c['earlier']['league'] == league for c in conflicts)
        features = cfg.get('leagues', {}).get(league, {}).get('features', {})
        statuses.append(league_status(league, clock, events, coverage, features))
    report = {'schema': 'sports.current_state.v1', 'clock': clock, 'code_base': cfg['code_base'],
              'leagues': statuses, 'source_receipts': receipts, 'conflicts': conflicts,
              'all_models_current': all(s['forecast_ready'] for s in statuses),
              'model_refits_performed': False, 'historical_forecasts_modified': False}
    artifacts = {'events.json': events, 'status.json': report,
                 'acquisition.json': cfg,
                 'cfb_observations.json': {'scope': 'PARTIAL_SCOREBOARD_OBSERVATIONS_NOT_COMPLETE_FBS_RESULTS',
                                         'observations': cfb_observations}}
    if extension:
        artifacts['wnba_extension.json'] = extension
    if mlb_reconciliation:
        artifacts['mlb_reconciliation.json'] = mlb_reconciliation
    manifest = {name: immutable_json(output / name, obj) for name, obj in artifacts.items()}
    immutable_json(output / 'manifest.json', manifest)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--as-of', help='Aware timestamp; defaults to the actual UTC clock')
    p.add_argument('--date', help='ISO local slate date; defaults to today')
    p.add_argument('--timezone', default='America/Los_Angeles')
    p.add_argument('--historical', action='store_true')
    args = p.parse_args()
    report = build(args.bundle, args.output, args.as_of, args.date, args.historical, args.timezone)
    print(json.dumps({'clock': report['clock'], 'leagues': [{k:s[k] for k in ('league','phase','league_week','schedule_status','acquired_slate_games','results_through','feature_status','forecast_ready')} for s in report['leagues']]}, indent=2))


if __name__ == '__main__':
    main()
