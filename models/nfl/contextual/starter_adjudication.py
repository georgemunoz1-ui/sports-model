"""Explicit, seed-pinned research corrections; raw schedules remain immutable."""
import hashlib
import json
from .recovered_inference import utc


def apply(games, pbp, resolutions, cutoff):
    games = games.copy()
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
        j = json.loads(evidence['text']); header = j['header']; c = header['competitions'][0]
        if str(header['id']) != r['espn_event_id'] or not c['status']['type']['completed']:
            raise ValueError('ADJUDICATION_EVENT_NOT_FINAL')
        if int(header['season']['year']) != int(g.season) or int(header['season']['type']) != 2:
            raise ValueError('ADJUDICATION_SEASON_BINDING')
        if utc(c['date']).date().isoformat() != str(g.gameday):
            raise ValueError('ADJUDICATION_DATE_BINDING')
        # Restricted to exact provider team codes. Alias cases require another review.
        teams = {x['homeAway']: x for x in c['competitors']}
        for s in ('home', 'away'):
            if teams[s]['team']['abbreviation'] != g[s+'_team'] or int(teams[s]['score']) != g[s+'_score']:
                raise ValueError('ADJUDICATION_FINAL_BINDING')
        passing = [a for t in j['boxscore']['players'] if t['team']['abbreviation'] == r['team']
                   for stat in t['statistics'] if stat['name'] == 'passing' for a in stat['athletes']]
        athletes = [a for a in passing if str(a['athlete']['id']) == r['espn_athlete_id']
                    and a['athlete']['displayName'] == r['player_name']]
        if len(athletes) != 1:
            raise ValueError('ADJUDICATION_PLAYER_BINDING')
        d = pbp[(pbp.game_id == r['game_id']) & (pbp.posteam == r['team']) & (pbp.qb_dropback == 1)]
        order = 'order_sequence' if 'order_sequence' in d else 'play_id'
        first = d.sort_values(order).iloc[0]
        first_id = first.get('rusher_player_id') if first.get('qb_scramble') == 1 else first.get('passer_player_id')
        if first_id != r['qb_id']:
            raise ValueError('ADJUDICATION_FIRST_QB_PLAY_BINDING')
        named = d[(d.passer_player_id == r['qb_id']) & (d.passer_player_name == r['pbp_player_name'])]
        if named.empty or r['expected_schedule_qb_id'] in set(d.passer_player_id):
            raise ValueError('ADJUDICATION_PBP_IDENTITY_CONFLICT')
        games.loc[match.index, side+'_qb_id'] = r['qb_id']
    return games
