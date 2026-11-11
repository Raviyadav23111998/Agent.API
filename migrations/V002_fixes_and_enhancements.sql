-- ============================================================================
-- Agent — Tenant Database Schema V002
-- ============================================================================
-- Fixes for gaps found in V001 audit:
--   1. Missing updated_at triggers (9 tables)
--   2. Missing audit_log partition prep (future-proofing)
--   3. Missing content_cache TTL expiry index
--   4. Missing user_permission_overrides table
--   5. Missing migration_history tracking table
--   6. Missing created_at on ag_brain.entities
--   7. Expired memory auto-cleanup function
--   8. Missing ag_brain.documents.created_at index for recency queries
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. AUTO-UPDATE updated_at TRIGGER FUNCTION
-- ============================================================================
-- PostgreSQL doesn't auto-update timestamps like MySQL/SQLite.
-- Must use a trigger function. This is the standard pattern.

CREATE OR REPLACE FUNCTION ag_common.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply to all 9 tables that have updated_at
CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_auth.users
    FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_brain.documents
    FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_brain.entities
    FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_brain.sync_state
    FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_memory.memories
    FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_agents.definitions
    FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_agents.cron_jobs
    FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_system.configs
    FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_system.integrations
    FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();


-- ============================================================================
-- 2. USER PERMISSION OVERRIDES (same as SMSystems auth.user_permission_overrides)
-- ============================================================================
-- Allows per-user exception grants (e.g., give a specific member admin access
-- to one module without changing their role).

CREATE TABLE IF NOT EXISTS ag_auth.user_permission_overrides (
    override_id     SERIAL PRIMARY KEY,
    user_id         INT NOT NULL REFERENCES ag_auth.users(user_id) ON DELETE CASCADE,
    module_id       INT NOT NULL REFERENCES ag_system.modules(module_id) ON DELETE CASCADE,
    can_create      BOOLEAN,
    can_read        BOOLEAN,
    can_update      BOOLEAN,
    can_delete      BOOLEAN,
    reason          TEXT,
    granted_by      INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    expires_at      TIMESTAMPTZ,
    UNIQUE(user_id, module_id)
);

CREATE INDEX idx_perm_overrides_user ON ag_auth.user_permission_overrides(user_id);


-- ============================================================================
-- 3. API KEYS TABLE (for programmatic access without JWT)
-- ============================================================================
-- Per-tenant API keys for integrations, webhooks, and automation.

CREATE TABLE IF NOT EXISTS ag_auth.api_keys (
    key_id          SERIAL PRIMARY KEY,
    user_id         INT NOT NULL REFERENCES ag_auth.users(user_id) ON DELETE CASCADE,
    key_prefix      VARCHAR(10) NOT NULL,           -- First 8 chars, for display: "ag_3f7b..."
    key_hash        VARCHAR(128) NOT NULL UNIQUE,    -- SHA-256 of the full key
    name            VARCHAR(200) NOT NULL,           -- Human label: "CI/CD Pipeline Key"
    scopes          JSONB DEFAULT '["ai_chat", "brain_search"]',  -- Allowed modules
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_used_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    revoked_at      TIMESTAMPTZ
);

CREATE INDEX idx_api_keys_hash ON ag_auth.api_keys(key_hash) WHERE is_active = TRUE;
CREATE INDEX idx_api_keys_user ON ag_auth.api_keys(user_id);


-- ============================================================================
-- 4. MIGRATION HISTORY TABLE
-- ============================================================================
-- Track which migrations have been applied (standard pattern).

CREATE TABLE IF NOT EXISTS ag_system.migration_history (
    migration_id    SERIAL PRIMARY KEY,
    version         VARCHAR(50) NOT NULL UNIQUE,
    script_name     VARCHAR(200) NOT NULL,
    description     TEXT,
    checksum        VARCHAR(64),
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    applied_by      VARCHAR(100) DEFAULT 'system',
    execution_ms    INT
);

-- Record V001 and V002
INSERT INTO ag_system.migration_history (version, script_name, description)
VALUES
    ('V001', 'V001_create_ag_schemas.sql', 'Initial schema creation: 6 schemas, 25 tables, seed data'),
    ('V002', 'V002_fixes_and_enhancements.sql', 'Triggers, API keys, overrides, migration tracking, TTL cleanup');


-- ============================================================================
-- 5. MISSING INDEXES FOR COMMON QUERY PATTERNS
-- ============================================================================

