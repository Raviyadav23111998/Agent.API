"""
Telegram platform adapter for Agent.

Distilled from Hermes gateway/platforms/telegram.py (3,745 lines → ~200 lines).
Uses python-telegram-bot library for polling-based message handling.

Env vars:
    TELEGRAM_BOT_TOKEN:     Required. Your bot token from @BotFather.
    TELEGRAM_ALLOWED_USERS: Optional. Comma-separated user IDs. Empty = allow all.
"""

import asyncio
import logging
from typing import Optional, Dict, Any

from gateway.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult, CardContent

logger = logging.getLogger(__name__)

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application,
        MessageHandler as TGMessageHandler,
        CallbackQueryHandler,
        ContextTypes,
        filters,
    )
    from telegram.constants import ParseMode
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

MAX_MESSAGE_LENGTH = 4096


def _escape_markdown(text: str) -> str:
    """Minimal Markdown escaping for Telegram — only escape what breaks parsing."""
    return text


def _split_message(text: str, limit: int = MAX_MESSAGE_LENGTH) -> list:
    """Split a long message into chunks that fit Telegram's limit."""
    if len(text) <= limit:
        return [text]
    
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        
        split_at = text.rfind('\n', 0, limit)
        if split_at == -1 or split_at < limit // 2:
            split_at = limit
        
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip('\n')
    
    return chunks


