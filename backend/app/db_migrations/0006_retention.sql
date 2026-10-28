-- Retention: an append-only log authorises the deletion of a long-archived, never-reviewed analysis or a
-- long-removed file. The immutability guards keep refusing every delete that is not in this log.
CREATE TABLE retention_purges (
    item_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('run','batch')),
    purged_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
CREATE TRIGGER retention_purges_no_update BEFORE UPDATE ON retention_purges
    FOR EACH ROW EXECUTE FUNCTION cir_reject('retention log is append-only');
CREATE TRIGGER retention_purges_no_delete BEFORE DELETE ON retention_purges
    FOR EACH ROW EXECUTE FUNCTION cir_reject('retention log is append-only');

-- Reject a delete unless the row's owner (column named by TG_ARGV[1]) is in the retention log.
CREATE OR REPLACE FUNCTION cir_reject_unless_purged() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM retention_purges WHERE item_id = to_jsonb(OLD) ->> TG_ARGV[1]) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION '%', TG_ARGV[0] USING ERRCODE = 'restrict_violation';
END $$;

DROP TRIGGER analysis_run_terminal_delete_guard ON analysis_runs;
CREATE TRIGGER analysis_run_terminal_delete_guard BEFORE DELETE ON analysis_runs
    FOR EACH ROW WHEN (OLD.execution_status IN ('completed','partial','failed'))
    EXECUTE FUNCTION cir_reject_unless_purged('AnalysisRun terminal state is immutable', 'run_id');
DROP TRIGGER analysis_run_result_delete_guard ON analysis_run_results;
CREATE TRIGGER analysis_run_result_delete_guard BEFORE DELETE ON analysis_run_results
    FOR EACH ROW EXECUTE FUNCTION cir_reject_unless_purged('AnalysisRun result is immutable', 'run_id');
DROP TRIGGER analysis_run_views_no_delete ON analysis_run_result_views;
CREATE TRIGGER analysis_run_views_no_delete BEFORE DELETE ON analysis_run_result_views
    FOR EACH ROW EXECUTE FUNCTION cir_reject_unless_purged('AnalysisRun result is immutable', 'run_id');
DROP TRIGGER analysis_run_cases_no_delete ON analysis_run_cases;
CREATE TRIGGER analysis_run_cases_no_delete BEFORE DELETE ON analysis_run_cases
    FOR EACH ROW EXECUTE FUNCTION cir_reject_unless_purged('AnalysisRun result is immutable', 'run_id');
DROP TRIGGER ready_batch_metadata_immutable_delete ON data_batches;
CREATE TRIGGER ready_batch_metadata_immutable_delete BEFORE DELETE ON data_batches
    FOR EACH ROW WHEN (OLD.status IN ('ready','ready_with_warnings'))
    EXECUTE FUNCTION cir_reject_unless_purged('ready batch is immutable', 'batch_id');

CREATE OR REPLACE FUNCTION cir_ready_batch_records_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    target TEXT := CASE WHEN TG_OP = 'INSERT' THEN NEW.batch_id ELSE OLD.batch_id END;
BEGIN
    IF TG_OP = 'DELETE' AND EXISTS (SELECT 1 FROM retention_purges WHERE item_id = OLD.batch_id) THEN
        RETURN OLD;
    END IF;
    IF (SELECT status FROM data_batches WHERE batch_id = target) IN ('ready','ready_with_warnings') THEN
        RAISE EXCEPTION 'ready batch records are immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;
