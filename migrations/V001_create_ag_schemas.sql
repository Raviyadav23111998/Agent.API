-- ============================================================================
-- Agent — Tenant Database Schema V001
-- ============================================================================
-- Database: agent_uat
-- Creates: ag_common, ag_auth, ag_system, ag_brain, ag_memory, ag_agents
-- Total: 5 schemas, 22 tables, 1 utility schema
-- ============================================================================

BEGIN;

-- ============================================================================
-- 0. UTILITY SCHEMA: ag_common
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS ag_common;

-- NOTE: Do NOT use 'NOW() AT TIME ZONE 'UTC'' here — that strips the timezone
-- info to a bare timestamp, which PG then re-interprets in the session timezone,
-- causing offset mismatches when the server is not in UTC.
-- NOW() already returns a correct TIMESTAMPTZ in all timezones.
CREATE OR REPLACE FUNCTION ag_common.utc_now()
RETURNS TIMESTAMPTZ AS $$
    SELECT NOW();
$$ LANGUAGE sql STABLE;

-- ============================================================================
-- 1. SCHEMA: ag_system — Platform Configuration
-- ============================================================================
-- Must be created BEFORE ag_auth (role_permissions references modules)
CREATE SCHEMA IF NOT EXISTS ag_system;

-- 1.1 Feature modules (RBAC scoping — same pattern as SMSystems system.modules)
CREATE TABLE ag_system.modules (
    module_id       SERIAL PRIMARY KEY,
    module_name     VARCHAR(200) NOT NULL,
    module_key      VARCHAR(100) NOT NULL UNIQUE,
    description     TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

-- 1.2 Per-tenant configuration (replaces .env + config.json)
CREATE TABLE ag_system.configs (
    config_id       SERIAL PRIMARY KEY,
    config_key      VARCHAR(200) NOT NULL UNIQUE,
    config_value    TEXT,
    description     TEXT,
    is_secret       BOOLEAN NOT NULL DEFAULT FALSE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

-- 1.3 External service integrations (Jira, Outlook, Slack, GitHub, etc.)
CREATE TABLE ag_system.integrations (
    integration_id  SERIAL PRIMARY KEY,
    service_key     VARCHAR(100) NOT NULL UNIQUE,
    display_name    VARCHAR(200),
    is_enabled      BOOLEAN NOT NULL DEFAULT FALSE,
    config_json     JSONB DEFAULT '{}',
    credentials_enc TEXT,
    last_verified   TIMESTAMPTZ,
    status          VARCHAR(50) NOT NULL DEFAULT 'unconfigured',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    CONSTRAINT chk_integration_status CHECK (status IN (
        'unconfigured', 'active', 'error', 'expired', 'revoked'
    ))
);

-- 1.4 File storage tracking (same pattern as SMSystems system.files)
CREATE TABLE ag_system.files (
    file_id         BIGSERIAL PRIMARY KEY,
    file_type       VARCHAR(50) NOT NULL,
    associated_to   VARCHAR(100) NOT NULL,
    associated_id   BIGINT,
    file_path       VARCHAR(1000) NOT NULL,
    file_name       VARCHAR(300),
    extension       VARCHAR(20),
    size_bytes      BIGINT,
    mime_type       VARCHAR(100),
    created_by      INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

-- 1.5 Comprehensive audit trail
CREATE TABLE ag_system.audit_log (
    log_id          BIGSERIAL PRIMARY KEY,
    action          VARCHAR(100) NOT NULL,
    entity_type     VARCHAR(100),
    entity_id       VARCHAR(200),
    user_id         INT,
    details_json    JSONB DEFAULT '{}',
    ip_address      VARCHAR(50),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

CREATE INDEX idx_audit_action ON ag_system.audit_log(action);
CREATE INDEX idx_audit_user ON ag_system.audit_log(user_id);
CREATE INDEX idx_audit_time ON ag_system.audit_log(created_at DESC);

-- 1.6 Conversation summaries (replaces summaries/*.json)
CREATE TABLE ag_system.conversation_summaries (
    summary_id      BIGSERIAL PRIMARY KEY,
    user_id         INT,
    session_id      VARCHAR(200),
    summary         TEXT NOT NULL,
    message_count   INT,
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

CREATE INDEX idx_summaries_user ON ag_system.conversation_summaries(user_id);
CREATE INDEX idx_summaries_session ON ag_system.conversation_summaries(session_id);

-- ============================================================================
-- 2. SCHEMA: ag_auth — Identity & Access Control
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS ag_auth;

-- 2.1 Roles (system-defined + tenant-custom)
CREATE TABLE ag_auth.roles (
    role_id     SERIAL PRIMARY KEY,
    role_key    VARCHAR(50) NOT NULL UNIQUE,
    role_name   VARCHAR(200) NOT NULL,
    description TEXT,
    is_system   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

-- 2.2 Per-tenant users
CREATE TABLE ag_auth.users (
    user_id         SERIAL PRIMARY KEY,
    external_id     VARCHAR(200),
    user_code       VARCHAR(100) UNIQUE,
    email           VARCHAR(300),
    mobile          VARCHAR(20),
    full_name       VARCHAR(300),
    avatar_url      VARCHAR(500),
    role_id         INT NOT NULL DEFAULT 3 REFERENCES ag_auth.roles(role_id),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    is_blocked      BOOLEAN NOT NULL DEFAULT FALSE,
    password_hash   TEXT,
    salt            BYTEA,
    last_login_at   TIMESTAMPTZ,
    metadata_json   JSONB DEFAULT '{}',
    platform        VARCHAR(50) DEFAULT 'web',
    share_ingested  BOOLEAN NOT NULL DEFAULT FALSE,
    created_by      INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    updated_by      INT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

CREATE INDEX idx_users_external ON ag_auth.users(external_id);
CREATE INDEX idx_users_email ON ag_auth.users(email);
CREATE INDEX idx_users_role ON ag_auth.users(role_id);

-- 2.3 RBAC permissions per module (same pattern as SMSystems auth.role_permissions)
CREATE TABLE ag_auth.role_permissions (
    role_id     INT NOT NULL REFERENCES ag_auth.roles(role_id) ON DELETE CASCADE,
    module_id   INT NOT NULL REFERENCES ag_system.modules(module_id) ON DELETE CASCADE,
    can_create  BOOLEAN DEFAULT FALSE,
    can_read    BOOLEAN DEFAULT FALSE,
    can_update  BOOLEAN DEFAULT FALSE,
    can_delete  BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (role_id, module_id)
);

-- 2.4 JWT refresh tokens
CREATE TABLE ag_auth.refresh_tokens (
    token_id        SERIAL PRIMARY KEY,
    user_id         INT NOT NULL REFERENCES ag_auth.users(user_id) ON DELETE CASCADE,
    token           VARCHAR(500) NOT NULL UNIQUE,
    expires_at      TIMESTAMPTZ NOT NULL,
    session_id      VARCHAR(200),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    revoked_at      TIMESTAMPTZ
);

CREATE INDEX idx_refresh_tokens_user ON ag_auth.refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_active ON ag_auth.refresh_tokens(token) WHERE is_active = TRUE;

-- 2.5 User sessions (same pattern as SMSystems auth.user_context)
CREATE TABLE ag_auth.user_sessions (
    session_id      VARCHAR(200) PRIMARY KEY,
    user_id         INT NOT NULL REFERENCES ag_auth.users(user_id) ON DELETE CASCADE,
    platform        VARCHAR(50),
    agent_type      VARCHAR(100),
    ip_address      VARCHAR(50),
    login_at        TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    last_active_at  TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    logout_at       TIMESTAMPTZ,
    metadata_json   JSONB DEFAULT '{}'
);

CREATE INDEX idx_sessions_user ON ag_auth.user_sessions(user_id);

-- ============================================================================
-- 3. SCHEMA: ag_brain — Knowledge Base
-- ============================================================================
-- Maps from: DocumentStore, ContentStore, EntityIndex, AnswerCache, SyncWorker
CREATE SCHEMA IF NOT EXISTS ag_brain;

-- 3.1 Ingested documents (replaces brain/storage/document_store.py → documents table)
CREATE TABLE ag_brain.documents (
    doc_id          BIGSERIAL PRIMARY KEY,
    source_path     VARCHAR(1000) NOT NULL UNIQUE,
    doc_type        VARCHAR(50) NOT NULL DEFAULT 'document',
    title           VARCHAR(500) DEFAULT '',
    content         TEXT NOT NULL,
    metadata_json   JSONB DEFAULT '{}',
    content_hash    VARCHAR(64) NOT NULL,
    token_count     INT DEFAULT 0,
    status          VARCHAR(50) NOT NULL DEFAULT 'pending',
    owner_id        VARCHAR(200) NOT NULL DEFAULT '__tenant__',
    created_by      INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    CONSTRAINT chk_doc_status CHECK (status IN (
        'pending', 'indexed', 'error', 'archived'
    ))
);

-- PostgreSQL generated tsvector for full-text search (replaces SQLite FTS5)
ALTER TABLE ag_brain.documents
    ADD COLUMN fts_vector TSVECTOR
    GENERATED ALWAYS AS (
        to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(content, ''))
    ) STORED;

CREATE INDEX idx_docs_fts ON ag_brain.documents USING GIN (fts_vector);
CREATE INDEX idx_docs_owner ON ag_brain.documents(owner_id);
CREATE INDEX idx_docs_type ON ag_brain.documents(doc_type);
CREATE INDEX idx_docs_hash ON ag_brain.documents(content_hash);
CREATE INDEX idx_docs_status ON ag_brain.documents(status);
CREATE INDEX idx_docs_source ON ag_brain.documents(source_path);

-- 3.2 Ingestion log (replaces document_store.py → ingestion_log table)
CREATE TABLE ag_brain.ingestion_log (
    log_id          BIGSERIAL PRIMARY KEY,
    doc_id          BIGINT NOT NULL REFERENCES ag_brain.documents(doc_id) ON DELETE CASCADE,
    action          VARCHAR(100) NOT NULL,
    details         TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

CREATE INDEX idx_ingestion_doc ON ag_brain.ingestion_log(doc_id);

-- 3.3 Content cache (replaces brain/storage/content_store.py)
CREATE TABLE ag_brain.content_cache (
    cache_id        BIGSERIAL PRIMARY KEY,
    source_uri      VARCHAR(1000) NOT NULL,
    owner_id        VARCHAR(200) NOT NULL DEFAULT '__tenant__',
    content         TEXT NOT NULL,
    content_hash    VARCHAR(64) NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    ttl_seconds     INT NOT NULL DEFAULT 3600,
    source_type     VARCHAR(100) DEFAULT '',
    size_bytes      BIGINT DEFAULT 0,
    UNIQUE(source_uri, owner_id)
);

CREATE INDEX idx_cache_owner ON ag_brain.content_cache(owner_id);
CREATE INDEX idx_cache_expiry ON ag_brain.content_cache(fetched_at, ttl_seconds);

-- 3.4 Answer cache (replaces brain/storage/answer_cache.py)
CREATE TABLE ag_brain.answer_cache (
    question_hash   VARCHAR(64) PRIMARY KEY,
    question_text   TEXT NOT NULL,
    question_keywords TEXT NOT NULL,
    answer          TEXT NOT NULL,
    bundle_name     VARCHAR(200) DEFAULT '',
    model           VARCHAR(200) DEFAULT '',
    input_tokens_saved INT DEFAULT 0,
    hit_count       INT DEFAULT 0,
    last_hit_at     TIMESTAMPTZ,
    ttl_seconds     INT DEFAULT 7200,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

CREATE INDEX idx_answer_bundle ON ag_brain.answer_cache(bundle_name);

-- 3.5 Knowledge graph — entities (replaces brain/storage/entity_index.py → entities)
CREATE TABLE ag_brain.entities (
    entity_id       BIGSERIAL PRIMARY KEY,
    name            VARCHAR(500) NOT NULL,
    entity_type     VARCHAR(100) NOT NULL,
    owner_id        VARCHAR(200) NOT NULL DEFAULT '__tenant__',
    source_uri      VARCHAR(1000) DEFAULT '',
    properties_json JSONB DEFAULT '{}',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    UNIQUE(name, entity_type, owner_id)
);

CREATE INDEX idx_brain_entities_type ON ag_brain.entities(entity_type);
CREATE INDEX idx_brain_entities_name ON ag_brain.entities(name);
CREATE INDEX idx_brain_entities_owner ON ag_brain.entities(owner_id);

-- FTS on entity names
ALTER TABLE ag_brain.entities
    ADD COLUMN fts_vector TSVECTOR
    GENERATED ALWAYS AS (
        to_tsvector('simple', COALESCE(name, '') || ' ' || COALESCE(entity_type, ''))
    ) STORED;
CREATE INDEX idx_brain_entities_fts ON ag_brain.entities USING GIN (fts_vector);

-- 3.6 Knowledge graph — relations (replaces entity_index.py → relations)
CREATE TABLE ag_brain.relations (
    relation_id     BIGSERIAL PRIMARY KEY,
    from_entity_id  BIGINT NOT NULL REFERENCES ag_brain.entities(entity_id) ON DELETE CASCADE,
    to_entity_id    BIGINT NOT NULL REFERENCES ag_brain.entities(entity_id) ON DELETE CASCADE,
    relation_type   VARCHAR(100) NOT NULL,
    source_uri      VARCHAR(1000) DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    UNIQUE(from_entity_id, to_entity_id, relation_type)
);

CREATE INDEX idx_brain_rels_from ON ag_brain.relations(from_entity_id);
CREATE INDEX idx_brain_rels_to ON ag_brain.relations(to_entity_id);
CREATE INDEX idx_brain_rels_type ON ag_brain.relations(relation_type);

-- 3.7 Data source sync state (replaces sync_state.json + sync_watermarks table)
CREATE TABLE ag_brain.sync_state (
    source_key      VARCHAR(100) PRIMARY KEY,
    last_sync_at    TIMESTAMPTZ,
    sync_cursor     TEXT,
    docs_synced     INT DEFAULT 0,
    status          VARCHAR(50) NOT NULL DEFAULT 'idle',
    error_message   TEXT,
    config_json     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    CONSTRAINT chk_sync_status CHECK (status IN (
        'idle', 'running', 'error', 'paused'
    ))
);

-- ============================================================================
-- 4. SCHEMA: ag_memory — Persistent Memory System
-- ============================================================================
-- Maps from: state/memory_store.py (memories, entities, relations, memory_tags)
CREATE SCHEMA IF NOT EXISTS ag_memory;

-- 4.1 Multi-layer memory (replaces memory_store.py → memories table)
CREATE TABLE ag_memory.memories (
    memory_id       BIGSERIAL PRIMARY KEY,
    user_id         VARCHAR(200) NOT NULL DEFAULT '__tenant__',
    layer           VARCHAR(50) NOT NULL DEFAULT 'semantic',
    category        VARCHAR(100) NOT NULL DEFAULT 'fact',
    key             VARCHAR(500) NOT NULL,
    value           TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 1.0,
    source          VARCHAR(200) NOT NULL DEFAULT '',
    access_count    INT NOT NULL DEFAULT 0,
    last_accessed   TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    UNIQUE(user_id, key),
    CONSTRAINT chk_memory_layer CHECK (layer IN (
        'session', 'episodic', 'semantic', 'company'
    ))
);

-- FTS on memory key+value (replaces SQLite FTS5 memory_fts)
ALTER TABLE ag_memory.memories
    ADD COLUMN fts_vector TSVECTOR
    GENERATED ALWAYS AS (
        to_tsvector('english', COALESCE(key, '') || ' ' || COALESCE(value, ''))
    ) STORED;

CREATE INDEX idx_mem_fts ON ag_memory.memories USING GIN (fts_vector);
CREATE INDEX idx_mem_user_layer ON ag_memory.memories(user_id, layer);
CREATE INDEX idx_mem_user_cat ON ag_memory.memories(user_id, category);
CREATE INDEX idx_mem_user_key ON ag_memory.memories(user_id, key);
CREATE INDEX idx_mem_expires ON ag_memory.memories(expires_at) WHERE expires_at IS NOT NULL;

-- 4.2 Memory tags (many-to-many, replaces memory_store.py → memory_tags)
CREATE TABLE ag_memory.memory_tags (
    memory_id   BIGINT NOT NULL REFERENCES ag_memory.memories(memory_id) ON DELETE CASCADE,
    tag         VARCHAR(100) NOT NULL,
    PRIMARY KEY (memory_id, tag)
);

CREATE INDEX idx_mem_tags_tag ON ag_memory.memory_tags(tag);

-- 4.3 Conversation entity graph (replaces memory_store.py → entities/relations)
CREATE TABLE ag_memory.entities (
    entity_id       BIGSERIAL PRIMARY KEY,
    name            VARCHAR(500) NOT NULL,
    entity_type     VARCHAR(100) NOT NULL,
    user_id         VARCHAR(200) NOT NULL DEFAULT '__tenant__',
    properties      JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    UNIQUE(name, entity_type, user_id)
);

CREATE INDEX idx_mem_entities_name ON ag_memory.entities(name);
CREATE INDEX idx_mem_entities_type ON ag_memory.entities(entity_type);
CREATE INDEX idx_mem_entities_user ON ag_memory.entities(user_id);

CREATE TABLE ag_memory.relations (
    source_id       BIGINT NOT NULL REFERENCES ag_memory.entities(entity_id) ON DELETE CASCADE,
    target_id       BIGINT NOT NULL REFERENCES ag_memory.entities(entity_id) ON DELETE CASCADE,
    relation_type   VARCHAR(100) NOT NULL,
    properties      JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    PRIMARY KEY (source_id, target_id, relation_type)
);

-- ============================================================================
-- 5. SCHEMA: ag_agents — Agent Ecosystem
-- ============================================================================
-- Maps from: agents/registry.py (AgentDefinition) + cron/jobs.py
CREATE SCHEMA IF NOT EXISTS ag_agents;

-- 5.1 Agent definitions (replaces .ag_data/agents/<name>.json)
CREATE TABLE ag_agents.definitions (
    agent_id        SERIAL PRIMARY KEY,
    name            VARCHAR(200) NOT NULL UNIQUE,
    description     TEXT,
    system_prompt   TEXT DEFAULT '',
    tools           JSONB DEFAULT '[]',
    model           VARCHAR(200) DEFAULT '',
    schedule        VARCHAR(100) DEFAULT '',
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    workspace_path  VARCHAR(500) DEFAULT '',
    deliver         VARCHAR(200) NOT NULL DEFAULT 'local',
    owner_id        VARCHAR(200) NOT NULL DEFAULT '__tenant__',
    visibility      VARCHAR(50) NOT NULL DEFAULT 'global',
    metadata_json   JSONB DEFAULT '{}',
    last_run_at     TIMESTAMPTZ,
    last_status     VARCHAR(50) DEFAULT '',
    last_error      TEXT DEFAULT '',
    run_count       INT NOT NULL DEFAULT 0,
    created_by      INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    CONSTRAINT chk_agent_visibility CHECK (visibility IN ('global', 'private'))
);

CREATE INDEX idx_agents_owner ON ag_agents.definitions(owner_id);
CREATE INDEX idx_agents_enabled ON ag_agents.definitions(enabled) WHERE enabled = TRUE;

-- 5.2 Agent run history (replaces .ag_data/agents/logs/<name>/<timestamp>.md)
CREATE TABLE ag_agents.runs (
    run_id          BIGSERIAL PRIMARY KEY,
    agent_id        INT NOT NULL REFERENCES ag_agents.definitions(agent_id) ON DELETE CASCADE,
    status          VARCHAR(50) NOT NULL DEFAULT 'running',
    input_prompt    TEXT,
    output_text     TEXT,
    error_message   TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    completed_at    TIMESTAMPTZ,
    duration_ms     INT,
    token_count     INT,
    triggered_by    INT,
    CONSTRAINT chk_run_status CHECK (status IN (
        'running', 'ok', 'error', 'timeout', 'cancelled'
    ))
);

CREATE INDEX idx_runs_agent ON ag_agents.runs(agent_id);
CREATE INDEX idx_runs_status ON ag_agents.runs(status);
CREATE INDEX idx_runs_time ON ag_agents.runs(started_at DESC);

-- 5.3 Cron job schedules (replaces cron/jobs.py JSON-based jobs)
CREATE TABLE ag_agents.cron_jobs (
    job_id          SERIAL PRIMARY KEY,
    name            VARCHAR(200) NOT NULL UNIQUE,
    prompt          TEXT NOT NULL,
    schedule        VARCHAR(100) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at     TIMESTAMPTZ,
    next_run_at     TIMESTAMPTZ,
    run_count       INT DEFAULT 0,
    last_status     VARCHAR(50),
    last_output     TEXT,
    created_by      INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

-- ============================================================================
-- 6. SEED DATA
-- ============================================================================

-- 6.1 Default Roles
INSERT INTO ag_auth.roles (role_key, role_name, description, is_system) VALUES
    ('owner',   'Tenant Owner',    'Full access including billing, user management, and system settings', TRUE),
    ('admin',   'Administrator',   'Full access except billing and system settings', TRUE),
    ('member',  'Member',          'Use AI agent, ingest documents, manage own memories and agents', TRUE),
    ('viewer',  'Viewer',          'Read-only access to brain search and memory recall', TRUE),
    ('agent',   'Service Agent',   'Service account for spawned AI agents and cron jobs', TRUE);

-- 6.2 Feature Modules
INSERT INTO ag_system.modules (module_name, module_key, description) VALUES
    ('AI Chat',              'ai_chat',              'Send messages to the AI agent and receive responses'),
    ('Brain Search',         'brain_search',         'Search the knowledge base for information'),
    ('Brain Ingest',         'brain_ingest',         'Ingest documents, URLs, and files into the brain'),
    ('Brain Sync',           'brain_sync',           'Configure and run data source synchronization'),
    ('Memory Management',    'memory_mgmt',          'Store, recall, and manage persistent memories'),
    ('Agent Management',     'agent_mgmt',           'Create, edit, and manage custom AI agents'),
    ('Cron Management',      'cron_mgmt',            'Schedule and manage recurring agent tasks'),
    ('File Operations',      'file_ops',             'Read, write, and manage files in workspace'),
    ('Code Operations',      'code_ops',             'Execute code, run commands, and terminal operations'),
    ('User Management',      'user_mgmt',            'Add, edit, and deactivate tenant users'),
    ('Integration Config',   'integration_config',   'Configure external service connections (Jira, Slack, etc.)'),
    ('System Settings',      'system_settings',      'Manage tenant-level configuration and API keys');

-- 6.3 Role Permissions Matrix
-- Owner: full CRUD on everything
INSERT INTO ag_auth.role_permissions (role_id, module_id, can_create, can_read, can_update, can_delete)
SELECT r.role_id, m.module_id, TRUE, TRUE, TRUE, TRUE
FROM ag_auth.roles r, ag_system.modules m
WHERE r.role_key = 'owner';

-- Admin: full CRUD on everything EXCEPT system_settings
INSERT INTO ag_auth.role_permissions (role_id, module_id, can_create, can_read, can_update, can_delete)
SELECT r.role_id, m.module_id, TRUE, TRUE, TRUE, TRUE
FROM ag_auth.roles r, ag_system.modules m
WHERE r.role_key = 'admin' AND m.module_key != 'system_settings';
-- Admin can read system_settings but not modify
INSERT INTO ag_auth.role_permissions (role_id, module_id, can_create, can_read, can_update, can_delete)
SELECT r.role_id, m.module_id, FALSE, TRUE, FALSE, FALSE
FROM ag_auth.roles r, ag_system.modules m
WHERE r.role_key = 'admin' AND m.module_key = 'system_settings';

-- Member: use agent, ingest, manage own stuff
INSERT INTO ag_auth.role_permissions (role_id, module_id, can_create, can_read, can_update, can_delete)
SELECT r.role_id, m.module_id,
    CASE WHEN m.module_key IN ('ai_chat', 'brain_ingest', 'memory_mgmt', 'agent_mgmt', 'file_ops', 'code_ops') THEN TRUE ELSE FALSE END,
    TRUE,
    CASE WHEN m.module_key IN ('memory_mgmt', 'agent_mgmt') THEN TRUE ELSE FALSE END,
    CASE WHEN m.module_key IN ('memory_mgmt', 'agent_mgmt') THEN TRUE ELSE FALSE END
FROM ag_auth.roles r, ag_system.modules m
WHERE r.role_key = 'member'
  AND m.module_key NOT IN ('user_mgmt', 'integration_config', 'system_settings');

-- Viewer: read-only on core features
INSERT INTO ag_auth.role_permissions (role_id, module_id, can_create, can_read, can_update, can_delete)
SELECT r.role_id, m.module_id, FALSE, TRUE, FALSE, FALSE
FROM ag_auth.roles r, ag_system.modules m
WHERE r.role_key = 'viewer'
  AND m.module_key IN ('ai_chat', 'brain_search', 'memory_mgmt');

-- Agent (service account): create/read on operational features
INSERT INTO ag_auth.role_permissions (role_id, module_id, can_create, can_read, can_update, can_delete)
SELECT r.role_id, m.module_id,
    CASE WHEN m.module_key IN ('brain_ingest', 'memory_mgmt', 'file_ops', 'code_ops') THEN TRUE ELSE FALSE END,
    TRUE,
    CASE WHEN m.module_key IN ('memory_mgmt') THEN TRUE ELSE FALSE END,
    FALSE
FROM ag_auth.roles r, ag_system.modules m
WHERE r.role_key = 'agent'
  AND m.module_key IN ('ai_chat', 'brain_search', 'brain_ingest', 'memory_mgmt', 'file_ops', 'code_ops');

-- 6.4 Default system configuration
INSERT INTO ag_system.configs (config_key, config_value, description, is_secret) VALUES
    ('llm.provider',         'openrouter',                       'LLM API provider',                  FALSE),
    ('llm.model',            'anthropic/claude-sonnet-4',       'Default LLM model',                  FALSE),
    ('llm.api_key',          '',                                 'LLM API key (encrypted)',            TRUE),
    ('llm.max_tokens',       '16000',                            'Max output tokens per request',     FALSE),
    ('llm.temperature',      '0.7',                              'Default temperature',               FALSE),
    ('brain.auto_sync',      'false',                            'Enable automatic data sync',        FALSE),
    ('brain.sync_interval',  '30m',                              'Sync interval (e.g. 30m, 1h)',      FALSE),
    ('memory.session_limit', '50',                               'Max memories per session layer',    FALSE),
    ('memory.decay_days',    '7',                                'Days before session memories decay', FALSE),
    ('agent.max_tools',      '20',                               'Max tools per agent definition',    FALSE),
    ('agent.timeout_seconds','300',                               'Default agent run timeout',         FALSE);

COMMIT;