class TelegramAdapter(BasePlatformAdapter):
    """Telegram bot adapter using long-polling.
    
    Receives text messages, routes them to the agent, sends responses back.
    
    Credential resolution order:
        1. CredentialRegistry (vault) — if credential_registry is provided
        2. app_config.resolve_env() — reads from ag_system.configs or ENV vars
    """
    
    def __init__(self, token: str = None, *, tenant_domain: str = "",
                 tenant_id: str = "", tenant_key: str = "", tenant_display: str = "",
                 owner_user_id: str = "", owner_email: str = "", owner_name: str = "",
                 credential_registry=None):
        super().__init__("telegram")

        if not TELEGRAM_AVAILABLE:
            raise ImportError(
                "python-telegram-bot not installed. "
                "Install: pip install python-telegram-bot"
            )

        self.tenant_domain = tenant_domain
        self.tenant_id = tenant_id
        self.tenant_key = tenant_key
        self.tenant_display = tenant_display or tenant_key
        self.owner_user_id = owner_user_id
        self.owner_email = owner_email
        self.owner_name = owner_name or "Telegram user"
        self.per_user = bool(owner_user_id or owner_email)
        self._msystem_router = None

        self.token = (token or "").strip()
        allowed_csv = ""

        if not self.token and credential_registry:
            try:
                cred = credential_registry.resolve("telegram")
                self.token = (cred.secret or "").strip()
                allowed_csv = cred.config.get("allowed_users", "")
            except Exception as e:
                logger.debug("telegram.vault_fallback: %s", e)
        if not self.token:
            from core.config import app_config
            self.token = app_config.resolve_env("TELEGRAM_BOT_TOKEN", "").strip()
            allowed_csv = allowed_csv or app_config.resolve_env("TELEGRAM_ALLOWED_USERS", "").strip()

        if not self.token:
            raise ValueError("Telegram bot token not configured.")

        self._allowed_users = ({uid.strip() for uid in str(allowed_csv).split(",") if uid.strip()}
                               if allowed_csv else None)
        self._app: Optional[Application] = None
        self._bot_info: Optional[Dict] = None

    def _bind_tenant(self):
        """Bind THIS bot's tenant for the duration of one message.

        contextvars don't propagate across the polling library's own tasks, so
        the context must be (re)set inside each handler. We bind the identity the
        manager already resolved (tenant_id/key) — exactly like the cron fan-out
        — instead of re-resolving a domain, which can be blank for a tenant.
        Falls back to a domain lookup only for a legacy bot configured without a
        resolved identity.
        """
        try:
            from core.tenant_context import set_tenant_context, TenantContext, multi_tenant_enabled
            if not multi_tenant_enabled():
                return None
            if self.tenant_id:
                return set_tenant_context(TenantContext(
                    tenant_id=self.tenant_id, tenant_key=self.tenant_key,
                    display_name=self.tenant_display, tenant_domain=self.tenant_domain,
                    is_default=False))
            dom = (self.tenant_domain or "").split(":")[0].strip().lower()
            if not dom or dom in ("localhost", "127.0.0.1", "::1"):
                return None
            if self._msystem_router is None:
                from core.msystem_router import MSystemRouter
                self._msystem_router = MSystemRouter()
            identity = self._msystem_router.resolve(dom)
            if not identity or not identity.is_active:
                return None
            return set_tenant_context(TenantContext(
                tenant_id=identity.tenant_id, tenant_key=identity.tenant_key,
                display_name=identity.display_name, tenant_domain=dom, is_default=False))
        except Exception as e:
            logger.warning("[Telegram] tenant bind failed (tenant=%s): %s",
                           self.tenant_key or self.tenant_domain, e)
            return None

    def _unbind_tenant(self, token) -> None:
        if token is None:
            return
        try:
            from core.tenant_context import reset_tenant_context
            reset_tenant_context(token)
        except Exception:
            pass
    
    def _is_user_authorized(self, user_id: str) -> bool:
        """Check if a user is authorized to use the bot."""
        if self._allowed_users is None:
            return True
        return "*" in self._allowed_users or str(user_id) in self._allowed_users
    
    async def start(self):
        """Start Telegram polling."""
        logger.info("[Telegram] Starting bot...")
        
        self._app = (
            Application.builder()
            .token(self.token)
            .concurrent_updates(True)
            .build()
        )

        self._app.add_handler(
            TGMessageHandler(
                filters.TEXT & ~filters.COMMAND,
                self._handle_message
            )
        )
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))
        
        await self._app.initialize()
        
        me = await self._app.bot.get_me()
        self._bot_info = {"id": me.id, "username": me.username, "name": me.first_name}
        logger.info("[Telegram] Bot started: @%s (%s)", me.username, me.first_name)
        
        await self._app.start()
        await self._app.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
    
    async def stop(self):
        """Stop Telegram polling and clean up."""
        logger.info("[Telegram] Stopping bot...")
        if self._app:
            try:
                if self._app.updater and self._app.updater.running:
                    await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception as e:
                logger.warning("[Telegram] Error during shutdown: %s", e)
        logger.info("[Telegram] Bot stopped")
    
    async def send(self, chat_id: str, text: str,
                   thread_id: Optional[str] = None) -> SendResult:
        """Send a message to a Telegram chat."""
        if not self._app or not self._app.bot:
            return SendResult(success=False, error="Bot not initialized")
        
        try:
            chunks = _split_message(text)
            last_msg = None
            
            kwargs: Dict[str, Any] = {}
            if thread_id:
                kwargs["message_thread_id"] = int(thread_id)
            
            for chunk in chunks:
                try:
                    last_msg = await self._app.bot.send_message(
                        chat_id=int(chat_id),
                        text=chunk,
                        parse_mode=ParseMode.MARKDOWN,
                        **kwargs,
                    )
                except Exception:
                    last_msg = await self._app.bot.send_message(
                        chat_id=int(chat_id),
                        text=chunk,
                        **kwargs,
                    )
                
                if len(chunks) > 1:
                    await asyncio.sleep(0.3)
            
            return SendResult(
                success=True,
                message_id=str(last_msg.message_id) if last_msg else None
            )
        except Exception as e:
            logger.error("[Telegram] Send failed to %s: %s", chat_id, e)
            return SendResult(success=False, error=str(e))
    
    async def send_media(self, chat_id: str, data: bytes, kind: str,
                         media_type: str = "", filename: str = "file",
                         thread_id: Optional[str] = None) -> SendResult:
        """Deliver model-generated media as a native Telegram photo/audio/video/
        document."""
        import io
        try:
            bio = io.BytesIO(data)
            bio.name = filename or "file"
            kwargs = {"chat_id": chat_id}
            if thread_id:
                try:
                    kwargs["message_thread_id"] = int(thread_id)
                except (TypeError, ValueError):
                    pass
            if kind == "image":
                await self._app.bot.send_photo(photo=bio, **kwargs)
            elif kind == "audio":
                await self._app.bot.send_audio(audio=bio, **kwargs)
            elif kind == "video":
                await self._app.bot.send_video(video=bio, **kwargs)
            else:
                await self._app.bot.send_document(document=bio, **kwargs)
            return SendResult(success=True)
        except Exception as e:
            logger.warning("[Telegram] send_media failed: %s", e)
            return SendResult(success=False, error=str(e))

    async def _extract_attachments(self, message, context) -> list:
        """Download Telegram photo/document/voice/audio/video → hydrated
        attachments [{kind, media_type, data_b64, filename}]. Images are
        downscaled to stay under provider per-image limits."""
        import base64
        from core.file_store import downscale_image
        out = []

        async def _b64(file_id, image=False):
            f = await context.bot.get_file(file_id)
            data = bytes(await f.download_as_bytearray())
            if image:
                data = downscale_image(data)
            return base64.b64encode(data).decode("ascii")

        if message.photo:
            out.append({"kind": "image", "media_type": "image/jpeg",
                        "data_b64": await _b64(message.photo[-1].file_id, image=True),
                        "filename": "photo.jpg"})
        if message.document:
            d = message.document
            mt = d.mime_type or "application/octet-stream"
            kind = ("image" if mt.startswith("image/") else "audio" if mt.startswith("audio/")
                    else "video" if mt.startswith("video/") else "document")
            out.append({"kind": kind, "media_type": mt,
                        "data_b64": await _b64(d.file_id, image=kind == "image"),
                        "filename": d.file_name or "document"})
        if message.voice:
            out.append({"kind": "audio", "media_type": message.voice.mime_type or "audio/ogg",
                        "data_b64": await _b64(message.voice.file_id), "filename": "voice.ogg"})
        if message.audio:
            a = message.audio
            out.append({"kind": "audio", "media_type": a.mime_type or "audio/mpeg",
                        "data_b64": await _b64(a.file_id), "filename": a.file_name or "audio.mp3"})
        if message.video:
            out.append({"kind": "video", "media_type": message.video.mime_type or "video/mp4",
                        "data_b64": await _b64(message.video.file_id), "filename": "video.mp4"})
        return out

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming Telegram message (text and/or media)."""
        message = update.effective_message
        if not message:
            return
        _has_media = bool(message.photo or message.document or message.voice
                          or message.audio or message.video)
        _text = message.text or message.caption or ""
        if not _text and not _has_media:
            return

        tg_user = update.effective_user
        tg_user_id = str(tg_user.id) if tg_user else "unknown"
        chat_id = str(message.chat_id)

        if not self.per_user and not self._is_user_authorized(tg_user_id):
            logger.warning("[Telegram] Unauthorized user %s", tg_user_id)
            await message.reply_text("⛔ Not authorized. Contact the bot admin.")
            return

        thread_id = str(message.message_thread_id) if message.message_thread_id else None
        try:
            await message.chat.send_action("typing")
        except Exception:
            pass

        if self.per_user:
            identity_id = self.owner_user_id or tg_user_id
            identity_name = self.owner_name
            session_key = f"telegram:{self.owner_user_id}:{chat_id}"
        else:
            identity_id = tg_user_id
            identity_name = (tg_user.username or tg_user.first_name) if tg_user else "Unknown"
            session_key = None

        logger.info("[Telegram] Message on %s's bot (chat %s): %s%s",
                    self.owner_email or identity_id, chat_id, _text[:80],
                    " [+media]" if _has_media else "")

        token = self._bind_tenant()
        try:
            attachments = None
            if _has_media:
                try:
                    attachments = await self._extract_attachments(message, context)
                except Exception as exc:
                    logger.warning("[Telegram] attachment download failed: %s", exc)
            event = MessageEvent(
                platform="telegram",
                chat_id=chat_id,
                user_id=identity_id,
                user_name=identity_name,
                text=_text,
                thread_id=thread_id,
                message_type=MessageType.IMAGE if message.photo else MessageType.TEXT,
                raw=update,
                email=self.owner_email or None,
                source_adapter=self,
                session_key=session_key,
                attachments=attachments or None,
            )
            await self._dispatch_message(event)
        finally:
            self._unbind_tenant(token)


    async def _send_approval_card(self, chat_id: str, card: CardContent,
                                  thread_id: Optional[str] = None) -> SendResult:
        """Send the approval prompt with Approve / Deny inline buttons."""
        approval_id = (card.data or {}).get("approval_id", "")
        if not approval_id:
            return await self.send(chat_id, card.fallback_text, thread_id)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"appr:{approval_id}:y"),
            InlineKeyboardButton("❌ Deny", callback_data=f"appr:{approval_id}:n"),
        ]])
        kwargs: Dict[str, Any] = {"reply_markup": keyboard}
        if thread_id:
            kwargs["message_thread_id"] = int(thread_id)
        try:
            msg = await self._app.bot.send_message(
                chat_id=int(chat_id), text=card.fallback_text, **kwargs)
            return SendResult(success=True,
                              message_id=str(msg.message_id) if msg else None)
        except Exception as e:
            logger.error("[Telegram] approval card send failed to %s: %s", chat_id, e)
            return await self.send(chat_id, card.fallback_text, thread_id)

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Resolve a HITL approval from an inline-button tap.

        Runs concurrently with the turn that is blocked awaiting this decision
        (see concurrent_updates in start()), so tapping Approve/Deny unblocks the
        agent immediately. resolve_approval() sets the in-process Future the
        AgentLoop's ApprovalManager is waiting on."""
        query = update.callback_query
        if not query:
            return
        data = query.data or ""
        try:
            await query.answer()
        except Exception:
            pass
        if not data.startswith("appr:"):
            return
        parts = data.split(":")
        if len(parts) != 3:
            return
        _, approval_id, decision = parts
        approved = decision == "y"

        token = self._bind_tenant()
        try:
            from core.approvals import resolve_approval
            uid = int(self.owner_user_id) if (self.per_user and self.owner_user_id.isdigit()) else None
            ok = resolve_approval(approval_id, approved, user_id=uid)
        except Exception as e:
            logger.error("[Telegram] approval resolve failed (%s): %s", approval_id, e)
            ok = False
        finally:
            self._unbind_tenant(token)

        verdict = "✅ Approved" if approved else "❌ Denied"
        if not ok:
            verdict += " — but it already expired or was handled."
        try:
            await query.edit_message_text(
                text=f"{(query.message.text or '').split(chr(10))[0]}\n\n{verdict}")
        except Exception:
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass


    async def send_card(self, chat_id: str, card: CardContent,
                        thread_id: Optional[str] = None) -> SendResult:
        """Send structured content as an HTML-formatted Telegram message.

        Plan steps are rendered as a numbered list; citations show title,
        type, and snippet.  Falls back to the plain-text representation
        on any formatting or send failure.
        """
        if not self._app or not self._app.bot:
            return SendResult(success=False, error="Bot not initialized")

        if card.card_type == "approval":
            return await self._send_approval_card(chat_id, card, thread_id)

        try:
            if card.card_type == "plan":
                html = self._format_plan_html(card)
            elif card.card_type == "citations":
                html = self._format_citations_html(card)
            else:
                return await self.send(chat_id, card.fallback_text, thread_id)

            kwargs: Dict[str, Any] = {}
            if thread_id:
                kwargs["message_thread_id"] = int(thread_id)

            try:
                msg = await self._app.bot.send_message(
                    chat_id=int(chat_id),
                    text=html,
                    parse_mode=ParseMode.HTML,
                    **kwargs,
                )
                return SendResult(success=True,
                                  message_id=str(msg.message_id) if msg else None)
            except Exception:
                return await self.send(chat_id, card.fallback_text, thread_id)

        except Exception as e:
            logger.error("[Telegram] send_card failed to %s: %s", chat_id, e)
            return await self.send(chat_id, card.fallback_text, thread_id)

    @staticmethod
    def _html_escape(text: str) -> str:
        """Escape HTML special characters for Telegram HTML mode."""
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))

    @classmethod
    def _format_plan_html(cls, card: CardContent) -> str:
        """Render plan steps as a numbered HTML list."""
        lines = [f"<b>{cls._html_escape(card.title)}</b>\n"]
        for idx, step in enumerate(card.items, 1):
            step_text = step if isinstance(step, str) else str(step)
            lines.append(f"{idx}. {cls._html_escape(step_text)}")
        return "\n".join(lines)

    @classmethod
    def _format_citations_html(cls, card: CardContent) -> str:
        """Render citation sources as an HTML block with snippets."""
        lines = [f"<b>{cls._html_escape(card.title)}</b>\n"]
        for src in card.items[:8]:
            if isinstance(src, dict):
                title = src.get("title", "Untitled")
                doc_type = src.get("type", "")
                snippet = src.get("snippet", "")
            else:
                title, doc_type, snippet = str(src), "", ""

            header = f"📄 <b>{cls._html_escape(title)}</b>"
            if doc_type:
                header += f"  <i>({cls._html_escape(doc_type)})</i>"
            lines.append(header)

            if snippet:
                lines.append(f"<blockquote>{cls._html_escape(snippet[:300])}</blockquote>")
        return "\n".join(lines)


