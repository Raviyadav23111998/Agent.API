"""
Chat Service — SSE Streaming Engine (ChatGPT/Gemini style)
════════════════════════════════════════════════════════════
Production-grade implementation that routes chat messages through the
full AgentLoop (with all 50+ tools: Outlook, Jira, Brain, Shell, etc.)

Architecture:
    - ONE AgentLoop PER CONVERSATION (not per user) for full context isolation
    - Mirrors gateway/runner.py SessionManager pattern
    - Shared CLI instance (heavy init once: LLM, tools, memory)
    - Per-conversation: isolated conversation_history, state machine, checkpoints
    - Session TTL: 30 min inactivity → auto-expire + summary
    - DB is source of truth — agent history rebuilt from DB on session resume

SSE Event Protocol:
    message.start  → conversation created/resumed
    status         → agent state transitions (loading_context, reasoning, etc.)
    tool.start     → tool execution beginning
    tool.end       → tool result received
    message.delta  → streaming text chunk
    message.end    → final message with full content
    error          → error occurred
    [DONE]         → stream complete
"""

import json
import uuid
import logging
import asyncio
import os
import time
from typing import AsyncGenerator, Optional, Dict, List

from api.repositories.chat_repo import ChatRepository

logger = logging.getLogger(__name__)


class _ConversationSession:
    """Lightweight wrapper around an AgentLoop bound to a single conversation.

    Each conversation gets its own AgentLoop with fully isolated:
        - conversation_history
        - state machine
        - checkpoint manager
        - token budget tracking
    """

    TTL = 1800

    __slots__ = ('conversation_id', 'agent', 'last_active', 'user_id', 'tenant_id',
                 'persona_id', 'app_id', 'integration_id', 'config_version',
                 'requested_model', 'credential_ref')

    def __init__(self, conversation_id: str, agent, user_id: int, tenant_id: str = "default",
                 persona_id: int = None, app_id: int = None, integration_id: int = None,
                 config_version: int = 0):
        self.conversation_id = conversation_id
        self.agent = agent
        self.last_active = time.time()
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.persona_id = persona_id
        self.app_id = app_id
        self.integration_id = integration_id
        self.config_version = config_version
        self.requested_model = None
        self.credential_ref = ""      # llm_scope.credential_ref of the key's override, "" = none

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.last_active) > self.TTL

    def touch(self):
        self.last_active = time.time()


