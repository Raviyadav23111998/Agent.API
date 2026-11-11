"""
Persona Applicator — THE single seam that resolves an app persona and wires it
onto an agent session. Web chat, the bot channels (Telegram/Teams) and cron all
call this, so a persona's identity, guardrails, tool whitelist, approval policy,
dynamic ops and picker are applied IDENTICALLY. No surface can silently run
"naked": building the agent goes through here.

Before this module the wiring was copy-pasted into chat_service and the gateway
session builder, and the cron runner had no copy at all — so crons ran with the
full unfiltered toolset and no persona. See
docs/PERSONA_CRON_ARCHITECTURE_AUDIT_AND_PLAN_2026-07-05.md.

Layering: api-layer (owns DB + integrations). The engine still just receives
prompt_overrides / guardrail_engine / a filtered ToolRegistry / approval_mode —
no engine change for persona.
"""
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class AppliedPersona:
    """Everything a surface needs to build a persona-governed AgentLoop."""
    persona: Optional[Dict[str, Any]]
    prompt_overrides: Dict[str, Any]
    guardrail_engine: Any
    tool_registry: Any                 # filtered + skills-reconciled
    approval_mode: str
    dynamic_picker: Any
    scope_meta: Dict[str, Any]


def effective_tool_names(persona_allowed, *, learning_on, skill_tools=()):
    """The tool names a persona actually gets.

    **Skills RIDE ALONG with capability; they do not manufacture it.** The
    whitelist is a CEILING, and an empty ceiling is zero — not three.

    This used to append the skills tools unconditionally, so a persona that had
    declared no tools was handed `skills_list`, `skill_view` and `skill_manage`
    anyway — one line after this module had logged that it would have none.

    That is not cosmetic. PrepCrest's authoring persona (V042, `allowed_tools`
    `'[]'`, *"NO TOOLS. Narrower than the tutor's on purpose"*) is a payload
    contract: it answers once and stops. Given three tools it had something to
    call, and `ag_system.transcript_logs` for one turn of batch 9 reads:

        TOOL_CALLS         11
        TOOL_SKILL_MANAGE   9      'author-jee-integral-calculus-questions'
        TOOL_SKILL_VIEW     2       patched ... v3, v4, v5, v6, v7, v8

    The question-author spent thirty minutes writing a skill about how to write
    questions and never wrote a question — 21 LLM calls on a turn that wanted
    one, ended by the caller's deadline with nothing banked.

    Neither loop guard could stop it: `_loop_guard_tripped` matches IDENTICAL
    tool inputs and every patch differed, and the consecutive-failure reflection
    needs failures where every patch succeeded. Nothing in the engine bounds a
    tool that keeps working, so the only real bound is not handing it over.

    Worse, a turn that calls a tool AFTER writing its answer has that answer
    cleared at the tool boundary (see `agent_streamer`), so the reply can also
    come back empty.

    A persona WITH tools keeps its skills exactly as before: procedural memory is
    about how to USE capability, so it belongs wherever capability is and nowhere
    else.
    """
    names = list(persona_allowed or [])

    if not names:
        return []

    if not learning_on:
        return names

    return names + [t for t in skill_tools if t not in names]


def resolve_persona(db, *, app_id=None, persona_id=None, embed=None):
    """The ONE resolution rule, used everywhere:
       embed persona  >  explicit persona_id  >  app default  >  None.

    A cron job carries its own persona_id (per-task assignment). If that
    persona has since been deactivated or removed, we DEGRADE to the app
    default rather than run ungoverned — deactivating a persona must never
    turn its crons naked (the FK ON DELETE SET NULL only covers hard deletes;
    delete_persona is a soft is_active=FALSE). Embed keeps a hard binding: its
    tool ceiling is enforced separately by build_embed_registry."""
    from api.repositories.persona_repo import PersonaRepository
    repo = PersonaRepository(db)
    if embed and embed.get("persona_id"):
        return repo.get_persona(embed["persona_id"])
    if persona_id:
        p = repo.get_persona(int(persona_id))
        if p:
            return p
        # assigned persona gone/inactive → fall through to the app default
    if app_id:
        return repo.get_persona_for_app(app_id)
    return None


