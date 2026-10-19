"""Immutable, opt-in margin cards; incumbents and source artifacts are read-only.

Input PMFs must already exist. This adapter never derives a score margin from a
winner probability and never treats a hypothetical handicap as a market quote.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import html
import json
import math
from pathlib import Path

import numpy as np

from models.common import discrete_research as D
from models.common import margin_system as M

INPUT_SCHEMA = "sports.margin_system_input.research.v1"
REPORT_SCHEMA = "sports.margin_system_card.research.v1"
LEAGUES = ("nfl", "cfb", "nba", "wnba", "mlb", "nhl", "mls")
DEFAULT_LINES = {
    "nfl": [-14., -10., -7., -6.5, -3.5, -3., 0., 3., 3.5, 6.5, 7., 10., 14.],
    "cfb": [-28., -21., -14., -10., -7., -3.5, -3., 0., 3., 3.5, 7., 10., 14., 21., 28.],
    "nba": [-15., -10., -7.5, -5., -2.5, 0., 2.5, 5., 7.5, 10., 15.],
    "wnba": [-15., -10., -7.5, -5., -2.5, 0., 2.5, 5., 7.5, 10., 15.],
    "mlb": [-3.5, -2.5, -1.5, -1., 0., 1., 1.5, 2.5, 3.5],
    "nhl": [-3.5, -2.5, -1.5, -1., 0., 1., 1.5, 2.5, 3.5],
    "mls": [-2., -1.5, -1., -.75, -.5, -.25, 0., .25, .5, .75, 1., 1.5, 2.],
}
CONFIG_SCHEMA = "sports.margin_system_challenger_config.research.v1"


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("JSON_OBJECT_REQUIRED")
    return value, {"path": str(path), "file_sha256": hashlib.sha256(raw).hexdigest()}


def _verify_report(value):
    """Validate the retained report's exact content identity before conversion."""
    artifact = dict(value)
    expected = artifact.pop("artifact_sha256", None)
    D.source_hash(expected)
    if D.digest(artifact) != expected:
        raise ValueError("PARENT_REPORT_HASH_MISMATCH")
    if value.get("action_authority") is not False:
        raise ValueError("PARENT_RESEARCH_AUTHORITY_REQUIRED")


def _metadata(path):
    if path is None:
        return {}, None
    value, receipt = _read(path)
    rows = value.get("events", value.get("forecasts"))
    if not isinstance(rows, list):
        raise ValueError("EVENT_METADATA_LIST_REQUIRED")
    result = {}
    for row in rows:
        eid = D.identity(row.get("event_id"), "EVENT_ID")
        if eid in result:
            raise ValueError("DUPLICATE_METADATA_EVENT")
        result[eid] = {k: row[k] for k in ("event_id", "home_team", "away_team", "start_time_utc") if k in row}
        if "start_time_utc" in result[eid]:
            D.stamp(result[eid]["start_time_utc"])
    receipt["role"] = "EVENT_LABELS_AND_START_TIMES_ONLY"
    return result, receipt


def _load_inputs(paths):
    inputs, rows, source_coverage = [], [], []
    for path in paths:
        value, receipt = _read(path)
        schema = value.get("schema")
        if schema == "sports.distribution_card.research.v1":
            _verify_report(value)
            entries = value.get("results")
            receipt.update({"role": "RETAINED_DISTRIBUTION_REPORT",
                            "artifact_sha256": value["artifact_sha256"],
                            "parent_card_sha256": value.get("parent_card_sha256"),
                            "created_at_utc": value.get("created_at_utc"),
                            "as_of_utc": value.get("as_of_utc")})
        elif schema == INPUT_SCHEMA:
            if value.get("action_authority") is not False:
                raise ValueError("INPUT_RESEARCH_AUTHORITY_REQUIRED")
            entries = value.get("distributions")
            receipt["role"] = "EXPLICIT_DISTRIBUTION_INPUT"
        else:
            raise ValueError("UNSUPPORTED_INPUT_SCHEMA")
        if not isinstance(entries, list):
            raise ValueError("DISTRIBUTIONS_LIST_REQUIRED")
        inputs.append(receipt)
        for entry in entries:
            if not isinstance(entry, dict) or "distribution" not in entry:
                raise ValueError("EXPLICIT_DISTRIBUTION_REQUIRED")
            eid = D.identity(entry.get("event_id"), "EVENT_ID")
            distribution = entry["distribution"]
            if not isinstance(distribution, dict):
                raise ValueError("DISTRIBUTION_OBJECT_REQUIRED")
            if distribution.get("product") != "margin":
                source_coverage.append({"event_id": eid, "league": distribution.get("league"),
                                        "product": distribution.get("product"), "status": "NOT_A_MARGIN_INPUT"})
                continue
            rows.append({**copy.deepcopy(entry), "input_file_sha256": receipt["file_sha256"],
                         "input_path": receipt["path"],
                         "parent_report_sha256": receipt.get("artifact_sha256")})
        for item in value.get("coverage", []):
            source_coverage.append({"league": value.get("league"), **copy.deepcopy(item),
                                    "source_file_sha256": receipt["file_sha256"]})
    return inputs, rows, source_coverage