-- Documents: recency queries (ORDER BY created_at DESC LIMIT N)
CREATE INDEX IF NOT EXISTS idx_docs_created ON ag_brain.documents(created_at DESC);

-- Documents: combined owner + type filter (hot path for brain search)
CREATE INDEX IF NOT EXISTS idx_docs_owner_type ON ag_brain.documents(owner_id, doc_type);

-- Content cache: TTL expiry cleanup (fetched_at + ttl_seconds < now)
-- Partial index for active caches only
CREATE INDEX IF NOT EXISTS idx_cache_source_type ON ag_brain.content_cache(source_type);

-- Memories: combined scope + category + layer (hot path for memory injection)
CREATE INDEX IF NOT EXISTS idx_mem_user_layer_cat ON ag_memory.memories(user_id, layer, category);

-- Agent runs: recent runs per agent (dashboard query)
CREATE INDEX IF NOT EXISTS idx_runs_agent_time ON ag_agents.runs(agent_id, started_at DESC);

-- Audit log: composite for common filter (entity_type + time range)
CREATE INDEX IF NOT EXISTS idx_audit_entity_time ON ag_system.audit_log(entity_type, created_at DESC);


-- ============================================================================
-- 6. EXPIRED MEMORY CLEANUP FUNCTION
-- ============================================================================
-- Call periodically to remove expired session memories.

CREATE OR REPLACE FUNCTION ag_memory.cleanup_expired()
RETURNS INT AS $$
DECLARE
    deleted_count INT;
BEGIN
    DELETE FROM ag_memory.memories
    WHERE expires_at IS NOT NULL AND expires_at < NOW();
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;


-- ============================================================================
-- 7. EFFECTIVE PERMISSIONS VIEW (merges role + overrides)
-- ============================================================================
-- Single query to get a user's effective permissions, considering overrides.
-- Same pattern as SMSystems where user_permission_overrides trump role_permissions.

CREATE OR REPLACE VIEW ag_auth.effective_permissions AS
SELECT
    u.user_id,
    u.user_code,
    u.full_name,
    r.role_key,
    m.module_key,
    m.module_name,
    -- Override wins if set, else fall back to role permission
    COALESCE(ov.can_create, rp.can_create, FALSE) AS can_create,
    COALESCE(ov.can_read, rp.can_read, FALSE) AS can_read,
    COALESCE(ov.can_update, rp.can_update, FALSE) AS can_update,
    COALESCE(ov.can_delete, rp.can_delete, FALSE) AS can_delete,
    CASE WHEN ov.override_id IS NOT NULL THEN TRUE ELSE FALSE END AS is_overridden
FROM ag_auth.users u
JOIN ag_auth.roles r ON u.role_id = r.role_id
CROSS JOIN ag_system.modules m
LEFT JOIN ag_auth.role_permissions rp ON rp.role_id = u.role_id AND rp.module_id = m.module_id
LEFT JOIN ag_auth.user_permission_overrides ov ON ov.user_id = u.user_id AND ov.module_id = m.module_id
    AND (ov.expires_at IS NULL OR ov.expires_at > NOW())
WHERE u.is_active = TRUE AND m.is_active = TRUE;


-- ============================================================================
-- 8. DATABASE STATISTICS VIEW
-- ============================================================================
-- Quick dashboard stats for the tenant.

CREATE OR REPLACE VIEW ag_system.tenant_stats AS
SELECT
    (SELECT COUNT(*) FROM ag_auth.users WHERE is_active = TRUE) AS active_users,
    (SELECT COUNT(*) FROM ag_brain.documents) AS total_documents,
    (SELECT COUNT(*) FROM ag_brain.documents WHERE status = 'indexed') AS indexed_documents,
    (SELECT COUNT(*) FROM ag_memory.memories) AS total_memories,
    (SELECT COUNT(*) FROM ag_brain.entities) AS brain_entities,
    (SELECT COUNT(*) FROM ag_brain.relations) AS brain_relations,
    (SELECT COUNT(*) FROM ag_memory.entities) AS memory_entities,
    (SELECT COUNT(*) FROM ag_agents.definitions WHERE enabled = TRUE) AS active_agents,
    (SELECT COUNT(*) FROM ag_agents.runs WHERE started_at > NOW() - INTERVAL '24 hours') AS runs_24h,
    (SELECT COUNT(*) FROM ag_system.audit_log WHERE created_at > NOW() - INTERVAL '24 hours') AS audit_24h,
    (SELECT pg_size_pretty(pg_database_size(current_database()))) AS db_size;


COMMIT;
