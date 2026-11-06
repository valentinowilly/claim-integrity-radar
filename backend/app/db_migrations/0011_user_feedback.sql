-- User feedback: whether a claim's explanation helped (one vote per person per claim), questions and suggestions.
CREATE TABLE user_feedback (
    feedback_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    context TEXT NOT NULL CHECK(context IN ('claim_explanation','help_question','general')),
    run_id TEXT,
    case_id TEXT,
    helpful INTEGER CHECK(helpful IS NULL OR helpful IN (0, 1)),
    message TEXT
);
CREATE INDEX idx_user_feedback_created ON user_feedback(created_at);
CREATE INDEX idx_user_feedback_claim ON user_feedback(user_id, run_id, case_id);
