#!/usr/bin/env python3
"""Score fixed hypothetical handicap ladders from frozen study distributions.

This is descriptive sensitivity analysis, not a timestamped-market backtest.
All lines within an event stay together in paired time-block resampling.
"""
from __future__ import annotations
import argparse
import gzip
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models.common import discrete_research as D
from research.evaluate_margin_system import evaluate
from scripts.run_margin_system_study import sha, write

GRIDS = {
    'cfb': [-14., -7., -3.5, -3., 0., 3., 3.5, 7., 14.],
    'nba': [-10., -7.5, -5., -2.5, 0., 2.5, 5., 7.5, 10.],
    'nhl': [-2.5, -1.5, -1., 0., 1., 1.5, 2.5],
    'mls': [-1.5, -1., -.75, -.5, -.25, 0., .25, .5, .75, 1., 1.5],
}


def run(study, output):
    study, output = Path(study), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    summary = json.loads((study/'summary.json').read_text())
    design = {'schema': 'sports.margin_ladder_evaluation.design.v1', 'created_at_utc': D.writer_clock(),
              'kind': 'DESCRIPTIVE_FIXED_THRESHOLD_SENSITIVITY_NO_REFITTING', 'home_handicap_grids': GRIDS,
              'study_summary_sha256': sha(study/'summary.json'), 'script_sha256': sha(__file__),
              'evaluator_sha256': sha(ROOT/'research/evaluate_margin_system.py'),
              'source_sha256': {league:sha(study/league/'evaluation_rows.json.gz') for league in summary['results']},
              'market_lines': False, 'promotion': False, 'action_authority': False}
    write(output/'design.json',design)
    for league, meta in summary['results'].items():
        rows=json.loads(gzip.decompress((study/league/'evaluation_rows.json.gz').read_bytes()))
        for row in rows:
            row.pop('contract',None)
            row['contracts']=[{'line':line,'side':'HOME','line_role':'DIAGNOSTIC_GRID',
                               'line_orientation':'HOME_HANDICAP'} for line in GRIDS[league]]
        report=evaluate(rows,baseline_id=meta['baseline_id'],challenger_id=meta['challenger_id'],
                        bootstrap=1000,seed=7,block_length=2)
        write(output/f'{league}.json',report)
        print(json.dumps({'league':league,'events':meta['evaluation_n'],'thresholds':len(GRIDS[league])}),flush=True)
    write(output/'manifest.json',{p.name:sha(p) for p in sorted(output.iterdir()) if p.is_file()})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.study,a.output)
