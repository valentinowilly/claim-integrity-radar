-- Rate-limit hits shared by every API process (keys are SHA-256 digests; rows older than a day are pruned).
CREATE TABLE rate_limit_hits (
    key_digest TEXT NOT NULL,
    hit_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX idx_rate_limit_hits_key ON rate_limit_hits(key_digest, hit_at);
CREATE INDEX idx_rate_limit_hits_time ON rate_limit_hits(hit_at);
