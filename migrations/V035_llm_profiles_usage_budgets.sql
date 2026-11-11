-- ════════════════════════════════════════════════════════════════════════
-- V035 — per-app/per-user LLM model profiles + usage ledger + budgets
-- ════════════════════════════════════════════════════════════════════════
-- Two features (docs/PER_APP_MODELS_AND_USER_BUDGETS_PLAN_2026-07-04.md):
--
--  1. MODEL SEPARATION — a model is not a string, it is a complete identity
--     (provider, model, base_url, api_key, params). ag_system.llm_profiles
--     holds named profiles; applications and users bind to one. Resolution
--     per turn: agent-definition > request param > user > app > default.
--     The current global llm.* config rows become the DEFAULT profile.
--
--  2. BUDGETS ("like Claude") — ag_system.llm_usage is the per-call ledger
--     (real API-reported tokens, cache-aware cost), written from the single
--     engine choke point. ag_system.budgets holds admin caps per user/app/
--     tenant per window; enforcement is pre-turn (429 + reset time) and
--     mid-turn (graceful wrap-up).
--
-- ADDITIVE + idempotent (IF NOT EXISTS / ON CONFLICT): safe to (re)apply.
-- Zero behavior change until an admin binds a non-default profile or
-- creates a budget row. apps.llm_model / apps.max_tokens_day (dead columns,
-- never read at runtime) are superseded; max_tokens_day values are migrated
-- into budget rows here. The columns are kept one release for rollback.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. Model profiles ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ag_system.llm_profiles (
    profile_id       BIGSERIAL PRIMARY KEY,
    name             VARCHAR(100) NOT NULL,
    provider         VARCHAR(50)  NOT NULL,             -- deepseek|anthropic|openai|zhipu|google|openrouter|...
    model            VARCHAR(200) NOT NULL,             -- provider-native model id
    base_url         VARCHAR(500) NOT NULL,
    api_key          TEXT         NOT NULL DEFAULT '',  -- encrypted-at-rest like config secrets
    small_model      VARCHAR(200),                      -- aux-call routing (compaction/salience)
    fallback_model   VARCHAR(200),
    temperature      NUMERIC(3,2),                      -- NULL = engine default
    max_tokens       INTEGER,
    reasoning_effort VARCHAR(10),                       -- off|low|medium|high (provider-gated)
    is_default       BOOLEAN      NOT NULL DEFAULT FALSE,
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_by       INTEGER,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT llm_profiles_name_uniq UNIQUE (name)
);

-- Exactly one active default profile.
CREATE UNIQUE INDEX IF NOT EXISTS llm_profiles_one_default
    ON ag_system.llm_profiles (is_default) WHERE is_default AND is_active;

-- Bindings (NULL = inherit). Users bind too ("per user separation").
-- Guarded: reduced environments (e.g. SIT) may lack these tables — the
-- feature simply has no app/user bindings there and resolution falls
-- straight to the default profile.
DO $$
BEGIN
    IF to_regclass('ag_system.applications') IS NOT NULL THEN
        ALTER TABLE ag_system.applications
            ADD COLUMN IF NOT EXISTS llm_profile_id BIGINT
            REFERENCES ag_system.llm_profiles(profile_id) ON DELETE SET NULL;
    END IF;
    IF to_regclass('ag_auth.users') IS NOT NULL THEN
        ALTER TABLE ag_auth.users
            ADD COLUMN IF NOT EXISTS llm_profile_id BIGINT
            REFERENCES ag_system.llm_profiles(profile_id) ON DELETE SET NULL;
    END IF;
END $$;

-- ── 2. Usage ledger (one row per LLM call, ALL surfaces) ────────────────
CREATE TABLE IF NOT EXISTS ag_system.llm_usage (
    usage_id          BIGSERIAL PRIMARY KEY,
    ts                TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id           INTEGER,                          -- NULL for pure system work
    app_id            INTEGER,
    conversation_id   VARCHAR(64),
    run_kind          VARCHAR(16) NOT NULL DEFAULT 'chat',  -- chat|bot|cron|subagent|embed|aux
    profile_id        BIGINT,
    model             VARCHAR(200) NOT NULL,
    prompt_tokens     INTEGER     NOT NULL DEFAULT 0,
    completion_tokens INTEGER     NOT NULL DEFAULT 0,
    cached_tokens     INTEGER     NOT NULL DEFAULT 0,
    cost_usd          NUMERIC(12,8) NOT NULL DEFAULT 0
);

-- Budget window scans + usage dashboard aggregations.
CREATE INDEX IF NOT EXISTS llm_usage_user_ts  ON ag_system.llm_usage (user_id, ts);
CREATE INDEX IF NOT EXISTS llm_usage_app_ts   ON ag_system.llm_usage (app_id, ts);
CREATE INDEX IF NOT EXISTS llm_usage_ts       ON ag_system.llm_usage (ts);

