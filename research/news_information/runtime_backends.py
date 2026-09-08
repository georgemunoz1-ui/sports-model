"""Optional local-runtime loaders for pinned research snapshots.

No model is downloaded here. Loaders require a previously materialized, hash-verified local snapshot.
Backends are deliberately lazy so the repository's engineering test suite remains stdlib-only.
NuExtract3 is exposed through an injected callable until its exact pinned checkpoint API passes a
materialization smoke test; this prevents guessing a remote-code execution contract.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from research.news_information.model_adapters import ModelRuntimeError


def transformers_pipeline_backend(snapshot: Path, task: str, *, device: int = -1):
    try:
        from transformers import pipeline
    except ImportError as exc:
        raise ModelRuntimeError("transformers is not installed") from exc
    pipe = pipeline(task, model=str(snapshot), tokenizer=str(snapshot), device=device, local_files_only=True)

    def backend(*, operation: str, **kwargs):
        if operation in {"SENTIMENT_TRIAGE", "EXTRACT"}:
            return pipe(kwargs["text"])
        if operation == "NLI_VERIFY":
            return pipe({"text": kwargs["premise"], "text_pair": kwargs["hypothesis"]})
        raise ModelRuntimeError(f"unsupported operation for transformers pipeline: {operation}")
    return backend


def gliner_backend(snapshot: Path):
    try:
        from gliner import GLiNER
    except ImportError as exc:
        raise ModelRuntimeError("gliner is not installed") from exc
    model = GLiNER.from_pretrained(str(snapshot), local_files_only=True)

    def backend(*, operation: str, **kwargs):
        if operation != "EXTRACT":
            raise ModelRuntimeError("GLiNER backend only supports EXTRACT")
        return model.predict_entities(kwargs["text"], kwargs.get("labels") or [])
    return backend


def encoder_backend(snapshot: Path, *, device: str = "cpu"):
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as exc:
        raise ModelRuntimeError("torch + transformers are required for encoder benchmark") from exc
    tok = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True)
    model = AutoModel.from_pretrained(str(snapshot), local_files_only=True).to(device).eval()

    def backend(*, operation: str, **kwargs):
        if operation != "ENCODE":
            raise ModelRuntimeError("encoder backend only supports ENCODE")
        x = tok(kwargs["text"], return_tensors="pt", truncation=True).to(device)
        with torch.no_grad():
            hidden = model(**x).last_hidden_state[:, 0, :]
        return {"embedding": hidden[0].detach().cpu().tolist(), "dimension": int(hidden.shape[-1])}
    return backend


def bge_reranker_backend(snapshot: Path, *, device: str = "cpu"):
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as exc:
        raise ModelRuntimeError("torch + transformers are required for BGE reranker") from exc
    tok = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(str(snapshot), local_files_only=True).to(device).eval()

    def backend(*, operation: str, **kwargs):
        if operation != "RERANK":
            raise ModelRuntimeError("BGE backend only supports RERANK")
        x = tok([[kwargs["query"], kwargs["text"]]], padding=True, truncation=True,
                return_tensors="pt", max_length=512).to(device)
        with torch.no_grad():
            score = model(**x, return_dict=True).logits.view(-1).float()[0].item()
        return {"relevance_logit": score}
    return backend


def nuextract3_injected_only(*args, **kwargs):
    raise ModelRuntimeError(
        "NuExtract3 runtime loader is intentionally fail-closed until the pinned checkpoint's local "
        "multimodal API passes materialization smoke validation; use an injected audited backend."
    )
