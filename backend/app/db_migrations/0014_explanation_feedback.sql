-- Whether the reasons shown for a claim helped the verifier (one answer per person, claim and check; codes only).
CREATE TABLE explanation_feedback (
    feedback_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    indicator TEXT NOT NULL,
    user_id TEXT NOT NULL,
    helpful INTEGER NOT NULL CHECK(helpful IN (0,1)),
    reason TEXT CHECK(reason IS NULL OR reason IN ('unclear','not_matching','too_long','other')),
    recorded_at TEXT NOT NULL,
    UNIQUE(run_id, case_id, indicator, user_id)
);
CREATE INDEX idx_explanation_feedback_run ON explanation_feedback(run_id);
