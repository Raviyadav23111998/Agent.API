# Persona Governance Across Surfaces — Audit & Implementation Plan (2026-07-05)

Author: senior-eng audit. Scope: why cron jobs do **not** run under a persona while
bot/chat do, the architectural root cause, and a clean (non-patch) plan to (a) make
crons pass through the persona, (b) support **multiple personas per app**, and (c) let
an operator **assign a specific persona to a specific task (cron job)**.

---

## PART A — AUDIT

### A.1 What a "persona" is and where it lives

`ag_system.agent_personas` (tenant DB), one row per persona, **scoped to `app_id`**:

| column | drives |
|---|---|
| `identity_prompt`, `constraints_prompt`, `communication_prompt` | the system-prompt overrides |
| `disable_passivity_correction` | engine passivity behaviour |
| `allowed_tools` (jsonb) | the deterministic tool whitelist |
| `input_guardrail_prompt`, `execution_policies`, `output_dlp_patterns`, `output_semantic_rules` | the GuardrailEngine |
| `approval_mode` | HITL approval policy |
| `is_default` (per app), `is_active` | selection |

Resolution API (`api/repositories/persona_repo.py`):
- `get_persona(persona_id)` — a specific persona.
- `get_persona_for_app(app_id)` — the **`is_default = TRUE`** persona for that app.
- `list_personas(app_id)` — all personas for an app. **Multiple personas per app are already a first-class data-model concept.**

The repo's own docstring states the intended contract: *"every bot/agent MUST have a
persona linked via its app_id. There is no fallback to file-based prompts."* — crons
violate this contract today.

### A.2 Applying a persona is SEVEN wiring steps

When a surface builds an `AgentLoop`, the persona drives seven distinct things
(observed in `chat_service._create_agent`, `agent.api/api/services/chat_service.py:190–403`):

1. **prompt_overrides** — identity / constraints / communication / disable_passivity → `AgentLoop(prompt_overrides=…)`.
2. **GuardrailEngine(persona)** — input guardrail, output DLP, semantic rules, execution policies → `AgentLoop(guardrail_engine=…)`.
3. **Dynamic-op registration** — `_integrations.register_session_direct(registry, ctx, persona_id=…)` (which dynamic API tools this persona may see).
4. **Tool whitelist** — `effective_allowed_tools(db, persona.allowed_tools, app_id, persona_id)` → a **filtered** `ToolRegistry` (+ the skills-tools reconciliation).
5. **approval_mode** — `persona.approval_mode` → `ApprovalManager`.
6. **dynamic_picker** — `_integrations.make_picker(ctx, persona_id=…)`.
7. **scope_meta** — `persona_id` propagated for telemetry/attribution.

### A.3 The gap — three agent-construction sites, only two apply persona

There are **three** places an interactive/automated `AgentLoop` is built, plus the
factory for system sub-agents:

