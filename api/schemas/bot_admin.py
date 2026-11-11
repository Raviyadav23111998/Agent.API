from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from uuid import UUID


class BotRuleBase(BaseModel):
    rule_type: str = Field(..., description="'url_contains', 'url_exact', 'url_regex', 'fallback'")
    pattern: str = Field(..., max_length=500)
    instruction: str = Field(...)
    priority: int = Field(0)
    is_active: bool = Field(True)


class BotCreateRequest(BaseModel):
    name: str = Field(..., max_length=200)
    description: Optional[str] = Field("")
    allowed_domains: List[str] = Field(default_factory=lambda: ["*"])
    system_prompt: str = Field(default="You are a helpful assistant.")
    welcome_message: Optional[str] = Field("Hi! How can I help you today?")
    model: Optional[str] = Field(None, max_length=100)
    theme_color: Optional[str] = Field("#6D28D9", max_length=7)
    max_context_docs: int = Field(5, ge=1, le=20)
    is_active: bool = Field(True)
    app_id: Optional[int] = Field(None, description="Application this bot belongs to")

class BotUpdateRequest(BotCreateRequest):
    pass

class BotRuleCreateRequest(BotRuleBase):
    pass


class BotRuleDTO(BotRuleBase):
    rule_id: int
    bot_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class BotDTO(BaseModel):
    """Bot details — NEVER includes the raw api_token."""
    bot_id: int
    bot_uuid: UUID
    name: str
    description: Optional[str]
    api_token_prefix: Optional[str] = None
    allowed_domains: List[str]
    system_prompt: str
    welcome_message: Optional[str]
    model: Optional[str]
    theme_color: Optional[str]
    max_context_docs: int
    is_active: bool
    app_id: Optional[int] = None
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_row(cls, row: dict) -> "BotDTO":
        """Create BotDTO from a DB row, masking the token."""
        data = dict(row)
        raw_token = data.pop("api_token", None) or ""
        if raw_token:
            if len(raw_token) > 14:
                data["api_token_prefix"] = f"{raw_token[:10]}...{raw_token[-4:]}"
            else:
                data["api_token_prefix"] = raw_token[:4] + "****"
        else:
            data["api_token_prefix"] = "****"
        data.pop("api_token_hash", None)
        return cls(**data)


class BotCreateResponseDTO(BotDTO):
    """Response for bot creation — includes raw api_token ONE TIME ONLY."""
    api_token: str

    class Config:
        from_attributes = True

