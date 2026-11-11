"""
Brain Schemas — Knowledge base DTOs.
═════════════════════════════════════
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime


class DocumentDTO(BaseModel):
    doc_id: int = Field(..., alias="docId", examples=[1])
    source_path: str = Field(..., alias="sourcePath",
        examples=["docs/architecture.md"])
    doc_type: str = Field("document", alias="docType",
        examples=["document"])
    title: Optional[str] = Field(None, examples=["System Architecture"])
    content: Optional[str] = Field(None,
        description="Full document content (omitted in list views)")
    content_hash: Optional[str] = Field(None, alias="contentHash")
    token_count: int = Field(0, alias="tokenCount", examples=[1250])
    status: str = Field("pending", examples=["indexed"])
    owner_id: Optional[str] = Field(None, alias="ownerId", examples=["24"])
    app_id: Optional[int] = Field(None, alias="appId", examples=[1])
    created_at: Optional[datetime] = Field(None, alias="createdAt")

    class Config:
        populate_by_name = True


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000,
        description="Full-text search query",
        examples=["agent architecture"])
    doc_type: Optional[str] = Field(None, alias="docType",
        description="Filter by document type",
        examples=["document"])
    limit: int = Field(10, ge=1, le=50,
        description="Max results (1-50)",
        examples=[10])

    class Config:
        populate_by_name = True

    @field_validator('query')
    @classmethod
    def validate_query(cls, v):
        v = v.strip()
        if not v:
            raise ValueError('Search query cannot be empty')
        return v


class SearchResult(BaseModel):
    doc_id: int = Field(..., alias="docId", examples=[1])
    title: Optional[str] = Field(None, examples=["System Architecture"])
    snippet: Optional[str] = Field(None,
        description="First 300 chars of matching content",
        examples=["The agent system uses a layered architecture..."])
    source_path: str = Field(..., alias="sourcePath",
        examples=["docs/architecture.md"])
    rank: Optional[float] = Field(None,
        description="FTS relevance score",
        examples=[0.85])

    class Config:
        populate_by_name = True


class IngestRequest(BaseModel):
    source_path: str = Field(..., alias="sourcePath", min_length=1, max_length=500,
        description="Unique identifier/path for the document",
        examples=["docs/architecture.md"])
    content: str = Field(..., min_length=1, max_length=500000,
        description="Document content (max 500k chars)",
        examples=["# System Architecture\n\nThe agent system uses a layered architecture..."])
    title: Optional[str] = Field(None, max_length=500,
        description="Document title",
        examples=["System Architecture"])
    doc_type: str = Field("document", alias="docType", max_length=50,
        description="Type: document | code | email | note",
        examples=["document"])
    app_id: Optional[int] = Field(None, alias="appId",
        description="Application ID to scope this document to (default: 1)",
        examples=[1])

    class Config:
        populate_by_name = True

    @field_validator('doc_type')
    @classmethod
    def validate_doc_type(cls, v):
        allowed = {'document', 'code', 'email', 'note', 'wiki', 'api_doc'}
        if v not in allowed:
            raise ValueError(f"doc_type must be one of: {', '.join(allowed)}")
        return v
