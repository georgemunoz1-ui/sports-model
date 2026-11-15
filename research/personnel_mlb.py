"""Audit probable-pitcher identity for retained MLB V13 winner forecasts."""

import math
import re

from models.current.common import current
from sports.rosters import digest, utc

MODEL_ID = 'mlb.v13.current_input.research.v1'
# These revisions bind the MLBAM IDs to starter profiles, then pass them to V13.
PITCHER_CODE = {
    'models/current/mlb.py': '72c734fb0a36a15a013300773382089da325d162a558605020c7271efc48cf5f',
    'pipelines/cards/adapters/mlb.py': '95cdbf3e028012a865e14d1ddbba2a3954c48488abe394f76044ec49063d05d5',
    'harness/run_v13_historical.py': 'd2fdf977cbd8eb34759af3bf23b19112ad02af99968973c1f0bc721a88470cba',
}
PROFILE_INPUTS = ('era', 'gs', 'k', 'bb')
SOURCE = 'https://statsapi.mlb.com/api/v1/'


def pitcher_inputs(event, cutoff, forecast, evidence):
    """Only credit named probables whose actual V13 input is bound to the retained package."""
    package = getattr(evidence, 'mlb_package', None)
    package_hash = getattr(evidence, 'mlb_package_sha256', None)
    if not isinstance(package, dict) or not isinstance(forecast, dict):
        return {}
    try:
        if not (package['model_id'] == forecast['model_id'] == MODEL_ID
                and package['schema'] == 'sports.current_research_package.v1' and package['league'] == 'mlb'
                and 0 < package['ttl_hours'] <= 6
                and package['action_authority'] is False and forecast['action_authority'] is False
                and package['data_grade'] == 'OFFICIAL_SEASON_CENSUS_AND_CURRENT_PITCHER_LOGS'
                and all(package['code_pins'].get(k) == v for k, v in PITCHER_CODE.items())):
            return {}
        current(package, cutoff)
        eid = event['event_id']
        retained, = (e for e in package['events'] if e['event_id'] == eid)
        if not (all(retained[k] == event[k] == forecast.get(k, event[k])
                    for k in ('event_id', 'away_team', 'home_team'))
                and retained['away_team'] != retained['home_team']
                and retained['away_pitcher_id'] != retained['home_pitcher_id']
                and all(row.get(key, retained[key]) == retained[key] for row in (event, forecast)
                        for key in ('away_pitcher_id','home_pitcher_id','away_starter','home_starter'))
                and utc(cutoff) < utc(retained['start_time_utc']) == utc(event['start_time_utc'])
                == utc(forecast.get('start_time_utc', event['start_time_utc']))):
            return {}
        snapshot = forecast['model_input_snapshot']
        state = {'pins':package['code_pins'], 'teams':package['team_state'], 'starters':package['starter_state']}
        if not (re.fullmatch('[0-9a-f]{64}', package_hash) and digest(state) == package['model_sha256']
                == forecast['model_state_config_hash'] and utc(snapshot['cutoff']) == utc(cutoff)):
            return {}
        count = forecast['simulation']['count']
        if type(count) is not int or not 1 <= count <= 1_000_000:
            return {}
        expected = {'event_id':eid, 'model_id':MODEL_ID, 'package_sha256':package_hash,
                    'cutoff':snapshot['cutoff'], 'n':count, 'park_factor':retained['park_factor']}
        for side in ('away', 'home'):
            expected['sp_'+side] = package['starter_state'][str(retained[side+'_pitcher_id'])]
            expected[side+'_form'] = package['team_state'][retained[side+'_team']]
        identity = digest(expected)
        if not (identity == forecast['input_snapshot_hash'] == digest(snapshot)
                and forecast['simulation']['seed'] == int(identity[:16], 16)
                and forecast['diagnostics']['starter_status'] == 'OFFICIAL_PROBABLE_NOT_CONFIRMED'):
            return {}
        sources = {r['source']: r['sha256'] for r in package['source_fetches'] if re.fullmatch('[0-9a-f]{64}', r['sha256'])}
        day = retained['slate_date']
        schedule_url = f'{SOURCE}schedule?sportId=1&date={day}&hydrate=probablePitcher,linescore,venue'
        if schedule_url not in sources:
            return {}
        roles = {}
        for side in ('away', 'home'):
            player, name = retained[side+'_pitcher_id'], retained[side+'_starter']
            team, profile = retained[side+'_team'], expected['sp_'+side]
            log_url = f'{SOURCE}people/{player}/stats?stats=gameLog&group=pitching&season={day[:4]}'
            if (type(player) is not int or player <= 0 or not isinstance(name, str) or not name.strip()
                    or log_url not in sources or profile.get('treatment') or not profile.get('observed_game_ids')
                    or not all(type(profile[k]) in (float, int) and math.isfinite(profile[k]) for k in PROFILE_INPUTS)):
                continue
            roles[team] = {'role':'starting_pitcher', 'team_id':team, 'player_id':str(player), 'player_name':name,
                           'assignment_status':'OFFICIAL_PROBABLE_NOT_CONFIRMED',
                           'model_consumption':'PITCHER_ID_BOUND_TO_V13_STARTER_INPUT',
                           'feature_names':list(PROFILE_INPUTS), 'state_sha256':package['model_sha256'],
                           'package_sha256':package_hash, 'input_snapshot_hash':identity,
                           'schedule_source_sha256':sources[schedule_url], 'pitcher_log_sha256':sources[log_url]}
        return roles
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        return {}
