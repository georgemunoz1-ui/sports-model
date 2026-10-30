#!/usr/bin/env python3
"""Replay retained real-cohort forecasts, paired metrics and sampling receipts."""
import argparse
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from models.common import discrete_research as D, discrete_calibration as C
from research.evaluate_discrete_products import evaluate
from scripts.run_distribution_history import distributions, contracts, diagnostics, sha
from research.replay_controls import equivalent, write_snapshot
from research.distribution_replay_adapter import reconstruct


def equivalent_law(actual, expected):
    D.validate(actual); D.validate(expected)
    equivalent({k:v for k,v in actual.items() if k != 'distribution_sha256'},
               {k:v for k,v in expected.items() if k != 'distribution_sha256'})


def verify(root):
    manifest = json.loads((root / 'manifest.json').read_text())
    for path, h in manifest.items():
        p = (root / path).resolve()
        if not p.is_relative_to(root.resolve()) or sha(p) != h:
            raise ValueError('STUDY_ARTIFACT_DRIFT:' + path)
    study = json.loads((root / 'summary.json').read_text())
    if study['runner_sha256'] != sha(ROOT / 'scripts/run_distribution_history.py'):
        raise ValueError('STUDY_RUNNER_DRIFT')
    portable = json.loads((root / 'portable_replay_manifest.json').read_text())
    if sha(root / 'manifest.json') != portable['original_manifest_sha256']:
        raise ValueError('ORIGINAL_MANIFEST_DRIFT')
    for rel, h in portable['files'].items():
        p = (root / rel).resolve()
        if not p.is_relative_to(root.resolve()) or sha(p) != h:
            raise ValueError('FROZEN_DISTRIBUTION_DRIFT')
    report = {'products': 0, 'evaluation_game_products': 0, 'draws_replayed': 0,
              'numeric_tolerance_absolute': 1e-11, 'artifact_and_draw_equality': 'EXACT',
              'source_scope': 'RETAINED_NORMALIZED_COHORT_NOT_INDEPENDENT_SOURCE_ATTESTATION',
              'adapter_receipts': [], 'pit_verdict': 'UNRESOLVED',
              'predictive_validation': 'NOT_ASSESSED', 'wagering_authority': 'OFF'}
    for league, products in study['results'].items():
        for product, expected in products.items():
            if 'evaluation_n' not in expected:
                continue
            folder = root / league
            rows = json.loads(gzip.decompress((folder / (product + '_cohort.json.gz')).read_bytes()))
            predictions = []
            models = []
            for method in ('empirical', 'conditional_scale'):
                model = json.loads((folder / (product + '_' + method + '.json')).read_text())
                if model['training_sha256'] != D.digest(rows['residual']):
                    raise ValueError('TRAINING_COHORT_DRIFT')
                errors = np.array([r['observed'] - r['predicted_mean'] for r in rows['residual']])
                if method == 'conditional_scale':
                    s = model['scaling']
                    x = np.array([[r['scale_features'][k] for k in s['features']] for r in rows['residual']])
                    z = np.column_stack([np.ones(len(x)), (x-s['mean'])/s['sd']])
                    errors /= np.exp(np.clip(z @ s['beta'], -8, 16)/2)
                equivalent(errors.tolist(), model['residuals'], abs_tol=1e-12)
                laws, receipt = reconstruct(model, rows['evaluation'])
                report['adapter_receipts'].append(receipt)
                models.append(model)
                predictions.append([{'distribution': law,
                    **{k: r[k] for k in ('start_time_utc', 'result_available_at', 'observed', 'result_source_sha256')},
                    'block_id': D.stamp(r['start_time_utc']).strftime('%G-%V')}
                    for law, r in zip(laws, rows['evaluation'])])
            # Expected numerical checkpoints are loaded only after reconstruction.
            frozen = json.loads(gzip.decompress((folder / (product + '_frozen_distributions.json.gz')).read_bytes()))
            hashes = json.loads(gzip.decompress((folder / (product + '_prediction_hashes.json.gz')).read_bytes()))
            actual = {r['distribution']['model_id']+':'+r['distribution']['provenance']['event_id']:
                      r['distribution']['distribution_sha256'] for group in frozen[:2] for r in group}
            if actual != hashes:
                raise ValueError('FROZEN_PREDICTION_HASH_MISMATCH')
            for actual_group, saved_group in zip(predictions, frozen[:2]):
                if len(actual_group) != len(saved_group): raise ValueError('PREDICTION_COUNT')
                for actual_row, saved_row in zip(actual_group, saved_group):
                    equivalent({k:v for k,v in actual_row.items() if k != 'distribution'},
                               {k:v for k,v in saved_row.items() if k != 'distribution'})
                    equivalent_law(actual_row['distribution'], saved_row['distribution'])
            predictions = frozen[:2]
            metric = evaluate(contracts(sum(predictions, []), product), baseline_id=models[0]['model_id'],
                              challenger_id=models[1]['model_id'], bootstrap=2000, seed=7)
            saved = json.loads((folder / (product + '_scale_evaluation.json')).read_text())
            # JSON round-trip converts the scope tuple to its serialized list.
            equivalent(json.loads(json.dumps(metric)), saved)
            for key, prediction in zip(('baseline', 'conditional_scale'), predictions):
                equivalent(diagnostics(prediction), expected[key])
            if expected['calibration_status'] == 'FITTED':
                cal = json.loads((folder / (product + '_cdf.json')).read_text())
                calibrated = [{**r, 'distribution': C.apply(r['distribution'], cal)} for r in predictions[0]]
                if len(calibrated) != len(frozen[2]): raise ValueError('CALIBRATION_COUNT')
                for a, b in zip(calibrated, frozen[2]): equivalent_law(a['distribution'], b['distribution'])
                calibrated = frozen[2]
                creport = evaluate(contracts(predictions[0]+calibrated, product), baseline_id=models[0]['model_id'],
                                   challenger_id=cal['model_id'], bootstrap=2000, seed=7)
                saved = json.loads((folder / (product + '_cdf_evaluation.json')).read_text())
                equivalent(json.loads(json.dumps(creport)), saved)
                equivalent(diagnostics(calibrated), expected['calibrated'])
            draws, receipt = D.simulate(predictions[0][0]['distribution'], draws=100000)
            saved = np.load(io.BytesIO(gzip.decompress((folder / (product + '_draws.npy.gz')).read_bytes())), allow_pickle=False)
            if not np.array_equal(draws, saved) or receipt != json.loads((folder / (product + '_simulation_receipt.json')).read_text()):
                raise ValueError('DRAW_REPLAY_MISMATCH')
            report['products'] += 1; report['evaluation_game_products'] += len(rows['evaluation'])
            report['draws_replayed'] += len(draws)
            print(json.dumps({'verified': league+':'+product, 'games': len(rows['evaluation'])}), flush=True)
    return report


