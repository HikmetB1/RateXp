-- Optional full-conversation storage. One row per consented skill invocation,
-- holding the session transcript as ATIF (Agent Trajectory Interchange Format)
-- JSON. Linked back to its feedback row by shared request_id / session_id.
CREATE TABLE IF NOT EXISTS transcript (
    id             BIGSERIAL PRIMARY KEY,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    session_id     TEXT NOT NULL,
    request_id     TEXT,
    skill_name     TEXT NOT NULL,
    agent          TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    atif           JSONB NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS transcript_request_id_uniq
    ON transcript (request_id) WHERE request_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS transcript_created_at_idx ON transcript (created_at DESC);
