"""Research-only Monte Carlo numerical precision; no forecast promotion or wagering.

Minimum 100k. Frozen engines are untouched. Bounds cover fixed bounded estimands
at a predeclared finite set of looks, conditional on a fixed simulator. They do
not cover model error, calibration error, unbounded scores, or reused-parameter
nested samples treated as independent observations.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import math
from types import MappingProxyType
import numpy as np

SCHEMA = 'sports.mc_precision.research.v1'
MIN_DRAWS = 100_000


def digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return 'sha256:' + hashlib.sha256(payload.encode()).hexdigest()


class SemanticStreams:
    """Order-independent named streams; one uniform per path per component.

    Couple arms with identical experiment/event/replicate/component coordinates.
    Store model/input identities in each arm ledger, not in the shared key.
    Separate streams intentionally by differing one semantic coordinate.
    Retain this object across batches. Changing chunk size preserves uniforms.
    Distribution transforms must consume these uniforms by inversion or an
    explicitly versioned coupling, not draw from variable-length rejection code.
    """
    def __init__(self, *, experiment_id, event_id, root_seed, replicate=0):
        if not all(isinstance(x, str) and x.strip() for x in (experiment_id, event_id)):
            raise ValueError('NONEMPTY_EXPERIMENT_AND_EVENT_REQUIRED')
        if type(root_seed) is not int or root_seed < 0 or type(replicate) is not int or replicate < 0:
            raise ValueError('NONNEGATIVE_INTEGER_SEED_AND_REPLICATE_REQUIRED')
        self.identity = dict(experiment_id=experiment_id, event_id=event_id,
                             root_seed=root_seed, replicate=replicate,
                             stream_schema='semantic_uniform_stream.v1')
        self._streams = {}
        self.counts = {}

    def uniforms(self, component, count):
        if not isinstance(component, str) or not component.strip():
            raise ValueError('NAMED_COMPONENT_REQUIRED')
        if type(count) is not int or count < 0:
            raise ValueError('NONNEGATIVE_INTEGER_COUNT_REQUIRED')
        if component not in self._streams:
            raw = hashlib.sha256(json.dumps({**self.identity, 'component': component},
                     sort_keys=True, separators=(',', ':')).encode()).digest()
            words = np.frombuffer(raw, dtype='<u4').tolist()
            self._streams[component] = np.random.Generator(np.random.PCG64DXSM(np.random.SeedSequence(words)))
            self.counts[component] = 0
        self.counts[component] += count
        return self._streams[component].random(count)

    def receipt(self):
        return {**self.identity, 'rng': 'numpy.PCG64DXSM', 'numpy_version': np.__version__,
                'component_draw_counts': dict(sorted(self.counts.items())),
                'stream_identity_sha256': digest(self.identity)}


@dataclass(frozen=True)
class PrecisionPlan:
    # Default consumes exactly the existing standard. Extra looks are opt-in.
    checkpoints: tuple[int, ...] = (MIN_DRAWS,)
    alpha: float = 0.05
    tolerance: float = 0.005

    def __post_init__(self):
        if not self.checkpoints or any(type(n) is not int or n < MIN_DRAWS for n in self.checkpoints):
            raise ValueError('MINIMUM_100K_REQUIRED')
        if tuple(sorted(set(self.checkpoints))) != self.checkpoints:
            raise ValueError('INCREASING_UNIQUE_PREDECLARED_CHECKPOINTS_REQUIRED')
        if not math.isfinite(self.alpha) or not 0 < self.alpha < 1:
            raise ValueError('INVALID_ALPHA')
        if not math.isfinite(self.tolerance) or self.tolerance <= 0:
            raise ValueError('INVALID_TOLERANCE')


class PrecisionMonitor:
    """Finite-look simultaneous empirical-Bernstein bands.

    For each of K fixed estimands and L fixed looks, apply Maurer-Pontil (2009)
    Theorem 4 to X and 1-X with delta=alpha/(2*K*L). Union bound gives >=1-alpha
    simultaneous coverage at all looks. log(2/delta)=log(4*K*L/alpha).
    Independence is required across rows; dependence across columns is allowed.
    This is NOT an unbounded-horizon confidence sequence.
    """
    def __init__(self, plan, bounds, *, sampling_design='IID_PATHS'):
        if sampling_design != 'IID_PATHS':
            raise ValueError('BOUND_REQUIRES_IID_PATHS_NOT_RQMC_OR_NESTED_REUSE')
        if not bounds:
            raise ValueError('PREDECLARED_ESTIMANDS_REQUIRED')
        self.plan = plan
        self.bounds = MappingProxyType({name: tuple(pair) for name, pair in bounds.items()})
        for name, pair in self.bounds.items():
            if not isinstance(name, str) or not name or len(pair) != 2:
                raise ValueError('INVALID_ESTIMAND')
            a, b = pair
            if not np.isfinite([a, b]).all() or not a < b:
                raise ValueError('FINITE_BOUNDED_ESTIMAND_REQUIRED')
        self.n = 0
        self.mean = np.zeros(len(bounds))
        self.m2 = np.zeros(len(bounds))
        self._terminal = False

    def update(self, values):
        if self._terminal:
            raise ValueError('MONITOR_ALREADY_STOPPED')
        if set(values) != set(self.bounds):
            raise ValueError('ESTIMAND_SET_CHANGED')
        columns = [np.asarray(values[k], dtype=np.float64) for k in self.bounds]
        if any(x.ndim != 1 for x in columns) or len({len(x) for x in columns}) != 1:
            raise ValueError('ALIGNED_ONE_DIMENSIONAL_PATHS_REQUIRED')
        m = len(columns[0])
        if not m:
            raise ValueError('EMPTY_BATCH')
        next_look = next(n for n in self.plan.checkpoints if n > self.n)
        if self.n + m > next_look:
            raise ValueError('BATCH_CROSSES_PREDECLARED_LOOK')
        x = np.column_stack(columns)
        for j, (a, b) in enumerate(self.bounds.values()):
            if not np.isfinite(x[:, j]).all() or np.any((x[:, j] < a) | (x[:, j] > b)):
                raise ValueError('OUT_OF_BOUND_OR_NONFINITE_OBSERVATION')
        means = x.mean(axis=0)
        m2 = np.sum((x - means) ** 2, axis=0)
        delta = means - self.mean
        total = self.n + m
        self.m2 += m2 + delta ** 2 * self.n * m / total
        self.mean += delta * m / total
        self.n = total
        if self.n not in self.plan.checkpoints:
            return None
        log_term = math.log(4 * len(self.bounds) * len(self.plan.checkpoints) / self.plan.alpha)
        reports = {}
        for j, (name, (a, b)) in enumerate(self.bounds.items()):
            variance = max(0.0, float(self.m2[j] / (self.n - 1)))
            radius = math.sqrt(2 * variance * log_term / self.n) + 7 * (b-a) * log_term / (3 * (self.n - 1))
            mu = float(self.mean[j])
            lo, hi = max(a, mu-radius), min(b, mu+radius)
            reports[name] = {'mean': mu, 'mc_standard_error': math.sqrt(variance/self.n),
                             'simultaneous_mc_interval': [lo, hi],
                             'max_error_bound': max(mu-lo, hi-mu)}
        met = all(x['max_error_bound'] <= self.plan.tolerance for x in reports.values())
        exhausted = self.n == self.plan.checkpoints[-1]
        self._terminal = met or exhausted
        return {'schema': SCHEMA, 'actual_draws': self.n, 'alpha': self.plan.alpha,
                'checkpoints': list(self.plan.checkpoints), 'tolerance': self.plan.tolerance,
                'method': 'FINITE_LOOK_SIMULTANEOUS_EMPIRICAL_BERNSTEIN',
                'coverage_scope': 'FIXED_SIMULATOR_NUMERICAL_ERROR_ONLY',
                'status': 'PRECISION_MET' if met else ('BUDGET_EXHAUSTED_UNRESOLVED' if exhausted else 'CONTINUE'),
                'stop': self._terminal, 'estimands': reports,
                'predictive_validation': 'NOT_ASSESSED', 'action_authority': False}


def paired_summary(a, b, *, sampling_design="IID_PAIRS"):
    """Fixed-N error for IID paired rows, not predictive superiority or a stopping CI.

    Within-row arm dependence is allowed; QMC, antithetic and shared-parameter
    nested rows require a different variance estimator.
    """
    if sampling_design != "IID_PAIRS":
        raise ValueError("PAIRED_STANDARD_ERROR_REQUIRES_IID_ROWS")
    a, b = np.asarray(a, float), np.asarray(b, float)
    if a.ndim != 1 or b.shape != a.shape or len(a) < 2 or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('FINITE_ALIGNED_PAIRS_REQUIRED')
    delta = a-b
    return {'n_pairs': len(a), 'delta_mean': float(delta.mean()),
            'paired_mc_standard_error': float(delta.std(ddof=1)/math.sqrt(len(a))),
            'measured_path_covariance': float(np.cov(a, b, ddof=1)[0, 1]),
            'unpaired_reference_standard_error': float(math.sqrt((a.var(ddof=1)+b.var(ddof=1))/len(a))),
            'interpretation': 'MONTE_CARLO_DIFFERENCE_ONLY_NOT_PREDICTIVE_SUPERIORITY'}


def draw_receipt(draws, *, model_id, code_commit, input_sha256, state_sha256,
                 distribution_sha256, stream_receipt, precision_report):
    """Bind retained numeric paths to an arm and its numerical diagnostic receipt."""
    if not all(isinstance(x, str) and x for x in (model_id, code_commit)):
        raise ValueError('MODEL_AND_CODE_IDENTITY_REQUIRED')
    for h in (input_sha256, state_sha256, distribution_sha256):
        if not isinstance(h, str) or len(h) != 71 or not h.startswith('sha256:'):
            raise ValueError('SHA256_IDENTITY_REQUIRED')
        try:
            int(h[7:], 16)
        except ValueError as exc:
            raise ValueError('SHA256_IDENTITY_REQUIRED') from exc
    raw = np.asarray(draws)
    if raw.dtype.kind not in 'biuf' or raw.ndim not in (1, 2) or not np.isfinite(raw).all():
        raise ValueError('FINITE_NUMERIC_PATHS_REQUIRED')
    array = np.ascontiguousarray(raw, dtype='<f8')
    if len(array) != precision_report['actual_draws']:
        raise ValueError('DRAW_COUNT_RECEIPT_MISMATCH')
    result = {'schema': 'sports.mc_draw_receipt.research.v1', 'model_id': model_id,
              'code_commit': code_commit, 'input_sha256': input_sha256, 'state_sha256': state_sha256,
              'distribution_sha256': distribution_sha256, 'stream': stream_receipt,
              'encoding': 'little_endian_float64_C_order', 'shape': list(array.shape),
              'draw_bytes_sha256': 'sha256:' + hashlib.sha256(array.tobytes()).hexdigest(),
              'precision': precision_report, 'action_authority': False}
    result['receipt_sha256'] = digest(result)
    return result
