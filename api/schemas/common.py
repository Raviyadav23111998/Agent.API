"""
Common Schemas — Shared response models.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Any


class ErrorResponse(BaseModel):
    """Standard error response (≈ Storeglance.Microservices.Core GlobalExceptionMiddleware)."""
    error: str = Field(..., examples=["InternalServerError"])
    message: str = Field(..., examples=["An unexpected error occurred. Please try again later."])
    status_code: int = Field(..., alias="statusCode", examples=[500])
    detail: Optional[str] = Field(None,
        description="Additional error details (only in development mode)")

    class Config:
        populate_by_name = True


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field("healthy", examples=["healthy"])
    version: str = Field("1.0.0", examples=["1.0.0"])
    service: str = Field("AGENT.API", examples=["AGENT.API"])
    uptime_seconds: Optional[float] = Field(None, examples=[3600.5])
    db_connected: bool = Field(False, examples=[True])


class PagedResponse(BaseModel):
    """Generic paged response for paginated endpoints."""
    items: List[Any] = []
    total: int = Field(0, examples=[42])
    page: int = Field(1, ge=1, examples=[1])
    page_size: int = Field(20, alias="pageSize", ge=1, le=100, examples=[20])
    has_next: bool = Field(False, alias="hasNext",
        description="Whether more pages are available")

    class Config:
        populate_by_name = True
