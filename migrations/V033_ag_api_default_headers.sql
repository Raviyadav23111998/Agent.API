-- ════════════════════════════════════════════════════════════════════════
-- V033 — ag_api.integrations.default_headers (static headers sent on every call)
-- ════════════════════════════════════════════════════════════════════════
-- Some APIs require a constant header on every request that the LLM can't know —
-- e.g. a multi-tenant backend needs `X-Tenant-Domain: <customer>` to pick the
-- right tenant DB (fleet). These are applied by the executor to every op call,
-- the login exchange, and token refresh; per-arg values still override them.
--
-- ADDITIVE + idempotent. Preserved across re-import (admin-owned, like op flags).
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE ag_api.integrations
    ADD COLUMN IF NOT EXISTS default_headers JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Grant block reused (idempotent).
DO $grant$
DECLARE app_role text;
BEGIN
    SELECT grantee INTO app_role
    FROM information_schema.role_table_grants
    WHERE table_schema = 'ag_system' AND privilege_type = 'SELECT'
      AND grantee NOT IN ('postgres', 'PUBLIC')
    GROUP BY grantee ORDER BY count(*) DESC LIMIT 1;
    IF app_role IS NOT NULL THEN
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ag_api TO %I', app_role);
    END IF;
END $grant$;

COMMIT;
