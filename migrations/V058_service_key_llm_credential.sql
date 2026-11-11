-- ════════════════════════════════════════════════════════════════════════
-- V058 — a service key may carry its own provider credential
-- ════════════════════════════════════════════════════════════════════════
-- A model profile (V035) is a complete identity: provider, model, base_url,
-- api_key. Applications bind to one, and every service key of an
-- application therefore spends on the SAME provider key. That was the right
-- default and it is still the default.
--
-- It stops being enough the day two deployments of one product call the
-- same applications. PrepCrest production and PrepCrest UAT both talk to
-- "PrepCrest Tutor", "PrepCrest Lesson Author" and the rest — same persona,
-- same model, same knowledge — and their spend lands on one OpenRouter key,
-- so one monthly limit, one bill, and no way to say "UAT may spend this
-- much and no more" without also capping production.
--
-- The lever that already exists — resolve_profile's user scope — is the
-- wrong shape for this: a profile bound to the key's service user would win
-- over the application's profile and replace the MODEL too. The evaluators
-- run one model and the authors another; a "UAT" profile would flatten that.
--
-- So the override is narrower than a profile: a CREDENTIAL, on the key.
--
--   service_keys.llm_api_key
--     NULL                          → exactly today's behaviour
--     'sk-or-v1-…'                  → this key's turns use that provider key
--     '__config:llm.api_key.xyz__'  → …the value of that ag_system.configs row
--
-- The sentinel form is the one to use. Sixteen production keys naming ONE
-- config row means rotating the provider key is one UPDATE, and the secret
-- lives in configs (is_secret, never logged) where the platform already
-- keeps it. The auth lookup resolves the sentinel with a LEFT JOIN, so a
-- config row that does not exist yields NULL and the key falls back to the
-- application's profile — with a warning in the log — rather than sending
-- an empty bearer to the provider and failing every turn.
--
-- Model, base_url, temperature and the rest still come from the resolved
-- profile; only api_key is replaced. The usage ledger still books the spend
-- against the profile and the key's service user, as before.
--
-- ADDITIVE + idempotent. Zero behaviour change until a row is set.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE ag_system.service_keys
    ADD COLUMN IF NOT EXISTS llm_api_key TEXT;

COMMENT ON COLUMN ag_system.service_keys.llm_api_key IS
    'Optional provider credential for this key''s turns: a raw key, or __config:<config_key>__ naming an ag_system.configs row. NULL = the application profile''s key. Replaces api_key only — the model stays the profile''s.';

COMMIT;