class _SessionPool:
    """Manages AgentLoop instances per conversation.

    Architecture mirrors gateway/runner.py SessionManager:
    - Each conversation gets its own AgentLoop with isolated context
    - Sessions share: LLM client, tool_registry, memory_manager (heavy, init once)
    - Sessions expire after 30 min inactivity → cleaned up on next access
    - Conversation history is rebuilt from DB every time a session is created
    """

    _CLI_INIT_COOLDOWN_S = 30.0

    def __init__(self):
        self._sessions: Dict[str, _ConversationSession] = {}
        self._cli = None
        self._cli_failed_at = 0.0
        self._lock = asyncio.Lock()
        self._audit_repo = None
        self._db = None

    def _ensure_cli(self):
        """Create the shared CLI instance (tool registry, LLM, memory, etc.).

        Graceful degradation with retry: if init fails (missing config, DB
        down), we record the failure and reject calls for a short cooldown,
        then allow a retry — so a transient outage self-heals instead of
        requiring a server restart.
        """
        if self._cli is not None:
            return
        if self._cli_failed_at and (time.time() - self._cli_failed_at) < self._CLI_INIT_COOLDOWN_S:
            raise RuntimeError(
                "Agent system is initializing/recovering. Retry in a few seconds."
            )
        try:
            from client.cli import AgentCLI
            workspace = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', '..')
            )
            self._cli = AgentCLI(workspace, db=self._db)
            self._cli_failed_at = 0.0
            # Attach the LLM scope service so core-side spawners (sub-agent
            # factory) can resolve profiles and meter spend without importing
            # api modules.
            from api.services.llm_scope import attach_scope
            attach_scope(self._cli, self._db)
            logger.info("SessionPool: CLI initialized (tools: %d)",
                        len(self._cli.tool_registry._tools))
        except Exception as e:
            self._cli_failed_at = time.time()
            logger.critical(
                "SessionPool: CLI initialization FAILED — %s. "
                "Chat endpoints will 503 for %ds, then retry.",
                e, int(self._CLI_INIT_COOLDOWN_S), exc_info=True,
            )
            raise RuntimeError(f"Agent system unavailable: {e}") from e

    def _create_agent(self, user_id: int, user_name: str = "",
                      user_email: str = "", app_id: int = None,
                      tool_executor=None, approval_mode: str = None,
                      user_role: str = "", embed: dict = None,
                      conversation_id: str = None,
                      requested_model: str = None,
                      page_nav: list = None,
                      persona_id: int = None,
                      llm_api_key: str = None):
        """Create a fresh AgentLoop for a conversation.

        embed (optional): {"mode": "chat"|"copilot", "persona_id": int,
        "integration_id": int} — when set, the persona is resolved by id and
        the tool registry is hard-capped to embed-safe tools (sandbox).
        
        Each user gets:
          1. A sandboxed workspace directory (/var/agent-workspaces/{tenant}/user_{id}/)
          2. A sandboxed ToolRegistry (filesystem/shell jailed to their workspace)
          3. Server tools (brain, jira, memory) shared from the global registry
        
        Args:
            app_id: Application scope from JWT — flows to UserContext → brain tools.
            tool_executor: Optional ToolExecutor override. If None, uses
                          LocalToolExecutor (default — sandboxed tools on VPS).
                          Pass RemoteToolExecutor for VS Code Local Server mode.
            approval_mode: Optional HITL override. Automation callers (agent
                          runs) pass "off" — they have no human watching, so
                          an approval gate would only hang them. None =
                          resolve from persona/config (interactive surfaces).
        """
        self._ensure_cli()

        from core.agent_loop import AgentLoop
        from core.user_context import UserContext
        from core.tenant_context import current_tenant
        from core.workspace_manager import WorkspaceManager
        from async_bus.event_bus import EventBus

        _tenant = current_tenant()

        _embed_uid = (embed or {}).get("end_user")
        user_ctx = UserContext(
            user_id=(f"embed_{_embed_uid}" if _embed_uid else f"user_{user_id}"),
            user_name=user_name or ("Visitor" if _embed_uid else f"User {user_id}"),
            platform=("embed" if embed else "api"),
            app_id=str(app_id) if app_id else None,
            role=user_role or "",
        )

        ws_manager = WorkspaceManager(tenant_id=_tenant.tenant_key)
        user_workspace = ws_manager.ensure_workspace(user_id)
        user_quota = ws_manager.get_user_quota_bytes(user_id)
        
        user_tool_registry = self._cli.create_user_tools(
            user_workspace, 
            sandboxed=True,
            max_size_bytes=user_quota,
            user_context=user_ctx,
        )

        # Persona governance — resolved and wired through the SINGLE shared
        # applicator (chat, bot and cron all use it). embed carries its own
        # persona_id + guardrail policy; a service key may PIN one (an app that
        # serves two surfaces from one knowledge scope); interactive chat
        # resolves the app default. See persona_applicator.apply_persona, which
        # owns the precedence rule — this must not re-implement it.
        from api.services.persona_applicator import apply_persona
        _ap = apply_persona(
            self._cli, self._cli.tenant_db,
            base_registry=user_tool_registry, user_ctx=user_ctx,
            app_id=app_id, persona_id=persona_id, embed=embed,
            preset_approval_mode=approval_mode)
        persona = _ap.persona
        prompt_overrides = _ap.prompt_overrides
        guardrail_engine = _ap.guardrail_engine
        user_tool_registry = _ap.tool_registry
        approval_mode = _ap.approval_mode
        dynamic_picker = _ap.dynamic_picker

        conversation_event_bus = EventBus()

        from core.approvals import ApprovalManager
        approval_manager = ApprovalManager(
            conversation_event_bus, user_id=user_id, mode=approval_mode,
        )

        _audit_repo = self._audit_repo
        _embed_audit = None
        _embed_conv_id = None
        if embed:
            from api.services.embed_audit import EmbedAuditRepo, AUDITABLE_TOOLS
            _embed_audit = EmbedAuditRepo(self._cli.tenant_db)
            _embed_conv_id = (
                conversation_id
                or f"embed_{embed.get('integration_id')}_{embed.get('end_user') or 'anon'}"
            )

        def _audit_sink(tool_name, side_effect, args_summary, approved, status):
            if _audit_repo is not None:
                _audit_repo.write_action_audit(
                    user_id, None, tool_name, side_effect, args_summary, approved, status,
                )
            if _embed_audit is not None and tool_name in AUDITABLE_TOOLS:
                _embed_audit.write_action(
                    integration_id=embed.get("integration_id"),
                    session_id=_embed_conv_id or "",
                    tool_name=tool_name,
                    target_label=(args_summary or "")[:200],
                    tool_args=args_summary,
                    status=status or "executed",
                )

        # dynamic_picker was resolved by apply_persona above.

        # Per-app/per-user model separation + Claude-style budgets: resolve
        # the model profile for this scope (agent-def > request > user > app
        # > default), bind its cached client, and inject the usage ledger +
        # budget probe. All best-effort — a missing V035 schema falls back to
        # the legacy shared client with no metering.
        llm_client = self._cli.llm
        _usage_sink = None
        _budget_check = None
        try:
            from api.services.llm_scope import attach_scope
            _scope = attach_scope(self._cli, self._db)
            _profile = _scope.resolve_profile(
                user_id=None if embed else user_id, app_id=app_id,
                requested_model=requested_model)
            # A service key's own provider credential (V058): api_key only,
            # the model is whatever was just resolved. No-op when unset.
            from api.services.llm_scope import with_credential
            _profile = with_credential(_profile, llm_api_key)
            llm_client = _scope.client_for(_profile, self._cli.llm)
            # The guardrail engine was built above, before this client
            # existed, holding the legacy shared one. Its semantic rails
            # must spend where the turn spends — see GuardrailEngine.bind_llm.
            if guardrail_engine is not None and hasattr(guardrail_engine, "bind_llm"):
                guardrail_engine.bind_llm(llm_client)
            _usage_sink = _scope.make_usage_sink(
                user_id=user_id, app_id=app_id,
                run_kind="embed" if embed else "chat",
                profile_id=(_profile or {}).get("profile_id"))
            _budget_check = _scope.make_budget_check(
                user_id=None if embed else user_id, app_id=app_id)
        except Exception as e:
            logger.debug("llm scope unavailable — legacy client (%s)", e)

        agent = AgentLoop(
            user_workspace,
            llm_client,
            user_tool_registry,
            conversation_event_bus,
            transcript_logger=self._cli.logger,
            memory_manager=self._cli.memory,
            user_context=user_ctx,
            tool_executor=tool_executor,
            prompt_overrides=prompt_overrides,
            guardrail_engine=guardrail_engine,
            approval_manager=approval_manager,
            audit_sink=_audit_sink,
            tenant_context=_tenant,
            conversation_id=conversation_id,
            dynamic_picker=dynamic_picker,
            usage_sink=_usage_sink,
            budget_check=_budget_check,
        )

        # Knowledge items → the generic section seam (renderer owns the wording).
        from core.prompt_sections import (
            render_knowledge, KNOWLEDGE_KEY, KNOWLEDGE_ORDER,
            render_skills_index, SKILLS_KEY, SKILLS_ORDER)
        agent.prompt_builder.set_section(
            KNOWLEDGE_KEY,
            render_knowledge(list(self._cli.knowledge.load_active_kis())),
            KNOWLEDGE_ORDER)

        # Procedural memory: per-session SNAPSHOT of the skills index into
        # the byte-stable prefix (bodies load on demand via skill_view).
        # No-op unless agent.skill_learning is enabled for the tenant.
        try:
            from api.services.skill_service import attach_skills
            _skills = attach_skills(self._cli, self._db)
            if _skills is not None:
                agent.prompt_builder.set_section(
                    SKILLS_KEY,
                    render_skills_index(_skills.index_for(
                        app_id, None if embed else user_id)),
                    SKILLS_ORDER)
        except Exception as e:
            logger.debug("skills index snapshot skipped: %s", e)

        # Copilot surface: inject the navigation playbook + the app's route map
        # ONLY for a page-driving copilot. The signal is the client's own
        # HANDSHAKE — it declares itself by sending a `nav` context frame
        # (page_nav is not None; [] is still a declaration). page_* tools are
        # copied into every session's registry (they aren't _LOCAL_TOOL_NAMES),
        # and VSCode/regular chat also use a RemoteToolExecutor, so neither
        # "page tools present" nor "remote executor" alone is a correct signal —
        # only the client saying "I drive a page" is. Belt-and-suspenders: the
        # page tools must actually be exposed. Surface content owned by the api
        # layer, never the core engine.
        try:
            _tools = getattr(user_tool_registry, "_tools", {})
            _is_copilot = ((embed and embed.get("mode") == "copilot")
                           or page_nav is not None)
            if _is_copilot and ("page_observe" in _tools
                                or "page_navigate" in _tools):
                from api.services.copilot_prompt import (
                    PAGE_NAV_PLAYBOOK, PLAYBOOK_KEY, PLAYBOOK_ORDER,
                    render_routes, ROUTES_KEY, ROUTES_ORDER)
                agent.prompt_builder.set_section(
                    PLAYBOOK_KEY, PAGE_NAV_PLAYBOOK, PLAYBOOK_ORDER)
                if page_nav:
                    agent.prompt_builder.set_section(
                        ROUTES_KEY, render_routes(page_nav), ROUTES_ORDER)
        except Exception as e:
            logger.debug("copilot prompt sections skipped: %s", e)

        scope_meta = {
            "persona_id": (persona or {}).get("persona_id"),
            "app_id": app_id,
            "integration_id": (embed or {}).get("integration_id"),
        }
        return agent, scope_meta

    async def get_session(self, conversation_id: str, user_id: int,
                          user_name: str = "", user_email: str = "",
                          app_id: int = None,
                          db_history: List[Dict] = None,
                          tool_executor=None,
                          approval_mode: str = None,
                          user_role: str = "",
                          embed: dict = None,
                          requested_model: str = None,
                          page_nav: list = None,
                          persona_id: int = None,
                          llm_api_key: str = None,
                          ) -> _ConversationSession:
        """Get or create an agent session for this conversation.

        If a valid (non-expired) session exists for this conversation_id,
        it is reused. Otherwise, a fresh AgentLoop is created and the
        conversation history is rebuilt from DB.
        """
        from core.tenant_context import current_tenant
        active_tenant_id = current_tenant().tenant_id

        async with self._lock:
            session = self._sessions.get(conversation_id)

            if (session and not session.is_expired
                    and session.tenant_id == active_tenant_id
                    and self._config_changed(session)):
                logger.info("SessionPool: config changed for conv=%s — rebuilding",
                            conversation_id[:8])
                self._expire_session(conversation_id)
                session = None

            # An explicit model switch rebuilds the session with the new
            # profile's client (history is replayed from DB, so no loss).
            # No model param = keep the session's current model (sticky) —
            # but an explicit pick on a default-model session MUST switch:
            # requiring the OLD value to be truthy too silently ignored the
            # first explicit pick of a conversation. To return to the
            # default profile explicitly, request it by name.
            if (session and requested_model
                    and (getattr(session, "requested_model", None) or None)
                        != requested_model):
                logger.info("SessionPool: model switch %s → %s for conv=%s",
                            getattr(session, "requested_model", None),
                            requested_model, conversation_id[:8])
                self._expire_session(conversation_id)
                session = None

            # The key's provider credential changed (set, cleared or rotated)
            # since this session's client was built: rebuild, or the old key
            # would be used until the session expired — up to TTL after a
            # rotation, which is exactly when the old key stops working.
            from api.services.llm_scope import credential_ref as _cred_ref
            _want_ref = _cred_ref(llm_api_key) if llm_api_key else ""
            if (session and not session.is_expired
                    and (getattr(session, "credential_ref", "") or "") != _want_ref):
                logger.info("SessionPool: credential changed for conv=%s — rebuilding",
                            conversation_id[:8])
                self._expire_session(conversation_id)
                session = None

            if session and not session.is_expired and session.tenant_id == active_tenant_id:
                session.touch()
                session.agent.bind_tool_executor(tool_executor)
                return session

            if session:
                self._expire_session(conversation_id)

            self._gc_expired()

            agent, scope_meta = self._create_agent(
                user_id, user_name, user_email,
                app_id=app_id,
                tool_executor=tool_executor,
                approval_mode=approval_mode,
                user_role=user_role,
                embed=embed,
                conversation_id=conversation_id,
                requested_model=requested_model,
                page_nav=page_nav,
                persona_id=persona_id,
                llm_api_key=llm_api_key)

            if db_history:
                for msg in db_history:
                    agent._append_message(msg)

            session = _ConversationSession(
                conversation_id, agent, user_id,
                tenant_id=active_tenant_id,
                persona_id=scope_meta.get("persona_id"),
                app_id=scope_meta.get("app_id"),
                integration_id=scope_meta.get("integration_id"),
                config_version=self._resolve_version(
                    active_tenant_id,
                    persona_id=scope_meta.get("persona_id"),
                    app_id=scope_meta.get("app_id"),
                    integration_id=scope_meta.get("integration_id")))
            session.requested_model = requested_model
            session.credential_ref = _want_ref
            self._sessions[conversation_id] = session

            logger.info(
                "SessionPool: Created session for conv=%s user=%d "
                "(history: %d msgs, tools: %d, executor: %s)",
                conversation_id[:8], user_id,
                len(db_history or []),
                len(agent.tool_registry._tools),
                type(tool_executor).__name__ if tool_executor else "Local",
            )
            return session

    def _resolve_version(self, tenant_key: str, *, persona_id=None,
                         app_id=None, integration_id=None) -> int:
        """Current config version for a scope (0 if unavailable). Redesign C1."""
        if self._db is None:
            return 0
        try:
            from api.services.config_resolver import config_resolver
            return config_resolver.current_version(
                self._db, tenant_key, app_id=app_id,
                integration_id=integration_id, persona_id=persona_id)
        except Exception as e:
            logger.debug("config version resolve failed: %s", e)
            return 0

    def _config_changed(self, session) -> bool:
        """True if the session's config scope was edited since it was built."""
        if session.config_version == 0:
            return False
        current = self._resolve_version(
            session.tenant_id, persona_id=session.persona_id,
            app_id=session.app_id, integration_id=session.integration_id)
        return current > session.config_version

    def _expire_session(self, conversation_id: str):
        """Clean up an expired session."""
        session = self._sessions.pop(conversation_id, None)
        if session:
            logger.info("SessionPool: Expired session for conv=%s",
                        conversation_id[:8])

    def _gc_expired(self):
        """Remove all expired sessions (lightweight sweep)."""
        expired = [
            cid for cid, s in self._sessions.items()
            if s.is_expired
        ]
        for cid in expired:
            self._expire_session(cid)

    def invalidate(self, conversation_id: str):
        """Force-invalidate a session (e.g., on conversation delete)."""
        self._sessions.pop(conversation_id, None)

    def invalidate_scope(self, persona_id: int = None, app_id: int = None,
                         integration_id: int = None) -> int:
        """Drop every cached session whose config came from the given scope.

        Called when an admin edits a persona / application / integration so the
        next message rebuilds the AgentLoop with fresh prompts, tools, and
        guardrails — no server restart, no waiting for the 30-min TTL.

        A flush-all (all args None) is intentional: used by the "*" pub/sub
        scope to clear everything across workers.

        Returns the number of sessions dropped.
        """
        flush_all = persona_id is None and app_id is None and integration_id is None
        victims = []
        for cid, s in self._sessions.items():
            if flush_all:
                victims.append(cid)
            elif persona_id is not None and s.persona_id == persona_id:
                victims.append(cid)
            elif app_id is not None and s.app_id == app_id:
                victims.append(cid)
            elif integration_id is not None and s.integration_id == integration_id:
                victims.append(cid)
        for cid in victims:
            self._sessions.pop(cid, None)
        if victims:
            logger.info(
                "SessionPool: invalidated %d session(s) (persona=%s app=%s integration=%s)",
                len(victims), persona_id, app_id, integration_id,
            )
        return len(victims)