import hashlib


def _token_fingerprint(token: str) -> str:
    """Stable, non-reversible id for a bot token — used to detect rotation
    without ever logging or comparing the raw secret."""
    return hashlib.sha256((token or "").encode()).hexdigest()[:12]


class TelegramManager:
    """Owns the fleet of personal Telegram bots across every tenant.

    Each `telegram` connection in ag_cred (one per user via @BotFather) is one
    polling bot, running AS its owner inside the owner's tenant. A reconcile loop
    keeps the live fleet in sync with the connections table:

        • a new connection            → start a bot
        • a removed/disabled one      → stop its bot
        • a rotated token / changed   → restart the bot
          owner / tenant

    The manager is intentionally self-healing and side-effect-isolated: one bad
    token or one unreachable tenant never blocks the rest of the fleet, and a
    failure simply leaves that slot empty to be retried on the next cycle. This
    replaces the single env/vault global bot.
    """

    RECONCILE_INTERVAL = 60

    def __init__(self, connections, db, on_message, *,
                 msystem_router=None, reconcile_interval: int = RECONCILE_INTERVAL):
        self._connections = connections
        self._db = db
        self._on_message = on_message
        self._router = msystem_router
        self._interval = reconcile_interval
        self._bots: Dict[str, Dict[str, Any]] = {}
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if not TELEGRAM_AVAILABLE:
            logger.info("[TelegramManager] python-telegram-bot not installed — disabled")
            return
        self._running = True
        await self._reconcile()
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for key, rec in list(self._bots.items()):
            await self._stop_bot(key, rec)
        self._bots.clear()

    @property
    def bot_count(self) -> int:
        return len(self._bots)

    async def _loop(self):
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                await self._reconcile()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[TelegramManager] reconcile loop error: %s", e, exc_info=True)

    async def _reconcile(self):
        """Diff desired (connections table) against running, then converge."""
        try:
            desired = self._desired_fleet()
        except Exception as e:
            logger.error("[TelegramManager] enumerate failed: %s", e, exc_info=True)
            return

        for key in list(self._bots.keys()):
            rec = self._bots[key]
            if key not in desired or desired[key]["sig"] != rec["sig"]:
                await self._stop_bot(key, rec)
                self._bots.pop(key, None)

        for key, spec in desired.items():
            if key in self._bots:
                continue
            await self._start_bot(key, spec)

    def _desired_fleet(self) -> Dict[str, Dict[str, Any]]:
        """Enumerate the desired bot set across the default context + every
        provisioned tenant, each under its own bound TenantContext."""
        from core.tenant_context import (multi_tenant_enabled, set_tenant_context,
                                          reset_tenant_context, TenantContext)
        desired: Dict[str, Dict[str, Any]] = {}

        try:
            desired.update(self._desired_for_current(None))
        except Exception as e:
            logger.warning("[TelegramManager] enumerate failed (default): %s", e)

        if not multi_tenant_enabled() or not self._router:
            return desired

        try:
            tenants = self._router.list_agent_tenants()
        except Exception as e:
            logger.error("[TelegramManager] tenant enumeration failed: %s", e)
            return desired

        for t in tenants:
            ctx = TenantContext(
                tenant_id=t["tenant_id"], tenant_key=t["tenant_key"],
                display_name=t.get("display_name") or t["tenant_key"],
                tenant_domain=t.get("primary_domain"), is_default=False,
            )
            tok = set_tenant_context(ctx)
            try:
                desired.update(self._desired_for_current(t))
            except Exception as e:
                logger.warning("[TelegramManager] enumerate failed (tenant=%s): %s",
                               t.get("tenant_key"), e)
            finally:
                reset_tenant_context(tok)
        return desired

    def _desired_for_current(self, tenant: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Desired bots for the CURRENTLY-bound tenant context. `tenant` is the
        list_agent_tenants() row (or None for the default/control context).
        Resolves each active telegram connection's token + owner identity, and
        carries the FULL tenant identity so the bot can rebind it per message."""
        tenant_key = (tenant or {}).get("tenant_key", "default")
        tenant_id = (tenant or {}).get("tenant_id", "")
        tenant_display = (tenant or {}).get("display_name") or tenant_key
        tenant_domain = (tenant or {}).get("primary_domain") or ""
        out: Dict[str, Dict[str, Any]] = {}
        try:
            conns = self._connections.list_connections(provider="telegram")
        except Exception as e:
            logger.debug("[TelegramManager] list_connections(telegram) failed for %s: %s",
                         tenant_key, e)
            return out

        for c in conns:
            if (c.scope not in ("user", "org")
                    or c.status in ("disabled", "error")
                    or not c.has_secret):
                continue
            owner_ref = c.owner_ref or ""
            try:
                if c.scope == "user":
                    uid = int(owner_ref) if owner_ref.isdigit() else None
                    resolved = self._connections.resolve("telegram", user_id=uid)
                    owner_email, owner_name = self._owner_identity(owner_ref)
                else:
                    resolved = self._connections.resolve("telegram")
                    owner_email, owner_name = "", ""
            except Exception as e:
                logger.warning("[TelegramManager] resolve failed (%s %s:%s): %s",
                               tenant_key, c.scope, owner_ref or "·", e)
                continue

            token = (resolved.secret or "").strip()
            if not token:
                continue

            key = f"{tenant_key}:{c.scope}:{owner_ref}"
            sig = "|".join((_token_fingerprint(token), tenant_id, tenant_domain, owner_email))
            out[key] = {
                "token": token,
                "tenant_id": tenant_id, "tenant_key": tenant_key,
                "tenant_display": tenant_display, "tenant_domain": tenant_domain,
                "owner_user_id": owner_ref if c.scope == "user" else "",
                "owner_email": owner_email, "owner_name": owner_name, "sig": sig,
            }
        return out

    def _owner_identity(self, owner_ref: str) -> tuple:
        """(email, full_name) for a user-scope owner, looked up in the bound
        tenant's ag_auth.users. Email is what the gateway resolves identity on."""
        if not owner_ref:
            return "", ""
        try:
            row = self._db.fetch_one(
                "SELECT email, full_name FROM ag_auth.users WHERE user_id = %s",
                (int(owner_ref) if owner_ref.isdigit() else owner_ref,),
            )
            if row:
                return (row.get("email") or "", row.get("full_name") or "")
        except Exception as e:
            logger.debug("[TelegramManager] owner identity lookup failed for %s: %s",
                         owner_ref, e)
        return "", ""

    async def _start_bot(self, key: str, spec: Dict[str, Any]):
        try:
            adapter = TelegramAdapter(
                token=spec["token"],
                tenant_id=spec["tenant_id"], tenant_key=spec["tenant_key"],
                tenant_display=spec["tenant_display"], tenant_domain=spec["tenant_domain"],
                owner_user_id=spec["owner_user_id"],
                owner_email=spec["owner_email"],
                owner_name=spec["owner_name"],
            )
            adapter.on_message = self._on_message
            await adapter.start()
            self._bots[key] = {"adapter": adapter, "sig": spec["sig"]}
            uname = (adapter._bot_info or {}).get("username", "?")
            logger.info("[TelegramManager] started bot %s → @%s (owner=%s)",
                        key, uname, spec["owner_email"] or spec["owner_user_id"] or "sender")
        except Exception as e:
            logger.warning("[TelegramManager] start failed for %s: %s", key, e)

    async def _stop_bot(self, key: str, rec: Dict[str, Any]):
        try:
            await rec["adapter"].stop()
            logger.info("[TelegramManager] stopped bot %s", key)
        except Exception as e:
            logger.warning("[TelegramManager] stop failed for %s: %s", key, e)
