"""
User Router — REST endpoints for user management.
═════════════════════════════════════════════════════
≈ SMSystems.Staff.Controllers.UserController

Endpoints (identical route paths to SMSystems):
    GET    User/Validate/Email       → Check email uniqueness
    GET    User/Validate/UserCode    → Check user_code uniqueness
    GET    User/ActiveSession        → Active sessions for current user
    GET    User/InActiveSession      → Inactive sessions for current user

Additional CRUD (standard REST):
    GET    /api/v1/users             → List all users
    GET    /api/v1/users/{id}        → Get user by ID
    POST   /api/v1/users             → Create user
    PUT    /api/v1/users/{id}        → Update user
    DELETE /api/v1/users/{id}        → Deactivate user
    GET    /api/v1/users/ddl         → Users dropdown (search)
    GET    /api/v1/users/by-ids      → Users by comma-separated IDs
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query

from api.middleware.auth import get_current_user
from api.schemas.user import (
    UserRequest,
    UserByIdResponse,
    UsersPagedResponse,
    UserSummary,
    UserSessionResponse,
    ValidateResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Users"])


def _get_user_service(request: Request):
    """Get UserService from app state."""
    return request.app.state.user_service


@router.get(
    "/v1/users/Validate/Email",
    response_model=ValidateResponse,
    summary="Validate email uniqueness",
    description="Check whether an email address is already registered",
)
async def validate_email(
    email: str = Query(..., description="Email to validate"),
    request: Request = None,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_user_service(request)
    result = await svc.validate_email(email)
    return result


@router.get(
    "/v1/users/Validate/UserCode",
    response_model=ValidateResponse,
    summary="Validate user code uniqueness",
    description="Check whether a user code is already taken",
)
async def validate_user_code(
    userCode: str = Query(..., description="User code to validate"),
    userId: Optional[int] = Query(None, description="Exclude this user ID"),
    request: Request = None,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_user_service(request)
    result = await svc.validate_user_code(userCode, userId)
    return result


@router.get(
    "/v1/users/ActiveSession",
    response_model=List[UserSessionResponse],
    summary="Get active sessions for current user",
    description="Mark the user session active",
)
async def active_session(
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_user_service(request)
    user_id = int(current_user.get("user_ID", 0))
    return await svc.get_active_sessions(user_id)


@router.get(
    "/v1/users/InActiveSession",
    response_model=List[UserSessionResponse],
    summary="Get inactive sessions for current user",
    description="Mark the user session inactive",
)
async def inactive_session(
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_user_service(request)
    user_id = int(current_user.get("user_ID", 0))
    return await svc.get_inactive_sessions(user_id)


@router.get(
    "/v1/users",
    response_model=UsersPagedResponse,
    summary="Get paginated list of users",
    description="Returns all users with creator and updater names, paginated.",
)
async def list_users(
    request: Request,
    skip: int = Query(0, description="Number of records to skip"),
    take: int = Query(10, description="Number of records to return"),
    search: Optional[str] = Query(None, description="Search text for filtering"),
    sort_field: str = Query('user_id', description="Field to sort by"),
    sort_dir: str = Query('desc', description="Sort direction (asc or desc)"),
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_user_service(request)
    return await svc.get_users(skip, take, search, sort_field, sort_dir)


@router.get(
    "/v1/users/ddl",
    response_model=List[UserSummary],
    summary="Users dropdown (search)",
    description="Users for a dropdown list",
)
async def users_ddl(
    SearchText: Optional[str] = Query(None, description="Search by name"),
    role: Optional[str] = Query(None, description="Filter by role key"),
    request: Request = None,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_user_service(request)
    return await svc.get_users_ddl(SearchText, role)


@router.get(
    "/v1/users/by-ids",
    response_model=List[UserSummary],
    summary="Get users by comma-separated IDs",
    description="Users by ID",
)
async def users_by_ids(
    UserIDs: str = Query(..., description="Comma-separated user IDs"),
    request: Request = None,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_user_service(request)
    return await svc.get_user_by_ids(UserIDs)


@router.get(
    "/v1/users/roles",
    summary="Get all available roles",
)
async def get_roles(
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_user_service(request)
    return await svc.get_roles()


@router.get(
    "/v1/users/{user_id}",
    response_model=UserByIdResponse,
    summary="Get user by ID",
)
async def get_user(
    user_id: int,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_user_service(request)
    user = await svc.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post(
    "/v1/users",
    summary="Create user",
    description="Create a user",
)
async def create_user(
    user_request: UserRequest,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_user_service(request)
    current_uid = int(current_user.get("user_ID", 0))

    user_request.user_id = None
    user_id = await svc.add_update_user(user_request, current_uid)
    return {"userId": user_id, "message": "User created successfully"}


@router.put(
    "/v1/users/{user_id}",
    summary="Update user",
    description="Update a user",
)
async def update_user(
    user_id: int,
    user_request: UserRequest,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_user_service(request)
    current_uid = int(current_user.get("user_ID", 0))

    user_request.user_id = user_id
    result_id = await svc.add_update_user(user_request, current_uid)
    return {"userId": result_id, "message": "User updated successfully"}


@router.delete(
    "/v1/users/{user_id}",
    summary="Deactivate user (soft delete)",
)
async def delete_user(
    user_id: int,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_user_service(request)
    current_uid = int(current_user.get("user_ID", 0))

    if user_id == current_uid:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    await svc.deactivate_user(user_id, current_uid)
    return {"message": "User deactivated successfully"}

