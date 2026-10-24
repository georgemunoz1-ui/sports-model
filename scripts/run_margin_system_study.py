#!/usr/bin/env python3
"""Evaluate a preregistered margin challenger on retained chronological cohorts.

Historical timing is reconstruction, never original point-in-time evidence.
Does not modify any parent, default, old forecast, or authority setting.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models.common import discrete_research as D
from models.common import margin_challenger as M
from research.evaluate_margin_system import evaluate


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, sort_keys=True, indent=2, allow_nan=False)
        f.write('\n')


def run(source, output, *, leagues=('cfb', 'nba', 'nhl', 'mls'), bootstrap=1000):
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    design = {
        'schema': 'sports.margin_system_study.design.v1',
        'created_at_utc': D.writer_clock(),
        'hypothesis': 'Training-only fitted dense integer mixture may reduce unsupported outcomes while preserving or improving CRPS.',
        'baseline': 'Frozen empirical residual distribution fitted on residual split only.',
        'challenger': 'margin_challenger defaults frozen by code hash before evaluation',
        'training': 'residual split only; chronological inner model selection',
        'evaluation': 'all events in retained evaluation split; calibration split unused',
        'primary_metric': 'paired CRPS; challenger minus baseline',
        'guardrails': ['zero-probability outcomes', 'mean absolute error', 'interval coverage and width', 'fixed-threshold probability scoring'],
        'bootstrap': {'replicates': bootstrap, 'seed': 7, 'block_length': 2},
        'information_regime': 'RETROSPECTIVE_RECONSTRUCTION_REUSED_HISTORICAL_COHORT',
        'historical_availability_proven': False,
        'untouched_holdout': False,
        'market_superiority': 'NOT_EVALUATED_NO_AUTHENTIC_QUOTES',
        'promotion': 'HOLD_REQUIRES_UNTOUCHED_PROSPECTIVE_EVIDENCE',
        'action_authority': False,
        'leagues': list(leagues),
        'code_sha256': {str(p.relative_to(ROOT)): sha(p) for p in [Path(__file__), ROOT/'models/common/margin_challenger.py', ROOT/'models/common/discrete_research.py', ROOT/'research/evaluate_margin_system.py']},
        'source_sha256': {f'{league}/{name}': sha(source/league/name) for league in leagues for name in ['margin_cohort.json.gz', 'margin_empirical.json']},
    }
    write(output/'design.json', design)
    results = {}
    for league in leagues:
        folder = output/league
        folder.mkdir()
        cohort = json.loads(gzip.decompress((source/league/'margin_cohort.json.gz').read_bytes()))
        baseline = json.loads((source/league/'margin_empirical.json').read_text())
        model = M.fit(cohort['residual'], league=league, settlement=baseline['settlement'],
                      parent_model_id=baseline['parent_model_id'], information_set=baseline['information_set'],
                      fitted_at=baseline['fit_as_of_utc'], scale_features=('absolute_parent_margin',))
        write(folder/'challenger.json', model)
        rows = []
        for r in cohort['evaluation']:
            shared = dict(mean=r['predicted_mean'], event_id=r['event_id'], cutoff=r['forecast_cutoff'],
                          parent_model_id=r['parent_model_id'], information_set=r['information_set'],
                          parent_forecast_sha256=r['forecast_sha256'], scale_features=r['scale_features'])
            distributions = [D.predict(baseline, **shared), M.predict(model, start_time_utc=r['start_time_utc'], **shared)]
            for distribution in distributions:
                row = {k: r[k] for k in ['observed', 'start_time_utc', 'result_available_at', 'result_source_sha256', 'parent_fit_cutoff']}
                row.update(distribution=distribution, block_id=D.stamp(r['start_time_utc']).strftime('%G-%V'),
                           contract={'line': 0, 'side': 'HOME', 'line_role': 'DIAGNOSTIC_GRID'})
                rows.append(row)
        with (folder/'evaluation_rows.json.gz').open('xb') as f:
            f.write(gzip.compress(json.dumps(rows, sort_keys=True, separators=(',', ':'), allow_nan=False).encode(), mtime=0))
        report = evaluate(rows, baseline_id=baseline['model_id'], challenger_id=model['model_id'],
                          bootstrap=bootstrap, seed=7, block_length=2)
        write(folder/'evaluation.json', report)
        results[league] = {'training_n': len(cohort['residual']), 'evaluation_n': len(cohort['evaluation']),
                           'baseline_id': baseline['model_id'], 'challenger_id': model['model_id'],
                           'report_file': f'{league}/evaluation.json'}
        print(json.dumps({'league': league, **results[league]}), flush=True)
    summary = {'schema': 'sports.margin_system_study.results.v1', 'created_at_utc': D.writer_clock(),
               'design_sha256': sha(output/'design.json'), 'results': results,
               'unavailable': {s: 'NO_MATCHED_RETAINED_COHORT' for s in ('nfl','wnba','mlb') if s not in leagues},
               'execution_status': 'COMPLETED', 'predictive_validation': 'UNVALIDATED',
               'publication_eligibility': 'INELIGIBLE', 'wagering_authority': 'OFF',
               'prospective_grade_eligible': False, 'historical_availability_proven': False,
               'untouched_holdout': False, 'action_authority': False}
    write(output/'summary.json', summary)
    write(output/'manifest.json', {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob('*')) if p.is_file()})
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--league', action='append', choices=['cfb','nba','nhl','mls'])
    p.add_argument('--bootstrap', type=int, default=1000)
    a=p.parse_args()
    run(a.source, a.output, leagues=a.league or ('cfb','nba','nhl','mls'), bootstrap=a.bootstrap)


if __name__=='__main__':
    main()
