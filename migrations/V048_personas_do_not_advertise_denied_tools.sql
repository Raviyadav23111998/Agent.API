-- ════════════════════════════════════════════════════════════════════════
-- V048 — a persona must not be shown a tool its own policy will refuse
-- ════════════════════════════════════════════════════════════════════════
-- V047 fixed one instance of this on the current-affairs persona. Watching
-- the log afterwards showed the same shape on the authoring one:
--
--     09:15:45  GUARDRAIL BLOCKED ($deny): tool 'skill_view' is explicitly denied
--     09:20:23  GUARDRAIL BLOCKED ($deny): tool 'skill_view' is explicitly denied
--
-- Persona 9 (PrepCrest Authoring) carries
--
--     allowed_tools      ["skill_manage","skill_view","skills_list"]
--     execution_policies {"skill_manage":{"$deny":true},
--                         "skill_view":{"$deny":true},
--                         "skills_list":{"$deny":true}}
--
-- every one of them visible and every one of them refused. V042 describes
-- that persona as having "no tools", which is the intent; the list is left
-- over from the tenant default.
--
-- ── WHY THIS IS A RULE AND NOT THREE FIXES ──────────────────────────────
--
-- The two columns answer different questions and are edited independently:
--
--     allowed_tools       what the model can SEE   (visibility)
--     execution_policies  what the model may DO    (arguments, and $deny)
--
-- Nothing has ever required them to agree, and the disagreement is not inert.
-- Denying a tool the model cannot see costs nothing. Denying one it CAN see
-- advertises it: the tool is in the manifest, the model reaches for it, the
-- guardrail refuses, and nothing in the refusal says the answer will be the
-- same next time — so it tries again. Every attempt is a round trip against
-- the caller's deadline.
--
-- On the current-affairs digest that was three attempts and roughly 150 of a
-- 458-second turn, on a caller that had already given up at 300. On authoring
-- it is one wasted call per batch, on a generator that runs every five
-- minutes, unattended, for ever.
--
-- Either honest setting is fine. Grant the tool, or hide it. The costly state
-- is the one in between, and it is the one you land in by editing one column.
--
-- ── WHAT THIS DOES ──────────────────────────────────────────────────────
--
-- Removes from allowed_tools, for every PrepCrest persona, any tool its own
-- execution_policies denies. It does not grant anything and it does not
-- change any policy: the set of tools a persona may USE is identical
-- afterwards. Only the advertising changes.
--
-- Deliberately not a CHECK constraint. A constraint would reject the
-- intermediate state of a legitimate two-step edit — granting a tool before
-- writing its argument rules — and would fail at write time in a console
-- somebody is using. The invariant is repaired here and asserted below.
--
-- Idempotent: re-running matches nothing.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

UPDATE ag_system.agent_personas p
   SET allowed_tools = COALESCE((
           SELECT jsonb_agg(tool ORDER BY tool)
             FROM jsonb_array_elements_text(p.allowed_tools) AS tool
            WHERE NOT (
                COALESCE(p.execution_policies, '{}'::jsonb) -> tool ->> '$deny'
            ) IS NOT DISTINCT FROM 'true'
       ), '[]'::jsonb),
       updated_at = now()
  FROM ag_system.applications a
 WHERE a.app_id = p.app_id
   AND a.name LIKE 'PrepCrest%'
   -- only rows that actually advertise something they refuse
   AND EXISTS (
       SELECT 1 FROM jsonb_array_elements_text(p.allowed_tools) AS tool
        WHERE COALESCE(p.execution_policies, '{}'::jsonb) -> tool ->> '$deny' = 'true'
   );

-- ── THE ASSERTION ───────────────────────────────────────────────────────
--
-- V046 was applied, recorded, and quietly undone by a console edit, and
-- nothing noticed until a digest failed a day later. A migration whose whole
-- purpose is to remove a contradiction should refuse to report success while
-- one is still there.
DO $check$
DECLARE
    offender text;
BEGIN
    SELECT a.name || ' → ' || tool
      INTO offender
      FROM ag_system.agent_personas p
      JOIN ag_system.applications a ON a.app_id = p.app_id
      CROSS JOIN LATERAL jsonb_array_elements_text(p.allowed_tools) AS tool
     WHERE a.name LIKE 'PrepCrest%'
       AND COALESCE(p.execution_policies, '{}'::jsonb) -> tool ->> '$deny' = 'true'
     LIMIT 1;

    IF offender IS NOT NULL THEN
        RAISE EXCEPTION
            'V048: % is still visible and still denied. The model will keep reaching for it.',
            offender;
    END IF;
END
$check$;

COMMIT;

-- Verify (manual):
--   -- every PrepCrest persona: what it can see, and what it may run
--   SELECT a.name, p.allowed_tools, p.execution_policies
--     FROM ag_system.agent_personas p
--     JOIN ag_system.applications a ON a.app_id = p.app_id
--    WHERE a.name LIKE 'PrepCrest%'
--    ORDER BY a.app_id;
--
--   -- and the log should fall silent
--   journalctl -u agent-api.service --since today | grep -c "GUARDRAIL BLOCKED"
