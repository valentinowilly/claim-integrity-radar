-- Light work sharing: who has taken a claim (per case reference, across analyses).
CREATE TABLE case_assignments (
    case_id TEXT PRIMARY KEY,
    assignee_user_id TEXT NOT NULL,
    assigned_at TEXT NOT NULL,
    assigned_in_run_id TEXT NOT NULL
);
CREATE INDEX idx_case_assignments_user ON case_assignments(assignee_user_id);
