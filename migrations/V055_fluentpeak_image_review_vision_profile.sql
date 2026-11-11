-- ════════════════════════════════════════════════════════════════════════
-- V055 — a vision profile, and the one application that needs it
-- ════════════════════════════════════════════════════════════════════════
-- V054's picture editor judges photographs. It was reachable, authenticated
-- and correct, and it answered its first three live turns with:
--
--     {"imageId":1,"verdict":"unrelated","note":"Attachment not accessible;
--      cannot verify content."}
--
-- Two separate faults, found in that order, and only the second is this file's
-- business — the first is fixed in the code.
--
-- ── FAULT 1 (fixed in api/repositories/file_repo.py) ────────────────────
--
-- assign_files bound an attachment with UPDATE … RETURNING through fetch_all,
-- which opens its cursor with commit=False because it is a READ helper. Every
-- binding was rolled back, RETURNING still handed back the rows it was about to
-- discard, so the call looked successful and returned the right count. Files
-- stayed at associated_id=0, hydrate_for_message found nothing, and the model
-- answered about pictures it had never received.
--
-- ── FAULT 2 (this file) ─────────────────────────────────────────────────
--
-- This tenant has exactly one LLM profile — deepseek-v4-flash, which is TEXT
-- ONLY — and _effective_model resolves the profile over a per-request `model`.
-- So a vision model asked for on the turn was silently replaced by a text one,
-- and _filter_by_capability then correctly refused to send images to it.
--
-- The fix is a profile, not a per-request override, because the model a
-- persona needs is a property of the APPLICATION rather than of one call. A
-- caller that had to remember to pass "model" on every turn would eventually
-- forget, and the failure is the expensive kind: a well-formed judgement about
-- pictures nobody looked at.
--
-- ── WHY THE DEFAULT PROFILE IS NOT TOUCHED ──────────────────────────────
--
-- Profile 1 is shared by PrepCrest, the internal assistant, email triage and
-- fleet support. Swapping its model to gain vision for one application would
-- change the model behind every one of them — a far larger blast radius than
-- the problem, and one nobody would connect to this change three weeks later.
--
-- Vision is scoped to app 12 alone. Every other FluentPeak application stays on
-- the default: the lesson author, the casting director and the phonetician all
-- produce text from text, and paying for a vision model to do that is spending
-- for nothing.
--
-- ── WHY THIS MODEL ──────────────────────────────────────────────────────
--
-- google/gemini-3.5-flash, probed live against this tenant's OpenRouter key on
-- 2026-08-06. Three things had to be true and all were checked rather than
-- assumed:
--
--   1. The key can reach it. gemini-2.0-flash-001, gemini-flash-1.5 and
--      claude-3.5-haiku all answered 404 on this key; the 3.x flash line is
--      what is actually available.
--   2. core/model_capabilities.py recognises it. _match is a SUBSTRING test, so
--      "gemini" in the id resolves to _caps(image=True, …). Worth stating
--      because the obvious alternative did not: "qwen/qwen2.5-vl-…" contains
--      neither "qwen-vl" nor "qwen2-vl" and would have been treated as
--      text-only with no warning at mint time.
--   3. It is cheap. Verification runs once per candidate SET, several hundred
--      times for a course, and a flash-tier model is the difference between a
--      line item and a rounding error.
--
-- temperature is 0.10 rather than the default 0.90. This persona is not writing
-- — it is grading, against a closed five-word vocabulary, and a high
-- temperature on a grading task buys variation nobody wants: the same three
-- photographs judged twice should reach the same verdict.
--
-- reasoning_effort is 'low' and must not be empty. This tenant's default is to
-- DISABLE reasoning, which client/cli.py sends to OpenRouter as
-- {"reasoning": {"enabled": false}} — and gemini-3.5-flash answers that with
-- "Reasoning is mandatory for this endpoint and cannot be disabled." (400, live,
-- 2026-08-06). 'low' sends {"effort": "low"}, which it accepts, and is the right
-- amount for the task anyway: deciding whether a photograph unambiguously
-- depicts a word is a judgement, not a derivation.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. The profile ──────────────────────────────────────────────────────
--
-- base_url and api_key are copied from the default profile rather than typed
-- again: they are the same OpenRouter account, and a second literal copy of a
-- credential is a second thing to rotate.
INSERT INTO ag_system.llm_profiles
    (name, provider, model, base_url, api_key, temperature, max_tokens,
     reasoning_effort, is_default, is_active)
SELECT 'vision',
       d.provider,
       'google/gemini-3.5-flash',
       d.base_url,
       d.api_key,
       0.10,
       8000,
       'low',
       FALSE,
       TRUE
  FROM ag_system.llm_profiles d
 WHERE d.is_default AND d.is_active
   AND NOT EXISTS (SELECT 1 FROM ag_system.llm_profiles WHERE name = 'vision');

-- Keep an existing 'vision' profile pointed at the model this file names, so a
-- re-run after a model change is the change rather than a no-op.
UPDATE ag_system.llm_profiles
   SET model = 'google/gemini-3.5-flash',
       temperature = 0.10,
       reasoning_effort = 'low',
       is_active = TRUE,
       updated_at = now()
 WHERE name = 'vision';

-- ── 2. The one application that needs it ────────────────────────────────
UPDATE ag_system.applications a
   SET llm_profile_id = p.profile_id
  FROM ag_system.llm_profiles p
 WHERE p.name = 'vision'
   AND a.name = 'FluentPeak Image Review';

DO $$
BEGIN
    IF to_regclass('ag_system.migration_history') IS NOT NULL THEN
        INSERT INTO ag_system.migration_history (version, script_name, description)
        VALUES ('V055', 'V055_fluentpeak_image_review_vision_profile.sql',
                'Vision LLM profile (google/gemini-3.5-flash, temp 0.10) scoped to FluentPeak Image Review. The default profile is text-only and _effective_model resolves it over a per-request model, so a vision persona could not receive images.')
        ON CONFLICT DO NOTHING;
    END IF;
END $$;

COMMIT;

-- Verify:
--   SELECT a.app_id, a.name, p.name AS profile, p.model
--     FROM ag_system.applications a
--     LEFT JOIN ag_system.llm_profiles p ON p.profile_id = a.llm_profile_id
--    WHERE a.name LIKE 'FluentPeak%' ORDER BY a.app_id;
--
-- Expect exactly one row with a profile: FluentPeak Image Review → vision.
-- The other three resolve to the default, which is correct — they produce text
-- from text.
