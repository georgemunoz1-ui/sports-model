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
    gold = {_key(x) for x in gold_rows}
    pred = {_key(x) for x in pred_rows}
    return precision_recall_f1(gold, pred)


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
        fps = sorted(x for x in pkeys - gkeys if x[2] in destructive_event_types(league))
        by_type = {}
        for event_type in sorted({x.get("event_type") for x in gold_l + pred_l if x.get("event_type")}):
            by_type[event_type] = _score(
                [x for x in gold_l if x.get("event_type") == event_type],
                [x for x in pred_l if x.get("event_type") == event_type],
            )
        by_league[league] = {**score, "by_event_type": by_type, "destructive_false_positive_count": len(fps)}
        destructive_fp[league] = fps

    pred_state_counts = Counter(str(x.get("cross_model_state")) for x in pred_rows if x.get("cross_model_state"))
    return {
        "schema_version": "sports_information_multisport_benchmark.v1",
        "overall": _score(gold_rows, pred_rows),
        "by_league": by_league,
        "destructive_false_positives_by_league": destructive_fp,
        "cross_model_state_counts": dict(sorted(pred_state_counts.items())),
        "global_only_metric_for_promotion": False,
        "promotion_requires_league_stratified_review": True,
    }
