# Joint energy scoring correction, version 2

Status: local software verification complete; independent review, hosted checks,
artifact retrieval and owner confirmation of remote changes remain separate.
This corrects score construction, not a forecast or a model/default verdict.

## Defect and reproduced counterexample

The historical `volatility_matrix_v1.energy_score` divides each forecast's
support and observation by that forecast's own predictive standard deviation.
That value is retained as a legacy normalized diagnostic, but it is not a
proper score for comparing differently dispersed forecasts.

For synthetic legal MLS scores, let the true law put probabilities
`[0.25, 0.5, 0.25]` on `[(9,4), (10,5), (11,6)]`. The legacy expected score is
0.75 for the true law but 0.7071067811865475 for the incorrect wider law
`[(8,3), (12,7)]` with probabilities `[0.5, 0.5]`. Lower scores are preferred,
so the old comparison incorrectly rewards the wider law.

## Corrected metric contract

`models/common/volatility_scoring_v2.py` defines
`joint_energy.euclidean_raw_score.v2`:

`E ||X - y||_2 - 0.5 E ||X - X_prime||_2`.

Coordinates are always `[home_score, away_score]`; component scales are the
fixed definition `[1.0, 1.0]`. Neither forecast SD, outcomes nor caller-supplied
values choose the scale. Every score carries its metric version, coordinate
order, scale-source identity and hash, metric-contract hash, and scorer-code
hash. The finite-support sum is exact; chunking only bounds temporary memory.

Under the same synthetic truth, the corrected expected score is
0.5303300858899106 for the true law and 1.4142135623730951 for the wider law.
This is a software counterexample and correction, not sports predictive evidence.

Comparisons require the same league, settlement, event population and metric.
Each aggregate accepts one model identity. Candidate aggregates must still be
compared on the same events under a separately preregistered evaluation design.
Raw scores across leagues with different scoring units are not pooled.

## New records and explicit historical rescoring

The v2 record schema is `sports.luck_accounting.research.v2`; the aggregate
schema is `sports.volatility_evaluation.research.v2`. An aggregate rejects v1
records, any different metric/scale/coordinate contract, mixed model or
settlement scope, duplicate events and a different scorer-code identity.
Existing scalar residual diagnostics are retained in new v2 records; their
energy field uses only the v2 score. The aggregate reports the v2 energy mean.

The CLI now makes the version choice explicit through command names:

```bash
# New v2 diagnostic; create-only output.
python scripts/cross_sport_volatility_research.py grade \
  --distribution frozen-distribution.json --input result.json --output new-v2.json

# V2 records only; legacy records fail closed instead of being silently mixed.
python scripts/cross_sport_volatility_research.py evaluate \
  --input evaluation-v2.json --output new-evaluation-v2.json

# Separate derived rescoring, retaining the exact original grade parent hash.
python scripts/cross_sport_volatility_research.py rescore-v2 \
  --distribution frozen-distribution.json --legacy-record original-v1.json \
  --output separate-derived-v2.json
```

`rescore-v2` validates the original grade hash, event, distribution, forecast,
cutoff and start bindings, then reuses the same observed outcome/source. It
does not revise a grade or create independent event evidence. The successor
retains the original grade's exact artifact hash and labels derived rescoring.
All CLI outputs are exclusive creates, so an existing output path is refused.

Historical behavior remains available only by explicit
`grade-legacy-v1` / `evaluate-legacy-v1` CLI command names or the unchanged v1
Python API. Those paths are for reproduction of the old normalized diagnostic,
not proper energy-score model comparison. The previous documentation and
historical claims remain part of the record; this document is their correction.

## Preservation and limits

The hash-pinned `models/common/volatility_matrix_v1.py`,
`models/common/discrete_research.py`, all six fitted matrices, their summaries,
existing forecasts/grades, selected defaults and state remain unchanged.
No fit is regenerated and no stored old score is silently replaced.

The targeted suite exercises the counterexample, an independent double-sum
calculation, common scale across forecasts, a guard against consulting forecast
SD, legacy/mixed-metric refusal, explicit parent-bound rescoring, CLI collision
refusal and original source/fit hashes. Hosted execution and downloadable
evidence still require a future owner-authorized remote change and run.
PR106's parent-orientation and closure-evidence incidents are separate repairs.
Predictive qualification, production enablement, model/default promotion,
canonical prospective grading and wagering authority remain ungranted.
