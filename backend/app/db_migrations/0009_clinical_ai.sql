-- Stage 2 reading aid: structured verdicts from Claude on a claim's clinical note (example data only).
CREATE TABLE clinical_ai_reviews (
    review_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    requested_by_user_id TEXT NOT NULL,
    model TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK(verdict IN ('sesuai','perlu_dicek','mencurigakan')),
    result_json TEXT NOT NULL
);
CREATE INDEX idx_clinical_ai_reviews_case ON clinical_ai_reviews(run_id, case_id, created_at);
