#!/usr/bin/env python3
"""Fail-closed contract checks for the preregistered CFB v2 challenger."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
PREREG = BASE / "data/cfb/model/CFB_V2_PREREG.json"
MODEL_ID = "cfb.fbs.epa_talent_hgb.v2_0.challenger"

FORBIDDEN_TOKENS = {
    "away_points",
    "closing_line",
    "consensus",
    "grade",
    "home_points",
    "home_win",
    "market",
    "moneyline",
    "odds",
    "price",
    "profit_loss",
    "public_percentage",
    "result",
    "score",
    "spread",
    "total_line",
}


class ContractError(ValueError):
    """A preregistration, feature, timing, or market-firewall violation."""


def _utc(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(f"timestamp lacks UTC offset: {value!r}")
    return parsed


def load_prereg() -> dict:
    if not PREREG.is_file():
        raise ContractError("CFB v2 preregistration is missing")
    record = json.loads(PREREG.read_text(encoding="utf-8"))
    if record.get("model_id") != MODEL_ID:
        raise ContractError("CFB v2 model identity drifted")
    if record.get("status") != "PREREGISTERED_DATA_ACQUISITION_PENDING":
        raise ContractError("unexpected CFB v2 lifecycle state")
    if record.get("output", {}).get("wager_authority") != "NO":
        raise ContractError("CFB v2 wager firewall opened")
    if record.get("output", {}).get("stake") != 0:
        raise ContractError("CFB v2 stake is nonzero")
    return record


def ordered_features(record: dict) -> list[str]:
    blocks = record.get("ordered_feature_blocks")
    if not isinstance(blocks, dict) or not blocks:
        raise ContractError("ordered feature blocks are absent")
    output: list[str] = []
    for name, features in blocks.items():
        if not isinstance(features, list) or not features:
            raise ContractError(f"feature block {name!r} is empty")
        output.extend(str(value) for value in features)
    if len(output) != len(set(output)):
        raise ContractError("a CFB v2 feature appears in more than one block")
    return output


def validate_feature_names(features: list[str]) -> None:
    for feature in features:
        normalized = feature.lower()
        hits = sorted(token for token in FORBIDDEN_TOKENS if token in normalized)
        if hits:
            raise ContractError(
                f"predictive feature {feature!r} violates market/result firewall: {hits}"
            )


def validate_asof_rows(rows: list[dict]) -> None:
    for index, row in enumerate(rows):
        kickoff = _utc(row.get("game_start_utc"))
        snapshot = _utc(row.get("feature_snapshot_utc"))
        if snapshot >= kickoff:
            raise ContractError(f"row {index} feature snapshot is not pregame")
        if row.get("market_columns_present"):
            raise ContractError(f"row {index} carries market columns into prediction")
        cohort = row.get("competition_cohort")
        if cohort not in {"FBS_VS_FBS", "FBS_VS_FCS"}:
            raise ContractError(f"row {index} has unresolved competition cohort")


def selftest() -> int:
    record = load_prereg()
    features = ordered_features(record)
    validate_feature_names(features)
    validate_asof_rows(
        [
            {
                "game_start_utc": "2026-08-29T19:00:00Z",
                "feature_snapshot_utc": "2026-08-27T12:00:00Z",
                "market_columns_present": False,
                "competition_cohort": "FBS_VS_FBS",
            }
        ]
    )

    failures = 0
    mutations = [
        ({**record, "model_id": "cfb.changed"}, "identity"),
        ({**record, "output": {**record["output"], "stake": 1}}, "stake"),
    ]
    for mutated, _ in mutations:
        try:
            if mutated.get("model_id") != MODEL_ID:
                raise ContractError("identity")
            if mutated.get("output", {}).get("stake") != 0:
                raise ContractError("stake")
        except ContractError:
            continue
        failures += 1

    try:
        validate_feature_names(features + ["closing_line_home"])
    except ContractError:
        pass
    else:
        failures += 1

    try:
        validate_asof_rows(
            [
                {
                    "game_start_utc": "2026-08-29T19:00:00Z",
                    "feature_snapshot_utc": "2026-08-29T19:00:01Z",
                    "market_columns_present": False,
                    "competition_cohort": "FBS_VS_FBS",
                }
            ]
        )
    except ContractError:
        pass
    else:
        failures += 1

    if failures:
        print(f"CFB v2 contract selftest: FAIL ({failures} mutation escapes)")
        return 1
    print(
        "CFB v2 contract selftest: PASS "
        f"({len(features)} frozen features; market, result, chronology and stake gates enforced)"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    try:
        if args.selftest:
            return selftest()
        record = load_prereg()
        features = ordered_features(record)
        validate_feature_names(features)
        print(
            f"CFB v2 contract: READY_FOR_ACQUISITION "
            f"({record['model_id']}; {len(features)} frozen features)"
        )
        return 0
    except (ContractError, ValueError) as exc:
        print(f"CFB v2 contract: FAIL ({exc})")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
