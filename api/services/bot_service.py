"""
Bot Service — Chatbot with FULL Agentic AI power.
═══════════════════════════════════════════════════════════
Routes chatbot messages through the complete AgentLoop — same engine
that powers the VS Code extension and Web UI. The bot gets ALL 50+ tools
(Brain search, Jira, Outlook, Shell, etc.), full memory, and the
knowledge-grounded system prompt.

Architecture:
    1. Validate API token → get bot config
    2. Match URL rules for the current page
    3. Search linked knowledge via FTS (full Brain power)
    4. Build enhanced system prompt: base + rules + knowledge
    5. Route through AgentLoop (NOT a direct LLM call)
    6. Stream response via EventBus → SSE events
    7. Persist messages to ag_bot tables

Memory Isolation:
    - Anonymous visitors (no userId): memory_manager=None → NO memory stored
    - Logged-in users (userId from site's JWT): user_id=f"bot_{bot_id}_{user_id}"
      → isolated memory per user per bot

The bot is NOT a dumbed-down FAQ bot — it's a FULL AI agent
with knowledge grounding and URL-aware context injection.
"""

import json
import logging
import asyncio
import time
from typing import AsyncGenerator, Optional, Dict, List
from urllib.parse import urlparse

from api.repositories.bot_repo import BotRepository
from api.repositories.persona_repo import PersonaRepository

logger = logging.getLogger(__name__)

BOT_RESPONSE_TIMEOUT = 60


class _BotSession:
    """Lightweight wrapper around an AgentLoop for one bot conversation."""
    TTL = 1800

    __slots__ = ('conversation_id', 'agent', 'last_active', 'bot_id', 'tenant_id')

    def __init__(self, conversation_id: str, agent, bot_id: int, tenant_id: str = "default"):
        self.conversation_id = conversation_id
        self.agent = agent
        self.last_active = time.time()
        self.bot_id = bot_id
        self.tenant_id = tenant_id

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.last_active) > self.TTL

    def touch(self):
        self.last_active = time.time()


