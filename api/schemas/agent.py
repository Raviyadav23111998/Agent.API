"""
Agent Schemas — DTOs for agent definitions and runs.
═════════════════════════════════════════════════════
Tables: ag_agents.definitions, ag_agents.runs
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime


class AgentCreateRequest(BaseModel):
    """Create/update agent definition."""
    name: str = Field(..., min_length=1, max_length=200,
        description="Agent name",
        examples=["Email Summarizer"])
    description: Optional[str] = Field(None, max_length=2000,
        description="Agent description",
        examples=["Summarizes daily emails and creates digest"])
    system_prompt: Optional[str] = Field(None, alias="systemPrompt", max_length=50000,
        description="System prompt for the agent",
        examples=["You are an email summarizer. Read the user's recent emails and create a concise digest."])
    tools: Optional[List[str]] = Field(None,
        description="List of tool names the agent can use",
        examples=[["outlook_list_emails", "outlook_read_email"]])
    model: Optional[str] = Field(None, description="Model to use for this agent.")
    schedule: Optional[str] = Field(None, max_length=100,
        description="Cron schedule for automated runs",
        examples=["0 9 * * 1-5"])
    enabled: bool = Field(True, description="Whether agent is active")
    workspace_path: Optional[str] = Field(None, alias="workspacePath", max_length=500)
    deliver: str = Field("local", max_length=50,
        description="Delivery method: local | email | webhook",
        examples=["local"])
    visibility: str = Field("global", max_length=50,
        description="Visibility: global (all users) | private (creator only)",
        examples=["global"])
    metadata: Optional[Dict[str, Any]] = Field(None,
        description="Additional key-value metadata")

    class Config:
        populate_by_name = True

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        return v.strip()

    @field_validator('deliver')
    @classmethod
    def validate_deliver(cls, v):
        allowed = {'local', 'email', 'webhook', 'slack'}
        if v not in allowed:
            raise ValueError(f"deliver must be one of: {', '.join(allowed)}")
        return v

    @field_validator('visibility')
    @classmethod
    def validate_visibility(cls, v):
        allowed = {'global', 'private'}
        if v not in allowed:
            raise ValueError(f"visibility must be one of: {', '.join(allowed)}")
        return v


class AgentDTO(BaseModel):
    """Agent definition response."""
    agent_id: int = Field(..., alias="agentId", examples=[1])
    name: str = Field(..., examples=["Email Summarizer"])
    description: Optional[str] = Field(None, examples=["Summarizes daily emails"])
    system_prompt: Optional[str] = Field(None, alias="systemPrompt")
    tools: Optional[List] = None
    model: Optional[str] = Field(None)
    schedule: Optional[str] = Field(None, examples=["0 9 * * 1-5"])
    enabled: bool = True
    deliver: str = Field("local", examples=["local"])
    visibility: str = Field("global", examples=["global"])
    run_count: int = Field(0, alias="runCount", examples=[42])
    last_run_at: Optional[datetime] = Field(None, alias="lastRunAt")
    last_status: Optional[str] = Field(None, alias="lastStatus", examples=["ok"])
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")

    class Config:
        populate_by_name = True


class AgentRunDTO(BaseModel):
    """Agent run record."""
    run_id: int = Field(..., alias="runId", examples=[101])
    agent_id: int = Field(..., alias="agentId", examples=[1])
    status: str = Field(..., examples=["ok"])
    input_prompt: Optional[str] = Field(None, alias="inputPrompt",
        examples=["Summarize my recent emails"])
    output_text: Optional[str] = Field(None, alias="outputText",
        examples=["You have 3 important emails..."])
    error_message: Optional[str] = Field(None, alias="errorMessage")
    started_at: Optional[datetime] = Field(None, alias="startedAt")
    completed_at: Optional[datetime] = Field(None, alias="completedAt")
    duration_ms: Optional[int] = Field(None, alias="durationMs", examples=[2340])
    token_count: Optional[int] = Field(None, alias="tokenCount", examples=[1250])

    class Config:
        populate_by_name = True


class AgentRunRequest(BaseModel):
    """Request to trigger an agent run."""
    prompt: Optional[str] = Field(None, max_length=32000,
        description="User prompt for the agent run",
        examples=["Summarize my last 5 emails"])
    stream: bool = Field(False, description="Stream response via SSE")
