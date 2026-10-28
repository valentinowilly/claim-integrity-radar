-- Automatic permanent deletion was dropped from the product: archived analyses are kept. This restores the
-- immutability guards of 0001 exactly (no delete path at all) and removes the retention log of 0006.
DROP TRIGGER analysis_run_terminal_delete_guard ON analysis_runs;
CREATE TRIGGER analysis_run_terminal_delete_guard BEFORE DELETE ON analysis_runs
    FOR EACH ROW WHEN (OLD.execution_status IN ('completed','partial','failed'))
    EXECUTE FUNCTION cir_reject('AnalysisRun terminal state is immutable');
DROP TRIGGER analysis_run_result_delete_guard ON analysis_run_results;
CREATE TRIGGER analysis_run_result_delete_guard BEFORE DELETE ON analysis_run_results
    FOR EACH ROW EXECUTE FUNCTION cir_reject('AnalysisRun result is immutable');
DROP TRIGGER analysis_run_views_no_delete ON analysis_run_result_views;
CREATE TRIGGER analysis_run_views_no_delete BEFORE DELETE ON analysis_run_result_views
    FOR EACH ROW EXECUTE FUNCTION cir_reject('AnalysisRun result is immutable');
DROP TRIGGER analysis_run_cases_no_delete ON analysis_run_cases;
CREATE TRIGGER analysis_run_cases_no_delete BEFORE DELETE ON analysis_run_cases
    FOR EACH ROW EXECUTE FUNCTION cir_reject('AnalysisRun result is immutable');
DROP TRIGGER ready_batch_metadata_immutable_delete ON data_batches;
CREATE TRIGGER ready_batch_metadata_immutable_delete BEFORE DELETE ON data_batches
    FOR EACH ROW WHEN (OLD.status IN ('ready','ready_with_warnings'))
    EXECUTE FUNCTION cir_reject('ready batch is immutable');

CREATE OR REPLACE FUNCTION cir_ready_batch_records_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    target TEXT := CASE WHEN TG_OP = 'INSERT' THEN NEW.batch_id ELSE OLD.batch_id END;
BEGIN
    IF (SELECT status FROM data_batches WHERE batch_id = target) IN ('ready','ready_with_warnings') THEN
        RAISE EXCEPTION 'ready batch records are immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;

DROP FUNCTION cir_reject_unless_purged();
DROP TABLE retention_purges;
