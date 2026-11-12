-- Claim documents whose retention ended keep their row (name, hash) with the time their content was removed.
ALTER TABLE claim_documents ADD COLUMN purged_at TEXT;
