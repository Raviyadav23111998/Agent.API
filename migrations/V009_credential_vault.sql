-- ============================================================================
-- V009: Credential Vault — Enterprise Credential Architecture
-- ============================================================================
--
-- Three-table design:
--   1. credential_providers — Schema registry (what each service needs)
--   2. credential_vault     — Encrypted credential storage (password manager)
--   3. credential_bindings  — Links contexts to credentials (IAM-style)
--
-- Resolution at runtime:
--   User context:   user binding ONLY (no fallback to system)
--   App context:    app binding → system binding
--   System context: system binding ONLY
--
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. Provider Registry
-- ============================================================================
-- Defines what each external service/provider needs. Drives the UI forms.
-- Admins can add new providers without code changes.
-- ============================================================================

CREATE TABLE IF NOT EXISTS ag_system.credential_providers (
    provider_key    VARCHAR(50) PRIMARY KEY,
    display_name    VARCHAR(200) NOT NULL,
    category        VARCHAR(50) NOT NULL DEFAULT 'integration',
    config_schema   JSONB NOT NULL DEFAULT '{}',
    icon_url        VARCHAR(500),
    docs_url        VARCHAR(500),
    supports_user   BOOLEAN NOT NULL DEFAULT TRUE,
    supports_verify BOOLEAN NOT NULL DEFAULT FALSE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order      INT NOT NULL DEFAULT 100,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),

    CONSTRAINT chk_provider_category CHECK (category IN (
        'infrastructure', 'ai_model', 'integration', 'platform'
    ))
);

COMMENT ON TABLE ag_system.credential_providers IS
    'Schema registry for external service providers. Drives UI forms and validation.';
COMMENT ON COLUMN ag_system.credential_providers.supports_user IS
    'If TRUE, regular users can create personal credentials for this provider.';
COMMENT ON COLUMN ag_system.credential_providers.config_schema IS
    'JSON schema defining non-secret config fields (server_url, email, port, etc.)';

-- ============================================================================
-- 2. Credential Vault
-- ============================================================================
-- The "password manager". Each row = one stored credential.
-- A user can have MULTIPLE credentials per provider (e.g., "Work Jira", "Client Jira").
-- System credentials are owned by owner_type='system', owner_id IS NULL.
-- ============================================================================

CREATE TABLE IF NOT EXISTS ag_system.credential_vault (
    credential_id   BIGSERIAL PRIMARY KEY,

    -- What provider
    provider_key    VARCHAR(50) NOT NULL
                    REFERENCES ag_system.credential_providers(provider_key),

    -- Who owns this credential (who stored it)
    owner_type      VARCHAR(20) NOT NULL DEFAULT 'user',
    owner_id        INT,

    -- Human-readable label (e.g., "Work Jira", "Personal Gmail SMTP")
    label           VARCHAR(200) NOT NULL DEFAULT 'Default',

    -- Non-secret config (server, port, email, tenant_id, etc.)
    config_json     JSONB NOT NULL DEFAULT '{}',

    -- Fernet-encrypted secret (api_token, password, client_secret)
    -- Can hold JSON string if provider has multiple secrets
    secret_enc      TEXT,

    -- Status tracking
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    status          VARCHAR(30) NOT NULL DEFAULT 'active',
    last_verified   TIMESTAMPTZ,
    last_used_at    TIMESTAMPTZ,

    -- Audit
    created_by      INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),

    CONSTRAINT chk_vault_owner CHECK (
        (owner_type = 'system' AND owner_id IS NULL)
        OR (owner_type = 'user' AND owner_id IS NOT NULL)
    ),
    CONSTRAINT chk_vault_owner_type CHECK (owner_type IN ('system', 'user')),
    CONSTRAINT chk_vault_status CHECK (status IN (
        'active', 'error', 'expired', 'revoked', 'unverified'
    ))
);

CREATE INDEX IF NOT EXISTS idx_vault_provider
    ON ag_system.credential_vault(provider_key);
