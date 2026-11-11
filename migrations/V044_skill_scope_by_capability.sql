-- ════════════════════════════════════════════════════════════════════════
-- V044 — a skill reaches the apps that can act on it, and no others
-- ════════════════════════════════════════════════════════════════════════
-- create-jira-ticket-scrum was written with scope_type='tenant', which is what
-- skill_service.write() defaulted to for every agent-learned skill until the
-- previous commit. The reader is right to treat 'tenant' as org-wide, so that
-- one row was offered to every application on the platform.
--
-- ── WHAT IT COST, MEASURED ──────────────────────────────────────────────
--
-- The PrepCrest Authoring app writes exam questions. It holds NO jira tools —
-- its persona's allowed_tools is empty. It was still shown the skill in its
-- <skills_index>, under a line that says "BEFORE starting a task a skill covers,
-- load it with skill_view(name)". So it did.
--
-- From the live log, one authoring turn:
--
--   23:47:28  Scoped brain tools registered for app_id=7
--   23:47:29  WARNING: Persona 'PrepCrest Authoring' (app_id=7) has empty allowed_tools
--   23:49:20  llm.usage prompt=319   completion=3361   ← produced ONE skill_view call
--   23:52:57  llm.usage prompt=5232  completion=4145   ← finally wrote the questions
--
-- 3,361 completion tokens and 1 m 52 s — 45% of the output and a third of the
-- wall clock — spent reading a Jira ticket procedure before a single exam
-- question was written. Then re-billed on every later turn of the batch, because
-- prompt caching was running at 1%.
--
-- ── WHY NOT JUST NARROW IT TO ONE APP ───────────────────────────────────
--
-- Because it is genuinely shared. Three applications hold jira tools and can
-- act on it — Internal AI Assistant (1), Email Triage (2), Fleet Support (4) —
-- and scope_id is a single integer, so one app-scoped row would silently take
-- the skill away from the other two.
--
-- The skill is not the problem and is not being removed. It is copied to each
-- application that can execute it, and withdrawn from the four that cannot:
-- SMSystem Support (3), Web Copilot (5), PrepCrest Tutor (6) and PrepCrest
-- Authoring (7) hold no jira tool between them, so the procedure was never
-- actionable there — only distracting.
--
-- ── THE RULE THIS ESTABLISHES ───────────────────────────────────────────
--
-- A skill belongs to the applications that can act on it. Tenant scope stays
-- for something genuinely universal, but it is now a deliberate admin choice
-- rather than a default an agent falls into (see skill_service._default_write_scope).
--
-- Idempotent: re-running neither duplicates the copies nor re-widens the original.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. Give each jira-capable app its own copy ───────────────────────────
-- Derived from capability, not from a guess: an app is included exactly when
-- its default persona's allowed_tools contains a jira tool.
INSERT INTO ag_agents.skills
    (name, description, tags, body, scope_type, scope_id, origin,
     pinned, is_active, version, created_by)
SELECT s.name, s.description, s.tags, s.body,
       'app', a.app_id, s.origin,
       s.pinned, s.is_active, 1, s.created_by
  FROM ag_agents.skills s
 CROSS JOIN LATERAL (
        SELECT DISTINCT p.app_id
          FROM ag_system.agent_personas p
         WHERE EXISTS (
                 SELECT 1 FROM jsonb_array_elements_text(p.allowed_tools) t
                  WHERE t LIKE 'jira\_%')
      ) a
 WHERE s.name = 'create-jira-ticket-scrum'
   AND s.scope_type = 'tenant'
   AND NOT EXISTS (
         SELECT 1 FROM ag_agents.skills x
          WHERE x.name = s.name AND x.scope_type = 'app' AND x.scope_id = a.app_id);

-- ── 2. Retire the tenant-wide original ───────────────────────────────────
-- Deactivated rather than deleted: it is the row every use_count and
-- skill_versions entry points at, and the history of what the agent learned is
-- worth more than the row is costing once it stops being visible.
UPDATE ag_agents.skills
   SET is_active = false, updated_at = NOW()
 WHERE name = 'create-jira-ticket-scrum'
   AND scope_type = 'tenant'
   AND is_active;

COMMIT;

-- Verify (manual):
--   -- every jira-capable app keeps it, nobody else sees it:
--   SELECT s.scope_type, s.scope_id, a.name, s.is_active
--     FROM ag_agents.skills s
--     LEFT JOIN ag_system.applications a ON a.app_id = s.scope_id
--    WHERE s.name = 'create-jira-ticket-scrum'
--    ORDER BY s.scope_type, s.scope_id;
--
--   -- what PrepCrest Authoring (app 7) is now offered — expect zero rows:
--   SELECT name, scope_type FROM ag_agents.skills
--    WHERE is_active AND (scope_type = 'tenant'
--                     OR (scope_type = 'app'  AND scope_id = 7)
--                     OR (scope_type = 'user' AND scope_id IS NULL));
