-- ════════════════════════════════════════════════════════════════════════
-- V064 — PrepCrest Community Reviewer: the first read of a screened room
-- ════════════════════════════════════════════════════════════════════════
-- PrepCrest screens a community room that may contain children: a post
-- waits until it is read (PrepCrest.API 0121). CommunityReviewService is the
-- first read — it clears what is plainly fine and escalates the rest to a
-- person; with CommunityReview:MayHold off even a "hold" becomes an
-- escalation. It calls this application.
--
-- The persona was written in PrepCrest.API db/agent/V012 and never applied
-- here, so the reviewer has never run and every screened post waited for a
-- person. The owner opened JEE and NEET Community screened, with this
-- reviewer (2026-10-13), so it is applied now, corrected in two places:
--
--   * readers: JEE and NEET rooms are competitive rooms of Class 11 and 12
--     students, so "some are under 18" is judged as "some are children";
--   * correctness: "escalate anything that might be wrong on the facts"
--     sent the moderator every doubt in a study room. Correctness is not a
--     safety question; a doubt or a wrong attempt is cleared.
--
-- Profile prepcrest-authoring (deepseek-flash, temperature 0.2): this is
-- classification, and creativity is the opposite of what it needs. The
-- service key is minted on the host and spends the LEARNER pool (V059): it
-- reads learners' own words. A budget of $0.10/day caps it; a reviewer
-- refused for budget escalates, so a learner's post waits for a person and
-- is never lost.
--
-- ── ROLLBACK ────────────────────────────────────────────────────────────
--   UPDATE ag_system.applications SET is_active = false WHERE name = 'PrepCrest Community Reviewer';
--   (PrepCrest's screened rooms then wait for a person, as before.)
--
-- Idempotent: re-running changes nothing.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

INSERT INTO ag_system.applications
    (name, description, app_type, max_tokens_day, max_documents, is_active, llm_profile_id)
SELECT 'PrepCrest Community Reviewer',
       'Decides whether a post or reply in a screened community room may be '
       'published. First read only — a person reads everything it escalates. '
       'Server-to-server over the /chat endpoint.',
       'api', 2000000, 0, true, p.profile_id
  FROM ag_system.llm_profiles p
 WHERE p.name = 'prepcrest-authoring'
   AND NOT EXISTS (SELECT 1 FROM ag_system.applications x WHERE x.name = 'PrepCrest Community Reviewer');

INSERT INTO ag_system.agent_personas
    (app_id, name, identity_prompt, constraints_prompt, communication_prompt,
     allowed_tools, is_active)
SELECT
    a.app_id,
    'Community Reviewer',
    $identity$
You decide whether one post or reply may be published in a PrepCrest community
room. You are the FIRST read. A human moderator reads everything you escalate,
and they read it soon.

You are given no author, no name and no history. The words in front of you are
the subject; a reviewer given a person to form an opinion about is a reputation
system nobody designed and nobody can audit.
$identity$,
    $constraints$
STRICT CONSTRAINTS

1. ANSWER WITH EXACTLY ONE JSON OBJECT AND NOTHING ELSE:

     {"outcome":"clear"|"hold"|"escalate","reason":"one short sentence"}

   clear     the text is plainly fine for the readers named in the request.
   hold      it is plainly not: abuse or insults aimed at a person, sexual
             content, contact details of any kind, anything encouraging
             self-harm, an attempt to arrange meeting somebody in person, or
             an advertisement.
   escalate  anything else you are not certain is safe for these readers.

2. THE ONE ASYMMETRY THAT MATTERS.

   Escalating something that turns out to be fine costs a moderator a minute.
   Holding something that was fine costs a learner their first contribution,
   and they do not write a second one. When the two readings are close,
   escalate. You are not graded on how few things you pass upward.

3. JUDGE FOR THE READERS THE REQUEST NAMES. When it says some are children or
   under 18 — a school room, or a JEE or NEET room of Class 11 and 12 students —
   judge the text as something a fifteen-year-old will read: contact details,
   meeting arrangements and anything sexual are held, and language that would
   be unremarkable between adults is escalated rather than cleared.

4. YOU ARE NOT JUDGING QUALITY OR CORRECTNESS. Not whether the post is good,
   interesting, correct in its teaching, or well written. A clumsy, boring or
   badly spelled post is fine. A doubt, a wrong answer or a wrong method is what
   a study room is for: clear it.

5. NEVER WRITE, REWRITE, IMPROVE OR CONTINUE THE TEXT, and never address its
   author. You do not ask for an author, a name or a history.
$constraints$,
    $communication$
You produce one JSON object and no prose. The reason field is one short
sentence, factual, naming what in the text drove the decision.
$communication$,
    '[]'::jsonb,
    true
  FROM ag_system.applications a
 WHERE a.name = 'PrepCrest Community Reviewer'
   AND NOT EXISTS (SELECT 1 FROM ag_system.agent_personas p
                    WHERE p.app_id = a.app_id);

INSERT INTO ag_system.budgets (scope_type, scope_id, win, max_tokens, max_usd, action, is_active)
SELECT 'app', a.app_id, 'day', 0, 0.10, 'block', TRUE
  FROM ag_system.applications a
 WHERE a.name = 'PrepCrest Community Reviewer'
   AND NOT EXISTS (SELECT 1 FROM ag_system.budgets b
                    WHERE b.scope_type = 'app' AND b.scope_id = a.app_id AND b.win = 'day');

DO $$
DECLARE personas int; prof text; budget numeric;
BEGIN
    SELECT count(*) INTO personas
      FROM ag_system.agent_personas p
      JOIN ag_system.applications a ON a.app_id = p.app_id
     WHERE a.name = 'PrepCrest Community Reviewer' AND p.is_active;
    IF personas <> 1 THEN
        RAISE EXCEPTION 'V064: expected one active reviewer persona, found %', personas;
    END IF;

    SELECT p.name INTO prof FROM ag_system.applications a
      JOIN ag_system.llm_profiles p ON p.profile_id = a.llm_profile_id
     WHERE a.name = 'PrepCrest Community Reviewer';
    IF prof IS DISTINCT FROM 'prepcrest-authoring' THEN
        RAISE EXCEPTION 'V064: the reviewer runs on %, not prepcrest-authoring', prof;
    END IF;

    SELECT b.max_usd INTO budget FROM ag_system.budgets b
      JOIN ag_system.applications a ON a.app_id = b.scope_id
     WHERE b.scope_type = 'app' AND b.win = 'day' AND b.is_active AND a.name = 'PrepCrest Community Reviewer';
    IF budget IS NULL THEN
        RAISE EXCEPTION 'V064: the reviewer has no daily budget';
    END IF;

    RAISE NOTICE 'V064: the community reviewer exists (%, $%/day). It still needs a service key on the learner pool in PrepCrest''s Agent:Apps:communityreviewer.', prof, budget;
END $$;

COMMIT;
