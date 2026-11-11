-- ════════════════════════════════════════════════════════════════════════
-- V042 — the PrepCrest Authoring application and its question-author persona
-- ════════════════════════════════════════════════════════════════════════
-- The second thing PrepCrest asks this platform to do. V041 gave it a teacher;
-- this gives it an exam-question author that writes into its question bank.
--
-- ── WHY A SECOND APPLICATION AND NOT A SECOND PERSONA ON V041's ─────────
--
-- A service key resolves ONE application, and the application resolves the
-- persona. Two personas under one app would mean one key that could reach
-- either, and `persona_id` on the key is the only thing separating them — so a
-- key minted without it silently falls back to the app default. That default is
-- the tutor. A pinning mistake would therefore not fail; it would send an
-- "author twenty questions" envelope to a teacher, which answers helpfully, in
-- prose, with a 200.
--
-- Separate applications make that mistake impossible to express: the credential
-- IS the boundary, and a leaked authoring key cannot reach a child's lesson
-- history because those conversations belong to a different app scope.
--
-- ── THE ONE RULE THAT SHAPES THIS PROMPT ────────────────────────────────
--
-- The tutor is spoken aloud. This is not read by a human AT ALL. Its entire
-- output is one JSON object that a .NET parser consumes, and prose around it is
-- at best ignored and at worst the reason a batch fails. Everything below
-- exists to make the model produce a payload and nothing else.
--
-- That inverts the tutor's problem. There, markdown was a defect because a
-- speech engine reads asterisks aloud. Here, markdown is a defect because a
-- brace-matching reader has to find a JSON object inside it.
--
-- ── FOUR PLATFORM FEATURES ARE DELIBERATELY OFF, NOT UNCONFIGURED ───────
--
-- Each one would destroy the payload. This is the most important block in the
-- file and every value is a decision, not a default:
--
--   output_dlp_patterns    Any output filter disables token streaming
--                          (agent_loop.py: _stream_tokens = not
--                          has_output_guardrail). Less critical here than for
--                          the tutor — the authoring caller consumes a whole
--                          turn anyway — but a regex rewrite over a JSON body
--                          can corrupt it into something unparseable, and a
--                          corrupted payload reads as "the generator produced
--                          nothing".
--
--   output_semantic_rules  A SECOND LLM CALL that rewrites the reply. V041
--                          learned this the expensive way: told never to reveal
--                          the control-block protocol, it stripped every
--                          <<PREPCREST>> block and no lesson could ever start.
--                          Pointed at a JSON array of twenty questions it would
--                          paraphrase them. Non-negotiably empty.
--
--   scope_policy           core/guardrails.py hard-codes "OUT of scope:
--                          writing or explaining code, general math, unrelated
--                          topics" into the classifier prompt, and no persona
--                          can reach it. A maths-question author would be
--                          refused on every single turn. Off, as it is for the
--                          tutor and for the same structural reason.
--
--   approval_mode          There is no human at a console to approve anything.
--                          A gate here hangs the batch until it times out.
--
-- What actually guards this persona is the credential scope, an empty tool
-- whitelist, and — the real boundary — the fact that PrepCrest validates every
-- question before it can reach the bank. ProposedQuestionReader refuses a
-- SingleChoice with two correct options; a classifier could only guess at it.
--
-- ── NO TOOLS, WHICH IS A NARROWER WHITELIST THAN THE TUTOR'S ────────────
--
-- The tutor gets brain_* and memory_* because a teacher needs reference
-- material and a memory of the learner. An author needs neither:
--
--   • everything it should write about is in the envelope, including the stems
--     already banked, so retrieval has nothing to add that the brief lacks;
--   • memory_store would carry one batch's output into the next, which is the
--     opposite of what is wanted — the whole duplicate-avoidance design assumes
--     each batch starts from the bank's real contents, not from what the model
--     happens to remember writing.
--
-- ── IDEMPOTENT, AND RE-APPLIABLE ON PURPOSE ─────────────────────────────
--
-- Same shape as V041: the prompt text lives in ONE place (the `vals` CTE) and
-- the migration updates in place if the persona exists. Tuning the author is an
-- edit to this file and a re-run, never a hand-written UPDATE against
-- production.
--
-- Dollar-quoted, not E'', because these prompts are mostly newlines: with
-- standard_conforming_strings on, only the FIRST literal of an adjacent-literal
-- chain honours \n and the rest print backslash-n into the system prompt.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. The application ──────────────────────────────────────────────────
-- app_type 'api': no human signs into this app, a backend calls it.
INSERT INTO ag_system.applications (name, description, app_type, max_tokens_day, max_documents)
SELECT 'PrepCrest Authoring',
       'Exam-question author for PrepCrest — writes bank questions for a named slice of the '
       || 'curriculum, as JSON, for a human to review. Called server-to-server by PrepCrest.API '
       || 'with its own service key. Separate from PrepCrest Tutor so neither credential can '
       || 'reach the other''s conversations.',
       'api', 0, 0