CREATE INDEX IF NOT EXISTS idx_vault_owner
    ON ag_system.credential_vault(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_vault_active
    ON ag_system.credential_vault(provider_key, owner_id)
    WHERE is_active = TRUE;

COMMENT ON TABLE ag_system.credential_vault IS
    'Encrypted credential storage. Each row = one stored credential. Users can have multiple per provider.';
COMMENT ON COLUMN ag_system.credential_vault.secret_enc IS
    'Fernet-encrypted secret value (api_token, password, client_secret). Decrypted at runtime by CredentialRegistry.';
COMMENT ON COLUMN ag_system.credential_vault.label IS
    'Human-readable label so users can distinguish multiple creds for the same provider.';

-- ============================================================================
-- 3. Credential Bindings
-- ============================================================================
-- IAM-style bindings. Links a context (user/app/system) to a specific
-- credential from the vault.
--
-- Resolution rules (enforced in application layer):
--   User context:   user binding ONLY (never falls back to system)
--   App context:    app binding → system binding
--   System context: system binding ONLY
--
-- One active binding per (context_type, context_id, provider_key).
-- ============================================================================

CREATE TABLE IF NOT EXISTS ag_system.credential_bindings (
    binding_id      BIGSERIAL PRIMARY KEY,

    -- WHO is using it
    context_type    VARCHAR(20) NOT NULL,
    context_id      VARCHAR(100) NOT NULL,

    -- What provider
    provider_key    VARCHAR(50) NOT NULL
                    REFERENCES ag_system.credential_providers(provider_key),

    -- Which credential from the vault
    credential_id   BIGINT NOT NULL
                    REFERENCES ag_system.credential_vault(credential_id)
                    ON DELETE CASCADE,

    -- Metadata
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),

    -- One active binding per (context + provider)
    CONSTRAINT uq_binding UNIQUE (context_type, context_id, provider_key),
    CONSTRAINT chk_binding_context CHECK (context_type IN ('system', 'user', 'app'))
);

CREATE INDEX IF NOT EXISTS idx_binding_context
    ON ag_system.credential_bindings(context_type, context_id);
CREATE INDEX IF NOT EXISTS idx_binding_cred
    ON ag_system.credential_bindings(credential_id);

COMMENT ON TABLE ag_system.credential_bindings IS
    'IAM-style bindings linking contexts (user/app/system) to vault credentials.';
COMMENT ON COLUMN ag_system.credential_bindings.context_type IS
    'system = global infra, user = personal, app = cron job / automated workflow';
COMMENT ON COLUMN ag_system.credential_bindings.context_id IS
    'system → __system__, user → user_id as string, app → app_id (e.g. email_triage)';

-- ============================================================================
-- 4. Seed Provider Registry
-- ============================================================================

INSERT INTO ag_system.credential_providers
    (provider_key, display_name, category, supports_user, supports_verify, sort_order, config_schema)
