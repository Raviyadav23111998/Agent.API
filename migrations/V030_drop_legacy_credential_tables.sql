-- ════════════════════════════════════════════════════════════════════════
-- V030 — Retire the legacy credential vault (run AFTER the Connections code
--        is deployed and verified in every environment).
-- ════════════════════════════════════════════════════════════════════════
-- V029 created ag_cred.{providers,connections} and backfilled them from the
-- legacy tables. Once the runtime resolves exclusively through core/connections
-- (no import of the deleted credential_registry remains), the old tables are
-- dead weight. This drops them, plus the V029 row-level backups.
--
-- DO NOT run this until:
--   1. core/connections.py is live everywhere (grep: no `credential_registry`
--      construction, no `ag_system.credential_vault` reads in app code).
--   2. A smoke test confirms M365 / Jira / SMTP resolve via ag_cred.connections.
--
-- This is destructive and NOT reversible (the V029 backfill already captured
-- the data into ag_cred; the *_bak_v029 tables are the last raw copy).
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

DROP TABLE IF EXISTS ag_system.credential_bindings CASCADE;
DROP TABLE IF EXISTS ag_system.credential_vault CASCADE;
DROP TABLE IF EXISTS ag_system.credential_providers CASCADE;

-- V029 raw backups — keep one release after the drop, then remove these too.
-- DROP TABLE IF EXISTS ag_system.credential_vault_bak_v029;
-- DROP TABLE IF EXISTS ag_system.credential_bindings_bak_v029;

COMMIT;