class _BotSessionPool:
    """Manages AgentLoop instances per bot conversation.

    Architecture mirrors ChatService's _SessionPool:
    - Each bot conversation gets its own AgentLoop with full tools
    - Sessions share: LLM client, tool_registry (heavy, init once)
    - Sessions expire after 30 min → cleaned up on next access
    
    Memory Isolation:
    - Anonymous visitors: memory_manager=None (no memory capture)
    - Logged-in users: memory scoped to bot_{bot_id}_{user_id}
    """

    _CLI_INIT_COOLDOWN_S = 30.0

    def __init__(self):
        self._sessions: Dict[str, _BotSession] = {}
        self._cli = None
        self._cli_failed_at = 0.0
        self._lock = asyncio.Lock()
        self._db = None

    def _ensure_cli(self):
        """Create the shared CLI instance (tool registry, LLM, memory, etc.)."""
        if self._cli is not None:
            return
        if self._cli_failed_at and (time.time() - self._cli_failed_at) < self._CLI_INIT_COOLDOWN_S:
            raise RuntimeError(
                "Agent system is initializing/recovering. Retry in a few seconds."
            )
        try:
            import os
            from client.cli import AgentCLI
            workspace = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', '..')
            )
            self._cli = AgentCLI(workspace, db=self._db)
            self._cli_failed_at = 0.0
            logger.info("BotSessionPool: CLI initialized (tools: %d)",
                        len(self._cli.tool_registry._tools))
        except Exception as e:
            self._cli_failed_at = time.time()
            logger.critical(
                "BotSessionPool: CLI init FAILED — %s. "
                "Bot chat will 503 for %ds, then retry.",
                e, int(self._CLI_INIT_COOLDOWN_S), exc_info=True)
            raise RuntimeError(f"Agent system unavailable: {e}") from e

    def _create_agent(self, bot_id: int, bot_name: str = "Bot",
                      user_id: str = None, app_id: int = None,
                      persona: dict = None, conversation_id: str = None):
        """Create a fresh AgentLoop for a bot conversation.
        
        Security model:
        - user_id=None → anonymous visitor → sandboxed to bot workspace, no memory
        - user_id="abc123" → logged-in user → sandboxed to user workspace, memory scoped
        - app_id flows to UserContext → tools use it for credential resolution
        - persona → prompt overrides + deterministic tool whitelist + guardrails
        """
        self._ensure_cli()

        from core.agent_loop import AgentLoop
        from core.user_context import UserContext
        from core.tenant_context import current_tenant
        from core.workspace_manager import WorkspaceManager
        from core.tool_executor import LocalToolExecutor
        from core.guardrails import GuardrailEngine
        from async_bus.event_bus import EventBus

        _tenant = current_tenant()
        is_authenticated = user_id is not None

        user_ctx = UserContext(
            user_id=f"bot_{bot_id}_{user_id}" if is_authenticated else "bot_anonymous",
            user_name=f"User {user_id}" if is_authenticated else f"{bot_name} Visitor",
            platform="chatbot",
            app_id=str(app_id) if app_id else None,
        )

        ws_manager = WorkspaceManager(tenant_id=_tenant.tenant_key)
        if is_authenticated:
            user_workspace = ws_manager.ensure_workspace(int(user_id) if user_id.isdigit() else 0)
        else:
            user_workspace = ws_manager.ensure_workspace(0)

        allowed_tools = None
        if persona and persona.get("allowed_tools") is not None:
            allowed_tools = persona["allowed_tools"]
            if isinstance(allowed_tools, str):
                import json as _json
                allowed_tools = _json.loads(allowed_tools)

        user_tool_registry = self._cli.create_user_tools(
            user_workspace, sandboxed=True, user_context=user_ctx,
            allowed_tools=allowed_tools,
        )

        if getattr(self._cli, "_integrations", None):
            try:
                for _n in [n for n, s in list(user_tool_registry._tools.items())
                           if isinstance(s, dict) and s.get("json_schema")]:
                    user_tool_registry._tools.pop(_n, None)
                    user_tool_registry._callbacks.pop(_n, None)
                    user_tool_registry._policies.pop(_n, None)
                self._cli._integrations.register_session_direct(
                    user_tool_registry, user_ctx,
                    persona_id=str((persona or {}).get("persona_id") or ""),
                    embed_safe_only=True)
            except Exception as e:
                logger.debug("bot dynamic op registration skipped: %s", e)

        guardrail_engine = None
        if persona:
            guardrail_engine = GuardrailEngine(persona, llm_client=self._cli.llm)

        conversation_event_bus = EventBus()

        from core.approvals import ApprovalManager
        from core.config import app_config
        approval_mode = (
            (persona.get("approval_mode") if persona else None)
            or app_config.get("bot.approval_mode", "irreversible")
        )
        approval_manager = ApprovalManager(
            conversation_event_bus, user_id=None, mode=approval_mode,
        )

        tool_executor = LocalToolExecutor(
            user_tool_registry, guardrail_engine=guardrail_engine,
            approval_manager=approval_manager,
        )

        prompt_overrides = {}
        if persona:
            if persona.get("identity_prompt"):
                prompt_overrides["identity"] = persona["identity_prompt"]
            if persona.get("constraints_prompt"):
                prompt_overrides["constraints"] = persona["constraints_prompt"]
            if persona.get("communication_prompt"):
                prompt_overrides["communication"] = persona["communication_prompt"]
            if persona.get("disable_passivity_correction"):
                prompt_overrides["disable_passivity"] = True

        dynamic_picker = None
        if getattr(self._cli, "_integrations", None):
            try:
                dynamic_picker = self._cli._integrations.make_picker(
                    user_ctx, persona_id=str((persona or {}).get("persona_id") or ""),
                    embed_safe_only=True)
            except Exception as e:
                logger.debug("bot dynamic picker unavailable: %s", e)

        # Per-app model profile + usage ledger + budgets. Bots resolve by
        # APP scope only: `user_id` here is the EMBEDDING SITE's user id
        # (from the site's own JWT), not a platform ag_auth user — a site's
        # user "123" must never inherit platform user 123's model profile or
        # burn their budget.
        llm_client = self._cli.llm
        _usage_sink = None
        _budget_check = None
        try:
            from api.services.llm_scope import attach_scope
            _scope = attach_scope(self._cli)
            from api.services.skill_service import attach_skills
            attach_skills(self._cli)
            _profile = _scope.resolve_profile(app_id=app_id)
            llm_client = _scope.client_for(_profile, self._cli.llm)
            _usage_sink = _scope.make_usage_sink(
                app_id=app_id, run_kind="bot",
                profile_id=(_profile or {}).get("profile_id"))
            _budget_check = _scope.make_budget_check(app_id=app_id)
        except Exception as e:
            logger.debug("bot llm scope unavailable — legacy client (%s)", e)

        agent = AgentLoop(
            user_workspace,
            llm_client,
            user_tool_registry,
            conversation_event_bus,
            transcript_logger=self._cli.logger,
            memory_manager=self._cli.memory if is_authenticated else None,
            user_context=user_ctx,
            tool_executor=tool_executor,
            prompt_overrides=prompt_overrides if prompt_overrides else None,
            guardrail_engine=guardrail_engine,
            approval_manager=approval_manager,
            tenant_context=_tenant,
            conversation_id=conversation_id,
            dynamic_picker=dynamic_picker,
            usage_sink=_usage_sink,
            budget_check=_budget_check,
        )


        if hasattr(user_tool_registry, '_brain_mcp_instance'):
            user_tool_registry._brain_mcp_instance._resolve_chat = lambda: agent._messages

        auth_label = f"user={user_id}" if is_authenticated else "anonymous (no memory)"
        persona_label = persona["name"] if persona else "none (file-based)"
        guardrail_label = repr(guardrail_engine) if guardrail_engine else "none"
        logger.info("BotSessionPool: Agent created — %s (sandbox: %s, persona: %s, guardrails: %s, tools: %d)",
                    auth_label, user_workspace, persona_label, guardrail_label,
                    len(user_tool_registry._tools))

        return agent

    async def get_session(self, conversation_id: str, bot_id: int,
                          bot_name: str = "Bot",
                          user_id: str = None,
                          app_id: int = None,
                          db_history: List[Dict] = None,
                          persona: dict = None) -> _BotSession:
        """Get or create an agent session for this bot conversation."""
        from core.tenant_context import current_tenant
        active_tenant_id = current_tenant().tenant_id

        async with self._lock:
            session = self._sessions.get(conversation_id)

            if session and not session.is_expired and session.tenant_id == active_tenant_id:
                session.touch()
                return session

            if session:
                self._sessions.pop(conversation_id, None)

            expired = [cid for cid, s in self._sessions.items() if s.is_expired]
            for cid in expired:
                self._sessions.pop(cid, None)

            agent = self._create_agent(bot_id, bot_name, user_id, app_id,
                                       persona=persona,
                                       conversation_id=conversation_id)

            if db_history:
                for msg in db_history:
                    agent._append_message(msg)

            session = _BotSession(conversation_id, agent, bot_id,
                                  tenant_id=active_tenant_id)
            self._sessions[conversation_id] = session

            logger.info(
                "BotSessionPool: Created session for conv=%s bot=%s "
                "(history: %d msgs, tools: %d, auth=%s, persona=%s)",
                conversation_id[:8], bot_name,
                len(db_history or []),
                len(agent.tool_registry._tools),
                "yes" if user_id else "anonymous",
                persona["name"] if persona else "none",
            )
            return session

    def invalidate(self, conversation_id: str):
        self._sessions.pop(conversation_id, None)

    async def invalidate_bot(self, bot_id: int):
        """Invalidate all active sessions for a specific bot (e.g. on config update)."""
        async with self._lock:
            expired = [cid for cid, s in self._sessions.items() if s.bot_id == bot_id]
            for cid in expired:
                self._sessions.pop(cid, None)
                logger.info("BotSessionPool: Invalidated session %s for updated bot %s", cid, bot_id)


