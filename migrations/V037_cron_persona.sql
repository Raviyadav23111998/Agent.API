-- ════════════════════════════════════════════════════════════════════════
-- V037 — per-task persona assignment for cron jobs
-- ════════════════════════════════════════════════════════════════════════
-- Lets an operator assign a SPECIFIC persona to a SPECIFIC cron task. NULL =
-- the job inherits its app's default persona at run time (resolved by the
-- runner's persona applicator). Fixes the gap where crons ran with no persona
-- at all while bot/chat applied one. See
-- docs/PERSONA_CRON_ARCHITECTURE_AUDIT_AND_PLAN_2026-07-05.md.
--
-- ADDITIVE + idempotent + schema-tolerant. Zero behaviour change for existing
-- jobs (persona_id defaults NULL → app default, which is now applied to crons).
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE ag_agents.cron_jobs
    ADD COLUMN IF NOT EXISTS persona_id INTEGER;

-- FK to the persona table (same tenant DB, cross-schema). ON DELETE SET NULL
-- so deleting a persona never orphans a job — it just falls back to the app
-- default. Guarded: only add if the personas table exists and the constraint
-- isn't already present.
DO $$
BEGIN
    IF to_regclass('ag_system.agent_personas') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM pg_constraint WHERE conname = 'cron_jobs_persona_fk'
       ) THEN
        EXECUTE 'ALTER TABLE ag_agents.cron_jobs '
                'ADD CONSTRAINT cron_jobs_persona_fk '
                'FOREIGN KEY (persona_id) '
                'REFERENCES ag_system.agent_personas(persona_id) '
                'ON DELETE SET NULL';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS cron_jobs_persona
    ON ag_agents.cron_jobs (persona_id) WHERE persona_id IS NOT NULL;

DO $$
BEGIN
    IF to_regclass('ag_system.migration_history') IS NOT NULL THEN
        INSERT INTO ag_system.migration_history (version, script_name, description)
        VALUES ('V037', 'V037_cron_persona.sql',
                'per-task persona assignment for cron jobs (cron_jobs.persona_id)')
        ON CONFLICT DO NOTHING;
    END IF;
END $$;

COMMIT;
