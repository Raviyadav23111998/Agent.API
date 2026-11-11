"""
Memory Schemas — Persistent memory DTOs.
═════════════════════════════════════════
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime


class MemoryDTO(BaseModel):
    memory_id: int = Field(..., alias="memoryId", examples=[1])
    user_id: str = Field(..., alias="userId", examples=["24"])
    layer: str = Field(..., examples=["semantic"])
    category: str = Field(..., examples=["fact"])
    key: str = Field(..., examples=["user_preference_theme"])
    value: str = Field(..., examples=["The user prefers dark mode"])
    confidence: float = Field(1.0, examples=[0.95])
    source: Optional[str] = Field(None, examples=["chat"])
    access_count: int = Field(0, alias="accessCount", examples=[5])
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")

    class Config:
        populate_by_name = True


class MemoryStoreRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=500,
        description="Unique key for the memory",
        examples=["user_preference_theme"])
    value: str = Field(..., min_length=1, max_length=10000,
        description="Memory content (max 10k chars)",
        examples=["The user prefers dark mode with blue accent colors"])
    category: Optional[str] = Field(None, max_length=50,
        description="Category: fact | preference | instruction | context",
        examples=["fact"])
    layer: str = Field("semantic", max_length=50,
        description="Memory layer: semantic | episodic | session | company",
        examples=["semantic"])
    tags: Optional[List[str]] = Field(None,
        description="Optional tags for categorization",
        examples=[["ui", "preferences"]])

    @field_validator('layer')
    @classmethod
    def validate_layer(cls, v):
        allowed = {'semantic', 'episodic', 'session', 'company'}
        if v not in allowed:
            raise ValueError(f"layer must be one of: {', '.join(allowed)}")
        return v

    @field_validator('category')
    @classmethod
    def validate_category(cls, v):
        if v is None:
            return v
        allowed = {'fact', 'preference', 'instruction', 'context', 'skill', 'entity'}
        if v not in allowed:
            raise ValueError(f"category must be one of: {', '.join(allowed)}")
        return v


class MemoryRecallRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000,
        description="Search query for full-text memory recall",
        examples=["What are the user's UI preferences?"])
    category: Optional[str] = Field(None, max_length=50,
        description="Filter by category",
        examples=["preference"])
    limit: int = Field(10, ge=1, le=50,
        description="Max results (1-50)",
        examples=[10])

    @field_validator('query')
    @classmethod
    def validate_query(cls, v):
        v = v.strip()
        if not v:
            raise ValueError('Search query cannot be empty')
        return v
