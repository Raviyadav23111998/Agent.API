-- ════════════════════════════════════════════════════════════════════════
-- V060 — PrepCrest calls DeepSeek directly, within a daily budget
-- ════════════════════════════════════════════════════════════════════════
-- Every PrepCrest profile spent through OpenRouter. From 10 Oct 2026 they
-- call DeepSeek's own API: the same two pools V059 drew (learner, authoring),
-- now holding DeepSeek keys.
--
-- ── 1. THE PROFILES ─────────────────────────────────────────────────────
--
-- Seven PrepCrest profiles move to provider deepseek, model deepseek-flash
-- (DeepSeek V4.1 Flash — it reads images, which the script reader needs;
-- Agent.Core a9d7cc7 makes chat_service stop dropping them). Each profile's
-- api_key names its pool, so a service key minted without a credential spends
-- the right DeepSeek key instead of the default profile's OpenRouter one.
--
--   profile                       pool       was
--   prepcrest-upsc         (6)    learner    openrouter deepseek-v4-flash
--   prepcrest-evaluator-*  (8–10) learner    openrouter gpt-5.6-luna (+ gemini fallback)
--   prepcrest-authoring    (7)    authoring  openrouter deepseek-v4-flash
--   prepcrest-lesson       (11)   authoring  openrouter deepseek-v4-flash
--   prepcrest-atlas        (13)   authoring  openrouter deepseek-v4-flash
--
-- Temperature, max_tokens and reasoning_effort are kept: they are tuned per
-- job and are not about the provider. fallback_model goes: the fallbacks were
-- other vendors' models through OpenRouter, which a DeepSeek endpoint cannot
-- serve; a second DeepSeek model would fail with the first. PrepCrest's
-- callers already put work back and retry on an outage.
--
-- The TUTOR (app 6) had no profile and ran on the tenant default — shared
-- with Internal AI Assistant, Email Triage and Fleet Support. It gets its own,
-- copied from the default's tuning (reasoning high, max_tokens 16000), so this
-- moves PrepCrest and nothing else.
--
-- ── 2. THE AUTHORING BUDGET ─────────────────────────────────────────────
--
-- OpenRouter capped a KEY; DeepSeek cannot — both keys draw on one account.
-- So the cap moves here, into the platform's own budgets, enforced before
-- every turn on the ledger (Agent.Core 8f55df3 prices DeepSeek-direct calls on
-- DeepSeek's list, doubled in its peak windows). One block budget per
-- authoring application, per DAY, together ≈ $1/day (the $30/month decided):
-- per app so one runaway author cannot spend its siblings' share, per day so a
-- month's budget cannot go in a week. Split by each app's share of September's
-- turns. The learner apps have none — a learner is never refused for budget.
--
-- PrepCrest pauses its authoring jobs during DeepSeek's peak hours on its own
-- side (PrepCrest.API 0227, system.job.off_peak_only), so most of this budget
-- is spent at the off-peak price.
--
-- ── ROLLBACK ────────────────────────────────────────────────────────────
-- Put back OpenRouter keys in the two pool rows (deploy/set-ai-key.sh), then:
--   UPDATE ag_system.llm_profiles SET provider='openrouter',
--          base_url='https://openrouter.ai/api/v1/chat/completions',
--          model=CASE WHEN profile_id IN (8,9,10) THEN 'openai/gpt-5.6-luna' ELSE 'deepseek/deepseek-v4-flash' END,
--          small_model=CASE WHEN profile_id IN (8,9,10) THEN 'openai/gpt-5.6-luna' ELSE 'deepseek/deepseek-v4-flash' END,
--          fallback_model=CASE WHEN profile_id IN (8,9,10) THEN 'google/gemini-2.5-flash'
--                              WHEN profile_id = 13 THEN NULL ELSE 'openai/gpt-5.6-luna' END,
--          updated_at=now()
--    WHERE name IN ('prepcrest-upsc','prepcrest-authoring','prepcrest-evaluator-reader',
--                   'prepcrest-evaluator-examiner','prepcrest-evaluator-mentor','prepcrest-lesson','prepcrest-atlas');
--   UPDATE ag_system.applications SET llm_profile_id = NULL WHERE name = 'PrepCrest Tutor';
-- (The profiles' api_key was the OpenRouter key itself; with the sentinel
-- left in place they spend the pools, which is what V059 wanted anyway.)
--
-- Idempotent: re-running changes nothing.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

-- The tutor's own profile, from the default's tuning.
INSERT INTO ag_system.llm_profiles
    (name, provider, model, base_url, api_key, small_model, fallback_model,
     temperature, max_tokens, reasoning_effort, is_default, is_active)
SELECT 'prepcrest-tutor', 'deepseek', 'deepseek-flash',
       'https://api.deepseek.com/chat/completions',
       '__config:llm.api_key.prepcrest_prod_learner__', 'deepseek-flash', NULL,
       d.temperature, d.max_tokens, d.reasoning_effort, FALSE, TRUE
  FROM ag_system.llm_profiles d
 WHERE d.is_default AND d.is_active
ON CONFLICT (name) DO NOTHING;

UPDATE ag_system.applications a
   SET llm_profile_id = p.profile_id, updated_at = now()
  FROM ag_system.llm_profiles p
 WHERE p.name = 'prepcrest-tutor'
   AND a.name = 'PrepCrest Tutor'
   AND a.llm_profile_id IS DISTINCT FROM p.profile_id;

UPDATE ag_system.llm_profiles p
   SET provider = 'deepseek',
       model = 'deepseek-flash',
       small_model = 'deepseek-flash',
       fallback_model = NULL,
       base_url = 'https://api.deepseek.com/chat/completions',
       api_key = v.cred,
       updated_at = now()
  FROM (VALUES
        ('prepcrest-upsc',               '__config:llm.api_key.prepcrest_prod_learner__'),
        ('prepcrest-evaluator-reader',   '__config:llm.api_key.prepcrest_prod_learner__'),
        ('prepcrest-evaluator-examiner', '__config:llm.api_key.prepcrest_prod_learner__'),
        ('prepcrest-evaluator-mentor',   '__config:llm.api_key.prepcrest_prod_learner__'),
        ('prepcrest-authoring',          '__config:llm.api_key.prepcrest_prod_authoring__'),
        ('prepcrest-lesson',             '__config:llm.api_key.prepcrest_prod_authoring__'),
        ('prepcrest-atlas',              '__config:llm.api_key.prepcrest_prod_authoring__')
       ) AS v(name, cred)
 WHERE p.name = v.name
   AND (p.provider, p.model, p.base_url, p.api_key, p.fallback_model)
       IS DISTINCT FROM ('deepseek', 'deepseek-flash', 'https://api.deepseek.com/chat/completions', v.cred, NULL);

INSERT INTO ag_system.budgets (scope_type, scope_id, win, max_tokens, max_usd, action, is_active)
SELECT 'app', a.app_id, 'day', 0, v.usd, 'block', TRUE
  FROM (VALUES
        ('PrepCrest Lesson Author',                  0.40),
        ('PrepCrest Civil Services Artifact Author', 0.30),
        ('PrepCrest Current Affairs Editor',         0.10),
        ('PrepCrest Scheme Author',                  0.05),
        ('PrepCrest Atlas Author',                   0.05),
        ('PrepCrest Editorial Analyst',              0.03),
        ('PrepCrest Secondary Artifact Author',      0.03),
        ('PrepCrest Entrance Artifact Author',       0.02),
        ('PrepCrest Primary Artifact Author',        0.02),
        ('PrepCrest Syllabus Mapper',                0.02),
        ('PrepCrest Class Course Architect',         0.02)
       ) AS v(name, usd)
  JOIN ag_system.applications a ON a.name = v.name
ON CONFLICT (scope_type, COALESCE(scope_id, 0), win) DO NOTHING;

COMMIT;
