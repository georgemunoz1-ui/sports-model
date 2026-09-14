from __future__ import annotations

from collections import Counter
from typing import Any

from research.news_information.benchmark import precision_recall_f1
from research.news_information.taxonomies import SUPPORTED_LEAGUES, destructive_event_types


def _key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("league")),
        str(row.get("example_id")),
        str(row.get("event_type")),
        str(row.get("subject_id")),
        str(row.get("event_id")),
    )


def _score(gold_rows: list[dict[str, Any]], pred_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return precision_recall_f1({_key(x) for x in gold_rows}, {_key(x) for x in pred_rows})


def _assignment_errors(gold_rows: list[dict[str, Any]], pred_rows: list[dict[str, Any]]) -> tuple[int, int]:
    wrong_event = 0
    wrong_subject = 0
    gold_by_example: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for gold in gold_rows:
        gold_by_example.setdefault((str(gold.get("league")), str(gold.get("example_id"))), []).append(gold)
    for pred in pred_rows:
        key = (str(pred.get("league")), str(pred.get("example_id")))
        for gold in gold_by_example.get(key, []):
            if (pred.get("event_type") == gold.get("event_type")
                    and pred.get("subject_id") == gold.get("subject_id")
                    and pred.get("event_id") != gold.get("event_id")):
                wrong_event += 1
            if (pred.get("event_type") == gold.get("event_type")
                    and pred.get("event_id") == gold.get("event_id")
                    and pred.get("subject_id") != gold.get("subject_id")):
                wrong_subject += 1
    return wrong_event, wrong_subject


def _tier_scores(gold_rows: list[dict[str, Any]], pred_rows: list[dict[str, Any]]) -> dict[str, Any]:
    tiers = sorted({int(x["source_tier"]) for x in gold_rows + pred_rows if x.get("source_tier") is not None})
    return {
        str(tier): _score(
            [x for x in gold_rows if x.get("source_tier") == tier],
            [x for x in pred_rows if x.get("source_tier") == tier],
        )
        for tier in tiers
    }


def score_multisport_extraction(gold_rows: list[dict[str, Any]],
                                pred_rows: list[dict[str, Any]]) -> dict[str, Any]:
    leagues = sorted({str(x.get("league")) for x in gold_rows + pred_rows if x.get("league")})
    unknown = sorted(set(leagues) - set(SUPPORTED_LEAGUES))
    if unknown:
        raise ValueError(f"unsupported leagues in benchmark: {unknown}")

    by_league = {}
    destructive_fp = {}
    for league in leagues:
        gold_l = [x for x in gold_rows if x.get("league") == league]
        pred_l = [x for x in pred_rows if x.get("league") == league]
        score = _score(gold_l, pred_l)
        gkeys = {_key(x) for x in gold_l}
        pkeys = {_key(x) for x in pred_l}
        destructive = destructive_event_types(league)
        fps = sorted(x for x in pkeys - gkeys if x[2] in destructive)
        by_type = {}
        for event_type in sorted({x.get("event_type") for x in gold_l + pred_l if x.get("event_type")}):
            by_type[event_type] = _score(
                [x for x in gold_l if x.get("event_type") == event_type],
                [x for x in pred_l if x.get("event_type") == event_type],
            )
        wrong_event, wrong_subject = _assignment_errors(gold_l, pred_l)
        post_cutoff = sum(
            x.get("known_before_cutoff") is False and x.get("used_as_prediction") is True
            for x in pred_l
        )
        destructive_gold = [x for x in gold_l if x.get("event_type") in destructive]
        destructive_pred = [x for x in pred_l if x.get("event_type") in destructive]
        nondestructive_gold = [x for x in gold_l if x.get("event_type") not in destructive]
        nondestructive_pred = [x for x in pred_l if x.get("event_type") not in destructive]
        by_league[league] = {
            **score,
            "by_event_type": by_type,
            "by_source_tier": _tier_scores(gold_l, pred_l),
            "by_claim_severity": {
                "DESTRUCTIVE": _score(destructive_gold, destructive_pred),
                "NON_DESTRUCTIVE": _score(nondestructive_gold, nondestructive_pred),
            },
            "destructive_false_positive_count": len(fps),
            "wrong_event_assignment_count": wrong_event,
            "wrong_subject_assignment_count": wrong_subject,
            "post_cutoff_leakage_count": int(post_cutoff),
        }
        destructive_fp[league] = fps

    wrong_event, wrong_subject = _assignment_errors(gold_rows, pred_rows)
    pred_state_counts = Counter(str(x.get("cross_model_state")) for x in pred_rows if x.get("cross_model_state"))
    return {
        "schema_version": "sports_information_multisport_benchmark.v1",
        "overall": _score(gold_rows, pred_rows),
        "by_league": by_league,
        "destructive_false_positives_by_league": destructive_fp,
        "wrong_event_assignment_count": wrong_event,
        "wrong_subject_assignment_count": wrong_subject,
        "post_cutoff_leakage_count": int(sum(
            x.get("known_before_cutoff") is False and x.get("used_as_prediction") is True
            for x in pred_rows
        )),
        "cross_model_state_counts": dict(sorted(pred_state_counts.items())),
        "global_only_metric_for_promotion": False,
        "promotion_requires_league_stratified_review": True,
    }
