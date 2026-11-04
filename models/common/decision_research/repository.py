"""Transaction-owning, append-only SQLite research decisions.

This is local research persistence, not a mapping to a production database.
The caller supplies an evaluator; flags in a saved payload are not authenticated
source evidence. All persisted results must explicitly prohibit orders. Hash
chains detect edits relative to a retained checkpoint; a database administrator
can drop triggers or rewrite both data and hashes. Retain checkpoints externally.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import inspect
import json
import logging
import sqlite3
from typing import Any, Callable

LOG = logging.getLogger(__name__)
ZERO_HASH = "0" * 64


class RepositoryError(ValueError):
    """The research persistence contract was not met."""


def _json_value(value: Any) -> Any:
    if value is None or type(value) in (str, bool, int):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise RepositoryError("Non-finite Decimal cannot be persisted")
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict) and all(type(k) is str for k in value):
        return {key: _json_value(item) for key, item in value.items()}
    raise RepositoryError("Use JSON values and decimal strings; floats are forbidden")


def canonical_json(value: Any) -> str:
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _forbid_orders(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"order_authorized", "action_authority", "execution_authorized", "allow_order_execution"} and item is not False:
                raise RepositoryError("ORDER_AUTHORIZATION_FORBIDDEN")
            if key == "wagering_authority" and item != "OFF":
                raise RepositoryError("ORDER_AUTHORIZATION_FORBIDDEN")
            _forbid_orders(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _forbid_orders(item)


def _identifier(value: Any, label: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > 1024:
        raise RepositoryError(f"{label} must be a nonempty bounded string")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _evaluator_identity(evaluator: Callable, evaluator_id: str | None) -> str:
    """An explicit full code/config digest is preferred at the integration edge.

    Automatic identity binds this function's source, defaults and closure values,
    not all transitive dependencies or external state. Opaque callables must have
    an explicit reviewed identity; the repository cannot attest to that review.
    """
    if evaluator_id is not None:
        return _identifier(evaluator_id, "evaluator_id")
    try:
        source = inspect.getsource(evaluator)
        closure = [cell.cell_contents for cell in (evaluator.__closure__ or ())]
        binding = canonical_json({"source": source, "defaults": evaluator.__defaults__,
                                  "kwdefaults": evaluator.__kwdefaults__, "closure": closure})
        return f"{evaluator.__module__}.{evaluator.__qualname__}:{digest(binding)}"
    except (AttributeError, OSError, TypeError, RepositoryError) as exc:
        raise RepositoryError("EVALUATOR_ID_REQUIRED: supply a code/config binding") from exc


_SCHEMA = """
CREATE TABLE IF NOT EXISTS decision_research_comparisons (
 comparison_id TEXT PRIMARY KEY NOT NULL,
 input_json TEXT NOT NULL CHECK(json_valid(input_json)),
 input_sha256 TEXT NOT NULL CHECK(length(input_sha256)=64),
 created_at_utc TEXT NOT NULL,
 UNIQUE(comparison_id,input_sha256)
);
CREATE TABLE IF NOT EXISTS decision_research_audit (
 sequence INTEGER PRIMARY KEY CHECK(sequence>0),
 request_id TEXT UNIQUE NOT NULL,
 comparison_id TEXT NOT NULL,
 evaluator_id TEXT NOT NULL,
 created_at_utc TEXT NOT NULL,
 input_sha256 TEXT NOT NULL,
 decision_json TEXT NOT NULL CHECK(json_valid(decision_json))
  CHECK(json_type(decision_json,'$.order_authorized') IS 'false'
    AND json_extract(decision_json,'$.order_authorized')=0),
 previous_hash TEXT NOT NULL CHECK(length(previous_hash)=64),
 record_hash TEXT NOT NULL CHECK(length(record_hash)=64),
 FOREIGN KEY(comparison_id,input_sha256)
  REFERENCES decision_research_comparisons(comparison_id,input_sha256)
);
CREATE TRIGGER IF NOT EXISTS decision_research_comparisons_no_update
 BEFORE UPDATE ON decision_research_comparisons BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER IF NOT EXISTS decision_research_comparisons_no_delete
 BEFORE DELETE ON decision_research_comparisons BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER IF NOT EXISTS decision_research_comparisons_no_replace
 BEFORE INSERT ON decision_research_comparisons
 WHEN EXISTS(SELECT 1 FROM decision_research_comparisons WHERE comparison_id=NEW.comparison_id)
 BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_ID_CONFLICT'); END;