-- ── 3. Budgets ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ag_system.budgets (
    budget_id    BIGSERIAL PRIMARY KEY,
    scope_type   VARCHAR(10)  NOT NULL,                 -- user|app|tenant
    scope_id     INTEGER,                               -- NULL for tenant scope
    win          VARCHAR(10)  NOT NULL DEFAULT 'day',   -- day|week|month (UTC windows)
    max_tokens   BIGINT       NOT NULL DEFAULT 0,       -- 0 = no token cap
    max_usd      NUMERIC(12,4) NOT NULL DEFAULT 0,      -- 0 = no money cap
    action       VARCHAR(10)  NOT NULL DEFAULT 'block', -- block|warn
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
    created_by   INTEGER,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT budgets_scope_ck  CHECK (scope_type IN ('user','app','tenant')),
    CONSTRAINT budgets_window_ck CHECK (win IN ('day','week','month')),
    CONSTRAINT budgets_action_ck CHECK (action IN ('block','warn'))
);

-- Uniqueness must treat the tenant scope's NULL scope_id as A VALUE: a
-- plain UNIQUE(scope_type, scope_id, win) considers NULLs distinct, so
-- every tenant-budget save would INSERT a duplicate row (ON CONFLICT never
-- fires on NULL). COALESCE to 0 (no real scope uses id 0).
-- Upgrade path: drop the old-shape constraint if a prior application of
-- this migration created it (it owns an index of the same name).
ALTER TABLE ag_system.budgets DROP CONSTRAINT IF EXISTS budgets_scope_uniq;
CREATE UNIQUE INDEX IF NOT EXISTS budgets_scope_uniq
    ON ag_system.budgets (scope_type, COALESCE(scope_id, 0), win);

-- ── 4. Backfill: default profile from current llm.* config ─────────────
-- The tenant keeps exactly its current behavior — the default profile IS
-- today's global config. api_key stays in configs (secret handling is
-- unchanged this release); the profile row references it by sentinel so the
-- service layer knows to read llm.api_key until keys move into profiles.
INSERT INTO ag_system.llm_profiles
    (name, provider, model, base_url, api_key, small_model, fallback_model,
     temperature, max_tokens, reasoning_effort, is_default, is_active)
SELECT
    'default',
    COALESCE((SELECT config_value FROM ag_system.configs WHERE config_key='llm.provider'      AND is_active), 'deepseek'),
    COALESCE((SELECT config_value FROM ag_system.configs WHERE config_key='llm.model'         AND is_active), 'deepseek-v4-flash'),
    COALESCE((SELECT config_value FROM ag_system.configs WHERE config_key='llm.base_url'      AND is_active), 'https://api.deepseek.com/v1/chat/completions'),
    '__config:llm.api_key__',
    NULLIF((SELECT config_value FROM ag_system.configs WHERE config_key='llm.small_model'     AND is_active), ''),
    NULLIF((SELECT config_value FROM ag_system.configs WHERE config_key='llm.fallback_model'  AND is_active), ''),
    NULLIF((SELECT config_value FROM ag_system.configs WHERE config_key='llm.temperature'     AND is_active), '')::NUMERIC,
    NULLIF((SELECT config_value FROM ag_system.configs WHERE config_key='llm.max_tokens'      AND is_active), '')::INTEGER,
    NULLIF((SELECT config_value FROM ag_system.configs WHERE config_key='llm.reasoning_effort' AND is_active), ''),
    TRUE, TRUE
WHERE NOT EXISTS (SELECT 1 FROM ag_system.llm_profiles WHERE is_default AND is_active);

-- ── 5. Migrate dead apps.max_tokens_day into real budget rows ───────────
DO $$
BEGIN
    IF to_regclass('ag_system.applications') IS NOT NULL THEN
        INSERT INTO ag_system.budgets (scope_type, scope_id, win, max_tokens, action)
        SELECT 'app', a.app_id, 'day', a.max_tokens_day, 'block'
        FROM ag_system.applications a
        WHERE COALESCE(a.max_tokens_day, 0) > 0
        ON CONFLICT (scope_type, COALESCE(scope_id, 0), win) DO NOTHING;
    END IF;
END $$;

-- ── 6. Record migration ─────────────────────────────────────────────────
DO $$
BEGIN
    IF to_regclass('ag_system.migration_history') IS NOT NULL THEN
        INSERT INTO ag_system.migration_history (version, script_name, description)
        VALUES ('V035', 'V035_llm_profiles_usage_budgets.sql', 'llm profiles + usage ledger + budgets (per-app/per-user models, Claude-style limits)')
        ON CONFLICT DO NOTHING;
    END IF;
END $$;

COMMIT;
