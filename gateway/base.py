"""
Base platform adapter interface for Agent.

All platform adapters (Telegram, future: Discord, Slack) inherit from this.
Distilled from Hermes gateway/platforms/base.py (3,481 lines → ~60 lines).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable, Any
from enum import Enum


class MessageType(Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"


@dataclass
class MessageEvent:
    """Incoming message from a platform."""
    platform: str
    chat_id: str
    user_id: str
    user_name: Optional[str] = None
    text: str = ""
    thread_id: Optional[str] = None
    message_type: MessageType = MessageType.TEXT
    raw: Any = None
    email: Optional[str] = None
    source_adapter: Any = None
    session_key: Optional[str] = None
    # Part 1 — attachments the user sent TO the model, already hydrated:
    # [{kind, media_type, data_b64, filename}]. Adapters populate this from the
    # platform's photo/document/voice; the runner passes it into _process_input.
    attachments: Optional[list] = None


@dataclass
class SendResult:
    """Result of sending a message."""
    success: bool
    error: Optional[str] = None
    message_id: Optional[str] = None


@dataclass
class CardContent:
    """Structured content renderable as Adaptive Card (Teams) or formatted text.

    Attributes:
        card_type: "plan", "citations", or "approval".
        title:     Human-readable header (e.g. "📋 Plan").
        items:     List of dicts — steps for plan, sources for citations.
        fallback_text: Plain-text representation for adapters without card support.
        data:      Optional payload for interactive cards (e.g. approval_id,
                   tool, args for an "approval" card with Approve/Deny buttons).
    """
    card_type: str
    title: str
    items: list
    fallback_text: str
    data: dict = None


class BasePlatformAdapter(ABC):
    """Base class for all platform adapters.
    
    Lifecycle:
        adapter = TelegramAdapter(config)
        adapter.on_message = my_callback
        await adapter.start()
        ...
        await adapter.stop()
    """
    
    def __init__(self, platform_name: str):
        self.platform_name = platform_name
        self._message_callback: Optional[Callable[[MessageEvent], Awaitable[None]]] = None
    
    @property
    def on_message(self) -> Optional[Callable]:
        return self._message_callback
    
    @on_message.setter
    def on_message(self, callback: Callable[[MessageEvent], Awaitable[None]]):
        self._message_callback = callback
    
    async def _dispatch_message(self, event: MessageEvent):
        """Route incoming message to registered callback."""
        if self._message_callback:
            await self._message_callback(event)
    
    @abstractmethod
    async def start(self):
        """Start receiving messages."""
        ...
    
    @abstractmethod
    async def stop(self):
        """Stop receiving messages and clean up."""
        ...
    
    @abstractmethod
    async def send(self, chat_id: str, text: str,
                   thread_id: Optional[str] = None) -> SendResult:
        """Send a text message to a chat."""
        ...

    async def send_card(self, chat_id: str, card: CardContent,
                        thread_id: Optional[str] = None) -> SendResult:
        """Send structured content (plan / citations).

        Adapters that support rich rendering (Adaptive Cards, HTML) should
        override this.  The default falls back to the plain-text representation.
        """
        return await self.send(chat_id, card.fallback_text, thread_id)

    async def send_media(self, chat_id: str, data: bytes, kind: str,
                         media_type: str = "", filename: str = "file",
                         thread_id: Optional[str] = None) -> SendResult:
        """Deliver model-GENERATED media (Part 2 — image/audio/video) to a chat.

        Adapters that support native media (Telegram photo, Teams card image)
        override this. The default sends a short text note so the user is at
        least told a file was produced.
        """
        return await self.send(chat_id, f"[Generated a {kind} file]", thread_id)
