-- Claim packages can be cancelled (while uploading, or after processing: the analysis is archived).
ALTER TABLE intake_packages DROP CONSTRAINT IF EXISTS intake_packages_status_check;
ALTER TABLE intake_packages ADD CONSTRAINT intake_packages_status_check
    CHECK(status IN ('uploading','processing','ready','failed','cancelled'));
