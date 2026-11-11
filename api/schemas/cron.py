from typing import Optional, Any, Dict
from pydantic import BaseModel, Field


class CronRepeatConfig(BaseModel):
    times: Optional[int] = None
    completed: int = 0


class CronJobDTO(BaseModel):
    id: str
    db_id: int
    name: str
    prompt: str
    schedule: Dict[str, Any]
    schedule_display: str
    repeat: CronRepeatConfig
    enabled: bool
    state: str
    created_at: str
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None
    last_status: str
    last_error: str
    deliver: str
    app_id: Optional[int] = None
    persona_id: Optional[int] = None
    origin: Optional[Dict[str, Any]] = None


class CronJobCreateRequest(BaseModel):
    name: Optional[str] = Field(None, description="Optional name for the cron job")
    prompt: str = Field(..., description="The prompt/instruction for the agent")
    schedule: str = Field(..., description="Schedule rule (e.g. '30m', 'every 1h', '0 9 * * *')")
    repeat_times: Optional[int] = Field(None, description="Number of times to run (null for infinite for interval/cron)")
    deliver: Optional[str] = Field(None, description="Delivery method (e.g. 'local', 'telegram')")
    app_id: Optional[int] = Field(None, description="Application this cron belongs to")
    persona_id: Optional[int] = Field(None, description="Persona to run this task under; null = the app's default persona")


class CronJobUpdateRequest(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    schedule: Optional[str] = None
    repeat_times: Optional[int] = None
    deliver: Optional[str] = None
    enabled: Optional[bool] = None
    app_id: Optional[int] = None
    persona_id: Optional[int] = None
