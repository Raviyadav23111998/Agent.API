-- ════════════════════════════════════════════════════════════════════════
-- V029 — Connections: credential system rebuilt from scratch
-- ════════════════════════════════════════════════════════════════════════
-- Replaces the three-table vault model (credential_providers + credential_vault
-- + credential_bindings) with ONE concept: a Connection.
--
--   ag_cred.providers      registry — provider + kind ('direct'|'shared_app') + field schema
--   ag_cred.connections    one row = "this principal can use this provider"
--                          unique(provider_key, scope, owner_ref) → the row IS the binding
--
-- Why: the binding indirection created a flat context_id keyspace where app:1
-- shadowed user:1; scope was only half-enforced (prod had a USER m365 row
-- carrying org client_id/tenant_id and NO mailbox). Here scope is a column,
-- app rows are keyed by app_uuid, and write-invariants live server-side.
--
-- ADDITIVE: legacy credential_* tables are left intact (read by nothing once
-- consumers are repointed) and dropped later in V030.
--
-- See CREDENTIAL_SYSTEM_REDESIGN.md.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE SCHEMA IF NOT EXISTS ag_cred;

-- ── 1. Provider registry ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ag_cred.providers (
    provider_key    VARCHAR(50)  PRIMARY KEY,
    display_name    VARCHAR(200) NOT NULL,
    category        VARCHAR(50)  NOT NULL DEFAULT 'integration',
    -- 'direct'      → self-contained credential (endpoint + secret).
    -- 'shared_app'  → org row holds the app registration + default identity;
    --                 user/app rows hold ONLY identity (e.g. a mailbox).
    kind            VARCHAR(20)  NOT NULL DEFAULT 'direct',
    -- fields: [{key,label,type,required,secret,scope,help,placeholder}]
    --   scope: 'org' (org row only) | 'identity' (user/app rows) | 'both'
    fields          JSONB        NOT NULL DEFAULT '[]'::jsonb,
    supports_user   BOOLEAN      NOT NULL DEFAULT TRUE,
    supports_verify BOOLEAN      NOT NULL DEFAULT FALSE,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    sort_order      INT          NOT NULL DEFAULT 100,
    icon_url        VARCHAR(500),
    docs_url        VARCHAR(500),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_provider_kind CHECK (kind IN ('direct', 'shared_app'))
);

COMMENT ON TABLE ag_cred.providers IS
  'Credential provider registry. kind drives resolution: direct = self-contained, '
  'shared_app = org app registration merged with per-principal identity.';

-- ── 2. Connections ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ag_cred.connections (
    connection_id    BIGSERIAL PRIMARY KEY,
    provider_key     VARCHAR(50) NOT NULL REFERENCES ag_cred.providers(provider_key),

    -- WHO owns it. owner_ref: org → '' · user → user_id · app → app_uuid.
    -- '' (not NULL) for org so the UNIQUE below actually constrains it.
    scope            VARCHAR(10) NOT NULL,
    owner_ref        VARCHAR(100) NOT NULL DEFAULT '',

    label            VARCHAR(200) NOT NULL DEFAULT 'Default',
    config           JSONB        NOT NULL DEFAULT '{}'::jsonb,   -- NON-secret only
    secret_enc       TEXT,                                        -- fernet; NULL for shared-app identity
    status           VARCHAR(20)  NOT NULL DEFAULT 'unverified',

    last_verified_at TIMESTAMPTZ,
    last_used_at     TIMESTAMPTZ,
    created_by       INT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_conn_scope  CHECK (scope IN ('org', 'user', 'app')),
    CONSTRAINT chk_conn_status CHECK (status IN ('active','unverified','error','disabled')),
    CONSTRAINT chk_conn_owner  CHECK (
        (scope = 'org' AND owner_ref = '')
        OR (scope IN ('user','app') AND owner_ref <> '')
    ),
    -- One connection per principal+provider. The row IS the active binding.
    CONSTRAINT uq_conn UNIQUE (provider_key, scope, owner_ref)
);

CREATE INDEX IF NOT EXISTS idx_conn_provider ON ag_cred.connections(provider_key);
CREATE INDEX IF NOT EXISTS idx_conn_owner    ON ag_cred.connections(scope, owner_ref);

COMMENT ON TABLE ag_cred.connections IS
  'One row per (provider, scope, owner). No separate bindings table — the row is the binding.';

-- ── 3. Seed providers ───────────────────────────────────────────────────
INSERT INTO ag_cred.providers
    (provider_key, display_name, category, kind, supports_user, supports_verify, sort_order, fields)
