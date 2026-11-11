-- ============================================================================
-- V006: Eliminate .ag_data — Transcripts, Checkpoints, Artifacts, SyncState
-- ============================================================================
-- Moves ALL remaining filesystem storage into PostgreSQL.
-- After this, .ag_data directory is no longer needed on the server.
-- ============================================================================

BEGIN;

-- ── Transcript Logs (replaces .ag_data/users/<id>/logs/transcript_*.jsonl) ──
CREATE TABLE IF NOT EXISTS ag_system.transcript_logs (
    log_id          BIGSERIAL PRIMARY KEY,
    session_id      VARCHAR(200) NOT NULL,
    user_id         VARCHAR(200),
    step_index      INT NOT NULL DEFAULT 0,
    source          VARCHAR(50) NOT NULL,     -- USER, MODEL, SYSTEM
    step_type       VARCHAR(100) NOT NULL,    -- USER_INPUT, LLM_RESPONSE, TOOL_*, etc.
    content         TEXT,
    tool_calls      JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

CREATE INDEX IF NOT EXISTS idx_transcript_session ON ag_system.transcript_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_transcript_user ON ag_system.transcript_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_transcript_time ON ag_system.transcript_logs(created_at DESC);

-- ── Checkpoints (replaces .ag_data/users/<id>/checkpoints/checkpoint_*.json) ──
CREATE TABLE IF NOT EXISTS ag_system.checkpoints (
    checkpoint_id   BIGSERIAL PRIMARY KEY,
    session_id      VARCHAR(200) NOT NULL,
    user_id         VARCHAR(200),
    iteration       INT NOT NULL,
    checkpoint_data JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

CREATE INDEX IF NOT EXISTS idx_checkpoint_session ON ag_system.checkpoints(session_id);

-- ── Artifacts (replaces .ag_data/artifacts/*.md) ──
CREATE TABLE IF NOT EXISTS ag_system.artifacts (
    artifact_id     BIGSERIAL PRIMARY KEY,
    name            VARCHAR(300) NOT NULL,
    title           VARCHAR(500),
    content         TEXT NOT NULL,
    session_id      VARCHAR(200) NOT NULL DEFAULT 'default',
    user_id         VARCHAR(200),
    request_feedback BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    UNIQUE(name, session_id)
);

CREATE INDEX IF NOT EXISTS idx_artifact_session ON ag_system.artifacts(session_id);

-- ── Context Bundles (replaces .ag_data/context_cache/bundles.json + text files) ──
CREATE TABLE IF NOT EXISTS ag_brain.context_bundles (
    bundle_id       BIGSERIAL PRIMARY KEY,
    name            VARCHAR(300) NOT NULL UNIQUE,
    description     TEXT,
    max_tokens      INT NOT NULL DEFAULT 1000000,
    total_tokens    INT NOT NULL DEFAULT 0,
    document_count  INT NOT NULL DEFAULT 0,
    doc_ids         JSONB DEFAULT '[]',
    cached_payload  TEXT,
    payload_built_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

COMMIT;
