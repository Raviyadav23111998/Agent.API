-- ════════════════════════════════════════════════════════════════════════
-- V023 — Credential cleanup: remove dead/duplicate records & fallbacks
-- ════════════════════════════════════════════════════════════════════════
-- Final consolidation of the credential model after V021 (m365 org-app split)
-- and V022 (LLM → configs). Establishes a single source of truth per concern:
--
--   • Integrations (m365, jira, smtp, imap, slack, confluence) → credential vault
--   • Infrastructure (neo4j, elasticsearch)                    → ag_system.configs
--   • LLM / platform (llm.*, secret.*)                         → ag_system.configs
--
-- Everything removed below is a verified duplicate or dead record:
--   1. azure.* configs       — duplicate of the live vault m365 cred (cred 2),
--                              which is now the only M365 source in code.
--   2. ai_model providers     — openrouter/google_gemini deactivated in V022;
--                              LLM creds live in configs. Remove the dead rows.
--   3. empty smtp.* configs   — unconfigured placeholders; SMTP is a vault
--                              integration provider.
--   4. neo4j / elasticsearch  — infra belongs in configs. The vault neo4j cred
--      vault creds + bindings   was already overridden by neo4j.* configs in
--      + provider rows          cli.py (uri==localhost path); the es vault cred
--                              had no binding and resolved to None. Both dead.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

-- 1. azure.* — duplicate of the vault m365 app registration.
DELETE FROM ag_system.configs
WHERE config_key IN (
    'azure.tenant_id', 'azure.client_id', 'azure.client_secret', 'azure.user_email'
);

-- 2. Dead inactive ai_model providers (LLM now lives in ag_system.configs).
DELETE FROM ag_system.credential_providers
WHERE provider_key IN ('openrouter', 'google_gemini');

-- 3. Empty/unconfigured smtp.* placeholders (SMTP is a vault integration).
DELETE FROM ag_system.configs
WHERE config_key IN (
    'smtp.from', 'smtp.password', 'smtp.port',
    'smtp.server', 'smtp.use_tls', 'smtp.username'
);

-- 4. Move infrastructure (neo4j, elasticsearch) out of the vault entirely.
--    Order matters: bindings → vault creds → providers (FK-safe).
DELETE FROM ag_system.credential_bindings  WHERE provider_key IN ('neo4j', 'elasticsearch');
DELETE FROM ag_system.credential_vault     WHERE provider_key IN ('neo4j', 'elasticsearch');
DELETE FROM ag_system.credential_providers WHERE provider_key IN ('neo4j', 'elasticsearch');

COMMIT;

-- Verification (run manually after apply):
--   SELECT provider_key, is_active FROM ag_system.credential_providers ORDER BY provider_key;
--   SELECT config_key FROM ag_system.configs WHERE config_key ~* 'azure|smtp' ORDER BY 1;
--   SELECT provider_key, count(*) FROM ag_system.credential_vault GROUP BY 1 ORDER BY 1;
