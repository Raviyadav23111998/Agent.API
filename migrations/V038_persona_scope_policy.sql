-- ═══════════════════════════════════════════════════════════════════════
-- V038: Persona INPUT SCOPE RAIL (behavioral topic gate)
-- ═══════════════════════════════════════════════════════════════════════
-- Adds a first-class scope control to ag_system.agent_personas.
--
-- ROOT CAUSE this fixes (see docs/PERSONA_TOPIC_SCOPING_ROOT_CAUSE_AND_
-- GUARDRAIL_DESIGN_2026-07-05.md): a scoped persona (e.g. the Fleet copilot)
-- had NO way to stay on its domain. Topic scope existed only as free prose in
-- constraints_prompt / input_guardrail_prompt — a suggestion the model can
-- ignore, not a gate. The Fleet copilot therefore answered off-domain requests
-- (it wrote a Python script). This is the STRUCTURAL layer that prose cannot be:
-- GuardrailEngine.evaluate_input() runs a pre-generation classification and
-- short-circuits the turn BEFORE the main model generates.
--
--   scope_policy JSONB shape:
--     {
--       "mode":            "off" | "restrict",   -- default "off" = no rail
--       "domain":          "<one-line description of what the persona covers>",
--       "refusal_message": "<what the user sees when a request is out of scope>",
--       "fail_open":       true                  -- classifier error → allow (brand
--                                                --   control, not a security wall)
--     }
--
-- Layering: this sits ABOVE the existing tool whitelist + execution/output
-- guardrails. The whitelist gates ACTIONS; this gates whether the agent should
-- engage with the request at all — the gap that let plain-text answers through.
-- ═══════════════════════════════════════════════════════════════════════

BEGIN;

-- 1. Column ---------------------------------------------------------------
ALTER TABLE ag_system.agent_personas
    ADD COLUMN IF NOT EXISTS scope_policy JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN ag_system.agent_personas.scope_policy IS
    'Input scope rail: {mode:off|restrict, domain, refusal_message, fail_open}. '
    'mode=restrict runs a pre-generation topic classifier that blocks '
    'out-of-domain requests before the main model generates.';

-- 2. Populate the Fleet Management copilot --------------------------------
--    Replaces the earlier prose-only mitigation with a structural control.
--    Content-targeted (NOT a hardcoded persona_id): id numbering differs
--    across prod / uat / sit / tenant DBs, so restricting a bare id could
--    wrongly gate an unrelated persona. Match the Fleet persona by name /
--    identity; DBs without one are an intentional no-op (rail stays off by
--    the '{}' default). Only rows still on the default are set, so re-running
--    the migration will not clobber a scope_policy an operator later tuned.
UPDATE ag_system.agent_personas
SET scope_policy = jsonb_build_object(
        'mode',   'restrict',
        'domain', 'Fleet Management: vehicles, drivers, staff, maintenance, '
                  'routes, and questions answerable from Fleet Management '
                  'documentation. Driving the Fleet Management web app on the '
                  'user''s behalf (navigating pages, filling forms, clicking).',
        'refusal_message',
                  'I''m the Fleet Management copilot, so I can only help with '
                  'Fleet tasks — vehicles, drivers, staff, maintenance and '
                  'routes. I can''t help with that one. What would you like to '
                  'do in Fleet Management?',
        'fail_open', true
    )
WHERE (name ILIKE '%fleet%' OR identity_prompt ILIKE '%Fleet Management%')
  AND coalesce(scope_policy, '{}'::jsonb) = '{}'::jsonb;

COMMIT;
