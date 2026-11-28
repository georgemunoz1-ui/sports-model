"""Actual file-backed SQLite tests, not PostgreSQL claims."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import sqlite3
import threading
import pytest

from models.common.decision_research.repository import SQLiteRepository, RepositoryError


def evaluate_fixture(payload):
    return {"disposition": "RESEARCH_ONLY", "order_authorized": False,
            "value": payload.get("price")}


@pytest.fixture
def repository(tmp_path):
    connection = sqlite3.connect(tmp_path / "research.sqlite", timeout=10)
    connection.execute("PRAGMA journal_mode=WAL")
    repository = SQLiteRepository(connection)
    repository.migrate()
    repository.add_comparison("c1", {"price": Decimal("0.52"), "qualified": False})
    yield repository
    connection.close()


def test_real_session_and_canonical_decimal(repository):
    assert repository.load_context("c1")["price"] == "0.52"
    assert repository.verify_audit()
    result = repository.evaluate("c1", evaluate_fixture, "r1")
    assert result["order_authorized"] is False
    assert repository.checkpoint()["count"] == 1
    assert repository.verify_audit()


def test_idempotency_does_not_reinvoke(repository):
    calls = []
    def evaluator(payload):
        calls.append(payload)
        return evaluate_fixture(payload)
    first = repository.evaluate("c1", evaluator, "r1", evaluator_id="test-evaluator-v1")
    second = repository.evaluate("c1", evaluator, "r1", evaluator_id="test-evaluator-v1")
    assert first == second
    assert len(calls) == 1
    assert repository.checkpoint()["count"] == 1


def test_different_comparison_id_conflicts(repository):
    repository.add_comparison("c2", {"price": "0.52"})
    repository.evaluate("c1", evaluate_fixture, "r1")
    with pytest.raises(RepositoryError, match="IDEMPOTENCY"):
        repository.evaluate("c2", evaluate_fixture, "r1")
    assert repository.checkpoint()["count"] == 1


def test_different_evaluator_identity_conflicts(repository):
    repository.evaluate("c1", evaluate_fixture, "r1", evaluator_id="code-a")
    with pytest.raises(RepositoryError, match="IDEMPOTENCY"):
        repository.evaluate("c1", evaluate_fixture, "r1", evaluator_id="code-b")
    assert repository.verify_audit()


def test_missing_comparison_does_not_append(repository):
    with pytest.raises(KeyError):
        repository.evaluate("absent", evaluate_fixture, "r1")
    assert repository.checkpoint()["count"] == 0
    assert not repository.session.in_transaction


def test_evaluator_failure_rolls_back(repository):
    def evaluator(payload):
        raise RuntimeError("test failure")
    with pytest.raises(RuntimeError, match="test failure"):
        repository.evaluate("c1", evaluator, "r1", evaluator_id="fails-v1")
    assert repository.checkpoint()["count"] == 0
    assert not repository.session.in_transaction


@pytest.mark.parametrize("decision", [
    {"order_authorized": True}, {"order_authorized": 0}, {},
    {"order_authorized": False, "child": {"order_authorized": True}},
    {"order_authorized": False, "children": [{"action_authority": True}]},
    {"order_authorized": False, "wagering_authority": "ON"},
])
def test_authorization_is_rejected_and_rolled_back(repository, decision):
    with pytest.raises(RepositoryError, match="ORDER_AUTHORIZATION"):
        repository.evaluate("c1", lambda _: decision, "r1", evaluator_id="malformed-v1")
    assert repository.checkpoint()["count"] == 0


@pytest.mark.parametrize("payload", [{"p": 0.5}, {"p": float("nan")},
    {"p": Decimal("Infinity")}, {"nested": {1: "invalid key"}}])
def test_noncanonical_payload_rejected_before_write(repository, payload):
    with pytest.raises(RepositoryError):
        repository.add_comparison("bad", payload)
    with pytest.raises(KeyError):
        repository.load_context("bad")


@pytest.mark.parametrize("table", ["decision_research_comparisons", "decision_research_audit"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "REPLACE"])
def test_ordinary_sql_cannot_mutate(repository, table, operation):
    repository.evaluate("c1", evaluate_fixture, "r1")
    session = repository.session
    # The explicit insert-conflict guard must work even if recursive delete
    # triggers are disabled by another connection.
    session.execute("PRAGMA recursive_triggers=OFF")
    rows_before = session.execute(f"SELECT * FROM {table}").fetchall()
    row = rows_before[0]
    if operation == "UPDATE":
        column = "comparison_id" if table.endswith("comparisons") else "request_id"
        sql = f"UPDATE {table} SET {column}={column}"
        args = ()
    elif operation == "DELETE":
        sql = f"DELETE FROM {table}"
        args = ()
    else:
        sql = f"INSERT OR REPLACE INTO {table} VALUES ({','.join('?' for _ in row)})"
        args = row
    with pytest.raises(sqlite3.IntegrityError, match="APPEND_ONLY|AUDIT_CHAIN_CONFLICT"):
        session.execute(sql, args)
    session.rollback()
    assert session.execute(f"SELECT * FROM {table}").fetchall() == rows_before
    assert repository.verify_audit()


def test_active_caller_transaction_is_not_committed_or_rolled_back(repository):
    connection = repository.session
    connection.execute("CREATE TABLE caller_state (value INTEGER)")
    connection.execute("INSERT INTO caller_state VALUES (1)")
    assert connection.in_transaction
    for operation in [lambda: SQLiteRepository(connection), repository.migrate,
                      lambda: repository.add_comparison("c2", {}),
                      lambda: repository.evaluate("c1", evaluate_fixture, "r1"),
                      repository.checkpoint]:
        with pytest.raises(RepositoryError, match="CALLER_TRANSACTION_ACTIVE"):
            operation()
        assert connection.in_transaction
        assert connection.execute("SELECT value FROM caller_state").fetchall() == [(1,)]
    connection.rollback()
    assert connection.execute("SELECT value FROM caller_state").fetchall() == []


def test_corrupted_input_detected_without_new_decision(repository):
    repository.session.execute("DROP TRIGGER decision_research_comparisons_no_update")
    repository.session.execute("UPDATE decision_research_comparisons SET input_json='{}'")
    repository.session.commit()
    assert not repository.verify_audit()
    with pytest.raises(RepositoryError, match="AUDIT_INTEGRITY"):
        repository.evaluate("c1", evaluate_fixture, "r1")
    assert repository.session.execute("SELECT count(*) FROM decision_research_audit").fetchone()[0] == 0


def test_tampered_decision_detected_and_reuse_fails(repository):
    repository.evaluate("c1", evaluate_fixture, "r1")
    repository.session.execute("DROP TRIGGER decision_research_audit_no_update")
    repository.session.execute("UPDATE decision_research_audit SET decision_json=?",
        (json.dumps({"order_authorized": False, "disposition": "BLOCKED"}),))
    repository.session.commit()
    assert not repository.verify_audit()
    with pytest.raises(RepositoryError, match="AUDIT_INTEGRITY"):
        repository.evaluate("c1", evaluate_fixture, "r1")


def test_external_checkpoint_detects_deleted_tail(repository):
    repository.evaluate("c1", evaluate_fixture, "r1")
    checkpoint = repository.checkpoint()
    repository.session.execute("DROP TRIGGER decision_research_audit_no_delete")
    repository.session.execute("DELETE FROM decision_research_audit")
    repository.session.commit()
    assert repository.verify_audit()  # valid empty state, not administrator proof
    assert not repository.verify_audit(expected_head=checkpoint["head"], expected_count=checkpoint["count"])


def test_two_file_backed_writers_serialize_and_dedupe(tmp_path):
    db = tmp_path / "concurrent.sqlite"
    with sqlite3.connect(db) as session:
        repository = SQLiteRepository(session)
        repository.migrate()
        repository.add_comparison("c1", {"price": "0.5"})
    barrier = threading.Barrier(2)
    def worker(index):
        connection = sqlite3.connect(db, timeout=10)
        try:
            repo = SQLiteRepository(connection)
            barrier.wait(timeout=5)
            for i in range(12):
                repo.evaluate("c1", evaluate_fixture, f"writer-{index}-{i}")
            repo.evaluate("c1", evaluate_fixture, "shared")
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(worker, [0, 1]))
    with sqlite3.connect(db) as session:
        repo = SQLiteRepository(session)
        assert repo.verify_audit()
        assert repo.checkpoint()["count"] == 25
        assert session.execute("SELECT count(*) FROM decision_research_audit WHERE request_id='shared'").fetchone() == (1,)


def test_insert_failure_not_reported_as_saved(repository):
    repository.session.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON decision_research_audit BEGIN SELECT RAISE(ABORT,'INJECTED_FAILURE'); END")
    with pytest.raises(sqlite3.IntegrityError, match="INJECTED_FAILURE"):
        repository.evaluate("c1", evaluate_fixture, "r1")
    assert repository.checkpoint()["count"] == 0
    assert not repository.session.in_transaction


def test_invalid_saved_string_can_produce_auditable_block(repository):
    repository.add_comparison("bad", {"price": "NaN"})
    def validating_evaluator(payload):
        return {"disposition": "BLOCKED", "reasons": ["INVALID_PRICE"], "order_authorized": False}
    result = repository.evaluate("bad", validating_evaluator, "bad-request")
    assert result["disposition"] == "BLOCKED"
    assert repository.verify_audit()


@pytest.mark.parametrize("output", [{}, {"order_authorized": None},
    {"order_authorized": "false"}, {"order_authorized": True}])
def test_raw_sql_missing_or_invalid_authority_refused(repository, output):
    input_sha = repository.session.execute("SELECT input_sha256 FROM decision_research_comparisons WHERE comparison_id='c1'").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        repository.session.execute("INSERT INTO decision_research_audit VALUES (?,?,?,?,?,?,?,?,?)",
          (1, "unsafe", "c1", "test", "2026-11-04T00:00:00+00:00", input_sha,
           json.dumps(output), "0" * 64, "1" * 64))
    repository.session.rollback()
    assert repository.checkpoint()["count"] == 0


def test_actual_decision_core_round_trip(repository):
    from models.common.decision_research.engine import decide_payload
    payload = {name: True for name in (
      "identity_valid", "settlement_verified", "state_aligned", "quote_fresh",
      "market_open", "execution_verified", "sufficient_size", "fees_verified",
      "valuation_qualified", "risk_limits_pass")}
    payload.update(dominated_by_executable_alternative=False, wagering_enabled=False,
      price="0.52", quantity=100, total_entry_fee="1.75", expected_payout="0.56",
      required_ev_buffer="0.02", available_quantity=100)
    repository.add_comparison("core", payload)
    result = repository.evaluate("core", decide_payload, "core-request")
    assert result["disposition"] == "ACTION_DISABLED"
    assert result["conservative_net_ev"] == "0.0225"
    assert result["order_authorized"] is False
    assert repository.verify_audit()
