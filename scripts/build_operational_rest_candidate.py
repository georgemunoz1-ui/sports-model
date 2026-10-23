#!/usr/bin/env python3
"""Build immutable operational-rest candidate inputs; never fit or infer a model.

History packet schema sports.operational_rest_history.v1 supplies raw source
receipts and upstream source-bound coverage assertions. All-played-game coverage
must be explicit; regular-season-only acquisition does not certify physical rest.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models.current.baseline import IDS, FEATURES
from models.current.common import current, save
from models.current.freshness import (normalize_captured_schedule, rebuild_candidate_features,
                                     state_freshness_receipt)
from models.nfl.contextual.recovered_inference import digest


def build(package_path, history_packet_path, event_id, cutoff_utc, output):
    package_path, history_packet_path, output = map(Path, (package_path, history_packet_path, output))
    raw_package = package_path.read_bytes()
    package = json.loads(raw_package)
    league = package.get('league')
    if (league not in IDS or package.get('model_id') != IDS[league]
            or package.get('schema') != 'sports.current_research_package.v1'
            or package.get('action_authority') is not False or package.get('feature_names') != FEATURES):
        raise ValueError('INITIAL_BASELINE_PACKAGE_REQUIRED')
    required = {'models/current/common.py', 'models/current/linear.py', 'models/current/baseline.py',
                f'pipelines/cards/adapters/{league}.py'}
    if not required.issubset(package.get('code_pins', {})):
        raise ValueError('RUNTIME_CODE_PINS_REQUIRED')
    for name, sha in package['code_pins'].items():
        code = (ROOT/name).resolve()
        if not code.is_relative_to(ROOT) or hashlib.sha256(code.read_bytes()).hexdigest() != sha:
            raise ValueError('RUNTIME_CODE_DRIFT')
    if digest({'model': package['fitted_model'], 'state': package['team_state'], 'prior': package['prior']}) != package['model_sha256']:
        raise ValueError('MODEL_STATE_DIGEST_MISMATCH')
    current(package, cutoff_utc)
    matches = [event for event in package['events'] if event['event_id'] == event_id]
    if len(matches) != 1:
        raise ValueError('EXACT_EVENT_ID_REQUIRED')
    event = matches[0]
    packet_raw = history_packet_path.read_bytes()
    packet = json.loads(packet_raw)
    if packet.get('schema') != 'sports.operational_rest_history.v1' or packet.get('league') != league:
        raise ValueError('REST_HISTORY_PACKET_REQUIRED')
    base = history_packet_path.parent.resolve()
    records, receipts, hashes = [], [], set()
    for source in packet.get('sources', []):
        path = (base/source['raw_path']).resolve()
        if Path(source['raw_path']).is_absolute() or not path.is_relative_to(base):
            raise ValueError('SOURCE_PATH_ESCAPE')
        sha = source['source_sha256']
        if sha in hashes:
            raise ValueError('DUPLICATE_RAW_SOURCE_RECEIPT')
        hashes.add(sha)
        records.extend(normalize_captured_schedule(path.read_bytes(), league=league,
                       captured_at_utc=source['captured_at_utc'], source_sha256=sha))
        receipts.append(dict(source))
    coverage = packet.get('coverage', [])
    if any(row.get('source_sha256') not in hashes for row in coverage):
        raise ValueError('UNBOUND_COVERAGE_SOURCE')
    result = rebuild_candidate_features(package['team_state'], event, package['prior'], records,
                                         cutoff_utc=cutoff_utc, coverage=coverage)
    result['package_sha256'] = hashlib.sha256(raw_package).hexdigest()
    result['history_packet_sha256'] = hashlib.sha256(packet_raw).hexdigest()
    result['source_receipts'] = receipts
    result['legacy_state_receipt'] = state_freshness_receipt(package, event, result['legacy_features'], cutoff_utc=cutoff_utc)
    result['coverage_assertion_basis'] = 'UPSTREAM_SOURCE_CENSUS_REQUIRED_NOT_INFERRED_FROM_NONEMPTY_RECORDS'
    result['forecast_generated'] = False
    result['procedure_code_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in [Path(__file__).resolve(), ROOT/'models/current/freshness.py']}
    result['candidate_artifact_id'] = digest(result)
    output.mkdir(parents=True, exist_ok=False)
    sha = save(output/'candidate.json', result)
    save(output/'manifest.json', {'candidate.json': sha})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package', type=Path, required=True)
    p.add_argument('--history-packet', type=Path, required=True)
    p.add_argument('--event-id', required=True)
    p.add_argument('--as-of-utc', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = build(a.package, a.history_packet, a.event_id, a.as_of_utc, a.output)
    print(json.dumps({key: result[key] for key in ['candidate_artifact_id', 'candidate_ready', 'adoption_status', 'forecast_generated']}))


if __name__ == '__main__':
    main()
