"""
Auth Schemas — Pydantic DTOs (≈ SMSystems LoginRequestDTO/LoginResponseDTO)
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime


class TokenInfo(BaseModel):
    """For refresh_token and external_client grant types."""
    token: Optional[str] = Field(None,
        description="Existing access token (can be expired for refresh flow)",
        examples=["eyJhbGciOiJSUzI1NiIs..."])
    refresh_token: Optional[str] = Field(None, alias="refreshToken",
        description="Refresh token issued during login",
        examples=["dGhpcyBpcyBhIHJlZnJlc2..."])
    token_provider: Optional[str] = Field(None, alias="tokenProvider",
        description="OAuth provider (future: google, microsoft)",
        examples=["google"])

    class Config:
        populate_by_name = True


class LoginRequest(BaseModel):
    """≈ SMSystems LoginRequestDTO"""
    username: Optional[str] = Field(None, alias="userName",
        description="Username for client_credentials grant",
        examples=["admin"])
    password: Optional[str] = Field(None,
        description="Password for client_credentials grant",
        examples=["Admin@123"])
    grant_type: str = Field("client_credentials", alias="grantType",
        description="Grant type: client_credentials | refresh_token",
        examples=["client_credentials"])
    token: Optional[TokenInfo] = Field(None,
        description="Token info for refresh_token grant")

    class Config:
        populate_by_name = True

    @field_validator('grant_type')
    @classmethod
    def validate_grant_type(cls, v):
        allowed = {'client_credentials', 'refresh_token', 'external_client'}
        if v not in allowed:
            raise ValueError(f"grant_type must be one of: {', '.join(allowed)}")
        return v


class UserInfo(BaseModel):
    """User details returned in login response."""
    user_id: int = Field(..., examples=[24])
    username: str = Field(..., examples=["admin"])
    email: str = Field(..., examples=["admin@storeglance.com"])
    first_name: str = Field(..., examples=["Admin"])
    last_name: str = Field(..., examples=["User"])
    role: str = Field(..., examples=["Administrator"])
    display_name: Optional[str] = Field(None, examples=["Admin User"])


class LoginResponse(BaseModel):
    """≈ SMSystems LoginResponseDTO"""
    message: Optional[str] = Field(None, examples=["Valid User!"])
    is_authenticated: bool = Field(False, alias="isAuthenticated")
    access_token: Optional[str] = Field(None, alias="accessToken",
        description="JWT access token (RS256, 24h expiry)",
        examples=["eyJhbGciOiJSUzI1NiIs..."])
    refresh_token: Optional[str] = Field(None, alias="refreshToken",
        description="Refresh token (7 day expiry)",
        examples=["dGhpcyBpcyBhIHJlZnJlc2..."])
    user: Optional[UserInfo] = None

    class Config:
        populate_by_name = True


class ChangePasswordRequest(BaseModel):
    """≈ SMSystems ChangePasswordRequestDTO"""
    user_code: Optional[str] = Field(None, alias="userCode", examples=["admin"])
    request_type: str = Field(..., alias="requestType",
        description="Challenge | ForgotPassword | ResetPassword",
        examples=["ResetPassword"])
    otp: Optional[str] = Field(None, alias="OTP",
        description="OTP for ForgotPassword flow",
        examples=["123456"])
    password: Optional[str] = Field(None, min_length=6, max_length=128,
        description="New password (min 6 chars)",
        examples=["NewSecureP@ss123"])
    old_password: Optional[str] = Field(None, alias="oldPassword",
        description="Current password — required for the ResetPassword flow "
                    "(a stolen JWT alone must not allow a password change)")
    access_token: Optional[str] = Field(None, alias="accessToken",
        description="Current JWT for ResetPassword flow")

    class Config:
        populate_by_name = True

    @field_validator('request_type')
    @classmethod
    def validate_request_type(cls, v):
        allowed = {'Challenge', 'ForgotPassword', 'ResetPassword'}
        if v not in allowed:
            raise ValueError(f"request_type must be one of: {', '.join(allowed)}")
        return v


class ChangePasswordResponse(BaseModel):
    """≈ SMSystems ChangePasswordResponseDTO"""
    message: Optional[str] = Field(None, examples=["Password Changed Successfully"])
    is_success: bool = Field(False, alias="isSuccess")

    class Config:
        populate_by_name = True


class SessionInfo(BaseModel):
    """Active session details."""
    session_id: str = Field(..., examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"])
    user_id: int = Field(..., examples=[24])
    login_date: Optional[datetime] = None
    agent_type: Optional[str] = None
    ip_address: Optional[str] = Field(None, examples=["127.0.0.1"])
