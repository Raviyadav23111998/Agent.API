"""
Gateway runner — orchestrates platform adapters + cron scheduler.

Architecture (identical to Agent):
- Each chat_id gets an ISOLATED agent session (no cross-user contamination)
- Sessions expire after SESSION_TTL_SECONDS of inactivity
- Shared: tool_registry, LLM client, memory (cross-session memories are intentional)
- Isolated per session: conversation_history, checkpoint_mgr, system prompt cache

Lifecycle:
    1. Initialize adapters (Telegram, etc.)
    2. Wire message callbacks → session manager → agent loop
    3. Start cron ticker (every 60s)
    4. Run until interrupted

Usage:
    runner = GatewayRunner(workspace_path)
    await runner.start()
"""

import asyncio
import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import path_setup  # noqa: F401 — bootstraps Agent.Core path

from gateway.base import MessageEvent, CardContent
from cron import scheduler as cron_scheduler, init_db as cron_init_db
from core.tenant import MembershipResolver

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.DOTALL | re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    """Remove inlined <think>…</think> reasoning from a final answer (Teams).

    Drops closed reasoning blocks; if an unclosed <think> remains (truncated),
    everything from it on is treated as reasoning and dropped too. Falls back to
    the original text if stripping would leave nothing, so the user always gets
    an answer.
    """
    if not text or "<think" not in text.lower():
        return text
    cleaned = _THINK_RE.sub("", text)
    low = cleaned.lower()
    if "<think" in low:
        cleaned = cleaned[: low.index("<think")]
    cleaned = cleaned.strip()
    return cleaned or text.strip()


def parse_tool_cron_marker(prompt: str):
    """Parse a ``[TOOL:<name>] <optional JSON args>`` cron prompt.

    Returns ``(name, args_dict)`` on success, or ``(None, error_string)`` on a
    malformed marker. Pure + total so the parse edge-cases are unit-testable
    without spinning up the runner.
    """
    import json
    head, sep, rest = (prompt or "").partition("]")
    if not sep or not head.startswith("[TOOL:"):
        return None, "✗ [TOOL] malformed marker — expected '[TOOL:<name>] {json}'."
    name = head[len("[TOOL:"):].strip()
    rest = rest.strip()
    if not name:
        return None, "✗ [TOOL] missing tool name — expected '[TOOL:<name>] {json}'."
    if not rest:
        return name, {}
    try:
        args = json.loads(rest)
    except Exception as e:
        return None, f"✗ [TOOL:{name}] invalid JSON args: {e}"
    if not isinstance(args, dict):
        return None, (f"✗ [TOOL:{name}] args must be a JSON object, got "
                      f"{type(args).__name__}.")
    return name, args


CRON_TICK_INTERVAL = 60
RECONCILE_TICK_INTERVAL = 120
SESSION_TTL_SECONDS = 1800
SESSION_CLEANUP_INTERVAL = 300


class AgentSession:
    """Isolated agent session per chat_id.
    
    Each session has its own conversation history and checkpoint state.
    This prevents cross-user contamination in the gateway.
    """
    
    def __init__(self, chat_id: str, agent_loop):
        self.chat_id = chat_id
        self.agent = agent_loop
        self.created_at = time.time()
        self.last_active = time.time()
        self.pending_approvals: dict = {}
        self.approval_forwarder = None
        self.plan_citations_forwarder = None
    
    def touch(self):
        """Update last active timestamp."""
        self.last_active = time.time()
    
    @property
    def is_expired(self) -> bool:
        return (time.time() - self.last_active) > SESSION_TTL_SECONDS


