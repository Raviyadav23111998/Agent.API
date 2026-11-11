-- ════════════════════════════════════════════════════════════════════════
-- MSYS_V001 — Per-app tenant DB routing  (Antigravity Multi-Tenancy Phase 0)
-- ════════════════════════════════════════════════════════════════════════
-- Target DB: msystems_prod  (the MSystem master / control plane)
-- ADDITIVE ONLY.
--
-- Today tenant_mgmt.tenant_databases is UNIQUE per tenant → one DB per tenant,
-- shared by all apps. Antigravity needs its OWN separate database per tenant
-- (agent_tenant_<id>), so we add an APP dimension via tenant_mgmt.app_databases.
-- This keeps MSystem the single master router for every app (smsystems, fleet,
-- … and now 'agent'), resolving domain → tenant → per-app DB.
--
-- See MULTITENANT_MASTER_PLAN.md §2/§4 (G1) and MULTITENANT_MSYSTEM_ROUTING_ARCHITECTURE.md §3.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

-- 1) Register Antigravity as an app in the catalog (requires its own tenant DB).
INSERT INTO tenant_mgmt.apps
    (app_key, app_name, requires_tenant_db, has_mobile_app, has_website, is_active,
     cloud_zone_config_key, created_at, updated_at)
VALUES
    ('agent', 'Antigravity Agent', TRUE, FALSE, TRUE, TRUE, 'default', NOW(), NOW())
ON CONFLICT (app_key) DO NOTHING;

-- 2) Per-(tenant, app) database routing — the agent DB lives alongside the
--    tenant's SMSystem DB on the same tenant_instances cluster.
CREATE TABLE IF NOT EXISTS tenant_mgmt.app_databases (
    id                   BIGSERIAL PRIMARY KEY,
    tenant_id            UUID    NOT NULL REFERENCES tenant_mgmt.tenants(tenant_id) ON DELETE CASCADE,
    app_id               BIGINT  NOT NULL REFERENCES tenant_mgmt.apps(id),
    instance_id          INTEGER NOT NULL REFERENCES tenant_mgmt.tenant_instances(id),
    db_name              VARCHAR(120) NOT NULL,          -- agent_tenant_<suffix8>
    db_endpoint          VARCHAR(255) NOT NULL,
    db_port              INTEGER      NOT NULL DEFAULT 5432,
    db_user              VARCHAR(120) NOT NULL,          -- agent_app_<suffix8>
    db_password          VARCHAR(255),                   -- plain (dev) — prefer encrypted_conn_pgp
    encrypted_conn_pgp   BYTEA,                          -- same secret model as tenant_databases
    connection_is_secret BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_app_databases_tenant_app UNIQUE (tenant_id, app_id)
);

CREATE INDEX IF NOT EXISTS ix_app_databases_tenant ON tenant_mgmt.app_databases (tenant_id);
CREATE INDEX IF NOT EXISTS ix_app_databases_app    ON tenant_mgmt.app_databases (app_id);

COMMENT ON TABLE tenant_mgmt.app_databases IS
  'Per-(tenant,app) database routing. Antigravity agent DBs (agent_tenant_<id>) '
  'are resolved here by MSystem; one row per (tenant_id, app_id).';

COMMIT;

-- Verify (manual):
--   SELECT app_key, requires_tenant_db FROM tenant_mgmt.apps WHERE app_key='agent';
--   \d tenant_mgmt.app_databases
