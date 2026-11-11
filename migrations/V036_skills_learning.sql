-- ════════════════════════════════════════════════════════════════════════
-- V036 — agent skills + learning loop (tenant-DB procedural memory)
-- ════════════════════════════════════════════════════════════════════════
-- Design: docs/SKILLS_LEARNING_IMPLEMENTATION_PLAN_2026-07-04.md (hermes-agent
-- port, MIT-attributed). A skill is a SKILL.md-shaped markdown document with
-- optional support files, scoped tenant|app|user. The background reviewer and
-- the curator write here through the skill_manage tool; every edit snapshots
-- into skill_versions (rollback + audit). Effectiveness columns close the
-- no-eval gap in the original design: skill_view marks a skill "in play",
-- and a user correction in the same conversation increments
-- correction_after_use — the curator works from data, not vibes.
--
-- ADDITIVE + idempotent + schema-tolerant (V035 lessons: COALESCE uniqueness,
-- to_regclass guards). Zero behavior change until agent.skill_learning=true.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS ag_agents.skills (
    skill_id      BIGSERIAL PRIMARY KEY,
    name          VARCHAR(64)  NOT NULL,               -- lowercase-hyphenated
    description   VARCHAR(120) NOT NULL,               -- one line; feeds the prompt index
    tags          TEXT[]       NOT NULL DEFAULT '{}',
    body          TEXT         NOT NULL,               -- SKILL.md markdown
    scope_type    VARCHAR(10)  NOT NULL DEFAULT 'tenant',
    scope_id      INTEGER,                             -- NULL for tenant scope
    origin        VARCHAR(10)  NOT NULL DEFAULT 'agent', -- agent|user|bundled
    pinned        BOOLEAN      NOT NULL DEFAULT FALSE, -- curator may not archive
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    version       INTEGER      NOT NULL DEFAULT 1,
    use_count            INTEGER NOT NULL DEFAULT 0,
    last_used_at         TIMESTAMPTZ,
    correction_after_use INTEGER NOT NULL DEFAULT 0,
    created_by    INTEGER,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT skills_scope_ck  CHECK (scope_type IN ('tenant','app','user')),
    CONSTRAINT skills_origin_ck CHECK (origin IN ('agent','user','bundled'))
);

-- Retrieval embedding — only where pgvector exists (SIT runs a reduced
-- stack without it; the service treats embeddings as an optimization).
DO $$
BEGIN
    BEGIN
        CREATE EXTENSION IF NOT EXISTS vector;
    EXCEPTION WHEN OTHERS THEN NULL;
    END;
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        EXECUTE 'ALTER TABLE ag_agents.skills '
                'ADD COLUMN IF NOT EXISTS embedding vector(768)';
    END IF;
END $$;

-- NULL scope_id must collide as a value (tenant scope) — V035 budgets lesson.
CREATE UNIQUE INDEX IF NOT EXISTS skills_name_scope_uniq
    ON ag_agents.skills (name, scope_type, COALESCE(scope_id, 0));

CREATE INDEX IF NOT EXISTS skills_active_scope
    ON ag_agents.skills (scope_type, COALESCE(scope_id, 0)) WHERE is_active;

CREATE TABLE IF NOT EXISTS ag_agents.skill_files (
    file_id    BIGSERIAL PRIMARY KEY,
    skill_id   BIGINT NOT NULL REFERENCES ag_agents.skills(skill_id) ON DELETE CASCADE,
    kind       VARCHAR(10)  NOT NULL,                  -- reference|template|script
    path       VARCHAR(200) NOT NULL,                  -- e.g. references/provider-quirks.md
    content    TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT skill_files_kind_ck CHECK (kind IN ('reference','template','script')),
    CONSTRAINT skill_files_path_uniq UNIQUE (skill_id, path)
);

CREATE TABLE IF NOT EXISTS ag_agents.skill_versions (
    version_id BIGSERIAL PRIMARY KEY,
    skill_id   BIGINT  NOT NULL,                       -- no FK: history survives deletes
    version    INTEGER NOT NULL,
    body       TEXT    NOT NULL,
    files      JSONB,                                  -- {path: content} snapshot
    edited_by  VARCHAR(40),                            -- reviewer|curator|learn|user:<id>
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS skill_versions_skill ON ag_agents.skill_versions (skill_id, version);

DO $$
BEGIN
    IF to_regclass('ag_system.migration_history') IS NOT NULL THEN
        INSERT INTO ag_system.migration_history (version, script_name, description)
        VALUES ('V036', 'V036_skills_learning.sql',
                'agent skills + learning loop (per-tenant procedural memory, reviewer/curator, effectiveness signals)')
        ON CONFLICT DO NOTHING;
    END IF;
END $$;

COMMIT;
