-- ════════════════════════════════════════════════════════════════════════
-- V043 — memory is scoped to its application, not just its user
-- ════════════════════════════════════════════════════════════════════════
-- ag_memory.memories has carried an app_id column since it was created. No
-- query has ever referenced it. Not the reads, not the writes — the column is
-- NOT NULL DEFAULT 1, so every memory from every application on the platform
-- was stamped as application 1 and nobody noticed, because a column that is
-- uniformly wrong looks exactly like a column that is uniformly right.
--
-- ── WHAT THAT COST ──────────────────────────────────────────────────────
--
-- Isolation rested entirely on user_id. That holds while a user_id belongs to
-- one person using one product, and stops holding the moment a SERVICE KEY is
-- involved: a key spends as the human who minted it (service_keys.service_user_id),
-- so an application calling the platform on behalf of ITS OWN end users runs
-- as that human. UserContext.user_id becomes "user_<their id>" — and the app
-- reads that person's private memories.
--
-- Observed, not hypothesised. An exam-question authoring application was
-- recalling a platform admin's personal research — a named private
-- individual's profile among it — and another product's internal API
-- endpoints, into prompts that write questions for schoolchildren. Nothing in
-- the reply said where the context came from.
--
-- ── WHY THE FIX IS A FILTER AND NOT A NEW MECHANISM ─────────────────────
--
-- UserContext already carries app_id, and has since cron needed it to resolve
-- app-scoped credentials (see test_cron_app_identity.py — the fleet Jira cron
-- that failed with app_id=None while the bot worked). Chat, service chat,
-- embed, cron and spawned agents all populate it correctly today.
--
-- So there was nothing to plumb. The identity was already there and arrived
-- intact at a store that threw it away. This migration makes the DATA able to
-- express what the code now enforces.
--
-- ── THE BACKFILL IS THE DANGEROUS PART ──────────────────────────────────
--
-- Every existing row says app_id = 1 because of the column default, not
-- because it came from application 1. Turning on a filter over that data
-- without correcting it would be worse than leaving the leak: reads would be
-- confidently, silently wrong, and an agent that lost its memory does not
-- report an error — it just stops knowing things.
--
-- Two groups need care, and they are handled differently on purpose:
--
--   • Real users (user_<n>, and the bare numeric ids) genuinely belong to
--     their home application, which ag_auth.users.app_id records. Backfilled
--     from there.
--
--   • System runners (__cli__, __cron__, __agent__*, embed_*) have a
--     synthetic user_id that is ALREADY unique to them, so they were never
--     the leak vector — nothing else shares their bucket. They keep app_id 1
--     and the code passes app_id=None for a context that has none, which
--     leaves their reads unfiltered and their behaviour identical. Narrowing
--     them is a separate change that needs each runner's owning app
--     established first; doing it blind here would silently blind the Jira
--     bot's 253 memories.
--
-- ADDITIVE + idempotent. Safe to re-run.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. Correct the real users' rows from their home application ──────────
-- Matches "user_12" and "12" alike: chat_service builds UserContext ids as
-- "user_<n>" while some older rows carry the bare number.
UPDATE ag_memory.memories m
   SET app_id = u.app_id
  FROM ag_auth.users u
 WHERE u.app_id IS NOT NULL
   AND m.app_id IS DISTINCT FROM u.app_id
   AND m.user_id IN ('user_' || u.user_id::text, u.user_id::text);

-- ── 2. The uniqueness rule follows the scope ─────────────────────────────
-- (user_id, key) meant two applications could not hold the same key for the
-- same person — one would silently UPDATE the other's memory through the
-- ON CONFLICT path. With app_id in the scope it has to be in the constraint,
-- or the isolation the reads now enforce is contradicted by the writes.
ALTER TABLE ag_memory.memories
    DROP CONSTRAINT IF EXISTS memories_user_id_key_key;

-- Named explicitly rather than left to the implicit name, so a later
-- migration can find it.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'ag_memory.memories'::regclass
           AND conname = 'uq_memories_app_user_key')
    THEN
        ALTER TABLE ag_memory.memories
            ADD CONSTRAINT uq_memories_app_user_key
            UNIQUE (app_id, user_id, key);
    END IF;
END $$;

-- The read path is (user_id | ANY(scopes)) AND app_id, in that order.
CREATE INDEX IF NOT EXISTS ix_memories_app_user
    ON ag_memory.memories (app_id, user_id);

COMMENT ON COLUMN ag_memory.memories.app_id IS
    'Owning application. ENFORCED on every read since V043 — before that it '
    'was written only by its DEFAULT 1 and never filtered on, so one '
    'application could read another''s memories whenever they resolved the '
    'same user_id (which a service key guarantees, since it spends as the '
    'human who minted it). NULL is never stored; a caller with no application '
    'passes None and the column default applies.';

COMMIT;

-- Verify (manual):
--   SELECT app_id, user_id, count(*) FROM ag_memory.memories
--    GROUP BY app_id, user_id ORDER BY app_id, user_id;
--
--   -- an app must not see another's rows:
--   SELECT count(*) FROM ag_memory.memories
--    WHERE user_id = 'user_1' AND app_id = 7;   -- expect 0