VALUES
    ('jira', 'Jira Cloud', 'integration', 'direct', TRUE, TRUE, 20, '[
       {"key":"server_url","label":"Jira Server URL","type":"url","required":true,"secret":false,"scope":"both","help":"Your Atlassian Cloud or Server instance URL","placeholder":"https://your-domain.atlassian.net"},
       {"key":"email","label":"Account Email","type":"email","required":true,"secret":false,"scope":"both","help":"Email associated with your Atlassian account","placeholder":"you@company.com"},
       {"key":"api_token","label":"API Token","type":"password","required":true,"secret":true,"scope":"both","help":"id.atlassian.com > Security > API tokens","placeholder":"Enter your Jira API token"}
     ]'::jsonb),

    ('m365', 'Microsoft 365 (Outlook)', 'integration', 'shared_app', TRUE, TRUE, 21, '[
       {"key":"tenant_id","label":"Azure AD Tenant ID","type":"text","required":true,"secret":false,"scope":"org","help":"Azure Portal > Microsoft Entra ID > Overview. Set once by an admin.","placeholder":"xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"},
       {"key":"client_id","label":"Application (Client) ID","type":"text","required":true,"secret":false,"scope":"org","help":"App Registration > Overview. Set once by an admin.","placeholder":"xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"},
       {"key":"client_secret","label":"Client Secret Value","type":"password","required":true,"secret":true,"scope":"org","help":"App Registration > Certificates & Secrets > Value. Set once by an admin.","placeholder":"Enter the client secret value"},
       {"key":"user_email","label":"Mailbox Email","type":"email","required":true,"secret":false,"scope":"identity","help":"The mailbox the agent should access — usually your own work email.","placeholder":"you@company.com"}
     ]'::jsonb),

    ('smtp', 'SMTP Email', 'integration', 'direct', TRUE, TRUE, 22, '[
       {"key":"server","label":"SMTP Server","type":"text","required":true,"secret":false,"scope":"both","help":"SMTP server hostname","placeholder":"smtp.gmail.com"},
       {"key":"port","label":"Port","type":"number","required":true,"secret":false,"scope":"both","help":"Usually 587 (TLS) or 465 (SSL)","placeholder":"587"},
       {"key":"username","label":"Username / Email","type":"text","required":true,"secret":false,"scope":"both","help":"SMTP authentication username","placeholder":"you@gmail.com"},
       {"key":"use_tls","label":"Use TLS","type":"boolean","required":false,"secret":false,"scope":"both","default":true},
       {"key":"password","label":"Password / App Password","type":"password","required":true,"secret":true,"scope":"both","help":"For Gmail, use an App Password","placeholder":"Enter password"}
     ]'::jsonb),

    ('imap', 'IMAP Email', 'integration', 'direct', TRUE, TRUE, 23, '[
       {"key":"server","label":"IMAP Server","type":"text","required":true,"secret":false,"scope":"both","help":"IMAP server hostname","placeholder":"imap.gmail.com"},
       {"key":"port","label":"Port","type":"number","required":false,"secret":false,"scope":"both","help":"Usually 993 (SSL)","placeholder":"993"},
       {"key":"username","label":"Username / Email","type":"text","required":true,"secret":false,"scope":"both","help":"IMAP authentication username","placeholder":"you@gmail.com"},
       {"key":"use_ssl","label":"Use SSL","type":"boolean","required":false,"secret":false,"scope":"both","default":true},
       {"key":"password","label":"Password / App Password","type":"password","required":true,"secret":true,"scope":"both","help":"For Gmail, use an App Password","placeholder":"Enter password"}
     ]'::jsonb),

    ('confluence', 'Confluence', 'integration', 'direct', TRUE, TRUE, 24, '[
       {"key":"url","label":"Base URL","type":"url","required":true,"secret":false,"scope":"both","help":"Your Confluence base URL","placeholder":"https://your-domain.atlassian.net/wiki"},
       {"key":"email","label":"Account Email","type":"email","required":true,"secret":false,"scope":"both","help":"Email associated with your Atlassian account","placeholder":"you@company.com"},
       {"key":"api_token","label":"API Token","type":"password","required":true,"secret":true,"scope":"both","help":"id.atlassian.com > Security > API tokens","placeholder":"Enter your API token"}
     ]'::jsonb)
ON CONFLICT (provider_key) DO NOTHING;

-- ── 3b. Grant the application role access to ag_cred ─────────────────────
-- The schema is created by a superuser during migration, but the app connects
-- as a per-DB role (e.g. <env>_agent_app_<suffix>). Without these grants every
-- query hits "permission denied for schema ag_cred". We discover that role from
-- the existing ag_system grants and mirror them onto ag_cred (idempotent).
DO $grant$
DECLARE app_role text;
BEGIN
    SELECT grantee INTO app_role
    FROM information_schema.role_table_grants
    WHERE table_schema = 'ag_system' AND privilege_type = 'SELECT'
      AND grantee NOT IN ('postgres', 'PUBLIC')
    GROUP BY grantee
    ORDER BY count(*) DESC
    LIMIT 1;

    IF app_role IS NOT NULL THEN
        EXECUTE format('GRANT USAGE ON SCHEMA ag_cred TO %I', app_role);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ag_cred TO %I', app_role);
        EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ag_cred TO %I', app_role);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA ag_cred GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', app_role);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA ag_cred GRANT USAGE, SELECT ON SEQUENCES TO %I', app_role);
        RAISE NOTICE 'ag_cred granted to %', app_role;
    END IF;
