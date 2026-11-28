-- CANDIDATE ONLY: not executed on PostgreSQL and not production schema mapping.
-- Uses a new namespace. Apply only to an explicitly disposable test database.
-- SQLite migration tests do not validate this PostgreSQL migration.
-- No production account, credential, order or allocation table is introduced.
BEGIN;
CREATE SCHEMA decision_research_candidate;
CREATE TABLE decision_research_candidate.comparisons (
 comparison_id TEXT PRIMARY KEY CHECK(length(trim(comparison_id)) > 0),
 input_payload JSONB NOT NULL CHECK(jsonb_typeof(input_payload) = 'object'),
 input_sha256 TEXT NOT NULL CHECK(input_sha256 ~ '^[0-9a-f]{64}$'),
 created_at_utc TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(comparison_id,input_sha256)
);
CREATE TABLE decision_research_candidate.audit (
 sequence BIGINT PRIMARY KEY CHECK(sequence > 0),
 request_id TEXT UNIQUE NOT NULL CHECK(length(trim(request_id)) > 0),
 comparison_id TEXT NOT NULL,
 evaluator_id TEXT NOT NULL CHECK(length(trim(evaluator_id)) > 0),
 created_at_utc TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 input_sha256 TEXT NOT NULL CHECK(input_sha256 ~ '^[0-9a-f]{64}$'),
 decision_payload JSONB NOT NULL CHECK(jsonb_typeof(decision_payload) = 'object')
  CHECK(COALESCE(decision_payload->'order_authorized' = 'false'::jsonb, FALSE)),
 previous_hash TEXT NOT NULL CHECK(previous_hash ~ '^[0-9a-f]{64}$'),
 record_hash TEXT NOT NULL CHECK(record_hash ~ '^[0-9a-f]{64}$'),
 FOREIGN KEY(comparison_id,input_sha256)
  REFERENCES decision_research_candidate.comparisons(comparison_id,input_sha256)
);
CREATE FUNCTION decision_research_candidate.reject_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'APPEND_ONLY_RESEARCH_EVIDENCE'; END;
$$;
CREATE TRIGGER comparisons_append_only BEFORE UPDATE OR DELETE
 ON decision_research_candidate.comparisons FOR EACH ROW
 EXECUTE FUNCTION decision_research_candidate.reject_mutation();
CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE
 ON decision_research_candidate.audit FOR EACH ROW
 EXECUTE FUNCTION decision_research_candidate.reject_mutation();
CREATE TRIGGER comparisons_no_truncate BEFORE TRUNCATE
 ON decision_research_candidate.comparisons FOR EACH STATEMENT
 EXECUTE FUNCTION decision_research_candidate.reject_mutation();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE
 ON decision_research_candidate.audit FOR EACH STATEMENT
 EXECUTE FUNCTION decision_research_candidate.reject_mutation();
-- No adapter is deployed for this candidate. Transaction serialization, exact
-- canonical JSON hashing, full recursive authority validation, writer-clock
-- receipt binding, idempotency reuse, chain verification, migration rollback and
-- concurrent PostgreSQL writers remain mandatory actual integration tests.
-- Hash values are structural bindings, not database authentication/qualification.
-- A superuser can bypass triggers; an independently retained checkpoint and
-- restricted runtime role are required for any stronger retention claim.
COMMIT;
