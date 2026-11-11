-- V012: Multi-worker conversation claims
-- ════════════════════════════════════════
-- With multiple uvicorn workers (or web + gateway), two processes could
-- process the SAME conversation concurrently: both build an AgentLoop,
-- both append to history → interleaved/corrupted replies.
--
-- processing_until is a short-lived claim: a worker atomically claims the
-- conversation before running the agent, and clears it when done. A stale
-- claim (crashed worker) expires on its own — no janitor needed.

ALTER TABLE ag_system.conversations
    ADD COLUMN IF NOT EXISTS processing_until TIMESTAMPTZ NULL;

COMMENT ON COLUMN ag_system.conversations.processing_until IS
    'Active-processing claim: worker holds the conversation until this time. NULL/past = free.';

-- Fast lookup for the claim check
CREATE INDEX IF NOT EXISTS idx_conversations_processing
    ON ag_system.conversations (conversation_id, processing_until);