class SessionManager:
    """Manages isolated agent sessions per chat_id.
    
    Architecture (from Agent):
    - Each chat gets its own AgentLoop instance with isolated conversation history
    - Sessions share: tool_registry, LLM client, memory_manager, event_bus
    - Sessions expire after 30min of inactivity
    - On expiry: auto-generates conversation summary for cross-session continuity
    
    Identity Resolution (Enterprise SSO pattern):
    - Platform adapters pass email/external_id in MessageEvent
    - SessionManager maps these to ag_auth.users via email lookup
    - If no match: JIT provision (auto-create user like Azure AD SSO)
    - Resolved user_id flows into UserContext → CredentialRegistry → per-user tools
    """
    
    def __init__(self, cli_instance, membership_resolver: MembershipResolver = None,
                 db=None):
        self._cli = cli_instance
        self._sessions: dict = {}
        self._membership = membership_resolver
        self._db = db
    
    def _resolve_system_user(self, platform: str, platform_user_id: str,
                              user_name: str = "", email: str = None,
                              raw: dict = None) -> dict:
        """Resolve an external platform identity to an internal ag_auth.users record.
        
        Resolution chain (first match wins):
            1. Email match → ag_auth.users.email
            2. External ID match → ag_auth.users.external_id
            3. JIT Provision → auto-create user (enterprise SSO pattern)
        
        This is how Microsoft Entra ID SSO works in large orgs:
        external identity (AAD Object ID / UPN) is mapped to an internal
        user record on first login, with auto-provisioning.
        
        Args:
            platform: Platform name ('teams', 'telegram')
            platform_user_id: Raw platform user ID (Teams AAD ID, Telegram ID)
            user_name: Display name from the platform
            email: User's email (from Teams UPN or profile)
            raw: Raw activity dict (for fallback email extraction)
            
        Returns:
            dict with keys: user_id (int), email, full_name, app_id, is_new
        """
        if not self._db:
            return {"user_id": None, "email": email, "full_name": user_name,
                    "app_id": None, "is_new": False}
        
        if email:
            row = self._db.fetch_one(
                "SELECT user_id, email, full_name, app_id FROM ag_auth.users "
                "WHERE LOWER(email) = LOWER(%s) AND is_active = TRUE",
                (email,)
            )
            if row:
                logger.info("[Identity] Resolved %s user %s (email=%s) → system user_id=%s",
                            platform, user_name, email, row["user_id"])
                return {"user_id": row["user_id"], "email": row["email"],
                        "full_name": row["full_name"], "app_id": row.get("app_id"),
                        "is_new": False}
        
        if platform_user_id:
            row = self._db.fetch_one(
                "SELECT user_id, email, full_name, app_id FROM ag_auth.users "
                "WHERE external_id = %s AND is_active = TRUE",
                (platform_user_id,)
            )
            if row:
                logger.info("[Identity] Resolved %s user %s (external_id=%s) → system user_id=%s",
                            platform, user_name, platform_user_id[:16], row["user_id"])
                return {"user_id": row["user_id"], "email": row["email"],
                        "full_name": row["full_name"], "app_id": row.get("app_id"),
                        "is_new": False}
        
        if email or user_name:
            try:
                row = self._db.execute_returning(
                    """INSERT INTO ag_auth.users
                        (email, full_name, external_id, platform, role_id, is_active, app_id, created_at)
                    VALUES (%s, %s, %s, %s, (SELECT role_id FROM ag_auth.roles WHERE role_name ILIKE 'Member' OR role_key ILIKE 'member' LIMIT 1), TRUE, 1, NOW())
                    ON CONFLICT (email) DO UPDATE SET
                        external_id = COALESCE(NULLIF(EXCLUDED.external_id, ''), ag_auth.users.external_id),
                        full_name = COALESCE(NULLIF(EXCLUDED.full_name, ''), ag_auth.users.full_name),
                        app_id = COALESCE(ag_auth.users.app_id, 1)
                    RETURNING user_id, email, full_name, app_id""",
                    (email or f"{platform}_{platform_user_id}@gateway",
                     user_name or f"User-{platform_user_id[:8]}",
                     platform_user_id, platform)
                )
                is_new = True
                logger.info("[Identity] JIT provisioned %s user %s (email=%s) → user_id=%s",
                            platform, user_name, email or "auto", row["user_id"])
                return {"user_id": row["user_id"], "email": row["email"],
                        "full_name": row["full_name"], "app_id": row.get("app_id"),
                        "is_new": is_new}
            except Exception as e:
                logger.error("[Identity] JIT provision failed for %s/%s: %s",
                             platform, user_name, e)
        
        logger.warning("[Identity] Could not resolve %s user %s — running as anonymous",
                        platform, user_name)
        return {"user_id": None, "email": email, "full_name": user_name,
                "app_id": None, "is_new": False}
    
    def get_or_create(self, chat_id: str, user_id: str = "",
                      user_name: str = "",
                      platform: str = "telegram",
                      email: str = None,
                      raw: dict = None) -> 'AgentSession':
        """Get existing session or create a new one for this chat."""
        if chat_id in self._sessions:
            session = self._sessions[chat_id]
            if not session.is_expired:
                session.touch()
                logger.debug("Found existing session for chat_id=%s", chat_id)
                return session
            else:
                logger.debug("Session expired for chat_id=%s", chat_id)
                self._expire_session(chat_id)

        logger.debug("Running identity resolution for platform=%s user_id=%s email=%s user_name=%s",
                     platform, user_id, email, user_name)
        resolved = self._resolve_system_user(
            platform=platform,
            platform_user_id=user_id,
            user_name=user_name,
            email=email,
            raw=raw,
        )
        system_user_id = resolved["user_id"]
        app_id = resolved["app_id"]
        
        effective_user_id = str(system_user_id) if system_user_id else (user_id or str(chat_id))
        
        group_ids = ()
        if self._membership:
            self._membership.resolve_chat_context(
                chat_id=str(chat_id),
                user_id=effective_user_id,
                user_name=user_name,
            )
            group_ids = tuple(self._membership.get_user_groups(effective_user_id))
        
        from core.user_context import UserContext
        user_ctx = UserContext(
            user_id=effective_user_id,
            user_name=user_name or resolved["full_name"] or f"User-{effective_user_id}",
            platform=platform,
            share_ingested=False,
            group_ids=group_ids,
            app_id=str(app_id) if app_id else None,
        )
        
        from core.agent_loop import AgentLoop
        from core.workspace_manager import WorkspaceManager
        from async_bus.event_bus import EventBus

        from core.tenant_context import current_tenant
        ws_manager = WorkspaceManager(tenant_id=current_tenant().tenant_key)
        ws_user_id = int(effective_user_id) if effective_user_id.isdigit() else 0
        user_ws = ws_manager.ensure_workspace(ws_user_id)
        user_quota = ws_manager.get_user_quota_bytes(ws_user_id)

        user_tool_registry = self._cli.create_user_tools(
            user_ws, sandboxed=True, max_size_bytes=user_quota,
            user_context=user_ctx,
        )

        session_bus = EventBus()

        # Persona governance via the shared applicator — the SAME seam chat and
        # cron use, so a bot session is wired identically (identity, guardrails,
        # tool whitelist, approval, dynamic ops/picker).
        from core.config import app_config
        from api.services.persona_applicator import apply_persona
        _ap = apply_persona(
            self._cli, self._db,
            base_registry=user_tool_registry, user_ctx=user_ctx,
            app_id=app_id,
            default_approval_mode=app_config.get(
                "gateway.approval_mode",
                app_config.get("agent.approval_mode", "irreversible")))
        persona = _ap.persona
        prompt_overrides = _ap.prompt_overrides
        guardrail_engine = _ap.guardrail_engine
        user_tool_registry = _ap.tool_registry
        dynamic_picker = _ap.dynamic_picker

        from core.approvals import ApprovalManager
        approval_manager = ApprovalManager(
            session_bus, user_id=system_user_id, mode=_ap.approval_mode,
        )

        # Per-app model profile + usage ledger + budgets (channel sessions
        # resolve by the messaging user's id + app scope).
        llm_client = self._cli.llm
        _usage_sink = None
        _budget_check = None
        try:
            from api.services.llm_scope import attach_scope, numeric_user_id
            _scope = attach_scope(self._cli)
            from api.services.skill_service import attach_skills
            attach_skills(self._cli)
            _uid = numeric_user_id(getattr(user_ctx, "user_id", None))
            _profile = _scope.resolve_profile(user_id=_uid, app_id=app_id)
            llm_client = _scope.client_for(_profile, self._cli.llm)
            _usage_sink = _scope.make_usage_sink(
                user_id=_uid, app_id=app_id, run_kind="bot",
                profile_id=(_profile or {}).get("profile_id"))
            _budget_check = _scope.make_budget_check(user_id=_uid, app_id=app_id)
        except Exception as e:
            logger.debug("[Session] llm scope unavailable — legacy client (%s)", e)

        agent = AgentLoop(
            user_ws,
            llm_client,
            user_tool_registry,
            session_bus,
            transcript_logger=self._cli.logger,
            memory_manager=self._cli.memory,
            user_context=user_ctx,
            db=self._membership._db if self._membership else None,
            prompt_overrides=prompt_overrides,
            guardrail_engine=guardrail_engine,
            approval_manager=approval_manager,
            tenant_context=current_tenant(),
            dynamic_picker=dynamic_picker,
            usage_sink=_usage_sink,
            budget_check=_budget_check,
        )
        
        from core.prompt_sections import (
            render_knowledge, KNOWLEDGE_KEY, KNOWLEDGE_ORDER)
        agent.prompt_builder.set_section(
            KNOWLEDGE_KEY,
            render_knowledge(list(self._cli.knowledge.load_active_kis())),
            KNOWLEDGE_ORDER)

        session = AgentSession(chat_id, agent)
        self._sessions[chat_id] = session
        logger.info("[Session] Created session for chat %s (user=%s app_id=%s groups=%d identity=%s)",
                    chat_id[:20], user_ctx, app_id, len(group_ids),
                    "resolved" if system_user_id else "anonymous")
        return session
    
    def _expire_session(self, chat_id: str):
        """Expire a session: save summary, clean up."""
        session = self._sessions.get(chat_id)
        if not session:
            return
        
        try:
            summary = session.agent.generate_session_summary()
            if summary and summary.get("objective"):
                self._cli.summaries.save_summary(summary)
                logger.info("[Session] Saved summary for expired session %s", chat_id)
        except Exception as e:
            logger.warning("[Session] Failed to save summary for %s: %s", chat_id, e)
        
        try:
            from state.memory_consolidator import MemoryConsolidator
            consolidator = MemoryConsolidator(self._cli.memory)
            consolidator.consolidate(user_id=str(chat_id))
        except Exception as e:
            logger.debug("[Session] Memory consolidation failed for %s: %s", chat_id, e)
        
        del self._sessions[chat_id]
        logger.info("[Session] Expired session for chat %s", chat_id)
    
    def cleanup_expired(self):
        """Remove all expired sessions."""
        expired = [cid for cid, s in self._sessions.items() if s.is_expired]
        for cid in expired:
            self._expire_session(cid)
        if expired:
            logger.info("[Session] Cleaned up %d expired session(s)", len(expired))
    
    @property
    def active_count(self) -> int:
        return len(self._sessions)


