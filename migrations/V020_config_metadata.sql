-- ============================================================================
-- V020: Config Metadata + Seed All Known Keys
-- ============================================================================
-- Adds metadata columns to ag_system.configs and ensures all config keys
-- used by the engine/API exist as rows (not just hardcoded DEFAULTS).
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. Add metadata columns (if not already present)
-- ============================================================================

ALTER TABLE ag_system.configs
    ADD COLUMN IF NOT EXISTS config_type     VARCHAR(20) DEFAULT 'text',
    ADD COLUMN IF NOT EXISTS config_group    VARCHAR(50) DEFAULT '',
    ADD COLUMN IF NOT EXISTS sort_order      INT DEFAULT 100,
    ADD COLUMN IF NOT EXISTS requires_restart BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN ag_system.configs.config_type IS
    'UI input type: text, number, boolean, password, select, textarea';
COMMENT ON COLUMN ag_system.configs.config_group IS
    'Logical group prefix (llm, agent, brain, memory, auth, secret, smtp, etc.)';
COMMENT ON COLUMN ag_system.configs.requires_restart IS
    'If TRUE, changes to this key need a process restart to take effect';


-- ============================================================================
-- 2. Seed all known config keys (upsert — only fills gaps)
-- ============================================================================
-- Keys that already exist in the DB keep their current values.
-- This ensures every key the UI needs to display has a row.

INSERT INTO ag_system.configs (config_key, config_value, is_secret, description, config_type, config_group, sort_order, requires_restart)
VALUES
    -- LLM (additional keys not seeded in V001)
    ('llm.fallback_model',        '',       FALSE, 'Fallback model when primary fails',                    'text',     'llm',  10, FALSE),
    ('llm.small_model',           '',       FALSE, 'Cheap model for classification, routing, compaction',  'text',     'llm',  11, FALSE),
    ('llm.context_window',        '0',      FALSE, 'Primary model context window in tokens (0=use fixed budget)', 'number', 'llm', 12, FALSE),
    ('llm.embedding_model',       '',       FALSE, 'Model for embeddings (activates vector RAG)',          'text',     'llm',  13, FALSE),
    ('llm.embedding_base_url',    '',       FALSE, 'API endpoint for embeddings',                          'text',     'llm',  14, FALSE),
    ('llm.embedding_api_key',     '',       TRUE,  'API key for embedding endpoint',                       'password', 'llm',  15, FALSE),
    ('llm.embedding_dimensions',  '768',    FALSE, 'Embedding vector dimensions',                          'number',  'llm',  16, FALSE),
    ('llm.prompt_caching',        'true',   FALSE, 'Enable Anthropic prompt caching',                      'boolean', 'llm',  17, FALSE),
    ('llm.debug_dump_payload',    'false',  FALSE, 'Write raw LLM payloads to temp/ for debug',            'boolean', 'llm',  18, FALSE),

    -- Agent
    ('agent.max_concurrent_turns',      '8',           FALSE, 'Max concurrent agent turns per process',          'number',  'agent', 20, FALSE),
    ('agent.conversation_token_budget', '0',           FALSE, 'Max cumulative tokens per conversation (0=unlimited)', 'number', 'agent', 21, FALSE),
    ('agent.compaction_llm',            'false',       FALSE, 'Use LLM for context compaction',                  'boolean', 'agent', 22, FALSE),
    ('agent.memory_llm_salience',       'false',       FALSE, 'Use LLM to distill auto-memories',                'boolean', 'agent', 23, FALSE),
    ('agent.planning_enabled',          'true',        FALSE, 'Enable explicit planning for complex tasks',      'boolean', 'agent', 24, FALSE),
    ('agent.tool_result_guard',         'true',        FALSE, 'Scan tool output for injection patterns',         'boolean', 'agent', 25, FALSE),
    ('agent.approval_mode',             'irreversible',FALSE, 'When to require human approval (none/irreversible/all)', 'select', 'agent', 26, FALSE),
    ('agent.data_dir',                  '.ag_data',    FALSE, 'Path to the agent data directory',                        'text',   'agent', 27, FALSE),

    -- Auth
    ('auth.login_max_failures',     '5',   FALSE, 'Failed login attempts before lockout',           'number',  'auth', 30, FALSE),
    ('auth.login_window_seconds',   '300', FALSE, 'Sliding window for counting failures (seconds)', 'number', 'auth', 31, FALSE),
    ('auth.login_lockout_seconds',  '900', FALSE, 'Lockout duration after max failures (seconds)',   'number', 'auth', 32, FALSE),

    -- SMTP
    ('smtp.server',   '', FALSE, 'SMTP server hostname',          'text',     'smtp', 40, FALSE),
    ('smtp.port',     '587', FALSE, 'SMTP port',                  'number',   'smtp', 41, FALSE),
    ('smtp.username', '', FALSE, 'SMTP login username',            'text',     'smtp', 42, FALSE),
    ('smtp.password', '', TRUE,  'SMTP login password',            'password', 'smtp', 43, FALSE),
    ('smtp.use_tls',  'true', FALSE, 'Use STARTTLS encryption',   'boolean',  'smtp', 44, FALSE),
    ('smtp.from',     '', FALSE, 'Sender email address',           'text',     'smtp', 45, FALSE),

    -- Redis
    ('redis.url', '', FALSE, 'Redis connection URL (empty=disabled)', 'text', 'redis', 50, FALSE),

    -- Gateway
    ('gateway.platform', 'telegram', FALSE, 'Primary gateway platform adapter', 'select', 'gateway', 60, FALSE),

    -- Workspace
    ('workspace.root',             '/var/agent-workspaces', FALSE, 'Root path for user workspaces',    'text',   'workspace', 70, FALSE),
    ('workspace.default_quota_mb', '500',                   FALSE, 'Default disk quota per workspace', 'number', 'workspace', 71, FALSE),
    ('workspace.tenant_id',        'default',               FALSE, 'Tenant identifier for scoping',    'text',   'workspace', 72, FALSE),

    -- Shell
    ('shell.os_sandbox', 'auto', FALSE, 'OS sandbox mode (auto/off/require)', 'select', 'shell', 80, FALSE),

    -- App
    ('app.env', 'development', FALSE, 'Application environment (development/staging/production)', 'select', 'app', 90, FALSE),

    -- Bot
    ('bot.approval_mode', 'irreversible', FALSE, 'Bot widget approval mode', 'select', 'bot', 100, FALSE)

