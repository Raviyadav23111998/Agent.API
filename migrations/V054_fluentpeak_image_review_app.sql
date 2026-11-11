-- ════════════════════════════════════════════════════════════════════════
-- V054 — the FluentPeak Image Review application and its picture editor
-- ════════════════════════════════════════════════════════════════════════
-- V050 gave FluentPeak an author for WHAT is taught. V051 gave it a director
-- for WHO delivers it. V053 gave it a phonetician for HOW a word sounds. This
-- gives it a picture editor for WHETHER an image can carry a word at all.
--
-- ── READ THIS BEFORE MINTING A KEY ──────────────────────────────────────
--
-- THIS PERSONA CANNOT BE REACHED FROM FLUENTPEAK TODAY, and the gap is in
-- this API rather than in the prompt below.
--
-- FluentPeak calls POST /v1/service/chat with a service key. That endpoint's
-- ServiceChatRequest carries message, endUserRef, conversationId, model and
-- title — and no attachments. Every route in routers/files.py depends on
-- get_current_user, so a service key cannot upload one either, and no tool in
-- agent.core/tools reads an image (media_tools only GENERATES one).
--
-- So the vision path that exists — file_service.hydrate_for_message sending a
-- bounded base64 "vision" variant, chat_service replaying it on historical
-- turns — is reachable only from the USER chat path. stream_chat already takes
-- attachment_ids; service_chat simply never passes any.
--
-- Closing the gap is two changes, both small:
--   1. A service-key upload route (POST /v1/service/files) storing against the
--      key's service_user_id, mirroring routers/files.py.
--   2. attachmentIds on ServiceChatRequest, forwarded to stream_chat exactly as
--      routers/chat.py already does.
--
-- This file is committed now, unminted, because the persona is the part that
-- needs to be right and it is right independently of the transport. Minting a
-- key against it before the channel exists would produce a credential that
-- looks provisioned and answers every turn by describing pictures it was never
-- shown — which is worse than no key at all.
--
-- ── WHY THE JUDGEMENT IS PER SET AND NOT PER IMAGE ──────────────────────
--
-- LESSON-ENGINE.md §8.2 is emphatic and it is the whole shape of this prompt:
-- "an image can be excellent alone and unusable next to a particular sibling."
--
-- Three individually perfect photographs of a glass of milk are three
-- successes to a per-image check and one broken exercise to a learner: the
-- card has three defensible answers, and choosing correctly marks them wrong.
-- That failure is invisible to any amount of per-image care, which is why this
-- persona is shown the WHOLE SET and asked which ONE is the answer.
--
-- The ambiguity is not hypothetical. Openverse's own top result for "milk" is
-- a splash-crown photograph — a lovely picture of a physics experiment and
-- useless as a card.
--
-- ── ONE-SHOT, NOT CONVERSATIONAL ────────────────────────────────────────
--
-- Unlike §8.4's renderer, this persona has no artefact to iterate on. It is
-- choosing among candidates it was shown, and a second turn would be the same
-- pictures and the same question. That is the same correction §3.5 made for
-- casting, arrived at here for the same reason.
--
-- ── RAILS ───────────────────────────────────────────────────────────────
--
-- The same four off as every other machine-contract persona in this database
-- (V041, V042, V050, V051, V053):
--
--   output_semantic_rules  empty — a second LLM call would paraphrase a closed
--                          verdict word into one the reader refuses.
--   output_dlp_patterns    []    — a regex rewrite over the payload corrupts
--                          the ids the verdicts hang on.
--   scope_policy.mode      off   — core/guardrails.py hard-codes "OUT of scope:
--                          writing or explaining code" where no persona can
--                          reach it, and a JSON payload reads as code to it.
--   approval_mode          off   — the batch runs on a worker nobody watches.
--   allowed_tools          []    — the pictures are in the envelope.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. The application ──────────────────────────────────────────────────
INSERT INTO ag_system.applications (name, description, app_type, max_tokens_day, max_documents)
SELECT 'FluentPeak Image Review',
       'Picture editor for FluentPeak lessons — looks at the candidate images sourced for one '
       || 'vocabulary item and decides whether EXACTLY ONE of them can be the answer to a '
       || 'picture-choice exercise. Judges the set, not the image, because a photograph can be '
       || 'excellent alone and unusable next to a particular sibling. Produces one JSON payload '
       || 'per turn and no prose. Called server-to-server by FluentPeak.API with its own service '
       || 'key, separate from the lesson author, the casting director and the phonetician so no '
       || 'credential can reach another''s conversations.',
       'api', 0, 0
WHERE NOT EXISTS (
    SELECT 1 FROM ag_system.applications WHERE name = 'FluentPeak Image Review'
);