_bot_session_pool = _BotSessionPool()


class BotRateLimiter:
    """Simple in-memory sliding window rate limiter for bot endpoints.
    
    Tracks requests per key (IP + bot_token combination).
    Rejects with 429 if limit exceeded within the window.
    
    Design:
    - Thread-safe via asyncio.Lock
    - Auto-prunes expired entries on each check
    - No external dependencies (Redis etc.)
    """

    def __init__(self, max_requests: int = 30, window_seconds: int = 3600):
        """
        Args:
            max_requests: Max requests per key within the window (default: 30/hour)
            window_seconds: Sliding window in seconds (default: 3600 = 1 hour)
        """
        self._max_requests = max_requests
        self._window = window_seconds
        self._requests: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> tuple:
        """Check if a request is allowed.
        
        Returns:
            (allowed: bool, remaining: int, reset_seconds: int)
        """
        async with self._lock:
            now = time.time()
            cutoff = now - self._window

            timestamps = self._requests.get(key, [])

            timestamps = [t for t in timestamps if t > cutoff]

            remaining = self._max_requests - len(timestamps)

            if remaining <= 0:
                reset_at = int(timestamps[0] + self._window - now)
                self._requests[key] = timestamps
                return (False, 0, max(reset_at, 1))

            timestamps.append(now)
            self._requests[key] = timestamps
            return (True, remaining - 1, self._window)

    async def cleanup(self):
        """Prune all expired entries. Call periodically to prevent memory growth."""
        async with self._lock:
            now = time.time()
            cutoff = now - self._window
            expired_keys = []
            for key, timestamps in self._requests.items():
                active = [t for t in timestamps if t > cutoff]
                if not active:
                    expired_keys.append(key)
                else:
                    self._requests[key] = active
            for key in expired_keys:
                del self._requests[key]


