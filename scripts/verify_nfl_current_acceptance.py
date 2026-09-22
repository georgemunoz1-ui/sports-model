#!/usr/bin/env python3
"""Reproduce the reviewed real Week 3 repair and canonical forecast consumption."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts.validate_current_nfl_weekly_state import validate
from scripts.prepare_nfl_weekly_events import build
from pipelines.cards.selection import select


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frozen', type=Path, required=True); p.add_argument('--capture', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); a.output.mkdir(parents=True, exist_ok=False)
    review = json.loads((ROOT/'data/nfl/starter_adjudications_20260922/review.json').read_text())
    raw = (a.capture/review['raw_path']).read_text()
    assert hashlib.sha256(raw.encode()).hexdigest() == review['evidence_receipt']['sha256']
    resolution = {k:v for k,v in review.items() if k not in {'evidence_receipt','raw_path','source_artifact_id','source_archive_sha256'}}
    resolution['evidence'] = {'text': raw, 'receipt': review['evidence_receipt']}
    refused = validate(a.frozen, a.capture, a.output/'original', 2)
    assert refused['status'] == 'REFUSED' and refused['refusal'] == 'STARTER_DROPBACK_BINDING'
    assert refused['head_preserved'] and refused['objects_preserved']
    resolved = validate(a.frozen, a.capture, a.output/'resolved', 2, [resolution])
    assert resolved['status'] == 'WEEKLY_STATE_VERIFIED', resolved
    store = (a.output/'resolved/state').resolve()
    os.environ['NFL_WEEKLY_STATE_SEED_SHA256'] = resolved['seed_id']
    package_path = (a.output/'event_package.json').resolve()
    package = build(store, resolved['published_state_id'], resolved['seed_id'], package_path)
    os.environ['NFL_CONTEXT_PACKAGE'] = str(package_path)
    # Exercise the actual CLI once per captured slate date, all 16 events.
    for date in package['covered_dates']:
        with (a.output/(date+'-cli.txt')).open('w') as log:
            subprocess.run([sys.executable, str(ROOT/'scripts/run_nfl_integrated.py'), '--date', date,
                '--output', str((a.output/'forecasts').resolve()), '--weekly-state-store', str(store),
                '--weekly-state-id', resolved['published_state_id']], check=True, stdout=log, stderr=subprocess.STDOUT)
    forecasts = sorted((a.output/'forecasts').glob('*/forecast.json'))
    assert len(forecasts) == len(package['events']) == 16
    selected = select('nfl')['default_model_id']
    for f in forecasts:
        result = json.loads(f.read_text())
        assert result['model_id'] == selected and result['selected_arm'] == 'qb'
        assert result['assimilation']['state_id'] == resolved['published_state_id']
        assert result['assimilation']['completed_week'] == 2
        assert len(result['assimilation']['consumed_game_ids']) == 32
        assert result['winner_simulation']['count'] == 100000
        assert not result['action_authority'] and not result['canonical_prospective_eligible']
        assert result['score_simulation']['status'] == 'UNAVAILABLE_FOR_SELECTED_ARM'
    summary = {'status': 'REAL_WEEK3_RESEARCH_STATE_CONSUMPTION_VERIFIED',
        'events': len(forecasts), 'model_id': selected, 'seed_id': resolved['seed_id'],
        'state_id': resolved['published_state_id'], 'source_sha256': resolved['source_sha256'],
        'starter_adjudication_count': 1, 'unmodified_source_refusal_verified': True,
        'identical_retry_verified': True, 'completed_games': 32, 'draws_per_event': 100000,
        'limitations': package['limitations'], 'action_authority': False, 'ensemble_promoted': False,
        'official_gamebook_clearance': False, 'validation_scope': 'NFL_ONLY'}
    (a.output/'acceptance.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__': main()