class GatewayRunner:
    """Manages platform adapters, session isolation, and the cron scheduler.
    
    Architecture (identical to Agent):
    - Each incoming message is routed to an ISOLATED session per chat_id
    - No cross-user contamination in conversation history
    - Cron jobs run in their own ephemeral session
    - Sessions expire after 30min of inactivity with auto-summary
    """
    
    def __init__(self, workspace_path: str):
        self.workspace_path = os.path.abspath(workspace_path)
        self._adapters = []
        self._telegram_manager = None
        self._cron_task = None
        self._cleanup_task = None
        self._reconcile_task = None
        self._running = False
        
        from core.tenant_db import TenantDB
        from core.tenant_context import multi_tenant_enabled
        control_db = TenantDB()
        control_db.connect()
        self._control_db = control_db

        try:
            from core.msystem_router import MSystemRouter
            self._msystem_router = MSystemRouter()
        except Exception as e:
            self._msystem_router = None
            logger.warning("[Gateway] MSystem router unavailable: %s", e)
        from core.tenant_resolver import TenantConnectionResolver, set_global_resolver
        self._tenant_resolver = TenantConnectionResolver(msystem_router=self._msystem_router)
        set_global_resolver(self._tenant_resolver)

        if multi_tenant_enabled():
            from core.tenant_db_proxy import TenantDBProxy
            self._db = TenantDBProxy(self._tenant_resolver, control_db)
            logger.info("[Gateway] Multi-tenant: ON — DB routes per-tenant via MSystem")
        else:
            self._db = control_db
            logger.info("[Gateway] Multi-tenant: OFF — control DB only")

        from client.cli import AgentCLI
        self._cli = AgentCLI(workspace_path, db=self._db)

        cron_init_db(self._db)

        from gateway.outbox import DeliveryOutbox
        self._outbox = DeliveryOutbox(self._db)

        from state.retention import RetentionManager
        self._retention = RetentionManager(self._db)
        self._last_retention_sweep = 0.0

        self._membership = MembershipResolver(self._db)
        
        self._sessions = SessionManager(self._cli, self._membership, db=self._db)
        
        self._register_cron_tools()
    
    def _register_cron_tools(self):
        """Register cron job management tools so the agent can self-schedule."""
        pass
        
        self._cli.tool_registry.register(
            "cron_create",
            "Create a scheduled cron job. The agent will run the prompt at the specified schedule. "
            "Results are saved locally AND delivered to Telegram (if available).",
            {
                "prompt": "string",
                "schedule": "string",
                "name?": "string",
                "repeat?": "int",
            },
            self._cron_create,
            param_descriptions={
                "prompt": "Self-contained prompt to run. Must include ALL context needed.",
                "schedule": "Schedule: '30m' (once in 30min), 'every 2h' (recurring), '0 9 * * *' (cron), '2026-02-03T14:00' (timestamp).",
                "name": "Friendly name for the job.",
                "repeat": "Times to run. Omit for default (1 for one-shot, unlimited for recurring).",
            }
        )
        
        self._cli.tool_registry.register(
            "cron_list",
            "List all scheduled cron jobs with their status, next run time, and schedule.",
            {},
            self._cron_list,
        )
        
        self._cli.tool_registry.register(
            "cron_remove",
            "Remove/cancel a cron job by its ID.",
            {"job_id": "string"},
            self._cron_remove,
            param_descriptions={
                "job_id": "The 12-character job ID to remove.",
            }
        )
    
    def _cron_create(self, prompt: str, schedule: str,
                     name: str = None, repeat: int = None) -> str:
        """Create a cron job. Called by the agent via tool."""
        try:
            origin = None
            if self._adapters:
                origin = {"platform": "telegram"}
            
            job = create_job(
                prompt=prompt,
                schedule=schedule,
                name=name,
                repeat=repeat,
                deliver="origin" if origin else "local",
                origin=origin,
            )
            return (
                f"✅ Cron job created:\n"
                f"  ID: {job['id']}\n"
                f"  Name: {job['name']}\n"
                f"  Schedule: {job['schedule_display']}\n"
                f"  Next run: {job.get('next_run_at', 'N/A')}\n"
                f"  Delivery: {job.get('deliver', 'local')}"
            )
        except ValueError as e:
            return f"❌ Error creating job: {e}"
        except Exception as e:
            return f"❌ Unexpected error: {e}"
    
    def _cron_list(self) -> str:
        """List all cron jobs."""
        jobs = list_jobs(include_disabled=True)
        if not jobs:
            return "No cron jobs scheduled."
        
        lines = ["**Scheduled Jobs:**\n"]
        for job in jobs:
            status = "✅" if job.get("enabled") else "⏸️"
            state = job.get("state", "unknown")
            lines.append(
                f"{status} **{job.get('name', job['id'])}** (ID: `{job['id']}`)\n"
                f"   Schedule: {job.get('schedule_display', '?')}\n"
                f"   State: {state} | Next: {job.get('next_run_at', 'N/A')}\n"
                f"   Last: {job.get('last_status', 'never')} at {job.get('last_run_at', 'N/A')}"
            )
        return "\n".join(lines)
    
    def _cron_remove(self, job_id: str) -> str:
        """Remove a cron job."""
        from cron.jobs import remove_job
        if remove_job(job_id):
            return f"✅ Job `{job_id}` removed."
        return f"❌ Job `{job_id}` not found."
    
    async def start(self):
        """Start all platform adapters and the cron ticker."""
        self._running = True
        import uuid, datetime
        self._instance_id = str(uuid.uuid4())[:8]
        print(f"\n[{datetime.datetime.now().isoformat()}] Instance {self._instance_id}", flush=True)
        
        print("\n" + "=" * 50)
        print("  Agent Gateway")
        print("=" * 50)
        print(f"  Model: {self._cli.llm.model}")
        print(f"  Tools: {len(self._cli.tool_registry._tools)}")
        print(f"  Sessions: Isolated per chat (TTL: {SESSION_TTL_SECONDS}s)")
        
        try:
            from gateway.telegram import TelegramManager
            self._telegram_manager = TelegramManager(
                self._cli.connections, self._db, self._handle_message,
                msystem_router=self._msystem_router,
            )
            await self._telegram_manager.start()
            print(f"  Telegram: ✅ {self._telegram_manager.bot_count} personal bot(s) "
                  f"(per-user, auto-reconciled)")
        except ImportError:
            print("  Telegram: ⚠️ python-telegram-bot not installed")
        except Exception as e:
            print(f"  Telegram: ❌ {e}")
            
        try:
            from gateway.teams import TeamsAdapter, BOTBUILDER_AVAILABLE
            if not BOTBUILDER_AVAILABLE:
                print("  Teams: ⚠️ botbuilder-core not installed")
            else:
                teams_adapter = TeamsAdapter(credential_registry=self._cli.connections)
                teams_adapter.on_message = self._handle_message
                self._adapters.append(teams_adapter)
                await teams_adapter.start()
                port = os.environ.get("AG_TEAMS_WORKER_PORT", "8115")
                print(f"  Teams: ✅ Webhook listener on port {port} (per-tenant bot credentials)")
        except Exception as e:
            print(f"  Teams: ❌ {e}")
        
        # The gateway holds a long-lived Connections (via the CLI), so it must
        # react to config/provider changes made in the API process instead of
        # serving a stale cache until the TTL lapses.
        try:
            from core.redis_client import subscribe_config_reload
            from core.config import app_config
            from core.connections import invalidate_provider_cache

            def _on_reload(key: str):
                app_config.reload()
                invalidate_provider_cache()

            subscribe_config_reload(_on_reload)
            print("  Config: ✅ Redis reload subscriber started")
        except Exception as e:
            print(f"  Config: ⚠️ reload subscriber skipped ({e})")

        self._cron_task = asyncio.create_task(self._cron_ticker())
        print(f"  Cron: ✅ Ticking every {CRON_TICK_INTERVAL}s")
        
        self._cleanup_task = asyncio.create_task(self._session_cleanup_loop())

        self._reconcile_task = asyncio.create_task(self._reconcile_ticker())
        print(f"  Brain reconciler: ✅ Ticking every {RECONCILE_TICK_INTERVAL}s")

        print("=" * 50)
        print("  Gateway running. Ctrl+C to stop.\n")
        sys.stdout.flush()
        
        try:
            while self._running:
                await asyncio.sleep(60)
            logger.debug("Main loop exited: running=%s", self._running)
        except BaseException as e:
            logger.exception("Main loop exception: %s", e)

        await self.stop()
    
    async def stop(self):
        """Stop all adapters and the cron ticker."""
        self._running = False
        print("\n  Shutting down gateway...")
        
        if self._cron_task:
            self._cron_task.cancel()
            try:
                await self._cron_task
            except asyncio.CancelledError:
                pass
        
        if self._reconcile_task:
            self._reconcile_task.cancel()
            try:
                await self._reconcile_task
            except asyncio.CancelledError:
                pass

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        self._sessions.cleanup_expired()
        
        if self._telegram_manager:
            await self._telegram_manager.stop()

        for adapter in self._adapters:
            await adapter.stop()

        print("  Gateway stopped.")
    
    async def _handle_message(self, event: MessageEvent):
        """Handle incoming message from a platform adapter.

        Routes to an ISOLATED session per chat_id.
        No cross-user contamination in conversation history.
        """
        logger.info("[Gateway] Message from %s (chat %s): %s",
                     event.user_name, event.chat_id, event.text[:80])
        
        adapter = getattr(event, 'source_adapter', None)
        if adapter is None:
            for a in self._adapters:
                if a.platform_name == event.platform:
                    adapter = a
                    break

        session_key = getattr(event, 'session_key', None) or event.chat_id

        session = self._sessions.get_or_create(
            session_key,
            user_id=getattr(event, 'user_id', '') or str(event.chat_id),
            user_name=event.user_name,
            platform=event.platform,
            email=getattr(event, 'email', None),
            raw=event.raw,
        )

        if session.pending_approvals:
            from core.approvals import resolve_approval
            reply = event.text.strip().lower()
            yes = reply in ("yes", "y", "approve", "approved", "ok", "allow")
            no = reply in ("no", "n", "deny", "denied", "reject", "cancel")
            if yes or no:
                approval_id = next(iter(session.pending_approvals))
                tool_name = session.pending_approvals.pop(approval_id)
                resolve_approval(approval_id, approved=yes)
                logger.info("[Gateway] Approval %s for %s: %s",
                            approval_id, tool_name, "approved" if yes else "denied")
            elif adapter:
                await adapter.send(
                    event.chat_id,
                    "⏳ An action is awaiting your approval. "
                    "Reply **yes** to approve or **no** to deny.",
                    event.thread_id,
                )
            return

        if session.approval_forwarder is None and adapter:
            _adapter, _chat, _thread = adapter, event.chat_id, event.thread_id

            async def _on_approval_request(payload):
                approval_id = payload.get("approval_id", "")
                tool_name = payload.get("tool_name", "action")
                if not approval_id:
                    return
                session.pending_approvals[approval_id] = tool_name
                args_preview = str(payload.get("tool_args", ""))[:300]
                timeout_s = int(payload.get("timeout_s", 300))
                timeout_min = max(1, timeout_s // 60)
                card = CardContent(
                    card_type="approval",
                    title="⚠️ Approval required",
                    items=[],
                    fallback_text=(
                        f"⚠️ **Approval required**\n"
                        f"The agent wants to run `{tool_name}`.\n"
                        f"Args: {args_preview}\n\n"
                        f"Reply **yes** to approve or **no** to deny "
                        f"(auto-denied in {timeout_min} min)."
                    ),
                    data={
                        "approval_id": approval_id,
                        "tool": tool_name,
                        "args": args_preview,
                        "timeout_min": timeout_min,
                    },
                )
                try:
                    await _adapter.send_card(_chat, card, _thread)
                except Exception as exc:
                    logger.debug("[Gateway] approval card send failed: %s", exc)
                    await _adapter.send(_chat, card.fallback_text, _thread)

            session.agent.event_bus.subscribe('approval_request', _on_approval_request)
            session.approval_forwarder = _on_approval_request

        if session.plan_citations_forwarder is None and adapter \
                and event.platform != "teams":
            _card_adapter, _card_chat, _card_thread = adapter, event.chat_id, event.thread_id

            async def _on_plan(payload):
                steps = payload.get("steps", [])
                if not steps:
                    return
                card = CardContent(
                    card_type="plan",
                    title="\U0001f4cb Plan",
                    items=steps,
                    fallback_text="\U0001f4cb **Plan:**\n" + "\n".join(
                        f"  {i+1}. {s}" for i, s in enumerate(
                            (st if isinstance(st, str) else str(st)) for st in steps
                        )
                    ),
                )
                try:
                    await _card_adapter.send_card(_card_chat, card, _card_thread)
                except Exception as exc:
                    logger.debug("[Gateway] plan card send failed: %s", exc)

            async def _on_citations(payload):
                sources = payload.get("sources", [])
                if not sources:
                    return
                card = CardContent(
                    card_type="citations",
                    title="\U0001f4ce Sources",
                    items=sources,
                    fallback_text="\U0001f4ce **Sources:**\n" + "\n".join(
                        f"  \u2022 {s.get('title', '?') if isinstance(s, dict) else s}"
                        f" \u2014 {(s.get('snippet', '')[:100] if isinstance(s, dict) else '')}"
                        for s in sources[:8]
                    ),
                )
                try:
                    await _card_adapter.send_card(_card_chat, card, _card_thread)
                except Exception as exc:
                    logger.debug("[Gateway] citations card send failed: %s", exc)

            session.agent.event_bus.subscribe('plan', _on_plan)
            session.agent.event_bus.subscribe('citations', _on_citations)
            session.plan_citations_forwarder = True

        # Part 2 egress — deliver model-generated media to this chat (all
        # platforms incl. Teams). Loads the artifact's bytes by id and hands
        # them to the adapter's send_media (Telegram photo, Teams card image…).
        if getattr(session, "artifact_forwarder", None) is None and adapter:
            _art_adapter, _art_chat = adapter, event.chat_id
            _art_thread, _art_db = event.thread_id, self._db

            async def _on_artifact(payload):
                fid = payload.get("file_id")
                if fid is None:
                    return
                try:
                    from core.file_record import load_file
                    f = load_file(_art_db, fid)
                    if f:
                        await _art_adapter.send_media(
                            _art_chat, f["bytes"], f["kind"],
                            f.get("mime_type") or "",
                            f.get("filename") or "file", _art_thread)
                except Exception as exc:
                    logger.debug("[Gateway] artifact send failed: %s", exc)

            session.agent.event_bus.subscribe('artifact', _on_artifact)
            session.artifact_forwarder = _on_artifact

        try:
            response_text = None
            response_event = asyncio.Event()

            async def capture_response(payload):
                nonlocal response_text
                response_text = payload.get("message", "")
                response_event.set()

            session.agent.event_bus.subscribe('agent_response', capture_response)

            typing_task = None
            if adapter and hasattr(adapter, "send_typing"):
                async def _typing_keepalive():
                    try:
                        while True:
                            await adapter.send_typing(event.chat_id)
                            await asyncio.sleep(4)
                    except asyncio.CancelledError:
                        pass
                typing_task = asyncio.create_task(_typing_keepalive())

            try:
                # Part 1 ingress — carry the platform's photo/document/voice into
                # the turn, but only the types THIS bot's model can read (drop +
                # warn otherwise, so a text-only model never 400s).
                _gw_payload = {"user_input": event.text}
                _atts = getattr(event, "attachments", None)
                if _atts:
                    from core.model_capabilities import accepted_input_kinds
                    _model = getattr(getattr(session.agent, "llm_client", None),
                                     "model", "") or ""
                    _accepted = accepted_input_kinds(_model)
                    _km = {"image": "image", "document": "pdf",
                           "audio": "audio", "video": "video"}
                    _kept = [a for a in _atts
                             if _km.get(a.get("kind"), a.get("kind")) in _accepted]
                    _dropped = sorted({a.get("kind") for a in _atts} -
                                      {a.get("kind") for a in _kept})
                    if _kept:
                        _gw_payload["attachments"] = _kept
                    if _dropped and adapter:
                        try:
                            await adapter.send(
                                event.chat_id,
                                "⚠️ This assistant's model can't read "
                                f"{', '.join(_dropped)} attachments, so they were "
                                "skipped.", event.thread_id)
                        except Exception:
                            pass
                await session.agent._process_input(_gw_payload)
                try:
                    await asyncio.wait_for(response_event.wait(), timeout=300)
                except asyncio.TimeoutError:
                    response_text = "⏰ Request timed out after 5 minutes."
            finally:
                if typing_task is not None:
                    typing_task.cancel()
                    try:
                        await typing_task
                    except asyncio.CancelledError:
                        pass

            session.agent.event_bus.unsubscribe('agent_response', capture_response)

            session.pending_approvals.clear()

            if adapter and response_text:
                if event.platform == "teams":
                    response_text = _strip_reasoning(response_text)
                await adapter.send(event.chat_id, response_text, event.thread_id)

            # Learning loop (M3): Telegram & Teams carry REAL, authenticated
            # users on the tenant's own connected channels (resolved to system
            # user ids, so they pass the engine's machine-turn gate the same as
            # web chat). Their corrections should teach too — same governed
            # path as chat_service: flag-gated, capped, budgeted, metered as
            # run_kind='review'. Fire-and-forget; never affects the reply.
            try:
                from api.services.learning_service import maybe_review
                _uctx = getattr(session.agent, "user_context", None)
                _aid = getattr(_uctx, "app_id", None)
                maybe_review(agent=session.agent, cli=self._cli, db=self._db,
                             conversation_id=session_key,
                             app_id=int(_aid) if _aid else None)
            except Exception:
                logger.debug("[Gateway] learning hook failed", exc_info=True)

        except Exception as e:
            logger.error("[Gateway] Error processing message: %s", e, exc_info=True)
            if adapter:
                await adapter.send(event.chat_id, f"❌ Error: {e}", event.thread_id)
    
    async def _cron_ticker(self):
        """Run the cron scheduler tick every CRON_TICK_INTERVAL seconds.

        Multi-tenant fan-out: cron jobs live in EACH tenant's own
        ag_agents.cron_jobs (DB-per-tenant), so a single default-context tick
        would only ever see the control DB and tenant jobs would never run. We
        tick the default context AND every provisioned tenant under its bound
        TenantContext, so each tenant's jobs + delivery outbox execute against
        that tenant's database (the routing proxy resolves the pool).
        """
        logger.info("[Cron] Ticker started (interval: %ds)", CRON_TICK_INTERVAL)

        while self._running:
            try:
                await asyncio.sleep(CRON_TICK_INTERVAL)
                await self._tick_all_contexts()
                import time as _t
                if _t.time() - self._last_retention_sweep >= 86400:
                    self._last_retention_sweep = _t.time()
                    await asyncio.to_thread(self._retention.sweep)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[Cron] Tick error: %s", e, exc_info=True)

    async def _tick_one_context(self):
        """Tick due jobs + flush the delivery outbox for the ACTIVE tenant
        context (default or whatever is currently bound)."""
        await cron_scheduler.tick(
            run_agent=self._run_agent_for_cron,
            deliver_fn=self._deliver_cron_result,
        )
        await self._outbox.flush(self._outbox_send)

    async def _tick_all_contexts(self):
        """Fan the cron tick across the default context + each provisioned
        tenant, each isolated by its bound TenantContext. One tenant failing
        never blocks the others."""
        from core.tenant_context import (multi_tenant_enabled, set_tenant_context,
                                          reset_tenant_context, TenantContext)
        try:
            await self._tick_one_context()
        except Exception as e:
            logger.error("[Cron] tick failed (default): %s", e, exc_info=True)

        if not multi_tenant_enabled() or not self._msystem_router:
            return
        try:
            tenants = self._msystem_router.list_agent_tenants()
        except Exception as e:
            logger.error("[Cron] tenant enumeration failed: %s", e)
            return
        for t in tenants:
            ctx = TenantContext(
                tenant_id=t["tenant_id"], tenant_key=t["tenant_key"],
                display_name=t.get("display_name") or t["tenant_key"],
                tenant_domain=t.get("primary_domain"), is_default=False,
            )
            tok = set_tenant_context(ctx)
            try:
                await self._tick_one_context()
            except Exception as e:
                logger.error("[Cron] tick failed (tenant=%s): %s", t.get("tenant_key"), e)
            finally:
                reset_tenant_context(tok)
    
    async def _reconcile_ticker(self):
        """Heal incomplete multi-store ingestion across all tenants, on a slow
        cadence. Re-runs any document pillar (ES / Neo4j / pgvector) that isn't
        'ok', so the back-catalogue and any post-outage gaps converge on their
        own — no manual backfill, and persistent failures stay visible in the
        index_state instead of vanishing."""
        logger.info("[Reconcile] Ticker started (interval: %ds)", RECONCILE_TICK_INTERVAL)
        while self._running:
            try:
                await asyncio.sleep(RECONCILE_TICK_INTERVAL)
                await self._reconcile_all_contexts()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[Reconcile] Tick error: %s", e, exc_info=True)

    async def _reconcile_one_context(self):
        """Run a reconciler pass for the ACTIVE tenant's StorageManager."""
        from core.tenant_resolver import get_global_resolver
        from core.tenant_context import current_tenant
        resolver = get_global_resolver()
        if resolver is None:
            return
        try:
            storage = resolver.for_tenant(current_tenant()).storage_manager
        except Exception:
            return
        if storage is None or getattr(storage, "index_state", None) is None:
            return
        extractor = None
        try:
            from brain.extraction.graph_extractor import GraphExtractor
            from brain.llm_adapter import BrainLLMAdapter
            extractor = GraphExtractor(BrainLLMAdapter(self._cli.llm))
        except Exception as e:
            logger.warning("[Reconcile] graph extractor unavailable: %s", e)
        from brain.ingestion.reconciler import BrainReconciler
        await BrainReconciler(storage, batch_size=50, extractor=extractor).tick()

    async def _reconcile_all_contexts(self):
        """Fan the reconcile pass across the default context + each provisioned
        tenant, isolated by its bound TenantContext (one failing never blocks
        the others) — mirrors the cron fan-out."""
        from core.tenant_context import (multi_tenant_enabled, set_tenant_context,
                                          reset_tenant_context, TenantContext)
        try:
            await self._reconcile_one_context()
        except Exception as e:
            logger.error("[Reconcile] failed (default): %s", e)

        if not multi_tenant_enabled() or not self._msystem_router:
            return
        try:
            tenants = self._msystem_router.list_agent_tenants()
        except Exception as e:
            logger.error("[Reconcile] tenant enumeration failed: %s", e)
            return
        for t in tenants:
            ctx = TenantContext(
                tenant_id=t["tenant_id"], tenant_key=t["tenant_key"],
                display_name=t.get("display_name") or t["tenant_key"],
                tenant_domain=t.get("primary_domain"), is_default=False,
            )
            tok = set_tenant_context(ctx)
            try:
                await self._reconcile_one_context()
            except Exception as e:
                logger.error("[Reconcile] failed (tenant=%s): %s", t.get("tenant_key"), e)
            finally:
                reset_tenant_context(tok)

    async def _session_cleanup_loop(self):
        """Periodically clean up expired sessions."""
        while self._running:
            try:
                await asyncio.sleep(SESSION_CLEANUP_INTERVAL)
                self._sessions.cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[Session] Cleanup error: %s", e)
    
    async def _run_agent_for_cron(self, prompt: str, app_id=None,
                                  persona_id=None) -> str:
        """Run a prompt through a fresh ephemeral agent for a cron job.

        The job's owning ``app_id`` is threaded into the run's identity so it
        authenticates with that app's connections (e.g. an app-scoped Jira
        credential) — without it, credential resolution can only reach
        org-scope connections and app/user-scoped ones are invisible.

        If the prompt starts with [AGENT:<name>], it spawns the named agent
        with its filtered tool set. Otherwise, uses the full tool registry.
        """
        # Clear any media a PRIOR job left undelivered (e.g. a direct cron that
        # generated an image but delivers 'local', so _deliver_cron_media never
        # ran). Jobs tick strictly sequentially (advisory-locked), so resetting
        # at entry guarantees this run's delivery can never inherit another
        # job's artifacts — which could target a different chat/tenant.
        self._pending_cron_media = []
        if prompt.startswith("[CURATOR]"):
            # Weekly skill-library maintenance (P4). Runs under the tenant
            # context the tick already set; metered/budgeted as a review.
            try:
                from api.services.learning_service import run_curator
                return await run_curator(cli=self._cli, db=self._db,
                                         app_id=app_id)
            except Exception as e:
                logger.warning("[Curator] run failed: %s", e)
                return f"Curator error: {e}"

        if prompt.startswith("[TOOL:"):
            # A cron whose whole job is "invoke one tool" needs NO LLM. Execute
            # the named tool directly — the same call the agent cron would make,
            # minus the ~20.5k-token prompt to have the model decide to make it.
            return await self._run_tool_cron(prompt, app_id=app_id)

        if prompt.startswith("[AGENT:"):
            return await self._run_agent_cron(prompt, app_id=app_id)

        from core.agent_loop import AgentLoop
        from core.user_context import create_cron_user
        from core.workspace_manager import WorkspaceManager
        from async_bus.event_bus import EventBus

        from core.tenant_context import current_tenant
        ws_manager = WorkspaceManager(tenant_id=current_tenant().tenant_key)
        cron_workspace = ws_manager.ensure_workspace(0)
        cron_user_ctx = create_cron_user(app_id=app_id)
        cron_tools = self._cli.create_user_tools(
            cron_workspace, sandboxed=True
        )

        # Crons resolve by their owning app: an app bound to a profile runs
        # its jobs on that model, and app/tenant budgets cap runaway jobs.
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
                app_id=app_id, run_kind="cron",
                profile_id=(_profile or {}).get("profile_id"))
            _budget_check = _scope.make_budget_check(app_id=app_id)
        except Exception as e:
            logger.debug("[Cron] llm scope unavailable — legacy client (%s)", e)

        # [SYSTEM] crons are PLATFORM INFRASTRUCTURE (brain_sync, etc.), not an
        # app agent doing a user task — the same category as [CURATOR]/[AGENT:].
        # They run with the full toolset and NO app persona; narrowing a
        # persona's whitelist must never silently disable brain-sync. Only user
        # automations are persona-governed.
        #
        # For those: the cron runs under its assigned persona (job.persona_id)
        # or, when unset, the app default — identity, guardrails, tool whitelist
        # and DLP all apply. Approval is deliberately NOT wired: crons are
        # headless, so the persona's whitelist + guardrails ARE the boundary; an
        # interactive HITL prompt would hang with no one to answer it.
        is_system = prompt.startswith("[SYSTEM]")
        if is_system:
            cron_registry = cron_tools
            _prompt_overrides, _guardrail, _picker = {}, None, None
        else:
            from api.services.persona_applicator import apply_persona
            _ap = apply_persona(
                self._cli, self._db,
                base_registry=cron_tools, user_ctx=cron_user_ctx,
                app_id=app_id, persona_id=persona_id)
            cron_registry = _ap.tool_registry
            _prompt_overrides = _ap.prompt_overrides
            _guardrail = _ap.guardrail_engine
            _picker = _ap.dynamic_picker

        cron_bus = EventBus()
        cron_agent = AgentLoop(
            cron_workspace,
            llm_client,
            cron_registry,
            cron_bus,
            transcript_logger=self._cli.logger,
            memory_manager=self._cli.memory,
            user_context=cron_user_ctx,
            db=self._db,
            usage_sink=_usage_sink,
            budget_check=_budget_check,
            prompt_overrides=_prompt_overrides,
            guardrail_engine=_guardrail,
            dynamic_picker=_picker,
        )

        response_text = None
        response_event = asyncio.Event()
        _cron_artifacts = []

        async def capture(payload):
            nonlocal response_text
            response_text = payload.get("message", "")
            response_event.set()

        async def _capture_artifact(payload):
            fid = payload.get("file_id")
            if fid is not None:
                _cron_artifacts.append(fid)

        cron_bus.subscribe('agent_response', capture)
        cron_bus.subscribe('artifact', _capture_artifact)

        try:
            await cron_agent._process_input({"user_input": prompt})
            await asyncio.wait_for(response_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            response_text = "⏰ Cron job timed out after 5 minutes."
        finally:
            cron_bus.unsubscribe('agent_response', capture)
            cron_bus.unsubscribe('artifact', _capture_artifact)
        # Hand any model-generated media to the delivery step (platform targets).
        self._pending_cron_media = _cron_artifacts

        # Learning hook: user-automation crons learn too (the direct-AgentLoop
        # path). [SYSTEM] infrastructure runs (brain_sync) are exempt — they are
        # not tasks a future session should learn a "skill" from.
        if not is_system:
            try:
                from api.services.learning_service import maybe_review
                maybe_review(
                    agent=cron_agent, cli=self._cli, db=self._db,
                    conversation_id=f"cron:direct:{id(cron_agent)}",
                    app_id=app_id,
                )
            except Exception:
                logger.debug("[Cron] direct learning hook failed", exc_info=True)

        return response_text or "(No output)"

    async def _run_tool_cron(self, prompt: str, app_id=None) -> str:
        """Execute ONE tool directly from a cron — no LLM, no agent loop.

        Prompt format: ``[TOOL:<tool_name>] <optional JSON args>``. The tool a
        cron runs is DATA in the cron row, never code here. It uses the SAME
        sandboxed registry + LocalToolExecutor the agent cron would, so the tool
        resolves its subsystems and tenant scope identically — we only remove
        the ~20.5k-token prompt whose sole purpose was to make the model decide
        to call this one deterministic tool.

        Grants NO new capability: only tools already in the sandboxed cron
        registry are reachable — exactly what the agent cron could call.
        """
        name, args_or_err = parse_tool_cron_marker(prompt)
        if name is None:
            return args_or_err  # error string
        args = args_or_err

        from core.user_context import current_user_context, create_cron_user
        from core.workspace_manager import WorkspaceManager
        from core.tenant_context import current_tenant
        from core.tool_executor import LocalToolExecutor

        # Same workspace + sandboxed registry the agent cron builds; the tenant
        # context is already bound by the tick.
        ws_manager = WorkspaceManager(tenant_id=current_tenant().tenant_key)
        cron_workspace = ws_manager.ensure_workspace(0)
        cron_user_ctx = create_cron_user(app_id=app_id)
        registry = self._cli.create_user_tools(cron_workspace, sandboxed=True)

        if name not in getattr(registry, "_tools", {}):
            return (f"✗ [TOOL:{name}] unknown tool — not in this cron's "
                    f"registry. Check the tool name.")

        _tok = current_user_context.set(cron_user_ctx)
        try:
            result = await LocalToolExecutor(registry).execute(name, args)
        except Exception as e:
            logger.warning("[Tool] cron '%s' failed: %s", name, e)
            result = f"✗ [TOOL:{name}] execution error: {e}"
        finally:
            current_user_context.reset(_tok)

        logger.info("[Tool] cron executed %s (app_id=%s) → %d chars",
                    name, app_id, len(result or ""))
        try:
            from core.telemetry import telemetry
            telemetry.incr("tool_cron_executed_total", tool=name)
        except Exception:
            pass
        return result or "(No output)"

    async def _run_agent_cron(self, prompt: str, app_id=None) -> str:
        """Run a dynamic agent via cron. Prompt format: [AGENT:<name>] <task>

        ``app_id`` (the cron job's owning app) is passed to the factory so the
        spawned agent authenticates with that app's connections.
        """
        try:
            agent_name = prompt.split("]")[0].replace("[AGENT:", "").strip()
            task = prompt.split("]", 1)[1].strip() if "]" in prompt else ""

            from agents.registry import AgentRegistry
            from agents.factory import AgentFactory

            registry = AgentRegistry(self._db)
            factory = AgentFactory(self._cli, registry)

            agent_def = registry.load(agent_name)
            if not agent_def:
                return f"✗ Agent '{agent_name}' not found."

            # Attach the scope so the factory can meter/budget this run —
            # the gateway has no chat_service to do it.
            from api.services.llm_scope import attach_scope
            attach_scope(self._cli)
            from api.services.skill_service import attach_skills
            attach_skills(self._cli)
            try:
                run_result = await factory.run_agent(
                    agent_def, task_prompt=task or None, app_id=app_id,
                    run_kind="cron")
            except TypeError:
                # Older engine without the run_kind kwarg (deploy-order
                # safety, 07-02 lesson: never let a call-contract change
                # break a mid-deploy prod).
                run_result = await factory.run_agent(
                    agent_def, task_prompt=task or None, app_id=app_id)

            # Learning hook: cron agents learn too (the factory path).
            # RunResult carries pre-collected signals + digest — pass them
            # directly, no coupling to the engine's AgentLoop.
            if run_result.run_kind != "review":
                try:
                    from api.services.learning_service import maybe_review
                    maybe_review(
                        review_signals=run_result.review_signals,
                        conversation_digest=run_result.conversation_digest,
                        cli=self._cli, db=self._db,
                        conversation_id=f"cron:{agent_name}:{id(run_result)}",
                        app_id=app_id,
                    )
                except Exception:
                    logger.debug("[Cron] factory learning hook failed",
                                 exc_info=True)

            return run_result.output
        except Exception as e:
            logger.error("[Cron] Agent run failed: %s", e, exc_info=True)
            return f"✗ Agent cron error: {str(e)}"
    
    async def _deliver_cron_result(self, job: dict, content: str):
        """Deliver cron job result to the appropriate platform.
        
        Delivery strategy (user requested "both"):
        - Always saved locally (done by scheduler)
        - Also send to Telegram if adapter is available
        """
        deliver = job.get("deliver", "local")
        
        if deliver == "local":
            return
        
        origin = job.get("origin")
        target_platform = None
        target_chat_id = None
        
        if deliver == "origin" and isinstance(origin, dict):
            target_platform = origin.get("platform")
            target_chat_id = origin.get("chat_id")
        elif ":" in deliver:
            target_platform, target_chat_id = deliver.split(":", 1)
        elif deliver in ("telegram",):
            target_platform = deliver
            from core.config import app_config
            target_chat_id = app_config.resolve_env("TELEGRAM_HOME_CHANNEL", "").strip()
        
        if not target_platform or not target_chat_id:
            logger.warning("[Cron] No delivery target for job '%s'", job.get("id"))
            return

        job_name = job.get("name", job.get("id", "?"))
        message = f"📋 **Cron: {job_name}**\n{'─' * 30}\n\n" + content

        for adapter in self._adapters:
            if adapter.platform_name == target_platform:
                try:
                    await adapter.send(target_chat_id, message)
                    await self._deliver_cron_media(adapter, target_chat_id)
                    return
                except Exception as e:
                    logger.warning("[Cron] Send failed (%s) — queueing to outbox", e)
                    self._outbox.enqueue(target_platform, target_chat_id,
                                         message, last_error=str(e))
                    return

        logger.warning("[Cron] No adapter for platform '%s' — queueing to outbox",
                       target_platform)
        self._outbox.enqueue(target_platform, target_chat_id, message,
                             last_error="no adapter available")

    async def _deliver_cron_media(self, adapter, chat_id: str):
        """Deliver media a cron job generated (Part 2) via the target platform."""
        media = getattr(self, "_pending_cron_media", None) or []
        self._pending_cron_media = []
        if not media:
            return
        from core.file_record import load_file
        for fid in media:
            try:
                f = load_file(self._db, fid)
                if f:
                    await adapter.send_media(chat_id, f["bytes"], f["kind"],
                                             f.get("mime_type") or "",
                                             f.get("filename") or "file")
            except Exception as e:
                logger.debug("[Cron] media delivery failed: %s", e)

    async def _outbox_send(self, platform: str, chat_id: str,
                           content: str, thread_id: str = None) -> bool:
        """Retry callback for DeliveryOutbox.flush — True on success."""
        for adapter in self._adapters:
            if adapter.platform_name == platform:
                await adapter.send(chat_id, content, thread_id)
                return True
        return False


from cron.jobs import create_job, list_jobs
