-- Hidden-from-list markers for uploaded files and archived runs (append-only).
-- The batches and runs themselves stay intact; lists only leave these entries out.
CREATE TABLE data_batch_removals (
    batch_id TEXT PRIMARY KEY REFERENCES data_batches(batch_id),
    removed_at TEXT NOT NULL,
    actor_user_id TEXT NOT NULL
);
CREATE TABLE analysis_run_archives (
    run_id TEXT PRIMARY KEY REFERENCES analysis_runs(run_id),
    archived_at TEXT NOT NULL,
    actor_user_id TEXT NOT NULL
);
