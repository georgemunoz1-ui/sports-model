from __future__ import annotations

from collections import Counter
from typing import Any

DESTRUCTIVE = {"PLAYER_OUT", "STARTER_SCRATCHED", "BULLPEN_UNAVAILABLE"}


def _key(row: dict[str, Any]):
    return (str(row.get("example_id")), str(row.get("event_type")), str(row.get("subject_id")), str(row.get("event_id")))


def precision_recall_f1(gold: set, pred: set):
    tp = len(gold & pred); fp = len(pred - gold); fn = len(gold - pred)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1}


def score_event_extraction(gold_rows: list[dict[str, Any]], pred_rows: list[dict[str, Any]]) -> dict[str, Any]:
    gold = {_key(x) for x in gold_rows}
    pred = {_key(x) for x in pred_rows}
    overall = precision_recall_f1(gold, pred)
    destructive_false_positives = sorted(x for x in pred - gold if x[1] in DESTRUCTIVE)
    wrong_event = 0
    wrong_subject = 0
    gold_by_example = {}
    for g in gold_rows:
        gold_by_example.setdefault(str(g["example_id"]), []).append(g)
    for p in pred_rows:
        for g in gold_by_example.get(str(p.get("example_id")), []):
            if p.get("event_type") == g.get("event_type") and p.get("subject_id") == g.get("subject_id") and p.get("event_id") != g.get("event_id"):
                wrong_event += 1
            if p.get("event_type") == g.get("event_type") and p.get("event_id") == g.get("event_id") and p.get("subject_id") != g.get("subject_id"):
                wrong_subject += 1
    post_cutoff_leakage = sum(bool(x.get("known_before_cutoff") is False and x.get("used_as_prediction") is True) for x in pred_rows)
    by_type = {}
    for event_type in sorted({x[1] for x in gold | pred}):
        by_type[event_type] = precision_recall_f1({x for x in gold if x[1] == event_type}, {x for x in pred if x[1] == event_type})
    return {
        "schema_version": "sports_information_component_benchmark.v1",
        "overall": overall,
        "by_event_type": by_type,
        "destructive_false_positive_count": len(destructive_false_positives),
        "destructive_false_positives": destructive_false_positives,
        "wrong_event_assignment_count": wrong_event,
        "wrong_subject_assignment_count": wrong_subject,
        "post_cutoff_leakage_count": post_cutoff_leakage,
    }


def score_ensemble(records: list[dict[str, Any]]) -> dict[str, Any]:
    states = Counter(str(x.get("cross_model_state")) for x in records)
    total = len(records)
    return {
        "n": total,
        "agreement_rate": states.get("CONSENSUS", 0) / total if total else 0.0,
        "conflict_rate": states.get("CONFLICTING", 0) / total if total else 0.0,
        "abstention_rate": states.get("ABSTAIN", 0) / total if total else 0.0,
        "state_counts": dict(sorted(states.items())),
    }