ON CONFLICT (config_key) DO UPDATE SET
    description = COALESCE(NULLIF(ag_system.configs.description, ''), EXCLUDED.description),
    config_type = COALESCE(NULLIF(ag_system.configs.config_type, 'text'), EXCLUDED.config_type),
    config_group = COALESCE(NULLIF(ag_system.configs.config_group, ''), EXCLUDED.config_group),
    sort_order = CASE WHEN ag_system.configs.sort_order = 100 THEN EXCLUDED.sort_order ELSE ag_system.configs.sort_order END,
    requires_restart = EXCLUDED.requires_restart;


-- ============================================================================
-- 3. Backfill metadata on existing V001 seed keys
-- ============================================================================

UPDATE ag_system.configs SET config_group = 'llm',    config_type = 'text',     sort_order = 1  WHERE config_key = 'llm.provider'        AND config_group = '';
UPDATE ag_system.configs SET config_group = 'llm',    config_type = 'text',     sort_order = 2  WHERE config_key = 'llm.model'           AND config_group = '';
UPDATE ag_system.configs SET config_group = 'llm',    config_type = 'password', sort_order = 3  WHERE config_key = 'llm.api_key'         AND config_group = '';
UPDATE ag_system.configs SET config_group = 'llm',    config_type = 'number',   sort_order = 4  WHERE config_key = 'llm.max_tokens'      AND config_group = '';
UPDATE ag_system.configs SET config_group = 'llm',    config_type = 'text',     sort_order = 5  WHERE config_key = 'llm.temperature'     AND config_group = '';
UPDATE ag_system.configs SET config_group = 'llm',    config_type = 'text',     sort_order = 6  WHERE config_key = 'llm.base_url'        AND config_group = '';
UPDATE ag_system.configs SET config_group = 'llm',    config_type = 'text',     sort_order = 7  WHERE config_key = 'llm.provider_order'  AND config_group = '';
UPDATE ag_system.configs SET config_group = 'brain',  config_type = 'boolean',  sort_order = 1  WHERE config_key = 'brain.auto_sync'     AND config_group = '';
UPDATE ag_system.configs SET config_group = 'brain',  config_type = 'text',     sort_order = 2  WHERE config_key = 'brain.sync_interval' AND config_group = '';
UPDATE ag_system.configs SET config_group = 'memory', config_type = 'number',   sort_order = 1  WHERE config_key = 'memory.session_limit' AND config_group = '';
UPDATE ag_system.configs SET config_group = 'memory', config_type = 'number',   sort_order = 2  WHERE config_key = 'memory.decay_days'   AND config_group = '';
UPDATE ag_system.configs SET config_group = 'agent',  config_type = 'number',   sort_order = 1  WHERE config_key = 'agent.max_tools'     AND config_group = '';
UPDATE ag_system.configs SET config_group = 'agent',  config_type = 'number',   sort_order = 2  WHERE config_key = 'agent.timeout_seconds' AND config_group = '';
UPDATE ag_system.configs SET config_group = 'agent',  config_type = 'number',   sort_order = 3  WHERE config_key = 'agent.history_token_budget' AND (config_group = '' OR config_group IS NULL);