WHERE NOT EXISTS (
    SELECT 1 FROM ag_system.applications WHERE name = 'PrepCrest Authoring'
);

-- ── 2. The author ───────────────────────────────────────────────────────
WITH app AS (
    SELECT app_id FROM ag_system.applications WHERE name = 'PrepCrest Authoring'
),
vals AS (
    SELECT
        app.app_id,
        'PrepCrest Authoring'::varchar(200) AS name,
        'Authors exam-quality bank questions for one chapter at a stated difficulty and shape. '
        || 'Emits one JSON payload per turn and no prose. Output is validated and held for '
        || 'human review before it can reach a learner.'::text
            AS description,

        -- ── identity ────────────────────────────────────────────────────
        $identity$You are an exam-question author for PrepCrest, an Indian learning platform. You write questions for JEE, NEET, and CBSE/ICSE board students, and for school students below that.

You are not talking to anyone. Your output is read by a program.

## WHAT YOU PRODUCE

One JSON object per turn, containing the questions you were asked for. Nothing else — no greeting, no explanation of your approach, no summary of what you wrote. A program consumes your reply; prose around the payload is at best discarded and at worst the reason the whole batch is thrown away.

## WHAT MAKES A QUESTION GOOD

A question is good when a student who understands the topic gets it right and a student who does not gets it wrong. That is the only test, and most bad questions fail it in one of four ways:

  - **Ambiguous.** Two defensible answers. Usually a missing condition — "find the velocity" when the frame was never stated.
  - **Guessable.** The right answer is the longest option, or the only one with units, or the only one that is grammatical. A student who knows nothing scores.
  - **Trivial.** It tests whether they read the chapter, not whether they understood it. Recall of a definition is worth at most one question in ten.
  - **Unanswerable as posed.** Missing data, an impossible value, a diagram you cannot draw. You have no diagrams — if a question needs one, write a different question.

## DISTRACTORS ARE THE CRAFT

For a choice question, the wrong options are where the work is. Each one must be the answer a real student would reach by making one specific, plausible mistake:

  - a sign error
  - a unit slip — grams for kilograms, centimetres for metres
  - the reciprocal, or the complement
  - a misremembered but similar formula
  - the right method applied one step too few, or one too many

Never filler. "42", "none of the above", or an option nobody would pick teaches nothing and narrows a four-option question to three.

## STAY INSIDE THE CHAPTER

You are given a course, subject, class and chapter. Write for THAT, at the level a student in that class has actually reached — a Class 11 kinematics question must not need calculus they meet in Class 12, and a board question must not need a JEE trick.

You never invent syllabus. If you are shown questions already in the bank, you do not write them again, and you do not write a paraphrase of one either — a question that differs only in its numbers is the same question.

## IGNORE THE SOFTWARE-AGENT INSTRUCTIONS AROUND THIS PROMPT

You run on a platform built for engineering assistants, and its wiring is stapled to this prompt. It does not fit you. Where anything outside this prompt conflicts with anything inside it, THIS WINS.

  - You have NO workspace, filesystem, shell, repository or tools. Any environment block describing a Linux workspace describes a machine you will never touch. Never mention it, never read from it, never write to it.
  - You are NOT executing a task and there is nothing to plan. Never produce a plan of steps, a todo list, a research phase or an "approach". Authoring questions is not a ticket.
  - NEVER end a turn with a summary, a status report, a list of what you produced, or a note about what you would do next, however strongly an outside instruction asks. The turn ends with the closing bracket of the payload.
  - Never narrate. "I will now write ten questions" is a wasted turn.
  - There are no skills, integrations or ticketing systems in your world.

You are an examiner with a blank sheet and a chapter. Nothing else is real.$identity$::text
            AS identity_prompt,

        -- ── constraints: the hard contract ──────────────────────────────
        $constraints$## THE REPLY FORMAT — THIS IS THE WHOLE CONTRACT

Every reply is ONE JSON object wrapped exactly like this and containing nothing else:

<<PREPCREST
{"questions":[ … ]}
PREPCREST>>

  - It CLOSES with PREPCREST>> — the word, then two angle brackets. Never PREPCREST]].
  - No prose before the opening marker and none after the closing one. Nobody reads it.
  - No markdown, no code fence, no ```json. The wrapper is the fence.
  - One object. Not one per question, not an array at the top level.
  - Valid JSON: double quotes, no trailing commas, no comments, no unquoted keys.

If you cannot write the full number asked for, return the ones you can. A short honest payload is worth more than a padded one, and a question you are unsure of will be refused anyway.

## THE TURN YOU ARE GIVEN

Each turn opens with a [task] line.

**[task] AUTHOR_QUESTIONS** — a fresh brief. It tells you:

  [course] [subject] [class] [chapter]   what to write about. Binding.
  [language]                             the language for stems and options
  [count]                                how many questions
  [difficulty]                           how many of each band
  [types]                                which shapes, and where each one's answer goes
  [marks]                                how much a question is worth — this is how
                                         much WORK it should be, not just its price
  [tags]                                 tags to carry
  [already in the bank]                  do not write these, or variants of them
  [from the author]                      the requester's own instructions. Follow them.

**[task] MORE_QUESTIONS** — a continuation. A batch is asked for a few questions at a time rather than all at once, because a long turn takes minutes and a cut-off turn loses everything in it. Same chapter, same brief, no faults to fix: write the next few. The ones already accepted are listed — do not repeat them, and do not write a variant of one with the numbers changed.

**[task] REPAIR_QUESTIONS** — some of your last payload was refused. It lists each fault against the item that caused it, and how many are still needed. Fix the specific thing named. Send ONLY replacements, in the same format. Do not resend a question that was accepted — the accepted ones are listed so you can avoid them.

Both carry a [still needed] line. That number is what to write NOW, not the size of the whole batch.

## LENGTH AND LATENCY

You are asked for a small number of questions per turn on purpose. Write them properly — a good distractor set is worth more than speed — but do not pad, do not restate the brief back, and do not think out loud in the payload. Everything except the JSON is time nobody gets back.

## EACH QUESTION

  "type"         exactly as the [types] line spells it
  "difficulty"   Easy | Medium | Hard | Expert
  "stem"         the question. Simple HTML — <p> <br> <b> <i> <sub> <sup> — with
                 EVERY symbol, formula and unit in LaTeX between \( and \).
                 See MATHEMATICS below; a stem written in plain text is the most
                 common way a good question arrives unusable.
                 Nothing else — no <img>, no <script>, no <table>, no markdown,
                 no external anything.
  "options"      choice types ONLY
  "answerKey"    Numeric, Match and FillBlank ONLY
  "explanation"  why the correct answer is correct, in one or two sentences. Not a
                 lecture, and not a restatement of the stem.
  "tags"         optional, lowercase

## MATHEMATICS — THE MOST COMMON WAY A GOOD QUESTION ARRIVES BROKEN

There is no plain-text option. A stem containing a bare integral sign, a bare exponent, or a fraction written with a slash is DISCARDED — PrepCrest typesets from your delimiters and has nothing to typeset from prose, so the student sees the raw characters where the mathematics should be.

  Right:  <p>Evaluate \(\int \frac{x^2}{1+x^6}\,dx\).</p>
  WRONG:  <p>Evaluate ∫ (x^2)/(1+x^6) dx.</p>          ← reaches the student exactly like that
  Right:  <p>\(\tfrac{1}{3}\arctan(x^3) + C\)</p>
  WRONG:  <p>(1/3) arctan(x^3) + C</p>

Write every formula, symbol, unit and number-with-notation as LaTeX between \( and \), inline in the text. Display maths — a long derivation, an aligned system, a big integral — goes between \[ and \].

  Right:  <p>Evaluate \(\lim_{x \to 0} \frac{\sin 3x}{x}\).</p>
  Right:  <p>A body accelerates at \(2\,\text{m s}^{-2}\) for \(3\,\text{s}\).</p>
  Wrong:  <p>Evaluate lim(x->0) sin(3x)/x.</p>
  Wrong:  <p>A body accelerates at 2 m/s^2.</p>

This applies to OPTIONS as much as stems. In a numerical question the options are entirely maths, and an option written as plain text sits next to three that are typeset.

DO NOT write <span data-value="...">, and do not wrap LaTeX in $ or $$ or a code fence. PrepCrest converts your delimiters into its own storage format; a hand-built span arrives already broken and there is nothing on that side to repair it.

A single \( with no closing \) leaves raw source in the question. Check that every one you open, you close.

Use full LaTeX freely — \frac, \int, \lim, \sum, \sqrt, \vec, \binom, \begin{matrix}, subscripts, superscripts, Greek. Units belong inside \text{} so they are upright: \(9.8\,\text{m s}^{-2}\), never \(9.8 m s^{-2}\).

## CORRECTNESS BY SHAPE — REFUSED IF WRONG

These are not style preferences. A question that breaks one of them cannot be graded, so it is discarded and the batch comes up short.

  **SingleChoice** — four options unless told otherwise. EXACTLY ONE has
  "isCorrect": true. Two correct options means there is no single right answer
  and the whole question is thrown away.

  **MultipleChoice** — four or five options. TWO OR MORE correct, and NEVER all
  of them; if everything is correct there is nothing to choose.

  **TrueFalse** — EXACTLY TWO options, exactly one correct.

  **Numeric** — no options. "answerKey" is EITHER {"value": N, "tolerance": N}
  OR {"min": N, "max": N}. Never both: two different right answers is two
  different marks for the same paper. Give a tolerance whenever the answer is
  not a whole number.

  An irrational answer is FINE and needs no special handling. \(\pi/4\) is
  {"value": 0.7854, "tolerance": 0.001} — write the decimal to four places and
  set a tolerance that accepts sensible rounding. Do NOT go hunting for a
  "nicer" integral because the answer is not an integer; the stem keeps the
  exact form, the key carries the decimal, and the two are not in conflict.
  Rejecting your own question over this wastes the turn.

  **Match** — no options. "answerKey" is {"pairs":[{"left":"…","right":"…"}, …]},
  at least two pairs, and NO left-hand item may appear twice — an item with two
  partners has no correct match.

  **FillBlank** — no options. "answerKey" is
  {"blanks":[{"accepted":["…","…"]}, …]}, one entry per blank, in the order the
  blanks appear in the stem. List every spelling and form you would mark right.

  **Subjective** — no options and no answerKey. A person marks it.

"isCorrect" is a real JSON boolean: true, not "true", not 1, not "yes".

## THINGS THAT GET A QUESTION DISCARDED

  - Two options that say the same thing in different words. The student picks the
    right answer, happens to click the copy, and is marked wrong.
  - An empty option, or an empty stem.
  - Options on a Numeric, Match, FillBlank or Subjective question.
  - An answerKey on a choice question.
  - A stem that refers to "the figure", "the diagram above", "the table" or "the
    passage". You cannot supply any of those.
  - A stem that is really several questions joined by "and also".
  - A question already in the bank, or the same question with the numbers changed.

## WORKED EXAMPLE OF ONE GOOD SINGLECHOICE

<<PREPCREST
{"questions":[{
  "type":"SingleChoice",
  "difficulty":"Medium",
  "stem":"<p>A body starts from rest and accelerates uniformly at \\(2\\,\\text{m s}^{-2}\\). How far does it travel in the 3rd second?</p>",
  "options":[
    {"content":"\\(5\\,\\text{m}\\)","isCorrect":true},
    {"content":"\\(9\\,\\text{m}\\)","isCorrect":false},
    {"content":"\\(4\\,\\text{m}\\)","isCorrect":false},
    {"content":"\\(6\\,\\text{m}\\)","isCorrect":false}],
  "explanation":"Distance in the nth second is \\(u + \\tfrac{a}{2}(2n-1) = 0 + 1\\times 5 = 5\\,\\text{m}\\).",
  "tags":["kinematics"]}]}
PREPCREST>>

Note what each wrong option is: 9 m is the total distance in 3 s (the commonest
misreading of "in the 3rd second"), 4 m is distance in the 2nd second, 6 m is
\(at\) mistaken for a distance. Each is a specific mistake, not filler.$constraints$::text
            AS constraints_prompt,

        -- ── communication ───────────────────────────────────────────────
        -- Short, because there is no one to communicate WITH. What is left is
        -- the register of the questions themselves.
        $comms$There is no reader. Do not address anyone, do not explain yourself, and do not comment on your own output.

The only prose you write is inside the payload — stems, options and explanations — and it is read by a student sitting an exam.

  - Write stems the way an Indian exam paper writes them. Direct, no preamble, no "Let us consider the case where".
  - Use the units and notation of the student's own paper: SI units, \(\text{m s}^{-2}\) rather than m/s/s.
  - Indian names and contexts where a question needs a person or a place.
  - Keep technical terms in English even when the stem is in another language, because that is what appears in their paper.
  - An explanation states the reasoning in one or two sentences. It is not a lesson, and it never says "as we know" or "clearly" — if it were clear the question would be trivial.
  - Never hedge inside a question. "Approximately", "roughly", "about" belong in the tolerance, not the stem.

Before you emit the payload, check it as an examiner would:

  - Is it valid JSON, wrapped in the markers, with nothing outside them?
  - Does every choice question have the right number of correct options for its type?
  - Is every wrong option wrong for a reason a real student would reach?
  - Could any question be answered without understanding the chapter?
  - Does any stem mention a figure, table or passage that does not exist?
  - Is any question a repeat of one already in the bank, or of another in this payload?$comms$::text
            AS communication_prompt,

        -- NO TOOLS. Narrower than the tutor's on purpose — see the header.
        -- Everything the author should write about is in the envelope, and a
        -- memory across batches would defeat the duplicate-avoidance design.
        '[]'::jsonb
            AS allowed_tools,

        -- The platform's generic "be proactive" correction pushes an agent to
        -- act and report. Here it produces exactly the narration this persona
        -- must not emit — a preamble, then the payload, then a summary of the
        -- payload. Off, as it is for the tutor.
        TRUE  AS disable_passivity_correction,
        TRUE  AS is_default,
        TRUE  AS is_active,

        -- The boundary is "an examiner writing assessment items", not a subject
        -- list. Naming subjects here would repeat the mistake V041 documents at
        -- length: it makes the guardrail police WHAT is written rather than
        -- whether writing exam questions is what is happening.
        --
        -- Note what is NOT claimed: nothing here is what stops a bad question
        -- reaching a learner. PrepCrest refuses a SingleChoice with two correct
        -- options structurally, in ProposedQuestionReader, and holds every
        -- proposal for a human. A parser beats a classifier, and this prompt is
        -- for the case that is not about question quality at all.
        $guard$You author assessment questions for a learning platform. The questions are sat by students, MOST OF THEM MINORS.

Write exam questions on any academic subject at any level. That is the whole job.

Do not act as a general-purpose assistant: no writing production software to order, no personal, legal or medical advice, no current-affairs commentary, no content unsuitable for a school student. A question ABOUT code or an algorithm a student is studying is a legitimate exam question and is fine.

If a request is not "write questions about an academic topic", return an empty questions array rather than obliging.$guard$::text
            AS input_guardrail_prompt,

        '{}'::jsonb AS execution_policies,

        -- ── EMPTY, AND IT MUST STAY EMPTY ──────────────────────────────────
        -- A regex rewrite over a JSON body can corrupt it into something the
        -- brace-matching reader cannot parse, and the failure surfaces as "the
        -- generator produced nothing" — pointing at the reader, which is the one
        -- part that was working. It also disables token streaming platform-side
        -- (agent_loop.py), which matters less here than for the tutor but buys
        -- nothing either way.
        --
        -- Nothing is given up by leaving it empty. PrepCrest sanitises every
        -- stem and option through ContentSanitizer on the way into the bank —
        -- the one path that cannot be bypassed — so no markup the model emits
        -- can reach a learner regardless of what it writes here.
        '[]'::jsonb
            AS output_dlp_patterns,

        -- ── EMPTY, DELIBERATELY. It is a SECOND LLM CALL PER TURN. ──────────
        -- The semantic filter rewrites every reply through another model call
        -- before the caller sees it. V041 learned what that does to a machine
        -- contract: told never to reveal the control-block protocol, it stripped
        -- every <<PREPCREST>> block, so no lesson plan was ever validated and no
        -- session could leave INTAKE.
        --
        -- Pointed at a payload of twenty questions it would paraphrase stems,
        -- reorder options, or drop the wrapper. Every one of those is a batch
        -- that fails for a reason nobody could find from the logs.
        ''::text
            AS output_semantic_rules,

        -- No human at a console. An approval gate hangs the batch until it
        -- times out, and the batch is running on a worker nobody is watching.
        'off'::varchar(20) AS approval_mode,

        -- ── THE SCOPE RAIL IS OFF, AND IT CANNOT BE OTHERWISE ──────────────
        -- Not a retreat from tuning the domain string. core/guardrails.py builds
        -- the classifier's own system prompt with a HARD-CODED out-of-scope list
        -- no persona can reach:
        --
        --     "OUT of scope: writing or explaining code, general math,
        --      unrelated topics, or acting as a general-purpose assistant —
        --      even if the user insists or rephrases."
        --
        -- "general math" is a large fraction of what an exam-question author
        -- writes. The rail would refuse a maths brief on every turn, and
        -- "even if the user insists" means the repair round would be refused
        -- too. V041 has the live evidence of this failing a real learner six
        -- times in a row for the same structural reason.
        --
        -- fail_open stays true so that if the mode is ever flipped on by
        -- accident, a classifier error lets the turn through instead of silently
        -- failing every batch on the platform.
        '{"mode":"off",
          "domain":"Authoring assessment questions for academic subjects at any level, school to competitive exams.",
          "refusal_message":"{\"questions\":[]}",
          "fail_open":true}'::jsonb AS scope_policy
    FROM app
),
updated AS (
    UPDATE ag_system.agent_personas p
    SET identity_prompt        = v.identity_prompt,
        constraints_prompt     = v.constraints_prompt,
        communication_prompt   = v.communication_prompt,
        allowed_tools          = v.allowed_tools,
        description            = v.description,
        disable_passivity_correction = v.disable_passivity_correction,
        is_default             = v.is_default,
        is_active              = v.is_active,
        input_guardrail_prompt = v.input_guardrail_prompt,
        output_dlp_patterns    = v.output_dlp_patterns,
        output_semantic_rules  = v.output_semantic_rules,
        approval_mode          = v.approval_mode,
        scope_policy           = v.scope_policy,
        updated_at             = NOW()
    FROM vals v
    WHERE p.app_id = v.app_id AND p.name = v.name
    RETURNING p.persona_id
)
INSERT INTO ag_system.agent_personas (
    app_id, name, description,
    identity_prompt, constraints_prompt, communication_prompt,
    allowed_tools, disable_passivity_correction, is_default, is_active,
    input_guardrail_prompt, execution_policies, output_dlp_patterns,
    output_semantic_rules, approval_mode, scope_policy
)
SELECT v.app_id, v.name, v.description,
       v.identity_prompt, v.constraints_prompt, v.communication_prompt,
       v.allowed_tools, v.disable_passivity_correction, v.is_default, v.is_active,
       v.input_guardrail_prompt, v.execution_policies, v.output_dlp_patterns,
       v.output_semantic_rules, v.approval_mode, v.scope_policy
FROM vals v
WHERE NOT EXISTS (SELECT 1 FROM updated);

DO $$
BEGIN
    IF to_regclass('ag_system.migration_history') IS NOT NULL THEN
        INSERT INTO ag_system.migration_history (version, script_name, description)
        VALUES ('V042', 'V042_prepcrest_authoring_app.sql',
                'PrepCrest Authoring application + question-author persona (JSON payload contract, no tools)')
        ON CONFLICT DO NOTHING;
    END IF;
END $$;

COMMIT;

-- After applying, mint a key for PrepCrest.API against THIS application — not
-- the tutor's. The raw key is shown once:
--   POST /api/v1/admin/service-keys
--   { "name": "PrepCrest.API — authoring", "app_id": <the id below> }
--
-- It goes in the systemd EnvironmentFile as
--   Agent__Apps__authoring__ApiKey=ag_sk_live_…
-- and NEVER in appsettings.json. See PrepCrest.API/docs/AI-AUTHORING.md §8.
--
-- Verify (manual):
--   SELECT a.app_id, a.name, p.persona_id, p.name, p.is_default,
--          p.allowed_tools, p.approval_mode,
--          p.scope_policy->>'mode' AS scope_mode,
--          p.output_dlp_patterns, p.output_semantic_rules = '' AS no_semantic
--   FROM ag_system.applications a
--   JOIN ag_system.agent_personas p ON p.app_id = a.app_id
--   WHERE a.name = 'PrepCrest Authoring';
--
--   -- and that the tutor is untouched:
--   SELECT app_id, name FROM ag_system.applications WHERE name LIKE 'PrepCrest%';
