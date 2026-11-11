-- ═══════════════════════════════════════════════════════════════════════
-- V011: Persona-Level Guardrails (Input / Execution / Output)
-- ═══════════════════════════════════════════════════════════════════════
-- Adds 3-layer security guardrails to ag_system.agent_personas:
--
--   1. input_guardrail_prompt  — Injected into system prompt as a hard
--                                 security boundary before the LLM sees input.
--   2. execution_policies      — IAM-style JSON rules evaluated before
--                                 any tool callback fires.
--   3. output_dlp_patterns     — Regex patterns for deterministic DLP
--                                 redaction on the final response.
--   4. output_semantic_rules   — Natural-language rules evaluated by the
--                                 LLM itself as a post-generation filter.
--
-- Design Decision:
--   Guardrails live on PERSONA (not Application) because one Application
--   can have multiple personas with different security profiles
--   (e.g. "Customer Bot" vs "Admin Bot" under the same App).
-- ═══════════════════════════════════════════════════════════════════════

BEGIN;

-- ══════════════════════════════════════════════════════════════════════
-- 1. ENSURE agent_personas TABLE EXISTS
-- ══════════════════════════════════════════════════════════════════════
-- This table may have been created manually on the VPS but has no
-- migration. This CREATE IF NOT EXISTS ensures idempotent deployment.

CREATE TABLE IF NOT EXISTS ag_system.agent_personas (
    persona_id                    SERIAL PRIMARY KEY,
    app_id                        INT NOT NULL REFERENCES ag_system.applications(app_id),
    name                          VARCHAR(100) NOT NULL,
    description                   TEXT DEFAULT '',
    identity_prompt               TEXT,
    constraints_prompt            TEXT,
    communication_prompt          TEXT DEFAULT 'Be concise, friendly, and professional. Use markdown formatting.',
    allowed_tools                 JSONB DEFAULT '[]',
    disable_passivity_correction  BOOLEAN DEFAULT TRUE,
    is_default                    BOOLEAN DEFAULT FALSE,
    is_active                     BOOLEAN DEFAULT TRUE,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ══════════════════════════════════════════════════════════════════════
-- 2. ADD GUARDRAIL COLUMNS
-- ══════════════════════════════════════════════════════════════════════

-- 2.1 Input Guardrail: hard security boundary injected into system prompt
ALTER TABLE ag_system.agent_personas
    ADD COLUMN IF NOT EXISTS input_guardrail_prompt TEXT;

-- 2.2 Execution Guardrail: IAM-style JSON policies per tool + argument
--     Example: {"jira_update_ticket": {"status": {"$not_in": ["Closed"]}}}
ALTER TABLE ag_system.agent_personas
    ADD COLUMN IF NOT EXISTS execution_policies JSONB DEFAULT '{}';

-- 2.3 Output Guardrail (Regex): deterministic DLP patterns
--     Example: ["SCRUM-\\d+", "(?i)password\\s*[:=]\\s*\\S+"]
ALTER TABLE ag_system.agent_personas
    ADD COLUMN IF NOT EXISTS output_dlp_patterns JSONB DEFAULT '[]';

-- 2.4 Output Guardrail (Semantic): natural-language rules for LLM filter
--     Example: "Never reveal internal IP addresses or server architecture."
ALTER TABLE ag_system.agent_personas
    ADD COLUMN IF NOT EXISTS output_semantic_rules TEXT;


-- ══════════════════════════════════════════════════════════════════════
-- 3. ENSURE persona_id FK ON bots TABLE
-- ══════════════════════════════════════════════════════════════════════

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ag_bot' AND table_name = 'bots'
        AND column_name = 'persona_id'
    ) THEN
        ALTER TABLE ag_bot.bots ADD COLUMN persona_id INT
            REFERENCES ag_system.agent_personas(persona_id);
        RAISE NOTICE 'Added persona_id FK to ag_bot.bots';
    END IF;
END $$;


-- ══════════════════════════════════════════════════════════════════════
-- 4. COMMENTS (documentation in the schema itself)
-- ══════════════════════════════════════════════════════════════════════

COMMENT ON COLUMN ag_system.agent_personas.input_guardrail_prompt IS
    'Hard security boundary injected into the LLM system prompt. E.g. "Only discuss Fleet Management."';

COMMENT ON COLUMN ag_system.agent_personas.execution_policies IS
    'IAM-style JSON rules. Blacklist model: tools NOT listed are allowed. '
    'Example: {"jira_update_ticket": {"status": {"$not_in": ["Closed"]}}}';

COMMENT ON COLUMN ag_system.agent_personas.output_dlp_patterns IS
    'Regex patterns for deterministic DLP redaction. '
    'Example: ["SCRUM-\\d+", "(?i)password\\s*[:=]\\s*\\S+"]';

COMMENT ON COLUMN ag_system.agent_personas.output_semantic_rules IS
    'Natural-language rules for LLM-based output filtering. '
    'Example: "Never reveal internal IP addresses or server names."';


-- ══════════════════════════════════════════════════════════════════════
-- 5. RECORD MIGRATION
-- ══════════════════════════════════════════════════════════════════════

INSERT INTO ag_system.migration_history (version, script_name, description)
VALUES ('V011', 'V011_guardrails.sql',
        'Persona-level 3-layer guardrails: input prompt, execution policies, output DLP + semantic')
ON CONFLICT DO NOTHING;

COMMIT;
