#!/usr/bin/env python3
"""Always-output diagnostic card orchestrator wired through sport adapters."""
from __future__ import annotations

import argparse
import csv
import importlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TIERS = {"PRIMARY_SHADOW", "REDUCED", "BASELINE", "EMERGENCY"}


def finite_prob(x):
    try:
        value = float(x)
    except Exception:
        return False
    return math.isfinite(value) and 0 <= value <= 1


def dt(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
    return parsed


def iso_utc(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def now_utc():
    return datetime.now(timezone.utc)


def load_adapter(league):
    from pipelines.cards.selection import select,SelectionError
    if league.lower() in {'nba','nhl','mls'} and os.environ.get('SPORTS_INITIAL_BASELINES')!='1':select(league)
    try:return importlib.import_module(f"pipelines.cards.adapters.{league.lower()}")
    except ModuleNotFoundError as exc:
        if exc.name==f"pipelines.cards.adapters.{league.lower()}":raise SelectionError('SELECTED_MODEL_CURRENT_CARD_ADAPTER_UNAVAILABLE:'+league) from exc
        raise


def divergence_category(abs_gap_pp):
    if abs_gap_pp >= 12.0:
        return "CRITICAL"
    if abs_gap_pp >= 8.0:
        return "SEVERE"
    if abs_gap_pp >= 4.0:
        return "MODERATE"
    return "NONE"


def normalize(event, raw):
    tier = raw.get("forecast_tier", "BASELINE")
    if tier not in TIERS:
        raise RuntimeError(f"INVALID_FORECAST_TIER:{tier}")
    if not finite_prob(raw.get("model_p")):
        raise RuntimeError("INVALID_MODEL_P")
    if not finite_prob(raw.get("sim_p")):
        raise RuntimeError("INVALID_SIM_P")
    dose = float(raw.get("dose", 0.5))
    if not math.isfinite(dose) or not 0 <= dose <= 1:
        raise RuntimeError("INVALID_DOSE")

    mc_only=raw.get("probability_estimator")=="MONTE_CARLO_ONLY"
    analytic_p = None if mc_only else float(raw.get("analytic_p", raw["model_p"]))
    stochastic_sim_p = float(raw.get("stochastic_sim_p", raw["sim_p"]))
    if (not mc_only and not finite_prob(analytic_p)) or not finite_prob(stochastic_sim_p):
        raise RuntimeError("INVALID_ESTIMATOR_PROBABILITY")
    signed_gap_pp = None if mc_only else 100.0 * (analytic_p - stochastic_sim_p)
    abs_gap_pp = None if mc_only else abs(signed_gap_pp)

    result = {
        "event_id": str(event["event_id"]),
        "model_id": raw.get("model_id"),
        "coverage_label": raw.get("coverage_label"),
        "away_team": event["away_team"],
        "home_team": event["home_team"],
        "start_time_utc": event["start_time_utc"],
        "forecast_status": "FORECAST_GENERATED",
        "forecast_tier": tier,
        "data_quality": raw.get("data_quality", "PARTIAL"),
        "dose": dose,
        "model_winner": raw.get("model_winner"),
        "model_p": float(raw["model_p"]),
        "probability_estimator":raw.get("probability_estimator","ANALYTIC_AND_SIMULATION"),
        "selection_hash":raw.get("selection_hash"),
        "sim_p": stochastic_sim_p,
        "analytic_p": analytic_p,
        "stochastic_sim_p": stochastic_sim_p,
        "analytic_sim_gap_pp": signed_gap_pp,
        "analytic_sim_abs_gap_pp": abs_gap_pp,
        "analytic_sim_divergence": "NOT_APPLICABLE_MC_ONLY" if mc_only else ("DIFFERENT_MODELS_NOT_CONVERGENCE" if raw.get("diagnostics", {}).get("comparison") == "DIFFERENT_MODELS_NOT_ANALYTIC_MC_CONVERGENCE" else divergence_category(abs_gap_pp)),
        "model_p_candidate_normal_margin": raw.get("model_p_candidate_normal_margin"),
        "model_p_candidate_status": raw.get("model_p_candidate_status"),
        "projected_margin": raw.get("projected_margin"),
        "projected_total": raw.get("projected_total", "UNSUPPORTED_BY_TIER"),
        "projected_home_points": raw.get("projected_home_points"),
        "projected_away_points": raw.get("projected_away_points"),
        "projected_home_runs": raw.get("projected_home_runs"),
        "projected_away_runs": raw.get("projected_away_runs"),
        "margin_std": raw.get("margin_std"),
        "total_std": raw.get("total_std"),
        "spread_or_runline": raw.get("spread_or_runline", "UNSUPPORTED_BY_TIER"),
        "total_market": raw.get("total_market", "UNSUPPORTED_BY_TIER"),
        "warnings": list(raw.get("warnings", [])),
        "input_snapshot_hash": raw.get("input_snapshot_hash"),
        "model_state_config_hash": raw.get("model_state_config_hash"),
        "model_input_snapshot": raw.get("model_input_snapshot"),
        "diagnostics": raw.get("diagnostics", {}),
        "simulation": raw.get("simulation", {}),
        "provenance": raw.get("provenance", {}),
        "roster_coverage": raw.get("roster_coverage"),
        "action_authority": False,
        "action_status": "SHADOW_ONLY",
    }
    for key in ("identity_semantics", "numerical_identity", "forecast_procedure_id",
                "feature_procedure_id", "calibration_procedure_id"):
        if key in raw:
            result[key] = raw[key]
    return result


def summarize_pit(context, requested_as_of_utc, generated_at_utc):
    raw = dict(context.get("pit_provenance") or {})
    fetches = list(raw.get("source_fetches") or [])
    # Byte retention is separate from PIT ordering, model usage and calibration.
    attestation = {"status": "SOURCE_RETENTION_UNVERIFIED",
                   "historical_pit_validity_proven": False,
                   "provider_authenticity_proven": False,
                   "model_input_usage_proven": False,
                   "certified_calibration_eligible": False}
    if os.environ.get("SPORTS_SOURCE_BUNDLES"):
        from scripts.source_attestation import attest_sources
        try:
            roots = json.loads(os.environ["SPORTS_SOURCE_BUNDLES"])
            if not isinstance(roots, list) or not roots or any(not isinstance(p, str) for p in roots):
                raise ValueError("SOURCE_BUNDLES_MUST_BE_PATH_LIST")
            attestation = attest_sources(fetches, roots, requested_as_of_utc)
        except (ValueError, KeyError, OSError, TypeError) as exc:
            attestation["reason"] = str(exc)
    timestamps = []
    invalid_timestamp = False
    for item in fetches:
        try:
            timestamps.append(dt(item["fetched_at_utc"]))
        except Exception:
            invalid_timestamp = True

    requested = dt(requested_as_of_utc)
    generated = dt(generated_at_utc)
    base = {
        "requested_as_of_utc": requested_as_of_utc,
        "generated_at_utc": generated_at_utc,
        "pit_mode": raw.get("pit_mode", "UNKNOWN"),
        "pit_reconstruction_supported": bool(raw.get("pit_reconstruction_supported", False)),
        "adapter_source": raw.get("adapter_source"),
        "data_vintage_basis": raw.get("data_vintage_basis", "UNKNOWN"),
        "pit_alignment_threshold_seconds": 0,
        "pit_threshold_seconds": 3600,
        "source_fetches": fetches,
        "source_attestation": attestation,
        "action_authority": False,
    }

    if not timestamps:
        base.update({
            "actual_data_vintage_utc": None,
            "min_source_timestamp_utc": None,
            "max_source_timestamp_utc": None,
            "pit_delta_seconds": None,
            "pit_status": "PIT_UNKNOWN",
            "pit_reason": "SOURCE_FETCH_TIMESTAMP_UNAVAILABLE",
            "pit_gate": "FAIL",
        })
        return base

    minimum = min(timestamps)
    maximum = max(timestamps)
    delta_seconds = int(round((maximum - requested).total_seconds()))
    if invalid_timestamp:
        status, reason, gate = "PIT_UNKNOWN", "SOURCE_TIMESTAMP_INVALID", "FAIL"
    elif requested > generated or maximum > generated:
        status, reason, gate = "PIT_REPLAY_INVALID", "FUTURE_TIMESTAMP", "FAIL"
    elif maximum > requested:
        status, reason, gate = "PIT_REPLAY_INVALID", "SOURCE_FETCH_AFTER_CUTOFF", "FAIL"
    else:
        status, reason, gate = "PIT_ORDERED", "FETCH_ORDER_ONLY_SOURCE_PROVENANCE_UNVERIFIED", "WARN"

    base.update({
        "actual_data_vintage_utc": iso_utc(maximum),
        "min_source_timestamp_utc": iso_utc(minimum),
        "max_source_timestamp_utc": iso_utc(maximum),
        "pit_delta_seconds": delta_seconds,
        "pit_status": status,
        "pit_reason": reason,
        "pit_gate": gate,
    })
    return base


def _home_probability(row, key):
    value = row.get(key)
    if not finite_prob(value):
        return None
    value = float(value)
    if row.get("model_winner") == row.get("home_team"):
        return value
    if row.get("model_winner") == row.get("away_team"):
        return 1.0 - value
    return None


def _calibration_bin(probability):
    if probability is None:
        return None
    low = min(0.9, math.floor(float(probability) * 10.0) / 10.0)
    return f"{low:.1f}-{min(1.0, low + 0.1):.1f}"


def attach_grading(card):
    pit = card.get("pit_provenance") or {}
    pit_status = pit.get("pit_status")
    source_cutoff = pit.get("max_source_timestamp_utc")
    generated_at = card.get("generated_at_utc")
    eligible_count = 0

    for row in card.get("forecasts", []):
        if row.get("forecast_status") != "FORECAST_GENERATED":
            continue
        analytic_home = _home_probability(row, "analytic_p")
        sim_home = _home_probability(row, "stochastic_sim_p")
        candidate_home = _home_probability(row, "model_p_candidate_normal_margin")
        start = dt(row["start_time_utc"])
        temporal_pregame = dt(generated_at) < start
        source_pregame = source_cutoff is None or dt(source_cutoff) < start
        eligible = (
            False  # Diagnostic cards have no writer-owned immutable registration receipt.
            and
            card.get("league") == "MLB"
            and pit_status == "PIT_ALIGNED"
            and temporal_pregame
            and source_pregame
            and analytic_home is not None
            and sim_home is not None
        )
        reason = "REGISTRATION_ATTESTATION_REQUIRED"
        if pit_status != "PIT_ALIGNED":
            reason = f"PIT_STATUS_{pit_status or 'UNKNOWN'}"
        elif not temporal_pregame or not source_pregame:
            reason = "POST_START_OR_SOURCE_FETCH_AFTER_START"
        elif analytic_home is None or sim_home is None:
            reason = "HOME_PROBABILITY_UNAVAILABLE"
        elif card.get("league") != "MLB":
            reason = "MLB_CALIBRATION_ONLY"
        if eligible:
            eligible_count += 1

        row["grading"] = {
            "schema_version": "forecast_grading_v1",
            "awaiting_outcome": bool(eligible),
            "eligible_for_prospective_grading": bool(eligible),
            "eligibility_reason": reason,
            "analytic_p_home": analytic_home,
            "stochastic_sim_p_home": sim_home,
            "normal_margin_candidate_p_home": candidate_home,
            "actual_result": None,
            "home_won": None,
            "brier_analytic": None,
            "brier_sim": None,
            "brier_normal_margin_candidate": None,
            "log_loss_analytic": None,
            "log_loss_sim": None,
            "calibration_bin_analytic": _calibration_bin(analytic_home),
            "calibration_bin_sim": _calibration_bin(sim_home),
            "graded_at_utc": None,
            # An absent producer declaration is unknown, not evidence of no use.
            "market_features_used": row.get("diagnostics", {}).get("market_input"),
            "market_independence_status": "NOT_CERTIFIED_BY_REPORTING_FLAGS",
            "action_authority": False,
        }

    card["grading_policy"] = {
        "schema_version": "mlb_probability_calibration_v1",
        "eligible_forecast_count": eligible_count,
        "registration_rule": "DIAGNOSTIC_ONLY; separate verified writer registration required",
        "market_overlay_enabled": False,
        "market_overlay_scope": "NO_COMPARISON_LAYER_ATTACHED_BY_SHARED_RUNNER",
        "market_independence_status": "SEE_DISCLOSURE_AND_RUNTIME_PERTURBATION_AUDIT",
        "action_authority": False,
    }
    return card


def attach_state_receipt(raw, event, context, league):
    """Add an input trace after forecasting without editing pinned model code."""
    import copy
    result = copy.deepcopy(raw)
    package = context.get("package")
    if league.lower() not in {"nba", "nhl", "mls"} or not isinstance(package, dict):
        return result
    from models.current.baseline import IDS
    if result.get("model_id") != IDS.get(league.lower()):
        return result
    from models.current.freshness import state_freshness_receipt
    diagnostic = result.setdefault("diagnostics", {})
    try:
        if package.get("model_id") != result["model_id"]:
            raise ValueError("RECEIPT_MODEL_IDENTITY_MISMATCH")
        receipt = state_freshness_receipt(package, event, result["model_input_snapshot"],
                                          cutoff_utc=context["cutoff"])
        if (receipt["input_snapshot_hash"] != result.get("input_snapshot_hash") or
                receipt["model_state_config_hash"] != result.get("model_state_config_hash")):
            raise ValueError("RECEIPT_PARENT_HASH_MISMATCH")
        diagnostic["state_freshness_receipt"] = receipt
    except (ValueError, KeyError, TypeError) as exc:
        # Retain raw evidence. A failed diagnostic is visible, never silently fresh.
        diagnostic["state_freshness_receipt_error"] = str(exc)
    return result


def generate(card_date, league, as_of, simulations, overrides, roster_bundle=None, require_roster_aware=False, *, identity_semantics="legacy.v1"):
    from sports.rosters import attach, assess, load_bundle
    roster = load_bundle(roster_bundle) if roster_bundle else None
    adapter = load_adapter(league)
    schedule = adapter.load_schedule(card_date, as_of)
    context = adapter.build_context(schedule, as_of, True, overrides)
    if league.lower() == "nfl":
        context["retain_draws"] = True
    rows = []
    incidents = []
    requested_cutoff = dt(as_of)

    for event in schedule:
        if not event.get("event_id") or not event.get("home_team") or not event.get("away_team"):
            incidents.append({"event": event, "incident": "CANONICAL_IDENTITY_UNRESOLVED"})
            continue
        event_start = dt(event["start_time_utc"])
        # A requested cutoff alone is insufficient for prospectivity. Do not fetch
        # event-level inputs if the game has already started in wall-clock time.
        if event_start <= requested_cutoff or event_start <= now_utc():
            rows.append({
                "event_id": str(event["event_id"]),
                "away_team": event["away_team"],
                "home_team": event["home_team"],
                "start_time_utc": event["start_time_utc"],
                "forecast_status": "POST_START",
                "action_authority": False,
                "action_status": "SHADOW_ONLY",
            })
            continue
        try:
            if require_roster_aware:
                coverage = assess(league.lower(), event, as_of, roster)
                if not coverage['roster_aware_forecast_eligible']:
                    raise ValueError('ROSTER_AWARE_FORECAST_UNAVAILABLE:' + ';'.join(coverage['reasons']))
            if identity_semantics == "legacy.v1":
                raw = adapter.forecast_event(event, context, simulations)
            else:
                from pipelines.cards.semantic_identity import forecast_with_identity
                raw = forecast_with_identity(adapter, event, context, simulations, semantics=identity_semantics)
            from pipelines.cards.selected import apply_default
            raw = apply_default(league,event,raw)
            raw = attach_state_receipt(raw, event, context, league)
            raw = attach(raw, league.lower(), event, as_of, roster)
            # Guard the rare case where network/simulation time crosses first pitch.
            if now_utc() >= event_start:
                rows.append({
                    "event_id": str(event["event_id"]),
                    "away_team": event["away_team"],
                    "home_team": event["home_team"],
                    "start_time_utc": event["start_time_utc"],
                    "forecast_status": "POST_START",
                    "action_authority": False,
                    "action_status": "SHADOW_ONLY",
                    "warnings": ["START_CROSSED_DURING_FORECAST_GENERATION"],
                })
            else:
                rows.append(normalize(event, raw))
        except Exception as exc:
            incidents.append({
                "event_id": str(event["event_id"]),
                "incident": "FORECAST_COVERAGE_BREACH",
                "detail": f"{type(exc).__name__}:{exc}",
            })

    generated_at = now_utc().isoformat().replace("+00:00", "Z")
    pit = summarize_pit(context, as_of, generated_at)
    actual_cutoff = max(requested_cutoff, dt(generated_at))
    pregame = [event for event in schedule if dt(event["start_time_utc"]) > actual_cutoff]
    generated = {row["event_id"] for row in rows if row.get("forecast_status") == "FORECAST_GENERATED"}
    missing = [str(event["event_id"]) for event in pregame if str(event["event_id"]) not in generated]

    card = {
        "artifact_type": "diagnostic_force_card_v1",
        "card_date": card_date,
        "league": league.upper(),
        "as_of_utc": as_of,
        "requested_as_of_utc": as_of,
        "generated_at_utc": generated_at,
        "pit_provenance": pit,
        "simulation_count": simulations,
        "authority": "SHADOW_ONLY",
        "actionable": False,
        "scheduled_game_count": len(schedule),
        "forecast_count": len(generated),
        "pregame_coverage": 1.0 if not pregame else len(generated) / len(pregame),
        "coverage_breach_event_ids": missing,
        "incidents": incidents,
        "roster_policy": {"bundle_sha256": roster.get('bundle_sha256') if roster else None,
                          "require_roster_aware": require_roster_aware,
                          "membership_is_not_availability": True,
                          "current_roster_is_not_numerical_consumption": True},
        "forecasts": rows,
    }
    return attach_grading(card)


def _delta_text(seconds):
    if seconds is None:
        return "unknown"
    sign = "+" if seconds >= 0 else "-"
    value = abs(int(seconds))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{sign}{hours}h {minutes:02d}m {secs:02d}s"


def render_md(card, disclosures=None):
    pit = card.get("pit_provenance") or {}
    grading = card.get("grading_policy") or {}
    lines = [
        f"# {card['league']} Diagnostic Card — {card['card_date']}",
        "",
        f"Pregame coverage: **{card['pregame_coverage']:.1%}** · Action authority: **OFF**",
        f"Prospective grading eligible: **{grading.get('eligible_forecast_count', 0)}**",
        "",
        "## Point-in-time provenance",
        "",
        f"- PIT status: **{pit.get('pit_status', 'PIT_UNKNOWN')}**",
        f"- Requested cutoff: `{card.get('requested_as_of_utc', card.get('as_of_utc'))}`",
        f"- Actual live-fetch vintage proxy: `{pit.get('actual_data_vintage_utc')}`",
        f"- Fetch-to-request delta: **{_delta_text(pit.get('pit_delta_seconds'))}**",
        f"- Replay supported: **{str(bool(pit.get('pit_reconstruction_supported'))).lower()}**",
        f"- Vintage basis: `{pit.get('data_vintage_basis', 'UNKNOWN')}`",
        "",
    ]
    if pit.get("pit_status") not in (None, "PIT_ALIGNED"):
        lines.extend(["> **PIT WARNING:** this diagnostic card must not be represented as an exact requested-cutoff replay.", ""])

    from pipelines.cards.integrity_reporting import render_integrity_md
    lines.extend([render_integrity_md(card), ""])
    seen_defaults=set()
    for row in card["forecasts"]:
        default=(row.get("diagnostics") or {}).get("default_selection")
        if default and default['profile'] not in seen_defaults:
            seen_defaults.add(default['profile'])
            lines.extend([f"**Selected default:** {default['default_model_id']} · {default['selection_status']}",default['reason'],""])
    for row in card["forecasts"]:
        diagnostic=row.get("diagnostics") or {}
        selection=diagnostic.get("selection_policy")
        if selection:
            lines.extend([f"**NFL selection:** {selection['presentation_role']} · screen {selection['screen_status']} · headline eligible: {selection['headline_eligible']}", ""])
            coherence=diagnostic.get("coherence", {})
            lines.extend(["Independent-head directions (home-oriented): `"+json.dumps(coherence.get("home_oriented_signs",{}))+"`. Joint score expectations appear only when available; Ridge centers are diagnostic.", ""])
            flow=diagnostic.get("assimilation")
            lines.extend(["Week-state assimilation: **"+(flow.get("status","UNVERIFIED") if flow else "NOT_DEMONSTRATED_FOR_THIS_RUN")+"**", ""])

    lines.extend([
        "| Game | Tier | Dose | Winner | Analytic P | Stochastic Sim P | Gap | Divergence | Margin | Total | Grade | Warnings |",
        "|---|---|---:|---|---:|---:|---:|---|---:|---:|---|---|",
    ])
    for row in card["forecasts"]:
        game = f"{row.get('away_team')} @ {row.get('home_team')}"
        if row.get("forecast_status") != "FORECAST_GENERATED":
            lines.append(f"| {game} | POST_START | — | — | — | — | — | — | — | — | INELIGIBLE | post-start; no new pregame forecast |")
            continue
        pct = lambda x: "—" if x is None else f"{100 * x:.1f}%"
        gap = "—" if row["analytic_sim_gap_pp"] is None else f"{row['analytic_sim_gap_pp']:+.2f} pp"
        grade = "AWAITING" if (row.get("grading") or {}).get("awaiting_outcome") else "INELIGIBLE"
        lines.append(
            f"| {game} | {row['forecast_tier']} | {row['dose']:.2f} | {row.get('model_winner', '—')} | "
            f"{pct(row['analytic_p'])} | {pct(row['stochastic_sim_p'])} | "
            f"{gap} | {row['analytic_sim_divergence']} | "
            f"{row.get('projected_margin', '—')} | {row.get('projected_total', '—')} | {grade} | "
            f"{', '.join(row.get('warnings', [])) or 'None'} |"
        )
    if card["incidents"]:
        lines += ["", "## Coverage incidents", "", "```json", json.dumps(card["incidents"], indent=2), "```"]
    from pipelines.cards.disclosures import build_report, render_md as render_disclosures
    if disclosures is not None:
        lines += ["", render_disclosures(disclosures)]
    elif card.get("as_of_utc"):
        lines += ["", render_disclosures(build_report(card))]
    else:
        # Legacy display-only fragments are not evidence-bearing full cards.
        # Preserve their renderer without inventing a missing cutoff.
        lines += ["", "**Disclosures unavailable: parent cutoff missing. Wagering remains OFF.**"]
    lines += ["", "**Diagnostic only. Action authority is OFF. No market/EV layer is attached.**"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--league", required=True, choices=["mlb", "cfb", "nfl", "wnba", "nba", "nhl", "mls"])
    parser.add_argument("--as-of-utc")
    parser.add_argument("--initial-research-baselines",action="store_true",help="Explicit NBA/NHL/MLS research models; does not change tested defaults")
    parser.add_argument("--simulations", type=int, default=100000)
    parser.add_argument("--manual-overrides")
    parser.add_argument("--roster-bundle", type=Path, help="Retained all-sports roster bundle.json; adds validated personnel coverage")
    parser.add_argument("--require-roster-aware", action="store_true", help="Fail closed unless full roster impacts are fitted and consumed; current parents do not meet this gate")
    parser.add_argument("--distribution-research-config", help="Opt-in hash-bound cross-sport distribution challengers; emits a separate report")
    parser.add_argument("--efficiency-research-config", type=Path, help="Opt-in fitted CFB/NBA efficiency experiments; separate source-bound local SHADOW receipts, no default change")
    parser.add_argument("--disclosures", type=Path, help="Source-bound availability scenarios, assumptions and dependence disclosures; presentation only")
    parser.add_argument("--identity-semantics", choices=["legacy.v1", "market_blind_numeric.v2"], default="market_blind_numeric.v2", help="Explicit independently identified execution child; legacy behavior remains available")
    parser.add_argument("--selection-config", type=Path, help="Frozen research selector configuration; absent config emits unqualified diagnostic NO_PICK")
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args()
    if args.initial_research_baselines:os.environ['SPORTS_INITIAL_BASELINES']='1'
    as_of = args.as_of_utc or now_utc().isoformat().replace("+00:00", "Z")

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=False)
    os.environ['SPORTS_RESEARCH_DRAW_OUTPUT']=str((output/'draws').resolve())
    if args.league == "mlb":
        os.environ["MLB_DRAW_OUTPUT"] = str((output / "draws").resolve())
    card = generate(args.date, args.league, as_of, args.simulations, args.manual_overrides, args.roster_bundle, args.require_roster_aware, identity_semantics=args.identity_semantics)
    (output / "diagnostic_card.json").write_text(json.dumps(card, indent=2, sort_keys=True) + "\n")
    from pipelines.cards.selection_integration import write_card_selection
    selection_config = json.loads(args.selection_config.read_text()) if args.selection_config else None
    selection = write_card_selection(output / "diagnostic_card.json", output / "research_selection", config=selection_config)
    from pipelines.cards.disclosures import write_report
    disclosures = write_report(card, output / "disclosures", args.disclosures)
    (output / "diagnostic_card.md").write_text(render_md(card, disclosures))
    fields = [
        "event_id", "away_team", "home_team", "forecast_status", "forecast_tier", "data_quality",
        "dose", "model_winner", "analytic_p", "stochastic_sim_p", "analytic_sim_gap_pp",
        "analytic_sim_abs_gap_pp", "analytic_sim_divergence", "model_p_candidate_normal_margin",
        "projected_margin", "projected_total", "projected_home_runs", "projected_away_runs",
        "margin_std", "total_std", "spread_or_runline", "total_market", "warnings",
        "analytic_p_home", "stochastic_sim_p_home", "grading_eligible",
    ]
    with (output / "diagnostic_card.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in card["forecasts"]:
            csv_row = dict(row)
            grading = row.get("grading") or {}
            csv_row["warnings"] = ";".join(csv_row.get("warnings", []))
            csv_row["analytic_p_home"] = grading.get("analytic_p_home")
            csv_row["stochastic_sim_p_home"] = grading.get("stochastic_sim_p_home")
            csv_row["grading_eligible"] = grading.get("eligible_for_prospective_grading")
            writer.writerow(csv_row)

    print(render_md(card, disclosures))
    print(json.dumps({"research_selection": selection["decision_counts"], "wagering_status": "OFF"}))
    research_incomplete = bool(disclosures["errors"])
    if args.efficiency_research_config:
        from research.efficiency.runner import shadow_from_card
        try:
            efficiency = shadow_from_card(output / "diagnostic_card.json", args.efficiency_research_config,
                                          output / "efficiency_research", simulations=args.simulations)
            research_incomplete |= any(row["status"] != "SHADOW_LOGGED" for row in efficiency["coverage"])
            print(json.dumps({"efficiency_research_run_id": efficiency["run_id"], "logged_count": efficiency["logged_count"], "canonical_prospective_eligible": False}))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            research_incomplete = True
            failure = {"status": "FAILED", "reason": str(exc), "action_authority": False}
            with (output / "efficiency_research_failure.json").open("x") as handle:
                json.dump(failure, handle, indent=2)
            print(json.dumps({"efficiency_research": failure}))
    if args.distribution_research_config:
        from pipelines.cards.distribution_research import build, load_config
        try:
            research = build(card, load_config(args.distribution_research_config), output / "distribution_research", simulations=args.simulations)
            research_incomplete |= any(r["status"] != "COMPLETED" for r in research["coverage"])
            print(json.dumps({"distribution_research": research["coverage"]}, indent=2))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            research_incomplete = True
            failure = {"status": "FAILED", "reason": str(exc), "action_authority": False}
            with (output / "distribution_research_failure.json").open("x") as handle:
                json.dump(failure, handle, indent=2)
            print(json.dumps({"distribution_research": failure}))
    raise SystemExit(2 if card["coverage_breach_event_ids"] or research_incomplete else 0)


if __name__ == "__main__":
    main()
