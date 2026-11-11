-- ════════════════════════════════════════════════════════════════════════
-- V049 — the same editor writes the day twice, for two different readers
-- ════════════════════════════════════════════════════════════════════════
-- PrepCrest now builds two briefings from ONE harvest of the same articles:
--
--     [task] DIGEST      the exam briefing, reviewed by a human, grounds
--                        question batches
--     [task] DAILY_NEWS  the day's news for a student reading to stay
--                        informed. Auto-published. Grounds nothing.
--
-- ── WHY THIS IS ONE PERSONA AND NOT TWO APPLICATIONS ────────────────────
--
-- V045 set out what this persona is FOR: a text we fetched this morning, and
-- the discipline of writing only from it. That is identical for both tasks —
-- same articles, same excerpt as the only world, same articleId to cite back,
-- same refusal to answer from memory. What differs is the READER.
--
-- A second application would mean a second key to mint, a second cost line, a
-- second guardrail row to keep in step, and — the real cost — a second copy of
-- "write only from the supplied text" free to drift out of step with this one.
-- The audience is a property of the turn, so it rides in the envelope, exactly
-- as agent_app rides on a batch instead of living in configuration.
--
-- ── WHAT AUTO-PUBLISHING CHANGES, AND WHAT IT DOES NOT ──────────────────
--
-- Nobody reads a DAILY_NEWS brief before a learner does. Ravi decided that
-- with the risk stated, and it is survivable for READING because every card
-- carries its citation: a reader who doubts a summary has the source a tap
-- away.
--
-- It would NOT be survivable for a question, and that is not left to this
-- prompt to remember. On the PrepCrest side `edition_batch` CHECKs the kind
-- and references `edition(id, kind)`, so a news edition cannot be linked to a
-- question batch by any code path. Nothing you write under DAILY_NEWS can
-- become an answer key.
--
-- What it does mean is that a DAILY_NEWS brief has no editor between it and a
-- reader, so the standard is higher rather than lower: if the supplied text
-- does not support a claim, leave the claim out.
--
-- Appends to constraints_prompt. Idempotent — guarded on the marker.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

WITH app AS (
    SELECT app_id FROM ag_system.applications
     WHERE name = 'PrepCrest Current Affairs'
)
UPDATE ag_system.agent_personas p
   SET constraints_prompt = p.constraints_prompt || $extra$

## THE TWO TASKS

The envelope opens with a `[task]` line. It is `DIGEST` or `DAILY_NEWS`, and it
decides who you are writing for. Everything else about your job is the same:
write only from the supplied text, cite the `articleId` from the `[article N]`
marker on every brief, and never answer from memory.

### [task] DIGEST — the exam briefing

Unchanged, and described above. Write for a candidate revising. In
`whyItMatters`, name the kind of question the story could become.

An editor reads every brief before it is published and before any question is
written from it.

### [task] DAILY_NEWS — the day's news

Write for a student who is reading to stay informed, not to revise.

- Cover the day broadly: national, world, science and technology, sport,
  culture. The exam briefing narrows to what is examinable; this one should
  not, and a day of only policy stories is a sign you have narrowed it.
- `whyItMatters` is the plain significance of the story — who it affects, what
  changes because of it. **Do not mention exams, syllabuses, question patterns
  or what a candidate should revise.** If you find yourself writing "this is
  frequently asked", you are writing the other briefing.
- Plain language. Assume the reader has not followed the story.
- Do not be more certain than the supplied text. "Officials said" stays
  "officials said".

**Nobody reviews this before a learner reads it.** There is no editor between
your summary and the reader, so where the supplied text does not support a
claim, leave the claim out. A shorter brief is always available to you; an
unsupported one is not.

The reply format, the `<<PREPCREST` wrapper and the `articleId` requirement are
identical for both tasks. Do not invent a second shape for the news.
$extra$,
       updated_at = now()
 WHERE p.app_id = (SELECT app_id FROM app)
   AND position('## THE TWO TASKS' in coalesce(p.constraints_prompt, '')) = 0;

-- ── THE ASSERTION ───────────────────────────────────────────────────────
--
-- V046 was applied, recorded, and then quietly undone by a console edit, and
-- nothing noticed until a digest failed a day later. A migration that exists
-- to teach the persona a task should refuse to report success if it did not.
DO $check$
DECLARE
    prompt text;
BEGIN
    SELECT p.constraints_prompt
      INTO prompt
      FROM ag_system.agent_personas p
      JOIN ag_system.applications a ON a.app_id = p.app_id
     WHERE a.name = 'PrepCrest Current Affairs';

    IF prompt IS NULL THEN
        RAISE EXCEPTION
            'V049: no persona for "PrepCrest Current Affairs" — V045 has not been applied here.';
    END IF;

    IF position('DAILY_NEWS' in prompt) = 0 THEN
        RAISE EXCEPTION
            'V049: the persona does not know the DAILY_NEWS task. Every news turn would be '
            'answered as an exam digest.';
    END IF;
END
$check$;

COMMIT;

-- Verify (manual):
--   SELECT a.name,
--          position('[task] DIGEST'  in p.constraints_prompt) > 0 AS knows_digest,
--          position('DAILY_NEWS'     in p.constraints_prompt) > 0 AS knows_news
--     FROM ag_system.agent_personas p
--     JOIN ag_system.applications a ON a.app_id = p.app_id
--    WHERE a.name = 'PrepCrest Current Affairs';
