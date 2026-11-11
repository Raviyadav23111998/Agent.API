-- ════════════════════════════════════════════════════════════════════════
-- V039 — indexes for chat attachments on the canonical ag_system.files table
-- ════════════════════════════════════════════════════════════════════════
-- ag_system.files already exists (bootstrap; shared with the SMSystems file
-- model). The attachments + media-generation feature stores chat files there as
-- associated_to='chat_message', associated_id=<message_id>. This migration is
-- ADDITIVE ONLY — it does NOT redefine the canonical table; it adds the indexes
-- the feature needs (the by-association lookup runs on every turn to replay a
-- message's attachments, but prod only had the file_id PK).
--
-- Idempotent + guarded (no-op if the table is somehow absent).
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

DO $$
BEGIN
    IF to_regclass('ag_system.files') IS NOT NULL THEN
        -- Hydrate-by-message + SMSystems-style by-type/assoc reads.
        EXECUTE 'CREATE INDEX IF NOT EXISTS ix_files_assoc '
                'ON ag_system.files (associated_to, associated_id)';
        -- Ownership checks on serve/delete.
        EXECUTE 'CREATE INDEX IF NOT EXISTS ix_files_owner '
                'ON ag_system.files (created_by)';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('ag_system.migration_history') IS NOT NULL THEN
        INSERT INTO ag_system.migration_history (version, script_name, description)
        VALUES ('V039', 'V039_files_attachments.sql',
                'indexes on ag_system.files for chat attachments (by-assoc, owner)')
        ON CONFLICT DO NOTHING;
    END IF;
END $$;

COMMIT;
