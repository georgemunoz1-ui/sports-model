"""Explicit, seed-pinned research corrections; raw schedules remain immutable."""
import hashlib
import json
from zoneinfo import ZoneInfo
from .features import kickoff
from .recovered_inference import utc


def reviewed_team(team, resolution):
    """Only a source-ID/name-bound WSH/WAS equivalence explicitly reviewed per event."""
    abbreviation = team['abbreviation']
    if abbreviation != 'WSH':
        return abbreviation
    expected = {'provider_code': 'WSH', 'canonical_code': 'WAS',
                'provider_team_id': '28', 'provider_display_name': 'Washington Commanders'}
    if resolution.get('provider_team_binding_review') != expected:
        raise ValueError('EXPLICIT_TEAM_ALIAS_REVIEW_REQUIRED')
    if str(team.get('id')) != expected['provider_team_id'] or team.get('displayName') != expected['provider_display_name']:
        raise ValueError('TEAM_ALIAS_IDENTITY_CONFLICT')
    return 'WAS'


def apply(games, pbp, resolutions, cutoff):
    games = games.copy()
    # A nominal first-snap starter need not record a passing play. Keep that
    # source fact distinct from the active passer used by the fitted QB state.
    for side in ('home', 'away'):
        games[side+'_active_qb_id'] = games[side+'_qb_id']
    seen = set()
    for r in resolutions:
        key = (r['game_id'], r['team'])
        if key in seen:
            raise ValueError('DUPLICATE_STARTER_ADJUDICATION')
        seen.add(key)
        match = games[games.game_id == r['game_id']]
        if match.empty:
            continue  # A pinned correction for a different week.
        g = match.iloc[0]
        if r['team'] not in (g.home_team, g.away_team):
            raise ValueError('ADJUDICATION_TEAM_BINDING')
        side = 'home' if r['team'] == g.home_team else 'away'
        kind = r.get('resolution_kind', 'STALE_SCHEDULE_STARTER')
        if kind not in ('STALE_SCHEDULE_STARTER', 'NOMINAL_STARTER_NO_DROPBACKS'):
            raise ValueError('ADJUDICATION_RESOLUTION_KIND')
        if g[side+'_qb_id'] != r['expected_schedule_qb_id']:
            raise ValueError('ADJUDICATION_SCHEDULE_CHANGED_REVIEW_REQUIRED')
        evidence = r['evidence']; receipt = evidence['receipt']
        if hashlib.sha256(evidence['text'].encode()).hexdigest() != receipt['sha256']:
            raise ValueError('ADJUDICATION_SOURCE_HASH')
        if receipt['source_url'] != 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event='+r['espn_event_id']:
            raise ValueError('ADJUDICATION_SOURCE_IDENTITY')
        if not r.get('review_reason') or not r.get('reviewed_by'):
            raise ValueError('ADJUDICATION_REVIEW_REQUIRED')
        if not utc(receipt['retrieved_at_utc']) <= utc(r['reviewed_at_utc']) <= utc(cutoff):
            raise ValueError('ADJUDICATION_AFTER_CUTOFF')
        for clock in ('available_at_utc', 'source_published_at_utc'):
            if receipt.get(clock) and utc(receipt[clock]) > utc(cutoff):
                raise ValueError('ADJUDICATION_AFTER_CUTOFF')
        j = json.loads(evidence['text']); header = j['header']; c = header['competitions'][0]
        if kind == 'NOMINAL_STARTER_NO_DROPBACKS':
            excerpt = r.get('nominal_starter_evidence_excerpt')
            if (not isinstance(excerpt, str) or not excerpt.strip()
                    or excerpt not in j.get('article', {}).get('story', '')
                    or not r.get('nominal_starter_player_name')
                    or r['nominal_starter_player_name'] not in excerpt
                    or r['nominal_starter_player_name'] != g.get(side+'_qb_name')):
                raise ValueError('NOMINAL_STARTER_SOURCE_REVIEW_REQUIRED')
        if str(header['id']) != r['espn_event_id'] or not c['status']['type']['completed']:
            raise ValueError('ADJUDICATION_EVENT_NOT_FINAL')
        if int(header['season']['year']) != int(g.season) or int(header['season']['type']) != 2:
            raise ValueError('ADJUDICATION_SEASON_BINDING')
        # nflverse gameday/gametime are Eastern, while ESPN dates carry UTC.
        # Evening games often cross midnight UTC. Compare instants when the
        # schedule time exists; otherwise retain an explicit Eastern date test.
        source_start = utc(c['date'])
        schedule_start = kickoff(g)
        if source_start.astimezone(ZoneInfo('America/New_York')).date().isoformat() != str(g.gameday):
            raise ValueError('ADJUDICATION_DATE_BINDING')
        if schedule_start is not None and source_start != schedule_start:
            raise ValueError('ADJUDICATION_START_TIME_BINDING')
        # Exact codes unless the separately reviewed provider ID/name binding passes.
        teams = {x['homeAway']: x for x in c['competitors']}
        for s in ('home', 'away'):
            if reviewed_team(teams[s]['team'], r) != g[s+'_team'] or int(teams[s]['score']) != g[s+'_score']:
                raise ValueError('ADJUDICATION_FINAL_BINDING')
        passing = [a for t in j['boxscore']['players'] if reviewed_team(t['team'], r) == r['team']
                   for stat in t['statistics'] if stat['name'] == 'passing' for a in stat['athletes']]
        athletes = [a for a in passing if str(a['athlete']['id']) == r['espn_athlete_id']
                    and a['athlete']['displayName'] == r['player_name']]
        if len(athletes) != 1:
            raise ValueError('ADJUDICATION_PLAYER_BINDING')
        d = pbp[(pbp.game_id == r['game_id']) & (pbp.posteam == r['team']) & (pbp.qb_dropback == 1)]
        if d.empty:
            raise ValueError('ADJUDICATION_QB_PLAYS_REQUIRED')
        if (kind == 'NOMINAL_STARTER_NO_DROPBACKS' and 'rusher_player_id' in d
                and d.rusher_player_id.eq(r['expected_schedule_qb_id']).any()):
            raise ValueError('ADJUDICATION_PBP_IDENTITY_CONFLICT')
        order = 'order_sequence' if 'order_sequence' in d else 'play_id'
        first = d.sort_values(order).iloc[0]
        first_id = first.get('rusher_player_id') if first.get('qb_scramble') == 1 else first.get('passer_player_id')
        if first_id != r['qb_id']:
            raise ValueError('ADJUDICATION_FIRST_QB_PLAY_BINDING')
        named = d[(d.passer_player_id == r['qb_id']) & (d.passer_player_name == r['pbp_player_name'])]
        if named.empty or r['expected_schedule_qb_id'] in set(d.passer_player_id):
            raise ValueError('ADJUDICATION_PBP_IDENTITY_CONFLICT')
        games.loc[match.index, side+'_active_qb_id'] = r['qb_id']
        if kind == 'STALE_SCHEDULE_STARTER':
            games.loc[match.index, side+'_qb_id'] = r['qb_id']
    return games
