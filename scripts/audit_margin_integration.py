"""Compare pinned PR sources on identical inputs; software evidence only.

python scripts/audit_margin_integration.py --main-source DIR --pr69-source DIR --pr70-source DIR --output NEW.json
The source directories are read only. No source is fetched by this command.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models.common import discrete_research as D
from models.common.margin_contract import bind_margin, cover_quote


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def audit(pr69, pr70, main_source):
    manifest = json.loads((ROOT / "tests/fixtures/margin_integration/sources.json").read_text())
    roots = {"main": main_source, "69": pr69, "70": pr70}
    for entry in manifest["files"]:
        raw = (roots[entry["source"]] / entry["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("PINNED_SOURCE_BYTES_MISMATCH:" + entry["path"])
    old69 = load_module("review_margin_69", pr69 / "models/common/margin_system.py")
    # These are historical defect reproductions. Never let newly integrated
    # packages shadow the explicitly pinned old core or validation module.
    old70 = load_module("review_pr70_margins", pr70 / "models/common/margins/__init__.py")
    load_module("review_pr70_adapters", pr70 / "pipelines/margins/__init__.py")
    old_nfl = load_module("review_pr70_adapters.nfl", pr70 / "pipelines/margins/nfl.py")
    old_mls = load_module("review_pr70_adapters.mls", pr70 / "pipelines/margins/mls.py")
    old_validation = load_module("review_pr70_validation", pr70 / "pipelines/margins/validate.py")
    simulated_margin, quote70 = old70.simulated_margin, old70.cover_quote
    normal_margin, margin_quote_record = old70.normal_margin, old70.margin_quote_record
    discrete_football_margin = old70.discrete_football_margin
    NFL_KEY_NUMBER_MASS, mls_cover = old_nfl.NFL_KEY_NUMBER_MASS, old_mls.mls_cover
    cover_calibration = old_validation.cover_calibration

    paired = []
    values = np.array([-7, -3, 3, 7], dtype=np.int64)
    draws = np.repeat(values, [10000, 20000, 30000, 40000])
    source = hashlib.sha256(draws.astype("<i8").tobytes()).hexdigest()
    cutoff = "2026-10-19T16:00:00Z"
    for league, settlements in D.SETTLEMENTS.items():
        for settlement in settlements:
            event = "SYNTHETIC_" + league + "_" + settlement
            d69 = old69.from_margin_draws(draws, league=league, settlement=settlement,
                model_id="synthetic.same_source.v1", event_id=event, cutoff=cutoff,
                source_sha256=source, orientation="HOME_MINUS_AWAY")
            view = bind_margin(d69, event_id=event, cutoff=cutoff, source_sha256=source)
            d70 = simulated_margin(draws, d69["provenance"])
            for line in [-7.5, -7., -3.5, -3., 0., 3., 3.5, 7., 7.5]:
                ladder = old69.cover_ladder(d69, [line])[0]
                for side in ["home", "away"]:
                    integrated = cover_quote(view, line, orientation=side)
                    q70 = quote70(d70, line, orientation=side)
                    for key, value in integrated["probabilities"].items():
                        assert abs(value - ladder[side][key]) < 1e-12
                    a = [integrated["probabilities"][k] for k in ["win", "push", "loss"]]
                    b = [q70.p_cover, q70.p_push, q70.p_loss]
                    np.testing.assert_allclose(a, b, rtol=0, atol=1e-12)
                    paired.append({"league": league, "settlement": settlement,
                        "event_id": event, "source_sha256": source,
                        "home_spread": line, "side": side, "max_abs_delta": float(np.max(np.abs(np.array(a)-b)))})

    fixture = json.loads((ROOT / "tests/fixtures/margin_integration/nfl_retrospective.json").read_text())
    actual = fixture["distribution"]; prov = actual["provenance"]
    view = bind_margin(actual, event_id=prov["event_id"], cutoff=prov["cutoff"],
        source_field="parent_forecast_sha256", source_sha256=prov["parent_forecast_sha256"])
    real_rows = []
    for line in [-17., -14., -10., -7.5, -7., -3.5, -3., 0., 3., 7., 10., 14., 17.]:
        q69 = old69.cover_ladder(actual, [line])[0]
        for side in ["home", "away"]:
            qi = cover_quote(view, line, orientation=side)
            # The original #70 CDF API now consumes the same exact retained law.
            q70 = quote70(view, line, orientation=side)
            vals = [qi["probabilities"][k] for k in ["win", "push", "loss"]]
            np.testing.assert_allclose(vals, [q70.p_cover, q70.p_push, q70.p_loss], rtol=0, atol=1e-12)
            np.testing.assert_allclose(vals, [q69[side][k] for k in ["win", "push", "loss"]], rtol=0, atol=1e-12)
            real_rows.append({"line": line, "side": side, "probabilities": qi["probabilities"]})
    assert fixture["evaluation_status"] == "HOLD"

    key_probes = []
    for mu in [-14., -7., 0., 7., 14.]:
        d70 = discrete_football_margin(mu, 13.5, NFL_KEY_NUMBER_MASS, {"test": True})
        mean = float(d70.grid @ d70.probs)
        key_probes.append({"input_mu": mu, "sigma": 13.5, "actual_mean": mean,
                           "mean_shift": mean-mu, "status": "UNFITTED_PLACEHOLDER_NOT_ADOPTED"})
    assert abs(key_probes[1]["mean_shift"]) > .01

    mls = old69.from_joint_scores([0, 1, 2], [1, 1, 1], weights=[.2, .3, .5],
        league="mls", settlement="REGULATION_90_STOPPAGE", model_id="synthetic.mls.v1",
        event_id="MLS_FIXTURE", cutoff=cutoff, source_sha256=source)
    mls_view = bind_margin(mls, event_id="MLS_FIXTURE", cutoff=cutoff, source_sha256=source)
    split = cover_quote(mls_view, -.25)
    assert split["probabilities"]["half_loss"] == .3
    core70 = quote70(mls_view, -.25)
    assert abs(core70.p_loss - .5) < 1e-12  # Its binary API loses the half outcome.
    try:
        mls_cover({}, -.25)
        raise AssertionError("MLS adapter unexpectedly allowed pricing")
    except ValueError as exc:
        assert "UNSUPPORTED_1X2_ONLY" in str(exc)

    normal = normal_margin(0., 13.5, {"fixture": True})
    records = [margin_quote_record(normal, quote70(normal, 0., orientation=s),
        event={"event_id": "same-event"}, source_model={"model_id": "same", "artifact_sha256": source},
        sigma_provenance={}, generated_at_utc=cutoff) for s in ["home", "away"]]
    assert records[0] == records[1]  # Side is missing from the #70 identity.
    calibration = cover_calibration([{"p_cover": .4, "p_push": .2, "line": -3.,
        "actual_margin": m, "orientation": "home", "sport": "nfl", "season": 2025,
        "week": 1, "date": "2025-09-01"} for m in [7, 0, 3]])
    assert abs(calibration["brier"] - .26) < 1e-12
    return {"schema": "sports.margin_integration_audit.v1", "sources": manifest,
        "historical_defect_replay": True,
        "current_bridge_sha256": hashlib.sha256((ROOT / "models/common/margin_contract.py").read_bytes()).hexdigest(),
        "execution_status": "COMPLETED", "predictive_validation": "NOT_ASSESSED",
        "preserved_nfl_predictive_decision": "HOLD", "publication_eligibility": "INELIGIBLE",
        "action_authority": False, "prospective_grade_eligible": False,
        "synthetic_contract_comparisons": len(paired), "synthetic_comparisons": paired,
        "retained_nfl": {"event_id": prov["event_id"], "distribution_sha256": view.distribution_id,
            "source_parent_forecast_sha256": prov["parent_forecast_sha256"],
            "cutoff": prov["cutoff"], "mode": fixture["mode"],
            "comparison_count": len(real_rows), "rows": real_rows},
        "pr70_key_number_probes": key_probes,
        "pr70_reproduced_contract_gaps": {"missing_side_record_collision": True,
            "mls_adapter_refuses_spread": True, "generic_quarter_line_loses_half_outcome": True,
            "nonpush_brier_with_raw_unconditional_p": calibration["brier"],
            "correct_conditional_brier_for_fixture": .25},
        "limits": ["Same-input software comparison; not a new predictive study.",
            "Retained NFL source binding is not independent PIT attestation.",
            "No fit, automatic NFL child, default, frozen forecast or wagering change."]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--main-source", required=True, type=Path,
                   help="Historical main checkout pinned by sources.json; not the current working tree")
    p.add_argument("--pr69-source", required=True, type=Path)
    p.add_argument("--pr70-source", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    result = audit(args.pr69_source.resolve(), args.pr70_source.resolve(), args.main_source.resolve())
    with args.output.open("x") as handle:
        json.dump(result, handle, indent=2, allow_nan=False); handle.write("\n")
    print(json.dumps({k: result[k] for k in ["execution_status", "synthetic_contract_comparisons",
        "predictive_validation", "preserved_nfl_predictive_decision", "action_authority"]}))


if __name__ == "__main__":
    main()
