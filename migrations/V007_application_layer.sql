-- ═══════════════════════════════════════════════════════════════════════
-- V007: Application-Level Data Isolation
-- ═══════════════════════════════════════════════════════════════════════
-- Introduces ag_system.applications as the missing isolation layer
-- between Tenant (database) and User (owner_id).
--
-- Design Decisions (per user approval):
--   • Multiple bots CAN belong to one application (many:1)
--   • Existing data → "Internal AI Assistant" app (app_id=1)
--   • Cron email ingestion → "Email Triage" app (app_id=2)
--   • SMSystem Support Bot → "SMSystem Support" app (app_id=3)
-- ═══════════════════════════════════════════════════════════════════════

BEGIN;

-- ══════════════════════════════════════════════════════════════════════
-- 1. CREATE ag_system.applications TABLE
-- ══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ag_system.applications (
    app_id          SERIAL PRIMARY KEY,
    app_uuid        UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    name            VARCHAR(200) NOT NULL,
    description     TEXT DEFAULT '',
    app_type        VARCHAR(50) NOT NULL DEFAULT 'internal',
    -- Per-app LLM config overrides (NULL = use tenant default)
    llm_model       VARCHAR(200),
    llm_api_key_enc TEXT,
    -- Per-app limits (0 = unlimited)
    max_tokens_day  INT DEFAULT 0,
    max_documents   INT DEFAULT 0,
    -- Metadata
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    CONSTRAINT chk_app_type CHECK (app_type IN (
        'internal', 'chatbot', 'api', 'mobile', 'widget'
    ))
);


-- ══════════════════════════════════════════════════════════════════════
-- 2. SEED APPLICATIONS
-- ══════════════════════════════════════════════════════════════════════

INSERT INTO ag_system.applications (app_id, name, description, app_type, created_by)
VALUES
    (1, 'Internal AI Assistant', 'Default internal AI assistant for admin dashboard and web chat', 'internal', 1),
    (2, 'Email Triage', 'Automated email ingestion and ticket creation from cron jobs', 'internal', 1),
    (3, 'SMSystem Support', 'Customer-facing support chatbot for SMSystem application', 'chatbot', 1)
ON CONFLICT (app_id) DO NOTHING;

-- Reset sequence to next available
SELECT setval('ag_system.applications_app_id_seq', (SELECT COALESCE(MAX(app_id), 0) FROM ag_system.applications), true);


-- ══════════════════════════════════════════════════════════════════════
-- 3. ADD app_id COLUMNS (non-breaking: DEFAULT 1)
-- ══════════════════════════════════════════════════════════════════════

-- 3.1 ag_brain.documents
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ag_brain' AND table_name = 'documents' AND column_name = 'app_id'
    ) THEN
        ALTER TABLE ag_brain.documents ADD COLUMN app_id INT NOT NULL DEFAULT 1
            REFERENCES ag_system.applications(app_id);
        CREATE INDEX idx_docs_app ON ag_brain.documents(app_id);
        RAISE NOTICE 'Added app_id to ag_brain.documents';
    END IF;
END $$;

-- 3.2 ag_brain.entities
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ag_brain' AND table_name = 'entities' AND column_name = 'app_id'
    ) THEN
        ALTER TABLE ag_brain.entities ADD COLUMN app_id INT NOT NULL DEFAULT 1
            REFERENCES ag_system.applications(app_id);
        CREATE INDEX idx_brain_entities_app ON ag_brain.entities(app_id);
        RAISE NOTICE 'Added app_id to ag_brain.entities';
    END IF;
END $$;

-- 3.3 ag_brain.content_cache
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ag_brain' AND table_name = 'content_cache' AND column_name = 'app_id'
    ) THEN
        ALTER TABLE ag_brain.content_cache ADD COLUMN app_id INT NOT NULL DEFAULT 1
            REFERENCES ag_system.applications(app_id);
        CREATE INDEX idx_cache_app ON ag_brain.content_cache(app_id);
        RAISE NOTICE 'Added app_id to ag_brain.content_cache';
    END IF;
END $$;

