"""
System Config Schemas — Pydantic models for the config admin API.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ConfigItemResponse(BaseModel):
    """Single config key with full metadata."""
    key: str
    value: str = ""
    is_secret: bool = False
    description: str = ""
    type: str = "text"
    default: str = ""
    source: str = "default"
    requires_restart: bool = False
    managed_by: Optional[str] = None
    validation: Optional[Dict[str, Any]] = None
    updated_at: Optional[str] = None


class ConfigGroupResponse(BaseModel):
    """A group of configs under a common prefix."""
    prefix: str
    label: str
    description: str = ""
    icon: str = "⚙️"
    sort: int = 99
    configs: List[ConfigItemResponse] = []


class ConfigUpdateRequest(BaseModel):
    """Update a single config key."""
    key: str = Field(..., min_length=1, description="Config key (e.g., 'agent.max_tools')")
    value: str = Field(..., description="New value")
    description: Optional[str] = Field(None, description="Optional description update")


class ConfigBulkUpdateRequest(BaseModel):
    """Update multiple config keys at once."""
    updates: List[ConfigUpdateRequest] = Field(..., min_length=1)


class ConfigDeleteRequest(BaseModel):
    """Soft-delete (deactivate) a config key."""
    key: str = Field(..., min_length=1)
