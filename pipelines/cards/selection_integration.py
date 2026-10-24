"""Automatic research-selection sidecars for the real card entrypoints.

The source card remains byte-for-byte unchanged. Legacy identity gaps are
recorded as gaps, not filled with assumed lineage or calibration approvals.
This bridge never fetches outcomes and never enables publication or wagering.
"""
from __future__ import annotations

from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

from pipelines.cards.research_selection import (
    content_hash, seal_forecast, seal_quality_receipt, select_research,
    selector_config_artifact, selector_config_id, target_id, verify_selection_record,
)


SCHEMA = "automatic-research-selection-sidecar-v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def utc(value):
    if not isinstance(value, str):
        raise ValueError("EXPLICIT_TIMESTAMP_REQUIRED")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError("UTC_TIMESTAMP_REQUIRED")
    return stamp


def _digest(value):
    return value if isinstance(value, str) and _SHA.fullmatch(value) else None


def _decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY:" + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("NONFINITE_JSON")))


def _rows(card):
    rows = card.get("forecasts", card.get("events"))
    if not isinstance(rows, list):
        raise ValueError("CARD_FORECAST_ROWS_REQUIRED")
    ids = [row.get("event_id") for row in rows]
    if any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
        raise ValueError("CARD_EVENT_IDENTITIES_NOT_UNIQUE")
    return rows


def _identity(row, *, product=None):
    diagnostics = row.get("diagnostics") or {}
    identity = diagnostics.get("identity_provenance") or {}
    # Observation bindings are deliberately not registered procedure nodes.
    # Neither an absent parent nor an absent calibration stage means 'none'.
    numerical = row.get("numerical_identity") or {}
    semantic = row.get("identity_semantics") == "market_blind_numeric.v2"
    objects = {}
    observed_procedure = None
    if semantic:
        if (numerical.get("identity_sha256") != content_hash({k: v for k, v in numerical.items() if k != "identity_sha256"})
                or numerical.get("event_id") != row["event_id"]
                or numerical.get("model_id") != row.get("model_id")):
            raise ValueError("SEMANTIC_PROCEDURE_NUMERIC_BINDING_MISMATCH")
        components = identity.get("identity_components") or {}
        component_ids = {}
        for kind in ("feature", "calibration"):
            component = components.get(kind)
            if not isinstance(component, dict):
                raise ValueError("SEMANTIC_PROCEDURE_COMPONENT_MISSING:" + kind)
            artifact = {k: v for k, v in component.items() if k != "procedure_id"}
            identifier = content_hash(artifact)
            if (component.get("procedure_id") != identifier
                    or row.get(kind + "_procedure_id") != identifier
                    or numerical.get(kind + "_procedure_id") != identifier):
                raise ValueError("SEMANTIC_PROCEDURE_COMPONENT_HASH_MISMATCH:" + kind)
            objects[identifier] = artifact
            component_ids[kind] = identifier
        fitted = _digest(numerical.get("fitted_state_sha256"))
        if fitted is None:
            raise ValueError("SEMANTIC_FITTED_MODEL_ID_REQUIRED")
        # Execution definitions are stable across event inputs, capture times,
        # display labels and quote metadata. They do not invent registry owners
        # or parent nodes, and carry no qualification or promotion authority.
        observed_procedure = {"schema": "executed-forecast-procedure-v1", "definition": {
            "model_id": row["model_id"], "model_state_id": fitted,
            "feature_semantics_id": component_ids["feature"], "calibration_id": component_ids["calibration"],
            "stochastic_procedure": {k: numerical[k] for k in
                ("semantics", "engine", "draw_count", "numpy_version", "semantic_runtime_sha256")}},
            "lineage_status": "OBSERVED_EXECUTION_NOT_REGISTERED", "validation_status": "NOT_ASSESSED"}
        objects[content_hash(observed_procedure)] = observed_procedure
    binding = {
        "schema": "observed-forecast-procedure-binding-v1",
        "model_id": product.get("model_id") if product else row.get("model_id"),
        "model_artifact_sha256": _digest(numerical.get("fitted_state_sha256")) if semantic else _digest(row.get("model_state_config_hash")),
        "archival_model_state_config_hash": row.get("model_state_config_hash"),
        "numeric_feature_snapshot_sha256": _digest(numerical.get("feature_sha256")) if semantic else None,
        "feature_procedure_id": _digest(row.get("feature_procedure_id") or identity.get("feature_procedure_id")),
        "calibration_procedure_id": _digest(row.get("calibration_procedure_id") or identity.get("calibration_procedure_id")),
        "explicit_forecast_procedure_id": _digest(row.get("forecast_procedure_id") or identity.get("forecast_procedure_id")),
        "declared_forecast_procedure_identity": row.get("forecast_procedure_id") or identity.get("forecast_procedure_id"),
        "identity_semantics": row.get("identity_semantics", "legacy.v1"),
        "code_hashes": diagnostics.get("code_hashes"),
        "distribution_model_id": product.get("model_id") if product else None,
        "lineage_status": "OBSERVATION_ONLY_NOT_REGISTERED_OR_QUALIFIED",
        "observed_execution_procedure_id": content_hash(observed_procedure) if observed_procedure and not product else None,
    }
    blocks = []
    for key, reason in (("model_artifact_sha256", "MODEL_ARTIFACT_ID_UNRESOLVED"),
                        ("feature_procedure_id", "FEATURE_PROCEDURE_ID_UNRESOLVED"),
                        ("calibration_procedure_id", "CALIBRATION_PROCEDURE_ID_UNRESOLVED")):
        if binding[key] is None:
            blocks.append(reason)
    if product:
        blocks.append("DISTRIBUTION_PROCEDURE_LINEAGE_UNRESOLVED")
    return binding, blocks, objects