def apply_persona(cli, db, *, base_registry, user_ctx, app_id,
                  persona_id=None, embed=None,
                  preset_approval_mode=None,
                  default_approval_mode=None) -> AppliedPersona:
    """Resolve the persona and return the wired components. `base_registry` is
    the surface's full session registry; the returned `tool_registry` is the
    persona-filtered one the AgentLoop should use."""
    from tools.registry import ToolRegistry
    from core.config import app_config

    persona = None
    try:
        persona = resolve_persona(db, app_id=app_id, persona_id=persona_id,
                                  embed=embed)
    except Exception as e:
        logger.debug("persona resolve skipped: %s", e)

    prompt_overrides: Dict[str, Any] = {}
    guardrail_engine = None
    tool_registry = base_registry

    if persona:
        prompt_overrides = {
            "identity": persona.get("identity_prompt"),
            "constraints": persona.get("constraints_prompt"),
            "communication": persona.get("communication_prompt"),
            "disable_passivity": persona.get("disable_passivity_correction", True),
        }
        # An embed integration may extend the DLP set + pin an execution policy.
        embed_execution = None
        if embed:
            ig_policy = embed.get("guardrail_policy") or {}
            embed_execution = ig_policy.get("embed_execution")
            ig_dlp = ig_policy.get("dlp_patterns") or []
            if ig_dlp:
                persona = dict(persona)
                persona["output_dlp_patterns"] = list(
                    persona.get("output_dlp_patterns") or []) + ig_dlp
        try:
            from core.guardrails import GuardrailEngine
            guardrail_engine = GuardrailEngine(
                persona, llm_client=cli.llm, embed_execution=embed_execution)
        except Exception as e:
            logger.debug("guardrail engine skipped: %s", e)

    # Dynamic-op registration onto the base registry (principal/persona-scoped).
    # Gated only on the integrations runtime — matches chat's placement so an
    # app with grants but no persona still gets its ops.
    if getattr(cli, "_integrations", None):
        try:
            cli._integrations.register_session_direct(
                base_registry, user_ctx,
                persona_id=str((persona or {}).get("persona_id") or ""),
                embed_safe_only=bool(embed))
        except Exception as e:
            logger.debug("dynamic op registration skipped: %s", e)

    # Tool whitelist.
    if embed:
        from core.embed_sandbox import build_embed_registry
        dynamic_embed_safe = None
        try:
            from core.integrations.grants import effective_allowed_tools
            dynamic_embed_safe = effective_allowed_tools(
                db, [], app_id=app_id,
                persona_id=(persona or {}).get("persona_id"),
                embed_safe_only=True)
        except Exception as e:
            logger.debug("embed grant expansion skipped: %s", e)
        tool_registry = build_embed_registry(
            base_registry, embed.get("mode", "chat"),
            (persona or {}).get("allowed_tools"),
            dynamic_embed_safe=dynamic_embed_safe)
        # Opt-in, create-only issue reporting (see core/embed_issue_intake.py).
        # Added to the scoped registry, never the full Jira toolset.
        try:
            from core.embed_issue_intake import intake_config, register_issue_intake
            intake = intake_config(embed.get("guardrail_policy"))
            if intake and getattr(cli, "connections", None) is not None:
                register_issue_intake(
                    tool_registry, cli.connections, intake,
                    app_id=app_id, integration_id=embed.get("integration_id"),
                    session_key=str(embed.get("end_user") or ""),
                    site=str(embed.get("site") or ""))
        except Exception as e:
            logger.warning("embed issue intake skipped: %s", e)
    elif persona:
        allowed = persona.get("allowed_tools") or []
        try:
            from core.integrations.grants import effective_allowed_tools
            allowed = list(effective_allowed_tools(
                db, allowed, app_id=app_id,
                persona_id=persona.get("persona_id")))
        except Exception as e:
            logger.debug("integration grant expansion skipped: %s", e)
        # THE single place the api-layer whitelist reconciles with the skills
        # subsystem. The rule itself is `effective_tool_names` — named and pure,
        # because "does an empty whitelist mean none or does it mean the
        # defaults" is a semantic decision that deserves to be stated once and
        # tested, not spelled inline where the next reader has to infer it.
        learning_on = False
        skill_tools = ()
        try:
            from api.services.skill_service import learning_enabled
            learning_on = learning_enabled()
            if learning_on:
                from tools.skills_mcp import SKILL_TOOL_NAMES
                skill_tools = SKILL_TOOL_NAMES
        except Exception:
            pass

        before = len(allowed)
        allowed = effective_tool_names(
            allowed, learning_on=learning_on, skill_tools=skill_tools)
        skills_added = len(allowed) > before

        filtered = ToolRegistry()
        for t in allowed:
            if t in base_registry._tools:
                filtered._tools[t] = base_registry._tools[t]
                filtered._callbacks[t] = base_registry._callbacks[t]
                if t in base_registry._policies:
                    filtered._policies[t] = base_registry._policies[t]
        tool_registry = filtered

        # Reported AFTER the whitelist resolves, and counted off the registry
        # that was actually built rather than off the intent.
        #
        # The old warning fired BEFORE the skills were appended and announced
        # "NO capability tools", while the session that followed logged
        # "tools: 3". Two lines, one apart, flatly contradicting each other —
        # which is how this survived in production as long as it did. A log that
        # describes what was decided instead of what was resolved is worse than
        # no log, because it is believed.
        if not filtered._tools:
            logger.info(
                "Persona '%s' (app_id=%s) resolved to NO tools — expected for a "
                "payload-contract persona, check configuration if it is not.",
                persona.get("name"), app_id)
        else:
            logger.info(
                "Persona '%s' (app_id=%s) resolved to %d tool(s)%s.",
                persona.get("name"), app_id, len(filtered._tools),
                " (skills included)" if skills_added else "")

    # Approval mode: caller preset > persona > caller default > global default.
    approval_mode = (
        preset_approval_mode
        or (persona.get("approval_mode") if persona else None)
        or default_approval_mode
        or app_config.get("agent.approval_mode", "irreversible"))

    dynamic_picker = None
    if getattr(cli, "_integrations", None):
        try:
            dynamic_picker = cli._integrations.make_picker(
                user_ctx,
                persona_id=str((persona or {}).get("persona_id") or ""),
                embed_safe_only=bool(embed))
        except Exception as e:
            logger.debug("dynamic picker unavailable: %s", e)

    return AppliedPersona(
        persona=persona,
        prompt_overrides=prompt_overrides,
        guardrail_engine=guardrail_engine,
        tool_registry=tool_registry,
        approval_mode=approval_mode,
        dynamic_picker=dynamic_picker,
        scope_meta={
            "persona_id": (persona or {}).get("persona_id"),
            "app_id": app_id,
            "integration_id": (embed or {}).get("integration_id"),
        },
    )
