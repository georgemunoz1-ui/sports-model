from __future__ import annotations
from dataclasses import dataclass, asdict

PROB_GAP_PP = 0.08          # 8 percentage points vs. no-vig market
TOTAL_LINE_GAP_PTS = 5.0    # 5.0 points vs. retained market total
BAD_WEATHER_STATUSES = {"WEATHER_IMPUTED", "WEATHER_ACQUISITION_FAILED", "WEATHER_NOT_YET_PUBLISHED"}

@dataclass(frozen=True)
class ScanAlert:
    event_id: str
    league: str
    alert_code: str
    severity: str           # "WARN" | "BLOCK"
    detail: dict

def scan_event_row(row: dict, context_receipt: dict | None = None) -> list[ScanAlert]:
    """Read-only pre-tip diagnostic scanner. Never mutates forecast probabilities."""
    alerts: list[ScanAlert] = []
    eid, lg = row["event_id"], row["league"]

    # 1. Probability divergence vs. no-vig market (> 8 pp)
    if row.get("p") is not None and row.get("market") is not None:
        gap = round(float(row["p"]) - float(row["market"]), 6)
        if abs(gap) > PROB_GAP_PP:
            alerts.append(ScanAlert(
                eid, lg, "MARKET_PROB_DIVERGENCE", "WARN",
                {"product": row.get("product"), "p": row["p"], "market": row["market"],
                 "gap_pp": round(gap * 100, 2), "requires_feature_attribution": True},
            ))

    # 2. Point-total divergence vs. market line (> 5 pts)
    if row.get("product") == "total" and row.get("point_total") is not None and row.get("line") is not None:
        tgap = round(float(row["point_total"]) - float(row["line"]), 4)
        if abs(tgap) > TOTAL_LINE_GAP_PTS:
            alerts.append(ScanAlert(
                eid, lg, "TOTAL_LINE_DIVERGENCE", "WARN",
                {"point_total": row["point_total"], "line": row["line"], "gap_pts": tgap},
            ))

    # 3. Context-freshness & missingness checks
    if context_receipt is None:
        alerts.append(ScanAlert(eid, lg, "CONTEXT_RECEIPT_MISSING", "WARN", {}))
        return alerts

    if lg == "NFL" and context_receipt.get("roof") == "outdoor":
        for field in ("temperature", "wind", "precipitation"):
            st = context_receipt.get(f"{field}_status")
            if st in BAD_WEATHER_STATUSES:
                alerts.append(ScanAlert(eid, lg, f"NFL_{field.upper()}_{st}", "WARN", {"field": field, "status": st}))

    if lg == "CBB" and context_receipt.get("orientation_reversed") and not context_receipt.get("neutral_venue_verified"):
        alerts.append(ScanAlert(eid, lg, "CBB_UNVERIFIED_NEUTRAL_REVERSAL", "BLOCK", {"status": "HOLD"}))

    return alerts