def _quality_blocks(row, league):
    blocks, notes = [], []
    receipt = (row.get("diagnostics") or {}).get("state_freshness_receipt")
    if receipt:
        blocks.extend(receipt.get("blocking_reasons", []))
        notes.extend(receipt.get("review_notes", []))
    else:
        notes.append("STATE_FRESHNESS_RECEIPT_NOT_PRESENT_IN_PARENT")
    # Existing NHL coefficients learned an embargoed rest proxy. A corrected
    # feature value may only be consumed by a separately fitted child model.
    if league == "nhl" and row.get("model_id") == "nhl.initial_causal_score.research.v1":
        blocks.append("NHL_EMBARGO_REST_CONSTRUCTION_SELECTION_SUSPENDED")
    for warning in row.get("warnings", []):
        notes.append("PARENT_WARNING:" + str(warning))
    return blocks, notes


def build_card_selection(card, *, source_sha256, source_ref, evaluated_at_utc,
                         config=None, registry=None, retrospective=False):
    """Adapt actual preserved fields; no model rerun or source mutation occurs."""
    if not _digest(source_sha256):
        raise ValueError("SOURCE_CARD_SHA256_REQUIRED")
    evaluated = utc(evaluated_at_utc)
    default_policy = config is None
    config = config or {"schema": "research-selector-config-v1", "objective": "unconditional_win",
                        "threshold": .5, "require_quality_receipt": True}
    config_artifact = selector_config_artifact(config)
    source_created = card.get("generated_at_utc", card.get("created_at_utc"))
    if source_created is None or utc(source_created) > evaluated:
        raise ValueError("SOURCE_CREATION_TIME_UNAVAILABLE_OR_FUTURE")
    objects = {content_hash(config_artifact): config_artifact}
    forecasts, decisions, qualities, bindings, opportunities, exclusions = [], [], [], [], [], []
    by_event = {row["event_id"]: row for row in _rows(card)}
    products = {(p["event_id"], p["product"], p["distribution_sha256"]): p
                for p in card.get("products", [])}

    def emit(row, *, product, side, line, probabilities, basis, rules, distribution=None, price=None,
             period="full_game", extra_blocks=()):
        league = str(row.get("league", card.get("league", ""))).lower()
        created = row.get("frozen_at_utc", source_created)
        cutoff = row.get("forecast_cutoff_utc", card.get("as_of_utc", created))
        if utc(cutoff) > utc(created):
            raise ValueError("PARENT_CUTOFF_AFTER_CREATION")
        decision_at = source_created if retrospective else evaluated_at_utc
        binding, blocks, component_objects = _identity(row, product=distribution)
        objects.update(component_objects)
        blocks.extend(extra_blocks)
        if "forecast_cutoff_utc" not in row and "as_of_utc" not in card:
            blocks.append("INFORMATION_CUTOFF_NOT_PRESENT_IN_PARENT_CREATION_UPPER_BOUND_USED")
        binding_id = content_hash(binding)
        objects[binding_id] = binding
        # Explicit qualified identities may be supplied by a later fitted child;
        # observed legacy bindings cannot impersonate registered lineage.
        procedure = binding["observed_execution_procedure_id"] or binding["explicit_forecast_procedure_id"] or binding_id
        snapshot = binding["numeric_feature_snapshot_sha256"] or _digest(row.get("input_snapshot_hash"))
        if snapshot is None:
            snapshot = content_hash({"source_card_sha256": source_sha256, "event_id": row["event_id"],
                                     "source_row": row})
            blocks.append("MODEL_INPUT_SNAPSHOT_ID_UNRESOLVED")
        target = {"event_id": row["event_id"], "league": league, "product": product,
                  "period": period, "side": side, "line": line,
                  "settlement_rules_id": rules, "starts_at_utc": row["start_time_utc"]}
        sealed = seal_forecast({"schema": "research-forecast-v1", "procedure_id": procedure,
            "input_snapshot_sha256": snapshot, "target": target, "probabilities": probabilities,
            "probability_basis": basis, "forecast_cutoff_utc": cutoff, "forecast_created_at_utc": created})
        event_blocks, notes = _quality_blocks(row, league)
        blocks.extend(event_blocks)
        if default_policy:
            blocks.append("AUTOMATIC_DIAGNOSTIC_POLICY_NOT_PREREGISTERED")
        if not (binding["explicit_forecast_procedure_id"] or binding["observed_execution_procedure_id"]):
            blocks.append("REGISTERED_PROCEDURE_LINEAGE_UNRESOLVED")
        elif binding["observed_execution_procedure_id"]:
            notes.append("COMPLETE_EXECUTION_IDENTITY_OBSERVED; REGISTRY_QUALIFICATION_STILL_REQUIRED")
        quality = seal_quality_receipt({"forecast_id": sealed["forecast_id"],
            "input_snapshot_sha256": snapshot, "created_at_utc": decision_at,
            "blocking_reasons": sorted(set(blocks)), "review_notes": sorted(set(notes))})
        result = select_research(sealed, config, decision_at_utc=decision_at,
            replay_at_utc=evaluated_at_utc if retrospective else None,
            registry=registry, quality_receipt=quality, price=price(target) if price else None)
        verify_selection_record(result)
        forecasts.append(sealed); decisions.append(result); qualities.append(quality)
        bindings.append({"forecast_id": sealed["forecast_id"], "procedure_binding_id": binding_id,
                         "forecast_procedure_id": procedure,
                         "identity_registration_status": "OBSERVED_NOT_REGISTERED" if binding["observed_execution_procedure_id"] else "NOT_ASSERTED_BY_ADAPTER",
                         "fitted_state_id": binding["model_artifact_sha256"],
                         "feature_procedure_id": binding["feature_procedure_id"],
                         "calibration_procedure_id": binding["calibration_procedure_id"],
                         "selector_config_id": selector_config_id(config),
                         "source_row_sha256": content_hash(row),
                         "distribution_sha256": distribution.get("distribution_sha256") if distribution else None})
        opportunities.append({"event_id": row["event_id"], "target_id": result["target_id"],
                              "slate_id": str(card.get("card_date", card.get("date", created[:10]))),
                              "decision_id": result["decision_id"]})

    for row in by_event.values():
        league = str(row.get("league", card.get("league", ""))).lower()
        if row.get("forecast_status") != "FORECAST_GENERATED":
            exclusions.append({"event_id": row["event_id"], "reason": "NO_PARENT_FORECAST", "status": row.get("forecast_status")})
            emit(row, product="winner", side="home", line=None,
                 probabilities={"win": None, "loss": None, "push": None, "void": None}, basis="unresolved",
                 rules="UNFORECASTED_HOME_WIN_OPPORTUNITY_v1",
                 extra_blocks=["NO_PARENT_FORECAST", "NULL_PLACEHOLDER_NOT_A_GENERATED_FORECAST"])
            continue
        side = ("home" if row.get("model_winner") == row.get("home_team") else
                "away" if row.get("model_winner") == row.get("away_team") else
                "draw" if league == "mls" and row.get("model_winner") == "Draw" else None)
        if side is None:
            exclusions.append({"event_id": row["event_id"], "reason": "WINNER_ORIENTATION_UNRESOLVED"})
            emit(row, product="winner", side="home", line=None,
                 probabilities={"win": None, "loss": None, "push": None, "void": None}, basis="unresolved",
                 rules="UNFORECASTED_HOME_WIN_OPPORTUNITY_v1", extra_blocks=["WINNER_ORIENTATION_UNRESOLVED"])
            continue
        p = row.get("model_p")
        if league == "mls":
            diagnostic = row.get("diagnostics") or {}
            order, mass = diagnostic.get("outcome_order"), diagnostic.get("analytic_probabilities")
            if order == ["away", "draw", "home"] and isinstance(mass, list) and len(mass) == 3:
                if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in mass)
                        or not math.isclose(sum(mass), 1., rel_tol=0., abs_tol=1e-9)):
                    raise ValueError("MLS_THREE_WAY_PROBABILITY_MASS_INVALID")
                probability = mass[order.index(side)]
                if probability != p:
                    raise ValueError("MLS_WINNER_PROBABILITY_BINDING_MISMATCH")
                emit(row, product="winner", side=side, line=None,
                     probabilities={"win": probability, "loss": sum(v for i, v in enumerate(mass) if i != order.index(side)), "push": 0., "void": 0.},
                     basis="unconditional_win", rules="REGULATION_90_1X2_DRAW_IS_SEPARATE_OUTCOME_v1", period="regulation_90")
            else:
                emit(row, product="winner", side=side, line=None,
                     probabilities={"win": p, "loss": None, "push": None, "void": None}, basis="unresolved",
                     rules="MLS_SETTLEMENT_UNRESOLVED_v1", period="regulation_90", extra_blocks=["MLS_THREE_WAY_MASS_UNRESOLVED"])
            continue
        # The NFL fitted binary head excludes ties. Do not silently convert its
        # conditional probability into an unconditional winning settlement.
        basis = "conditional_decisive" if league == "nfl" else "unconditional_win"
        probabilities = row.get("winner_settlement_probabilities")
        if probabilities is None:
            probabilities = {"win": p, "loss": 1-p if p is not None else None, "push": 0., "void": 0.}
        else:
            basis = row.get("winner_probability_basis", "unresolved")
        emit(row, product="winner", side=side, line=None, probabilities=probabilities, basis=basis,
             rules="full_game_winner_tie_push_v1")

    seen_targets = set()
    for quote in card.get("quotes", []):
        row = by_event.get(quote.get("event_id"))
        if row is None:
            raise ValueError("QUOTE_EVENT_OUTSIDE_CARD")
        key = (quote["event_id"], quote["product"], quote["distribution_sha256"])
        distribution = products.get(key)
        mass = quote.get("model_probabilities") or {}
        if distribution is None or quote["product"] not in {"margin", "total"}:
            exclusions.append({"event_id": row["event_id"], "reason": "EXACT_DISTRIBUTION_BINDING_UNRESOLVED"})
            continue
        if mass.get("half_win", 0) or mass.get("half_loss", 0):
            exclusions.append({"event_id": row["event_id"], "reason": "SPLIT_SETTLEMENT_NOT_SUPPORTED"})
            continue
        identity = (row["event_id"], quote["product"], quote["side"], quote["line"], quote["settlement"])
        if identity in seen_targets:
            continue  # One selection opportunity, irrespective of quote count.
        seen_targets.add(identity)
        # Quote timing remains downstream diagnostic metadata. It never affects
        # which raw contract probability is preserved or qualifies a procedure.
        def price(target, quote=quote):
            if quote.get("decimal_odds") is None or quote.get("retrieved_at_utc") is None:
                return None
            return {"target_id": target_id(target), "decimal_odds": quote["decimal_odds"],
                    "quoted_at_utc": quote["retrieved_at_utc"]}
        emit(row, product="spread" if quote["product"] == "margin" else "total",
             side=quote["side"].lower(), line=quote["line"],
             probabilities={"win": mass.get("win"), "loss": mass.get("loss"), "push": mass.get("push"), "void": 0.},
             basis="unconditional_win", rules=quote["settlement"] + "_single_stake_refund_v1",
             distribution=distribution, price=price)
    report = {"schema": SCHEMA, "created_at_utc": evaluated_at_utc,
        "execution_mode": "RETROSPECTIVE_DIAGNOSTIC" if retrospective else "UNREGISTERED_RESEARCH",
        "evidence_scope": "DISCOVERY" if retrospective else "SHADOW",
        "source_card": {"path": str(source_ref), "sha256": source_sha256, "created_at_utc": source_created},
        "config": config, "selector_config_id": selector_config_id(config),
        "forecasts": forecasts, "decisions": decisions, "quality_receipts": qualities,
        "procedure_bindings": bindings, "objects": objects, "population": opportunities,
        "adapter_exclusions": exclusions, "decision_counts": dict(Counter(d["decision_class"] for d in decisions)),
        "event_count": len(by_event), "opportunity_count": len(decisions),
        "unsupported_products": "Products without exact source contract probabilities are not invented.",
        "prospective_registration_verified": False, "publication_allowed": False,
        "action_authority": False, "wagering_status": "OFF"}
    report["sidecar_id"] = content_hash(report)
    return report


