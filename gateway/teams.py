"""
Microsoft Teams platform adapter for Agent.
Handles incoming webhook activities from Azure Bot Service.
"""

import logging
import asyncio
import os

TEAMS_WORKER_PORT = int(os.environ.get("AG_TEAMS_WORKER_PORT", "8115"))
from typing import Optional, Dict

from gateway.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult, CardContent

logger = logging.getLogger(__name__)

try:
    from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext, MessageFactory
    from botbuilder.schema import Activity, ActivityTypes, ConversationReference
    BOTBUILDER_AVAILABLE = True
except ImportError:
    BOTBUILDER_AVAILABLE = False
    
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from botbuilder.schema import Activity
    from botbuilder.core import TurnContext


class TeamsAdapter(BasePlatformAdapter):
    """Teams bot adapter using Bot Framework webhooks.
    
    Responsibilities:
    - Receive incoming webhook activities from Azure Bot Service
    - Parse message events and dispatch to the Gateway
    - Send replies back to conversations (reactive messaging)
    
    Note: Proactive messaging (send DMs, post to channels) is handled by
    tools/teams_messaging.py — a standalone tool module using sync REST API
    calls, following the same architecture as Microsoft365Tools and OutlookActionTools.
    """
    
    def __init__(self, credential_registry=None):
        super().__init__("teams")

        if not BOTBUILDER_AVAILABLE:
            raise ImportError(
                "botbuilder-core not installed. "
                "Install: pip install botbuilder-core"
            )

        self._registry = credential_registry

        self._bf_adapters: Dict[str, "BotFrameworkAdapter"] = {}

        self._conversation_refs: Dict[str, dict] = {}
        self._ref_app: Dict[str, str] = {}

    def _resolve_bot(self):
        """Resolve the current tenant's Teams bot credentials from the vault.

        Reads under whatever tenant context is bound on the calling task. Returns
        (app_id, app_password, tenant_id) or None if this tenant has no m365 app.
        """
        if not self._registry:
            return None
        try:
            cred = self._registry.resolve("m365")
            app_id = (cred.config.get("client_id") or "").strip()
            app_password = (cred.secret or "").strip()
            tenant_id = (cred.config.get("tenant_id") or "").strip()
            if app_id and app_password:
                return app_id, app_password, tenant_id
        except Exception as e:
            logger.debug("teams.bot_resolve_failed: %s", e)
        return None

    def _bf_adapter_for(self, app_id: str, app_password: str, tenant_id: str) -> "BotFrameworkAdapter":
        """Get-or-build the BotFrameworkAdapter for a given bot app_id (cached)."""
        existing = self._bf_adapters.get(app_id)
        if existing is not None:
            return existing
        settings = BotFrameworkAdapterSettings(
            app_id=app_id,
            app_password=app_password,
            channel_auth_tenant=tenant_id or None,
        )
        adapter = BotFrameworkAdapter(settings)
        self._bf_adapters[app_id] = adapter
        return adapter

    def _bot_for_chat(self, chat_id: str):
        """Return (bf_adapter, app_id) to reply on a chat.

        Uses the exact bot that received the chat (cached in _ref_app during the
        incoming turn). If unknown — e.g. a proactive reply in a fresh process —
        resolve from the currently bound tenant. Never the control DB.
        """
        app_id = self._ref_app.get(chat_id, "")
        if app_id and app_id in self._bf_adapters:
            return self._bf_adapters[app_id], app_id
        bot = self._resolve_bot()
        if not bot:
            return None, ""
        aid, pw, tid = bot
        return self._bf_adapter_for(aid, pw, tid), aid

    def _bind_tenant(self, tenant_domain: str):
        """Resolve X-Tenant-Domain → tenant and bind TenantContext for this turn.
        Returns a reset token (or None). Best-effort; never raises."""
        dom = (tenant_domain or "").split(":")[0].strip().lower()
        if not dom or dom in ("localhost", "127.0.0.1", "::1"):
            return None
        try:
            from core.tenant_context import set_tenant_context, TenantContext, multi_tenant_enabled
            if not multi_tenant_enabled():
                return None
            if getattr(self, "_msystem_router", None) is None:
                from core.msystem_router import MSystemRouter
                self._msystem_router = MSystemRouter()
            identity = self._msystem_router.resolve(dom)
            if not identity or not identity.is_active:
                logger.info("[Teams] tenant unresolved/inactive for X-Tenant-Domain=%s — default ctx", dom)
                return None
            token = set_tenant_context(TenantContext(
                tenant_id=identity.tenant_id, tenant_key=identity.tenant_key,
                display_name=identity.display_name, tenant_domain=dom, is_default=False,
            ))
            logger.info("[Teams] bound tenant=%s (%s) from X-Tenant-Domain", identity.tenant_key, dom)
            return token
        except Exception as e:
            logger.warning("[Teams] tenant bind failed for %s: %s", dom, e)
            return None

    def _unbind_tenant(self, token) -> None:
        if token is None:
            return
        try:
            from core.tenant_context import reset_tenant_context
            reset_tenant_context(token)
        except Exception:
            pass

    async def start(self):
        """Start Teams adapter aiohttp webhook server."""
        from aiohttp import web
        
        async def handle_webhook(req: web.Request):
            if "application/json" in req.headers.get("Content-Type", ""):
                body = await req.json()
            else:
                return web.Response(status=415)
                
            activity = Activity().deserialize(body)
            
            if not activity or not activity.type:
                logger.info("[Teams] Received empty or typeless activity (likely Azure validation). Returning 200 OK.")
                return web.Response(status=200)
                
            auth_header = req.headers.get("Authorization", "")

            tenant_domain = req.headers.get("X-Tenant-Domain", "") or ""
            ctx_token = self._bind_tenant(tenant_domain)
            try:
                await self.process_activity(activity, auth_header)
                return web.Response(status=200)
            except Exception as e:
                logger.error("[Teams] Webhook error: %s", e)
                return web.Response(status=500)
            finally:
                self._unbind_tenant(ctx_token)
                
        app = web.Application()
        app.router.add_post('/api/webhook/teams', handle_webhook)
        
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '127.0.0.1', TEAMS_WORKER_PORT)
        await self.site.start()

        logger.info("[Teams] Webhook listener up on 127.0.0.1:%s (per-tenant bot credentials)", TEAMS_WORKER_PORT)

    async def stop(self):
        logger.info("[Teams] Bot adapter stopped")
        if hasattr(self, 'runner') and self.runner:
            await self.runner.cleanup()

    async def process_activity(self, activity: 'Activity', auth_header: str):
        """Called by the FastAPI webhook router when an activity arrives.

        Resolves the bot for the CURRENTLY BOUND tenant (set by handle_webhook
        from X-Tenant-Domain), so auth validation and replies use that tenant's
        own bot — never a startup default.
        """
        bot = self._resolve_bot()
        if not bot:
            logger.error("[Teams] No m365 bot configured for the active tenant — "
                         "cannot process activity. Configure the org M365 app for this tenant.")
            return
        app_id, app_password, tenant_id = bot
        bf_adapter = self._bf_adapter_for(app_id, app_password, tenant_id)

        async def logic(turn_context: 'TurnContext'):
            return await self._handle_turn(turn_context, app_id)

        try:
            return await bf_adapter.process_activity(activity, auth_header, logic)
        except Exception as e:
            logger.error("[Teams] Error processing activity: %s", e)
            raise

    async def _handle_turn(self, turn_context: 'TurnContext', app_id: str = ""):
        """Handle the TurnContext logic inside the adapter.

        app_id is the bot that received this activity — recorded against the
        conversation so proactive replies use the same per-tenant bot.
        """
        activity = turn_context.activity
        
        if activity.type != ActivityTypes.message:
            return
            
        text = TurnContext.remove_recipient_mention(activity)
        if not text:
            text = activity.text
        text = text.strip() if text else ""

        if not text and getattr(activity, "value", None):
            val = activity.value if isinstance(activity.value, dict) else {}
            if val.get("ag_action") == "approval":
                text = "yes" if val.get("decision") == "approve" else "no"

        # Part 1 ingress — accept a message that carries only media (no text).
        _tc_attachments = self._extract_attachments(getattr(activity, "attachments", None))
        if not text and not _tc_attachments:
            return
            
        user_id = activity.from_property.id
        user_name = activity.from_property.name
        chat_id = activity.conversation.id
        
        aad_object_id = getattr(activity.from_property, 'aad_object_id', None) or ""
        
        user_email = ""
        if hasattr(activity.from_property, 'properties') and activity.from_property.properties:
            user_email = activity.from_property.properties.get('upn', '') or \
                         activity.from_property.properties.get('email', '')
        if not user_email and activity.channel_data:
            channel_data = activity.channel_data if isinstance(activity.channel_data, dict) else {}
            user_email = channel_data.get('user_email', '') or \
                         channel_data.get('userPrincipalName', '')

        if not user_email:
            try:
                from botbuilder.core.teams import TeamsInfo
                member = await TeamsInfo.get_member(turn_context, user_id)
                if member:
                    user_email = getattr(member, 'user_principal_name', '') or getattr(member, 'email', '')
                    if user_email:
                        logger.info("[Teams] Fetched email %s via TeamsInfo for user %s", user_email, user_id)
            except Exception as e:
                logger.warning("[Teams] Failed to fetch member info via TeamsInfo: %s", e)
                
        bot = self._resolve_bot() if (not user_email and aad_object_id) else None
        if bot:
            try:
                import requests
                app_id, app_password, tenant_id = bot
                token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
                payload = {
                    "client_id": app_id,
                    "client_secret": app_password,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                }
                resp = requests.post(token_url, data=payload, timeout=5)
                if resp.status_code == 200:
                    token = resp.json().get("access_token")
                    graph_url = f"https://graph.microsoft.com/v1.0/users/{aad_object_id}?$select=mail,userPrincipalName"
                    graph_resp = requests.get(graph_url, headers={"Authorization": f"Bearer {token}"}, timeout=5)
                    if graph_resp.status_code == 200:
                        user_data = graph_resp.json()
                        user_email = user_data.get("userPrincipalName", "") or user_data.get("mail", "")
                        if user_email:
                            logger.info("[Teams] Fetched email %s via Graph API for aad_object_id %s", user_email, aad_object_id)
            except Exception as e:
                logger.error("[Teams] Failed to fetch email via Graph API: %s", e)
        
        logger.info("[Teams] Message from %s (email=%s, aad=%s, chat=%s): %s",
                     user_name, user_email or "?", aad_object_id[:8] if aad_object_id else "?",
                     chat_id[:20], text[:80])
        
        ref = TurnContext.get_conversation_reference(activity)
        self._conversation_refs[chat_id] = ref.as_dict()
        self._ref_app[chat_id] = app_id or ""
        
        event = MessageEvent(
            platform="teams",
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
            text=text,
            thread_id=None,
            message_type=MessageType.TEXT,
            raw=activity.as_dict(),
            email=user_email or None,
            attachments=_tc_attachments or None,
        )
        
        from core.tenant_context import current_tenant, set_tenant_context, reset_tenant_context
        _captured_ctx = current_tenant()

        async def _run_dispatch(ev=event, cctx=_captured_ctx):
            tok = set_tenant_context(cctx)
            try:
                await self._dispatch_message(ev)
            finally:
                reset_tenant_context(tok)

        asyncio.create_task(_run_dispatch())

    def _extract_attachments(self, attachments) -> list:
        """Best-effort ingress: download inline IMAGE attachments Teams provides
        with a fetchable contentUrl (or a data: URI). File uploads that need an
        auth'd Graph download are a follow-up; anything unsupported is skipped so
        the turn is never broken."""
        if not attachments:
            return []
        import base64
        import requests
        from core.file_store import downscale_image
        out = []
        for att in attachments:
            is_dict = isinstance(att, dict)
            ct = (att.get("contentType") if is_dict else getattr(att, "content_type", None)) or ""
            url = att.get("contentUrl") if is_dict else getattr(att, "content_url", None)
            name = (att.get("name") if is_dict else getattr(att, "name", None)) or "image"
            if not url or not ct.startswith("image/"):
                continue
            try:
                if url.startswith("data:"):
                    data = base64.b64decode(url.split(",", 1)[1])
                else:
                    r = requests.get(url, timeout=10)
                    r.raise_for_status()
                    data = r.content
                data = downscale_image(data)
                out.append({"kind": "image", "media_type": ct or "image/png",
                            "data_b64": base64.b64encode(data).decode("ascii"),
                            "filename": name})
            except Exception as e:
                logger.debug("[Teams] attachment download skipped: %s", e)
        return out

    async def send_media(self, chat_id: str, data: bytes, kind: str,
                         media_type: str = "", filename: str = "file",
                         thread_id: Optional[str] = None) -> SendResult:
        """Deliver model-generated media to Teams as an inline attachment."""
        if chat_id not in self._conversation_refs:
            return SendResult(success=False, error="Conversation reference not found")
        try:
            import base64
            from botbuilder.schema import Attachment
            ref_dict = self._conversation_refs[chat_id]
            reference = ConversationReference().deserialize(ref_dict)
            if not reference.service_url:
                reference.service_url = ref_dict.get("service_url") or ref_dict.get("serviceUrl")
            bf_adapter, app_id = self._bot_for_chat(chat_id)
            if not bf_adapter:
                return SendResult(success=False, error="No bot configured for tenant")
            from botframework.connector.auth import MicrosoftAppCredentials
            if reference.service_url:
                MicrosoftAppCredentials.trust_service_url(reference.service_url)
            mt = media_type or ("image/png" if kind == "image" else "application/octet-stream")
            b64 = base64.b64encode(data).decode("ascii")

            async def send_logic(turn_context: TurnContext):
                att = Attachment(content_type=mt,
                                 content_url=f"data:{mt};base64,{b64}",
                                 name=filename or "file")
                await turn_context.send_activity(MessageFactory.attachment(att))

            await bf_adapter.continue_conversation(reference, send_logic, app_id)
            return SendResult(success=True)
        except Exception as e:
            logger.error("[Teams] send_media failed to %s: %s", chat_id, e)
            return SendResult(success=False, error=str(e))

    async def send(self, chat_id: str, text: str, thread_id: Optional[str] = None) -> SendResult:
        """Send a reply message to a Teams chat/channel."""
        if chat_id not in self._conversation_refs:
            logger.error("[Teams] Cannot send to %s: Conversation reference not found.", chat_id)
            return SendResult(success=False, error="Conversation reference not found")
            
        ref_dict = self._conversation_refs[chat_id]
        
        try:
            reference = ConversationReference().deserialize(ref_dict)
            
            if not reference.service_url and "service_url" in ref_dict:
                reference.service_url = ref_dict["service_url"]
            elif not reference.service_url and "serviceUrl" in ref_dict:
                reference.service_url = ref_dict["serviceUrl"]
            
            bf_adapter, app_id = self._bot_for_chat(chat_id)
            if not bf_adapter:
                logger.error("[Teams] No bot configured to reply to %s", chat_id)
                return SendResult(success=False, error="No bot configured for tenant")

            from botframework.connector.auth import MicrosoftAppCredentials
            if reference.service_url:
                MicrosoftAppCredentials.trust_service_url(reference.service_url)

            async def send_logic(turn_context: TurnContext):
                message = MessageFactory.text(text)
                message.text_format = "markdown"
                await turn_context.send_activity(message)

            await bf_adapter.continue_conversation(
                reference,
                send_logic,
                app_id
            )
            return SendResult(success=True)

        except Exception as e:
            logger.error("[Teams] Send failed to %s: %s", chat_id, e)
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str) -> None:
        """Send a Teams 'typing' activity so the user sees the bot is working.

        Best-effort and fire-and-forget: any failure is swallowed (a missing
        typing indicator must never break the actual turn). Teams shows the
        indicator for a few seconds, so the caller re-sends periodically during
        a long agent run.
        """
        ref_dict = self._conversation_refs.get(chat_id)
        if not ref_dict:
            return
        try:
            bf_adapter, app_id = self._bot_for_chat(chat_id)
            if not bf_adapter:
                return
            reference = ConversationReference().deserialize(ref_dict)
            if not reference.service_url:
                reference.service_url = ref_dict.get("service_url") or ref_dict.get("serviceUrl")
            if reference.service_url:
                from botframework.connector.auth import MicrosoftAppCredentials
                MicrosoftAppCredentials.trust_service_url(reference.service_url)

            async def typing_logic(turn_context: TurnContext):
                await turn_context.send_activity(Activity(type=ActivityTypes.typing))

            await bf_adapter.continue_conversation(
                reference, typing_logic, app_id
            )
        except Exception as e:
            logger.debug("[Teams] typing indicator failed for %s: %s", chat_id, e)


    async def send_card(self, chat_id: str, card: CardContent,
                        thread_id: Optional[str] = None) -> SendResult:
        """Send structured content as an Adaptive Card in Teams.

        Falls back to plain-text ``send()`` if the conversation reference is
        missing or if Adaptive Card construction fails for any reason.
        """
        if chat_id not in self._conversation_refs:
            return await self.send(chat_id, card.fallback_text, thread_id)

        try:
            if card.card_type == "plan":
                ac_json = self._build_plan_card(card)
            elif card.card_type == "citations":
                ac_json = self._build_citations_card(card)
            elif card.card_type == "approval":
                ac_json = self._build_approval_card(card)
            else:
                return await self.send(chat_id, card.fallback_text, thread_id)

            bf_adapter, app_id = self._bot_for_chat(chat_id)
            if not bf_adapter:
                return await self.send(chat_id, card.fallback_text, thread_id)

            ref_dict = self._conversation_refs[chat_id]
            reference = ConversationReference().deserialize(ref_dict)
            if not reference.service_url and "service_url" in ref_dict:
                reference.service_url = ref_dict["service_url"]
            elif not reference.service_url and "serviceUrl" in ref_dict:
                reference.service_url = ref_dict["serviceUrl"]

            from botframework.connector.auth import MicrosoftAppCredentials
            if reference.service_url:
                MicrosoftAppCredentials.trust_service_url(reference.service_url)

            from botbuilder.schema import Attachment

            async def send_logic(turn_context: TurnContext):
                attachment = Attachment(
                    content_type="application/vnd.microsoft.card.adaptive",
                    content=ac_json,
                )
                activity = MessageFactory.attachment(attachment)
                await turn_context.send_activity(activity)

            await bf_adapter.continue_conversation(
                reference, send_logic, app_id
            )
            return SendResult(success=True)

        except Exception as e:
            logger.warning("[Teams] Adaptive Card send failed (%s) — falling back to text", e)
            return await self.send(chat_id, card.fallback_text, thread_id)


    @staticmethod
    def _header_block(emoji: str, title: str, subtitle: str = "",
                      accent: str = "Accent", style: str = "emphasis") -> dict:
        """A styled header strip: icon + bold coloured title (+ optional subtitle)."""
        col_items = [{
            "type": "TextBlock", "text": f"{title}", "weight": "Bolder",
            "size": "Medium", "color": accent, "wrap": True, "spacing": "None",
        }]
        if subtitle:
            col_items.append({
                "type": "TextBlock", "text": subtitle, "isSubtle": True,
                "size": "Small", "wrap": True, "spacing": "None",
            })
        return {
            "type": "Container", "style": style, "bleed": True,
            "items": [{
                "type": "ColumnSet", "columns": [
                    {"type": "Column", "width": "auto", "verticalContentAlignment": "Center",
                     "items": [{"type": "TextBlock", "text": emoji, "size": "Large", "spacing": "None"}]},
                    {"type": "Column", "width": "stretch", "verticalContentAlignment": "Center",
                     "items": col_items},
                ],
            }],
        }

    @staticmethod
    def _build_approval_card(card: CardContent) -> dict:
        """Adaptive Card for a human-in-the-loop approval (Approve / Deny buttons).

        card.data carries: approval_id, tool, args, timeout_min.
        Button clicks come back as Action.Submit ``value`` and are handled in
        ``_handle_turn`` (mapped to a yes/no decision).
        """
        data = card.data or {}
        approval_id = data.get("approval_id", "")
        tool = data.get("tool", "action")
        args = str(data.get("args", ""))
        timeout_min = data.get("timeout_min")
        if len(args) > 500:
            args = args[:500] + "…"

        body = [
            TeamsAdapter._header_block(
                "⚠️", card.title or "Approval required",
                "The agent wants to run an irreversible action.",
                accent="Warning", style="warning"),
            {"type": "FactSet", "spacing": "Medium", "facts": [
                {"title": "Tool", "value": tool},
            ]},
        ]
        if args:
            body.append({"type": "Container", "style": "emphasis", "spacing": "Small",
                         "items": [{"type": "TextBlock", "text": args, "wrap": True,
                                    "fontType": "Monospace", "size": "Small", "isSubtle": True}]})
        if timeout_min:
            body.append({"type": "TextBlock", "wrap": True, "isSubtle": True,
                         "spacing": "Small", "size": "Small",
                         "text": f"⏱ Auto-denied in {timeout_min} min if no response."})

        return {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": body,
            "actions": [
                {"type": "Action.Submit", "title": "✅ Approve", "style": "positive",
                 "data": {"ag_action": "approval", "approval_id": approval_id, "decision": "approve"}},
                {"type": "Action.Submit", "title": "❌ Deny", "style": "destructive",
                 "data": {"ag_action": "approval", "approval_id": approval_id, "decision": "deny"}},
            ],
        }

    @staticmethod
    def _build_plan_card(card: CardContent) -> dict:
        """Adaptive Card for a plan (task list) — numbered steps in a styled card."""
        steps = list(card.items or [])
        body: list = [
            TeamsAdapter._header_block(
                "🗺️", card.title or "Plan",
                f"{len(steps)} step{'s' if len(steps) != 1 else ''}"),
        ]

        rows = []
        for idx, step in enumerate(steps, 1):
            step_text = step if isinstance(step, str) else str(step)
            rows.append({
                "type": "ColumnSet",
                "spacing": "Small",
                "columns": [
                    {
                        "type": "Column", "width": "auto",
                        "items": [{
                            "type": "TextBlock", "text": f"{idx}", "weight": "Bolder",
                            "color": "Accent", "horizontalAlignment": "Center", "wrap": False,
                        }],
                    },
                    {
                        "type": "Column", "width": "stretch",
                        "items": [{"type": "TextBlock", "text": step_text, "wrap": True}],
                    },
                ],
            })
        body.append({"type": "Container", "spacing": "Medium", "items": rows})

        return {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": body,
        }

    @staticmethod
    def _build_citations_card(card: CardContent) -> dict:
        """Adaptive Card for brain citations — each source a styled row + snippet."""
        srcs = list(card.items or [])
        body: list = [
            TeamsAdapter._header_block(
                "📚", card.title or "Sources",
                f"{min(len(srcs), 8)} reference{'s' if min(len(srcs), 8) != 1 else ''}"),
        ]

        for src in srcs[:8]:
            title = src.get("title", "Untitled") if isinstance(src, dict) else str(src)
            doc_type = src.get("type", "") if isinstance(src, dict) else ""
            snippet = src.get("snippet", "") if isinstance(src, dict) else ""

            header = f"📄 **{title}**"
            if doc_type:
                header += f"  _({doc_type})_"

            items = [{
                "type": "TextBlock", "text": header, "wrap": True, "spacing": "Small",
            }]
            if snippet:
                items.append({
                    "type": "TextBlock", "text": snippet[:300], "wrap": True,
                    "isSubtle": True, "size": "Small", "spacing": "None",
                })

            body.append({
                "type": "Container", "spacing": "Small", "items": items, "separator": True,
            })

        return {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": body,
        }

