"""Source-bound state and operational-rest diagnostics; never rewrites a fit.

The v1 initial baseline learned an embargoed ``state.last`` proxy.  Operational
rest is a different feature definition and is emitted as a refit candidate only.
Normalized history records must retain when their FINAL status was observed;
an old game date alone does not establish point-in-time availability.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from collections import Counter


REST_SEMANTICS = "initial_causal_score.operational_rest.start_to_start.v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _utc(value):
    if not isinstance(value, str):
        raise ValueError("AWARE_TIMESTAMP_REQUIRED")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("INVALID_TIMESTAMP") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("AWARE_TIMESTAMP_REQUIRED")
    return parsed.astimezone(dt.timezone.utc)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("FINITE_NUMBER_REQUIRED")
    return float(value)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _identity(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("NONEMPTY_ID_REQUIRED")
    return value


def _source(value):
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError("SOURCE_SHA256_REQUIRED")
    return value


def normalize_captured_schedule(raw, *, league, captured_at_utc, source_sha256):
    """Normalize retained ESPN schedule bytes, checking the capture digest.

    This proves byte binding and final status *at capture*, not that historical
    status was available earlier, nor completeness of a provider response.
    Separate source-bound coverage receipts are required by operational_rest.
    Scores are deliberately discarded: this path cannot consume outcomes.
    """
    if not isinstance(raw, bytes):
        raise ValueError("RAW_BYTES_REQUIRED")
    _source(source_sha256)
    if hashlib.sha256(raw).hexdigest() != source_sha256:
        raise ValueError("SOURCE_DIGEST_MISMATCH")
    _utc(captured_at_utc)
    if league not in {"nba", "nhl", "mls"}:
        raise ValueError("LEAGUE_REQUIRED")
    payload = json.loads(raw)
    if not isinstance(payload.get("events"), list):
        raise ValueError("SCHEDULE_EVENTS_REQUIRED")
    rows = []
    for event in payload["events"]:
        competitions = event.get("competitions", [])
        if len(competitions) != 1:
            raise ValueError("SINGLE_COMPETITION_REQUIRED")
        competition = competitions[0]
        sides = {r["homeAway"]: r["team"]["id"] for r in competition["competitors"]}
        if set(sides) != {"home", "away"} or len(competition["competitors"]) != 2:
            raise ValueError("TEAM_SIDE_IDENTITY")
        status = competition.get("status", event.get("status", {})).get("type", {})
        # Completed flags are also used for canceled/forfeit records by some feeds.
        final = status.get("completed") is True and status.get("state") == "post" and status.get("name") in {
            "STATUS_FINAL", "STATUS_FINAL_OT", "STATUS_FINAL_SO", "STATUS_FINAL_PEN"}
        rows.append({"event_id": league.upper() + ":" + str(event["id"]),
                     "home_id": str(sides["home"]), "away_id": str(sides["away"]),
                     "start_time_utc": _utc(event["date"]).isoformat(),
                     "status": "final" if final else "nonfinal",
                     "observed_at_utc": captured_at_utc, "source_sha256": source_sha256})
    return rows


def operational_rest(event, records, *, cutoff_utc, coverage=(), max_capture_age_hours=6):
    """Return start-to-start rest candidates under explicit as-of eligibility.

    ``coverage`` rows are upstream acquisition assertions bound to source bytes:
    team_id, from_utc, through_utc, observed_at_utc, source_sha256, complete=True,
    population='ALL_PLAYED_GAMES'. Regular-season-only history is insufficient
    to establish physical rest around preseason or postseason boundaries.
    They must cover the selected predecessor through a timely capture. This
    routine checks those assertions and binding; it cannot prove the provider
    omitted no game. Missing/incomplete coverage emits null, never a fresh value.
    ``completed_at_utc`` is optional: FINAL observed at capture is sufficient.
    """
    cutoff = _utc(cutoff_utc)
    if _number(max_capture_age_hours) <= 0:
        raise ValueError("POSITIVE_CAPTURE_AGE_POLICY_REQUIRED")
    start = _utc(event["start_time_utc"])
    target_id = _identity(event["event_id"])
    teams = [_identity(event[s + "_id"]) for s in ("home", "away")]
    if start <= cutoff or len(set(teams)) != 2:
        raise ValueError("PREGAME_DISTINCT_TEAMS_REQUIRED")
    eligible = {team: {} for team in teams}
    exclusions = Counter()
    invalid_teams = set()
    source_observations = set()
    for record in records:
        # Malformed data may hide the latest event: fail closed rather than skip it.
        try:
            eid = _identity(record["event_id"])
            members = {_identity(record["home_id"]), _identity(record["away_id"])}
            if len(members) != 2:
                raise ValueError("SELF_MATCH")
            played = _utc(record["start_time_utc"])
            observed = _utc(record["observed_at_utc"])
            _source(record["source_sha256"])
            source_observations.add((record["source_sha256"], observed))
        except (KeyError, TypeError, ValueError):
            exclusions["INVALID_HISTORY_RECORD"] += 1
            invalid_teams.update(teams)
            continue
        if eid == target_id:
            exclusions["CURRENT_EVENT_EXCLUDED"] += 1
            continue
        if record.get("status") != "final":
            exclusions["NONFINAL_EXCLUDED"] += 1
            continue
        if observed > cutoff or played >= cutoff or played >= start:
            exclusions["NOT_AVAILABLE_PREFORECAST"] += 1
            continue
        # Upcoming/nonfinal schedule rows normally have observation < start.
        # Completion ordering is meaningful only for an otherwise eligible final.
        try:
            completed = _utc(record["completed_at_utc"]) if record.get("completed_at_utc") else observed
            if completed < played or observed < completed:
                raise ValueError("INVALID_COMPLETION_ORDER")
        except (TypeError, ValueError):
            exclusions["INVALID_HISTORY_RECORD"] += 1
            invalid_teams.update(members.intersection(teams))
            continue
        if completed > cutoff:
            exclusions["NOT_AVAILABLE_PREFORECAST"] += 1
            continue
        for team in members.intersection(teams):
            prior = eligible[team].get(eid)
            # Duplicate provider copies are harmless only if identity is consistent.
            identity = (played, record["home_id"], record["away_id"])
            if prior and prior[0] != identity:
                invalid_teams.add(team)
                exclusions["CONFLICTING_EVENT_IDENTITY"] += 1
            elif not prior or observed < prior[1]["observed_at_utc_dt"]:
                retained = dict(record, observed_at_utc_dt=observed)
                eligible[team][eid] = (identity, retained)
    per_side = {}
    for side, team in zip(("home", "away"), teams):
        predecessors = list(eligible[team].values())
        latest = max(predecessors, key=lambda x: (x[0][0], x[1]["event_id"])) if predecessors else None
        reasons = []
        if team in invalid_teams:
            reasons.append("HISTORY_INTEGRITY_UNPROVEN")
        if latest is None:
            reasons.append("NO_OBSERVED_PRIOR_FINAL")
        elif sum(row[0][0] == latest[0][0] for row in predecessors) > 1:
            reasons.append("AMBIGUOUS_LATEST_EVENT_IDENTITY")
        valid_coverage = []
        for receipt in coverage:
            if receipt.get("team_id") != team:
                continue
            try:
                observed = _utc(receipt["observed_at_utc"])
                since, through = _utc(receipt["from_utc"]), _utc(receipt["through_utc"])
                sha = _source(receipt["source_sha256"])
                if (receipt.get("complete") is True and receipt.get("population") == "ALL_PLAYED_GAMES"
                        and observed <= cutoff and through <= observed
                        and (sha, observed) in source_observations
                        and (cutoff - through).total_seconds() <= max_capture_age_hours * 3600
                        and latest is not None and since <= latest[0][0]
                        and since <= through and sha in {x[1]["source_sha256"] for x in predecessors}):
                    valid_coverage.append({k: v for k, v in receipt.items()})
            except (KeyError, TypeError, ValueError):
                pass
        if not valid_coverage:
            reasons.append("AS_OF_HISTORY_COVERAGE_UNPROVEN")
        known = not reasons
        previous = latest[1] if latest else None
        raw_days = (start - latest[0][0]).total_seconds() / 86400 if latest else None
        per_side[side] = {"team_id": team, "status": "KNOWN" if known else "UNKNOWN",
                          "rest_start_to_start_days": raw_days if known else None,
                          "candidate_feature_value": min(14.0, raw_days) if known else None,
                          "previous_event_id": previous["event_id"] if previous else None,
                          "previous_start_time_utc": latest[0][0].isoformat() if latest else None,
                          "observed_at_utc": previous["observed_at_utc"] if previous else None,
                          "source_sha256": previous["source_sha256"] if previous else None,
                          "completion_time_basis": "provider_completion" if previous and previous.get("completed_at_utc") else "observed_final_at_capture",
                          "coverage_receipts": valid_coverage, "blocking_reasons": reasons}
    return {"schema": "sports.operational_rest_candidate.v1", "event_id": target_id,
            "cutoff_utc": cutoff.isoformat(), "units": "start_to_start_days_24h",
            "max_capture_age_hours_policy": max_capture_age_hours,
            "coverage_basis": "OBSERVED_FINALS_AT_RETAINED_CAPTURE_NOT_CONTINUOUS_LIVE_TRUTH",
            "feature_semantics_id": REST_SEMANTICS, "per_side": per_side,
            "exclusions": dict(sorted(exclusions.items())), "action_authority": False}


def rebuild_candidate_features(state, event, prior, records, *, cutoff_utc, coverage=(), max_capture_age_hours=6):
    """Executable candidate build; no inference with legacy fitted coefficients."""
    from models.current.baseline import feature
    legacy = feature(state, event, prior)
    rest = operational_rest(event, records, cutoff_utc=cutoff_utc, coverage=coverage, max_capture_age_hours=max_capture_age_hours)
    ready = all(r["status"] == "KNOWN" for r in rest["per_side"].values())
    candidate = dict(legacy) if ready else None
    if ready:
        for side in ("home", "away"):
            candidate[side + "_rest"] = rest["per_side"][side]["candidate_feature_value"]
    return {"schema": "sports.operational_rest_feature_rebuild.v1", "event_id": event["event_id"],
            "feature_semantics_id": REST_SEMANTICS, "legacy_features": legacy,
            "candidate_features": candidate, "candidate_ready": ready, "rest_receipt": rest,
            "state_sha256": _digest(state), "candidate_input_snapshot_hash": _digest(candidate) if ready else None,
            "adoption_status": "REFIT_AND_CHRONOLOGICAL_EVALUATION_REQUIRED", "action_authority": False}


def state_freshness_receipt(package, event, features, *, cutoff_utc, max_state_age_hours=None):
    """Disclose consumed state, not merely when a stale source was re-fetched.

    ``max_state_age_hours`` is an explicitly chosen input policy, not a calibrated
    predictive threshold. None reports ages without asserting a validation floor.
    Rest consistency proves the exact consumed feature, not a causal effect size.
    """
    cutoff, start = _utc(cutoff_utc), _utc(event["start_time_utc"])
    if start <= cutoff:
        raise ValueError("PREGAME_EVENT_REQUIRED")
    if max_state_age_hours is not None and _number(max_state_age_hours) <= 0:
        raise ValueError("POSITIVE_STATE_AGE_POLICY_REQUIRED")
    per_side, reasons = {}, []
    training_cutoff = package.get("training_cutoff_utc")
    if training_cutoff is None:
        reasons.append("TRAINING_CUTOFF_UNKNOWN")
    elif _utc(training_cutoff) > cutoff:
        reasons.append("FIT_NOT_AVAILABLE_PREFORECAST")
    for side in ("home", "away"):
        state = package.get("team_state", {}).get(event[side + "_id"], {})
        raw_last = state.get("last")
        last = _utc(raw_last) if raw_last else None
        age = (cutoff - last).total_seconds() / 3600 if last else None
        expected = min(14.0, max(0.0, (start - last).total_seconds() / 86400)) if last else 14.0
        observed = _number(features[side + "_rest"])
        warnings = []
        if last is None:
            warnings.append("STATE_TIMESTAMP_UNKNOWN_LEGACY_REST_IMPUTED")
        elif last >= cutoff:
            warnings.append("CONSUMED_STATE_NOT_PREFORECAST")
        elif max_state_age_hours is not None and age > max_state_age_hours:
            warnings.append("CONSUMED_STATE_OLDER_THAN_POLICY")
        matched = math.isclose(expected, observed, rel_tol=0, abs_tol=1e-10)
        if not matched:
            warnings.append("REST_FEATURE_STATE_MISMATCH")
        reasons.extend(side.upper() + ":" + warning for warning in warnings)
        per_side[side] = {"team_id": event[side + "_id"], "consumed_state_last_start_utc": raw_last,
                          "state_age_at_cutoff_hours": age, "rest_feature_value": observed,
                          "rest_reconstructed_value": expected, "feature_matches_consumed_state": matched,
                          "rest_basis": "EMBARGOED_FORM_STATE_START_TO_START_CAPPED_14_DAYS",
                          "imputed": last is None, "blocking_reasons": warnings}
    receipt = {"schema": "sports.state_freshness_receipt.v1", "event_id": event["event_id"],
               "model_id": package.get("model_id"), "model_state_config_hash": package.get("model_sha256"),
               "input_snapshot_hash": _digest(features), "cutoff_utc": cutoff.isoformat(),
               "training_cutoff_utc": package.get("training_cutoff_utc"),
               "state_sha256": _digest(package.get("team_state", {})),
               "max_state_age_hours_policy": max_state_age_hours,
               "per_side": per_side, "blocking_reasons": reasons,
               "review_notes": ["CAPTURE_FRESHNESS_DOES_NOT_ESTABLISH_CONSUMED_STATE_FRESHNESS",
                                "NUMERICAL_USE_IS_FEATURE_TRACE_NOT_COUNTERFACTUAL_EFFECT_SIZE"],
               "action_authority": False}
    receipt["receipt_sha256"] = _digest(receipt)
    return receipt
