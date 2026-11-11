"""
Auth Router — REST endpoints for authentication.
═════════════════════════════════════════════════
≈ SMSystems.Staff.Controllers.AuthController

Endpoints:
    POST /Login           → Login (same path as SMSystems)
    GET  /Logout          → Logout (same path as SMSystems)
    POST /ChangePassword  → Change password (same path as SMSystems)
    POST /api/v1/auth/refresh  → Convenience alias for refresh_token grant
"""

import logging
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from api.middleware.auth import get_current_user
from api.schemas.auth import (
    LoginRequest,
    LoginResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Auth"])


def _get_auth_service(request: Request):
    """Get AuthService from app state (wired in main.py)."""
    return request.app.state.auth_service


@router.post(
    "/Login",
    response_model=LoginResponse,
    summary="Login — authenticate user",
    description="Sign in. Supports grant_type: client_credentials, refresh_token.",
)
async def login(
    login_request: LoginRequest,
    request: Request,
):
    auth_service = _get_auth_service(request)
    response = await auth_service.login(login_request)

    if response.is_authenticated:
        return response
    else:
        raise HTTPException(status_code=401, detail=response.message)


@router.get(
    "/Logout",
    summary="Logout — invalidate session",
    description="Sign out. Requires Bearer token.",
)
async def logout(
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    auth_service = _get_auth_service(request)
    session_id = current_user.get("session_ID", "")
    user_id = int(current_user.get("user_ID", 0))
    auth_service.logout(session_id, user_id)
    return {"message": "Logged out successfully"}


@router.post(
    "/ChangePassword",
    response_model=ChangePasswordResponse,
    summary="Change password",
    description="Change or reset a password. Supports: ResetPassword (with JWT).",
)
async def change_password(
    change_request: ChangePasswordRequest,
    request: Request,
):
    auth_service = _get_auth_service(request)
    try:
        response = await auth_service.change_password(change_request)
        return response
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


from typing import Optional
from pydantic import BaseModel


class RefreshTokenBody(BaseModel):
    """JSON body for the refresh endpoint — tokens must never travel in
    the query string, where they end up in access logs and proxies."""
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None


@router.post(
    "/v1/auth/refresh",
    response_model=LoginResponse,
    summary="Refresh token — convenience endpoint",
    description="Shorthand for Login with grant_type=refresh_token. "
                "Send tokens in the JSON body.",
)
async def refresh_token(
    request: Request,
    body: Optional[RefreshTokenBody] = None,
    access_token: str = None,
    refresh_token_str: str = None,
):
    from api.schemas.auth import TokenInfo

    at = (body.access_token if body else None) or access_token
    rt = (body.refresh_token if body else None) or refresh_token_str

    login_req = LoginRequest(
        grant_type="refresh_token",
        token=TokenInfo(token=at, refresh_token=rt),
    )
    auth_service = _get_auth_service(request)
    response = await auth_service.login(login_req)
    if response.is_authenticated:
        return response
    else:
        raise HTTPException(status_code=401, detail=response.message)
