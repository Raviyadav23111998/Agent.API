"""
User Service — Business logic for user management.
═══════════════════════════════════════════════════
≈ SMSystems.Application.Staff.Services.UserService

Methods map 1:1:
    AddUpdateUser  → add_update_user (with password hashing)
    GetUserById    → get_user_by_id (with created/updated user summaries)
    GetUsers       → get_users
    GetUsersDDL    → get_users_ddl
    GetUserByIDs   → get_user_by_ids
    ValidateEmail  → validate_email
    ValidateUserCode → validate_user_code
    GetActiveSession → get_active_sessions
    GetInActiveSession → get_inactive_sessions
"""

import logging
from typing import Optional, List, Dict
from fastapi import HTTPException

from api.middleware.auth import generate_password_hash
from api.repositories.user_crud_repo import UserRepository
from api.schemas.user import (
    UserRequest,
    UserByIdResponse,
    UsersListItem,
    UserSummary,
    UserSessionResponse,
    ValidateResponse,
)

logger = logging.getLogger(__name__)


class UserService:
    """User management service (≈ SMSystems UserService)."""

    def __init__(self, repo: UserRepository, notification_svc=None):
        self._repo = repo
        self._notification_svc = notification_svc


    async def add_update_user(self, request: UserRequest, current_user_id: int) -> int:
        """Create or update a user.
        
        ≈ SMSystems UserService.AddUpdateUser
        
        If password is provided:
            - Hash it (HMAC-SHA512, same as SMSystems)
            - On create: set hash + salt
            - On update: update hash + salt
        If password is empty/None:
            - Preserve existing hash (pass 'HASH' sentinel)
        """
        password_hash = None
        salt = None

        if request.password:
            password_hash, salt = generate_password_hash(request.password)
        elif not request.user_id:
            logger.warning("Creating user %s without password", request.user_code)

        email_exists = self._repo.validate_email(request.email)
        if email_exists:
            existing_user = self._repo._db.fetch_one("SELECT user_id FROM ag_auth.users WHERE LOWER(email) = LOWER(%s)", (request.email,))
            if not existing_user or existing_user['user_id'] != request.user_id:
                raise HTTPException(status_code=400, detail="Email already in use")

        code_exists = self._repo.validate_user_code(request.user_code, request.user_id)
        if code_exists:
            raise HTTPException(status_code=400, detail="User code already in use")

        user_id = self._repo.add_update_user(
            user_code=request.user_code,
            email=request.email,
            full_name=request.full_name,
            role_id=request.role_id or 3,
            is_active=request.is_active,
            password_hash=password_hash,
            salt=salt,
            user_id=request.user_id,
            mobile=request.mobile,
            avatar_url=request.avatar_url,
            platform=request.platform or 'web',
            current_user_id=current_user_id,
        )

        action = 'USER_UPDATED' if request.user_id else 'USER_CREATED'
        logger.info("%s: user_id=%d, user_code=%s, by=%d",
                    action, user_id, request.user_code, current_user_id)

        if self._notification_svc and request.password:
            template_type = "WELCOME_EMAIL" if not request.user_id else "PASSWORD_RESET"
            import asyncio
            asyncio.create_task(self._notification_svc.send_email(
                template_type=template_type,
                data_payload={
                    "UserCode": request.user_code,
                    "FullName": request.full_name,
                    "Password": request.password
                },
                recipient_email=request.email,
                recipient_user_id=user_id
            ))

        if not request.user_id:
            try:
                from core.workspace_manager import WorkspaceManager
                ws = WorkspaceManager(tenant_id="default")
                ws_path = ws.ensure_workspace(user_id)
                logger.info("Workspace provisioned for user %d: %s", user_id, ws_path)
            except Exception as e:
                logger.warning("Failed to provision workspace for user %d: %s", user_id, e)

        return user_id


    async def get_user_by_id(self, user_id: int) -> Optional[UserByIdResponse]:
        """Get user details with created/updated user summaries.
        
        ≈ SMSystems UserService.GetUserById
        """
        row = self._repo.get_user_by_id(user_id)
        if not row:
            return None

        created = None
        updated = None
        ids_to_fetch = []
        if row.get('created_by'):
            ids_to_fetch.append(row['created_by'])
        if row.get('updated_by'):
            ids_to_fetch.append(row['updated_by'])

        if ids_to_fetch:
            summaries = self._repo.get_user_by_ids(ids_to_fetch)
            summary_map = {s['user_id']: s for s in summaries}
            if row.get('created_by') and row['created_by'] in summary_map:
                s = summary_map[row['created_by']]
                created = UserSummary(user_id=s['user_id'], name=s.get('name'), user_code=s.get('user_code'))
            if row.get('updated_by') and row['updated_by'] in summary_map:
                s = summary_map[row['updated_by']]
                updated = UserSummary(user_id=s['user_id'], name=s.get('name'), user_code=s.get('user_code'))

        return UserByIdResponse(
            user_id=row['user_id'],
            user_code=row['user_code'],
            email=row.get('email', ''),
            full_name=row.get('full_name', ''),
            mobile=row.get('mobile'),
            avatar_url=row.get('avatar_url'),
            role_id=row['role_id'],
            role_name=row.get('role_name'),
            is_active=row['is_active'],
            is_blocked=row.get('is_blocked', False),
            platform=row.get('platform'),
            last_login_at=row.get('last_login_at'),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at'),
            created=created,
            updated=updated,
        )


    async def get_users(self, skip: int = 0, take: int = 10, search: Optional[str] = None, sort_field: str = 'user_id', sort_dir: str = 'desc') -> Dict:
        """Get paginated users with creator/updater display names."""
        result = self._repo.get_users(skip, take, search, sort_field, sort_dir)
        items = [
            UsersListItem(
                user_id=r['user_id'],
                user_code=r['user_code'],
                email=r.get('email', ''),
                full_name=r.get('full_name', ''),
                role_name=r.get('role_name'),
                is_active=r['is_active'],
                is_blocked=r.get('is_blocked', False),
                platform=r.get('platform'),
                created_by_name=r.get('created_by_name'),
                created_at=r.get('created_at'),
                updated_by_name=r.get('updated_by_name'),
                updated_at=r.get('updated_at'),
            )
            for r in result['data']
        ]
        return {
            "total": result['total'],
            "data": items
        }


    async def get_users_ddl(
        self, search_text: Optional[str] = None, role: Optional[str] = None
    ) -> List[UserSummary]:
        """Get users for dropdown/autocomplete.
        
        ≈ SMSystems UserService.GetUsersDDL
        """
        rows = self._repo.get_users_ddl(search_text, role)
        return [
            UserSummary(
                user_id=r['user_id'],
                name=r.get('name'),
                user_code=r.get('user_code'),
                email=r.get('email'),
                role_name=r.get('role_name'),
                is_active=r.get('is_active'),
            )
            for r in rows
        ]


    async def get_user_by_ids(self, user_ids: str) -> List[UserSummary]:
        """Get user summaries by comma-separated IDs.
        
        ≈ SMSystems UserService.GetUserByIDs (string of comma-separated IDs)
        """
        ids = [int(x.strip()) for x in user_ids.split(',') if x.strip().isdigit()]
        rows = self._repo.get_user_by_ids(ids)
        return [
            UserSummary(user_id=r['user_id'], name=r.get('name'), user_code=r.get('user_code'))
            for r in rows
        ]


    async def validate_email(self, email: str) -> ValidateResponse:
        """Check if email is already taken.
        
        ≈ SMSystems UserService.ValidateEmail
        """
        exists = self._repo.validate_email(email)
        return ValidateResponse(
            exists=exists,
            message="Email already in use" if exists else "Email available",
        )


    async def validate_user_code(
        self, user_code: str, user_id: Optional[int] = None
    ) -> ValidateResponse:
        """Check if user_code is already taken.
        
        ≈ SMSystems UserService.ValidateUserCode
        """
        exists = self._repo.validate_user_code(user_code, user_id)
        return ValidateResponse(
            exists=exists,
            message="User code already in use" if exists else "User code available",
        )


    async def get_active_sessions(self, user_id: int) -> List[UserSessionResponse]:
        """Get active sessions for a user.
        
        ≈ SMSystems UserService.GetActiveSession
        """
        rows = self._repo.get_active_sessions(user_id)
        return [UserSessionResponse(**r) for r in rows]


    async def get_inactive_sessions(self, user_id: int) -> List[UserSessionResponse]:
        """Get inactive (logged-out) sessions for a user.
        
        ≈ SMSystems UserService.GetInActiveSession
        """
        rows = self._repo.get_inactive_sessions(user_id)
        return [UserSessionResponse(**r) for r in rows]


    async def deactivate_user(self, user_id: int, current_user_id: int) -> bool:
        """Soft-delete (deactivate) a user."""
        return self._repo.deactivate_user(user_id, current_user_id)


    async def get_roles(self) -> List[Dict]:
        """Get all available roles."""
        return self._repo.get_roles()