| Site | File:line | Persona applied? |
|---|---|---|
| Web chat / embed | `api/services/chat_service.py:190–403` | ✅ all 7 steps |
| Bot session (Telegram/Teams) | `gateway/runner.py:262–360` (`SessionManager.get_or_create`) | ✅ all 7 steps — **duplicated copy of chat_service** |
| **Cron (plain)** | `gateway/runner.py:1035–1103` (`_run_agent_for_cron`) | ❌ **NONE** |
| Cron `[AGENT:name]` | `gateway/runner.py:_run_agent_cron` → `factory.run_agent` | ❌ persona bypassed (uses the AgentDefinition's own tool list) |
| Sub-agents / reviewer / curator | `agents/factory.py` | ❌ by design (system agents, not app personas) |

**`_run_agent_for_cron` builds a naked agent:**
```python
cron_tools = self._cli.create_user_tools(cron_workspace, sandboxed=True)   # FULL registry
cron_agent = AgentLoop(cron_workspace, llm_client, cron_tools, cron_bus,
                       user_context=create_cron_user(app_id=app_id), …)
# no prompt_overrides, no guardrail_engine, no allowed_tools filter,
# no approval_manager-from-persona, no dynamic_picker, no persona scope_meta
```

Consequence (the reported bug): a cron for an app that has a persona runs with a
**different identity, the full unfiltered toolset, and none of the persona's guardrails,
DLP, or approval policy.** The bot for the same app behaves correctly because it goes
through `get_or_create`.

### A.4 Root cause

**Agent construction + persona application is copy-pasted, not shared.** Because the
logic was duplicated into `get_or_create` rather than extracted, the third consumer
(the cron runner) was written independently and simply never got the block. This is a
DRY / single-responsibility failure, not a one-line omission — patching only the cron
path would create a *third* copy to drift.

### A.5 Secondary findings

1. **No per-task persona.** `ag_agents.cron_jobs` has `app_id` (NOT NULL default 1) but
   **no `persona_id`**. `CronJobCreateRequest`/`UpdateRequest` (`api/schemas/cron.py`)
   and `cron.jobs.create_job` have no persona field. There is no way to say "run *this*
   job under *that* persona." A given app can only ever express one behaviour for all
   its crons (the app default), even though the data model supports many personas.
2. **`get_persona_for_app` only ever returns the default.** Multi-persona exists in
   storage and in `list_personas`, but selection is hard-wired to `is_default` at every
   call site — there is no "resolve persona for this run" abstraction that can honour an
   explicit choice.
3. **`[AGENT:name]` crons** are governed by the AgentDefinition tool list, a *second*
   governance model living beside personas. Acceptable for named system agents, but it
   means "cron governance" is currently two disjoint mechanisms.
4. **Deploy-ordering hazard (known lesson).** The cron scheduler
   (`agent.core/cron/scheduler.py:111`) calls `run_agent(prompt, app_id=…)`. Threading a
   new `persona_id` kwarg is a core→api call-contract change — per the 2026-07-02
   incident, the api runner MUST accept the new kwarg (default `None`) **before** core
   starts sending it.

### A.6 Fleet use-case impact

Fleet is an app (its own `app_id`) with a persona applied to its bot. Its automations
(e.g. the email→Jira cron) run through `_run_agent_for_cron` → **no persona** → wrong
identity, unfiltered tools, no guardrails/approval. The operator also wants *different*
automations to behave *differently* (e.g. a read-only digest cron vs. a ticket-creating
cron) — impossible today because all of an app's crons share the single default persona
(and in fact currently share *no* persona).

---

## PART B — IMPLEMENTATION PLAN (architectural, not a patch)

### B.1 Design principle — ONE persona seam

Introduce a single **`PersonaApplicator`** (`api/services/persona_applicator.py`) that is
the *only* place persona is resolved and wired. Every surface — chat, bot, cron — calls
it. This removes the duplication (A.4) and fixes the cron gap *by construction* (a new
surface cannot forget persona because building the agent goes through the applicator).

```python
@dataclass
class AppliedPersona:
    persona: dict | None
    prompt_overrides: dict
    guardrail_engine: GuardrailEngine | None
    tool_registry: ToolRegistry          # already filtered + skills-reconciled
    approval_mode: str
    dynamic_picker: object | None
    scope_meta: dict                      # {persona_id, app_id, integration_id}

def resolve_persona(db, *, app_id, persona_id=None, embed=None) -> dict | None:
    # precedence: explicit persona_id  >  app default  >  None
    if persona_id: return PersonaRepository(db).get_persona(persona_id)
    if embed and embed.get("persona_id"): return PersonaRepository(db).get_persona(embed["persona_id"])
    if app_id:     return PersonaRepository(db).get_persona_for_app(app_id)
    return None

def apply_persona(cli, db, *, base_registry, user_ctx, app_id,
                  persona_id=None, embed=None, user_id=None) -> AppliedPersona:
    # the SEVEN steps from A.2, exactly once, returned as a value object.
```

Layering stays correct: applicator is api-layer (owns DB + integrations); the engine
still just receives `prompt_overrides` / `guardrail_engine` / `approval_manager` /
filtered registry — no engine change for persona itself.

### B.2 Phases

| Phase | Work | Risk | Est |
|---|---|---|---|
| **P0** | Extract `PersonaApplicator`; refactor `chat_service._create_agent` and `get_or_create` to call it. **Behaviour-preserving** — verified by identical persona wiring on chat + bot before touching cron. | Med (touches 2 hot paths) — mitigated by keeping the exact 7 steps and testing chat+bot first. | 1d |
| **P1** | Wire cron through the applicator: `_run_agent_for_cron` resolves persona (`persona_id` from the job → app default) and builds the agent from `apply_persona(...)`. Same for the delivered digest/approval. | Low–Med | 0.5d |
| **P2** | Per-task assignment. `V037`: `ALTER TABLE ag_agents.cron_jobs ADD COLUMN persona_id INTEGER` + cross-schema FK to `ag_system.agent_personas(persona_id) ON DELETE SET NULL` (same tenant DB). Thread `persona_id`: `create_job(persona_id=…)`, scheduler passes `run_agent(prompt, app_id, persona_id)`, runner default `persona_id=None` **deployed api-first**. Extend `CronJobCreate/UpdateRequest` + `cron_service` + `cron_admin` router (camelCase `personaId`). | Med (schema + call-contract) — deploy-order guard from A.5. | 1d |
| **P3** | Multi-persona UX. Persona admin page: create/list/edit personas per app, set default, activate/deactivate (repo already supports it). Crons page: a persona picker per job (defaults to "App default"). `list_personas(app_id)` endpoint (add if missing). | Low | 1d |
| **P4** | Tests + live verify on prod fleet app: bot and cron of the same app now share identity/tools/guardrails; a second persona assigned to one cron changes only that cron. | — | 0.5d |

Total ≈ **4 dev-days**.

### B.3 Persona resolution precedence (single rule, everywhere)

```
explicit persona_id (embed persona / cron job.persona_id)
  → app default (is_default persona for app_id)
    → None  (naked; log a warning — matches today's bot behaviour, never silently for crons)
```

### B.4 Governance / correctness guarantees

- A cron with `persona_id` set runs under exactly that persona's identity, whitelist,
  guardrails, DLP, approval_mode — identical wiring to the bot (shared code path).
- A cron with no `persona_id` inherits the app's **default** persona (not "no persona").
- Deleting a persona sets dependent crons' `persona_id` → NULL (they fall back to app
  default), never orphaning a job.
