-- ════════════════════════════════════════════════════════════════════════
-- V034 — per-user Telegram channel provider (ag_cred)
-- ════════════════════════════════════════════════════════════════════════
-- Telegram becomes an INDIVIDUAL, per-user channel: each user creates their own
-- bot via @BotFather and connects its token on the Connections page (user scope).
-- The gateway runs one polling bot per connection and routes its messages to the
-- agent AS that user. Replaces the single global env/vault bot.
--
-- ADDITIVE + idempotent. `direct` kind, supports_user so a member can self-serve.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

INSERT INTO ag_cred.providers
    (provider_key, display_name, category, kind, supports_user, supports_verify, sort_order, fields)
VALUES
    ('telegram', 'Telegram (personal bot)', 'channel', 'direct', TRUE, TRUE, 30, '[
       {"key":"bot_token","label":"Bot Token","type":"password","required":true,"secret":true,"scope":"both","help":"Create a bot with @BotFather in Telegram and paste the token it gives you.","placeholder":"123456789:ABCdef..."}
     ]'::jsonb)
ON CONFLICT (provider_key) DO UPDATE SET
    display_name=EXCLUDED.display_name, category=EXCLUDED.category, kind=EXCLUDED.kind,
    supports_user=EXCLUDED.supports_user, supports_verify=EXCLUDED.supports_verify,
    fields=EXCLUDED.fields;

DO $grant$
DECLARE app_role text;
BEGIN
    SELECT grantee INTO app_role FROM information_schema.role_table_grants
    WHERE table_schema='ag_cred' AND privilege_type='SELECT'
      AND grantee NOT IN ('postgres','PUBLIC') GROUP BY grantee ORDER BY count(*) DESC LIMIT 1;
    IF app_role IS NOT NULL THEN
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ag_cred TO %I', app_role);
    END IF;
END $grant$;

COMMIT;
