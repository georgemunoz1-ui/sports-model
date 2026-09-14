# Sports news information-state stack — research only

Branch contract: `feature/sports-news-information-state` is stacked on PR #17's research evaluator. It introduces no production forecast import, market input, wager selector, registry promotion, or canonical-ledger writer.

## Status vocabulary

`PINNED` means an immutable Hugging Face repository revision is recorded. `MATERIALIZED` means the weights were downloaded separately and a hash receipt was generated. `RUNTIME_SMOKE_PASS` means that pinned local snapshot executed through its adapter. `BENCHMARKED` means it was evaluated on the labeled PIT corpus. `TRUSTED` and `FORECAST_IMPACTING` require later evidence and are **false for every candidate in this stack**.

Current code intentionally does **not** commit model weights. `materialize_models.py` downloads exact revisions to an external cache and emits content-addressed receipts containing SHA-256 for every file. A model being materialized never changes its `trusted=false`, `enabled_by_default=false`, or `forecast_adjustment_eligible=false` state.

## Parallel candidates

- `BAAI/bge-reranker-v2-m3` — source relevance.
- `fastino/gliner2.5-base-v1` — primary structured extraction.
- `maxo99/sports-injury-ner` — sports-status second opinion.
- `numind/NuNER_Zero` — independent zero-shot NER challenger.
- `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` — claim-state/NLI verification.
- `numind/NuExtract3` — screenshot/PDF/document extraction path.
- `microsoft/SportsBERT` — sports-domain encoder benchmark.
- `answerdotai/ModernBERT-base` — future custom fine-tune base.
- `ProsusAI/finbert` — sentiment triage control only.

Exact revisions and upstream-license review state are in `research/model_intake_lock.yaml`. SportsBERT and ProsusAI FinBERT are explicitly `REQUIRES_LICENSE_REVIEW`; the lock does not pretend otherwise.

## Immutable information contract

Every accepted research event is normalized to `research/schemas/sports_information_event.v1.json`. PIT availability uses the conservative retrieval timestamp: a post retrieved after forecast cutoff cannot become known-before-cutoff even when its publication timestamp is earlier.

The closed claim taxonomy includes player availability, lineup, starter confirmation/scratch/pitch limit, bullpen availability, roster moves, travel disruption, roof/weather and delay risk. Subjective statements such as "checked out" or "called it in" emit no deterministic availability claim.

Named identity resolution consumes a separate official entity-index snapshot and uses exact normalized aliases. Ambiguous identities fail closed. Named source trust consumes `source_allowlist.v1.json`; the repository ships with no invented reporter identities.

## Pipeline

```text
raw bytes
 -> content-addressed archive + PIT/source record
 -> BGE relevance output
 -> deterministic claim hints + GLiNER extraction
 -> sports-injury NER + NuNER parallel outputs
 -> DeBERTa NLI verification
 -> official entity/team/game resolution
 -> cross-model agreement/conflict record
 -> sports_information_event.v1
 -> immutable research feature store
 -> later shadow challenger only
```

NuExtract3 uses the same downstream schema. Its model-specific local runtime is intentionally injected/fail-closed until the pinned checkpoint passes an actual materialization smoke test; no remote-code API is guessed in CI.

## Materialization

Requires `huggingface_hub` in a separate research environment:

```bash
python -m research.news_information.materialize_models \
  --candidate all \
  --cache-dir /research-cache/hf \
  --receipt-dir /research-evidence/model-materialization
```

Materialization is deliberately separate from GitHub engineering CI because the full set is large (NuExtract3 alone is multi-GB). CI never downloads weights.

## Engineering tests

```bash
python -m unittest discover -s research -p 'test_*.py' -v
```

The new tests are deterministic and use injected fake component outputs. They exercise model-lock governance, PIT leakage, subjective-effort exclusion, rule extraction, exact/ambiguous entity resolution, immutable storage, destructive-claim gates, ensemble conflicts, benchmark failure counters and zero forecast/action authority.

## Future benchmark gates

The labeled pregame corpus must score each candidate and ensemble on identical examples. Required reports include player/team/entity precision/recall/F1, event F1, NLI state accuracy, correct event assignment, source relevance, latency, conflict/abstention, and explicit counts of `FALSE_PLAYER_OUT`, `FALSE_STARTER_SCRATCH`, `FALSE_BULLPEN_UNAVAILABLE`, wrong team/game assignments and post-cutoff leakage.

Only after extraction evidence exists may a separately versioned shadow MLB challenger consume verified information-state features. Production forecast probabilities, market overlay and action authority remain OFF.