_session_pool = _SessionPool()


def invalidate_config(persona_id: int = None, app_id: int = None,
                      integration_id: int = None):
    """Invalidate sessions locally and broadcast to all other workers."""
    try:
        from api.services.config_resolver import config_resolver
        config_resolver.bust()
    except Exception:
        pass
    _session_pool.invalidate_scope(
        persona_id=persona_id, app_id=app_id, integration_id=integration_id)
    try:
        from core.redis_client import publish_session_invalidate
        if persona_id is not None:
            publish_session_invalidate(f"persona:{persona_id}")
        if app_id is not None:
            publish_session_invalidate(f"app:{app_id}")
        if integration_id is not None:
            publish_session_invalidate(f"integration:{integration_id}")
    except Exception as e:
        logger.warning("config invalidation broadcast failed: %s", e)


def _refresh_integrations_local():
    """Re-register external tools on THIS worker's CLI, then flush sessions.

    Used when a credential or infra-connection config changes so newly-connected
    providers (Jira/M365/SMTP…) and changed Neo4j/ES URLs apply without a restart.
    """
    cli = _session_pool._cli
    if cli is not None and hasattr(cli, "refresh_integrations"):
        try:
            cli.refresh_integrations()
        except Exception as e:
            logger.warning("local integration refresh failed: %s", e)
    _session_pool.invalidate_scope()


