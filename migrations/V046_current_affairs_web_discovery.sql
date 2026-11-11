-- ════════════════════════════════════════════════════════════════════════
-- V046 — the current-affairs editor may SEARCH, but still may not SOURCE
-- ════════════════════════════════════════════════════════════════════════
-- V045 gave persona 10 an empty tool whitelist and said why: search_web is a
-- POST to html.duckduckgo.com, regex-scraped, returning the top five results as
-- title + URL + snippet, and every page_* tool is delegated to a browser a
-- server-to-server caller does not have. It can discover that a story exists.
-- It cannot read it.
--
-- That reasoning has not changed and this migration does not overturn it. What
-- it does is separate two questions that V045 answered as one:
--
--     "may this persona SEARCH?"        — now yes
--     "may a search result become a
--      published FACT?"                  — still, absolutely, no
--
-- ── WHY GRANTING IT IS SAFE, AND WHERE THE SAFETY LIVES ─────────────────
--
-- Not in an instruction. Instructions are advice; the payload contract is
-- physics.
--
-- Every brief must carry an `articleId`, and PrepCrest refuses any brief whose
-- id was not in the envelope it sent (DigestReader checks against the offered
-- set). A search result has no articleId and cannot be given one — so a snippet
-- CANNOT become a brief, cannot become a question, and cannot reach a learner,
-- no matter what the model decides to do with the tool.
--
-- What a search result CAN become is a `suggestion`: a headline, a URL and one
-- line saying why it might matter. PrepCrest stores those apart from articles
-- and shows them to the editor as "stories we may have missed". The only way one
-- becomes content is a human adding the outlet to the allow-list so that we
-- FETCH it — at which point it is an article like any other, with an excerpt we
-- hold and a citation we can show.
--
-- So the tool widens what the editor LEARNS without widening what the platform
-- may ASSERT. That is the whole design, and it is the reason this is a payload
-- change as much as a tool grant.
--
-- ── THE SECOND USE, WHICH IS QUIETER AND WORTH MORE ─────────────────────
--
-- Disambiguation. Our excerpt says "the committee" or "the minister" and the
-- brief needs the office. A five-snippet search settles that without any of it
-- being published as a new fact: the claim still comes from our text, and the
-- search only helps the model write it unambiguously. The prompt allows exactly
-- this and nothing more.
--
-- ── WHAT DID NOT CHANGE ─────────────────────────────────────────────────
--
-- scope_policy, output_semantic_rules, output_dlp_patterns and approval_mode
-- are all still off, for the reasons V045 sets out at length. A digest is the
-- most out-of-scope-looking request this platform ever sees, and a semantic
-- filter paraphrases facts into new ones.
--
-- Idempotent: the prompt lives in one place and the migration updates in place.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

WITH app AS (
    SELECT app_id FROM ag_system.applications WHERE name = 'PrepCrest Current Affairs'
)
UPDATE ag_system.agent_personas p
SET
    -- ── the one tool, and only this one ─────────────────────────────────
    -- No page_*, because they return _BROWSER_ONLY server-side and a model
    -- that keeps trying one burns a turn discovering that every night.
    -- No memory_*, because carrying one day's news into the next is precisely
    -- how a model starts "remembering" a fact it was never given: the whole
    -- design is that each digest sees only the text supplied to it.
    allowed_tools = '["search_web"]'::jsonb,

    constraints_prompt = p.constraints_prompt || $extra$

## THE SEARCH TOOL — WHAT IT IS FOR, AND WHAT IT IS NOT

You have `search_web`. It returns the top five results as a title, a URL and a
one-line snippet. **It cannot open any of them, and neither can you.** There is
no tool in your world that fetches a page.

So a search result is a POINTER, never a source. You may use it for exactly two
things:

**1. Disambiguation.** The supplied text says "the committee" or "the minister"
   and you need the office to write the brief unambiguously. Search, confirm,
   and write the brief FROM THE SUPPLIED TEXT with the name filled in. The claim
   is still ours; the search only stopped you writing something vague.

**2. Discovery.** A major story broke that is not in the articles you were given.
   Say so — in `suggestions`, never in `briefs`.

## SUGGESTIONS — THE ONLY PLACE A SEARCH RESULT MAY APPEAR

  {"briefs":[ … ],
   "suggestions":[
     {"headline":"Supreme Court verdict on the electoral bonds review",
      "url":"https://…",
      "note":"Major constitutional judgment today; none of the supplied articles covers it."}
   ]}

  - `suggestions` is OPTIONAL and usually absent. Two or three on a big day; an
    empty array on an ordinary one. It is not a place to pad.
  - A suggestion has NO articleId, because we did not fetch it. That is the
    point.
  - Never write a summary in a suggestion, and never state the fact as though it
    were established. One line on why it might matter, and the link.
  - Never move a suggestion into `briefs`. A brief without an articleId from
    this turn is discarded, so doing it wastes the item and tells us nothing.

## THE RULE THE TOOL DOES NOT CHANGE

Every fact in every brief still comes from the text supplied in this turn. Not
from a snippet, not from what you remember, not from what a search implied. If
the supplied text does not support a sentence, the sentence does not go in a
brief — it goes in a suggestion, or nowhere.

Search costs a turn several seconds. Use it when a name is genuinely unclear or
when you believe something big is missing. Do not search every article.$extra$

WHERE p.app_id = (SELECT app_id FROM app)
  AND p.name = 'PrepCrest Current Affairs'
  -- Idempotent: only append once, however many times this is applied.
  AND position('## THE SEARCH TOOL' in p.constraints_prompt) = 0;

-- The tool grant is idempotent on its own; re-running is a no-op UPDATE.
WITH app AS (
    SELECT app_id FROM ag_system.applications WHERE name = 'PrepCrest Current Affairs'
)
UPDATE ag_system.agent_personas p
   SET allowed_tools = '["search_web"]'::jsonb,
       updated_at = NOW()
 WHERE p.app_id = (SELECT app_id FROM app)
   AND p.name = 'PrepCrest Current Affairs'
   AND p.allowed_tools <> '["search_web"]'::jsonb;

DO $$
BEGIN
    IF to_regclass('ag_system.migration_history') IS NOT NULL THEN
        INSERT INTO ag_system.migration_history (version, script_name, description)
        VALUES ('V046', 'V046_current_affairs_web_discovery.sql',
                'Grant search_web to the current-affairs persona for disambiguation and discovery; suggestions payload keeps snippets out of published facts')
        ON CONFLICT DO NOTHING;
    END IF;
END $$;

COMMIT;

-- Verify (manual):
--   SELECT p.persona_id, p.allowed_tools,
--          position('## THE SEARCH TOOL' in p.constraints_prompt) > 0 AS has_tool_rules,
--          p.scope_policy->>'mode' AS scope_mode,
--          p.output_semantic_rules = '' AS no_semantic
--     FROM ag_system.agent_personas p
--     JOIN ag_system.applications a ON a.app_id = p.app_id
--    WHERE a.name = 'PrepCrest Current Affairs';
--
--   -- and that the tutor and the author did NOT gain a tool:
--   SELECT a.name, p.allowed_tools
--     FROM ag_system.agent_personas p
--     JOIN ag_system.applications a ON a.app_id = p.app_id
--    WHERE a.name LIKE 'PrepCrest%';
