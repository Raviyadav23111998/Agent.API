-- V013: Action audit log for irreversible tool executions
-- ════════════════════════════════════════════════════════
-- A tamper-evident record of every side-effecting/irreversible action the
-- agent takes (send email, run shell, delete, push) — who, what, when, and
-- whether it was approved. Complements the existing auth-event log.

CREATE TABLE IF NOT EXISTS ag_system.action_audit (
    audit_id        BIGSERIAL PRIMARY KEY,
    user_id         INTEGER NULL,
    conversation_id TEXT NULL,
    tool_name       TEXT NOT NULL,
    side_effect     TEXT NOT NULL,          -- read | write | irreversible
    args_summary    TEXT NULL,              -- truncated/sanitized args
    approved        BOOLEAN NULL,           -- NULL = no approval required
    status          TEXT NOT NULL,          -- executed | denied | blocked | error
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_action_audit_user
    ON ag_system.action_audit (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_action_audit_tool
    ON ag_system.action_audit (tool_name, created_at DESC);

COMMENT ON TABLE ag_system.action_audit IS
    'Audit trail of side-effecting agent tool executions (V013).';
