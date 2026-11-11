-- ════════════════════════════════════════════════════════════════════════
-- V031 — ag_api: external API integration catalog (dynamic, spec-derived tools)
-- ════════════════════════════════════════════════════════════════════════
-- Turns any external HTTP API (OpenAPI 3.x / Swagger 2.0 / MCP) — public SaaS OR
-- a tenant's OWN internal business API — into governed, retrieval-selected agent
-- tools with NO per-provider Python class. Sibling to ag_cred (credentials):
--
--   ag_api.integrations        one row per imported API (spec + base_url + auth ref)
--   ag_api.operations          one row per endpoint → one tool ({slug}__{operationId})
--   ag_api.integration_grants  binds an integration to apps/personas (who may use it)
--
-- Auth reuses ag_cred: ingest materializes an ag_cred.providers row ('api_{slug}')
-- and credentials resolve per-tenant via Connections.resolve(provider,user,app).
-- Vector column mirrors ag_brain (pgvector 0.8.0, vector(768), HNSW cosine).
--
-- ADDITIVE + idempotent (IF NOT EXISTS): safe to (re)apply on any tenant DB even
-- where ag_system.migration_history under-records. Inert until the feature flag
-- `agent.dynamic_integrations` is enabled per tenant.
--
-- NOTE: named ag_api (NOT "integrations") to avoid colliding with the embeddable
-- bot platform — ag_bot.bots is the "integration" in that sense (V025).
-- See API_INTEGRATION_IMPLEMENTATION_PLAN.md §3 + §5A.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE SCHEMA IF NOT EXISTS ag_api;

-- ── 1. Integrations (one per imported API) ──────────────────────────────
CREATE TABLE IF NOT EXISTS ag_api.integrations (
    integration_id   BIGSERIAL PRIMARY KEY,
    slug             VARCHAR(50)  NOT NULL,            -- "acme_crm" (tool namespace)
    display_name     VARCHAR(200) NOT NULL,
    base_url         VARCHAR(500) NOT NULL,
    spec_kind        VARCHAR(20)  NOT NULL,            -- openapi | swagger | mcp
    spec_raw         JSONB,                            -- original spec (re-derivable)
    spec_hash        VARCHAR(64)  NOT NULL,            -- change detection on re-import
    auth_provider    VARCHAR(50)  REFERENCES ag_cred.providers(provider_key),
    security_scheme  VARCHAR(20),                      -- apiKey|bearer|basic|oauth2|custom|hmac|mtls
    auth_config      JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- {in,name,...} / signing recipe
    status           VARCHAR(20)  NOT NULL DEFAULT 'active',
    egress_allow     JSONB        NOT NULL DEFAULT '[]'::jsonb,  -- extra allowed hosts (admin opt-in)
    allow_private    BOOLEAN      NOT NULL DEFAULT FALSE,        -- internal API (admin-confirmed SSRF override)
    created_by       INT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_api_slug    UNIQUE (slug),
    CONSTRAINT chk_api_status CHECK (status IN ('active', 'disabled')),
    CONSTRAINT chk_api_kind   CHECK (spec_kind IN ('openapi', 'swagger', 'mcp'))
);

COMMENT ON TABLE ag_api.integrations IS
  'External API catalog. One row per imported spec. Auth joins ag_cred.providers; '
  'credentials resolve per-tenant via Connections.resolve.';

-- ── 2. Operations (one per endpoint → one tool) ─────────────────────────
CREATE TABLE IF NOT EXISTS ag_api.operations (
    operation_pk      BIGSERIAL PRIMARY KEY,
    integration_id    BIGINT NOT NULL REFERENCES ag_api.integrations(integration_id) ON DELETE CASCADE,
    operation_id      VARCHAR(120) NOT NULL,           -- from spec (operationId)
    tool_name         VARCHAR(160) NOT NULL,           -- "{slug}__{operationId}"
    http_method       VARCHAR(10)  NOT NULL,
    path_template     VARCHAR(500) NOT NULL,
    summary           TEXT,
    description       TEXT,
    parameters_schema JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- full JSON Schema the LLM fills
    request_map       JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- where each arg goes: {path:[],query:[],header:[],has_body:bool}
    side_effect       VARCHAR(20)  NOT NULL DEFAULT 'write',      -- read|write|irreversible (from method)
    requires_approval BOOLEAN      NOT NULL DEFAULT TRUE,
    enabled           BOOLEAN      NOT NULL DEFAULT TRUE,
    embed_safe        BOOLEAN      NOT NULL DEFAULT FALSE,        -- opt-in: reachable by anon chatbot visitors
    response_transform JSONB,                                     -- optional trim/summarize rule
    rate_limit        JSONB,                                      -- optional per-op caps
    embedding         vector(768),                                -- pgvector; NULL until embedded
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_op       UNIQUE (integration_id, operation_id),
    CONSTRAINT chk_op_side CHECK (side_effect IN ('read', 'write', 'irreversible'))
);

