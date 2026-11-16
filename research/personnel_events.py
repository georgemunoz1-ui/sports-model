"""Post-forecast review of event-specific personnel reports. Never changes predictions or grades."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
import subprocess
from functools import lru_cache
from datetime import datetime
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from sports.rosters import digest, utc


ROLES = {
    'NFL': ('starting_qb', 'receiver', 'offensive_line', 'defender'),
    'CFB': ('starting_qb', 'receiver', 'offensive_line', 'defender'),
    'NBA': ('starter', 'rotation_player'), 'WNBA': ('starter', 'rotation_player'),
    'CBB': ('starter', 'rotation_player'),
    'NHL': ('starting_goalie', 'skater'),
    'MLB': ('starting_pitcher', 'reliever', 'batter'),
    'MLS': ('goalkeeper', 'starting_xi', 'substitute'),
}
LEAGUE_HOSTS = {
    'NFL': ('nfl.com',), 'CFB': ('ncaa.org', 'ncaa.com'), 'CBB': ('ncaa.org', 'ncaa.com'),
    'NBA': ('nba.com',), 'WNBA': ('wnba.com',), 'NHL': ('nhl.com',), 'MLB': ('mlb.com',),
    'MLS': ('mlssoccer.com',),
}
NFL_TEAM_HOSTS = dict(zip(
    'ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LA LAC LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS'.split(),
    ('azcardinals.com atlantafalcons.com baltimoreravens.com buffalobills.com panthers.com chicagobears.com '
     'bengals.com clevelandbrowns.com dallascowboys.com denverbroncos.com detroitlions.com packers.com '
     'houstontexans.com colts.com jaguars.com chiefs.com therams.com chargers.com raiders.com miamidolphins.com '
     'vikings.com patriots.com neworleanssaints.com giants.com newyorkjets.com philadelphiaeagles.com '
     'steelers.com seahawks.com 49ers.com buccaneers.com tennesseetitans.com commanders.com').split()))
# College athletics hosts verified against the schools' own Athletics directories.
COLLEGE_TEAM_HOSTS = {('CBB','235'):'gotigersgo.com', ('CBB','Memphis'):'gotigersgo.com',
                      ('CFB','145'):'olemisssports.com', ('CFB','Ole Miss'):'olemisssports.com'}
NFL_NICKNAMES = dict(zip(NFL_TEAM_HOSTS, (
    'Cardinals Falcons Ravens Bills Panthers Bears Bengals Browns Cowboys Broncos Lions Packers Texans Colts '
    'Jaguars Chiefs Rams Chargers Raiders Dolphins Vikings Patriots Saints Giants Jets Eagles Steelers Seahawks '
    '49ers Buccaneers Titans Commanders').lower().split()))
# Conservative text checks on attributed, hand-reviewed claims. These do not extract new claims.
STATUS_TERMS = {
    'STARTING': r'\b(start(s|ing|er)?|started)\b',
    'EXPECTED': r'\b(expect\w*|likely|project\w*|in line|in position|prepar\w*|ready)\b',
    'OUT': r'\b(out|inactive|unavailable|injured reserve|suspended|will miss|will not play|withholding period)\b',
    'LIMITED': r'\b(limit\w*|restrict\w*|questionable)\b',
    'PROBABLE': r'\bprobable\b', 'AVAILABLE':r'\bavailable\b', 'DOUBTFUL':r'\bdoubtful\b',
    'TRADED': r'\b(trad\w*|acquir\w*|reacquir\w*)\b',
}
NFL_SOURCE = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'


def _text(value):
    return re.sub(r'\s+([,.;:!?])', r'\1', ' '.join(value.split()).casefold())


class _Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0
        self.metadata = []
        self.script_type = None

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag == 'script':
            attrs = dict(attrs)
            self.script_type = 'article' if attrs.get('type') == 'application/ld+json' else (
                'college' if attrs.get('id') == '__NUXT_DATA__' else None)

    def handle_endtag(self, tag):
        if tag == 'script':
            self.script_type = None
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)
        elif self.script_type:
            try:
                self.metadata.append((self.script_type, json.loads(value)))
            except ValueError:
                pass


def _publication(page, url):
    parsed = urlsplit(url)
    for kind, data in page.metadata:
        if kind == 'article':
            articles = data.get('@graph', [data]) if isinstance(data, dict) else data
            for a in articles if isinstance(articles, list) else ():
                if isinstance(a, dict) and a.get('@type') == 'NewsArticle' and a.get('url') == url and a.get('datePublished'):
                    return utc(a['datePublished'])
        if kind == 'college' and parsed.hostname in COLLEGE_TEAM_HOSTS.values() and isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and 'gamePostStoryId' in item:
                    article_url = data[item['url']]
                    if article_url == parsed.path:
                        return datetime.fromisoformat(data[item['date']]).replace(tzinfo=ZoneInfo('America/Chicago'))
    return None


@dataclass(frozen=True)
class _Evidence:
    reports: tuple = ()
    schedule: dict | None = None
    schedule_sha256: str | None = None
    state: dict | None = None
    state_sha256: str | None = None
    mlb_package: dict | None = None
    mlb_package_sha256: str | None = None


def _path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('PERSONNEL_SOURCE_PATH')
    return path


def _retained(root, ref):
    raw = _path(root, ref['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref['sha256']:
        raise ValueError('PERSONNEL_SOURCE_HASH')
    return raw


def _official_host(url, league, team, previous=None):
    parsed = urlsplit(url)
    host = parsed.hostname or ''
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
        return False
    allowed = list(LEAGUE_HOSTS[league])
    allowed += [NFL_TEAM_HOSTS.get(club) for club in (team, previous)] if league == 'NFL' else [COLLEGE_TEAM_HOSTS.get((league, team))]
    return any(d and (host == d or host.endswith('.'+d)) for d in allowed)


@lru_cache(maxsize=4)
def _pdf_text(raw):
    tool = shutil.which('pdftotext')
    if not tool:
        return ''
    result = subprocess.run([tool, '-layout', '-', '-'], input=raw, capture_output=True, timeout=15)
    return result.stdout.decode('utf-8') if result.returncode == 0 else ''


def _pdf_status(raw, report):
    """An NBA daily PDF carries teams and matchups forward between rows and pages."""
    source = report['source']
    if report['league'] != 'NBA' or urlsplit(source['url']).hostname != 'ak-static.cms.nba.com':
        return False
    matchup = source.get('pdf_matchup', '')
    team = source.get('pdf_team', '')
    label = source.get('player_label', '')
    # Match the precise participant, including the original printed surname/given names.
    pieces = label.split(', ', 1)
    if len(pieces) != 2 or _text(' '.join(reversed(pieces))) != _text(report['player_name']):
        return False
    statuses = {'OUT': 'Out', 'LIMITED': 'Questionable', 'PROBABLE': 'Probable', 'AVAILABLE':'Available', 'DOUBTFUL':'Doubtful'}
    expected = statuses.get(report['status'])
    if not expected or not team or not re.fullmatch(r'[A-Z]{2,4}@[A-Z]{2,4}',matchup):
        return False
    content = _pdf_text(raw)
    header = re.search(r'Injury Report:\s*(\d{2}/\d{2}/\d{2} \d{2}:\d{2} [AP]M)', content)
    if not header or datetime.strptime(header[1], '%m/%d/%y %I:%M %p').replace(tzinfo=ZoneInfo('America/New_York')) != utc(source['published_at_utc']):
        return False
    current_match, current_team = '', ''
    for line in content.splitlines():
        cells = [x.strip() for x in re.split(r'\s{2,}',line.strip()) if x.strip()]
        for i, cell in enumerate(cells):
            if re.fullmatch(r'[A-Z]{2,4}@[A-Z]{2,4}', cell):
                current_match, current_team = cell, ''
            if cell in NBA_TEAMS.values():
                current_team = cell
            if cell == label and i+1 < len(cells) and cells[i+1] == expected:
                if current_team == team and current_match == matchup:
                    return _text(source['excerpt']) in _text(line)
    return False


NBA_TEAMS = dict(zip('ATL BOS BKN CHA CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK OKC ORL PHI PHX POR SAC SAS TOR UTA WAS'.split(),
    ('Atlanta Hawks|Boston Celtics|Brooklyn Nets|Charlotte Hornets|Chicago Bulls|Cleveland Cavaliers|Dallas Mavericks|Denver Nuggets|'
     'Detroit Pistons|Golden State Warriors|Houston Rockets|Indiana Pacers|LA Clippers|Los Angeles Lakers|Memphis Grizzlies|Miami Heat|'
     'Milwaukee Bucks|Minnesota Timberwolves|New Orleans Pelicans|New York Knicks|Oklahoma City Thunder|Orlando Magic|Philadelphia 76ers|'
     'Phoenix Suns|Portland Trail Blazers|Sacramento Kings|San Antonio Spurs|Toronto Raptors|Utah Jazz|Washington Wizards').split('|')))


def _substantive(name, status, quote):
    # These checks verify a narrow reviewed statement; unsupported wording stays uncertain.
    if not re.search(STATUS_TERMS[status], quote):
        return False
    if status != 'EXPECTED' and re.search(r"\b(may|might|could|would|unlikely|expected|projected|likely|whether|if|last week|previously)\b|\?", quote):
        return False
    if re.search(r"\b(not|never|isn't|wasn't|won't)\b", quote) and not (status == 'OUT' and 'will not play' in quote):
        return False
    if status == 'EXPECTED' and re.search(r"\b(not|unlikely|whether|if)\b|\?", quote):
        return False
    after = re.split(r"[.;!?]|\b(?:while|but|however)\b",quote.split(name, 1)[1], maxsplit=1)[0]
    before = re.split(r"[.;!?]",quote.split(name, 1)[0])[-1]
    subject = r'(?:quarterback|rookie|veteran|guard|forward|center|pitcher|goalie|receiver)\s+'
    if status == 'STARTING':
        return bool(re.search(r'\b(?:start|starting)\s+(?:'+subject+r')?$',before)
                    or re.match(r"\s*(?:is |was |will |has been |set to |is set to |will be the [\w’'-]+ )*(?:start|starting|starter)\b",after)
                    or re.match(r"\s+(?:is set to make|will make) (?:his|her) .{0,28}debut.{0,18}starting at quarterback\b", after))
    if status == 'OUT':
        return bool(re.match(r'\s*[:,]?\s*(?:(?:is|was|has been|already|been|who was|ruled|placed|listed|on|the|as|remains) )*(?:out|on injured reserve|injured reserve|inactive|unavailable|suspended|will miss|will not play|must serve a [\w-]+ withholding period)\b',after)
                    or re.match(r"\s+and [\w '-]+, both of whom have (?:already )?been ruled out\b",after)
                    or (re.search(r'\bplaced\s+(?:'+subject+r')?$',before) and re.match(r"\s+and [\w '-]+ on (?:the )?injured reserve\b",after)))
    if status == 'TRADED':
        return bool(re.match(r'\s+(?:via (?:a )?trade|was traded|has been traded|was acquired|has been acquired)\b', after)
                    or re.search(r'\b(?:acquired|reacquired|traded for)\s+(?:'+subject+r')?$', before))
    if status == 'EXPECTED':
        return bool(re.match(r"\s+(?:(?:is |was |has been )?(?:expected|projected|likely|preparing|in line) to start|was limited in practice as he prepares to start)\b",after))
    return bool(re.match(r'\s*[:,]?\s*(?:(?:is|was|has been|listed|as|remains) )*'+STATUS_TERMS[status],after))


def _report(root, report):
    league, status = report['league'], report['status']
    if report['role'] not in ROLES.get(league, ()) or status not in STATUS_TERMS:
        raise ValueError('PERSONNEL_ROLE_OR_STATUS')
    for key in ('event_id', 'team_id', 'player_id', 'player_name'):
        if not isinstance(report.get(key), str) or not report[key].strip():
            raise ValueError('PERSONNEL_IDENTITY_REQUIRED')
    source = report['source']
    raw = _retained(root, source)
    published, retrieved = utc(source['published_at_utc']), utc(source['retrieved_at_utc'])
    if published > retrieved:
        raise ValueError('PERSONNEL_SOURCE_CHRONOLOGY')
    witness = json.loads(_path(root, source.get('receipt_path', str(Path(source['path']).with_suffix('.json')))).read_bytes())
    if witness.get('status') != 'CAPTURED' and Path(source['path']).name in witness:
        witness = witness[Path(source['path']).name]
    if (witness.get('sha256') != source['sha256'] or witness.get('url') != source['url']
            or witness.get('final_url', witness.get('url')) != source['url']
            or utc(witness.get('acquired_at_utc', witness.get('fetched_at_utc'))) != retrieved):
        raise ValueError('PERSONNEL_CAPTURE_RECEIPT_MISMATCH')
    official = _official_host(source['url'], league, report['team_id'],
                              report.get('prior_team_id') if status == 'TRADED' else None)
    if raw.startswith(b'%PDF-'):
        substantive = _pdf_status(raw, report)
        publish_bound = substantive
    else:
        page = _Page()
        page.feed(raw.decode('utf-8'))
        body, quote = _text(' '.join(page.parts)), _text(source['excerpt'])
        name = _text(report['player_name'])
        if name not in quote:
            identity = _text(source.get('participant_excerpt', ''))
            short = name.split()[-1]
            if not (identity and name in identity and identity in body and short in quote
                    and 0 <= body.find(quote) - body.find(identity) <= len(identity) + 90):
                raise ValueError('PERSONNEL_SOURCE_PARTICIPANT')
            name = short
        if not quote or quote not in body:
            raise ValueError('PERSONNEL_SOURCE_EXCERPT')
        if source.get('context_excerpt') and _text(source['context_excerpt']) not in body:
            raise ValueError('PERSONNEL_EVENT_EXCERPT')
        substantive = _substantive(name, status, quote)
        observed = _publication(page, source['url'])
        if observed is not None and observed != published:
            raise ValueError('PERSONNEL_PUBLISHED_TIME_MISMATCH')
        publish_bound = observed is not None
    return {**{k: report[k] for k in ('league','event_id','team_id','player_id','player_name','role','status')},
            'prior_team_id': report.get('prior_team_id'), 'prior_team_event_id':report.get('prior_team_event_id'), 'source_url': source['url'],
            'source_sha256': source['sha256'], 'published_at_utc': source['published_at_utc'],
            'retrieved_at_utc': source['retrieved_at_utc'], 'excerpt': source['excerpt'],
            'context_excerpt':source.get('context_excerpt',''), 'pdf_matchup':source.get('pdf_matchup'), 'pdf_team':source.get('pdf_team'),
            'official_source': official, 'substantive_excerpt': substantive, 'published_time_verified':publish_bound,
            'source_scope': 'HAND_ADJUDICATED_REPORT_WITH_RETAINED_QUOTE'}


def load_observations(path):
    """Load hash-checked, locally retained evidence. A missing input is unknown coverage."""
    path = Path(path).resolve()
    manifest = json.loads(path.read_bytes())
    if manifest.get('schema') != 'sports.personnel_review_inputs.v1':
        raise ValueError('PERSONNEL_INPUT_SCHEMA')
    records = tuple(_report(path.parent, r) for r in manifest.get('reports', ()))
    schedule_ref, state_ref = manifest.get('nfl_schedule'), manifest.get('nfl_state')
    schedule, state = {}, None
    if schedule_ref:
        raw = _retained(path.parent, schedule_ref).decode('utf-8-sig')
        for row in csv.DictReader(io.StringIO(raw)):
            if not row.get('game_id') or row['game_id'] in schedule:
                raise ValueError('PERSONNEL_SCHEDULE_EVENT_AMBIGUOUS')
            schedule[row['game_id']] = row
    if state_ref:
        state = json.loads(_retained(path.parent, state_ref))
    mlb_ref = manifest.get('mlb_package')
    mlb = json.loads(_retained(path.parent, mlb_ref)) if mlb_ref else None
    return _Evidence(records, schedule, (schedule_ref or {}).get('sha256'), state, (state_ref or {}).get('sha256'),
                     mlb, (mlb_ref or {}).get('sha256'))


def _nfl_inputs(event, cutoff, forecast, evidence):
    """Reproduce the selected QB features from ID-keyed state before claiming individual use."""
    from models.nfl.contextual.features import qb_features

    if not forecast or not evidence.state or not evidence.schedule:
        return {}
    trace = forecast if forecast.get('schema') == 'nfl.integrated_context_forecast.v1' else forecast.get('diagnostics', {})
    eid = event['event_id']
    state, game = evidence.state, evidence.schedule.get(eid, {})
    try:
        bound = trace['event']
        assimilation, report = trace['assimilation'], trace['capability_report']
        source = state['schedule_source']['receipt']
        if not (trace['selected_arm'] == 'qb' and trace['model_id'] == 'nfl.integrated_context.qb.v1.research'
                and bound['event_id'] == report['event_id'] == eid
                and all(bound[k] == game[k] == event[k] for k in ('home_team', 'away_team'))
                and utc(bound['start_time_utc']) == utc(event['start_time_utc'])
                and utc(source['retrieved_at_utc']) <= utc(state['cutoff_utc']) <= utc(cutoff)
                and utc(report['cutoff_utc']) == utc(trace['cutoff_utc']) == utc(cutoff)
                and source['source_url'] == NFL_SOURCE
                and assimilation['schedule_sha256'] == source['sha256'] == evidence.schedule_sha256
                and assimilation['state_id'] == evidence.state_sha256
                and digest(state['qb_state']) == assimilation['qb_state_sha256']
                and trace['model_id'] == report['model_id'] and state['model_sha256'] == trace['model_artifact_sha256']):
            return {}
        qstate = state['qb_state']
        projected = qb_features(game, qstate['qb_ratings'], qstate['last_qb'])
        active = {r['feature']: r for r in report['rows'] if r['active_in_run'] is True and r['feature'] in projected}
        if set(active) != set(projected):
            return {}
        for name, value in projected.items():
            r = active[name]
            if not (digest(trace['features'][name]) == digest(value) == digest(r['raw_value']) == r['lineage']['feature_value_sha256']
                    and r['lineage']['source_sha256'] == evidence.schedule_sha256
                    and r['lineage']['model_artifact_sha256'] == trace['model_artifact_sha256']):
                return {}
        if trace is not forecast and (forecast['event_id'] != eid or forecast['model_id'] != trace['model_id']
                or forecast['input_snapshot_hash'] != digest(trace['features'])
                or forecast['model_state_config_hash'] != trace['model_artifact_sha256']):
            return {}
        if trace is forecast:
            numeric = trace['numerical_identity']
            selected = {r['feature']: trace['features'][r['feature']] for r in report['rows'] if r['active_in_run'] is True}
            if not (numeric['feature_sha256'] == digest(selected)
                    and numeric['model_id'] == trace['model_id'] and numeric['event_id'] == eid
                    and utc(numeric['cutoff_utc']) == utc(cutoff)
                    and numeric['identity_sha256'] == trace['identity'] == digest({k: v for k, v in numeric.items() if k != 'identity_sha256'})):
                return {}
        games = [evidence.schedule[g] for g in state['consumed_game_ids']
                 if evidence.schedule[g]['season'] == game['season']]
        roles = {}
        for side in ('away', 'home'):
            team, player = game[side+'_team'], game[side+'_qb_id']
            if not player or not game[side+'_qb_name']:
                continue
            prior = qstate['last_qb'].get(team)
            clubs = [g[s+'_team'] for g in games for s in ('away', 'home') if g[s+'_qb_id'] == player]
            roles[team] = {'role':'starting_qb', 'team_id':team, 'player_id':player, 'player_name':game[side+'_qb_name'],
                           'previous_team_starter_id':prior, 'same_team_schedule_starts':clubs.count(team),
                           'prior_clubs_in_consumed_season':sorted(set(clubs)-{team}),
                           'changed_from_previous_starter':bool(prior and prior != player),
                           'model_consumption':'QB_ID_BOUND_TO_ACTIVE_FEATURES', 'feature_names':sorted(projected),
                           'assignment_status':'SCHEDULE_ASSIGNED', 'state_sha256':evidence.state_sha256}
        return roles
    except (KeyError, ValueError, TypeError):
        return {}



def _fixture_scope(report, event):
    """Independently bind the curated quote to a fixture, or to a recent named transaction."""
    team = report['team_id']
    side = next((s for s in ('away', 'home') if team in
                 {str(event.get(s+'_id', '')), str(event.get(s+'_team', ''))}), None)
    if not side:
        return False
    start = utc(event['start_time_utc'])
    effective_time = report['published_at_utc'] if report['published_time_verified'] else report['retrieved_at_utc']
    if utc(effective_time) >= start:
        return False
    other = 'home' if side == 'away' else 'away'
    opponent = str(event.get(other+'_team', ''))
    context = _text(report['excerpt']+' '+report['context_excerpt'])
    if report['pdf_matchup']:
        matchup = report['pdf_matchup'].split('@')
        game_names = [str(event.get(s+'_team', '')) for s in ('away','home')]
        def matches(team, code):
            full = NBA_TEAMS.get(code, '')
            return bool(team and full) and team.casefold() in {code.casefold(), full.casefold(), full.rsplit(' ',1)[0].casefold()}
        return (len(matchup) == 2 and all(matches(team, code) for team, code in zip(game_names, matchup))
                and NBA_TEAMS.get(matchup[1 if side == 'home' else 0]) == report['pdf_team']
                and start.astimezone(ZoneInfo('America/New_York')).date() == utc(report['published_at_utc']).astimezone(ZoneInfo('America/New_York')).date())
    league = report['league']
    team_domain = NFL_TEAM_HOSTS.get(team) if league == 'NFL' else COLLEGE_TEAM_HOSTS.get((league,team))
    host = urlsplit(report['source_url']).hostname or ''
    from_club = bool(team_domain and (host == team_domain or host.endswith('.'+team_domain)))
    team_label = str(event.get(side+'_team',''))
    if league == 'NFL':
        team_label = NFL_NICKNAMES.get(team_label, team_label)
    if not from_club and not (team_label and re.search(r'\b'+re.escape(team_label.casefold())+r'\b',context)):
        return False
    if league == 'NFL':
        if report['status'] == 'TRADED':
            aliases = [NFL_NICKNAMES.get(t) for t in (report.get('receiving_team_id', team), report['prior_team_id'])]
            return all(t and re.search(r'\b'+re.escape(t)+r'\b',context) for t in aliases)
        week = re.fullmatch(r'\d{4}_(\d+)_[A-Z0-9]+_[A-Z0-9]+',event['event_id'])
        # A fixture identity established by the source itself binds independently of
        # the week-label heuristic; the manifest assignment alone never scopes a notice.
        if report.get('source_event_id') is not None:
            return report['source_event_id'] == event['event_id']
        if report.get('source_season') is not None or report.get('source_fixture_date_utc') is not None:
            season = int(week.group(0)[:4]) if week else start.year
            return (report.get('source_season') == season
                    and str(report.get('source_fixture_date_utc')) == start.date().isoformat())
        mentioned_weeks = set(re.findall(r'\bweek (\d+)\b', context))
        if week and mentioned_weeks:
            if mentioned_weeks != {str(int(week.group(1)))}:
                return False
            # A club notice may specify its unique scheduled game for the week.
            # A named opponent in the notice must agree with the retained schedule.
            # The week label is season-relative and binds a fixture only for a
            # hand-adjudicated report whose retained quote was verified in place.
            adjudicated = report.get('source_scope') == 'HAND_ADJUDICATED_REPORT_WITH_RETAINED_QUOTE'
            others = {nick for key, nick in NFL_NICKNAMES.items()
                      if key != team and re.search(r'\b'+re.escape(nick)+r'\b',context)}
            intended = NFL_NICKNAMES.get(opponent, opponent.casefold())
            if from_club:
                return adjudicated and (not others or intended in others)
            if others and intended not in others:
                return False
        opponent = NFL_NICKNAMES.get(opponent, opponent)
    if not opponent or opponent.isdecimal():
        return False
    # College fixture rows may use the full team display name while the official
    # preview uses its school name (e.g. Louisville Cardinals -> Louisville).
    terms = [opponent]
    if report['league'] in ('CFB','CBB'):
        terms += [re.sub(r' [^ ]+$','',opponent)]
    return any(t and re.search(r'\b'+re.escape(t.casefold())+r'\b',context) for t in terms)

def review_fixture(league, event, cutoff, *, forecast=None, observations=()):
    """Explain personnel coverage at this specific freeze and later review without re-scoring it."""
    league = str(league).upper()
    event = event or {}
    eid = event.get('event_id')
    result = {'schema':'sports.personnel_event_review.v1', 'league':league, 'event_id':eid,
              'cutoff_utc':cutoff, 'status':'UNVERIFIED', 'roles':[], 'observations':[], 'caveats':[],
              'roles_in_scope':list(ROLES.get(league, ())), 'review_required':False,
              'causal_attribution':'NOT_ESTABLISHED', 'action_authority':False}
    notes = result['caveats']
    result['forecast_available'] = forecast is not None
    try:
        start = utc(event['start_time_utc'])
        if not eid or league not in ROLES:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        notes.append('Event identity or eligible freeze clock unavailable.')
        return result
    try:
        valid_cutoff = utc(cutoff) < start
    except (ValueError, TypeError, AttributeError):
        valid_cutoff = False
    if not valid_cutoff:
        notes.append('No verifiable pregame forecast cutoff.')
    teams = {str(event[key]) for key in ('away_team','home_team','away_id','home_id') if event.get(key) is not None}
    if not isinstance(observations, _Evidence):
        if observations:
            notes.append('Personnel evidence has no verified input manifest.')
        observations = _Evidence()
    roles = {}
    if valid_cutoff and league == 'NFL':
        roles = _nfl_inputs(event, cutoff, forecast, observations)
    if valid_cutoff and league == 'MLB':
        from research.personnel_mlb import pitcher_inputs
        roles = pitcher_inputs(event, cutoff, forecast, observations)
    result['roles'] = list(roles.values())
    transition = False
    for row in roles.values():
        if row.get('changed_from_previous_starter'):
            transition = True
            notes.append(f"{row['team_id']} has a different schedule-assigned starter than in its frozen team state.")
        if row.get('prior_clubs_in_consumed_season') and row.get('same_team_schedule_starts') == 0:
            transition = True
            notes.append(f"{row['player_name']} has prior-club starts and zero starts for {row['team_id']} in the consumed season.")
    reports = [r for r in observations.reports if r['event_id'] == eid and r['league'] == league]
    for r in observations.reports:
        if (r['league'] == league and r['status'] == 'TRADED' and r.get('prior_team_event_id') == eid
                and r['prior_team_id'] in teams and r['team_id'] != r['prior_team_id']):
            reports.append({**r, 'event_id':eid, 'receiving_team_id':r['team_id'], 'team_id':r['prior_team_id'],
                            'source_event_id':r['event_id'], 'direction':'OUTGOING'})
    confirmed = {}
    for notice in reports:
        team, role = notice['team_id'], notice['role']
        timely = valid_cutoff and utc(notice['retrieved_at_utc']) <= utc(cutoff)
        source_status = ('REVIEWED_OFFICIAL_REPORT' if notice['official_source'] and notice['substantive_excerpt']
                         else 'UNVERIFIED_SOURCE_OR_CLAIM')
        binding = roles.get(team, {})
        scoped = _fixture_scope(notice, event) if team in teams else False
        verified = source_status == 'REVIEWED_OFFICIAL_REPORT' and scoped
        status = 'MODEL_USE_UNVERIFIED'
        if team not in teams:
            status = 'FIXTURE_TEAM_UNRESOLVED'
        elif utc(notice['published_at_utc']) >= start:
            verified = False
            status = 'REPORT_PUBLISHED_AFTER_START'
        elif not verified:
            status = 'FIXTURE_CONTEXT_UNVERIFIED' if source_status == 'REVIEWED_OFFICIAL_REPORT' else 'REPORT_UNVERIFIED'
        elif notice.get('direction') == 'OUTGOING':
            status = 'PRIOR_TEAM_DEPARTURE'
        elif binding.get('role') == role:
            same_id = binding['player_id'] == notice['player_id']
            same_name = _text(binding['player_name']) == _text(notice['player_name'])
            if same_id != same_name:
                status = 'PARTICIPANT_ID_CONFLICT'
            elif notice['status'] == 'OUT' and same_id:
                status = 'ASSIGNED_PLAYER_REPORTED_OUT'
            elif notice['status'] == 'STARTING':
                status = 'ASSIGNMENT_AGREES_WITH_REPORT' if same_id else 'DIFFERENT_STARTER_REPORTED'
            elif notice['status'] == 'EXPECTED':
                status = 'EXPECTED_ROLE_ONLY' if same_id else 'DIFFERENT_STARTER_EXPECTED'
            elif same_id:
                status = 'PERSONNEL_CHANGE_REVIEW'
            else:
                status = 'OTHER_PARTICIPANT_REPORTED'
        if verified:
            confirmed.setdefault((team, role), []).append((notice['player_id'], notice['status']))
        result['observations'].append({**notice, 'source_status':source_status, 'fixture_context_verified':scoped, 'comparison':status,
                                       'timing':('CAPTURED_BY_CUTOFF' if timely else 'KNOWN_TO_REVIEW_ONLY') if valid_cutoff else 'NO_VALID_FORECAST_CUTOFF'})
    exclusive = {'starting_qb','starting_pitcher','starting_goalie','goalkeeper'}
    for (_, role), declarations in confirmed.items():
        starters = {player for player, status in declarations if status == 'STARTING'}
        unavailable = {player for player, status in declarations if status == 'OUT'}
        if starters & unavailable or (role in exclusive and len(starters) > 1):
            notes.append('Conflicting personnel reports on the same role require reconciliation.')
            result['status'] = 'CONFLICTING_REPORTS'
    unbound_impact = any(r['comparison'] == 'MODEL_USE_UNVERIFIED' for r in result['observations'])
    if unbound_impact:
        notes.append('An event-specific official personnel report has no verified player-to-feature binding.')
    comparisons = {r['comparison'] for r in result['observations']}
    if result['status'] == 'CONFLICTING_REPORTS':
        pass
    elif comparisons & {'DIFFERENT_STARTER_REPORTED','ASSIGNED_PLAYER_REPORTED_OUT'}:
        result['status'] = 'ASSIGNMENT_CONTRADICTED'
    elif comparisons & {'PARTICIPANT_ID_CONFLICT','DIFFERENT_STARTER_EXPECTED','PERSONNEL_CHANGE_REVIEW','PRIOR_TEAM_DEPARTURE'} or transition or unbound_impact:
        result['status'] = 'PERSONNEL_REVIEW_REQUIRED'
    elif forecast is None:
        result['status'] = 'NO_FROZEN_FORECAST'
    elif comparisons == {'ASSIGNMENT_AGREES_WITH_REPORT'}:
        result['status'] = 'REPORTED_ASSIGNMENT_MATCH'
    elif roles:
        result['status'] = 'SCHEDULE_ASSIGNMENT_ONLY'
    result['review_required'] = result['status'] in {'CONFLICTING_REPORTS','ASSIGNMENT_CONTRADICTED','PERSONNEL_REVIEW_REQUIRED'}
    if not reports:
        notes.append('No event-specific personnel report supplied. Change coverage is unknown.')
    if not roles:
        notes.append('No verified player-to-feature binding for this forecast.')
    if any(r['timing'] == 'KNOWN_TO_REVIEW_ONLY' for r in result['observations']):
        notes.append('A report was retrieved after the freeze. Its contents are available for review only.')
    return result
