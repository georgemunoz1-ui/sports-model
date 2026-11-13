"""Static migration checks only; these are NOT PostgreSQL integration tests."""
from pathlib import Path

SQL = (Path(__file__).resolve().parents[1] / "models/common/decision_research/sql/001_postgresql_candidate.sql").read_text()


def test_postgres_candidate_explicitly_undeployed():
    assert "not executed on PostgreSQL" in SQL
    assert "not production schema mapping" in SQL
    assert "CREATE SCHEMA decision_research_candidate;" in SQL


def test_postgres_missing_authority_fails_closed_in_candidate_check():
    assert "CHECK(COALESCE(decision_payload->'order_authorized' = 'false'::jsonb, FALSE))" in SQL


def test_postgres_candidate_covers_truncate_and_row_mutation():
    for table in ("comparisons", "audit"):
        assert f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE" in SQL
        assert f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE" in SQL


def test_postgres_candidate_input_binding_and_transaction_boundaries():
    assert "FOREIGN KEY(comparison_id,input_sha256)" in SQL
    assert "UNIQUE(comparison_id,input_sha256)" in SQL
    assert "BEGIN;" in SQL and SQL.rstrip().endswith("COMMIT;")
