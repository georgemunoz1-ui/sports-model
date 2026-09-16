#!/usr/bin/env python3
"""Fail-closed contract checks for the preregistered CFB v2 challenger."""

from __future__ import annotations

MODULE_ID = "cfb_v2_contract"

import argparse
import copy
import json
from datetime import datetime
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
PREREG = BASE / "data/cfb/model/CFB_V2_PREREG.json"
MODEL_ID = "cfb.fbs.epa_talent_hgb.v2_0.challenger"

ALLOWED_LIFECYCLE_STATES = {
    "PREREGISTERED_DATA_ACQUISITION_PENDING",
    "DATA_ACQUISITION_RUNNING",
    "DATA_ACQUIRED_FEATURE_BUILD_PENDING",
    "FEATURE_BUILD_RUNNING",
    "OOF_EVALUATION_PENDING",
    "OOF_EVALUATION_RUNNING",
    "HISTORICALLY_VALIDATED_SHADOW_PENDING_PROSPECTIVE",
    "REJECTED",
}

ALLOWED_PREDICTIVE_PROVENANCE = {
    "RAW_GAME_ARTIFACT",
    "CAUSAL_TEAM_STATE",
    "PREGAME_PERSONNEL_ARTIFACT",
    "PREGAME_CONTEXT_ARTIFACT",
    "MISSINGNESS_INDICATOR",
}

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


def load_prereg(record: dict | None = None) -> dict:
    """Load and validate the preregistration, allowing mutation injection in tests."""
    if record is None:
        if not PREREG.is_file():
            raise ContractError("CFB v2 preregistration is missing")
        record = json.loads(PREREG.read_text(encoding="utf-8"))
    elif not isinstance(record, dict):
        raise ContractError("CFB v2 preregistration must be an object")
    else:
        record = copy.deepcopy(record)
    if record.get("model_id") != MODEL_ID:
        raise ContractError("CFB v2 model identity drifted")
    if record.get("status") not in ALLOWED_LIFECYCLE_STATES:
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


def validate_column_provenance(record: dict, columns: list[dict]) -> None:
    """Reject renamed market inputs by validating lineage, not only column names."""
    features = ordered_features(record)
    by_feature: dict[str, dict] = {}
    for index, column in enumerate(columns):
        if not isinstance(column, dict):
            raise ContractError(f"column provenance row {index} is not an object")
        feature = str(column.get("feature", ""))
        if feature in by_feature:
            raise ContractError(f"duplicate column provenance for {feature!r}")
        if feature not in features:
            raise ContractError(f"unregistered predictive column {feature!r}")
        provenance = column.get("provenance_class")
        if provenance not in ALLOWED_PREDICTIVE_PROVENANCE:
            raise ContractError(
                f"predictive feature {feature!r} has forbidden provenance {provenance!r}"
            )
        if column.get("market_derived") is not False:
            raise ContractError(f"predictive feature {feature!r} is market-derived")
        bindings = column.get("source_bindings")
        if not isinstance(bindings, list) or not bindings:
            raise ContractError(f"predictive feature {feature!r} lacks source bindings")
        by_feature[feature] = column
    missing = sorted(set(features) - set(by_feature))
    if missing:
        raise ContractError(f"predictive column provenance incomplete: {missing}")


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
    prereg_mutations = [
        ({**record, "model_id": "cfb.changed"}, "identity"),
        ({**record, "output": {**record["output"], "stake": 1}}, "stake"),
        ({**record, "status": "UNREGISTERED_LIVE_MODEL"}, "lifecycle"),
    ]
    for mutated, _ in prereg_mutations:
        try:
            load_prereg(mutated)
        except ContractError:
            continue
        failures += 1

    try:
        validate_feature_names(features + ["closing_line_home"])
    except ContractError:
        pass
    else:
        failures += 1

    provenance = [
        {
            "feature": feature,
            "provenance_class": (
                "MISSINGNESS_INDICATOR"
                if feature.endswith("_available")
                else "CAUSAL_TEAM_STATE"
            ),
            "market_derived": False,
            "source_bindings": ["fixture:pregame-source"],
        }
        for feature in features
    ]
    validate_column_provenance(record, provenance)
    market_alias = copy.deepcopy(provenance)
    market_alias[0]["provenance_class"] = "MARKET_DERIVED"
    market_alias[0]["market_derived"] = True
    try:
        validate_column_provenance(record, market_alias)
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
        f"({len(features)} frozen features; identity, lifecycle, provenance, "
        "market, result, chronology and stake gates enforced)"
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
            f"CFB v2 contract: {record['status']} "
            f"({record['model_id']}; {len(features)} frozen features)"
        )
        return 0
    except (ContractError, ValueError) as exc:
        print(f"CFB v2 contract: FAIL ({exc})")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
