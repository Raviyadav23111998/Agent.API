"""
User Repository — Data access for ag_auth.users.
═══════════════════════════════════════════════════
≈ SMSystems.Infrastructure.Data.Repository.UserRepo

Queries match SMSystems SQL patterns adapted for ag_auth schema:
  - UPSERT via INSERT ... ON CONFLICT (user_id) DO UPDATE
  - Password handling: skip hash update when value is 'HASH'
  - DDL search: ILIKE pattern matching
  - Session queries: active (logout_at IS NULL), inactive (logout_at IS NOT NULL)
"""

import logging
from typing import Optional, Dict, List

from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)


class UserRepository:
    """Data access for ag_auth.users CRUD.
    
    ≈ SMSystems UserRepo (Dapper-based, mapped to PostgreSQL)
    """

    def __init__(self, db: TenantDB):
        self._db = db

    def add_update_user(
        self,
        user_code: str,
        email: str,
        full_name: str,
        role_id: int,
        is_active: bool,
        password_hash: Optional[str],
        salt: Optional[bytes],
        user_id: Optional[int] = None,
        mobile: Optional[str] = None,
        avatar_url: Optional[str] = None,
        platform: str = 'web',
        current_user_id: int = None,
    ) -> int:
        """Create or update user (UPSERT).
        
        ≈ SMSystems UserRepo.AddUpdateUser
        
        When password_hash is 'HASH' or None, the existing hash is preserved (same as SMSystems).
        Returns the user_id.
        """
        skip_password = (password_hash is None or password_hash == 'HASH')

        if user_id:
            if skip_password:
                self._db.execute("""
                    UPDATE ag_auth.users SET
                        user_code = %s, email = %s, full_name = %s, mobile = %s,
                        role_id = %s, is_active = %s, avatar_url = %s, platform = %s,
                        updated_by = %s, updated_at = ag_common.utc_now()
                    WHERE user_id = %s
                """, (user_code, email, full_name, mobile, role_id, is_active,
                      avatar_url, platform, current_user_id, user_id))
            else:
                self._db.execute("""
                    UPDATE ag_auth.users SET
                        user_code = %s, email = %s, full_name = %s, mobile = %s,
                        role_id = %s, is_active = %s, password_hash = %s, salt = %s,
                        avatar_url = %s, platform = %s,
                        updated_by = %s, updated_at = ag_common.utc_now()
                    WHERE user_id = %s
                """, (user_code, email, full_name, mobile, role_id, is_active,
                      password_hash, salt, avatar_url, platform, current_user_id, user_id))
            return user_id
        else:
            row = self._db.execute_returning("""
                INSERT INTO ag_auth.users (
                    user_code, email, full_name, mobile, role_id, is_active,
                    password_hash, salt, avatar_url, platform, app_id, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s)
                RETURNING user_id
            """, (user_code, email, full_name, mobile, role_id, is_active,
                  password_hash, salt, avatar_url, platform, current_user_id))
            return row['user_id']

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """Get full user details by ID.
        
        ≈ SMSystems UserRepo.GetUserById
        """
        return self._db.fetch_one("""
            SELECT u.user_id, u.user_code, u.email, u.full_name, u.mobile,
                   u.avatar_url, u.role_id, u.is_active, u.is_blocked,
                   u.platform, u.last_login_at,
                   u.created_by, u.created_at, u.updated_by, u.updated_at,
                   r.role_name
            FROM ag_auth.users u
            LEFT JOIN ag_auth.roles r ON r.role_id = u.role_id
            WHERE u.user_id = %s
        """, (user_id,))

    def get_users(self, skip: int = 0, take: int = 10, search: Optional[str] = None, sort_field: str = 'user_id', sort_dir: str = 'desc') -> Dict:
        """Get users with pagination and search."""
        
        where_clause = ""
        params = []
        if search:
            where_clause = "WHERE u.user_code ILIKE %s OR u.email ILIKE %s OR u.full_name ILIKE %s"
            search_param = f"%{search}%"
            params.extend([search_param, search_param, search_param])

        allowed_sorts = ['user_id', 'user_code', 'email', 'full_name', 'role_name', 'is_active', 'platform', 'created_at']
        if sort_field not in allowed_sorts:
            sort_field = 'user_id'
        if sort_dir.lower() not in ['asc', 'desc']:
            sort_dir = 'desc'

        count_query = f"SELECT COUNT(*) as total FROM ag_auth.users u {where_clause}"
        total_row = self._db.fetch_one(count_query, tuple(params) if params else None)
        total = total_row['total'] if total_row else 0

        data_query = f"""
            SELECT u.user_id, u.user_code, u.email, u.full_name,
                   u.is_active, u.is_blocked, u.platform,
                   u.created_at, u.updated_at,
                   r.role_name,
                   cr.full_name AS created_by_name,
                   up.full_name AS updated_by_name
            FROM ag_auth.users u
            LEFT JOIN ag_auth.roles r ON r.role_id = u.role_id
            LEFT JOIN ag_auth.users cr ON cr.user_id = u.created_by
            LEFT JOIN ag_auth.users up ON up.user_id = u.updated_by
            {where_clause}
            ORDER BY {sort_field} {sort_dir}
            LIMIT %s OFFSET %s
        """
        params.extend([take, skip])
        data = self._db.fetch_all(data_query, tuple(params))

        return {
            "total": total,
            "data": data
        }

    def get_users_ddl(self, search_text: Optional[str] = None, role: Optional[str] = None) -> List[Dict]:
        """Get users for dropdown (search by name).
        
        ≈ SMSystems UserRepo.GetUsersDDL
        """
        params = []
        where_clauses = ["u.is_active = TRUE"]

        if search_text:
            where_clauses.append("u.full_name ILIKE %s")
            params.append(f'%{search_text}%')

        if role:
            where_clauses.append("r.role_key = %s")
            params.append(role)

        where = " AND ".join(where_clauses)

        return self._db.fetch_all(f"""
            SELECT u.user_id, u.user_code, u.email, u.full_name AS name,
                   u.is_active, r.role_name
            FROM ag_auth.users u
            LEFT JOIN ag_auth.roles r ON r.role_id = u.role_id
            WHERE {where}
            ORDER BY u.full_name
            LIMIT 50
        """, tuple(params) if params else None)

    def get_user_by_ids(self, user_ids: List[int]) -> List[Dict]:
        """Get user summaries by list of IDs.
        
        ≈ SMSystems UserRepo.GetUserByIDs (comma-separated → unnest)
        """
        if not user_ids:
            return []
        placeholders = ','.join(['%s'] * len(user_ids))
        return self._db.fetch_all(f"""
            SELECT DISTINCT user_id, full_name AS name, user_code
            FROM ag_auth.users
            WHERE user_id IN ({placeholders})
        """, tuple(user_ids))

    def validate_email(self, email: str) -> bool:
        """Check if email already exists.
        
        ≈ SMSystems UserRepo.ValidateEmail
        """
        row = self._db.fetch_one("""
            SELECT EXISTS(SELECT 1 FROM ag_auth.users WHERE LOWER(email) = LOWER(%s)) AS exists
        """, (email,))
        return row['exists'] if row else False

    def validate_user_code(self, user_code: str, exclude_user_id: Optional[int] = None) -> bool:
        """Check if user_code already exists (optionally exclude a user).
        
        ≈ SMSystems UserRepo.ValidateUserCode
        """
        if exclude_user_id:
            row = self._db.fetch_one("""
                SELECT EXISTS(
                    SELECT 1 FROM ag_auth.users
                    WHERE LOWER(user_code) = LOWER(%s) AND user_id <> %s
                ) AS exists
            """, (user_code, exclude_user_id))
        else:
            row = self._db.fetch_one("""
                SELECT EXISTS(
                    SELECT 1 FROM ag_auth.users WHERE LOWER(user_code) = LOWER(%s)
                ) AS exists
            """, (user_code,))
        return row['exists'] if row else False

    def get_active_sessions(self, user_id: int) -> List[Dict]:
        """Get active sessions (no logout_at).
        
        ≈ SMSystems UserRepo.GetActiveSession
        """
        return self._db.fetch_all("""
            SELECT session_id, user_id, platform, agent_type, ip_address,
                   login_at, last_active_at, logout_at
            FROM ag_auth.user_sessions
            WHERE logout_at IS NULL AND user_id = %s
            ORDER BY login_at DESC LIMIT 5
        """, (user_id,))

    def get_inactive_sessions(self, user_id: int) -> List[Dict]:
        """Get inactive (logged-out) sessions.
        
        ≈ SMSystems UserRepo.GetInActiveSession
        """
        return self._db.fetch_all("""
            SELECT session_id, user_id, platform, agent_type, ip_address,
                   login_at, last_active_at, logout_at
            FROM ag_auth.user_sessions
            WHERE logout_at IS NOT NULL AND user_id = %s
            ORDER BY logout_at DESC LIMIT 5
        """, (user_id,))

    def deactivate_user(self, user_id: int, current_user_id: int = None) -> bool:
        """Soft-delete (deactivate) a user."""
        self._db.execute("""
            UPDATE ag_auth.users SET is_active = FALSE, 
                   updated_by = %s, updated_at = ag_common.utc_now()
            WHERE user_id = %s
        """, (current_user_id, user_id))
        return True

    def get_roles(self) -> List[Dict]:
        """Get all available roles."""
        return self._db.fetch_all("""
            SELECT role_id, role_name, role_key
            FROM ag_auth.roles
            ORDER BY role_id
        """)
