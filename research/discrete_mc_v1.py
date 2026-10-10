"""Opt-in numerical research bridge for existing discrete distribution artifacts.

Consumes existing distributions or shared-card distribution reports. It does not
call/refit/reseed selected forecast engines, change registries, or grant authority.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
from models.common import discrete_research as D
from research.mc_precision_v1 import PrecisionPlan, PrecisionMonitor, SemanticStreams, digest, draw_receipt

ENGINE_ID = 'sports.discrete_mc_precision.research.v1'
MAX_DRAWS = 1_000_000


def select_distribution(payload, *, event_id=None, model_id=None, product=None):
    """Accept the real shared-card downstream report or one canonical law."""
    if payload.get('schema') == D.SCHEMA:
        candidates = [payload]
    elif payload.get('schema') == 'sports.distribution_card.research.v1':
        material = dict(payload)
        recorded_hash = material.pop('artifact_sha256', None)
        if D.digest(material) != recorded_hash:
            raise ValueError('CARD_REPORT_HASH_MISMATCH')
        if payload.get('action_authority') is not False or payload.get('prospective_grade_eligible') is not False:
            raise ValueError('RESEARCH_ONLY_REPORT_REQUIRED')
        candidates = [r['distribution'] for r in payload.get('results', []) if r.get('status') == 'DIAGNOSTIC']
    else:
        raise ValueError('DISCRETE_DISTRIBUTION_OR_CARD_REPORT_REQUIRED')
    selected = [d for d in candidates if
                (event_id is None or d.get('provenance', {}).get('event_id') == event_id) and
                (model_id is None or d.get('model_id') == model_id) and
                (product is None or d.get('product') == product)]
    if len(selected) != 1:
        raise ValueError('EXACTLY_ONE_DISTRIBUTION_REQUIRED_USE_SELECTORS')
    D.validate(selected[0])
    return selected[0]


def _binding(d):
    provenance = d.get('provenance', {})
    event = D.identity(provenance.get('event_id'), 'EVENT_ID')
    cutoff = provenance.get('cutoff')
    D.stamp(cutoff)
    return (event, cutoff, d['league'], d['product'], d['settlement'])


def run(distributions, *, line, side, experiment_id, root_seed, plan=None, replicate=0):
    """Sample one or two fixed finite laws with an explicit versioned coupling.

    All five settlement categories are predeclared endpoints. With two laws,
    five paired differences join the same simultaneous interval family. No price
    enters the generator; line/side only classify already specified score support.
    """
    plan = PrecisionPlan() if plan is None else plan
    if plan.checkpoints[-1] > MAX_DRAWS:
        raise ValueError('RESEARCH_DRAW_CAP_EXCEEDED')
    if not 1 <= len(distributions) <= 2:
        raise ValueError('ONE_OR_TWO_DISTRIBUTIONS_REQUIRED')
    validated = [D.validate(d) for d in distributions]
    bindings = [_binding(d) for d in distributions]
    if any(b != bindings[0] for b in bindings):
        raise ValueError('PAIRED_EVENT_CUTOFF_PRODUCT_SETTLEMENT_MISMATCH')
    if len({d['model_id'] for d in distributions}) != len(distributions):
        raise ValueError('DISTINCT_PAIRED_MODEL_IDENTITIES_REQUIRED')
    exact = [D.price(d, line, side) for d in distributions] # validates side/line
    labels = []
    for d, (support, _) in zip(distributions, validated):
        labels.append(np.array([D.outcome(int(x), league=d['league'], product=d['product'],
                       settlement=d['settlement'], line=line, side=side) for x in support]))
    bounds = {f'arm_{i}.{state}': (0., 1.) for i in range(len(distributions)) for state in D.STATES}
    if len(distributions) == 2:
        bounds.update({f'delta_0_minus_1.{state}': (-1., 1.) for state in D.STATES})
    monitor = PrecisionMonitor(plan, bounds)
    streams = SemanticStreams(experiment_id=experiment_id, event_id=bindings[0][0], root_seed=root_seed, replicate=replicate)
    cdfs = [np.cumsum(p) for _, p in validated]
    for cdf in cdfs:
        cdf[-1] = 1.
    chunks = [[] for _ in distributions]
    looks = []
    previous = 0
    for n in plan.checkpoints:
        u = streams.uniforms('finite_score_inverse_cdf.v1', n-previous)
        observations = {}
        arm_values = []
        for i, ((support, _), cdf, label) in enumerate(zip(validated, cdfs, labels)):
            indices = np.searchsorted(cdf, u, side='right')
            chunks[i].append(support[indices].astype('<i8'))
            category = label[indices]
            arm_values.append({state: (category == state).astype(float) for state in D.STATES})
            observations.update({f'arm_{i}.{state}': arr for state, arr in arm_values[-1].items()})
        if len(distributions) == 2:
            observations.update({f'delta_0_minus_1.{state}': arm_values[0][state]-arm_values[1][state] for state in D.STATES})
        result = monitor.update(observations)
        looks.append(result)
        previous = n
        if result['stop']:
            break
    paths = [np.concatenate(c) for c in chunks]
    code = digest({'bridge_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   'precision_sha256': hashlib.sha256(Path(__file__).with_name('mc_precision_v1.py').read_bytes()).hexdigest(),
                   'distribution_code_sha256': D.code_hash()})
    report = {'schema': ENGINE_ID, 'engine_id': ENGINE_ID,
              'source_distribution_ids': [d['model_id'] for d in distributions],
              'event_id': bindings[0][0], 'cutoff': bindings[0][1], 'league': bindings[0][2],
              'product': bindings[0][3], 'settlement': bindings[0][4], 'line': line, 'side': side,
              'sampling_design': 'IID_PATHS', 'coupling': 'COMMON_SEMANTIC_INVERSE_CDF_V1',
              'implementation_sha256': code, 'exact_law_probabilities': exact, 'looks': looks,
              'actual_draws': result['actual_draws'], 'stream': streams.receipt(),
              'uncertainty_scope': 'NUMERICAL_ONLY_CONDITIONAL_ON_INPUT_DISTRIBUTIONS',
              'parameter_uncertainty_included_by_this_engine': False,
              'predictive_validation': 'NOT_ASSESSED', 'prospective_grade_eligible': False,
              'publication_eligibility': 'INELIGIBLE', 'action_authority': False,
              'frozen_source_modified': False, 'arms': []}
    for i, (d, values) in enumerate(zip(distributions, paths)):
        receipt = draw_receipt(values, model_id=d['model_id']+'::'+ENGINE_ID,
             code_commit='implementation:'+code, input_sha256=digest(d), state_sha256=digest({'fixed_law':d['distribution_sha256']}),
             distribution_sha256='sha256:'+d['distribution_sha256'],stream_receipt=streams.receipt(),precision_report=result)
        report['arms'].append({'source_model_id': d['model_id'], 'source_distribution_sha256': d['distribution_sha256'],
                              'research_simulation_id': d['model_id']+'::'+ENGINE_ID, 'receipt': receipt})
    report['report_sha256'] = digest(report)
    return paths, report


def write_run(output, paths, report):
    """New-directory-only output prevents overwriting a frozen artifact."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    files=[]
    for i, values in enumerate(paths):
        name=f'arm_{i}_draws.npy'
        np.save(output/name,values,allow_pickle=False)
        files.append({'file':name,'file_sha256':hashlib.sha256((output/name).read_bytes()).hexdigest(),
                      'encoding':'numpy_npy_little_endian_int64','count':len(values)})
    report = dict(report)
    report['path_files']=files
    report.pop('report_sha256',None)
    report['report_sha256']=digest(report)
    (output/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
    return report
