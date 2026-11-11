-- V014: Per-persona HITL approval mode.
--
-- approval_mode on ag_system.agent_personas controls whether the agent
-- pauses for human approval before irreversible tool calls (send email,
-- shell, delete, push):
--   'irreversible' — ask the user before such actions
--   'off'          — never ask
--   NULL           — inherit the global default
--                    (agent.approval_mode / bot.approval_mode config,
--                     which defaults to 'irreversible' for interactive
--                     surfaces; cron/automation is always off)

ALTER TABLE ag_system.agent_personas
    ADD COLUMN IF NOT EXISTS approval_mode VARCHAR(20) DEFAULT NULL;

ALTER TABLE ag_system.agent_personas
    DROP CONSTRAINT IF EXISTS agent_personas_approval_mode_check;

ALTER TABLE ag_system.agent_personas
    ADD CONSTRAINT agent_personas_approval_mode_check
    CHECK (approval_mode IS NULL OR approval_mode IN ('off', 'irreversible'));

COMMENT ON COLUMN ag_system.agent_personas.approval_mode IS
    'HITL approval gate: ''irreversible'' = ask user before irreversible tools, ''off'' = never ask, NULL = inherit global config';