def _point_inputs(parent_card_paths, config_path):
    """Bind separately fitted challengers to explicit same-scope point heads."""
    from models.common import margin_challenger as F
    from pipelines.cards.distribution_research import point

    config, receipt = _read(config_path)
    if config.get("schema") != CONFIG_SCHEMA or config.get("action_authority") is not False:
        raise ValueError("CHALLENGER_CONFIG_SCHEMA_OR_AUTHORITY")
    information_set = D.identity(config.get("information_set"), "INFORMATION_SET")
    receipt["role"] = "CHALLENGER_CONFIG"
    sources, entries, coverage, models = [receipt], [], [], []
    for entry in config.get("models", []):
        path = (Path(config_path).resolve().parent / entry["path"]).resolve()
        model, model_receipt = _read(path)
        D.source_hash(entry.get("sha256"))
        if model_receipt["file_sha256"] != entry["sha256"]:
            raise ValueError("CHALLENGER_MODEL_FILE_HASH_MISMATCH")
        F.validate_model(model)
        if model["information_set"] != information_set:
            raise ValueError("CHALLENGER_INFORMATION_SET_MISMATCH")
        models.append(model)
        sources.append({**model_receipt, "role": "FITTED_CHALLENGER", "model_id": model["model_id"],
                        "artifact_sha256": model["artifact_sha256"]})
    for path in parent_card_paths:
        card, card_receipt = _read(path)
        league = str(card.get("league", "")).lower()
        if league not in LEAGUES:
            raise ValueError("PARENT_CARD_LEAGUE_REQUIRED")
        cutoff = card.get("as_of_utc")
        D.stamp(cutoff)
        generated = card.get("generated_at_utc")
        D.stamp(generated)
        if not isinstance(card.get("forecasts"), list):
            raise ValueError("PARENT_FORECAST_LIST_REQUIRED")
        card_receipt.update({"role": "POINT_HEAD_PARENT_CARD", "parent_card_sha256": D.digest(card),
                             "as_of_utc": cutoff, "generated_at_utc": generated})
        sources.append(card_receipt)
        for row in card["forecasts"]:
            eid = D.identity(row.get("event_id"), "EVENT_ID")
            matched = [m for m in models if m["league"] == league and m["parent_model_id"] == row.get("model_id")]
            if not matched:
                coverage.append({"league": league, "event_id": eid, "parent_model_id": row.get("model_id"),
                                 "status": "MATCHING_CHALLENGER_FIT_REQUIRED"})
                continue
            for model in matched:
                try:
                    if row.get("forecast_status") != "FORECAST_GENERATED":
                        raise ValueError("PARENT_NOT_FORECAST")
                    start = row["start_time_utc"]
                    if not D.stamp(cutoff) <= D.stamp(generated) < D.stamp(start):
                        raise ValueError("PARENT_NOT_CREATED_PREGAME")
                    if row.get("information_set", card.get("information_set")) != information_set:
                        raise ValueError("PARENT_INFORMATION_SET_MISMATCH")
                    if row.get("settlement", card.get("settlement")) != model["settlement"]:
                        raise ValueError("PARENT_SETTLEMENT_MISMATCH")
                    D.source_hash(row.get("input_snapshot_hash"))
                    D.source_hash(row.get("model_state_config_hash"))
                    diagnostics = row.get("diagnostics") or {}
                    if diagnostics.get("market_input", False) is not False or row.get("market_input", False) is not False:
                        raise ValueError("MARKET_INFORMED_PARENT_REFUSED")
                    mean = point(row, "margin")
                    required_features = (model["state"].get("scaling") or {}).get("features", [])
                    snapshot = row.get("model_input_snapshot") or {}
                    scale_features = {}
                    for name in required_features:
                        if name in snapshot:
                            scale_features[name] = snapshot[name]
                        elif name == "absolute_parent_margin" and name in config.get("derived_scale_features", []):
                            scale_features[name] = abs(mean)
                        else:
                            raise ValueError("SCALE_FEATURE_UNAVAILABLE:" + name)
                    d = F.predict(model, mean=mean, event_id=eid, cutoff=cutoff, start_time_utc=start,
                                  parent_model_id=row["model_id"], information_set=information_set,
                                  parent_forecast_sha256=D.digest(row),
                                  scale_features=scale_features)
                    warnings = list(row.get("warnings", []))
                    if not d["provenance"].get("artifact_existed_at_forecast_cutoff"):
                        warnings.append("NEW_FIT_CREATED_AFTER_PARENT_CUTOFF_RECONSTRUCTION_ONLY")
                    entries.append({"event_id": eid, "distribution": d,
                                    "home_team": row["home_team"], "away_team": row["away_team"],
                                    "start_time_utc": start, "parent_warnings": warnings,
                                    "parent_report_sha256": None,
                                    "input_file_sha256": card_receipt["file_sha256"],
                                    "input_path": card_receipt["path"]})
                    coverage.append({"league": league, "event_id": eid, "model_id": model["model_id"],
                                     "product": "margin", "status": "CHALLENGER_GENERATED"})
                except (ValueError, KeyError, TypeError) as exc:
                    coverage.append({"league": league, "event_id": eid, "model_id": model["model_id"],
                                     "product": "margin", "status": "UNAVAILABLE", "reason": str(exc)})
    return sources, entries, coverage


