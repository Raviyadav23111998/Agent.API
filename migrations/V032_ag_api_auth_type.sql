-- ════════════════════════════════════════════════════════════════════════
-- V032 — ag_api.integrations.auth_type (pluggable AuthStrategy id)
-- ════════════════════════════════════════════════════════════════════════
-- Records WHICH auth strategy an integration uses (api_key | bearer_static |
-- basic | hmac | oauth2_client_credentials | oauth2_password | login_grant | …),
-- decoupling the runtime auth from the legacy `security_scheme`. Spec discovery
-- (openapi.discover_auth) now sets it on import; the runtime falls back to
-- `security_scheme` when NULL, so this is purely additive and back-compatible.
--
-- ADDITIVE + idempotent (IF NOT EXISTS / guarded). See docs/INTEGRATION_AUTH_*.md.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE ag_api.integrations ADD COLUMN IF NOT EXISTS auth_type VARCHAR(40);

-- Backfill from the legacy security_scheme so existing integrations keep
-- resolving to the same strategy with an explicit value.
UPDATE ag_api.integrations
SET auth_type = CASE lower(coalesce(security_scheme, ''))
        WHEN 'apikey' THEN 'api_key'
        WHEN 'bearer' THEN 'bearer_static'
        WHEN 'basic'  THEN 'basic'
        WHEN 'oauth2' THEN 'oauth2_client_credentials'
        WHEN 'hmac'   THEN 'hmac'
        WHEN 'custom' THEN 'custom'
        ELSE NULL END
WHERE auth_type IS NULL AND security_scheme IS NOT NULL;

-- Grant block reused (idempotent) — keeps the per-tenant app role's access intact.
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
        RAISE NOTICE 'ag_api re-granted to %', app_role;
    END IF;
END $grant$;

COMMIT;

-- Verify (manual):
--   SELECT slug, security_scheme, auth_type FROM ag_api.integrations ORDER BY slug;
