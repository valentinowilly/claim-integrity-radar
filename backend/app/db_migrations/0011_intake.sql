-- Claim packages from several sources (CSV, FHIR JSON, PDF) and the documents read from them.
CREATE TABLE intake_packages (
    package_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    creator_user_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('uploading','processing','ready','failed')),
    stage TEXT,
    progress_done INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    file_count INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT,
    batch_id TEXT,
    run_id TEXT,
    message_code TEXT,
    finished_at TEXT
);
CREATE INDEX idx_intake_packages_created ON intake_packages(created_at DESC);
CREATE TABLE claim_documents (
    document_id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL,
    case_id TEXT,
    file_name TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    page_count INTEGER NOT NULL,
    scanned_pages INTEGER NOT NULL,
    ocr_confidence DOUBLE PRECISION,
    doc_type TEXT NOT NULL,
    reader TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('linked','unlinked','unreadable')),
    facts_json TEXT NOT NULL,
    pages_json TEXT NOT NULL,
    checks_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_claim_documents_case ON claim_documents(case_id);
CREATE INDEX idx_claim_documents_package ON claim_documents(package_id);