def _apply_invalidation_signal(scope: str):
    """Subscriber callback: apply a pub/sub invalidation scope to the local pool.

    Scope tokens: "persona:<id>", "app:<id>", "integration:<id>",
    "integrations" (credential/infra change → refresh tools), "*".
    """
    try:
        from api.services.config_resolver import config_resolver
        config_resolver.bust()
    except Exception:
        pass
    scope = (scope or "").strip()
    if not scope or scope == "*":
        _session_pool.invalidate_scope()
        return
    if scope == "integrations":
        _refresh_integrations_local()
        return
    try:
        kind, _, raw = scope.partition(":")
        sid = int(raw)
    except (ValueError, AttributeError):
        return
    if kind == "persona":
        _session_pool.invalidate_scope(persona_id=sid)
    elif kind == "app":
        _session_pool.invalidate_scope(app_id=sid)
    elif kind == "integration":
        _session_pool.invalidate_scope(integration_id=sid)


def refresh_integrations_global():
    """Hot-apply credential / infra-config changes across ALL workers.

    Refreshes this worker's tool registry immediately and broadcasts an
    "integrations" signal so every other worker re-registers too. Call after a
    credential is stored / updated / deleted / bound, or an infra connection
    setting (Neo4j/ES) changes.
    """
    _refresh_integrations_local()
    try:
        from core.redis_client import publish_session_invalidate
        publish_session_invalidate("integrations")
    except Exception as e:
        logger.warning("integration refresh broadcast failed: %s", e)