CREATE TRIGGER IF NOT EXISTS decision_research_audit_no_update
 BEFORE UPDATE ON decision_research_audit BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER IF NOT EXISTS decision_research_audit_no_delete
 BEFORE DELETE ON decision_research_audit BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER IF NOT EXISTS decision_research_audit_no_replace
 BEFORE INSERT ON decision_research_audit
 WHEN EXISTS(SELECT 1 FROM decision_research_audit
  WHERE sequence=NEW.sequence OR request_id=NEW.request_id)
 BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_ID_CONFLICT'); END;
CREATE TRIGGER IF NOT EXISTS decision_research_audit_chain
 BEFORE INSERT ON decision_research_audit
 WHEN NEW.sequence != COALESCE((SELECT MAX(sequence)+1 FROM decision_research_audit),1)
 OR NEW.previous_hash != COALESCE((SELECT record_hash FROM decision_research_audit
  ORDER BY sequence DESC LIMIT 1),'0000000000000000000000000000000000000000000000000000000000000000')
 BEGIN SELECT RAISE(ABORT,'AUDIT_CHAIN_CONFLICT'); END;
"""


class SQLiteRepository:
    """Own each write transaction; never commit or roll back caller work."""

    def __init__(self, session: sqlite3.Connection):
        if not isinstance(session, sqlite3.Connection):
            raise TypeError("session must be an actual sqlite3.Connection")
        if session.in_transaction:
            raise RepositoryError("CALLER_TRANSACTION_ACTIVE")
        self.session = session
        session.execute("PRAGMA foreign_keys=ON")
        session.execute("PRAGMA recursive_triggers=ON")

    def _begin(self) -> None:
        if self.session.in_transaction:
            raise RepositoryError("CALLER_TRANSACTION_ACTIVE")
        self.session.execute("BEGIN IMMEDIATE")

    def migrate(self) -> None:
        if self.session.in_transaction:
            raise RepositoryError("CALLER_TRANSACTION_ACTIVE")
        try:
            # executescript can implicitly commit: check caller ownership first.
            self.session.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA + "\nCOMMIT;")
        except Exception:
            if self.session.in_transaction:
                self.session.rollback()
            raise

    def add_comparison(self, comparison_id: str, payload: dict) -> str:
        comparison_id = _identifier(comparison_id, "comparison_id")
        if not isinstance(payload, dict):
            raise RepositoryError("comparison payload must be an object")
        serialized = canonical_json(payload)
        sha = digest(serialized)
        self._begin()
        try:
            self.session.execute("INSERT INTO decision_research_comparisons VALUES (?,?,?,?)",
                                 (comparison_id, serialized, sha, _utc_now()))
            self.session.commit()
            return sha
        except Exception:
            self.session.rollback()
            raise

    def load_context(self, comparison_id: str) -> dict:
        comparison_id = _identifier(comparison_id, "comparison_id")
        row = self.session.execute("SELECT input_json,input_sha256 FROM decision_research_comparisons WHERE comparison_id=?",
                                   (comparison_id,)).fetchone()
        if row is None:
            raise KeyError(comparison_id)
        serialized, sha = row
        parsed = json.loads(serialized)
        if not isinstance(parsed, dict) or digest(serialized) != sha or canonical_json(parsed) != serialized:
            raise RepositoryError("INPUT_HASH_MISMATCH")
        return parsed

    def evaluate(self, comparison_id: str, evaluator: Callable[[dict], dict],
                 request_id: str, *, evaluator_id: str | None = None) -> dict:
        comparison_id = _identifier(comparison_id, "comparison_id")
        request_id = _identifier(request_id, "request_id")
        identity = _evaluator_identity(evaluator, evaluator_id)
        self._begin()
        try:
            # Validate the complete existing chain before reuse or append.
            if not self.verify_audit():
                raise RepositoryError("AUDIT_INTEGRITY_FAILURE")
            payload = self.load_context(comparison_id)
            input_sha = digest(canonical_json(payload))
            existing = self.session.execute(
                "SELECT comparison_id,input_sha256,evaluator_id,decision_json FROM decision_research_audit WHERE request_id=?",
                (request_id,)).fetchone()
            if existing is not None:
                if existing[:3] != (comparison_id, input_sha, identity):
                    raise RepositoryError("IDEMPOTENCY_KEY_CONFLICT")
                self.session.commit()
                return json.loads(existing[3])
            decision = evaluator(payload)
            if not isinstance(decision, dict) or decision.get("order_authorized") is not False:
                raise RepositoryError("ORDER_AUTHORIZATION_FORBIDDEN")
            _forbid_orders(decision)
            serialized = canonical_json(decision)
            head = self.session.execute("SELECT sequence,record_hash FROM decision_research_audit ORDER BY sequence DESC LIMIT 1").fetchone()
            sequence = head[0] + 1 if head else 1
            previous = head[1] if head else ZERO_HASH
            created = _utc_now()
            record = {"sequence": sequence, "request_id": request_id,
                      "comparison_id": comparison_id, "evaluator_id": identity,
                      "created_at_utc": created, "input_sha256": input_sha,
                      "decision": json.loads(serialized), "previous_hash": previous}
            record_hash = digest(canonical_json(record))
            self.session.execute("INSERT INTO decision_research_audit VALUES (?,?,?,?,?,?,?,?,?)",
                                 (sequence, request_id, comparison_id, identity, created,
                                  input_sha, serialized, previous, record_hash))
            self.session.commit()
        except Exception:
            self.session.rollback()
            LOG.exception("decision_failed", extra={"comparison_id": comparison_id, "request_id": request_id})
            raise
        LOG.info("decision_recorded", extra={"comparison_id": comparison_id, "request_id": request_id})
        return json.loads(serialized)

    def verify_audit(self, *, expected_head: str | None = None,
                     expected_count: int | None = None) -> bool:
        """Check a read snapshot; optional external checkpoint detects truncation.

        Database triggers alone do not protect against an administrator. An empty
        chain is valid unless a retained nonempty checkpoint is supplied.
        """
        owns_read = not self.session.in_transaction
        if owns_read:
            self.session.execute("BEGIN")
        try:
            inputs = {}
            for comparison_id, serialized, sha, created in self.session.execute("SELECT * FROM decision_research_comparisons"):
                parsed = json.loads(serialized)
                if not isinstance(parsed, dict) or digest(serialized) != sha or canonical_json(parsed) != serialized:
                    return False
                if datetime.fromisoformat(created).utcoffset() is None:
                    return False
                inputs[comparison_id] = sha
            previous = ZERO_HASH
            count = 0
            for row in self.session.execute("SELECT * FROM decision_research_audit ORDER BY sequence"):
                seq, request_id, comparison_id, evaluator_id, created, sha, serialized, prior, current = row
                count += 1
                decision = json.loads(serialized)
                if (seq != count or prior != previous or inputs.get(comparison_id) != sha
                    or not isinstance(decision, dict) or decision.get("order_authorized") is not False
                    or canonical_json(decision) != serialized
                    or datetime.fromisoformat(created).utcoffset() is None):
                    return False
                _forbid_orders(decision)
                record = {"sequence": seq, "request_id": request_id,
                          "comparison_id": comparison_id, "evaluator_id": evaluator_id,
                          "created_at_utc": created, "input_sha256": sha,
                          "decision": decision, "previous_hash": prior}
                if digest(canonical_json(record)) != current:
                    return False
                previous = current
            return ((expected_head is None or previous == expected_head)
                    and (expected_count is None or count == expected_count))
        except (ValueError, TypeError, sqlite3.DatabaseError):
            return False
        finally:
            if owns_read:
                self.session.rollback()

    def checkpoint(self) -> dict:
        """Export for independent retention; does not itself retain externally."""
        if self.session.in_transaction:
            raise RepositoryError("CALLER_TRANSACTION_ACTIVE")
        self.session.execute("BEGIN")
        try:
            if not self.verify_audit():
                raise RepositoryError("AUDIT_INTEGRITY_FAILURE")
            row = self.session.execute("SELECT sequence,record_hash FROM decision_research_audit ORDER BY sequence DESC LIMIT 1").fetchone()
            return {"count": row[0] if row else 0, "head": row[1] if row else ZERO_HASH,
                    "captured_at_utc": _utc_now(), "external_retention": "NOT_ESTABLISHED"}
        finally:
            self.session.rollback()
