"""Present retained audit evidence without recomputing or reclassifying forecasts."""
from html import escape


HEADERS = ("Arm / head", "Attribution units", "Sporting inputs", "Missingness / imputation",
           "Model / version", "Unresolved / mixed", "Reporting state")


def _number(value):
    return "UNAVAILABLE" if value is None else f"{value:+.6g}"


def audit_view(row):
    receipt = row.get("missingness_audit") or {}
    if not receipt:
        return {"summary": "MISSING RECEIPT", "heads": [],
                "notes": ["Change attribution unavailable; model, simulation and interactions unassessed."]}
    details = receipt["details"]
    native = details.get("native")
    if native:
        details = native["details"]
    refresh = details.get("refresh") or {}
    status = details.get("comparison_status") or refresh.get("status") or "COMPARISON_UNAVAILABLE"
    parts = [receipt["release_status"], details.get("status", "NATIVE_DIAGNOSTICS"), status]
    heads, notes = [], []
    for arm, evidence in details.get("arms", {}).items():
        for target, head in evidence.get("changes", {}).items():
            dominated = head.get("reporting_state_dominated") is True
            heads.append((f"{arm} / {target}", head["units"],
                          _number(head.get("observed_feature_change")),
                          _number(head.get("missingness_imputation")),
                          _number(head.get("model_version_delta")),
                          _number(head.get("observation_or_reporting_interaction")),
                          "REPORTING_STATE_DOMINATED" if dominated else "No dominance flag"))
            if dominated:
                notes.append(f"{arm} / {target}: report-presence contribution "
                             f"{_number(head.get('reporting_presence_delta'))} {head['units']}; "
                             "descriptive diagnostic, not an injury-driven edge.")
    for target, head in refresh.get("heads", {}).items():
        units = details.get("units", "native") if head["scale"] == "native" else head["scale"]
        heads.append((f"{receipt['model_id']} / {target}", units,
                      _number(head.get("substantive")), _number(head.get("missingness_indicator")),
                      refresh.get("model_version_change", "UNAVAILABLE"),
                      _number(head.get("mixed_imputation_or_unknown")), "Not assessed"))
        interaction = head.get("native_head_interaction") or {}
        if interaction:
            notes.append(f"{target}: output-scale interaction {_number(interaction.get('interaction'))}; "
                         f"method {interaction['method']}; complete {interaction['decomposition_complete']}.")
    if any(h[-1] == "REPORTING_STATE_DOMINATED" for h in heads):
        parts.append("REPORTING_STATE_DOMINATED")
    if not heads:
        notes.append(f"Change attribution unavailable: {status}. Sporting, missingness and model "
                     "contributions must not be inferred as zero.")
    notes.append("Contributions use the stated fitted-head units; home_log_odds are not probability points. "
                 "Mixed or unresolved terms are not allocated to sporting observations.")
    for key in ("joint_law_attribution", "unresolved_interactions"):
        if details.get(key):
            notes.append(str(details[key]))
    if refresh.get("interactions"):
        notes.append(refresh["interactions"])
    if refresh.get("model_version_change"):
        notes.append("Model/version: " + refresh["model_version_change"])
    elif details.get("current_artifact_sha256"):
        notes.append("Model/version artifact: " + str(details.get("prior_artifact_sha256") or "UNAVAILABLE") +
                     " → " + details["current_artifact_sha256"])
    simulation = details.get("simulation")
    if isinstance(simulation, dict):
        before, after = simulation.get("winner_before") or {}, simulation.get("winner_after") or {}
        notes.append("Simulation (separate): home-win P " + str(before.get("home_win_probability", "UNAVAILABLE")) +
                     " → " + str(after.get("home_win_probability", "UNAVAILABLE")) +
                     "; draws " + str(before.get("count", "UNAVAILABLE")) + " → " + str(after.get("count", "UNAVAILABLE")) +
                     "; score law " + str(simulation.get("score_law_before") or "UNAVAILABLE") +
                     " → " + str(simulation.get("score_law_after") or "UNAVAILABLE") + ".")
    elif "sim_p_before" in refresh:
        notes.append(f"Simulation (separate): named outcome {refresh.get('side_before')} "
                     f"P {refresh['sim_p_before']} → {refresh.get('side_after')} P {refresh.get('sim_p_after')}.")
    else:
        notes.append("Simulation change: UNAVAILABLE; no paired sampling attribution.")
    notes.append("Before/after simulation outputs do not isolate sampling noise when inputs or laws change. "
                 "Perturbations are diagnostic experiments, not established sporting counterfactuals.")
    return {"summary": " · ".join(parts), "heads": heads, "notes": notes}


def render_html(card):
    sections = ["<section><h2>Missingness change receipts</h2>"]
    for row in card["forecasts"]:
        view = audit_view(row)
        label = f"{row.get('away_team')} @ {row.get('home_team')} ({row.get('event_id')})"
        sections.append(f"<h3>{escape(label)}</h3><p>{escape(view['summary'])}</p>")
        if view["heads"]:
            sections.append("<table><thead><tr>" + "".join(f"<th>{escape(h)}</th>" for h in HEADERS) +
                            "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{escape(v)}</td>" for v in head) +
                            "</tr>" for head in view["heads"]) + "</tbody></table>")
        sections.extend(f"<p>{escape(note)}</p>" for note in view["notes"])
    return "".join(sections) + "</section>"


def render_md(card):
    def safe(value):
        return escape(str(value)).replace("|", "&#124;").replace("\n", " ").replace("\r", " ")
    lines = ["## Missingness change receipts", ""]
    for row in card["forecasts"]:
        view = audit_view(row)
        lines += [f"### {safe(row.get('away_team'))} @ {safe(row.get('home_team'))} ({safe(row.get('event_id'))})",
                  "", safe(view["summary"]), ""]
        if view["heads"]:
            lines += ["| " + " | ".join(HEADERS) + " |", "| " + " | ".join("---" for _ in HEADERS) + " |"]
            lines.extend("| " + " | ".join(safe(v) for v in head) + " |" for head in view["heads"])
            lines.append("")
        lines.extend(safe(note) + "\n" for note in view["notes"])
    return "\n".join(lines)