VALUES
    ('openrouter',   'OpenRouter (LLM)',
     'ai_model', FALSE, TRUE, 10,
     '{"fields": [{"key": "model", "label": "Default Model", "type": "text", "required": false}]}'::jsonb),

    ('google_gemini', 'Google Gemini',
     'ai_model', FALSE, TRUE, 11,
     '{"fields": [{"key": "cache_model", "label": "Cache Model", "type": "text", "required": false}, {"key": "cache_ttl", "label": "Cache TTL (seconds)", "type": "number", "required": false}]}'::jsonb),

    ('jira',          'Jira Cloud',
     'integration', TRUE, TRUE, 20,
     '{"fields": [{"key": "server_url", "label": "Server URL", "type": "url", "required": true}, {"key": "email", "label": "Email", "type": "email", "required": true}]}'::jsonb),

    ('m365',          'Microsoft 365 (Outlook)',
     'integration', TRUE, TRUE, 21,
     '{"fields": [{"key": "tenant_id", "label": "Tenant ID", "type": "text", "required": true}, {"key": "client_id", "label": "Client ID", "type": "text", "required": true}, {"key": "user_email", "label": "User Email", "type": "email", "required": true}]}'::jsonb),

    ('smtp',          'SMTP Email',
     'integration', TRUE, TRUE, 22,
     '{"fields": [{"key": "server", "label": "SMTP Server", "type": "text", "required": true}, {"key": "port", "label": "Port", "type": "number", "required": true}, {"key": "username", "label": "Username", "type": "text", "required": true}, {"key": "use_tls", "label": "Use TLS", "type": "boolean", "required": false}]}'::jsonb),

    ('imap',          'IMAP Email',
     'integration', TRUE, TRUE, 23,
     '{"fields": [{"key": "server", "label": "IMAP Server", "type": "text", "required": true}, {"key": "port", "label": "Port", "type": "number", "required": false}, {"key": "username", "label": "Username", "type": "text", "required": true}, {"key": "use_ssl", "label": "Use SSL", "type": "boolean", "required": false}]}'::jsonb),

    ('confluence',    'Confluence',
     'integration', TRUE, TRUE, 24,
     '{"fields": [{"key": "url", "label": "Base URL", "type": "url", "required": true}, {"key": "email", "label": "Email", "type": "email", "required": true}]}'::jsonb),

    ('slack',         'Slack',
     'integration', FALSE, TRUE, 25,
     '{"fields": []}'::jsonb),

    ('neo4j',         'Neo4j Graph DB',
     'infrastructure', FALSE, FALSE, 50,
     '{"fields": [{"key": "uri", "label": "Bolt URI", "type": "text", "required": true}, {"key": "user", "label": "Username", "type": "text", "required": true}]}'::jsonb),

    ('elasticsearch', 'Elasticsearch',
     'infrastructure', FALSE, FALSE, 51,
     '{"fields": [{"key": "url", "label": "URL", "type": "url", "required": true}, {"key": "index", "label": "Default Index", "type": "text", "required": false}]}'::jsonb),

    ('telegram',      'Telegram Bot',
     'platform', FALSE, FALSE, 60,
     '{"fields": [{"key": "allowed_users", "label": "Allowed User IDs (comma-separated)", "type": "text", "required": false}, {"key": "home_channel", "label": "Home Channel ID", "type": "text", "required": false}]}'::jsonb),

    ('platform_security', 'Platform Security (JWT/Encryption)',
     'platform', FALSE, FALSE, 70,
     '{"fields": [{"key": "issuer", "label": "JWT Issuer", "type": "text", "required": false}, {"key": "audience", "label": "JWT Audience", "type": "text", "required": false}, {"key": "token_expiry_minutes", "label": "Token Expiry (min)", "type": "number", "required": false}, {"key": "refresh_token_expiry_days", "label": "Refresh Token Expiry (days)", "type": "number", "required": false}]}'::jsonb)
ON CONFLICT (provider_key) DO NOTHING;


-- ============================================================================
-- 5. Migrate Existing Data
-- ============================================================================
-- Move data from ag_system.integrations and ag_system.configs into the vault.
-- Old tables are NOT dropped — they remain for backward compat during transition.
-- ============================================================================

-- 5a. Migrate per-user integrations (smtp_1, m365_1, imap_1, etc.)
--     These follow the pattern: service_key = '{provider}_{user_id}'
INSERT INTO ag_system.credential_vault
    (provider_key, owner_type, owner_id, label, config_json, secret_enc, is_active, status, created_at, updated_at)
SELECT
    SPLIT_PART(i.service_key, '_', 1) AS provider_key,
    'user' AS owner_type,
    CAST(SPLIT_PART(i.service_key, '_', 2) AS INT) AS owner_id,
    COALESCE(i.display_name, 'Migrated') AS label,
    COALESCE(i.config_json, '{}'::jsonb) AS config_json,
    i.credentials_enc AS secret_enc,
    i.is_enabled AS is_active,
    i.status,
    i.created_at,
    i.updated_at
FROM ag_system.integrations i
WHERE i.service_key ~ '^[a-z]+_[0-9]+$'
  AND SPLIT_PART(i.service_key, '_', 1) IN ('smtp', 'm365', 'imap')
  AND NOT EXISTS (
    SELECT 1 FROM ag_system.credential_vault v
    WHERE v.provider_key = SPLIT_PART(i.service_key, '_', 1)
      AND v.owner_type = 'user'
      AND v.owner_id = CAST(SPLIT_PART(i.service_key, '_', 2) AS INT)
  );

