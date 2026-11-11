"""
User Schemas — Pydantic DTOs (≈ SMSystems UserDTO.cs)
═════════════════════════════════════════════════════
Maps to: UserRequestDTO, UserByIdResponseDTO, UsersResponseDTO, UserSessionDTO, UserSummary
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime
import re


class UserSummary(BaseModel):
    """Lightweight user reference (for DDL/lookups)."""
    user_id: int = Field(..., alias="userId", examples=[24])
    name: Optional[str] = Field(None, examples=["Admin User"])
    user_code: Optional[str] = Field(None, alias="userCode", examples=["admin"])
    email: Optional[str] = Field(None, examples=["admin@storeglance.com"])
    role_name: Optional[str] = Field(None, alias="roleName", examples=["Administrator"])
    is_active: Optional[bool] = Field(None, alias="isActive", examples=[True])

    class Config:
        populate_by_name = True


class UserRequest(BaseModel):
    """Create/Update user request."""
    user_id: Optional[int] = Field(None, alias="userId",
        description="Pass null/omit for create, pass existing ID for update",
        examples=[None])
    user_code: str = Field(..., alias="userCode", min_length=2, max_length=50,
        description="Unique username (2-50 chars, alphanumeric + underscore)",
        examples=["john_doe"])
    email: str = Field(..., max_length=255,
        description="Valid email address",
        examples=["john@storeglance.com"])
    full_name: str = Field(..., alias="fullName", min_length=1, max_length=200,
        description="Display name",
        examples=["John Doe"])
    mobile: Optional[str] = Field(None, max_length=20, examples=["+91-9876543210"])
    role_id: Optional[int] = Field(None, alias="roleId",
        description="1=SuperAdmin, 2=Admin, 3=Member",
        examples=[3])
    is_active: bool = Field(True, alias="isActive")
    password: Optional[str] = Field(None, min_length=6, max_length=128,
        description="Required on create, optional on update (preserves existing)",
        examples=["SecureP@ss123"])
    avatar_url: Optional[str] = Field(None, alias="avatarUrl", max_length=500)
    platform: Optional[str] = Field('web', max_length=50, examples=["web"])

    class Config:
        populate_by_name = True

    @field_validator('user_code')
    @classmethod
    def validate_user_code(cls, v):
        if not re.match(r'^[a-zA-Z0-9_.-]+$', v):
            raise ValueError('user_code must contain only letters, digits, underscores, dots, or hyphens')
        return v

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if '@' not in v or '.' not in v.split('@')[-1]:
            raise ValueError('Invalid email format')
        return v.lower().strip()

    @field_validator('full_name')
    @classmethod
    def validate_full_name(cls, v):
        return v.strip()


class UserByIdResponse(BaseModel):
    """Full user detail response."""
    user_id: int = Field(..., alias="userId", examples=[24])
    user_code: Optional[str] = Field(None, alias="userCode", examples=["admin"])
    email: Optional[str] = Field(None, examples=["admin@storeglance.com"])
    full_name: str = Field(..., alias="fullName", examples=["Admin User"])
    mobile: Optional[str] = Field(None, examples=["+91-9876543210"])
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    role_id: int = Field(..., alias="roleId", examples=[1])
    role_name: Optional[str] = Field(None, alias="roleName", examples=["Administrator"])
    is_active: bool = Field(True, alias="isActive")
    is_blocked: bool = Field(False, alias="isBlocked")
    platform: Optional[str] = Field(None, examples=["web"])
    last_login_at: Optional[datetime] = Field(None, alias="lastLoginAt")
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")
    created: Optional[UserSummary] = None
    updated: Optional[UserSummary] = None

    class Config:
        populate_by_name = True


class UsersListItem(BaseModel):
    """User list item (for grid/table)."""
    user_id: int = Field(..., alias="userId", examples=[24])
    user_code: Optional[str] = Field(None, alias="userCode", examples=["admin"])
    email: Optional[str] = Field(None, examples=["admin@storeglance.com"])
    full_name: str = Field(..., alias="fullName", examples=["Admin User"])
    role_name: Optional[str] = Field(None, alias="roleName", examples=["Administrator"])
    is_active: bool = Field(True, alias="isActive")
    is_blocked: bool = Field(False, alias="isBlocked")
    platform: Optional[str] = Field(None, examples=["web"])
    created_by_name: Optional[str] = Field(None, alias="createdByName")
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_by_name: Optional[str] = Field(None, alias="updatedByName")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")

    class Config:
        populate_by_name = True


class UserSessionResponse(BaseModel):
    """Session info for active/inactive sessions."""
    session_id: str = Field(..., alias="sessionId", examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"])
    user_id: int = Field(..., alias="userId", examples=[24])
    platform: Optional[str] = Field(None, examples=["web"])
    agent_type: Optional[str] = Field(None, alias="agentType")
    ip_address: Optional[str] = Field(None, alias="ipAddress", examples=["127.0.0.1"])
    login_at: Optional[datetime] = Field(None, alias="loginAt")
    last_active_at: Optional[datetime] = Field(None, alias="lastActiveAt")
    logout_at: Optional[datetime] = Field(None, alias="logoutAt")

    class Config:
        populate_by_name = True


class UsersPagedResponse(BaseModel):
    total: int
    data: List[UsersListItem]

class ValidateResponse(BaseModel):
    """Validation response for email/userCode uniqueness."""
    exists: bool = Field(..., examples=[True])
    message: Optional[str] = Field(None, examples=["Email already in use"])
