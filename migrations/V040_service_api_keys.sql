-- ════════════════════════════════════════════════════════════════════════
-- V040 — service API keys: server-to-server access without a user JWT
-- ════════════════════════════════════════════════════════════════════════
-- Every existing way into the agent assumes a HUMAN behind the request:
--
--   • Authorization: Bearer <RSA JWT>   a signed-in user (api/middleware/auth.py)
--   • ag_pk_… + Origin → session JWT    a browser embed (V025, embed_session_auth)
--
-- Neither fits a BACKEND calling us on behalf of its own end users. A JWT
-- expires in 24h, so a server would have to hold a password and re-login on a
-- timer; and the embed handshake is built around an Origin header and a 15-min
-- browser session, which a server-side caller has neither of.
--
-- So: a long-lived, revocable, hashed API key bound to ONE application (and
-- therefore to one persona and one knowledge scope).
--
--   ag_sk_live_<43 url-safe chars>
--   └────┬────┘
--        └── the prefix is stored in clear for lookup + display ("ag_sk_live_7Kq2…").
--            The key itself is only ever stored as sha256; shown to the admin once.
--
-- ── Why the key carries app_id, not the caller ──────────────────────────
-- app_id is what resolves the persona (ag_system.agent_personas.is_default),
-- the brain/document scope, and the LLM profile + budget. Putting it on the KEY
-- rather than in the request means a compromised key cannot ask to be a
-- different application — the blast radius of a leak is exactly one persona.
--
-- ── Why conversations grow two columns ──────────────────────────────────
-- ag_system.conversations.user_id assumes one row per human. Under a service
-- key the "user" is the calling BACKEND, and the real end user (a PrepCrest
-- learner) is opaque to us. Rather than mint fake user rows — which would land
-- in every admin list, dashboard count and budget query — a service
-- conversation is identified by (service_key_id, end_user_ref):
--
--   service_key_id   which key owns it   → revoking a key orphans nothing else
--   end_user_ref     the caller's OWN id → learner 4821, opaque text to us
--
-- user_id stays populated (the key's service_user_id) so per-user budgets,
-- audit and llm_scope.check_budgets keep working unchanged.
--
-- ADDITIVE + idempotent. Nothing here changes an existing code path: no key
-- rows exist until an admin mints one.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. The keys ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ag_system.service_keys (
    key_id            BIGSERIAL PRIMARY KEY,

    name              VARCHAR(200) NOT NULL,
    description       TEXT         NOT NULL DEFAULT '',

    -- Clear-text, indexed, and NOT a secret: it is the lookup handle and the
    -- only thing we can ever show an admin again. A verify still hashes the
    -- presented key and compares in constant time.
    key_prefix        VARCHAR(32)  NOT NULL,
    key_hash          CHAR(64)     NOT NULL,

    -- The scope the key IS. app_id NOT NULL on purpose: a key that resolves no
    -- application resolves no persona, and a persona-less agent is the
    -- file-prompt fallback this platform deliberately removed.
    app_id            INT          NOT NULL REFERENCES ag_system.applications(app_id),

    -- Pin a specific persona, or NULL to take the app's default. Pinning is for
    -- an app that serves two surfaces (a tutor and a grader) from one scope.
    persona_id        INT          NULL REFERENCES ag_system.agent_personas(persona_id),

    -- Whose budget and audit trail the key spends against. A real user row —
    -- normally the admin who minted it — so llm_scope, dashboards and the token
    -- ledger need no notion of "service" at all.
    service_user_id   INT          NOT NULL,

    -- Coarse capability list. 'chat' is the only verb today; the column exists
    -- so adding 'files' or 'brain' later is a grant, not a migration.
    scopes            JSONB        NOT NULL DEFAULT '["chat"]'::jsonb,

    -- Same shape and same enforcement path as ag_bot.bots.rate_limits (V025):
    -- {"per_session_msg": N, "per_ip_per_min": N, "daily_token_cap": N},
    -- read by EmbedRateLimiter (Redis sliding window, multi-worker correct).
    --
    -- The default DISABLES the per-IP dimension, and that is the whole point.
    -- A backend is ONE address in front of all of its end users, so an per-IP
    -- cap throttles every learner together — the precise flaw that makes the
    -- bot token (30/IP/hour) unusable here. For a service key the meaningful
    -- dimension is per END USER, which the limiter gets via a session key of
    -- "svc:{key_id}:{end_user_ref}".
    rate_limits       JSONB        NOT NULL
        DEFAULT '{"per_session_msg": 120, "per_ip_per_min": 0, "daily_token_cap": 0}'::jsonb,

    -- Empty = any source address. A caller with a static egress IP should fill
    -- this in; it is the cheapest defence a leaked key has.
    allowed_ips       JSONB        NOT NULL DEFAULT '[]'::jsonb,

    is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
    expires_at        TIMESTAMPTZ  NULL,
    revoked_at        TIMESTAMPTZ  NULL,

    -- Written at most once a minute by the auth path (see service_key_repo):
    -- an UPDATE on every request would make a read-only auth check a write.
    last_used_at      TIMESTAMPTZ  NULL,

    created_by        INT          NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_service_key_hash CHECK (length(key_hash) = 64)
);

-- The hash is the identity: two rows with one hash would make "which key was
-- this?" unanswerable in the audit log.
CREATE UNIQUE INDEX IF NOT EXISTS uq_service_keys_hash
    ON ag_system.service_keys (key_hash);

-- Auth reads by prefix (cheap, selective) and then verifies the hash.
CREATE INDEX IF NOT EXISTS ix_service_keys_prefix
    ON ag_system.service_keys (key_prefix) WHERE is_active;

CREATE INDEX IF NOT EXISTS ix_service_keys_app
    ON ag_system.service_keys (app_id);

COMMENT ON TABLE ag_system.service_keys IS
    'Long-lived hashed API keys (ag_sk_live_…) for server-to-server agent access. '
    'Bound to one application, therefore to one persona and one knowledge scope.';
COMMENT ON COLUMN ag_system.service_keys.key_hash IS
    'sha256 of the full key. The raw key is shown to the admin exactly once, at mint.';
COMMENT ON COLUMN ag_system.service_keys.service_user_id IS
    'Real user row the key spends against, so budgets/audit need no service concept.';

-- ── 2. Conversations owned by a key, on behalf of an end user ───────────
ALTER TABLE ag_system.conversations
    ADD COLUMN IF NOT EXISTS service_key_id BIGINT NULL
        REFERENCES ag_system.service_keys(key_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS end_user_ref   TEXT   NULL;

COMMENT ON COLUMN ag_system.conversations.service_key_id IS
    'Set when the conversation was opened by a service key rather than a signed-in user.';
COMMENT ON COLUMN ag_system.conversations.end_user_ref IS
    'The CALLER''s own end-user id (opaque to us). Scopes a service conversation to one '
    'of the caller''s users so one backend cannot read another user''s thread.';

-- The ownership check on every service turn: given a key, an end user and a
-- conversation id, is this thread theirs? Partial — service rows are the
-- minority and human conversations must not pay for this index.
CREATE INDEX IF NOT EXISTS ix_conversations_service_owner
    ON ag_system.conversations (service_key_id, end_user_ref, updated_at DESC)
    WHERE service_key_id IS NOT NULL;

-- ── 3. Audit ────────────────────────────────────────────────────────────
-- Deliberately NO new table. ag_system.audit_log already carries exactly the
-- columns a key event needs — action, entity_type, entity_id, user_id,
-- details_json, ip_address — and user_repo already writes auth events into it
-- under entity_type='auth'. Key events go in as:
--
--   entity_type = 'service_key'
--   entity_id   = <key_id>
--   action      = auth.denied | key.minted | key.rotated | key.revoked
--
-- so one query answers "what happened to this credential" alongside every
-- other security event, instead of two tables nobody remembers to join.
-- Only denials and lifecycle changes are recorded; a successful auth is
-- represented by service_keys.last_used_at, which is far cheaper than a row
-- per request.
CREATE INDEX IF NOT EXISTS ix_audit_log_entity
    ON ag_system.audit_log (entity_type, entity_id, created_at DESC);

-- ── 4. Grants ───────────────────────────────────────────────────────────
-- The table above is created by the migration's superuser, but the API
-- connects as a per-DB role (e.g. <env>_agent_app_<suffix>). A new table does
-- NOT inherit that role's privileges, so without this every request dies at
-- "permission denied for table service_keys" — and because it fails inside the
-- auth path, it surfaces as "Invalid or inactive API key", pointing at the
-- credential rather than at the grant.
--
-- The role is discovered from the existing ag_system grants rather than named,
-- because it differs per database. Mirrors V031_ag_api.sql exactly.
--
-- ag_system already has ALTER DEFAULT PRIVILEGES from V020, but only for roles
-- that existed when it ran; re-granting here is idempotent and covers a role
-- created since.
DO $grant$
DECLARE app_role text;
BEGIN
    SELECT grantee INTO app_role
    FROM information_schema.role_table_grants
    WHERE table_schema = 'ag_system' AND privilege_type = 'SELECT'
      AND grantee NOT IN ('postgres', 'PUBLIC')
    GROUP BY grantee
    ORDER BY count(*) DESC
    LIMIT 1;

    IF app_role IS NOT NULL THEN
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ag_system.service_keys TO %I', app_role);
        EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE ag_system.service_keys_key_id_seq TO %I', app_role);
        RAISE NOTICE 'ag_system.service_keys granted to %', app_role;
    ELSE
        RAISE WARNING 'No application role found on ag_system — grant service_keys by hand.';
    END IF;
END $grant$;

DO $$
BEGIN
    IF to_regclass('ag_system.migration_history') IS NOT NULL THEN
        INSERT INTO ag_system.migration_history (version, script_name, description)
        VALUES ('V040', 'V040_service_api_keys.sql',
                'service API keys (ag_sk_live_) + key-scoped conversations')
        ON CONFLICT DO NOTHING;
    END IF;
END $$;

COMMIT;

-- Verify (manual):
--   SELECT key_id, name, key_prefix, app_id, persona_id, is_active, last_used_at
--   FROM ag_system.service_keys ORDER BY key_id;