def retain_evidence(root, output, report):
    identity = {'study_manifest_sha256': sha(root / 'manifest.json'),
                'verifier_sha256': sha(__file__)}
    run_id = 'distribution-replay-' + D.digest({'identity': identity, 'report': report})[:24]
    def evidence(kind, verdict, detail):
        return {'kind': kind, 'run_id': run_id, 'verdict': verdict,
                'evidence': {**identity, **detail}}
    reports = {
        'replay': evidence('replay', 'PASS', {'execution_report': report}),
        'pit': evidence('pit', 'UNRESOLVED', {'reason': 'Reconstructed historical availability; not original pregame capture.'}),
        'semantic': evidence('semantic', 'NOT_RUN', {'reason': 'Independent semantic test execution must be bound separately; checkpoint match is insufficient.'}),
        'source': evidence('source', 'NOT_AUTHENTICATED', {'reason': report['source_scope']}),
        'predictive': evidence('predictive', 'NOT_ASSESSED', {'reason': 'Numerical replay does not evaluate later outcomes or transfer predictive qualification.'}),
    }
    return write_snapshot(output, run_id=run_id, reports=reports)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('root', type=Path)
    ap.add_argument('--evidence-dir', type=Path, help='Append-only local reports; no registration or eligibility grant')
    args = ap.parse_args()
    report = verify(args.root)
    if args.evidence_dir:
        report['evidence_snapshot'] = str(retain_evidence(args.root, args.evidence_dir, report))
    print(json.dumps(report, indent=2), flush=True)
