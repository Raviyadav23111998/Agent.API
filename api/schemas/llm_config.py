from typing import Optional
from pydantic import BaseModel, Field

class LLMConfigResponse(BaseModel):
    provider: str = Field("", description="e.g. openrouter, openai, groq")
    model: str = Field("", description="e.g. deepseek/deepseek-v4-flash")
    base_url: str = Field("", description="e.g. https://openrouter.ai/api/v1/chat/completions")
    api_key: str = Field("", description="Masked API Key (e.g. *****1234)")
    provider_order: str = Field("", description="e.g. DeepInfra")
    max_tokens: str = Field("16000", description="Max tokens for response")
    temperature: str = Field("0.7", description="Temperature for generation")

class LLMConfigUpdateRequest(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    provider_order: Optional[str] = None
    max_tokens: Optional[str] = None
    temperature: Optional[str] = None