CREATE INDEX IF NOT EXISTS idx_op_tool    ON ag_api.operations(tool_name);
CREATE INDEX IF NOT EXISTS idx_op_enabled ON ag_api.operations(integration_id, enabled);
-- Vector index mirrors ag_brain (HNSW cosine). Wrapped in DO so a build without
-- the vector opclass available still completes the rest of the migration.
DO $idx$
BEGIN
    CREATE INDEX IF NOT EXISTS idx_op_embed ON ag_api.operations
        USING hnsw (embedding vector_cosine_ops);
EXCEPTION WHEN undefined_object OR feature_not_supported THEN
    RAISE NOTICE 'ag_api.operations HNSW index skipped (vector opclass unavailable)';
END $idx$;

COMMENT ON TABLE ag_api.operations IS
  'One row per API endpoint. tool_name = {slug}__{operationId}. parameters_schema is '
  'a full JSON Schema passed verbatim to the OpenAI function definition.';

-- ── 3. Grants (which apps/personas may use an integration) ──────────────
-- The persona allowed_tools whitelist is exact-name and will not scale to N ops;
-- a grant is expanded to concrete op names at the filter site (chat_service /
-- embed_sandbox) by effective_allowed_tools(). See plan §5A.
CREATE TABLE IF NOT EXISTS ag_api.integration_grants (
    grant_id        BIGSERIAL PRIMARY KEY,
    integration_id  BIGINT NOT NULL REFERENCES ag_api.integrations(integration_id) ON DELETE CASCADE,
    scope           VARCHAR(10) NOT NULL,             -- 'app' | 'persona' | 'org'
    ref             VARCHAR(100) NOT NULL DEFAULT '', -- app_id | persona_id | '' (org = all apps)
    op_filter       JSONB,                            -- NULL = all enabled ops; else ["op_a","op_b"]
    created_by      INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_grant      UNIQUE (integration_id, scope, ref),
    CONSTRAINT chk_grant_scope CHECK (scope IN ('app', 'persona', 'org')),
    CONSTRAINT chk_grant_owner CHECK (
        (scope = 'org' AND ref = '') OR (scope IN ('app', 'persona') AND ref <> '')
    )
);

CREATE INDEX IF NOT EXISTS idx_grant_lookup ON ag_api.integration_grants(scope, ref);

COMMENT ON TABLE ag_api.integration_grants IS
  'Binds an integration to apps/personas. Expanded to op tool_names at the persona/'
  'embed filter site so the exact-name whitelist keeps working unchanged.';

COMMENT ON SCHEMA ag_api IS
  'External API integration catalog — dynamic, spec-derived, governed agent tools.';

-- ── 4. Grant the application role access to ag_api ──────────────────────
-- The schema is created by a superuser during migration, but the app connects
-- as a per-DB role (e.g. <env>_agent_app_<suffix>). Without these grants every
-- query hits "permission denied for schema ag_api". We discover that role from
-- the existing ag_system grants and mirror them onto ag_api (idempotent).
-- Mirrors V029_connections_rebuild.sql §3b exactly.
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
        EXECUTE format('GRANT USAGE ON SCHEMA ag_api TO %I', app_role);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ag_api TO %I', app_role);
        EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ag_api TO %I', app_role);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA ag_api GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', app_role);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA ag_api GRANT USAGE, SELECT ON SEQUENCES TO %I', app_role);
        RAISE NOTICE 'ag_api granted to %', app_role;
    END IF;
END $grant$;

COMMIT;

-- Verify (manual):
--   \dn ag_api
--   SELECT indexname FROM pg_indexes WHERE schemaname='ag_api';
--   SELECT slug, spec_kind, auth_provider, status, allow_private FROM ag_api.integrations;
--   SELECT tool_name, http_method, side_effect, requires_approval, enabled,
--          (embedding IS NOT NULL) AS embedded FROM ag_api.operations ORDER BY operation_pk;
