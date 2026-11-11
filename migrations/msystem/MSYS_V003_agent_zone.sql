-- ════════════════════════════════════════════════════════════════════════
-- MSYS_V003 — Dedicated cloud zone for the Antigravity Agent app
-- ════════════════════════════════════════════════════════════════════════
-- Target DB: msystems_prod  (the MSystem master / control plane; also msystems_uat)
-- ADDITIVE / idempotent.
--
-- WHY: MSYS_V001 registered the 'agent' app with cloud_zone_config_key='default',
-- which is the SCHOOL zone (base_domain = storeglanceedu.com, origin gateway.storeglanceedu.com).
-- Onboarding an agent tenant would therefore build {tenant}.storeglanceedu.com — colliding
-- with schools and serving the wrong origin.
--
-- This migration gives the agent its OWN apex zone, exactly mirroring how schools use
-- storeglanceedu.com and fleet uses storeglancefleet.com:
--     config_key  = 'agent'
--     base_domain = 'storeglanceai.com'           ← {tenant}.storeglanceai.com (1 level under apex → *.storeglanceai.com Universal SSL)
-- and re-points apps.app_key='agent' → cloud_zone_config_key='agent'.
--
-- See MULTITENANT_AGENT_DOMAIN_IMPLEMENTATION_PLAN.md §3 (TLS rationale) + Phase 3,
-- and MULTITENANT_URL_DOMAIN_ARCHITECTURE.md §4.3.
--
-- ┌────────────────────────────────────────────────────────────────────────┐
-- │ BLOCKER (Phase 0): storeglanceai.com must be registered and added to the    │
-- │ existing Cloudflare account FIRST, to obtain the zone_id + Universal SSL. │
-- │ Until then, fill the placeholders below with the live values.            │
-- └────────────────────────────────────────────────────────────────────────┘
--
-- ENCRYPTION: zone_id and api_token are stored ENCRYPTED at rest
-- (FieldEncryptor, AES-256-GCM, format  ENC:base64(nonce12|ct|tag16)).
-- Pure SQL cannot encrypt — you MUST paste the already-encrypted ENC:… strings,
-- produced with the env's Security:FieldEncryptionKey. Two ways to get them:
--   (a) run MSystems' FieldEncryptor against the plaintext zone_id / shared CF token, or
--   (b) insert via the MSystem app/admin path that encrypts on write.
-- CloudZoneConfigRepository.DecryptSensitiveFields decrypts these on read.
-- ════════════════════════════════════════════════════════════════════════

-- ── Parameters: replace the four placeholders below per environment ──────
--   :AGENT_ZONE_ID_ENC   ENC:… encryption of the storeglanceai.com Cloudflare zone_id (Phase 0.4)
--   :AGENT_API_TOKEN_ENC ENC:… encryption of the shared Cloudflare account API token
--   :AGENT_ORIGIN        CNAME target for tenant subdomains (proxied A-record → VPS),
--                        e.g. 'lb.storeglance.com' (reuse existing) or 'app.storeglanceai.com'
--   base_domain          'storeglanceai.com' (prod). For UAT use a separate zone
--                        'uat-storeglanceai.com' to keep tenants 1 level under apex (see §7).

BEGIN;

-- 1) Create/refresh the dedicated 'agent' cloud zone config.
INSERT INTO tenant_mgmt.cloud_zone_configs
    (config_key, provider, base_domain, origin_server, fallback_origin,
     zone_id, api_token, is_active, created_at, updated_at)
SELECT
    'agent', 'cloudflare', 'storeglanceai.com',
    'REPLACE_AGENT_ORIGIN',          -- :AGENT_ORIGIN  (e.g. lb.storeglance.com)
    'REPLACE_AGENT_ORIGIN',          -- fallback_origin (same; used for BYO custom domains)
    'ENC:REPLACE_ZONE_ID',           -- :AGENT_ZONE_ID_ENC
    'ENC:REPLACE_API_TOKEN',         -- :AGENT_API_TOKEN_ENC
    TRUE, NOW(), NOW()
WHERE NOT EXISTS (
    SELECT 1 FROM tenant_mgmt.cloud_zone_configs WHERE config_key = 'agent');

-- If the row already exists (e.g. re-run with corrected values), refresh the
-- non-secret fields. Secrets are only set when still placeholders, so a real
-- ENC:… value pasted by hand is never clobbered by a re-run.
UPDATE tenant_mgmt.cloud_zone_configs
SET base_domain     = 'storeglanceai.com',
    provider        = 'cloudflare',
    origin_server   = 'REPLACE_AGENT_ORIGIN',
    fallback_origin = 'REPLACE_AGENT_ORIGIN',
    is_active       = TRUE,
    updated_at      = NOW()
WHERE config_key = 'agent';

-- 2) Re-point the agent app from the school 'default' zone to its own 'agent' zone.
UPDATE tenant_mgmt.apps
SET cloud_zone_config_key = 'agent',
    updated_at            = NOW()
WHERE app_key = 'agent'
  AND cloud_zone_config_key IS DISTINCT FROM 'agent';

COMMIT;

-- ── Verify (manual) ──────────────────────────────────────────────────────
--   SELECT config_key, base_domain, origin_server, is_active,
--          left(zone_id, 4) AS zone_enc, left(api_token, 4) AS tok_enc
--     FROM tenant_mgmt.cloud_zone_configs WHERE config_key = 'agent';
--   -- zone_enc / tok_enc should read 'ENC:'  (i.e. encrypted, not placeholders)
--   SELECT app_key, cloud_zone_config_key FROM tenant_mgmt.apps WHERE app_key = 'agent';
--   -- → agent | agent
