-- ════════════════════════════════════════════════════════════════════════
-- V047 — the search grant V046 made was overturned by hand, and cost a digest
-- ════════════════════════════════════════════════════════════════════════
-- V046 granted `search_web` to persona 10 (PrepCrest Current Affairs) and set
-- out at length why that is safe: a snippet has no `articleId`, PrepCrest
-- refuses any brief whose id was not in the envelope it sent, so a search
-- result can become a *suggestion* and can never become a published fact.
--
-- It was applied on 1 August 2026 at 14:50. By the time the 2 August digest
-- ran, the persona read:
--
--     allowed_tools      ["skill_manage","skill_view","skills_list","search_web"]
--     execution_policies {"search_web": {"$deny": true}}
--
-- Neither value is one any migration ever wrote. V045 declares `'[]'` and
-- `'{}'`; V046 declares `'["search_web"]'` and does not touch the policies.
-- Both were edited through the console afterwards, and the edit inverted the
-- decision V046 had just made.
--
-- ── WHY THAT COMBINATION IS THE WORST OF THE THREE ──────────────────────
--
-- These are two independent layers and they are supposed to agree:
--
--     allowed_tools       what the model can SEE   (visibility)
--     execution_policies  what the model may DO    (arguments, and $deny)
--
-- Granting visibility while denying execution does not disable a tool. It
-- advertises it. The model is shown `search_web`, the constraints prompt V046
-- appended tells it what the tool is for, it calls the tool, and the guardrail
-- refuses — and then it tries again, because nothing in its context says the
-- refusal is permanent.
--
-- On the 2 August digest that happened three times:
--
--     07:49:36  digest turn opens, persona resolves to 3 tools
--     07:54:14  GUARDRAIL BLOCKED ($deny): tool 'search_web' is explicitly denied
--     07:54:36  PrepCrest's deadline fires; the digest is recorded as Failed
--     07:55:18  GUARDRAIL BLOCKED ($deny): search_web
--     07:56:41  GUARDRAIL BLOCKED ($deny): search_web
--     07:57:15  {"briefs":[ ...   the day's briefs, 458s in, nobody listening
--
-- Roughly 150 of those 458 seconds bought nothing. The caller had already
-- given up, so the day published no briefing and banked no questions. Either
-- honest setting would have been fine — grant the tool, or hide it. The one
-- state that costs real money is the one where the model can see a tool it is
-- not allowed to use.
--
-- ── WHAT THIS DOES ──────────────────────────────────────────────────────
--
-- Restores persona 10 to exactly what V046 declares, and nothing else:
--
--   * execution_policies — the `search_web` deny is removed. Other keys, if a
--     later migration ever adds any, are preserved: this deletes one key
--     rather than assigning `'{}'`, so it repairs without overwriting.
--   * allowed_tools — back to `["search_web"]`. The skill_* entries are not a
--     current-affairs concern; V046 says so ("No page_*… No memory_*") and the
--     editor persona has no use for skills at all. Fewer visible tools is also
--     fewer turns spent discovering they do nothing.
--
-- The prompts are untouched. V046 owns those and got them right.
--
-- Idempotent: re-running is a no-op.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

WITH app AS (
    SELECT app_id FROM ag_system.applications
     WHERE name = 'PrepCrest Current Affairs'
)
UPDATE ag_system.agent_personas p
   SET execution_policies = COALESCE(p.execution_policies, '{}'::jsonb) - 'search_web',
       allowed_tools      = '["search_web"]'::jsonb,
       updated_at         = now()
 WHERE p.app_id = (SELECT app_id FROM app)
   AND (
        COALESCE(p.execution_policies, '{}'::jsonb) ? 'search_web'
     OR p.allowed_tools IS DISTINCT FROM '["search_web"]'::jsonb
   );

-- ── THE ASSERTION, BECAUSE A SILENT NO-OP IS HOW WE GOT HERE ────────────
--
-- V046 was applied, recorded, and then quietly undone, and nothing noticed
-- until a digest failed a day later. A migration whose whole purpose is to fix
-- a contradiction should refuse to report success while the contradiction is
-- still there.
DO $check$
DECLARE
    tools  jsonb;
    policy jsonb;
BEGIN
    SELECT p.allowed_tools, COALESCE(p.execution_policies, '{}'::jsonb)
      INTO tools, policy
      FROM ag_system.agent_personas p
      JOIN ag_system.applications a ON a.app_id = p.app_id
     WHERE a.name = 'PrepCrest Current Affairs';

    IF tools IS NULL THEN
        RAISE EXCEPTION
            'V047: no persona for "PrepCrest Current Affairs" — V045 has not been applied here.';
    END IF;

    IF policy ? 'search_web' THEN
        RAISE EXCEPTION
            'V047: search_web is still denied in execution_policies (%). The grant would be inert.',
            policy;
    END IF;

    IF NOT (tools ? 'search_web') THEN
        RAISE EXCEPTION
            'V047: search_web is not visible in allowed_tools (%). The grant would be unreachable.',
            tools;
    END IF;
END
$check$;

COMMIT;

-- Verify (manual):
--   -- the two layers must agree: visible AND not denied
--   SELECT a.name,
--          p.allowed_tools,
--          p.execution_policies,
--          (p.allowed_tools ? 'search_web')                                   AS visible,
--          NOT (COALESCE(p.execution_policies,'{}'::jsonb) ? 'search_web')    AS executable
--     FROM ag_system.agent_personas p
--     JOIN ag_system.applications a ON a.app_id = p.app_id
--    WHERE a.name LIKE 'PrepCrest%'
--    ORDER BY a.app_id;
--
--   -- and no blocked calls on the next digest
--   journalctl -u agent-api.service --since today | grep "GUARDRAIL BLOCKED"
