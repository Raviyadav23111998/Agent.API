-- ════════════════════════════════════════════════════════════════════════
-- V024 — Retire the vestigial 'platform_security' vault provider
-- ════════════════════════════════════════════════════════════════════════
-- 'platform_security' (JWT/encryption keys) was registered as a credential
-- vault provider, but those keys actually live in ag_system.configs under the
-- `secret.*` group (System Configuration → "Security & Keys"), read by
-- core/security.py via app_config. The vault provider:
--   • has NO credentials and NO bindings,
--   • is referenced by ZERO lines of code,
--   • showed up as an empty, confusing card in Connections that duplicated the
--     Security & Keys group on the System Configuration page.
--
-- Removing it gives a clean 2-surface model:
--   • Connections          → integration credentials (jira, m365, slack, smtp …)
--   • System Configuration → platform/infra/behavior + JWT/encryption (secret.*)
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

-- Safety: only delete if it truly has no creds/bindings (it shouldn't).
DELETE FROM ag_system.credential_bindings WHERE provider_key = 'platform_security';
DELETE FROM ag_system.credential_vault     WHERE provider_key = 'platform_security';
DELETE FROM ag_system.credential_providers WHERE provider_key = 'platform_security';

COMMIT;

-- Verify (run manually):
--   SELECT provider_key, category FROM ag_system.credential_providers ORDER BY 1;
--   -- 'platform_security' should be gone; secret.* configs remain in System Configuration.
