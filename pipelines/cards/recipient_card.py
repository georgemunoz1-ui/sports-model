"""Static recipient presentation for diagnostic cards. No model or price translation."""
from hashlib import sha256
from html import escape
from pathlib import Path
from xml.etree import ElementTree as ET


_COLUMNS = ("Event ID", "Start (UTC)", "Away", "Home", "Status", "Model winner",
            "Model P", "Simulation P", "Projected margin¹", "Projected total", "Missingness review", "Refusal reason")


def _percent(value):
    return "—" if value is None else f"{value:.2%}"


def _audit_summary(row):
    receipt = row.get("missingness_audit") or {}
    if not receipt:
        return "MISSING RECEIPT"
    details = receipt["details"]
    parts = [receipt["release_status"], details.get("status", "See native diagnostics")]
    refresh = details.get("refresh") or {}
    if refresh:
        parts.append(refresh.get("status", "UNRESOLVED"))
    for name, head in refresh.get("heads", {}).items():
        parts.append(f"{name} ({head['scale']}): sporting {head['substantive']:+.3g}, "
                     f"indicator {head['missingness_indicator']:+.3g}, mixed {head['mixed_imputation_or_unknown']:+.3g}")
    return " · ".join(parts)


def _cells(row):
    status = row["forecast_status"]
    if status not in {"FORECAST_GENERATED", "BLOCKED", "POST_START"}:
        raise ValueError("UNKNOWN_RECIPIENT_ROW_STATUS")
    reason = row.get("refusal_reason") or ("POST_START" if status == "POST_START" else None)
    if status == "FORECAST_GENERATED" and (not row.get("model_winner") or
            row.get("model_p") is None or row.get("sim_p") is None):
        raise ValueError("RECIPIENT_FORECAST_INCOMPLETE")
    if status == "BLOCKED" and not reason:
        raise ValueError("RECIPIENT_REFUSAL_REASON_REQUIRED")
    fields = (row.get("event_id"), row.get("start_time_utc"), row.get("away_team"),
              row.get("home_team"), status, row.get("model_winner"),
              _percent(row.get("model_p")), _percent(row.get("sim_p")),
              row.get("projected_margin"), row.get("projected_total"), _audit_summary(row), reason)
    return tuple("—" if v is None else str(v) for v in fields)


def _html(card):
    title = f'{card["league"]} diagnostic card — {card["card_date"]}'
    rows = ["<tr>" + "".join(f"<td>{escape(v)}</td>" for v in _cells(r)) + "</tr>"
            for r in card["forecasts"]]
    title = escape(title)
    notes = [escape(str(i.get("detail") or i.get("incident") or ""))
             for i in card.get("incidents", []) if not i.get("event_id")]
    incident_note = ("<h2>Schedule and input issues</h2><ul>" +
                     "".join(f"<li>{note}</li>" for note in notes) + "</ul>") if notes else ""
    nfl_note = ("<p>NFL winner probabilities are conditional on a non-tie. "
                "The margin and total are independent point estimates.</p>" if
                any(r.get("probability_scope") == "BINARY_CONDITIONAL_ON_NON_TIE"
                    for r in card["forecasts"]) else "")
    empty_note = "" if rows else "<p>The checked card contains zero event rows.</p>"
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"/>'
            f'<title>{title}</title></head><body><h1>{title}</h1>'
            '<p>Research only · Wagering authority OFF</p>'
            f'{empty_note}{incident_note}{nfl_note}<table><thead><tr>' + "".join(f"<th>{v}</th>" for v in _COLUMNS) +
            '</tr></thead><tbody>' + "\n".join(rows) + '</tbody></table>'
            '<p>¹ Margin and total retain the values and units of the league adapter. '
            'Model and simulation probabilities refer to the named outcome. '
            'Consult the source card for the estimator and settlement scope.</p></body></html>\n')


def write_recipient_card(card, destination):
    with Path(destination).open("x", encoding="utf-8") as stream:
        stream.write(_html(card))


def verify_recipient_card(card, path):
    """Check readback bytes and table text; require the static, script-free presentation."""
    raw = Path(path).read_bytes()
    if raw != _html(card).encode("utf-8"):
        raise ValueError("RECIPIENT_HTML_READBACK_MISMATCH")
    document = ET.fromstring(raw)
    table = document.find("./body/table/tbody")
    if table is None:
        raise ValueError("RECIPIENT_TABLE_MISSING")
    actual = [tuple(td.text or "" for td in tr.findall("td")) for tr in table.findall("tr")]
    expected = [_cells(row) for row in card["forecasts"]]
    if actual != expected:
        raise ValueError("RECIPIENT_ROWS_MISMATCH")
    return {"sha256": sha256(raw).hexdigest(), "rows": len(actual),
            "forecast_count": sum(row["forecast_status"] == "FORECAST_GENERATED" for row in card["forecasts"])}
