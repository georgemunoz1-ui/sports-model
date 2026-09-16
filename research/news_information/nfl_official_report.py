"""Deterministic NFL report table extraction. Provider profile URLs are NOT canonical IDs."""
import re
from html import unescape
from html.parser import HTMLParser
from research.news_information.contracts import digest, sha256_bytes


class Table(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows = []; self.row = None; self.cell = None; self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.row = []
        if tag in ('td', 'th'): self.cell = []; self.links = []
        if tag == 'a' and self.cell is not None:
            link = dict(attrs).get('href')
            if link: self.links.append(link)

    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append((' '.join(''.join(self.cell).split()), self.links))
            self.cell = None; self.links = []
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row); self.row = None


def parse_nfl_report(raw, receipt):
    if sha256_bytes(raw) != receipt['raw_sha256']:
        raise ValueError('NFL source receipt hash mismatch')
    html = raw.decode('utf-8')
    year = re.search(r'<h1[^>]*>\s*(\d{4}) NFL Injury Report\s*</h1>', html)
    week = re.search(r'Injuries\s*-\s*WEEK\s+(\d+)', html)
    if not year or not week:
        raise ValueError('NFL report season/week context missing')
    pattern = r'<div class="d3-o-section-sub-title"><span>([^<]+)</span></div></div>\s*<div class="d3-o-table--horizontal-scroll">\s*(<table\b.*?</table>)'
    tables = re.findall(pattern, html, re.S)
    if not tables:
        raise ValueError('no recognized NFL injury tables; cannot infer healthy roster')
    practice = {'Full Participation in Practice': 'FULL', 'Limited Participation in Practice': 'LIMITED',
                'Did Not Participate In Practice': 'DNP', '': 'UNKNOWN'}
    designations = {'Out': 'OUT', 'Questionable': 'QUESTIONABLE', 'Doubtful': 'DOUBTFUL', '': 'UNKNOWN'}
    rows = []
    for team, table_html in tables:
        table = Table(); table.feed(table_html)
        if not table.rows or [x[0] for x in table.rows[0]] != ['Player', 'Position', 'Injuries', 'Practice Status', 'Game Status']:
            raise ValueError('NFL table header changed')
        for cells in table.rows[1:]:
            if len(cells) != 5: raise ValueError('NFL table width changed')
            name, position, injuries, training, game = [x[0] for x in cells]
            refs = [x for x in cells[0][1] if re.fullmatch(r'/players/[a-zA-Z0-9-]+/', x)]
            if len(refs) != 1 or not name: raise ValueError('NFL player profile reference missing/ambiguous')
            row = {'league': 'NFL', 'season': int(year[1]), 'week': int(week[1]),
                   'team_report_name': unescape(team), 'player_name': name,
                   'official_profile_url': 'https://www.nfl.com' + refs[0], 'position': position,
                   'injury_text': injuries, 'practice_raw': training, 'game_status_raw': game,
                   'practice_state': practice.get(training, 'UNRESOLVED'),
                   'game_status': designations.get(game, 'UNRESOLVED'),
                   'canonical_player_id': None, 'event_id': None, 'identity_status': 'UNRESOLVED',
                   'published_at_utc': None, 'practice_date': None, 'effective_at_utc': None,
                   'retrieved_at_utc': receipt['retrieved_at_utc'], 'source_sha256': receipt['raw_sha256'],
                   'forecast_adjustment_eligible': False, 'action_authority': 'OFF'}
            rows.append({**row, 'observation_id': digest(row)})
    if len({r['official_profile_url'] for r in rows}) != len(rows):
        raise ValueError('duplicate NFL player across report tables')
    return {'schema_version': 'nfl_official_report_observations.v1', 'observations': rows,
            'parsed_tables': len(tables), 'parsed_player_rows': len(rows),
            'status': 'PARSED_UNBOUND_RESEARCH', 'roster_coverage': None,
            'date_event_identity_binding': 'REQUIRED', 'action_authority': 'OFF'}
