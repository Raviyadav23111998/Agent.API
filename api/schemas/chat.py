"""
Chat Schemas — SSE streaming DTOs (ChatGPT/Gemini style)
═══════════════════════════════════════════════════════════
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict
from datetime import datetime
from enum import Enum


class StreamEventType(str, Enum):
    MESSAGE_START = "message.start"
    MESSAGE_DELTA = "message.delta"
    MESSAGE_END = "message.end"
    TOOL_START = "tool.start"
    TOOL_END = "tool.end"
    STATUS = "status"
    ERROR = "error"


class ChatRequest(BaseModel):
    """Chat message request — identical to ChatGPT API."""
    message: str = Field(..., min_length=1, max_length=32000,
        description="User message (1-32k chars)",
        examples=["Summarize my last 10 emails"])
    conversation_id: Optional[str] = Field(None, alias="conversationId",
        description="Existing conversation ID (omit to create new)",
        examples=["d0c2984f-8714-49fa-a0ec-a138b6573a1e"])
    agent_id: Optional[int] = Field(None, alias="agentId",
        description="Agent to use (default: general assistant)",
        examples=[1])
    model: Optional[str] = Field(None, description="Optional. Override the default model.")
    stream: bool = Field(True, description="Stream response via SSE")
    attachment_ids: Optional[List[int]] = Field(None, alias="attachmentIds",
        description="File ids from POST /v1/files to attach to this message (Part 1)")

    class Config:
        populate_by_name = True

    @field_validator('message')
    @classmethod
    def validate_message(cls, v):
        # Allow an image-only turn (blank text) when attachments are present;
        # the message length floor (min_length=1) still applies to the string,
        # so the web sends a single space for image-only messages.
        v = v.strip()
        return v


class MessageDTO(BaseModel):
    """Single message in a conversation."""
    message_id: Optional[int] = Field(None, alias="messageId", examples=[101])
    role: str = Field(..., examples=["assistant"])
    content: Optional[str] = Field(None, examples=["Here are your last 10 emails..."])
    tool_calls: Optional[List[Dict]] = Field(None, alias="toolCalls")
    created_at: Optional[datetime] = Field(None, alias="createdAt")

    class Config:
        populate_by_name = True


class ConversationDTO(BaseModel):
    """Conversation metadata."""
    conversation_id: str = Field(..., alias="conversationId",
        examples=["d0c2984f-8714-49fa-a0ec-a138b6573a1e"])
    title: Optional[str] = Field(None, examples=["Email Summary"])
    agent_id: Optional[int] = Field(None, alias="agentId", examples=[1])
    model: Optional[str] = Field(None)
    message_count: int = Field(0, alias="messageCount", examples=[4])
    is_archived: bool = Field(False, alias="isArchived")
    source: str = Field('web', description="Client channel: web, vscode, chatbot, mobile, api",
        examples=["web", "vscode"])
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")

    class Config:
        populate_by_name = True


class ConversationDetailDTO(ConversationDTO):
    """Conversation with full message history."""
    messages: List[MessageDTO] = []
