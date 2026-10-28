-- Automatic intake from the server drop folder: one row per file content, one row per pull.
CREATE TABLE inbox_files (
    file_id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    checksum TEXT NOT NULL UNIQUE,
    received_at TEXT NOT NULL,
    finished_at TEXT,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('processing','analysed','rejected','failed')),
    row_count INTEGER,
    batch_id TEXT,
    run_id TEXT,
    message_code TEXT
);
CREATE TABLE inbox_pulls (
    pull_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    trigger TEXT NOT NULL,
    actor_user_id TEXT NOT NULL,
    files_found INTEGER NOT NULL DEFAULT 0,
    files_processed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_inbox_files_received ON inbox_files(received_at DESC);