-- 5b. Auto-create bindings for migrated user credentials
INSERT INTO ag_system.credential_bindings
    (context_type, context_id, provider_key, credential_id)
SELECT
    'user' AS context_type,
    CAST(v.owner_id AS VARCHAR) AS context_id,
    v.provider_key,
    v.credential_id
FROM ag_system.credential_vault v
WHERE v.owner_type = 'user'
  AND v.is_active = TRUE
  AND NOT EXISTS (
    SELECT 1 FROM ag_system.credential_bindings b
    WHERE b.context_type = 'user'
      AND b.context_id = CAST(v.owner_id AS VARCHAR)
      AND b.provider_key = v.provider_key
  );

-- 5c. Migrate global Jira from ag_system.configs → system credential
DO $$
DECLARE
    v_server TEXT;
    v_email TEXT;
    v_token TEXT;
    v_cred_id BIGINT;
BEGIN
    SELECT config_value INTO v_server FROM ag_system.configs WHERE config_key = 'jira.server_url' AND is_active = TRUE;
    SELECT config_value INTO v_email  FROM ag_system.configs WHERE config_key = 'jira.email' AND is_active = TRUE;
    SELECT config_value INTO v_token  FROM ag_system.configs WHERE config_key = 'jira.api_token' AND is_active = TRUE;

    IF v_server IS NOT NULL AND v_token IS NOT NULL THEN
        INSERT INTO ag_system.credential_vault
            (provider_key, owner_type, owner_id, label, config_json, secret_enc, is_active, status)
        VALUES
            ('jira', 'system', NULL, 'System Jira (migrated)',
             jsonb_build_object('server_url', v_server, 'email', COALESCE(v_email, '')),
             v_token, TRUE, 'active')
        ON CONFLICT DO NOTHING
        RETURNING credential_id INTO v_cred_id;

        IF v_cred_id IS NOT NULL THEN
            INSERT INTO ag_system.credential_bindings
                (context_type, context_id, provider_key, credential_id)
            VALUES ('system', '__system__', 'jira', v_cred_id)
            ON CONFLICT DO NOTHING;
        END IF;
    END IF;
END $$;

-- 5d. Migrate global Azure/M365 from configs → system credential
DO $$
DECLARE
    v_tenant TEXT;
    v_client_id TEXT;
    v_client_secret TEXT;
    v_user_email TEXT;
    v_cred_id BIGINT;
BEGIN
    SELECT config_value INTO v_tenant       FROM ag_system.configs WHERE config_key = 'azure.tenant_id' AND is_active = TRUE;
    SELECT config_value INTO v_client_id    FROM ag_system.configs WHERE config_key = 'azure.client_id' AND is_active = TRUE;
    SELECT config_value INTO v_client_secret FROM ag_system.configs WHERE config_key = 'azure.client_secret' AND is_active = TRUE;
    SELECT config_value INTO v_user_email   FROM ag_system.configs WHERE config_key = 'azure.user_email' AND is_active = TRUE;

    IF v_tenant IS NOT NULL AND v_client_id IS NOT NULL THEN
        INSERT INTO ag_system.credential_vault
            (provider_key, owner_type, owner_id, label, config_json, secret_enc, is_active, status)
        VALUES
            ('m365', 'system', NULL, 'System M365 (migrated)',
             jsonb_build_object('tenant_id', v_tenant, 'client_id', v_client_id, 'user_email', COALESCE(v_user_email, '')),
             v_client_secret, TRUE, 'active')
        ON CONFLICT DO NOTHING
        RETURNING credential_id INTO v_cred_id;

        IF v_cred_id IS NOT NULL THEN
            INSERT INTO ag_system.credential_bindings
                (context_type, context_id, provider_key, credential_id)
            VALUES ('system', '__system__', 'm365', v_cred_id)
            ON CONFLICT DO NOTHING;
        END IF;
    END IF;