-- 3.4 ag_brain.sync_state
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ag_brain' AND table_name = 'sync_state' AND column_name = 'app_id'
    ) THEN
        ALTER TABLE ag_brain.sync_state ADD COLUMN app_id INT NOT NULL DEFAULT 1
            REFERENCES ag_system.applications(app_id);
        RAISE NOTICE 'Added app_id to ag_brain.sync_state';
    END IF;
END $$;

-- 3.5 ag_memory.memories
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ag_memory' AND table_name = 'memories' AND column_name = 'app_id'
    ) THEN
        ALTER TABLE ag_memory.memories ADD COLUMN app_id INT NOT NULL DEFAULT 1
            REFERENCES ag_system.applications(app_id);
        CREATE INDEX idx_mem_app ON ag_memory.memories(app_id);
        RAISE NOTICE 'Added app_id to ag_memory.memories';
    END IF;
END $$;

-- 3.6 ag_agents.cron_jobs
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ag_agents' AND table_name = 'cron_jobs' AND column_name = 'app_id'
    ) THEN
        ALTER TABLE ag_agents.cron_jobs ADD COLUMN app_id INT NOT NULL DEFAULT 1
            REFERENCES ag_system.applications(app_id);
        CREATE INDEX idx_cron_app ON ag_agents.cron_jobs(app_id);
        RAISE NOTICE 'Added app_id to ag_agents.cron_jobs';
    END IF;
END $$;

-- 3.7 ag_agents.definitions
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ag_agents' AND table_name = 'definitions' AND column_name = 'app_id'
    ) THEN
        ALTER TABLE ag_agents.definitions ADD COLUMN app_id INT NOT NULL DEFAULT 1
            REFERENCES ag_system.applications(app_id);
        CREATE INDEX idx_agents_app ON ag_agents.definitions(app_id);
        RAISE NOTICE 'Added app_id to ag_agents.definitions';
    END IF;
END $$;

-- 3.8 ag_bot.bots (nullable — allows unassigned legacy bots)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ag_bot' AND table_name = 'bots' AND column_name = 'app_id'
    ) THEN
        ALTER TABLE ag_bot.bots ADD COLUMN app_id INT
            REFERENCES ag_system.applications(app_id);
        CREATE INDEX idx_bots_app ON ag_bot.bots(app_id);
        RAISE NOTICE 'Added app_id to ag_bot.bots';
    END IF;
END $$;


-- ══════════════════════════════════════════════════════════════════════
-- 4. MIGRATE EXISTING DATA TO CORRECT APPLICATIONS
-- ══════════════════════════════════════════════════════════════════════

-- 4.1 Emails and tickets → "Email Triage" app (app_id=2)
UPDATE ag_brain.documents SET app_id = 2
WHERE doc_type IN ('email', 'ticket') AND app_id = 1;

-- 4.2 Bot knowledge (FAQs linked to SMSystem bot) → "SMSystem Support" app (app_id=3)
UPDATE ag_brain.documents SET app_id = 3
WHERE doc_id IN (
    SELECT doc_id FROM ag_bot.bot_knowledge_links WHERE bot_id = 1
);

-- 4.3 Link SMSystem bot to its application
UPDATE ag_bot.bots SET app_id = 3 WHERE bot_id = 1;

-- 4.4 Cron jobs → "Email Triage" app (app_id=2)
UPDATE ag_agents.cron_jobs SET app_id = 2;

-- 4.5 Entities extracted from emails/tickets → "Email Triage" app
UPDATE ag_brain.entities SET app_id = 2;

-- 4.6 Content cache from email sync → "Email Triage" app
UPDATE ag_brain.content_cache SET app_id = 2;


-- ══════════════════════════════════════════════════════════════════════
-- 5. RECORD MIGRATION
-- ══════════════════════════════════════════════════════════════════════

INSERT INTO ag_system.migration_history (version, script_name, description)
VALUES ('V007', 'V007_application_layer.sql', 'Application-level data isolation: ag_system.applications + app_id on 8 tables')
ON CONFLICT DO NOTHING;

COMMIT;
