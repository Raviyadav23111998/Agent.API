-- ============================================================================
-- V005: Cron & Membership Enhancements
-- ============================================================================
-- Adds missing columns to ag_agents.cron_jobs for full parity with JSON format.
-- Creates ag_agents.cron_job_outputs for audit trail.
-- Creates ag_auth.memberships to replace memberships.json.
-- ============================================================================

BEGIN;

-- ── ag_agents.cron_jobs: Add missing columns ──
ALTER TABLE ag_agents.cron_jobs ADD COLUMN IF NOT EXISTS job_uuid VARCHAR(12);
ALTER TABLE ag_agents.cron_jobs ADD COLUMN IF NOT EXISTS schedule_kind VARCHAR(20) DEFAULT 'once';
ALTER TABLE ag_agents.cron_jobs ADD COLUMN IF NOT EXISTS schedule_json JSONB DEFAULT '{}';
ALTER TABLE ag_agents.cron_jobs ADD COLUMN IF NOT EXISTS repeat_times INT;
ALTER TABLE ag_agents.cron_jobs ADD COLUMN IF NOT EXISTS repeat_completed INT DEFAULT 0;
ALTER TABLE ag_agents.cron_jobs ADD COLUMN IF NOT EXISTS deliver VARCHAR(100) DEFAULT 'local';
ALTER TABLE ag_agents.cron_jobs ADD COLUMN IF NOT EXISTS origin_json JSONB;
ALTER TABLE ag_agents.cron_jobs ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE ag_agents.cron_jobs ADD COLUMN IF NOT EXISTS state VARCHAR(50) DEFAULT 'scheduled';

-- Drop the UNIQUE constraint on name to allow multiple jobs with same name
ALTER TABLE ag_agents.cron_jobs DROP CONSTRAINT IF EXISTS cron_jobs_name_key;

CREATE INDEX IF NOT EXISTS idx_cron_jobs_active ON ag_agents.cron_jobs(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_cron_jobs_next_run ON ag_agents.cron_jobs(next_run_at) WHERE is_active = TRUE;

-- ── Cron job output log (replaces filesystem output/) ──
CREATE TABLE IF NOT EXISTS ag_agents.cron_job_outputs (
    output_id   BIGSERIAL PRIMARY KEY,
    job_id      INT NOT NULL REFERENCES ag_agents.cron_jobs(job_id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

CREATE INDEX IF NOT EXISTS idx_cron_outputs_job ON ag_agents.cron_job_outputs(job_id);

-- ── Memberships table (replaces memberships.json) ──
CREATE TABLE IF NOT EXISTS ag_auth.memberships (
    membership_id   SERIAL PRIMARY KEY,
    user_ext_id     VARCHAR(200) NOT NULL,
    display_name    VARCHAR(300),
    group_ext_id    VARCHAR(200) NOT NULL,
    group_name      VARCHAR(300),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    UNIQUE(user_ext_id, group_ext_id)
);

CREATE INDEX IF NOT EXISTS idx_memberships_user ON ag_auth.memberships(user_ext_id);
CREATE INDEX IF NOT EXISTS idx_memberships_group ON ag_auth.memberships(group_ext_id);

COMMIT;
