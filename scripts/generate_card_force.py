#!/usr/bin/env python3
"""Always-output diagnostic card orchestrator wired through sport adapters."""
from __future__ import annotations

import argparse
import csv
import importlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

# When invoked as `python scripts/generate_card_force.py`, Python places the
# scripts directory on sys.path rather than the repository root. Add the root
# explicitly so `pipelines.*` and `models.*` imports are stable in CI/local runs.
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
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def iso_utc(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_adapter(league):
    return importlib.import_module(f"pipelines.cards.adapters.{league.lower()}")


def divergence_category(abs_gap_pp):
    """Registered Model-vs-Sim divergence policy for the sports-model project."""
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
    if not math.isfinite(dose) or not 0.2 <= dose <= 1:
        raise RuntimeError("INVALID_DOSE")

    analytic_p = float(raw.get("analytic_p", raw["model_p"]))
    stochastic_sim_p = float(raw.get("stochastic_sim_p", raw["sim_p"]))
    signed_gap_pp = 100.0 * (analytic_p - stochastic_sim_p)
    abs_gap_pp = abs(signed_gap_pp)

    return {
        "event_id": str(event["event_id"]),
        "away_team": event["away_team"],
        "home_team": event["home_team"],
        "start_time_utc": event["start_time_utc"],
        "forecast_status": "FORECAST_GENERATED",
        "forecast_tier": tier,
        "data_quality": raw.get("data_quality", "PARTIAL"),
        "dose": dose,
        "model_winner": raw.get("model_winner"),
        # Backward-compatible aliases remain until downstream consumers migrate.
        "model_p": analytic_p,
        "sim_p": stochastic_sim_p,
        "analytic_p": analytic_p,
        "stochastic_sim_p": stochastic_sim_p,
        "analytic_sim_gap_pp": signed_gap_pp,
        "analytic_sim_abs_gap_pp": abs_gap_pp,
        "analytic_sim_divergence": divergence_category(abs_gap_pp),
        "model_p_candidate_normal_margin": raw.get("model_p_candidate_normal_margin"),
        "model_p_candidate_status": raw.get("model_p_candidate_status"),
        "projected_margin": raw.get("projected_margin"),
        "projected_total": raw.get("projected_total", "UNSUPPORTED_BY_TIER"),
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
        "action_authority": False,
        "action_status": "SHADOW_ONLY",
    }


def summarize_pit(context, requested_as_of_utc, generated_at_utc):
    """Build a truthful PIT label from adapter-captured live fetch timestamps.

    This does not pretend that fetch time is the source's effective-data time.
    The adapter declares the basis explicitly. Diagnostic cards are allowed to
    print with PIT warnings; action authority remains off.
    """
    raw = dict(context.get("pit_provenance") or {})
    fetches = list(raw.get("source_fetches") or [])
    timestamps = []
    for item in fetches:
        try:
            timestamps.append(dt(item["fetched_at_utc"]))
        except Exception:
            continue

    requested = dt(requested_as_of_utc)
    generated = dt(generated_at_utc)
    base = {
        "requested_as_of_utc": requested_as_of_utc,
        "generated_at_utc": generated_at_utc,
        "pit_mode": raw.get("pit_mode", "UNKNOWN"),
        "pit_reconstruction_supported": bool(raw.get("pit_reconstruction_supported", False)),
        "adapter_source": raw.get("adapter_source"),
        "data_vintage_basis": raw.get("data_vintage_basis", "UNKNOWN"),
        "pit_alignment_threshold_seconds": 900,
        "pit_threshold_seconds": 3600,
        "source_fetches": fetches,
        "action_authority": False,
    }

    if not timestamps:
        base.update(
            {
                "actual_data_vintage_utc": None,
                "min_source_timestamp_utc": None,
                "max_source_timestamp_utc": None,
                "pit_delta_seconds": None,
                "pit_status": "PIT_UNKNOWN",
                "pit_reason": "SOURCE_FETCH_TIMESTAMP_UNAVAILABLE",
                "pit_gate": "WARN",
            }
        )
        return base

    minimum = min(timestamps)
    maximum = max(timestamps)
    delta_seconds = int(round((maximum - requested).total_seconds()))
    absolute_delta = abs(delta_seconds)

    if absolute_delta <= 900:
        status = "PIT_ALIGNED"
        reason = "LIVE_FETCH_WITHIN_15_MINUTES_OF_REQUESTED_CUTOFF"
        gate = "PASS"
    elif absolute_delta <= 3600:
        status = "PIT_WARN"
        reason = "LIVE_FETCH_15_TO_60_MINUTES_FROM_REQUESTED_CUTOFF"
        gate = "WARN"
    elif delta_seconds > 3600 and not base["pit_reconstruction_supported"]:
        # A live-only source fetched materially after the requested historical
        # cutoff cannot support a retrospective PIT claim.
        status = "PIT_REPLAY_INVALID"
        reason = "LIVE_ONLY_SOURCE_FETCHED_AFTER_REQUESTED_CUTOFF"
        gate = "WARN"
    else:
        status = "PIT_STALE"
        reason = (
            "REQUESTED_CUTOFF_NOT_YET_REACHED_AT_LIVE_FETCH"
            if requested > generated
            else "LIVE_FETCH_MORE_THAN_60_MINUTES_BEFORE_REQUESTED_CUTOFF"
        )
        gate = "WARN"

    base.update(
        {
            # Fetch time is only a proxy for data vintage; the basis field above
            # prevents it from being mislabeled as a source-effective timestamp.
            "actual_data_vintage_utc": iso_utc(maximum),
            "min_source_timestamp_utc": iso_utc(minimum),
            "max_source_timestamp_utc": iso_utc(maximum),
            "pit_delta_seconds": delta_seconds,
            "pit_status": status,
            "pit_reason": reason,
            "pit_gate": gate,
        }
    )
    return base


def generate(card_date, league, as_of, simulations, overrides):
    adapter = load_adapter(league)
    schedule = adapter.load_schedule(card_date, as_of)
    context = adapter.build_context(schedule, as_of, True, overrides)
    rows = []
    incidents = []
    cutoff = dt(as_of)

    for event in schedule:
        if not event.get("event_id") or not event.get("home_team") or not event.get("away_team"):
            incidents.append({"event": event, "incident": "CANONICAL_IDENTITY_UNRESOLVED"})
            continue
        if dt(event["start_time_utc"]) <= cutoff:
            rows.append(
                {
                    "event_id": str(event["event_id"]),
                    "away_team": event["away_team"],
                    "home_team": event["home_team"],
                    "start_time_utc": event["start_time_utc"],
                    "forecast_status": "POST_START",
                    "action_authority": False,
                    "action_status": "SHADOW_ONLY",
                }
            )
            continue
        try:
            rows.append(normalize(event, adapter.forecast_event(event, context, simulations)))
        except Exception as exc:
            incidents.append(
                {
                    "event_id": str(event["event_id"]),
                    "incident": "FORECAST_COVERAGE_BREACH",
                    "detail": f"{type(exc).__name__}:{exc}",
                }
            )

    pregame = [event for event in schedule if dt(event["start_time_utc"]) > cutoff]
    generated = {
        row["event_id"]
        for row in rows
        if row.get("forecast_status") == "FORECAST_GENERATED"
    }
    missing = [str(event["event_id"]) for event in pregame if str(event["event_id"]) not in generated]
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    pit = summarize_pit(context, as_of, generated_at)

    return {
        "artifact_type": "diagnostic_force_card_v1",
        "card_date": card_date,
        "league": league.upper(),
        # Backward-compatible field. It means requested cutoff, not actual data vintage.
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
        "forecasts": rows,
    }


def _delta_text(seconds):
    if seconds is None:
        return "unknown"
    sign = "+" if seconds >= 0 else "-"
    value = abs(int(seconds))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{sign}{hours}h {minutes:02d}m {secs:02d}s"


def render_md(card):
    pit = card.get("pit_provenance") or {}
    lines = [
        f"# {card['league']} Diagnostic Card — {card['card_date']}",
        "",
        f"Pregame coverage: **{card['pregame_coverage']:.1%}** · Action authority: **OFF**",
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
        lines.extend(
            [
                "> **PIT WARNING:** this diagnostic card must not be represented as an exact requested-cutoff replay.",
                "",
            ]
        )

    lines.extend(
        [
            "| Game | Tier | Dose | Winner | Analytic P | Stochastic Sim P | Gap | Divergence | Margin | Total | RL/ATS | Total Market | Warnings |",
            "|---|---|---:|---|---:|---:|---:|---|---:|---:|---|---|---|",
        ]
    )
    for row in card["forecasts"]:
        game = f"{row.get('away_team')} @ {row.get('home_team')}"
        if row.get("forecast_status") != "FORECAST_GENERATED":
            lines.append(
                f"| {game} | POST_START | — | — | — | — | — | — | — | — | — | — | post-start; no new pregame forecast |"
            )
            continue
        pct = lambda x: f"{100 * x:.1f}%"
        lines.append(
            f"| {game} | {row['forecast_tier']} | {row['dose']:.2f} | {row.get('model_winner', '—')} | "
            f"{pct(row['analytic_p'])} | {pct(row['stochastic_sim_p'])} | "
            f"{row['analytic_sim_gap_pp']:+.2f} pp | {row['analytic_sim_divergence']} | "
            f"{row.get('projected_margin', '—')} | {row.get('projected_total', '—')} | "
            f"{row.get('spread_or_runline', '—')} | {row.get('total_market', '—')} | "
            f"{', '.join(row['warnings']) or 'None'} |"
        )
    if card["incidents"]:
        lines += ["", "## Coverage incidents", "", "```json", json.dumps(card["incidents"], indent=2), "```"]
    lines += ["", "**Diagnostic only. Action authority is OFF. No market/EV layer is attached.**"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--league", required=True, choices=["mlb", "cfb", "nfl", "wnba", "nba"])
    parser.add_argument("--as-of-utc")
    parser.add_argument("--simulations", type=int, default=100000)
    parser.add_argument("--manual-overrides")
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args()
    as_of = args.as_of_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    card = generate(args.date, args.league, as_of, args.simulations, args.manual_overrides)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "diagnostic_card.json").write_text(json.dumps(card, indent=2, sort_keys=True) + "\n")
    (output / "diagnostic_card.md").write_text(render_md(card))

    fields = [
        "event_id",
        "away_team",
        "home_team",
        "forecast_status",
        "forecast_tier",
        "data_quality",
        "dose",
        "model_winner",
        "analytic_p",
        "stochastic_sim_p",
        "analytic_sim_gap_pp",
        "analytic_sim_abs_gap_pp",
        "analytic_sim_divergence",
        "model_p_candidate_normal_margin",
        "projected_margin",
        "projected_total",
        "projected_home_runs",
        "projected_away_runs",
        "margin_std",
        "total_std",
        "spread_or_runline",
        "total_market",
        "warnings",
    ]
    with (output / "diagnostic_card.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in card["forecasts"]:
            csv_row = dict(row)
            csv_row["warnings"] = ";".join(csv_row.get("warnings", []))
            writer.writerow(csv_row)

    print(render_md(card))
    raise SystemExit(2 if card["coverage_breach_event_ids"] else 0)


if __name__ == "__main__":
    main()
