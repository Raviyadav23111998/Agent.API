"""
Auth Repository — Data access layer for ag_auth schema.
═══════════════════════════════════════════════════════
≈ SMSystems.Infrastructure.Data.Repository (UserRepository)

Tables: ag_auth.users, ag_auth.roles, ag_auth.refresh_tokens, ag_auth.user_sessions
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List

from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)


class AuthRepository:
    """Data access for auth-related tables in ag_auth schema."""

    def __init__(self, db: TenantDB):
        self._db = db


    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Fetch user by user_code for login authentication."""
        return self._db.fetch_one("""
            SELECT u.user_id, u.user_code, u.email, u.full_name,
                   u.password_hash, encode(u.salt, 'hex') as salt_hex,
                   u.is_active, u.role_id, u.app_id,
                   r.role_name, r.role_key
            FROM ag_auth.users u
            LEFT JOIN ag_auth.roles r ON r.role_id = u.role_id
            WHERE u.user_code = %s OR u.email = %s
        """, (username, username))

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """Fetch user by ID."""
        return self._db.fetch_one("""
            SELECT u.user_id, u.user_code, u.email, u.full_name,
                   u.is_active, u.role_id,
                   r.role_name, r.role_key
            FROM ag_auth.users u
            LEFT JOIN ag_auth.roles r ON r.role_id = u.role_id
            WHERE u.user_id = %s
        """, (user_id,))

    def get_role_id_by_name(self, role_name: str) -> Optional[int]:
        """Fetch role_id by role name (case-insensitive)."""
        row = self._db.fetch_one("""
            SELECT role_id FROM ag_auth.roles 
            WHERE role_name ILIKE %s OR role_key ILIKE %s
        """, (role_name, role_name))
        return row['role_id'] if row else None

    def create_jit_user(self, email: str, first_name: str, last_name: str, role_name: str) -> Optional[Dict]:
        """Create a new user Just-In-Time (JIT) from SSO."""
        role_id = self.get_role_id_by_name(role_name)
        if not role_id:
            role_id = self.get_role_id_by_name('User') or 3

        full_name = f"{first_name} {last_name}".strip()
        user_code = email.split('@')[0] if email else f"user_{int(datetime.now().timestamp())}"

        row = self._db.execute_returning("""
            INSERT INTO ag_auth.users (
                user_code, email, full_name, role_id, 
                is_active, password_hash, salt, app_id, created_at
            )
            VALUES (%s, %s, %s, %s, TRUE, '', '', 1, NOW())
            RETURNING user_id
        """, (user_code, email, full_name, role_id))
        user_id = row['user_id'] if row else None
        
        if user_id:
            return self.get_user_by_id(user_id)
        return None


    def get_active_refresh_tokens(self, user_id: int) -> List[Dict]:
        """Get active refresh tokens for a user."""
        return self._db.fetch_all("""
            SELECT token_id, token, expires_at, is_active, session_id
            FROM ag_auth.refresh_tokens
            WHERE user_id = %s AND is_active = TRUE
            ORDER BY created_at DESC
        """, (user_id,))

    def save_refresh_token(
        self, user_id: int, token: str, expires_at: datetime,
        session_id: str, is_active: bool = True,
    ):
        """Save refresh token."""
        self._db.execute("""
            INSERT INTO ag_auth.refresh_tokens (user_id, token, expires_at, session_id, is_active)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, token, expires_at, session_id, is_active))

    def deactivate_refresh_token_by_id(self, token_id: int):
        """Deactivate a single refresh token (rotation after use)."""
        self._db.execute("""
            UPDATE ag_auth.refresh_tokens
            SET is_active = FALSE, revoked_at = NOW()
            WHERE token_id = %s AND is_active = TRUE
        """, (token_id,))

    def deactivate_refresh_token_by_session(self, session_id: str):
        """Deactivate refresh token by session ID (for logout)."""
        self._db.execute("""
            UPDATE ag_auth.refresh_tokens 
            SET is_active = FALSE, revoked_at = NOW() 
            WHERE session_id = %s AND is_active = TRUE
        """, (session_id,))

    def create_jit_user(self, email: str, first_name: str, last_name: str, role_name: str) -> Optional[Dict]:
        """Create a new user Just-In-Time (JIT) from SSO."""
        role_id = self.get_role_id_by_name(role_name)
        if not role_id:
            role_id = self.get_role_id_by_name('Member')
            if not role_id:
                raise Exception("Critical Error: 'Member' role not found in ag_auth.roles table.")

        full_name = f"{first_name} {last_name}".strip()
        user_code = email.split('@')[0] if email else f"user_{int(datetime.now().timestamp())}"

        user_id = self._db.execute("""
            INSERT INTO ag_auth.users (
                user_code, email, full_name, role_id, 
                is_active, password_hash, salt, created_at
            )
            VALUES (%s, %s, %s, %s, TRUE, '', '', NOW())
            RETURNING user_id
        """, (user_code, email, full_name, role_id), return_id=True)
        
        if user_id:
            return self.get_user_by_id(user_id)
        return None

    def validate_refresh_token(self, user_id: int, refresh_token: str) -> Optional[Dict]:
        """Validate a specific refresh token."""
        return self._db.fetch_one("""
            SELECT token_id, token, expires_at, session_id
            FROM ag_auth.refresh_tokens
            WHERE user_id = %s AND token = %s AND is_active = TRUE AND expires_at > NOW()
        """, (user_id, refresh_token))

    def find_refresh_token(self, user_id: int, refresh_token: str) -> Optional[Dict]:
        """Look up a refresh token in ANY state (active/revoked/expired).

        Needed for rotation reuse-detection: a token that EXISTS but is no
        longer active was already rotated or revoked — replaying it signals
        theft, which the caller handles by revoking the whole session family.
        """
        return self._db.fetch_one("""
            SELECT token_id, expires_at, session_id, is_active,
                   (expires_at > NOW()) AS not_expired
            FROM ag_auth.refresh_tokens
            WHERE user_id = %s AND token = %s
        """, (user_id, refresh_token))


    def create_session(
        self, user_id: int, session_id: str, ip_address: str = None,
        agent_type: str = None, platform: str = 'api',
    ):
        """Create login session."""
        self._db.execute("""
            INSERT INTO ag_auth.user_sessions (session_id, user_id, platform, agent_type, ip_address)
            VALUES (%s, %s, %s, %s, %s)
        """, (session_id, user_id, platform, agent_type, ip_address or '0.0.0.0'))

    def close_session(self, session_id: str):
        """Close session (logout)."""
        self._db.execute("""
            UPDATE ag_auth.user_sessions SET logout_at = NOW() WHERE session_id = %s
        """, (session_id,))

    def update_session_activity(self, session_id: str):
        """Update last active timestamp."""
        self._db.execute("""
            UPDATE ag_auth.user_sessions SET last_active_at = NOW() WHERE session_id = %s
        """, (session_id,))


    def update_password(self, user_id: int, password_hash: str, salt: bytes):
        """Update user password hash and salt."""
        self._db.execute("""
            UPDATE ag_auth.users SET password_hash = %s, salt = %s WHERE user_id = %s
        """, (password_hash, salt, user_id))

    def save_passcode(self, user_id: int, encrypted_passcode: str):
        """Save OTP passcode for password reset."""
        data = json.dumps({
            "code": encrypted_passcode,
            "generated_at": datetime.now(timezone.utc).isoformat()
        })
        self._db.execute("""
            UPDATE ag_auth.users
            SET metadata_json = jsonb_set(COALESCE(metadata_json, '{}'), '{passcode}', %s::jsonb)
            WHERE user_id = %s
        """, (data, user_id))


    def create_otp(self, user_id: int, otp_hash: str, ttl_minutes: int = 10) -> None:
        """Store a hashed OTP; invalidates any previous unused OTPs first
        (only the most recently issued code is ever valid)."""
        self._db.execute("""
            UPDATE ag_auth.password_otps SET used = TRUE
            WHERE user_id = %s AND used = FALSE
        """, (user_id,))
        self._db.execute("""
            INSERT INTO ag_auth.password_otps (user_id, otp_hash, expires_at)
            VALUES (%s, %s, ag_common.utc_now() + (%s || ' minutes')::interval)
        """, (user_id, otp_hash, ttl_minutes))

    def get_active_otp(self, user_id: int) -> Optional[Dict]:
        """Latest unused, unexpired OTP row for a user (or None)."""
        return self._db.fetch_one("""
            SELECT otp_id, otp_hash, attempts
            FROM ag_auth.password_otps
            WHERE user_id = %s AND used = FALSE
              AND expires_at > ag_common.utc_now()
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,))

    def mark_otp_used(self, otp_id: int) -> None:
        self._db.execute(
            "UPDATE ag_auth.password_otps SET used = TRUE WHERE otp_id = %s",
            (otp_id,))

    def increment_otp_attempts(self, otp_id: int) -> None:
        self._db.execute(
            "UPDATE ag_auth.password_otps SET attempts = attempts + 1 WHERE otp_id = %s",
            (otp_id,))


    def log_auth_event(self, user_id, action: str, detail: str = None):
        """Log auth event to audit trail."""
        uid = int(user_id) if user_id else None
        details = json.dumps({"info": detail}) if detail else '{}'
        self._db.execute("""
            INSERT INTO ag_system.audit_log (user_id, action, entity_type, details_json)
            VALUES (%s, %s, %s, %s::jsonb)
        """, (uid, action, 'auth', details))
