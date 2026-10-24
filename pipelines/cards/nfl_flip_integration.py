"""Presentation diagnostics outside the frozen NFL numerical source and RNG identity."""
import copy
import hashlib
import json
from pathlib import Path

from models.nfl.contextual import runtime
from models.nfl.contextual.flip_diagnostics import build_flip_diagnostics, append_flip_diagnostic
from models.nfl.contextual.recovered_inference import digest


def attach_diagnostic(bundle, artifact):
    result = copy.deepcopy(bundle)
    if result.get('mode') != 'research_pregame':
        return result
    valid_artifact = (isinstance(artifact, dict)
        and result.get('model_artifact_sha256') == digest(artifact)
        and all(name in artifact.get('arms', {}) for name in ('base', 'qb')))
    models = None
    if valid_artifact:
        result['arm_feature_references'] = {'model_artifact_sha256': digest(artifact), 'arms': {
            name: {'model_id': artifact['arms'][name]['model_id'],
                   'feature_names': copy.deepcopy(artifact['arms'][name]['feature_names']),
                   'home_win_head': copy.deepcopy(artifact['arms'][name]['heads']['home_win'])}
            for name in ('base', 'qb')}}
        models = {name: params['model_id'] for name, params in artifact['arms'].items()}
    else:
        result.pop('arm_feature_references', None)
    # Missing or misbound diagnostic evidence stays visible without discarding
    # the independent frozen parent forecast.
    result['flip_diagnostics'] = build_flip_diagnostics(result, arm_model_ids=models)
    return result


def run(artifact, *args, **kwargs):
    result, winner, scores = runtime.run(artifact, *args, **kwargs)
    return attach_diagnostic(result, artifact), winner, scores


def persist_run(folder, bundle, winner, scores, design):
    runtime.persist_run(folder, bundle, winner, scores, design)
    if 'flip_diagnostics' not in bundle:
        return
    # A separate manifest avoids rewriting the already frozen forecast manifest.
    path = Path(folder) / 'diagnostics'
    path.mkdir(exist_ok=False)
    data = (json.dumps(bundle['flip_diagnostics'], sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    with (path / 'flip_diagnostics.json').open('xb') as stream:
        stream.write(data)
    with (path / 'manifest.json').open('x') as stream:
        json.dump({'flip_diagnostics.json': hashlib.sha256(data).hexdigest()}, stream, sort_keys=True)
    append_flip_diagnostic(Path(folder).parent / 'flip_diagnostics.jsonl', bundle['flip_diagnostics'])


def enhanced(football, *args, **kwargs):
    from models.nfl.modes import runtime as modes
    source = copy.deepcopy(football)
    diagnostic = source.pop('flip_diagnostics', None)
    result, winner, scores = modes.enhanced(source, *args, **kwargs)
    if diagnostic is not None:
        result['football_reference']['flip_diagnostics'] = diagnostic
    return result, winner, scores
