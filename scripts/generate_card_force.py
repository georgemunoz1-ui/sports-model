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
        v = float(x)
    except Exception:
        return False
    return math.isfinite(v) and 0 <= v <= 1


def dt(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def load_adapter(league):
    return importlib.import_module(f"pipelines.cards.adapters.{league.lower()}")


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
        "model_p": float(raw["model_p"]),
        "sim_p": float(raw["sim_p"]),
        "projected_margin": raw.get("projected_margin"),
        "projected_total": raw.get("projected_total", "UNSUPPORTED_BY_TIER"),
        "spread_or_runline": raw.get("spread_or_runline", "UNSUPPORTED_BY_TIER"),
        "total_market": raw.get("total_market", "UNSUPPORTED_BY_TIER"),
        "warnings": list(raw.get("warnings", [])),
        "input_snapshot_hash": raw.get("input_snapshot_hash"),
        "model_state_config_hash": raw.get("model_state_config_hash"),
        "simulation": raw.get("simulation", {}),
        "provenance": raw.get("provenance", {}),
        "action_authority": False,
        "action_status": "SHADOW_ONLY",
    }


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

    pre = [e for e in schedule if dt(e["start_time_utc"]) > cutoff]
    generated = {r["event_id"] for r in rows if r.get("forecast_status") == "FORECAST_GENERATED"}
    missing = [str(e["event_id"]) for e in pre if str(e["event_id"]) not in generated]
    return {
        "artifact_type": "diagnostic_force_card_v1",
        "card_date": card_date,
        "league": league.upper(),
        "as_of_utc": as_of,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "simulation_count": simulations,
        "authority": "SHADOW_ONLY",
        "actionable": False,
        "scheduled_game_count": len(schedule),
        "forecast_count": len(generated),
        "pregame_coverage": 1.0 if not pre else len(generated) / len(pre),
        "coverage_breach_event_ids": missing,
        "incidents": incidents,
        "forecasts": rows,
    }


def render_md(card):
    lines = [
        f"# {card['league']} Diagnostic Card — {card['card_date']}",
        "",
        f"Pregame coverage: **{card['pregame_coverage']:.1%}** · Action authority: **OFF**",
        "",
        "| Game | Tier | Dose | Winner | Model P | Sim P | Margin | Total | RL/ATS | Total Market | Warnings |",
        "|---|---|---:|---|---:|---:|---:|---:|---|---|---|",
    ]
    for r in card["forecasts"]:
        game = f"{r.get('away_team')} @ {r.get('home_team')}"
        if r.get("forecast_status") != "FORECAST_GENERATED":
            lines.append(
                f"| {game} | POST_START | — | — | — | — | — | — | — | — | post-start; no new pregame forecast |"
            )
            continue
        pct = lambda x: f"{100 * x:.1f}%"
        lines.append(
            f"| {game} | {r['forecast_tier']} | {r['dose']:.2f} | {r.get('model_winner', '—')} | "
            f"{pct(r['model_p'])} | {pct(r['sim_p'])} | {r.get('projected_margin', '—')} | "
            f"{r.get('projected_total', '—')} | {r.get('spread_or_runline', '—')} | "
            f"{r.get('total_market', '—')} | {', '.join(r['warnings']) or 'None'} |"
        )
    if card["incidents"]:
        lines += ["", "## Coverage incidents", "", "```json", json.dumps(card["incidents"], indent=2), "```"]
    lines += ["", "**Diagnostic only. Action authority is OFF.**"]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--league", required=True, choices=["mlb", "cfb", "nfl", "wnba", "nba"])
    ap.add_argument("--as-of-utc")
    ap.add_argument("--simulations", type=int, default=100000)
    ap.add_argument("--manual-overrides")
    ap.add_argument("--output-dir", default="output")
    a = ap.parse_args()
    asof = a.as_of_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    card = generate(a.date, a.league, asof, a.simulations, a.manual_overrides)
    out = Path(a.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "diagnostic_card.json").write_text(json.dumps(card, indent=2, sort_keys=True) + "\n")
    (out / "diagnostic_card.md").write_text(render_md(card))

    fields = [
        "event_id",
        "away_team",
        "home_team",
        "forecast_status",
        "forecast_tier",
        "data_quality",
        "dose",
        "model_winner",
        "model_p",
        "sim_p",
        "projected_margin",
        "projected_total",
        "spread_or_runline",
        "total_market",
        "warnings",
    ]
    with (out / "diagnostic_card.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in card["forecasts"]:
            rr = dict(r)
            rr["warnings"] = ";".join(rr.get("warnings", []))
            w.writerow(rr)

    print(render_md(card))
    raise SystemExit(2 if card["coverage_breach_event_ids"] else 0)


if __name__ == "__main__":
    main()
