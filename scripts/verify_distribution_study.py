#!/usr/bin/env python3
"""Replay retained real-cohort forecasts, paired metrics and sampling receipts."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from models.common import discrete_research as D, discrete_calibration as C
from research.evaluate_discrete_products import evaluate
from scripts.run_distribution_history import distributions, contracts, diagnostics, sha


def verify(root):
    manifest = json.loads((root / 'manifest.json').read_text())
    for path, h in manifest.items():
        p = (root / path).resolve()
        if not p.is_relative_to(root.resolve()) or sha(p) != h:
            raise ValueError('STUDY_ARTIFACT_DRIFT:' + path)
    study = json.loads((root / 'summary.json').read_text())
    if study['runner_sha256'] != sha(ROOT / 'scripts/run_distribution_history.py'):
        raise ValueError('STUDY_RUNNER_DRIFT')
    report = {'products': 0, 'evaluation_game_products': 0, 'draws_replayed': 0,
              'source_scope': 'RETAINED_NORMALIZED_COHORT_NOT_INDEPENDENT_SOURCE_ATTESTATION'}
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
                if not np.allclose(errors, model['residuals'], atol=1e-12, rtol=0):
                    raise ValueError('FITTED_RESIDUAL_MISMATCH')
                models.append(model); predictions.append(distributions(model, rows['evaluation']))
            hashes = json.loads(gzip.decompress((folder / (product + '_prediction_hashes.json.gz')).read_bytes()))
            actual = {r['distribution']['model_id']+':'+r['distribution']['provenance']['event_id']:
                      r['distribution']['distribution_sha256'] for group in predictions for r in group}
            if actual != hashes:
                raise ValueError('PREDICTION_REPLAY_MISMATCH')
            metric = evaluate(contracts(sum(predictions, []), product), baseline_id=models[0]['model_id'],
                              challenger_id=models[1]['model_id'], bootstrap=2000, seed=7)
            saved = json.loads((folder / (product + '_scale_evaluation.json')).read_text())
            # JSON round-trip converts the scope tuple to its serialized list.
            if json.loads(json.dumps(metric)) != saved:
                raise ValueError('PAIRED_METRIC_REPLAY_MISMATCH')
            for key, prediction in zip(('baseline', 'conditional_scale'), predictions):
                if diagnostics(prediction) != expected[key]:
                    raise ValueError('DISTRIBUTION_DIAGNOSTIC_MISMATCH')
            if expected['calibration_status'] == 'FITTED':
                cal = json.loads((folder / (product + '_cdf.json')).read_text())
                calibrated = [{**r, 'distribution': C.apply(r['distribution'], cal)} for r in predictions[0]]
                creport = evaluate(contracts(predictions[0]+calibrated, product), baseline_id=models[0]['model_id'],
                                   challenger_id=cal['model_id'], bootstrap=2000, seed=7)
                saved = json.loads((folder / (product + '_cdf_evaluation.json')).read_text())
                if json.loads(json.dumps(creport)) != saved or diagnostics(calibrated) != expected['calibrated']:
                    raise ValueError('CALIBRATION_REPLAY_MISMATCH')
            draws, receipt = D.simulate(predictions[0][0]['distribution'], draws=100000)
            saved = np.load(io.BytesIO(gzip.decompress((folder / (product + '_draws.npy.gz')).read_bytes())), allow_pickle=False)
            if not np.array_equal(draws, saved) or receipt != json.loads((folder / (product + '_simulation_receipt.json')).read_text()):
                raise ValueError('DRAW_REPLAY_MISMATCH')
            report['products'] += 1; report['evaluation_game_products'] += len(rows['evaluation'])
            report['draws_replayed'] += len(draws)
            print(json.dumps({'verified': league+':'+product, 'games': len(rows['evaluation'])}), flush=True)
    return report


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('root', type=Path); args = ap.parse_args()
    print(json.dumps(verify(args.root), indent=2), flush=True)