def _time_status(start_time, cutoff, created):
    if start_time is None:
        return "START_TIME_UNAVAILABLE"
    start = D.stamp(start_time)
    if D.stamp(created) >= start:
        return "CREATED_POST_START_RESEARCH_ONLY"
    if cutoff is None:
        return "INPUT_CUTOFF_UNAVAILABLE"
    if D.stamp(cutoff) >= start:
        return "INPUT_CUTOFF_NOT_PREGAME"
    return "CREATED_BEFORE_START_RESEARCH_ONLY"


def _percent(value):
    return "—" if value is None else f"{100 * value:.2f}%"


def build(input_paths, output, *, events_path=None, draws=100000, home_spreads=None,
          parent_card_paths=(), challenger_config_path=None):
    """Read retained PMFs and create a distinct report plus real simulation files.

    Fail before creating the output directory on malformed or mismatched inputs.
    An existing output path always refuses, including an empty directory. The
    actual writer clock controls post-start labels; there is no clock CLI option.
    """
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError("OUTPUT_EXISTS_IMMUTABLE")
    if isinstance(draws, bool) or not isinstance(draws, int) or not 1 <= draws <= 1_000_000:
        raise ValueError("DRAWS_INTEGER_1_TO_1000000_REQUIRED")
    input_paths = list(input_paths)
    parent_card_paths = list(parent_card_paths)
    if bool(parent_card_paths) != bool(challenger_config_path):
        raise ValueError("PARENT_CARDS_AND_CHALLENGER_CONFIG_REQUIRED_TOGETHER")
    if not input_paths and not parent_card_paths:
        raise ValueError("INPUT_REQUIRED")
    sources, entries, source_coverage = _load_inputs(input_paths)
    if parent_card_paths:
        extra_sources, extra_entries, extra_coverage = _point_inputs(parent_card_paths, challenger_config_path)
        sources.extend(extra_sources)
        entries.extend(extra_entries)
        source_coverage.extend(extra_coverage)
    metadata, metadata_receipt = _metadata(events_path)
    created = D.writer_clock()
    now = D.stamp(created)
    results, arrays, seen = [], [], set()
    for entry in entries:
        d = M.from_discrete(entry["distribution"])
        eid = entry["event_id"]
        provenance = d["provenance"]
        if provenance.get("event_id") != eid:
            raise ValueError("DISTRIBUTION_EVENT_BINDING_MISMATCH")
        cutoff = provenance.get("cutoff")
        if D.stamp(cutoff) > now:
            raise ValueError("INPUT_CUTOFF_IN_FUTURE")
        league = d["league"]
        key = (eid, d["model_id"], d["settlement"])
        if key in seen:
            raise ValueError("DUPLICATE_EVENT_MODEL_SETTLEMENT")
        seen.add(key)
        labels = {}
        if provenance.get("start_time_utc") is not None:
            labels["start_time_utc"] = provenance["start_time_utc"]
            D.stamp(labels["start_time_utc"])
        for k in ("home_team", "away_team", "start_time_utc"):
            if k not in entry:
                continue
            if k == "start_time_utc" and k in labels and D.stamp(labels[k]) != D.stamp(entry[k]):
                raise ValueError("DISTRIBUTION_START_TIME_CONFLICT")
            labels[k] = entry[k]
        for k, v in metadata.get(eid, {}).items():
            if k == "event_id":
                continue
            disagree = k in labels and (D.stamp(labels[k]) != D.stamp(v) if k == "start_time_utc" else labels[k] != v)
            if disagree:
                raise ValueError("EVENT_METADATA_CONFLICT:" + k)
            labels[k] = v
        for k in ("home_team", "away_team"):
            if k in labels:
                D.identity(labels[k], k.upper())
        lines = DEFAULT_LINES[league] if home_spreads is None else home_spreads
        ladder = [{"kind": "HYPOTHETICAL", "home_handicap": p["home_spread"],
                   "away_handicap": p["away_spread"], **p} for p in M.cover_ladder(d, lines)]
        actual_draws, simulation = M.simulate_margin(d, draws=draws, home_spreads=lines)
        receipt = simulation.pop("receipt")
        filename = d["distribution_sha256"] + ".npy"
        arrays.append((filename, actual_draws))
        summary = M.summarize(d)
        warnings = list(entry.get("parent_warnings", entry.get("warnings", [])))
        warnings.extend(summary.get("limitations", []))
        if provenance.get("market_input") is True:
            warnings.append("MARKET_INFORMED_PARENT_NOT_INDEPENDENT_MARKET_EDGE")
        if provenance.get("support_policy") == "CONDITION_ON_LEGAL_SUPPORT":
            warnings.append("RETAINED_UPSTREAM_SUPPORT_CONDITIONING_NOT_REPAIRED")
        if provenance.get("removed_zero_margin_mass_before_conditioning", 0) > 0:
            warnings.append("UPSTREAM_ZERO_MARGIN_CONDITIONING_PRESENT")
        time_status = _time_status(labels.get("start_time_utc"), cutoff, created)
        results.append({"event_id": eid, "league": league, "model_id": d["model_id"],
                        "settlement": d["settlement"], **labels, "as_of_utc": cutoff,
                        "time_status": time_status, "summary": summary, "cover_ladder": ladder,
                        "simulation": {**receipt, "file": "draws/" + filename,
                                       "diagnostics": simulation},
                        "distribution": d, "parent_distribution_sha256": d["distribution_sha256"],
                        "parent_report_sha256": entry["parent_report_sha256"],
                        "input_file_sha256": entry["input_file_sha256"],
                        "source_simulation_receipt": entry.get("simulation"),
                        "warnings": sorted(set(warnings)),
                        "status": {"software": "EXECUTED", "input": "RETAINED_HASH_VERIFIED",
                                   "fit_validation": "NOT_ESTABLISHED_BY_THIS_REPORT",
                                   "prospective_validation": "PENDING_TEST",
                                   "global_health": "INCOMPLETE_PARTIAL_SNAPSHOT"},
                        "prospective_grade_eligible": False, "action_authority": False})
    coverage = []
    for league in LEAGUES:
        selected = [row for row in results if row["league"] == league]
        coverage.append({"league": league, "margin_rows": len(selected),
                         "event_count": len({row["event_id"] for row in selected}),
                         "status": "RESEARCH_OUTPUT_AVAILABLE" if selected else "NO_MARGIN_INPUT",
                         "schedule_status": "NOT_VERIFIED_BY_THIS_RUN",
                         "total_status": "NOT_GENERATED_BY_MARGIN_RUN",
                         "joint_score_status": "SOURCE_DECLARED" if any(row["distribution"]["provenance"].get("joint_score_distribution") for row in selected) else "UNAVAILABLE",
                         "source_coverage": [item for item in source_coverage if item.get("league") == league]})
    report = {"schema": REPORT_SCHEMA, "execution_started_at_utc": created, "orientation": M.ORIENTATION,
              "results": results, "coverage": coverage, "source_coverage": source_coverage,
              "sources": sources, "event_metadata_source": metadata_receipt,
              "contract_kind": "HYPOTHETICAL", "market_quotes_used": False,
              "global_health": "INCOMPLETE_PARTIAL_SNAPSHOT",
              "execution_status": "PARTIAL" if any(item.get("status") not in {"COMPLETED", "CHALLENGER_GENERATED"} for item in source_coverage) else "COMPLETED",
              "predictive_validation": "UNVALIDATED",
              "predictive_validation_reason": "NOT_ESTABLISHED_BY_SOFTWARE_EXECUTION",
              "publication_eligibility": "INELIGIBLE", "wagering_authority": "OFF",
              "prospective_grade_eligible": False, "action_authority": False,
              "incumbent_models_changed": False,
              "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    # mkdir(exist_ok=False) is the final race-safe no-overwrite guard.
    output.mkdir(parents=True, exist_ok=False)
    (output / "draws").mkdir()
    for filename, values in arrays:
        path = output / "draws" / filename
        with path.open("xb") as stream:
            np.save(stream, values, allow_pickle=False)
        file_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        for row in results:
            if row["simulation"]["file"] == "draws/" + filename:
                row["simulation"]["file_sha256"] = file_sha
    report["created_at_utc"] = D.writer_clock()
    for row in results:
        row["time_status"] = _time_status(row.get("start_time_utc"), row["as_of_utc"], report["created_at_utc"])
    report["artifact_sha256"] = D.digest(report)
    with (output / "margin_report.json").open("x") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    with (output / "margin_card.html").open("x") as stream:
        stream.write(_render(report))
    return report


def _render(report):
    """Render a readable card without changing numerical data or model identity."""
    esc = lambda value: html.escape(str(value))
    parts = ["<!doctype html><html lang='en'><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width,initial-scale=1'>",
             "<title>All-sports margin and cover research</title>",
             "<style>body{font:16px system-ui,sans-serif;background:#f4f6fa;color:#192331;max-width:1200px;margin:36px auto;padding:0 20px}h1{font-size:30px}h2{margin-top:38px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;background:white;margin:16px 0}th,td{padding:10px;border-bottom:1px solid #dbe1ea;text-align:right}th:first-child,td:first-child{text-align:left}small,.muted{color:#596779}code{overflow-wrap:anywhere;font-size:12px}.notice{background:#fff2cd;border-left:4px solid #c68c00;padding:16px}.scroll{overflow:auto}.tag{font-size:12px;color:#4c6182}details{padding:10px;background:white}</style>",
             "<h1>All-sports margin and cover research</h1>",
             f"<p class='muted'>Generated {esc(report['created_at_utc'])}. Margin M = home score − away score.</p>",
             "<p class='notice'><b>Research only; action authority OFF.</b> Global health is incomplete. All line ladders are <b>HYPOTHETICAL</b>, with no sportsbook quote or price implied. Predictive performance is pending test. Winner, margin and cover numbers below come from the same margin PMF; they are separate from any incumbent winner model.</p>",
             "<h2>Coverage</h2><div class='scroll'><table><tr><th>League</th><th>Margin rows</th><th>Status</th><th>Total / joint score</th></tr>"]
    for row in report["coverage"]:
        parts.append(f"<tr><td>{esc(row['league'].upper())}</td><td>{row['margin_rows']}</td><td>{esc(row['status'])}</td><td>{esc(row['total_status'])} / {esc(row['joint_score_status'])}</td></tr>")
    parts.append("</table></div><p class='muted'>No input does not establish an empty schedule. All prediction intervals describe game variability, not confidence intervals on fitted parameters.</p>")
    failures = [row for row in report["source_coverage"] if row.get("status") not in {"COMPLETED", "CHALLENGER_GENERATED"}]
    if failures:
        parts.append("<h3>Unavailable inputs and products</h3><div class='scroll'><table><tr><th>Event</th><th>Status</th><th>Reason</th></tr>")
        for row in failures:
            parts.append(f"<tr><td>{esc(row.get('event_id', '—'))}</td><td>{esc(row.get('status', 'UNAVAILABLE'))}</td><td>{esc(row.get('reason', row.get('detail', '—')))}</td></tr>")
        parts.append("</table></div>")
    for row in report["results"]:
        summary = row["summary"]
        label = f"{row.get('away_team', 'Away')} @ {row.get('home_team', 'Home')}"
        parts.extend([f"<h2>{esc(label)} <span class='tag'>{esc(row['league'].upper())}</span></h2>",
                      f"<p><code>{esc(row['model_id'])}</code><br><small>{esc(row['event_id'])} · {esc(row['time_status'])} · Input cutoff {esc(row.get('as_of_utc'))}</small></p>",
                      f"<p>Settlement: {esc(row['settlement'])}. Retained parent distribution: <code>{esc(row['parent_distribution_sha256'])}</code>.</p>",
                      "<div class='scroll'><table><tr><th>Summary</th><th>Value</th></tr>"])
        human_summary = [("Mean home margin", f"{summary['mean_margin']:+.3f}"),
                         ("Median home margin", f"{summary['median_margin']:+g}"),
                         ("Mean-implied home handicap", f"{summary['mean_implied_home_spread']:+.3f}"),
                         ("Home win / draw / away win", " / ".join(_percent(summary['winner'][k]) for k in ("home_win", "draw", "away_win")))]
        for nominal in ("50", "80", "95"):
            interval = summary["prediction_intervals"][nominal]
            human_summary.append((nominal + "% predictive interval", f"[{interval['lower']:+g}, {interval['upper']:+g}] (mass {_percent(interval['attained_probability'])})"))
        for label, val in human_summary:
            parts.append(f"<tr><td>{esc(label)}</td><td>{esc(val)}</td></tr>")
        parts.extend(["</table></div><h3>Hypothetical home-handicap ladder</h3>",
                      "<div class='scroll'><table><tr><th>Home handicap</th><th>Home win</th><th>Half win</th><th>Push</th><th>Half loss</th><th>Home loss</th></tr>"])
        for item in row["cover_ladder"]:
            p = item["home"]
            parts.append(f"<tr><td>{item['home_spread']:+g}</td>" + "".join(f"<td>{_percent(p[k])}</td>" for k in D.STATES) + "</tr>")
        parts.extend(["</table></div>", f"<p class='muted'>Actual draws: {row['simulation']['count']:,}. RNG {esc(row['simulation']['rng'])}. Draw SHA-256: <code>{esc(row['simulation']['draw_sha256'])}</code>.</p>"])
        if row.get("warnings"):
            parts.append("<p class='notice'>" + " · ".join(esc(v) for v in row["warnings"]) + "</p>")
        parts.append("<details><summary>Distribution and provenance</summary><pre style='white-space:pre-wrap'>" + esc(json.dumps({"distribution": row["distribution"], "simulation": row["simulation"]}, indent=2, sort_keys=True)) + "</pre></details>")
    parts.append("<h2>Source identities</h2><div class='scroll'><table><tr><th>Source file</th><th>Role</th><th>SHA-256</th></tr>")
    for source in report["sources"]:
        parts.append(f"<tr><td>{esc(Path(source['path']).name)}</td><td>{esc(source['role'])}</td><td><code>{esc(source['file_sha256'])}</code></td></tr>")
    parts.append("</table></div><h2>Artifact identity</h2><p><code>" + esc(report["artifact_sha256"]) + "</code></p></html>")
    return "\n".join(parts)