bot_rate_limiter = BotRateLimiter(max_requests=30, window_seconds=3600)


class BotService:
    """Streaming chatbot service powered by the FULL AgentLoop.

    NOT a simple LLM wrapper — this routes through the complete
    agent pipeline with persona-controlled tools, Brain, memory, and
    knowledge-grounded system prompt injection.
    """

    def __init__(self, bot_repo: BotRepository, persona_repo: PersonaRepository = None,
                 db=None):
        self._repo = bot_repo
        self._persona_repo = persona_repo
        _bot_session_pool._db = db


    @staticmethod
    def _sse(event: str, **kwargs) -> str:
        payload = {"event": event, **kwargs}
        return f"data: {json.dumps(payload)}\n\n"

    @staticmethod
    def _sse_done() -> str:
        return "data: [DONE]\n\n"


    def get_bot_config(self, api_token: str) -> Optional[Dict]:
        """Get public bot config for the widget."""
        bot = self._repo.get_bot_by_token(api_token)
        if not bot:
            return None
        return {
            "name": bot["name"],
            "welcome_message": bot.get("welcome_message", "Hi! How can I help?"),
            "theme_color": bot.get("theme_color", "#6D28D9"),
            "bot_uuid": str(bot["bot_uuid"]),
        }


    def _build_bot_context(self, bot: Dict, page_url: str = None,
                            user_message: str = None,
                            persona: dict = None) -> str:
        """Build context-aware system prompt injection.

        This gets PREPENDED to the user's message so the AgentLoop
        sees it as context. The agent's own system prompt stays unchanged.

        Layers:
        1. Bot's base personality/rules (SKIPPED if persona is active — 
           persona defines identity in the system prompt instead)
        2. Matched URL rules (page-specific instructions)
        3. Relevant knowledge (FTS search against user's question)
        """
        context_parts = []

        if not persona:
            context_parts.append(f"[BOT CONTEXT — {bot['name']}]")
            context_parts.append(bot["system_prompt"])
        else:
            context_parts.append(f"[BOT CONTEXT — {bot['name']}]")

        rules = self._repo.get_bot_rules(bot["bot_id"], page_url)
        if rules:
            context_parts.append("\n[PAGE-SPECIFIC INSTRUCTIONS]")
            for rule in rules:
                context_parts.append(f"- [{rule['rule_type']}: {rule['pattern']}] {rule['instruction']}")

        max_docs = bot.get("max_context_docs", 5)
        knowledge_docs = []

        if user_message:
            knowledge_docs = self._repo.search_bot_knowledge(
                bot["bot_id"], user_message, page_url, limit=max_docs
            )

        if not knowledge_docs:
            knowledge_docs = self._repo.get_bot_knowledge_docs(
                bot["bot_id"], page_url, limit=max_docs
            )

        if knowledge_docs:
            context_parts.append("\n[REFERENCE KNOWLEDGE BASE]")
            context_parts.append("Use this knowledge to answer. Cite it when relevant.")
            for doc in knowledge_docs:
                content = doc.get("content", "")[:2000]
                title = doc.get("title", "Untitled")
                context_parts.append(f"\n### {title}\n{content}")

        if page_url:
            context_parts.append(f"\n[User is currently on page: {page_url}]")

        context_parts.append("[END BOT CONTEXT]\n")

        return "\n".join(context_parts)


    def _load_history_for_agent(self, conversation_id: str) -> List[Dict]:
        """Load recent messages as OpenAI-format for AgentLoop."""
        rows = self._repo.get_recent_messages(conversation_id, limit=20)

        if rows and rows[-1].get("role") == "user":
            rows = rows[:-1]

        history = []
        for r in rows:
            history.append({"role": r["role"], "content": r.get("content", "")})
        return history


    async def stream_bot_chat(
        self,
        api_token: str,
        session_id: str,
        message: str,
        page_url: str = None,
        user_id: str = None,
        client_ip: str = None,
        request_origin: str = None,
    ) -> AsyncGenerator[str, None]:
        """Core streaming method — routes through the FULL AgentLoop.

        Flow:
        1. Validate token → get bot
        1b. Validate origin domain
        2. Rate limit check
        3. Get/create conversation
        4. Build bot context (rules + knowledge)
        5. Inject context into user message
        6. Route through AgentLoop._process_input() (FULL AI AGENT)
        7. 60-second timeout for bot responses
        8. Persist messages
        
        Memory Isolation:
        - user_id=None → anonymous → no memory stored
        - user_id="abc123" → logged-in → memory scoped to bot_{bot_id}_{user_id}
        """
        bot = self._repo.get_bot_by_token(api_token)
        if not bot:
            yield self._sse("error", message="Invalid bot token")
            yield self._sse_done()
            return

        allowed = bot.get("allowed_domains") or ["*"]
        if "*" not in allowed and request_origin:
            origin_host = urlparse(request_origin).hostname or ""
            if not any(
                origin_host == d or origin_host.endswith(f".{d}")
                for d in allowed
            ):
                logger.warning(
                    "bot.domain_rejected: bot=%s origin=%s allowed=%s",
                    bot["name"], origin_host, allowed,
                )
                yield self._sse("error", message="This bot is not authorized for this domain.")
                yield self._sse_done()
                return

        rate_key = f"{client_ip or 'unknown'}:{api_token[:16]}"
        allowed, remaining, reset_secs = await bot_rate_limiter.check(rate_key)
        if not allowed:
            yield self._sse("error",
                message=f"Rate limit exceeded. Try again in {reset_secs} seconds.",
                retryAfter=reset_secs)
            yield self._sse_done()
            return

        conv = self._repo.get_or_create_conversation(
            bot["bot_id"], session_id, page_url
        )
        conversation_id = str(conv["conversation_id"])

        yield self._sse("message.start", conversationId=conversation_id,
                        botName=bot["name"], remaining=remaining)

        self._repo.add_message(conversation_id, "user", message)

        # Persona precedence + graceful degradation: a bound persona that was
        # since deactivated falls back to the app default, never to an
        # ungoverned session. (Resolved via the repo bot_service already holds
        # — self._cli isn't built until _create_agent; the embed-safe wiring
        # below stays bespoke to preserve the public-surface hardening.)
        persona = None
        if self._persona_repo:
            if bot.get("persona_id"):
                persona = self._persona_repo.get_persona(bot["persona_id"])
            if persona is None and bot.get("app_id"):
                persona = self._persona_repo.get_persona_for_app(bot["app_id"])

        yield self._sse("status", state="loading_context")
        bot_context = self._build_bot_context(bot, page_url, message, persona=persona)
        enriched_message = f"{bot_context}\nUser message: {message}"

        db_history = self._load_history_for_agent(conversation_id)

        try:
            session = await _bot_session_pool.get_session(
                conversation_id=conversation_id,
                bot_id=bot["bot_id"],
                bot_name=bot["name"],
                user_id=user_id,
                app_id=bot.get("app_id"),
                db_history=db_history,
                persona=persona,
            )
            agent = session.agent

            yield self._sse("status", state="reasoning")

            from api.services.agent_streamer import stream_agent_turn, final_usage_fields
            state = {"final_text": ""}
            async for frame in stream_agent_turn(
                agent, enriched_message, self._sse, state,
                timeout_s=BOT_RESPONSE_TIMEOUT, ping_every=15,
                log_ctx=f"bot={bot['name']} conv={conversation_id[:8]}",
                include_thinking=False):
                yield frame
            final_text = state["final_text"]

            token_count = len(final_text.split()) if final_text else 0
            self._repo.add_message(
                conversation_id, "assistant", final_text,
                token_count=token_count,
            )

            yield self._sse(
                "message.end",
                content=final_text,
                conversationId=conversation_id,
                tokenCount=token_count,
                **final_usage_fields(agent),
            )

        except Exception as e:
            logger.error("Bot chat error (bot=%s): %s",
                         bot["name"], e, exc_info=True)
            error_msg = "I'm sorry, I encountered an error. Please try again."
            yield self._sse("error", message=error_msg)
            self._repo.add_message(conversation_id, "assistant", error_msg)
            _bot_session_pool.invalidate(conversation_id)

        yield self._sse_done()


    def get_conversation_history(self, api_token: str, session_id: str) -> Optional[Dict]:
        """Get conversation history for a session."""
        bot = self._repo.get_bot_by_token(api_token)
        if not bot:
            return None

        conv = self._repo.get_or_create_conversation(bot["bot_id"], session_id)
        messages = self._repo.get_messages(str(conv["conversation_id"]))

        return {
            "conversationId": str(conv["conversation_id"]),
            "botName": bot["name"],
            "messages": [
                {
                    "role": m["role"],
                    "content": m["content"],
                    "createdAt": m["created_at"].isoformat() if m.get("created_at") else None,
                }
                for m in messages
            ],
        }