END $$;

-- 5e. Migrate global OpenRouter API key → system credential
DO $$
DECLARE
    v_api_key TEXT;
    v_cred_id BIGINT;
BEGIN
    SELECT config_value INTO v_api_key FROM ag_system.configs WHERE config_key = 'llm.api_key' AND is_active = TRUE;

    IF v_api_key IS NOT NULL THEN
        INSERT INTO ag_system.credential_vault
            (provider_key, owner_type, owner_id, label, config_json, secret_enc, is_active, status)
        VALUES
            ('openrouter', 'system', NULL, 'System OpenRouter (migrated)',
             '{}'::jsonb, v_api_key, TRUE, 'active')
        ON CONFLICT DO NOTHING
        RETURNING credential_id INTO v_cred_id;

        IF v_cred_id IS NOT NULL THEN
            INSERT INTO ag_system.credential_bindings
                (context_type, context_id, provider_key, credential_id)
            VALUES ('system', '__system__', 'openrouter', v_cred_id)
            ON CONFLICT DO NOTHING;
        END IF;
    END IF;
END $$;

-- 5f. Migrate Neo4j credentials → system credential
DO $$
DECLARE
    v_uri TEXT;
    v_user TEXT;
    v_pass TEXT;
    v_cred_id BIGINT;
BEGIN
    SELECT config_value INTO v_uri  FROM ag_system.configs WHERE config_key = 'neo4j.uri' AND is_active = TRUE;
    SELECT config_value INTO v_user FROM ag_system.configs WHERE config_key = 'neo4j.user' AND is_active = TRUE;
    SELECT config_value INTO v_pass FROM ag_system.configs WHERE config_key = 'neo4j.password' AND is_active = TRUE;

    IF v_uri IS NOT NULL THEN
        INSERT INTO ag_system.credential_vault
            (provider_key, owner_type, owner_id, label, config_json, secret_enc, is_active, status)
        VALUES
            ('neo4j', 'system', NULL, 'System Neo4j (migrated)',
             jsonb_build_object('uri', v_uri, 'user', COALESCE(v_user, 'neo4j')),
             v_pass, TRUE, 'active')
        ON CONFLICT DO NOTHING
        RETURNING credential_id INTO v_cred_id;

        IF v_cred_id IS NOT NULL THEN
            INSERT INTO ag_system.credential_bindings
                (context_type, context_id, provider_key, credential_id)
            VALUES ('system', '__system__', 'neo4j', v_cred_id)
            ON CONFLICT DO NOTHING;
        END IF;
    END IF;
END $$;

-- 5g. Migrate Elasticsearch → system credential
DO $$
DECLARE
    v_url TEXT;
    v_index TEXT;
    v_cred_id BIGINT;
BEGIN
    SELECT config_value INTO v_url   FROM ag_system.configs WHERE config_key = 'elasticsearch.url' AND is_active = TRUE;
    SELECT config_value INTO v_index FROM ag_system.configs WHERE config_key = 'elasticsearch.index' AND is_active = TRUE;

    IF v_url IS NOT NULL THEN
        INSERT INTO ag_system.credential_vault
            (provider_key, owner_type, owner_id, label, config_json, secret_enc, is_active, status)
        VALUES
            ('elasticsearch', 'system', NULL, 'System Elasticsearch (migrated)',
             jsonb_build_object('url', v_url, 'index', COALESCE(v_index, 'brain')),
             NULL, TRUE, 'active')
        ON CONFLICT DO NOTHING
        RETURNING credential_id INTO v_cred_id;

        IF v_cred_id IS NOT NULL THEN
            INSERT INTO ag_system.credential_bindings
                (context_type, context_id, provider_key, credential_id)
            VALUES ('system', '__system__', 'elasticsearch', v_cred_id)
            ON CONFLICT DO NOTHING;
        END IF;
    END IF;
END $$;

-- 5h. Migrate Telegram bot → system credential
DO $$
DECLARE
    v_token TEXT;
    v_allowed TEXT;
    v_channel TEXT;
    v_cred_id BIGINT;
