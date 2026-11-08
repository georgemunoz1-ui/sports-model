"""Verify a frozen CBB shadow card offline; never issue a new forecast."""

import argparse
import csv
import json
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import cbb_shadow as model
from models.common.discrete_research import digest
from scripts import cbb_missingness as missingness


def require(test, description):
    if not test:
        raise ValueError(description)


def verify(inputs, run, expected_card_sha, previous_card=None):
    data = (run / "card.json").read_bytes()
    require(model.sha(data) == expected_card_sha, "PARENT_BYTES_CHANGED")
    card = json.loads(data)
    missingness.verify(card)
    parent = None
    if card["previous_card_sha256"] is not None:
        require(previous_card is not None and model.sha(previous_card.read_bytes()) == card["previous_card_sha256"],
                "PREVIOUS_CARD_INPUT_REQUIRED")
        parent = json.loads(previous_card.read_bytes())
        missingness.verify(parent)
        require(parent["date"] == card["date"] and model.ts(parent["generated_at_utc"]) <= model.ts(card["as_of_utc"]),
                "PREVIOUS_CARD_SCOPE")
    require(
        model.sha((inputs / "manifest.json").read_bytes())
        == card["input_manifest_sha256"],
        "INPUT_MANIFEST_CHANGED",
    )
    require(
        model.sha(Path(model.__file__).read_bytes()) == card["model"]["code_sha256"],
        "RUNNER_SOURCE_CHANGED",
    )
    passed = model.ts(card["generated_at_utc"])
    cutoff = model.ts(card["as_of_utc"])
    require(cutoff <= passed, "FORECAST_CREATION_PRECEDES_CUTOFF")
    history, targets, manifest, sources = model.load(
        inputs, model.date.fromisoformat(card["date"]), cutoff
    )
    state, prior, bank, records, season = model.fit(history)
    if manifest["season"] != season:
        for team in state.values():
            team[:2] *= model.PARAMS["offseason_retention"]
    require(card["history_games_sha256"] == digest(history), "CONSUMED_RESULTS_CHANGED")
    require(
        card["state_sha256"]
        == digest({k: v.tolist() for k, v in sorted(state.items())}),
        "RATINGS_STATE_CHANGED",
    )
    require(
        card["model"]["bank_sha256"] == model.sha(bank.astype("<f8").tobytes()),
        "RESIDUALS_CHANGED",
    )
    require(
        card["market_input"]
        is card["official_release_eligible"]
        is card["action_authority"]
        is False,
        "AUTHORITY",
    )
    require(card["missingness_historical_support"] == missingness.historical_support(history,model.PARAMS["min_prior_games"]),
            "HISTORICAL_MISSINGNESS_SUPPORT_CHANGED")
    require(card["missingness_runtime_checks"] == model.run_contract_checks(targets,state,prior,cutoff),
            "MISSINGNESS_RUNTIME_PROBES_CHANGED")
    receipts = [r["missingness_audit"] for r in card["forecasts"]]
    missingness.attach(card, targets, state, model.PARAMS["min_prior_games"], parent)
    require(receipts == [r["missingness_audit"] for r in card["forecasts"]], "MISSINGNESS_DETAILS_DO_NOT_REPLAY")
    ids = {g["id"]: g for g in targets}
    observed = {r["event_id"].split(":")[1]: r for r in card["forecasts"]}
    require(
        len(observed) == len(card["forecasts"]) == len(ids)
        and ids.keys() == observed.keys(),
        "COVERAGE",
    )
    counted = 0
    max_dev = 0.0
    numeric = []
    with (run / "historical_rows.csv").open() as f:
        for row in csv.DictReader(f):
            numeric.append(row)
    require(
        len(numeric) == len(records)
        and len(records) == len(set(r["id"] for r in records)),
        "HISTORICAL_POPULATION",
    )
    numeric_keys = (
        "margin",
        "total",
        "p_home",
        "actual_margin",
        "actual_total",
        "prior_margin",
        "prior_total",
        "prior_p_home",
    )
    for current, stored in zip(records, numeric):
        require(
            current["id"] == stored["id"] and current["day"] == stored["day"],
            "HISTORICAL_IDENTITY",
        )
        require(
            all(abs(current[k] - float(stored[k])) < 1e-10 for k in numeric_keys),
            "HISTORICAL_FORECAST",
        )
    for k, row in observed.items():
        g = ids[k]
        require(
            row["home_team"] == g["hn"] and row["away_team"] == g["an"], "ORIENTATION"
        )
        if row["forecast_status"] != "FORECAST_GENERATED":
            reason = row["reason"]
            supported = (
                (
                    reason == "OUTSIDE_VERIFIED_D1_PAIR"
                    and (not g["d1"] or g["type"] not in (2, 3))
                )
                or (
                    reason == "NOT_SCHEDULED_PRE_START"
                    and (
                        g["status"] != "STATUS_SCHEDULED"
                        or model.ts(g["utc"]) <= passed
                    )
                )
                or (
                    reason == "INSUFFICIENT_TEAM_HISTORY"
                    and model.admission(g,state,cutoff) == reason
                )
            )
            if reason == "EMPTY_LEGAL_SUPPORT":
                h, a = model.project(state,g,prior)
                scores = np.floor(np.array([h,a])+bank+0.5)
                supported = not ((scores >= 0).all(axis=1) & (scores[:,0] != scores[:,1])).any()
            require(supported or reason in g["issues"], "UNSUPPORTED_EXCLUSION")
            continue
        require(
            g["status"] == "STATUS_SCHEDULED"
            and g["d1"] and not g["issues"]
            and min(state[g["h"]][2],state[g["a"]][2]) >= model.PARAMS["min_prior_games"]
            and g["type"] in (2,3)
            and passed < model.ts(g["utc"]),
            "LATE_OR_WRONG_SCOPE",
        )
        require(
            row["settlement"] == model.SETTLEMENT and row["qualification"] == "NO_PICK",
            "RESEARCH_SCOPE",
        )
        require(
            digest(row["model_input_snapshot"]) == row["input_snapshot_hash"]
            and row["model_state_config_hash"] == digest(card["model"]),
            "INPUT_BINDING",
        )
        h, a = model.project(state, g, prior)
        require(
            [h, a, h - a, h + a]
            == [
                row[z]
                for z in (
                    "projected_home_score",
                    "projected_away_score",
                    "home_margin",
                    "total",
                )
            ],
            "SCORE_HEADS",
        )
        scores = model.legal_scores(h, a, bank)
        require(
            model.sha(scores.astype("<i4").tobytes())
            == row["distribution_input_sha256"],
            "JOINT_RESIDUAL_BINDING",
        )
        sim = row["simulation"]
        expected_seed = int(
            digest(
                [
                    model.MODEL,
                    digest(card["model"]),
                    k,
                    row["input_snapshot_hash"],
                    model.N,
                ]
            )[:16],
            16,
        )
        require(
            sim["seed"] == expected_seed
            and sim["n"] == model.N
            and sim["rng"] == "numpy.PCG64",
            "RNG_IDENTITY",
        )
        pair = scores[
            np.random.Generator(np.random.PCG64(expected_seed)).choice(
                len(scores), model.N
            )
        ]
        f = run / sim["file"]
        require(
            f.name == k + ".npz" and model.sha(f.read_bytes()) == sim["sha256"],
            "NPZ_HASH",
        )
        with np.load(f, allow_pickle=False) as d:
            require(
                np.array_equal(pair[:, 0], d["home"])
                and np.array_equal(pair[:, 1], d["away"]),
                "DRAW_REPLAY",
            )
        require(
            model.sha(pair.astype("<i4").tobytes()) == sim["packed_pair_sha256"],
            "PACKED_ARRAY_BINDING",
        )
        for name, support, draw in [
            ("margin", scores[:, 0] - scores[:, 1], pair[:, 0] - pair[:, 1]),
            ("total", scores.sum(axis=1), pair.sum(axis=1)),
        ]:
            require(
                model.pmf(support) == row["distributions"][name], "MARGINAL_MISMATCH"
            )
            counts = np.searchsorted(
                np.sort(draw), np.unique(support), side="right"
            ) / len(draw)
            cumulative = np.cumsum(row["distributions"][name]["masses"])
            max_dev = max(max_dev, float(abs(counts - cumulative).max()))
        require(
            float((scores[:, 0] > scores[:, 1]).mean()) == row["p_home_win"]
            and float((pair[:, 0] > pair[:, 1]).mean()) == row["p_home_win_sim"],
            "WINNER_PROBABILITY",
        )
        counted += 1
    require(card["forecast_count"] == counted, "FORECAST_COUNT")
    bound = math.sqrt(math.log(4 * counted / 0.01) / (2 * model.N)) if counted else 0.0
    require(max_dev <= bound, "MC_CDF_BOUND")
    return {
        "status": "PASS",
        "card_sha256": expected_card_sha,
        "heldout_rows_replayed": len(records),
        "frozen_rows": len(ids),
        "forecasts_replayed": counted,
        "paired_draws_replayed": counted * model.N,
        "missingness_receipts_replayed": len(observed),
        "model_release_review": {"status":"HOLD", "action_authority":False, "blockers":[
            "INDEPENDENT_FEATURE_CONTRACT_REVIEW_REQUIRED", "PRODUCT_LIMITS_AND_FORWARD_MONITORING_REQUIRED",
            "NO_PRODUCT_SPECIFIC_VALIDATED_MISSINGNESS_POLICY"]},
        "missingness_registry_sha256": card["missingness_registry_sha256"],
        "max_absolute_margin_or_total_cdf_error": max_dev,
        "simultaneous_dkw_99pct_tolerance": bound,
        "qualification": "DIAGNOSTIC_ONLY",
        "action_authority": False,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for f in ("inputs", "run", "out"):
        p.add_argument("--" + f, type=Path, required=True)
    p.add_argument("--card-sha256", required=True)
    p.add_argument("--previous-card",type=Path)
    p.add_argument("--release-review",action="store_true",help="Require missingness release eligibility as well as numerical replay")
    a = p.parse_args()
    receipt = verify(a.inputs, a.run, a.card_sha256, a.previous_card)
    model.write(a.out, receipt)
    print(json.dumps(receipt))
    if a.release_review and receipt["model_release_review"]["status"] != "PASS":
        raise SystemExit(2)