END $grant$;

-- ── 4. Backfill from the legacy vault + bindings ────────────────────────
-- The legacy tables (credential_vault/bindings, applications) do NOT exist in
-- every DB — many tenants and control DBs never had them. Each backfill block
-- is therefore guarded with to_regclass() and run via dynamic EXECUTE so a
-- missing table is simply skipped (instead of aborting the whole migration and
-- leaving the DB without ag_cred). All backfills are idempotent.
DO $do$
BEGIN
    -- 4a. ORG connections (from system-owned vault credentials).
    -- 4b. USER connections (shared_app → identity-only; direct → as-is).
    IF to_regclass('ag_system.credential_vault') IS NOT NULL
       AND to_regclass('ag_auth.users') IS NOT NULL THEN

        EXECUTE $q$
            INSERT INTO ag_cred.connections
                (provider_key, scope, owner_ref, label, config, secret_enc, status, created_by, created_at, updated_at)
            SELECT
                v.provider_key, 'org', '', v.label,
                CASE WHEN p.kind = 'shared_app'
                     THEN jsonb_strip_nulls(v.config_json || jsonb_build_object(
                              'user_email',
                              COALESCE(NULLIF(v.config_json->>'user_email',''),
                                       (SELECT email FROM ag_auth.users ORDER BY user_id LIMIT 1))))
                     ELSE v.config_json END,
                v.secret_enc,
                CASE WHEN v.status IN ('active','unverified','error','disabled') THEN v.status ELSE 'active' END,
                v.created_by, v.created_at, NOW()
            FROM ag_system.credential_vault v
            JOIN ag_cred.providers p ON p.provider_key = v.provider_key
            WHERE v.owner_type = 'system' AND v.is_active = TRUE
            ON CONFLICT (provider_key, scope, owner_ref) DO NOTHING
        $q$;

        EXECUTE $q$
            INSERT INTO ag_cred.connections
                (provider_key, scope, owner_ref, label, config, secret_enc, status, created_by, created_at, updated_at)
            SELECT
                v.provider_key, 'user', v.owner_id::text, v.label,
                CASE WHEN p.kind = 'shared_app'
                     THEN jsonb_strip_nulls(jsonb_build_object(
                              'user_email',
                              COALESCE(NULLIF(v.config_json->>'user_email',''), u.email)))
                     ELSE v.config_json END,
                CASE WHEN p.kind = 'shared_app' THEN NULL ELSE v.secret_enc END,
                CASE WHEN v.status IN ('active','unverified','error','disabled') THEN v.status ELSE 'active' END,
                v.created_by, v.created_at, NOW()
            FROM ag_system.credential_vault v
            JOIN ag_cred.providers p ON p.provider_key = v.provider_key
            LEFT JOIN ag_auth.users u ON u.user_id = v.owner_id
            WHERE v.owner_type = 'user' AND v.is_active = TRUE
            ON CONFLICT (provider_key, scope, owner_ref) DO NOTHING
        $q$;
    END IF;

    -- 4c. APP connections — DIRECT providers only, keyed by app_uuid (never
    -- numeric). shared_app app-bindings are dropped on purpose (those resolve
    -- via the org default), which retires the bogus app:1→user-m365 binding.
    IF to_regclass('ag_system.credential_bindings') IS NOT NULL
       AND to_regclass('ag_system.credential_vault') IS NOT NULL
       AND to_regclass('ag_system.applications') IS NOT NULL THEN

        EXECUTE $q$
            INSERT INTO ag_cred.connections
                (provider_key, scope, owner_ref, label, config, secret_enc, status, created_by, created_at, updated_at)
            SELECT
                v.provider_key, 'app', a.app_uuid::text, v.label, v.config_json, v.secret_enc,
                CASE WHEN v.status IN ('active','unverified','error','disabled') THEN v.status ELSE 'active' END,
                v.created_by, v.created_at, NOW()
            FROM ag_system.credential_bindings b
            JOIN ag_system.credential_vault v ON v.credential_id = b.credential_id AND v.is_active = TRUE
            JOIN ag_cred.providers p ON p.provider_key = v.provider_key AND p.kind = 'direct'
            JOIN ag_system.applications a ON a.app_id::text = b.context_id
            WHERE b.context_type = 'app' AND b.is_active = TRUE
            ON CONFLICT (provider_key, scope, owner_ref) DO NOTHING
        $q$;
    END IF;
END $do$;

COMMIT;

-- Verify (manual):
--   SELECT provider_key, kind FROM ag_cred.providers ORDER BY sort_order;
--   SELECT provider_key, scope, owner_ref, config, (secret_enc IS NOT NULL) has_secret, status
--     FROM ag_cred.connections ORDER BY provider_key, scope, owner_ref;