def verify_sidecar(report, *, source_card_sha256=None):
    if report.get("schema") != SCHEMA:
        raise ValueError("SELECTION_SIDECAR_SCHEMA")
    if content_hash({k: v for k, v in report.items() if k != "sidecar_id"}) != report.get("sidecar_id"):
        raise ValueError("SELECTION_SIDECAR_HASH_MISMATCH")
    if source_card_sha256 and report["source_card"]["sha256"] != source_card_sha256:
        raise ValueError("SELECTION_SOURCE_CARD_MISMATCH")
    for decision in report["decisions"]:
        verify_selection_record(decision)
    if report.get("publication_allowed") is not False or report.get("wagering_status") != "OFF":
        raise ValueError("SELECTION_AUTHORITY_FIREWALL")


def settle_target(target, home_score, away_score, *, score_period=None):
    """Exact settlement arithmetic; caller authenticates final score evidence.

    Regulation contracts require an explicit verified score period. A final
    after extra time or penalties cannot silently settle a 90-minute target.
    """
    if any(isinstance(s, bool) or not isinstance(s, int) or s < 0 for s in (home_score, away_score)):
        raise ValueError("NONNEGATIVE_INTEGER_FINAL_SCORES_REQUIRED")
    product, side, line = target["product"], target["side"], target["line"]
    if target["period"] == "regulation_90":
        if score_period not in {"REGULATION_90", "regulation_90"}:
            raise ValueError("VERIFIED_REGULATION_90_SCORE_PERIOD_REQUIRED")
        if (target["league"] != "mls" or product != "winner" or line is not None
                or target["settlement_rules_id"] != "REGULATION_90_1X2_DRAW_IS_SEPARATE_OUTCOME_v1"
                or side not in {"home", "away", "draw"}):
            raise ValueError("UNSUPPORTED_EXACT_SETTLEMENT_RULES")
        actual = "home" if home_score > away_score else "away" if away_score > home_score else "draw"
        return "WIN" if side == actual else "LOSS"
    if target["period"] != "full_game" or score_period not in {None, "FULL_GAME", "full_game"}:
        raise ValueError("UNSUPPORTED_SETTLEMENT_PERIOD")
    if product == "winner" and target["settlement_rules_id"] == "full_game_winner_tie_push_v1":
        delta = home_score-away_score if side == "home" else away_score-home_score
    elif product == "spread" and target["settlement_rules_id"] in {"FULL_GAME_OT_single_stake_refund_v1", "FULL_GAME_OT_SO_single_stake_refund_v1", "FULL_GAME_OT_SO_PLUS_ONE_single_stake_refund_v1"}:
        delta = (home_score-away_score if side == "home" else away_score-home_score) + line
    elif product == "total" and target["settlement_rules_id"] in {"FULL_GAME_OT_single_stake_refund_v1", "FULL_GAME_OT_SO_single_stake_refund_v1", "FULL_GAME_OT_SO_PLUS_ONE_single_stake_refund_v1"}:
        delta = (home_score+away_score-line) * (1 if side == "over" else -1)
    else:
        raise ValueError("UNSUPPORTED_EXACT_SETTLEMENT_RULES")
    return "WIN" if delta > 0 else "LOSS" if delta < 0 else "PUSH"


