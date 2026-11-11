-- ════════════════════════════════════════════════════════════════════════
-- V026 — Embed Action Audit Log (Phase 4)
-- ════════════════════════════════════════════════════════════════════════
-- Every copilot page action (click, fill, select, navigate) is logged
-- so admins can see what the embedded agent did on customer pages.
-- Also logs blocked/approved/denied actions from the execution policy.
--
-- Feeds Phase 5 analytics dashboard + audit log viewer.
-- See EMBED_AGENT_PLATFORM_ARCHITECTURE.md Appendix D #7.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS ag_bot.embed_action_audit (
    id             BIGSERIAL    PRIMARY KEY,
    integration_id INT          NOT NULL REFERENCES ag_bot.bots(bot_id),
    session_id     TEXT         NOT NULL,
    tool_name      TEXT         NOT NULL,
    target_label   TEXT,                    -- e.g. "Delete Account" button label
    tool_args      TEXT,                    -- truncated args summary (≤500 chars)
    result         TEXT,                    -- truncated result (≤500 chars)
    status         TEXT         NOT NULL,   -- 'executed', 'blocked', 'approved', 'denied'
    client_ip      TEXT,
    end_user_id    TEXT,                    -- verified identity if available
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Per-integration chronological queries (Phase 5 audit viewer).
CREATE INDEX IF NOT EXISTS idx_embed_audit_integration
    ON ag_bot.embed_action_audit(integration_id, created_at DESC);

-- Per-session queries (debugging a specific conversation).
CREATE INDEX IF NOT EXISTS idx_embed_audit_session
    ON ag_bot.embed_action_audit(session_id, created_at);

COMMIT;

-- Verify (manual):
--   SELECT id, integration_id, session_id, tool_name, target_label, status, created_at
--   FROM ag_bot.embed_action_audit ORDER BY id DESC LIMIT 10;