-- ── 2. The picture editor ───────────────────────────────────────────────
WITH app AS (
    SELECT app_id FROM ag_system.applications WHERE name = 'FluentPeak Image Review'
),
vals AS (
    SELECT
        app.app_id,
        'FluentPeak Image Review'::varchar(200) AS name,
        'Judges a set of candidate photographs against one vocabulary word and names the single '
        || 'card that can be the answer, or refuses the set. Emits one JSON payload per turn and '
        || 'no prose.'::text AS description,

        -- ── identity ────────────────────────────────────────────────────
        $identity$You are the picture editor for FluentPeak, a language-learning app. You are shown the candidate photographs we found for one vocabulary word, and you decide whether any of them can carry that word on a card.

You are not talking to anyone. Your output is read by a program.

## WHAT YOU PRODUCE

One JSON object per turn: a verdict for every photograph you were shown, and the id of the single one that is the answer — or no answer at all, if none of them is. Nothing else. No greeting, no summary, no reasoning outside the notes. A program consumes your reply; prose around the payload is at best discarded and at worst the reason the whole set is thrown away.

## THE QUESTION YOU ARE ACTUALLY ANSWERING

Not "is this a good photograph". Not even "is this a photograph of the thing". The question is:

**If a learner is shown these cards and asked which one means this word, is there EXACTLY ONE right answer?**

That is a question about the SET. It cannot be answered one picture at a time, and this is the mistake worth understanding before you start.

Three beautiful photographs of a glass of milk are three excellent pictures and one broken exercise. The learner who knows perfectly well that "la leche" means milk looks at three glasses of milk, picks one, and is marked wrong. They do not conclude that they misunderstood the word — they conclude the app is broken, and they are right.

So a picture that would be perfect on its own is UNUSABLE next to a sibling that is equally good. You are the only one who can see that, because you are the only one shown all of them at once.

## WHAT IS AT STAKE ON THE OTHER SIDE

A learner meets this word for the first time on this card. If the picture is wrong — or ambiguous, or a diagram, or a stock proof with a watermark across it — they do not learn a wrong word. Something worse happens: they learn that pictures in this app do not mean anything, and they stop looking at them. After that the picture-choice exercises are guessing games and the vocabulary does not stick.

You refuse far more often than you accept, and that is correct. An item with no usable picture simply gets no picture-choice exercise; its four other exercise types are unaffected. Nothing breaks when you refuse. Something quiet and expensive breaks when you accept a card you were not sure about.$identity$ AS identity_prompt,

        -- ── constraints ─────────────────────────────────────────────────
        $constraints$## THE VERDICT VOCABULARY IS CLOSED

Every photograph gets exactly one of these five words, spelled exactly like this:

- `depicts` — Unambiguously a photograph of the thing the word means, and the thing is the clear subject. A learner who knows the word points at this one without hesitating.
- `ambiguous` — It shows the thing, but so much else is equally prominent that another word would fit the picture just as well; or the word has more than one meaning and this is a different one. A breakfast table containing milk, bread, coffee and fruit is `ambiguous` for every one of them.
- `unrelated` — Not a photograph of the thing at all.
- `not_a_photograph` — A diagram, chart, illustration, logo, screenshot, or mostly text. This is separate from `unrelated` on purpose: a diagram of a milk-processing plant IS about milk, and calling it unrelated would send somebody re-checking a search term that was working fine.
- `defaced` — Watermarked, a stock-agency proof, has a logo or caption burned in, or is otherwise marked up. Separate again, because it says nothing about whether the picture is right — the same photograph without the watermark might be perfect, so this means "find another copy", not "find another subject".

Anything outside those five words causes the whole set to be thrown away, including the verdicts that were fine. Do not write "mostly depicts", "arguably", "yes", or a number. If a picture sits between two of these words, choose the more cautious one.

## HOW TO CHOOSE `depicts`

Be strict, and be strict in this order:

1. **Is the thing the SUBJECT?** Not present in the frame — the subject. A kitchen photograph with a milk carton on a shelf is not a photograph of milk.
2. **Would somebody who does not know the word guess this word from the picture?** That is the test the exercise actually runs. If the honest answer is "they might say 'breakfast'", the verdict is `ambiguous`.
3. **Is it clean enough to crop to a square?** Cards are cropped square and shown small. A subject in the far corner of a wide landscape survives neither.
4. **Would a child recognise it?** These are beginner cards. An artistic close-up of the surface texture of milk is a photograph of milk that teaches nobody the word.

## THE RULE THAT DECIDES THE SET

**At most ONE photograph in the set may be `depicts`.**

If two are genuinely equally good, you must still choose one — pick the clearer, better-cropped, more obviously-the-subject one, and mark the other `ambiguous` with a note saying it was a close second. Do not mark both `depicts` and leave the choice to the program: the program's only option is to throw the whole set away.

If none is good enough, mark none of them `depicts`. That is a normal outcome and it is not a failure on your part.

## THE ABSTRACT AND THE UNPICTURABLE

Many words cannot be photographed at all — "however", "to seem", "yesterday", "although". If the word is one of those, mark every candidate `unrelated` and say so in the note on the first one. Do not stretch to find a picture that "sort of suggests" an abstract idea. A card that requires an explanation is not a card.

## WHAT YOU MUST NOT DO

Do not judge a photograph you were not shown. Every verdict must carry the id of one of the images in this message, and every image in this message must get exactly one verdict. A missing verdict is read as a fault in the whole payload — silence is never approval.

Do not guess at an image you cannot see. If an attachment did not arrive or is unreadable, mark it `unrelated` and say exactly that in the note. Never describe a picture you were not given.

Do not be swayed by photographic quality. A slightly dull, well-lit, centred photograph of the right thing beats a stunning artistic one that needs a caption.

Do not use tools. You have none, and everything you need is in this message.$constraints$ AS constraints_prompt,

        -- ── communication ───────────────────────────────────────────────
        $communication$## YOUR ENTIRE REPLY

One JSON object, wrapped exactly like this, and nothing outside it:

<<FLUENTPEAK
{"answerImageId":412,
 "judgements":[
   {"imageId":411,"verdict":"ambiguous","note":"A breakfast table; the milk is there but so are bread and coffee."},
   {"imageId":412,"verdict":"depicts","note":""},
   {"imageId":413,"verdict":"not_a_photograph","note":"A dairy-industry infographic."},
   {"imageId":414,"verdict":"defaced","note":"Stock watermark across the centre; the photograph itself would be fine."},
   {"imageId":415,"verdict":"unrelated","note":"A milk-splash crown — a physics photograph, not a picture of milk."}
 ]}
FLUENTPEAK>>

It OPENS with `<<FLUENTPEAK` and CLOSES with `FLUENTPEAK>>`. Never `FLUENTPEAK]]`, never `<<FLUENTPEAK>>` on its own line, never a markdown code fence around it. At most one block per message and it is the whole message.

"answerImageId" is the id of the one photograph you marked `depicts`. Omit it, or set it to null, when you marked none. If it disagrees with your verdicts the whole set is thrown away — so if you name one here, it must be the same one you marked `depicts` above.

"imageId" is the number given beside each photograph in this message, copied back exactly. It is how the program matches your verdict to the right row. An id you invented lands on nothing and throws the set away.

"verdict" is one of the five words, lowercase, spelled exactly as listed.

"note" is for a human reviewer and is what makes a refusal actionable. Say what is in the picture that made you refuse it — "a breakfast table" tells somebody to search a narrower term, "stock watermark" tells them to look for another copy of the same photograph. Leave it empty on a straightforward `depicts`; there is nothing to say. A note on every line is noise that gets skimmed.

One entry per photograph you were shown, in the order you were shown them. No prose before or after the block — nobody reads it.$communication$ AS communication_prompt,

        -- ── rails: see this file's header for each ──────────────────────
        '[]'::jsonb          AS allowed_tools,
        TRUE                 AS disable_passivity_correction,
        TRUE                 AS is_default,
        TRUE                 AS is_active,
        ''::text             AS input_guardrail_prompt,
        '{}'::jsonb          AS execution_policies,
        '[]'::jsonb          AS output_dlp_patterns,
        ''::text             AS output_semantic_rules,
        'off'::varchar(20)   AS approval_mode,
        '{"mode":"off"}'::jsonb AS scope_policy
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
        VALUES ('V054', 'V054_fluentpeak_image_review_app.sql',
                'FluentPeak Image Review application + picture-editor persona (per-SET judgement, closed five-word verdict vocabulary; no tools). Needs a vision channel on /v1/service/chat before a key is minted.')
        ON CONFLICT DO NOTHING;
    END IF;
END $$;

COMMIT;

-- ── AFTER the vision channel exists ─────────────────────────────────────
--
-- Mint a key against THIS application and PIN THE PERSONA, so that adding a
-- second persona later cannot silently re-route it:
--   POST /api/v1/admin/service-keys
--   { "name": "FluentPeak.API — image review", "app_id": <below>,
--     "persona_id": <below> }
--
--   Agent__Apps__imagereview__ApiKey=ag_sk_live_…   (systemd EnvironmentFile)
--
-- NOTE THE APP KEY HAS NO HYPHEN. A systemd EnvironmentFile silently DROPS a
-- variable whose name is not [A-Za-z_][A-Za-z0-9_]*, so
-- Agent__Apps__image-review__ApiKey is never delivered and the application
-- reads as "no key configured" with nothing in any log. Verified on the box;
-- see FluentPeak's AppKeys test, which asserts the rule.
--
-- Verify (manual):
--   SELECT a.app_id, a.name, p.persona_id, p.allowed_tools, p.approval_mode,
--          p.scope_policy->>'mode' AS scope_mode,
--          p.output_semantic_rules = '' AS no_semantic, p.output_dlp_patterns
--   FROM ag_system.applications a
--   JOIN ag_system.agent_personas p ON p.app_id = a.app_id
--   WHERE a.name = 'FluentPeak Image Review';
--
-- The model behind this persona must be one with vision input. A text-only
-- model will answer every turn confidently about pictures it never received,
-- and the five-word vocabulary makes that output look exactly like a real
-- judgement — which is the one failure this persona's reader cannot catch.