def start_session_invalidation_subscriber():
    """Wire the Redis subscriber so remote invalidations clear the local pool.

    Safe no-op when Redis is unconfigured — local invalidation still works,
    other workers just fall back to TTL expiry. Call once at app startup.
    """
    try:
        from core.redis_client import subscribe_session_invalidate
        subscribe_session_invalidate(_apply_invalidation_signal)
    except Exception as e:
        logger.info("session invalidation subscriber skipped (%s)", e)


class ChatService:
    """Streaming chat service — routes through the full AgentLoop.

    Responsibilities:
        - Conversation lifecycle (create, load, delete)
        - Message persistence (user + assistant messages to DB)
        - SSE streaming orchestration
        - Agent session management (via _session_pool)
    """

    def __init__(self, chat_repo: ChatRepository, db=None):
        self._repo = chat_repo
        self._db = db
        _session_pool._audit_repo = chat_repo
        _session_pool._db = db
        # File/attachment orchestration (Part 1: user → model). Built off the
        # same tenant-scoped db so it resolves per-request like the chat repo.
        self._files = None
        if db is not None:
            from api.repositories.file_repo import FileRepository
            from api.services.file_service import FileService
            self._files = FileService(FileRepository(db), db)


    @staticmethod
    def _sse(event: str, **kwargs) -> str:
        """Build a single SSE data line."""
        payload = {"event": event, **kwargs}
        return f"data: {json.dumps(payload)}\n\n"

    @staticmethod
    def _sse_done() -> str:
        return "data: [DONE]\n\n"


    def get_or_create_conversation(self, conversation_id: Optional[str],
                                    user_id: int, agent_id: int = None,
                                    model: str = '', source: str = 'web') -> Dict:
        """Get existing conversation (owned by user) or create new one."""
        if conversation_id:
            conv = self._repo.get_conversation(conversation_id, user_id=user_id)
            if conv:
                return conv

        conv_id = conversation_id or str(uuid.uuid4())
        return self._repo.create_conversation(
            conversation_id=conv_id,
            user_id=user_id,
            agent_id=agent_id,
            model=model,
            source=source,
        )

    def list_conversations(self, user_id: int, source: str = None) -> List[Dict]:
        return self._repo.list_conversations(user_id, source=source)

    def get_conversation_detail(self, conversation_id: str,
                                 user_id: int = None) -> Optional[Dict]:
        """Get conversation + messages — scoped to user_id."""
        conv = self._repo.get_conversation(conversation_id, user_id=user_id)
        if not conv:
            return None
        messages = self._repo.get_messages(conversation_id)
        # Attach file metadata so reloaded conversations render their images/docs
        # (bytes fetched lazily by the web via GET /v1/media/{fileId}). ONE query
        # for the whole conversation — no N+1.
        if self._files is not None:
            try:
                ids = [m["message_id"] for m in messages if m.get("message_id")]
                by_msg = self._files.list_for_messages(ids)
                for m in messages:
                    atts = by_msg.get(m.get("message_id"))
                    if atts:
                        m["attachments"] = atts
            except Exception:
                logger.warning("attachment hydrate on detail failed", exc_info=True)
        conv["messages"] = messages
        return conv

    def delete_conversation(self, conversation_id: str, user_id: int = None):
        """Delete conversation — scoped to user_id."""
        _session_pool.invalidate(conversation_id)
        self._repo.delete_conversation(conversation_id, user_id=user_id)


    def _load_history_for_agent(self, conversation_id: str) -> List[Dict]:
        """Load recent messages as OpenAI-format conversation history.

        Transforms DB rows into the format expected by AgentLoop._append_message():
            {"role": "user|assistant|tool", "content": "...", "tool_calls": [...]}

        Does NOT include the current (latest) user message, because
        AgentLoop._process_input() will append it internally.
        """
        rows = self._repo.get_recent_messages(conversation_id, limit=30)

        if rows and rows[-1].get("role") == "user":
            rows = rows[:-1]

        history = []
        for r in rows:
            msg = {"role": r["role"], "content": r.get("content", "")}
            if r.get("tool_calls"):
                tc = r["tool_calls"]
                if isinstance(tc, str):
                    tc = json.loads(tc)
                if tc and tc != []:
                    msg["tool_calls"] = tc
            if r.get("tool_call_id"):
                msg["tool_call_id"] = r["tool_call_id"]
            # Replay multimodal attachments on historical user turns so the model
            # keeps seeing images/docs from earlier in the conversation.
            if (r.get("role") == "user" and self._files is not None
                    and r.get("message_id")):
                try:
                    atts = self._files.hydrate_for_message(r["message_id"])
                    if atts:
                        msg["_attachments"] = atts
                except Exception:
                    pass
            history.append(msg)
        return history

    def _effective_model(self, user_id, app_id, requested_model):
        """Resolve the model a turn ACTUALLY uses (agent-def > request > user >
        app profile) so capability checks match reality — not the raw config
        default (which on a profile-driven tenant is a different, possibly
        text-only, model)."""
        from core.config import app_config
        model, provider = requested_model, None
        try:
            from api.services.llm_scope import get_scope_service
            prof = get_scope_service(self._db).resolve_profile(
                user_id=user_id, app_id=app_id, requested_model=requested_model)
            if prof:
                model = prof.get("model") or model
                provider = prof.get("provider")
        except Exception:
            pass
        return (model or app_config.get("llm.model"),
                provider or app_config.get("llm.provider"))

    def resolve_capabilities(self, user_id=None, app_id=None,
                             requested_model=None) -> dict:
        """Capability matrix for the effective model — used by the /v1/capabilities
        endpoint so the composer warns against the real model."""
        from core.model_capabilities import capabilities_for
        model, provider = self._effective_model(user_id, app_id, requested_model)
        caps = capabilities_for(model, provider)
        # Part 2 — image generation is available if the model does it natively OR
        # a provider tool is configured (the tool is exposed to the agent).
        try:
            from core.media_providers import image_generation_available
            if image_generation_available():
                caps["output"]["image"] = True
        except Exception:
            pass
        return {"model": model, "provider": provider, "capabilities": caps}

    def _filter_by_capability(self, attachments: list, user_id, app_id,
                              requested_model: str):
        """Keep only attachment kinds the EFFECTIVE model accepts; return
        (kept, warnings). Server-side twin of the composer's warning so we never
        send e.g. an image to a text-only model (which would 400)."""
        if not attachments:
            return attachments, []
        try:
            from core.model_capabilities import capabilities_for
            model, provider = self._effective_model(user_id, app_id, requested_model)
            caps = capabilities_for(model, provider)["input"]
        except Exception:
            return attachments, []
        keymap = {"image": "image", "document": "pdf",
                  "audio": "audio", "video": "video"}
        kept, dropped = [], set()
        for a in attachments:
            if caps.get(keymap.get(a.get("kind"), a.get("kind")), False):
                kept.append(a)
            else:
                dropped.add(a.get("kind"))
        warnings = []
        if dropped:
            names = ", ".join(sorted(dropped))
            warnings.append(
                f"The selected model can't read {names} attachment(s), so they "
                f"were not sent to it. Choose a model that supports {names}, or "
                f"remove them.")
        return kept, warnings


    def _auto_title(self, conversation_id: str, message: str):
        """Set conversation title from first user message (if untitled)."""
        conv = self._repo.get_conversation(conversation_id)
        if conv and not conv.get("title"):
            title = message[:80].strip()
            if len(message) > 80:
                title += "..."
            self._repo.update_conversation_title(conversation_id, title)


    async def stream_chat(
        self,
        conversation_id: str,
        user_message: str,
        user_id: int,
        system_prompt: str = None,
        model: str = None,
        user_name: str = "",
        user_email: str = "",
        app_id: int = None,
        tool_executor=None,
        user_role: str = "",
        page_nav: list = None,
        attachment_ids: list = None,
        persona_id: int = None,
        llm_api_key: str = None,
    ) -> AsyncGenerator[str, None]:
        """Claim-guarded wrapper around the streaming body.

        Guarantees the multi-worker claim is RELEASED on every exit path —
        including client disconnect (GeneratorExit), which the inner body's
        except blocks cannot see.
        """
        if not self._repo.try_claim_conversation(conversation_id):
            yield self._sse("error", message=(
                "This conversation is already processing another message. "
                "Wait for it to finish and try again."
            ))
            yield self._sse_done()
            return
        try:
            async for event in self._stream_chat_body(
                conversation_id=conversation_id,
                user_message=user_message,
                user_id=user_id,
                system_prompt=system_prompt,
                model=model,
                user_name=user_name,
                user_email=user_email,
                app_id=app_id,
                tool_executor=tool_executor,
                user_role=user_role,
                page_nav=page_nav,
                attachment_ids=attachment_ids,
                persona_id=persona_id,
                llm_api_key=llm_api_key,
            ):
                yield event
        finally:
            self._repo.release_conversation_claim(conversation_id)

    async def _stream_chat_body(
        self,
        conversation_id: str,
        user_message: str,
        user_id: int,
        system_prompt: str = None,
        model: str = None,
        user_name: str = "",
        user_email: str = "",
        app_id: int = None,
        tool_executor=None,
        user_role: str = "",
        page_nav: list = None,
        attachment_ids: list = None,
        persona_id: int = None,
        llm_api_key: str = None,
    ) -> AsyncGenerator[str, None]:
        """Core streaming method — yields SSE events like ChatGPT.

        Flow:
        1. Emit message.start
        2. Persist user message to DB
        3. Load conversation history from DB
        4. Get or create agent session (per-conversation isolation)
        5. Route user_message through AgentLoop._process_input()
        6. Capture response via EventBus subscription
        7. Emit as SSE deltas → message.end → [DONE]
        8. Persist assistant response to DB
        
        Args:
            tool_executor: Optional ToolExecutor for remote tool execution.
                          Pass RemoteToolExecutor for VS Code Local Server mode.
                          None = LocalToolExecutor (default, all tools on VPS).
        """

        # Pre-turn budget gate (Claude-style): a spent limit refuses the turn
        # up front with the reset time — before any message is persisted or
        # any model is invoked.
        try:
            from api.services.llm_scope import get_scope_service
            _budget_msg = get_scope_service(self._db).check_budgets(
                user_id=user_id, app_id=app_id)
        except Exception:
            _budget_msg = None
        if _budget_msg:
            yield self._sse("error", message=_budget_msg, code="budget_exceeded")
            yield self._sse_done()
            return

        yield self._sse("message.start", conversationId=conversation_id)

        _user_row = self._repo.add_message(conversation_id, "user", user_message)
        self._repo.increment_message_count(conversation_id)
        # An image-only turn has blank text; give the conversation a sane title.
        self._auto_title(conversation_id,
                         user_message or ("Attachment" if attachment_ids else ""))

        # Part 1 — bind uploaded attachments to this user message, hydrate them
        # as base64 for the model, and WARN (never silently drop) on any type the
        # selected model can't accept.
        turn_attachments = []
        _message_id = (_user_row or {}).get("message_id")
        if attachment_ids and self._files is not None and _message_id:
            try:
                self._files.assign_to_message(attachment_ids, _message_id, user_id)
                turn_attachments = self._files.hydrate_for_message(_message_id)
                turn_attachments, _warnings = self._filter_by_capability(
                    turn_attachments, user_id, app_id, model)
                for _w in _warnings:
                    yield self._sse("warning", message=_w)
            except Exception:
                logger.warning("attachment binding failed", exc_info=True)
                turn_attachments = []

        yield self._sse("status", state="loading_context")
        db_history = self._load_history_for_agent(conversation_id)

        try:
            session = await _session_pool.get_session(
                conversation_id=conversation_id,
                user_id=user_id,
                user_name=user_name,
                user_email=user_email,
                app_id=app_id,
                db_history=db_history,
                tool_executor=tool_executor,
                user_role=user_role,
                requested_model=model,
                page_nav=page_nav,
                # The pin, finally reaching the applicator. Threading it as far
                # as stream_chat and stopping one call short of here is what
                # made every service turn a 200 with an empty body.
                persona_id=persona_id,
                llm_api_key=llm_api_key,
            )
            agent = session.agent

            yield self._sse("status", state="reasoning")

            # /learn <source> — standards-guided skill authoring executed by
            # the live agent (the stored message stays the user's original).
            agent_input = user_message
            _lm = user_message.strip()
            if _lm.lower().startswith("/learn"):
                try:
                    from api.services.skill_service import learning_enabled
                    from api.services.learning_service import build_learn_prompt
                    if learning_enabled():
                        agent_input = build_learn_prompt(_lm[6:])
                except Exception:
                    pass

            from api.services.agent_streamer import stream_agent_turn, final_usage_fields
            state = {"final_text": ""}
            async for frame in stream_agent_turn(
                agent, agent_input, self._sse, state,
                timeout_s=3600, ping_every=10, log_ctx=conversation_id[:8],
                attachments=turn_attachments):
                yield frame
            final_text = state["final_text"]

            # Learning loop (P3): fire-and-forget background review when the
            # turn signaled a lesson (correction / remember / long task /
            # skill in play). Flag-gated, daily-capped, metered as
            # run_kind='review'. Never affects the finished turn.
            try:
                from api.services.learning_service import maybe_review
                # The shared CLI lives on the session pool, not ChatService.
                maybe_review(agent=agent, cli=_session_pool._cli, db=self._db,
                             conversation_id=conversation_id,
                             user_id=user_id, app_id=app_id)
            except Exception:
                logger.warning("learning hook failed", exc_info=True)

            token_count = len(final_text.split()) if final_text else 0
            _asst_row = self._repo.add_message(
                conversation_id, "assistant", final_text,
                token_count=token_count,
            )
            # Part 2 — bind any model-generated media to the assistant message so
            # it persists and renders on reload (it already streamed live).
            _artifacts = state.get("artifacts") or []
            if _artifacts and self._files is not None:
                _amid = (_asst_row or {}).get("message_id")
                if _amid:
                    try:
                        self._files.bind_generated(_artifacts, _amid)
                    except Exception:
                        logger.warning("artifact binding failed", exc_info=True)
            self._repo.increment_message_count(conversation_id)

            yield self._sse(
                "message.end",
                content=final_text,
                conversationId=conversation_id,
                tokenCount=token_count,
                **final_usage_fields(agent),
            )

        except Exception as e:
            logger.error("Chat stream error (conv=%s): %s",
                         conversation_id[:8], e, exc_info=True)
            yield self._sse("error", message=str(e))
            _session_pool.invalidate(conversation_id)

        yield self._sse_done()


    async def chat_sync(
        self,
        conversation_id: str,
        user_message: str,
        user_id: int,
        system_prompt: str = None,
        model: str = None,
        user_role: str = "",
    ) -> Dict:
        """Non-streaming version — returns full response."""
        full_response = []
        async for event_str in self.stream_chat(
            conversation_id, user_message, user_id, system_prompt, model,
            user_role=user_role,
        ):
            for line in event_str.strip().split("\n"):
                line = line.strip()
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if raw == "[DONE]":
                    break
                try:
                    data = json.loads(raw)
                    if data.get("event") == "message.delta" and data.get("content"):
                        full_response.append(data["content"])
                except (json.JSONDecodeError, KeyError):
                    pass

        return {
            "conversationId": conversation_id,
            "message": "".join(full_response),
        }
