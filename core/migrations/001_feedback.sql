-- One row per submitted rating. score is binary: 1 = good, 2 = bad (nullable,
-- since a user may submit a comment only). request_id is an optional idempotency
-- key - a unique partial index dedupes retries without blocking null values.
CREATE TABLE IF NOT EXISTS feedback (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    session_id  TEXT NOT NULL,
    skill_name  TEXT NOT NULL,
    agent       TEXT NOT NULL,
    score       INTEGER CHECK (score BETWEEN 1 AND 2),
    comment     TEXT,
    request_id  TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS feedback_request_id_uniq
    ON feedback (request_id) WHERE request_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS feedback_created_at_idx ON feedback (created_at DESC);
