-- Record of completed SQLite -> PostgreSQL data migrations (counts and digests only).
CREATE TABLE data_migration_runs (
    migration_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    source_digests_json TEXT NOT NULL,
    report_json TEXT NOT NULL
);
CREATE TRIGGER data_migration_runs_no_update BEFORE UPDATE ON data_migration_runs
    FOR EACH ROW EXECUTE FUNCTION cir_reject('data migration log is append-only');
CREATE TRIGGER data_migration_runs_no_delete BEFORE DELETE ON data_migration_runs
    FOR EACH ROW EXECUTE FUNCTION cir_reject('data migration log is append-only');