- `[AGENT:name]` crons keep their AgentDefinition governance (documented as the "named
  system agent" path); optional future unification noted, not in scope.
- Skills/learning tool reconciliation (the "keep skill tools even under a whitelist"
  rule) lives inside the applicator so it applies to crons too.

### B.5 Tests

- Unit: `resolve_persona` precedence; `apply_persona` returns filtered registry = whitelist ∩ base (+ skills tools); empty-whitelist warning.
- Regression: chat + bot produce byte-identical persona wiring pre/post refactor.
- Cron: a job with `persona_id` builds an agent whose tool set == persona whitelist and whose prompt carries the identity; a job without it uses the app default.
- Deploy-order: runner accepts a call *without* `persona_id` (old scheduler) and *with* it.

### B.6 Deploy sequence (safe)

1. Ship P0/P1 (api + applicator) — runner already accepts `persona_id=None`.
2. Ship V037 migration (additive, idempotent, guarded).
3. Ship P2 core scheduler change (now safe: runner already tolerates the kwarg).
4. Ship P3 web.
5. Verify on the fleet app (main → prod).

---

## PART C — ONE-LINE SUMMARY

Persona application is duplicated in chat and bot and **absent** in cron. Fix = extract a
single `PersonaApplicator` all three call, add `cron_jobs.persona_id` for per-task
persona selection (default → app default), and surface persona pickers in the UI. No
patching a third copy; one seam, one rule.