def write_card_selection(source_path, output_dir, *, config=None, registry=None,
                         retrospective=False, evaluated_at_utc=None):
    """Write once into a new directory, then verify original source bytes."""
    source_path, output = Path(source_path).resolve(), Path(output_dir)
    if output.exists() or output.is_symlink():
        raise ValueError("SELECTION_OUTPUT_DIRECTORY_ALREADY_EXISTS")
    raw = source_path.read_bytes()
    created = evaluated_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    report = build_card_selection(_decode(raw), source_sha256=hashlib.sha256(raw).hexdigest(),
        source_ref=source_path, evaluated_at_utc=created, config=config, registry=registry,
        retrospective=retrospective)
    output.mkdir(parents=True, exist_ok=False)
    data = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with (output / "decisions.json").open("xb") as stream:
        stream.write(data)
    if source_path.read_bytes() != raw:
        raise ValueError("SOURCE_CHANGED_DURING_SELECTION_INTEGRATION")
    receipt = {"schema": "selection-integration-execution-receipt-v1", "created_at_utc": created,
        "source_sha256": report["source_card"]["sha256"], "sidecar_id": report["sidecar_id"],
        "decisions_sha256": hashlib.sha256(data).hexdigest(),
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "original_source_unchanged": True, "complete": True, "publication_allowed": False}
    with (output / "execution_receipt.json").open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
    return report