-- Security keys
UPDATE ag_system.configs SET config_group = 'secret', config_type = 'password', sort_order = 1, requires_restart = TRUE WHERE config_key LIKE 'secret.%' AND config_group = '';
UPDATE ag_system.configs SET config_group = 'secret', config_type = 'text',     sort_order = 5, requires_restart = TRUE WHERE config_key LIKE 'jwt.%'    AND config_group = '';

-- Database
UPDATE ag_system.configs SET config_group = 'db', config_type = 'text', requires_restart = TRUE WHERE config_key LIKE 'db.%' AND config_group = '';

-- Infra
UPDATE ag_system.configs SET config_group = 'neo4j',         config_type = 'text' WHERE config_key LIKE 'neo4j.%'         AND config_group = '';
UPDATE ag_system.configs SET config_group = 'elasticsearch', config_type = 'text' WHERE config_key LIKE 'elasticsearch.%' AND config_group = '';
UPDATE ag_system.configs SET config_group = 'gateway',       config_type = 'text' WHERE config_key LIKE 'gateway.%'       AND config_group = '';
UPDATE ag_system.configs SET config_group = 'azure',         config_type = 'text' WHERE config_key LIKE 'azure.%'         AND config_group = '';
UPDATE ag_system.configs SET config_group = 'jira',          config_type = 'text' WHERE config_key LIKE 'jira.%'          AND config_group = '';


-- ============================================================================
-- 4. Grant permissions to all application users
-- ============================================================================
-- The ALTER TABLE runs as 'postgres' (table owner), but the app connects
-- as agent_*_user. Ensure all three environments have full DML access.

DO $$
DECLARE
    u TEXT;
    s TEXT;
BEGIN
    FOR u IN SELECT unnest(ARRAY['agent_uat_user', 'agent_prod_user', 'agent_sit_user'])
    LOOP
        -- Schema-level usage
        FOR s IN SELECT nspname FROM pg_namespace WHERE nspname LIKE 'ag_%'
        LOOP
            EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I', s, u);
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO %I', s, u);
            EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO %I', s, u);
        END LOOP;

        -- Default privileges for future objects in ag_system
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA ag_system GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', u);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA ag_system GRANT USAGE, SELECT ON SEQUENCES TO %I', u);
    END LOOP;
END$$;


-- ============================================================================
-- 5. Record migration
-- ============================================================================

INSERT INTO ag_system.migration_history (version, script_name, description)
VALUES ('V020', 'V020_config_metadata.sql', 'Config metadata columns + seed all known keys for System Config Hub + grants')
ON CONFLICT DO NOTHING;

COMMIT;

