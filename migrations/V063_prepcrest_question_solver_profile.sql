-- ════════════════════════════════════════════════════════════════════════
-- V063 — PrepCrest's question solver runs on a model the writer does not
-- ════════════════════════════════════════════════════════════════════════
-- PrepCrest checks every question it writes with an independent solver: a
-- fresh conversation that never sees the key answers it blind
-- (PrepCrest.API 0171, QuestionVerification). The solver must be a DIFFERENT
-- model from the writer, because a fresh conversation on the writer's own
-- model agrees with its own mistakes. PrepCrest names the model on each
-- solver turn, and a requested model resolves to the active profile with
-- that name or model (llm_scope.resolve_profile).
--
-- It named openai/gpt-5.6-luna, which matched the OpenRouter "vision"
-- profile. When V059/V060 moved PrepCrest to DeepSeek, that route lost its
-- key, and every solver turn failed with OpenRouter 401 "Missing
-- Authentication header" from 2026-10-10. No question was checked, and
-- grounded batches published unchecked; one JEE question went live with a
-- wrong key (2026-10-12).
--
-- PrepCrest now names deepseek-v4-pro. No profile has that model, so the
-- name fell through to the app's own profile, and the solver ran on
-- deepseek-flash, the writer's model. The check worked but was not
-- independent. This profile makes the name mean what it says:
--
--   prepcrest-solver   deepseek / deepseek-v4-pro, authoring pool
--
-- Temperature 0: a solver reaches an answer, it does not write. Spend is
-- metered to the calling app (the authoring author whose questions are being
-- checked), within that app's daily budget. Agent.Core telemetry prices
-- deepseek-v4-pro direct at $0.66/$1.98 per M (peak doubled). Any other app
-- naming deepseek-v4-pro would also resolve here and spend the authoring pool.
--
-- ── ROLLBACK ────────────────────────────────────────────────────────────
--   UPDATE ag_system.llm_profiles SET is_active = false, updated_at = now()
--    WHERE name = 'prepcrest-solver';
-- (PrepCrest's solver then falls back to the app profile — deepseek-flash.)
--
-- Idempotent: re-running changes nothing.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

INSERT INTO ag_system.llm_profiles
    (name, provider, model, base_url, api_key, small_model, fallback_model,
     temperature, max_tokens, reasoning_effort, is_default, is_active)
VALUES ('prepcrest-solver', 'deepseek', 'deepseek-v4-pro',
        'https://api.deepseek.com/chat/completions',
        '__config:llm.api_key.prepcrest_prod_authoring__', 'deepseek-v4-pro', NULL,
        0.00, 8000, 'off', FALSE, TRUE)
ON CONFLICT (name) DO UPDATE
   SET provider = EXCLUDED.provider, model = EXCLUDED.model, base_url = EXCLUDED.base_url,
       api_key = EXCLUDED.api_key, small_model = EXCLUDED.small_model,
       fallback_model = EXCLUDED.fallback_model, temperature = EXCLUDED.temperature,
       max_tokens = EXCLUDED.max_tokens, reasoning_effort = EXCLUDED.reasoning_effort,
       is_active = TRUE, updated_at = now()
 WHERE (ag_system.llm_profiles.provider, ag_system.llm_profiles.model, ag_system.llm_profiles.api_key,
        ag_system.llm_profiles.is_active)
       IS DISTINCT FROM (EXCLUDED.provider, EXCLUDED.model, EXCLUDED.api_key, TRUE);

DO $$
DECLARE n int;
BEGIN
    -- The name PrepCrest sends must resolve to exactly this profile:
    -- find_profile_by_model takes the first active match by name OR model.
    SELECT count(*) INTO n FROM ag_system.llm_profiles
     WHERE is_active AND (name = 'deepseek-v4-pro' OR model = 'deepseek-v4-pro');
    IF n <> 1 THEN
        RAISE EXCEPTION 'V063: % active profiles answer to deepseek-v4-pro; the solver needs exactly one', n;
    END IF;
    RAISE NOTICE 'V063: deepseek-v4-pro resolves to prepcrest-solver (authoring pool).';
END $$;

COMMIT;
