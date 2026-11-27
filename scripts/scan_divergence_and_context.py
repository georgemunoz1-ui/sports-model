"""Read-only diagnostic scanner. CBB adapter replays native quote and schedule evidence.

Untrusted dictionaries never establish context authentication or input consumption.
The companion output is not a registration, forecast, or release authorization.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import argparse
import json
import math
import re

from scripts.cbb_reconciliation_gate import parse, forecast_deadline, load_evidence, target_gate
from scripts.source_attestation import instant, sha256

PROB_GAP_PP = 0.08
TOTAL_LINE_GAP_PTS = 5.0
WEATHER_FIELDS = ("temperature", "wind", "precipitation")
WEATHER_STATES = {"WEATHER_IMPUTED", "WEATHER_ACQUISITION_FAILED",
                  "WEATHER_NOT_YET_PUBLISHED", "WEATHER_OBSERVED_NOT_CONSUMED",
                  "WEATHER_OBSERVED_CONSUMED", "WEATHER_UNSUPPORTED_BY_HEAD"}
SETTLEMENT = "FULL_GAME_INCLUDING_OVERTIME"

@dataclass(frozen=True)
class ScanAlert:
    event_id: str
    league: str
    alert_code: str
    severity: str
    detail: dict

def valid_number(x):
    return type(x) in (int, float) and math.isfinite(x)

def valid_prob(x):
    return valid_number(x) and 0 <= x <= 1

def pin_json(path, pin):
    if not isinstance(pin, str) or not re.fullmatch(r"[a-f0-9]{64}", pin):
        raise ValueError("TRUSTED_SHA256_REQUIRED")
    raw = Path(path).read_bytes()
    if sha256(raw) != pin:
        raise ValueError("ARTIFACT_SHA256_MISMATCH")
    return parse(raw)

def scan_contract(row):
    eid, lg = row["event_id"], row["league"]
    alerts = []
    def add(code, severity="BLOCK", **detail):
        alerts.append(ScanAlert(eid, lg, code, severity, detail))
    p, m = row.get("p"), row.get("market")
    for val, name in ((p, "NATIVE"), (m, "MARKET")):
        if not valid_prob(val):
            add("INVALID_OR_MISSING_" + name + "_PROBABILITY")
    for field in ("product", "side", "line", "period", "settlement_scope", "event_id"):
        other = "market_" + field
        if field not in row or other not in row:
            add("CONTRACT_IDENTITY_MISSING", field=field)
        elif row[field] != row[other]:
            add("CONTRACT_MISMATCH", field=field)
    prod, line, side = row.get("product"), row.get("line"), row.get("side")
    if prod not in ("winner", "margin", "total") or side not in (
        ("over", "under") if prod == "total" else ("home", "away")
    ):
        add("CONTRACT_DOMAIN_INVALID")
    if prod == "winner":
        if line is not None or row.get("market_line") is not None:
            add("CONTRACT_LINE_INVALID")
    elif not valid_number(line) or not valid_number(row.get("market_line")) or (prod == "total" and line <= 0):
        add("CONTRACT_LINE_INVALID")
    if row.get("period") != "FULL_GAME" or row.get("settlement_scope") != SETTLEMENT:
        add("CONTRACT_SCOPE_UNSUPPORTED")
    if prod == "total" and not valid_number(row.get("point_total")):
        add("POINT_TOTAL_INVALID")
    if alerts:
        return alerts
    gap = Decimal(str(p)) - Decimal(str(m))
    if abs(gap) > Decimal(str(PROB_GAP_PP)):
        add("MARKET_PROB_DIVERGENCE", "WARN", product=prod, side=side,
            line=line, gap_pp=float(gap*100), requires_feature_attribution=True)
    if prod == "total":
        tgap = Decimal(str(row["point_total"])) - Decimal(str(line))
        if abs(tgap) > Decimal(str(TOTAL_LINE_GAP_PTS)):
            add("TOTAL_LINE_DIVERGENCE", "WARN", point_total=row["point_total"],
                line=line, gap_pts=float(tgap))
    return alerts

def scan_event_row(row, context_receipt=None):
    """Generic diagnostic input: report claims but never authenticate caller dictionaries."""
    alerts = scan_contract(row)
    def add(code, severity="BLOCK", **detail):
        alerts.append(ScanAlert(row["event_id"], row["league"], code, severity, detail))
    if not isinstance(context_receipt, dict):
        add("CONTEXT_RECEIPT_MISSING")
        return alerts
    add("UNAUTHENTICATED_CONTEXT_RECEIPT")
    try:
        retrieved = instant(context_receipt["retrieved_at_utc"])
        cutoff = instant(row["pregame_cutoff_utc"])
        if (context_receipt.get("event_id") != row["event_id"]
            or instant(context_receipt["pregame_cutoff_utc"]) != cutoff
            or not timedelta(0) < cutoff-retrieved <= timedelta(hours=6)):
            raise ValueError("context timing")
    except (KeyError, TypeError, ValueError, OverflowError):
        add("STALE_OR_POST_CUTOFF_RECEIPT")
    if row["league"] == "NFL":
        roof = context_receipt.get("roof")
        if roof not in ("outdoor", "indoor", "retractable_closed", "retractable_open"):
            add("NFL_ROOF_UNKNOWN", "WARN")
        if roof not in ("indoor", "retractable_closed"):
            for field in WEATHER_FIELDS:
                status = context_receipt.get(field+"_status")
                if not isinstance(status, str) or status not in WEATHER_STATES:
                    code = "STATUS_MISSING_OR_UNKNOWN"
                elif status == "WEATHER_OBSERVED_CONSUMED":
                    code = "CONSUMPTION_UNVERIFIED"
                elif status == "WEATHER_OBSERVED_NOT_CONSUMED":
                    code = "OBSERVED_NOT_CONSUMED"
                else:
                    code = status
                add("NFL_"+field.upper()+"_"+code, "WARN", field=field)
    if row["league"] == "CBB":
        reversal = context_receipt.get("orientation_reversed")
        if type(reversal) is not bool:
            add("CBB_ORIENTATION_UNVERIFIED")
        elif reversal:
            add("CBB_UNVERIFIED_NEUTRAL_REVERSAL", status="HOLD")
    return alerts

def _implied(price):
    if type(price) is not int or abs(price) < 100:
        raise ValueError("INVALID_AMERICAN_PRICE")
    return -price/(-price+100) if price < 0 else 100/(price+100)

def _contract_rows(fc, contracts):
    """Use native PMF outputs; conditional decisive comparison on refund contracts."""
    for product, sides in (("winner", {"home","away"}), ("margin", {"home","away"}), ("total", {"over","under"})):
        pair = [c for c in contracts if c["product"] == product]
        if not pair:
            continue
        if len(pair) != 2 or {c["side"] for c in pair} != sides:
            raise ValueError("PAIR_NOT_UNIQUE")
        a,b = pair
        for c in pair:
            if not all(valid_prob(c[k]) for k in ("win","push","loss")) or not math.isclose(
                math.fsum(c[k] for k in ("win","push","loss")),1,rel_tol=0,abs_tol=1e-10
            ):
                raise ValueError("INVALID_SETTLEMENT_PROBABILITIES")
        if any(not math.isclose(a[x],b[y],rel_tol=0,abs_tol=1e-10) for x,y in (
            ("win","loss"),("loss","win"),("push","push")
        )):
            raise ValueError("SETTLEMENT_COMPLEMENT_MISMATCH")
        if product == "winner":
            if a["line"] is not None or b["line"] is not None or a["push"] != 0:
                raise ValueError("WINNER_CONTRACT_INVALID")
        elif not all(valid_number(c["line"]) for c in pair) or (
            a["line"] != (-b["line"] if product=="margin" else b["line"])
        ):
            raise ValueError("LINE_COMPLEMENT_MISMATCH")
        prices = [_implied(c["american_price"]) for c in pair]
        for c, implied in zip(pair,prices):
            denom = c["win"]+c["loss"]
            row = dict(event_id=fc["event_id"],league="CBB",product=product,
                       side=c["side"],line=c["line"],period="FULL_GAME",
                       settlement_scope=fc["settlement"],point_total=fc.get("total"),
                       p=c["win"]/denom if denom>0 else None,
                       market=implied/sum(prices))
            row.update({"market_"+k:row[k] for k in ("event_id","product","side","line","period","settlement_scope")})
            yield row

def scan_frozen_cbb(card_path, card_sha, market_path, market_sha, inputs, manifest_sha,
                    reconciliation_inputs=None):
    """Replay the actual native CBB card/attachment schemas from pinned retained bytes."""
    from scripts import cbb_market_and_grades as native
    card=pin_json(card_path,card_sha)
    market=pin_json(market_path,market_sha)
    if (card.get("schema"),card.get("league"),card.get("market_input"),card.get("action_authority")) != (
        "sports.cbb.shadow_card.v1","CBB",False,False
    ) or card["market_input"] is not False or card["action_authority"] is not False:
        raise ValueError("CARD_IDENTITY_OR_AUTHORITY_INVALID")
    if (market.get("schema")!="sports.cbb.market.shadow.v1" or market.get("action_authority") is not False
        or market.get("frozen_parent_sha256")!=card_sha or market.get("date")!=card["date"]):
        raise ValueError("MARKET_PARENT_MISMATCH")
    fc_rows=card["forecasts"]; m_rows=market["rows"]
    byid={r["event_id"]:r for r in m_rows}
    generated=[r for r in fc_rows if r["forecast_status"]=="FORECAST_GENERATED"]
    if (len({r["event_id"] for r in fc_rows})!=len(fc_rows) or
        len(fc_rows)!=card["scheduled"] or len(generated)!=card["forecast_count"] or
        len(byid)!=len(m_rows) or set(byid)!={r["event_id"] for r in generated}):
        raise ValueError("COVERAGE_MISMATCH")
    inputs=Path(inputs)
    manifest=pin_json(inputs/"manifest.json",manifest_sha)
    day=date.fromisoformat(card["date"])
    if manifest.get("date")!=day.strftime("%Y%m%d"):
        raise ValueError("CAPTURE_DATE_MISMATCH")
    cut=instant(card["as_of_utc"]); frozen=instant(card["generated_at_utc"])
    attached=instant(market["created_at_utc"])
    if not cut<=frozen<=attached:
        raise ValueError("ATTACHMENT_CLOCK_INVALID")
    evidence=None
    if reconciliation_inputs is not None:
        evidence=load_evidence(reconciliation_inputs,card["reconciliation_manifest_sha256"],day,cut)
        if evidence["coverage_sha256"]!=card["reconciliation_coverage_sha256"]:
            raise ValueError("RECONCILIATION_COVERAGE_MISMATCH")
    results=[]
    for fc in fc_rows:
        eid=fc["event_id"]; alerts=[]; scanned=0
        def block(code,**detail):
            alerts.append(ScanAlert(eid,"CBB",code,"BLOCK",detail))
        if fc["forecast_status"]!="FORECAST_GENERATED":
            block("FORECAST_MISSING",reason=fc.get("reason"))
        else:
            try:
                deadline=forecast_deadline(card,fc)
                if not attached<deadline:
                    raise ValueError("ATTACHMENT_AT_OR_AFTER_START")
                if fc["settlement"]!=SETTLEMENT:
                    raise ValueError("SETTLEMENT_UNSUPPORTED")
                if evidence is None:
                    block("CONTEXT_RECEIPT_MISSING")
                else:
                    target=fc["model_input_snapshot"]
                    hold,proof=target_gate(target,evidence,frozen)
                    if hold or proof!=fc.get("schedule_reconciliation"):
                        block("CONTEXT_RECONCILIATION_UNVERIFIED",reason=hold)
                    elif evidence["records"][eid].get("ncaa_orientation")!="DIRECT":
                        block("CBB_UNVERIFIED_NEUTRAL_REVERSAL")
                entry=byid[eid]
                if entry.get("status")!="DIAGNOSTIC_RETRIEVAL_TIME_ONLY":
                    block("QUOTE_UNAVAILABLE")
                else:
                    raw,comp,_,receipt=native.capture(inputs,fc,manifest)
                    seen=instant(receipt["retrieved_at_utc"])
                    if not (seen<=cut and timedelta(0)<=cut-seen<=timedelta(hours=6)
                            and seen<deadline and comp["status"]["type"]["state"]=="pre"):
                        raise ValueError("QUOTE_CAPTURE_CHRONOLOGY_INVALID")
                    if (entry.get("source_sha256")!=receipt["sha256"] or
                        entry.get("source_url")!=receipt["url"] or
                        instant(entry["quote_retrieved_at_utc"])!=seen or
                        entry.get("settlement")!=fc["settlement"] or entry.get("book")!="DraftKings"):
                        raise ValueError("QUOTE_RECEIPT_BINDING_MISMATCH")
                    contracts=native.market_rows(raw,fc)
                    if not contracts or contracts!=entry["contracts"]:
                        raise ValueError("EXACT_CONTRACT_REPLAY_MISMATCH")
                    for row in _contract_rows(fc,contracts):
                        alerts.extend(scan_contract(row)); scanned+=1
            except (KeyError,TypeError,ValueError,OSError,OverflowError,IndexError) as exc:
                block("FROZEN_CARD_SCAN_REFUSED",error_type=type(exc).__name__,reason=str(exc))
        results.append(dict(event_id=eid,contracts_scanned=scanned,alerts=[asdict(a) for a in alerts]))
    return dict(schema="sports.cbb.divergence_scan.v1",date=card["date"],
                card_sha256=card_sha,market_sha256=market_sha,source_manifest_sha256=manifest_sha,
                reconciliation_manifest_sha256=card.get("reconciliation_manifest_sha256") if evidence is not None else None,
                comparison_scope="RETAINED_RESEARCH_ONLY_PROVIDER_TICK_UNVERIFIED",
                rows=results,scheduled=len(fc_rows),contracts_scanned=sum(r["contracts_scanned"] for r in results),
                action_authority=False,qualification="NO_PICK",official_units=0.0,
                market_overlay_enabled=False,official_ledger_admitted=False)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("card","market","inputs","output"):
        p.add_argument("--"+arg,type=Path,required=True)
    for arg in ("card-sha","market-sha","manifest-sha"):
        p.add_argument("--"+arg,required=True)
    p.add_argument("--reconciliation-inputs",type=Path)
    a=p.parse_args()
    result=scan_frozen_cbb(a.card,a.card_sha,a.market,a.market_sha,a.inputs,a.manifest_sha,a.reconciliation_inputs)
    raw=(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+"\n").encode()
    with a.output.open("xb") as out:
        out.write(raw)
    print(sha256(raw))

if __name__=="__main__":
    main()
