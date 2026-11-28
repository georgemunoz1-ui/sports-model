"""Descriptive tail and interval diagnostics for retained matched laws.

This never fits a distribution, selects a model or qualifies a product. The
population may already have been inspected; results are historical diagnostics.
"""
from __future__ import annotations

import math
import numpy as np

from models.common import discrete_research as D


def summarize(rows):
    if not rows:
        raise ValueError("EMPTY_DIAGNOSTIC_POPULATION")
    ids, scope, intervals, losses, crps, zeros = set(), None, {}, [], [], 0
    mass, actual = {}, {}
    for row in rows:
        law = row["distribution"]
        x, p = D.validate(law)
        current = tuple(law[k] for k in ("league", "product", "settlement", "model_id"))
        if scope is not None and scope != current:
            raise ValueError("MIXED_DIAGNOSTIC_SCOPE")
        scope = current
        eid = law["provenance"]["event_id"]
        if eid in ids:
            raise ValueError("DUPLICATE_DIAGNOSTIC_EVENT")
        ids.add(eid)
        y = D.finite(row["observed"])
        if y != int(y):
            raise ValueError("INTEGER_OBSERVATION_REQUIRED")
        D.source_hash(row["result_source_sha256"])
        if not D.stamp(law["provenance"]["cutoff"]) < D.stamp(row["start_time_utc"]) <= D.stamp(row["result_available_at"]):
            raise ValueError("DIAGNOSTIC_CHRONOLOGY_INVALID")
        score = D.score(law, y)
        crps.append(score["crps"])
        if score["log_loss"] is None:
            zeros += 1
        else:
            losses.append(score["log_loss"])
        cdf = np.cumsum(p)
        for level in (.5, .8, .95):
            alpha = (1 - level) / 2
            lo = x[min(np.searchsorted(cdf, alpha), len(x) - 1)]
            hi = x[min(np.searchsorted(cdf, 1 - alpha), len(x) - 1)]
            record = intervals.setdefault(str(level), {k: [] for k in
                ("covered", "width", "lower_miss", "upper_miss", "lower_probability", "upper_probability")})
            for key, value in {"covered": lo <= y <= hi, "width": hi - lo,
                    "lower_miss": y < lo, "upper_miss": y > hi,
                    "lower_probability": p[x < lo].sum(), "upper_probability": p[x > hi].sum()}.items():
                record[key].append(float(value))
        if law["product"] == "margin":
            keys = (-10, -7, -3, -1, 0, 1, 3, 7, 10)
            for key in keys:
                mass.setdefault(key, []).append(float(p[x == key].sum()))
                actual.setdefault(key, []).append(float(y == key))
    average = lambda values: math.fsum(values) / len(values)
    return {"league": scope[0], "product": scope[1], "settlement": scope[2], "model_id": scope[3],
            "events": len(ids), "event_ids_sha256": D.digest(sorted(ids)), "crps": average(crps),
            "log_loss": None if zeros else average(losses), "zero_probability_outcomes": zeros,
            "log_loss_status": "INFINITE_DUE_TO_ZERO_SUPPORT" if zeros else "FINITE",
            "intervals": {level: {key: average(values) for key, values in fields.items()}
                          for level, fields in intervals.items()},
            "key_margin_mass": [{"margin": key, "mean_probability": average(values),
                                  "observed_frequency": average(actual[key])} for key, values in mass.items()],
            "input_sha256": D.digest(rows), "predictive_validation": "NOT_ASSESSED",
            "analysis_class": "PREVIOUSLY_INSPECTED_HISTORICAL_DESCRIPTIVE", "action_authority": False}


def audit_groups(groups):
    """Require identical events, cutoffs and result bindings across methods."""
    if not groups:
        raise ValueError("EMPTY_DIAGNOSTIC_GROUPS")
    summaries, expected, models = [], None, set()
    for rows in groups:
        summary = summarize(rows)
        if summary["model_id"] in models:
            raise ValueError("DUPLICATE_DIAGNOSTIC_MODEL")
        models.add(summary["model_id"])
        identities = {r["distribution"]["provenance"]["event_id"]:
                      [r["distribution"]["provenance"]["cutoff"], r["observed"],
                       r["result_source_sha256"], r["start_time_utc"], r["result_available_at"],
                       *[r["distribution"][k] for k in ("league", "product", "settlement")]] for r in rows}
        if expected is not None and identities != expected:
            raise ValueError("UNMATCHED_DIAGNOSTIC_POPULATION")
        expected = identities
        summaries.append(summary)
    return {"matched_unique_events": len(expected), "methods": summaries,
            "automatic_promotion": False, "action_authority": False}