BEGIN
    SELECT config_value INTO v_token   FROM ag_system.configs WHERE config_key = 'telegram.bot_token' AND is_active = TRUE;
    SELECT config_value INTO v_allowed FROM ag_system.configs WHERE config_key = 'telegram.allowed_users' AND is_active = TRUE;
    SELECT config_value INTO v_channel FROM ag_system.configs WHERE config_key = 'telegram.home_channel' AND is_active = TRUE;

    IF v_token IS NOT NULL THEN
        INSERT INTO ag_system.credential_vault
            (provider_key, owner_type, owner_id, label, config_json, secret_enc, is_active, status)
        VALUES
            ('telegram', 'system', NULL, 'System Telegram Bot (migrated)',
             jsonb_build_object('allowed_users', COALESCE(v_allowed, ''), 'home_channel', COALESCE(v_channel, '')),
             v_token, TRUE, 'active')
        ON CONFLICT DO NOTHING
        RETURNING credential_id INTO v_cred_id;

        IF v_cred_id IS NOT NULL THEN
            INSERT INTO ag_system.credential_bindings
                (context_type, context_id, provider_key, credential_id)
            VALUES ('system', '__system__', 'telegram', v_cred_id)
            ON CONFLICT DO NOTHING;
        END IF;
    END IF;
END $$;

-- 5i. Migrate platform security keys → system credential
DO $$
DECLARE
    v_private_key TEXT;
    v_public_key TEXT;
    v_enc_key TEXT;
    v_issuer TEXT;
    v_audience TEXT;
    v_token_exp TEXT;
    v_refresh_exp TEXT;
    v_cred_id BIGINT;
BEGIN
    SELECT config_value INTO v_private_key FROM ag_system.configs WHERE config_key = 'secret.jwt_private_key' AND is_active = TRUE;
    SELECT config_value INTO v_public_key  FROM ag_system.configs WHERE config_key = 'secret.jwt_public_key' AND is_active = TRUE;
    SELECT config_value INTO v_enc_key     FROM ag_system.configs WHERE config_key = 'secret.encryption_key' AND is_active = TRUE;
    SELECT config_value INTO v_issuer      FROM ag_system.configs WHERE config_key = 'jwt.issuer' AND is_active = TRUE;
    SELECT config_value INTO v_audience    FROM ag_system.configs WHERE config_key = 'jwt.audience' AND is_active = TRUE;
    SELECT config_value INTO v_token_exp   FROM ag_system.configs WHERE config_key = 'jwt.token_expiry_minutes' AND is_active = TRUE;
    SELECT config_value INTO v_refresh_exp FROM ag_system.configs WHERE config_key = 'jwt.refresh_token_expiry_days' AND is_active = TRUE;

    IF v_private_key IS NOT NULL THEN
        INSERT INTO ag_system.credential_vault
            (provider_key, owner_type, owner_id, label, config_json, secret_enc, is_active, status)
        VALUES
            ('platform_security', 'system', NULL, 'Platform Security Keys (migrated)',
             jsonb_build_object(
                'issuer', COALESCE(v_issuer, 'agent'),
                'audience', COALESCE(v_audience, 'agent-web'),
                'token_expiry_minutes', COALESCE(v_token_exp, '60'),
                'refresh_token_expiry_days', COALESCE(v_refresh_exp, '30')
             ),
             -- Store all security secrets as JSON-encoded string
             jsonb_build_object(
                'private_key', v_private_key,
                'public_key', COALESCE(v_public_key, ''),
                'encryption_key', COALESCE(v_enc_key, '')
             )::text,
             TRUE, 'active')
        ON CONFLICT DO NOTHING
        RETURNING credential_id INTO v_cred_id;

        IF v_cred_id IS NOT NULL THEN
            INSERT INTO ag_system.credential_bindings
                (context_type, context_id, provider_key, credential_id)
            VALUES ('system', '__system__', 'platform_security', v_cred_id)
            ON CONFLICT DO NOTHING;
        END IF;
    END IF;
END $$;


COMMIT;
