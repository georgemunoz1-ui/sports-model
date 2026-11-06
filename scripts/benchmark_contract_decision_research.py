#!/usr/bin/env python3
"""Local synthetic engineering timing; not production capacity or model evidence."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models.common.decision_research.engine import FLAGS, decide_payload
from models.common.decision_research.repository import SQLiteRepository


def payload(index=0):
    value = {name: True for name in FLAGS}
    value.update(dominated_by_executable_alternative=False, wagering_enabled=False,
                 price="0.52", quantity=100, total_entry_fee="1.75", expected_payout="0.56",
                 available_quantity=100, required_ev_buffer="0.01", synthetic_event_id=f"TEST:{index}")
    return value


def measure(count, call):
    latencies = []
    started = time.perf_counter()
    for index in range(count):
        tick = time.perf_counter()
        result = call(index)
        assert result["order_authorized"] is False
        latencies.append(time.perf_counter() - tick)
    elapsed = time.perf_counter() - started
    return {"evaluations": count, "elapsed_seconds": elapsed, "evaluations_per_second": count / elapsed,
            "latency_median_seconds": statistics.median(latencies),
            "latency_p95_seconds": sorted(latencies)[min(count - 1, int(count * 0.95))]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = {"label": "SYNTHETIC_SINGLE_LOCAL_RUN", "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "pure": [measure(n, lambda i: decide_payload(payload(i))) for n in (1000, 10000)],
              "limits": ["Single process; excludes source capture, venue qualification and production database.",
                         "Synthetic inputs differ by event ID only; no model or predictive validation.",
                         "SQLite validates the entire audit chain before each append; not a capacity claim."]}
    with tempfile.TemporaryDirectory() as tmp, closing(sqlite3.connect(Path(tmp) / "benchmark.sqlite")) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        repo = SQLiteRepository(conn)
        repo.migrate()
        for i in range(100):
            repo.add_comparison(f"comparison-{i}", payload(i))
        report["sqlite_wal"] = measure(100, lambda i: repo.evaluate(f"comparison-{i}", decide_payload, f"request-{i}"))
        assert repo.verify_audit()
        report["audit_count"] = repo.checkpoint()["count"]
    report.update(order_authorized=False, action="OFF", dose=0, postgresql="NOT_RUN")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
