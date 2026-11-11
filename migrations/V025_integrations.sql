-- ════════════════════════════════════════════════════════════════════════
-- V025 — Embed Agent Platform: Integration identity & security (Phase 1)
-- ════════════════════════════════════════════════════════════════════════
-- Evolve ag_bot.bots into the unified "integration" model. ADDITIVE ONLY —
-- existing chatbots keep working unchanged (mode defaults to 'chat').
--
--   mode             'chat' | 'copilot'      (capability tier)
--   publishable_key  'ag_pk_…'               (goes in the <script>, public)
--   secret_key_enc   Fernet('ag_sk_…')       (server-side; needed to verify
--                                             HMAC end-user identities; raw shown once)
--   guardrail_policy jsonb                    (action policy, DLP, egress)
--   rate_limits      jsonb                    (per-integration/session/IP caps)
--
-- Reused as-is: allowed_domains (origins), persona_id (tool boundary),
-- app_id (knowledge scope), is_active (status).
-- See EMBED_AGENT_PLATFORM_ARCHITECTURE.md §3 + Appendix A #1.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE ag_bot.bots
    ADD COLUMN IF NOT EXISTS mode             TEXT  NOT NULL DEFAULT 'chat',
    ADD COLUMN IF NOT EXISTS publishable_key  TEXT,
    ADD COLUMN IF NOT EXISTS secret_key_enc   TEXT,
    ADD COLUMN IF NOT EXISTS guardrail_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS rate_limits      JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Constrain mode to the known capability tiers.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bots_mode_chk') THEN
        ALTER TABLE ag_bot.bots
            ADD CONSTRAINT bots_mode_chk CHECK (mode IN ('chat', 'copilot'));
    END IF;
END $$;

-- Backfill a deterministic publishable key for existing bots (derived from the
-- already-unique bot_uuid). New integrations mint a random key in code.
UPDATE ag_bot.bots
SET publishable_key = 'ag_pk_' || replace(bot_uuid::text, '-', '')
WHERE publishable_key IS NULL;

-- Enforce uniqueness once backfilled.
CREATE UNIQUE INDEX IF NOT EXISTS bots_publishable_key_uq
    ON ag_bot.bots (publishable_key);

COMMIT;

-- Verify (manual):
--   SELECT bot_id, name, mode, left(publishable_key,14)||'…' AS pk,
--          (secret_key_enc IS NOT NULL) AS has_secret
--   FROM ag_bot.bots ORDER BY bot_id;
