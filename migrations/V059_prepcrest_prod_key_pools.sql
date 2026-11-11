-- ════════════════════════════════════════════════════════════════════════
-- V059 — PrepCrest production spends from two pools, not one
-- ════════════════════════════════════════════════════════════════════════
-- V058 let a service key name its own provider credential, and every
-- PrepCrest PRODUCTION key (25–41) names one: llm.api_key.prepcrest_prod.
-- One OpenRouter key, one limit — so the content pipelines, which spend
-- ~99% of it (lesson author $19, civil services author $13, current affairs
-- $3.7 in the 30 days to 10 Oct 2026, against $0.40 for every learner-facing
-- turn together), run the key out and the answer evaluator, the tutor and
-- the mentor stop with them. A learner is refused because a back-office
-- batch was busy.
--
-- Two pools, by who is waiting for the answer:
--
--   llm.api_key.prepcrest_prod_learner     a learner is waiting
--       PrepCrest UPSC Mentor   (mentor chat + its knowledge-sync key)
--       PrepCrest Tutor
--       PrepCrest Script Reader, Answer Examiner, Answer Mentor (evaluator)
--
--   llm.api_key.prepcrest_prod_authoring   nobody is waiting
--       every other PrepCrest production key: lesson, question, course,
--       current affairs, editorial, scheme, atlas authors, syllabus mapper
--
-- Each row holds its own OpenRouter key. The authoring key carries a
-- monthly limit on OpenRouter ($30), so generation stops at its cap and
-- the learner key — no limit of its own — keeps answering for as long as
-- the account has credit. A limit caps a key; it cannot reserve money, so
-- keeping the account's balance above the authoring cap is what makes the
-- learner pool safe. That and the rotation procedure are in PrepCrest.API
-- docs/AI-KEYS.md.
--
-- ZERO BEHAVIOUR CHANGE on apply: both rows are seeded with the value
-- llm.api_key.prepcrest_prod holds today, so every key spends exactly
-- where it did. The split happens when the operator writes the two new
-- OpenRouter keys into the rows (effective within the 30 s auth cache).
--
-- Only keys on the prod sentinel are moved — UAT's (revoked) keys and
-- other products' keys are untouched — and a re-run moves only a production
-- key minted since onto the old sentinel, by the same rule. The old row is
-- kept, marked retired: once its OpenRouter key is deleted, a key minted
-- onto it by mistake fails loudly instead of spending unbudgeted.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

INSERT INTO ag_system.configs
    (config_key, config_value, description, is_secret, is_active,
     config_type, config_group, sort_order, requires_restart)
SELECT v.config_key, src.config_value, v.description, TRUE, TRUE,
       src.config_type, src.config_group, v.sort_order, FALSE
  FROM ag_system.configs src
 CROSS JOIN (VALUES
    ('llm.api_key.prepcrest_prod_learner', 103,
     'OpenRouter key for PrepCrest PRODUCTION turns a learner is waiting on — mentor, tutor, answer evaluator (V059). No monthly limit on OpenRouter. Rotate here; takes effect within 30s.'),
    ('llm.api_key.prepcrest_prod_authoring', 104,
     'OpenRouter key for PrepCrest PRODUCTION content generation — lesson/question/course/current-affairs/scheme/atlas authors, syllabus mapper (V059). Carries a monthly limit on OpenRouter so it cannot spend the learner pool''s credit. Rotate here; takes effect within 30s.')
 ) AS v(config_key, sort_order, description)
 WHERE src.config_key = 'llm.api_key.prepcrest_prod'
ON CONFLICT (config_key) DO NOTHING;

-- The learner pool, by application name: the names are what V041/V0NN
-- created and what an operator reads; ids differ between tenants.
UPDATE ag_system.service_keys k
   SET llm_api_key = '__config:llm.api_key.prepcrest_prod_learner__', updated_at = now()
  FROM ag_system.applications a
 WHERE a.app_id = k.app_id
   AND k.llm_api_key = '__config:llm.api_key.prepcrest_prod__'
   AND a.name IN ('PrepCrest UPSC Mentor', 'PrepCrest Tutor',
                  'PrepCrest Script Reader', 'PrepCrest Answer Examiner', 'PrepCrest Answer Mentor')
   AND EXISTS (SELECT 1 FROM ag_system.configs WHERE config_key = 'llm.api_key.prepcrest_prod_learner');

-- Everything else PrepCrest production calls is generation.
UPDATE ag_system.service_keys k
   SET llm_api_key = '__config:llm.api_key.prepcrest_prod_authoring__', updated_at = now()
 WHERE k.llm_api_key = '__config:llm.api_key.prepcrest_prod__'
   AND EXISTS (SELECT 1 FROM ag_system.configs WHERE config_key = 'llm.api_key.prepcrest_prod_authoring');

UPDATE ag_system.configs
   SET description = 'RETIRED by V059 — no PrepCrest key should name this row. New production keys name llm.api_key.prepcrest_prod_learner or llm.api_key.prepcrest_prod_authoring.',
       updated_at = now()
 WHERE config_key = 'llm.api_key.prepcrest_prod'
   AND description NOT LIKE 'RETIRED%';

COMMIT;
