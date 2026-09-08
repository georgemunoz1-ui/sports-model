"""Offline verification of an Actions ZIP; never recapture or rewrite historic output."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile
from research.news_information.contracts import digest, sha256_bytes
from research.news_information.official_pilot import parse_schedule, apply_roster
from research.news_information.nfl_official_report import parse_nfl_report
from research.news_information.state_reducer import reduce_claims


def replay(path):
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate ZIP member')
        reports = [n for n in names if n.endswith('/report.json')]
        if len(reports) != 1: raise ValueError('exactly one report required')
        report_path = reports[0]
        run_root = report_path.rsplit('/', 1)[0]
        raw_root = run_root.split('/runs/')[0]
        read_json = lambda name: json.loads(archive.read(name))
        report = read_json(report_path)
        if report['failures'] or not report['schedule_reconciled']:
            raise ValueError('capture is incomplete; replay acceptance unavailable')
        raws = {}
        for receipt in report['captures']:
            raw = archive.read(raw_root + '/raw/' + receipt['raw_sha256'])
            if sha256_bytes(raw) != receipt['raw_sha256'] or len(raw) != receipt['bytes']:
                raise ValueError('raw source hash/length mismatch')
            retained = read_json(raw_root + '/receipts/' + digest(receipt) + '.json')
            if retained != receipt: raise ValueError('receipt mismatch')
            raws[receipt['raw_sha256']] = raw
        schedule = [r for r in report['captures'] if urlsplit(r['url']).path == '/api/v1/schedule']
        if len(schedule) != 1: raise ValueError('one schedule receipt required')
        games, teams, players, claims = parse_schedule(json.loads(raws[schedule[0]['raw_sha256']]), schedule[0])
        for r in report['captures']:
            path_parts = urlsplit(r['url']).path.split('/')
            if len(path_parts) == 6 and path_parts[3] == 'teams' and path_parts[5] == 'roster':
                apply_roster(json.loads(raws[r['raw_sha256']]), 'mlb:' + path_parts[4], r, players)
        registry = read_json(run_root + '/registry.json')
        core = {k: v for k, v in registry.items() if k != 'registry_sha256'}
        if digest(core) != registry['registry_sha256']: raise ValueError('registry hash mismatch')
        if registry['players'] != list(players.values()) or registry['teams'] != list(teams.values()):
            raise ValueError('identity replay differs')
        full_slate = read_json(run_root + '/full_slate.json')
        if registry['events'] != full_slate or len(full_slate) != len(games):
            raise ValueError('full slate mismatch')
        for expected, actual in zip(games, full_slate):
            if any(actual.get(k) != v for k, v in expected.items()):
                raise ValueError('event replay differs')
        if claims != read_json(run_root + '/claims.json'): raise ValueError('claim replay differs')
        if reduce_claims(claims, report['cutoff_utc']) != read_json(run_root + '/state_snapshot.json'):
            raise ValueError('state replay differs')
        nfl_reports = [r for r in report['captures'] if urlsplit(r['url']).hostname == 'www.nfl.com']
        nfl = parse_nfl_report(raws[nfl_reports[0]['raw_sha256']], nfl_reports[0]) if nfl_reports else None
        if run_root + '/nfl_observations.json' in names and nfl != read_json(run_root + '/nfl_observations.json'):
            raise ValueError('NFL observation replay differs')
        # The original bundle hash also binds all derived files, including report metadata.
        bundle = {Path(n).stem: read_json(n) for n in names if n.startswith(run_root + '/') and n.endswith('.json')}
        if digest(bundle) != run_root.rsplit('/', 1)[1]: raise ValueError('bundle digest mismatch')
    return {'status': 'OFFLINE_REPLAY_PASS', 'archive_sha256': sha256_bytes(Path(path).read_bytes()),
            'cutoff_utc': report['cutoff_utc'], 'source_hashes_verified': len(report['captures']),
            'games_retained': len(full_slate), 'pregame_games_at_capture': sum(g['pregame_at_capture'] for g in full_slate),
            'player_ids': len(players), 'probable_only_ids': [p['canonical_player_id'] for p in players.values()
                                                          if not p['team_assignments']],
            'nfl_reparsed_rows': nfl['parsed_player_rows'] if nfl else None,
            'nfl_identity_status': 'UNRESOLVED', 'extraction_accuracy': None,
            'canonical_prospective_eligible': False, 'action_authority': 'OFF'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('archive', type=Path)
    print(json.dumps(replay(p.parse_args().archive), indent=2, sort_keys=True))