def nfl_selection_card(bundle, created_at_utc):
    """Bridge the NFL runner's actual winner head, retaining conditional basis."""
    # Sidecar warnings must never mutate the already persisted parent bundle.
    bundle = copy.deepcopy(bundle)
    from pipelines.cards.distribution_research import nfl_card
    if bundle.get("mode") == "live":
        event = bundle["event"]
        card = {"league": "NFL", "as_of_utc": bundle["cutoff_utc"], "generated_at_utc": created_at_utc,
            "parent_bundle_sha256": content_hash(bundle), "forecasts": [{
                **event, "model_id": bundle["model_id"], "forecast_status": "FORECAST_GENERATED",
                "input_snapshot_hash": content_hash(bundle.get("features", {})),
                "model_state_config_hash": bundle.get("model_artifact_sha256"),
                "diagnostics": bundle, "warnings": ["LIVE_FORECAST_NOT_PREGAME_SELECTION"]}]}
    else:
        card = nfl_card(bundle, created_at_utc)
    row = card["forecasts"][0]
    p_home = bundle.get("prediction", {}).get("home_win")
    if p_home is None:
        row.update(model_winner=None, model_p=None)
        row.setdefault("warnings", []).append("WINNER_HEAD_UNAVAILABLE")
        return card
    home = p_home >= .5
    row.update(model_winner=row["home_team"] if home else row["away_team"],
               model_p=p_home if home else 1-p_home, identity_semantics=bundle.get("identity_semantics", "legacy.v1"),
               forecast_procedure_id=bundle.get("forecast_procedure_id"),
               feature_procedure_id=bundle.get("feature_procedure_id"),
               calibration_procedure_id=bundle.get("calibration_procedure_id"))
    return card
