-- V022: credential consolidation — ONE home per credential.
-- Two-tier policy made explicit:
--   * Platform/infra config (LLM provider/model/key, embedding, redis,
--     secret.* keys) lives in ag_system.configs, managed via "LLM/System
--     Settings". Single platform-wide values.
--   * Integration credentials (jira, m365/teams, smtp, imap, slack, …) live
--     in the credential vault, per-user/per-org, managed via "Connections".
--
-- This removes the duplicate/dead surfaces that made the vault and config
-- stores look like they disagreed.

-- 1. LLM/AI-model providers are managed in LLM Settings (configs), NOT the
--    credential vault. Hide them from the vault catalog so admins aren't
--    presented two places to set the same key. (resolve() is unaffected — it
--    keys off bindings, not provider is_active.)
UPDATE ag_system.credential_providers
SET is_active = FALSE
WHERE category = 'ai_model';   -- openrouter, google_gemini

-- 2. Remove the dead vault OpenRouter credential (empty config, unreferenced —
--    the live LLM key is llm.api_key in configs) and its binding.
DELETE FROM ag_system.credential_bindings
WHERE credential_id IN (
    SELECT credential_id FROM ag_system.credential_vault
    WHERE provider_key = 'openrouter');
DELETE FROM ag_system.credential_vault WHERE provider_key = 'openrouter';

-- 3. Remove orphaned jira.* config keys — the Jira tool resolves the vault
--    only; these duplicated the vault credential and had no code consumer.
DELETE FROM ag_system.configs
WHERE config_key IN ('jira.api_token', 'jira.email', 'jira.server_url');

-- NOTE intentionally NOT touched:
--  - azure.* configs: sourced from the deploy .env (env→config map); no
--    business-logic consumer (m365 vault credential is authoritative). Harmless;
--    cleaning the .env is a deploy-config task.
--  - neo4j.* / elasticsearch.* configs: the legitimate infra fallback used by
--    the brain when no vault infra credential is set.
--  - smtp.* configs: the platform transactional-SMTP home (OTP email). Empty
--    today; an admin sets server/username/password here OR a vault system smtp
--    credential — EmailService now prefers the vault then falls back to these.
