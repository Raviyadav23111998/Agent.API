"""
Auth Service — Business logic for authentication.
═══════════════════════════════════════════════════
≈ SMSystems.Application.Staff.Services.AuthService

Implements the same grant_type flow:
    - client_credentials: username + password
    - refresh_token: JWT + refresh token
    - (future) external_client: OAuth provider token

Same claim structure as SMSystems:
    user_ID, user_code, email_ID, first_name, last_name, role, session_ID, tenant_id
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from api.middleware.auth import (
    jwt_config,
    generate_jwt_token,
    generate_refresh_token,
    verify_jwt_token,
    verify_password_hash,
    generate_password_hash,
)
from api.repositories.user_repo import AuthRepository
from api.schemas.auth import (
    LoginRequest,
    LoginResponse,
    UserInfo,
    ChangePasswordRequest,
    ChangePasswordResponse,
)

logger = logging.getLogger(__name__)


class AuthService:
    """Authentication service (≈ SMSystems AuthService).
    
    Same flow as SMSystems:
        1. Validate credentials (password/refresh token)
        2. Build ClaimsIdentity
        3. Generate JWT + refresh token
        4. Create session context
        5. Return LoginResponse
    """

    def __init__(self, repo: AuthRepository, tenant_id: str = None):
        self._repo = repo
        self._tenant_id = tenant_id or ""

    async def login(self, request: LoginRequest) -> LoginResponse:
        """Process login request (≈ AuthService.Login).
        
        Supports grant types:
            - client_credentials: username + password
            - refresh_token: existing JWT + refresh token
        """
        response = LoginResponse()
        is_authenticated = False
        user_row = None
        session_id = str(uuid.uuid4())

        if request.grant_type == "client_credentials":
            is_authenticated, user_row, response = await self._auth_credentials(
                request.username, request.password, response
            )

        elif request.grant_type == "refresh_token":
            is_authenticated, user_row, _old_session_id, response = await self._auth_refresh(
                request.token, response
            )
            session_id = str(uuid.uuid4())

        elif request.grant_type == "external_client":
            is_authenticated, user_row, response = await self._auth_external(
                request.token, response
            )

        else:
            response.message = "Invalid GrantType"
            return response

        if is_authenticated and user_row:
            display_name = user_row.get('full_name') or user_row.get('user_code', '')
            parts = display_name.split(' ', 1)
            first_name = parts[0] if parts else ''
            last_name = parts[1] if len(parts) > 1 else ''
            role_name = user_row.get('role_name') or 'user'

            from core.tenant_context import current_tenant_id, DEFAULT_TENANT_ID
            active_tenant_id = current_tenant_id()
            effective_tenant_id = (
                active_tenant_id
                if active_tenant_id and active_tenant_id != DEFAULT_TENANT_ID
                else self._tenant_id
            )

            claims = {
                "user_ID": str(user_row['user_id']),
                "user_code": user_row['user_code'] or user_row.get('email', ''),
                "email_ID": user_row.get('email', ''),
                "first_name": first_name,
                "last_name": last_name,
                "role": role_name,
                "session_ID": session_id,
                "tenant_id": effective_tenant_id,
                "app_id": user_row.get('app_id'),
            }

            access_token = generate_jwt_token(
                claims,
                jwt_config.private_key,
                jwt_config.issuer,
                jwt_config.audience,
                jwt_config.token_expiry_minutes,
            )
            refresh_tok = generate_refresh_token()

            self._repo.save_refresh_token(
                user_id=user_row['user_id'],
                token=refresh_tok,
                expires_at=datetime.now(timezone.utc) + timedelta(days=jwt_config.refresh_expiry_days),
                session_id=session_id,
            )

            self._repo.create_session(
                user_id=user_row['user_id'],
                session_id=session_id,
            )

            self._repo.log_auth_event(user_row['user_id'], 'LOGIN', f"grant={request.grant_type}")

            response.message = "Valid User!"
            response.is_authenticated = True
            response.access_token = access_token
            response.refresh_token = refresh_tok
            response.user = UserInfo(
                user_id=user_row['user_id'],
                username=user_row['user_code'] or user_row.get('email', ''),
                email=user_row.get('email', ''),
                first_name=first_name,
                last_name=last_name,
                role=role_name,
                display_name=display_name,
            )

        return response

    _GENERIC_AUTH_FAIL = "Invalid username or password"

    async def _auth_credentials(
        self, username: Optional[str], password: Optional[str], response: LoginResponse
    ):
        """Authenticate via username + password (≈ case "client_credentials")."""
        if not username or not password:
            response.message = "Username and password required"
            return False, None, response

        from core.rate_limit import login_limiter
        allowed, retry_after = login_limiter.check(username.lower())
        if not allowed:
            response.message = (
                f"Too many failed attempts. Try again in {retry_after}s."
            )
            self._repo.log_auth_event(None, 'LOGIN_BLOCKED', f"user={username} retry={retry_after}s")
            return False, None, response

        def _fail(user_id, reason):
            login_limiter.record_failure(username.lower())
            self._repo.log_auth_event(user_id, 'LOGIN_FAILED', reason)
            response.message = self._GENERIC_AUTH_FAIL
            return False, None, response

        user = self._repo.get_user_by_username(username)

        if not user:
            return _fail(None, f"user={username} reason=not_found")

        if not user.get('is_active', True):
            return _fail(user['user_id'], "reason=disabled")

        stored_hash = user.get('password_hash', '')
        salt_hex = user.get('salt_hex', '')

        if not stored_hash or not salt_hex:
            return _fail(user['user_id'], "reason=no_credentials")

        try:
            salt_bytes = bytes.fromhex(salt_hex)
            if verify_password_hash(password, stored_hash, salt_bytes):
                login_limiter.record_success(username.lower())
                return True, user, response
            else:
                return _fail(user['user_id'], "reason=bad_password")
        except Exception as e:
            logger.error("Password verification error: %s", e)
            return _fail(user.get('user_id'), "reason=verify_error")

    _GENERIC_REFRESH_FAIL = "Invalid or expired session. Please sign in again."

    async def _auth_refresh(self, token_info, response: LoginResponse):
        """Authenticate via refresh token with single-use rotation + reuse detection.

        Security model (OAuth 2.0 refresh-token rotation):
          - A refresh token is single-use; on success it is revoked and the
            old session closed, and `login()` issues a fresh token + session.
          - Replaying an ALREADY-rotated/revoked token is treated as theft:
            the entire session's tokens are revoked and the session closed.
        """
        if not token_info or not token_info.token or not token_info.refresh_token:
            response.message = "Token and RefreshToken required"
            return False, None, "", response

        try:
            payload = verify_jwt_token(
                token_info.token,
                jwt_config.public_key,
                jwt_config.issuer,
                jwt_config.audience,
                verify_expiry=False,
            )
            username = payload.get("user_code", "")
            session_id = payload.get("session_ID", "")
        except Exception:
            response.message = self._GENERIC_REFRESH_FAIL
            return False, None, "", response

        if not username:
            response.message = self._GENERIC_REFRESH_FAIL
            return False, None, "", response

        user = self._repo.get_user_by_username(username)
        if not user or not user.get('is_active', True):
            response.message = self._GENERIC_REFRESH_FAIL
            return False, None, "", response

        row = self._repo.find_refresh_token(
            user_id=user['user_id'],
            refresh_token=token_info.refresh_token,
        )

        if not row:
            self._repo.log_auth_event(user['user_id'], 'REFRESH_FAILED', "reason=unknown_token")
            response.message = self._GENERIC_REFRESH_FAIL
            return False, None, "", response

        if not row.get('is_active'):
            theft_session = row.get('session_id') or session_id
            try:
                if theft_session:
                    self._repo.deactivate_refresh_token_by_session(theft_session)
                    self._repo.close_session(theft_session)
            except Exception as e:
                logger.warning("Refresh reuse cleanup failed: %s", e)
            self._repo.log_auth_event(
                user['user_id'], 'REFRESH_REUSE_DETECTED',
                f"session={theft_session} — token replay, session revoked",
            )
            logger.warning("Refresh token REUSE detected for user %s session %s — revoked",
                           user['user_id'], theft_session)
            response.message = self._GENERIC_REFRESH_FAIL
            return False, None, "", response

        if not row.get('not_expired'):
            self._repo.deactivate_refresh_token_by_id(row['token_id'])
            response.message = self._GENERIC_REFRESH_FAIL
            return False, None, "", response

        try:
            self._repo.deactivate_refresh_token_by_id(row['token_id'])
            old_session = row.get('session_id') or session_id
            if old_session:
                self._repo.close_session(old_session)
        except Exception as e:
            logger.warning("Failed to rotate refresh token / close session: %s", e)

        return True, user, session_id, response

    async def _auth_external(self, token_info, response: LoginResponse):
        """Authenticate via external OAuth provider token (e.g. Microsoft Graph)."""
        if not token_info or not token_info.token or not token_info.token_provider:
            response.message = "Token and TokenProvider required"
            return False, None, response

        provider = token_info.token_provider.lower()

        if provider == "microsoft":
            import httpx
            
            try:
                async with httpx.AsyncClient() as client:
                    headers = {"Authorization": f"Bearer {token_info.token}"}
                    graph_res = await client.get("https://graph.microsoft.com/v1.0/me", headers=headers)
                    
                    if graph_res.status_code != 200:
                        logger.error(f"Microsoft Graph API error: {graph_res.text}")
                        response.message = "Invalid Microsoft Token"
                        return False, None, response
                        
                    data = graph_res.json()
                    email = data.get('mail') or data.get('userPrincipalName')
                    first_name = data.get('givenName', '')
                    last_name = data.get('surname', '')
                    
            except Exception as e:
                logger.error(f"Error validating Microsoft token: {str(e)}")
                response.message = "Error validating Microsoft token"
                return False, None, response

            if not email:
                response.message = "Could not extract email from Microsoft account"
                return False, None, response

            expected_tenant = ""
            try:
                from core.connections import Connections
                _reg = Connections(self._repo._db)
                expected_tenant = (_reg.resolve("m365").config.get("tenant_id") or "").strip()
            except Exception as e:
                logger.debug(f"Microsoft SSO tenant resolve from vault failed: {e}")
            if not expected_tenant:
                logger.error(
                    "Microsoft SSO rejected: no m365 app credential in the vault. "
                    "Add the org M365 app (with tenant_id) under Org Credentials "
                    "to enable Microsoft login."
                )
                response.message = (
                    "Microsoft SSO is not configured on this server "
                    "(no organization M365 app). Contact your administrator."
                )
                return False, None, response
            if expected_tenant:
                try:
                    import jwt
                    decoded_token = jwt.decode(token_info.token, options={"verify_signature": False})
                    token_tenant = decoded_token.get('tid', '')
                    if token_tenant and token_tenant != expected_tenant:
                        logger.warning(f"Tenant mismatch. Expected {expected_tenant}, got {token_tenant}")
                        response.message = "Account does not belong to the authorized organization"
                        return False, None, response
                        
                    roles = decoded_token.get('roles', [])
                    role_name = roles[0] if roles else 'User'
                except Exception as e:
                    logger.warning(f"Could not parse token tenant/roles: {str(e)}")
                    role_name = 'User'
            else:
                role_name = 'User'

            user = self._repo.get_user_by_username(email)

            if not user:
                logger.info(f"User {email} not found. Executing JIT provisioning.")
                user = self._repo.create_jit_user(email, first_name, last_name, role_name)
                if not user:
                    response.message = "Failed to auto-register user"
                    return False, None, response

            if not user.get('is_active', True):
                response.message = "Account Disabled!"
                self._repo.log_auth_event(user['user_id'], 'LOGIN_FAILED', "reason=disabled_sso")
                return False, None, response

            return True, user, response
            
        elif provider == "google":
            response.message = "Google SSO not fully implemented in backend yet"
            return False, None, response
            
        else:
            response.message = f"Unsupported token provider: {token_info.token_provider}"
            return False, None, response

    def logout(self, session_id: str, user_id: Optional[int] = None):
        """Logout — deactivate refresh token + close session.
        
        ≈ SMSystems AuthService.Logout(SessionID)
        """
        self._repo.deactivate_refresh_token_by_session(session_id)
        self._repo.close_session(session_id)
        self._repo.log_auth_event(user_id, 'LOGOUT', f"session={session_id}")

    @staticmethod
    def _password_strength_error(password: Optional[str]) -> Optional[str]:
        """Basic server-side strength check for new passwords.

        Returns an error message, or None if acceptable. Kept modest
        (length + letter + digit) — the schema already enforces min 6;
        this raises the bar to 8 for newly set passwords without
        touching existing credentials.
        """
        pw = password or ""
        if len(pw) < 8:
            return "Password must be at least 8 characters"
        if not any(c.isalpha() for c in pw):
            return "Password must contain at least one letter"
        if not any(c.isdigit() for c in pw):
            return "Password must contain at least one digit"
        return None

    async def change_password(self, request: ChangePasswordRequest) -> ChangePasswordResponse:
        """Change password flow (≈ AuthService.ChangePassword).
        
        Supports:
            - Challenge: Send OTP to email
            - ForgotPassword: Verify OTP + set new password
            - ResetPassword: Verify JWT + set new password
        """
        response = ChangePasswordResponse()

        if request.request_type == "ResetPassword":
            if not request.access_token:
                response.message = "Access token required"
                return response

            try:
                payload = verify_jwt_token(
                    request.access_token,
                    jwt_config.public_key,
                    jwt_config.issuer,
                    jwt_config.audience,
                )
                username = payload.get("user_code")
                user = self._repo.get_user_by_username(username)
                if not user:
                    response.message = "Invalid user"
                    return response

                from core.rate_limit import login_limiter
                key = (username or "").lower()
                allowed, retry_after = login_limiter.check(key)
                if not allowed:
                    self._repo.log_auth_event(
                        user['user_id'], 'PASSWORD_RESET_BLOCKED',
                        f"retry={retry_after}s")
                    response.message = (
                        f"Too many failed attempts. Try again in {retry_after}s."
                    )
                    return response

                stored_hash = user.get('password_hash', '')
                salt_hex = user.get('salt_hex', '')
                old_ok = bool(
                    request.old_password and stored_hash and salt_hex
                    and verify_password_hash(
                        request.old_password, stored_hash, bytes.fromhex(salt_hex))
                )
                if not old_ok:
                    login_limiter.record_failure(key)
                    self._repo.log_auth_event(
                        user['user_id'], 'PASSWORD_RESET_FAILED',
                        "reason=old_password")
                    response.message = "Current password is incorrect"
                    return response
                login_limiter.record_success(key)

                strength_err = self._password_strength_error(request.password)
                if strength_err:
                    response.message = strength_err
                    return response

                pw_hash, salt = generate_password_hash(request.password)
                self._repo.update_password(user['user_id'], pw_hash, salt)
                self._repo.log_auth_event(user['user_id'], 'PASSWORD_RESET', "via=jwt")

                response.message = "Password Changed Successfully"
                response.is_success = True

            except Exception as e:
                response.message = str(e)

        elif request.request_type == "Challenge":
            return self._challenge_flow(request, response)

        elif request.request_type == "ForgotPassword":
            return self._forgot_password_flow(request, response)

        else:
            response.message = f"Unknown request type '{request.request_type}'"

        return response


    OTP_TTL_MINUTES = 10
    OTP_MAX_ATTEMPTS = 5

    @staticmethod
    def _hash_otp(user_code: str, otp: str) -> str:
        """sha256(user_code:otp) — a DB leak must not expose live codes."""
        import hashlib
        return hashlib.sha256(f"{(user_code or '').lower()}:{otp}".encode()).hexdigest()

    def _challenge_flow(self, request: ChangePasswordRequest,
                        response: ChangePasswordResponse) -> ChangePasswordResponse:
        """Send an OTP to the account's registered email.

        ALWAYS returns the same generic message — whether the account
        exists, lacks an email, or the send failed — so this endpoint
        cannot be used for account enumeration. Throttled per user_code.
        """
        generic = ("If the account exists, a reset code has been sent to "
                   "its registered email.")
        from core.rate_limit import login_limiter
        key = f"otp:{(request.user_code or '').lower()}"
        allowed, _retry = login_limiter.check(key)
        if not allowed:
            response.message = generic
            return response
        login_limiter.record_failure(key)

        try:
            user = self._repo.get_user_by_username(request.user_code or "")
            email = (user or {}).get("email")
            if user and email:
                import secrets
                otp = f"{secrets.randbelow(1_000_000):06d}"
                self._repo.create_otp(
                    user["user_id"],
                    self._hash_otp(request.user_code, otp),
                    ttl_minutes=self.OTP_TTL_MINUTES,
                )
                from api.services.email_service import EmailService
                from core.connections import Connections
                sent = EmailService(Connections(self._repo._db)).send_otp(
                    email, otp, ttl_minutes=self.OTP_TTL_MINUTES)
                self._repo.log_auth_event(
                    user["user_id"], "OTP_CHALLENGE",
                    f"sent={sent}")
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("challenge_flow failed: %s", e)

        response.message = generic
        response.is_success = True
        return response

    def _forgot_password_flow(self, request: ChangePasswordRequest,
                              response: ChangePasswordResponse) -> ChangePasswordResponse:
        """Verify the emailed OTP and set the new password."""
        if not request.user_code or not request.otp or not request.password:
            response.message = "user_code, OTP and new password are required"
            return response

        from core.rate_limit import login_limiter
        key = (request.user_code or "").lower()
        allowed, retry_after = login_limiter.check(key)
        if not allowed:
            response.message = f"Too many failed attempts. Try again in {retry_after}s."
            return response

        user = self._repo.get_user_by_username(request.user_code)
        row = self._repo.get_active_otp(user["user_id"]) if user else None
        if not user or not row or row.get("attempts", 0) >= self.OTP_MAX_ATTEMPTS:
            login_limiter.record_failure(key)
            response.message = "Invalid or expired code"
            return response

        if self._hash_otp(request.user_code, request.otp) != row["otp_hash"]:
            self._repo.increment_otp_attempts(row["otp_id"])
            login_limiter.record_failure(key)
            self._repo.log_auth_event(user["user_id"], "OTP_FAILED", None)
            response.message = "Invalid or expired code"
            return response

        strength_err = self._password_strength_error(request.password)
        if strength_err:
            response.message = strength_err
            return response

        pw_hash, salt = generate_password_hash(request.password)
        self._repo.update_password(user["user_id"], pw_hash, salt)
        self._repo.mark_otp_used(row["otp_id"])
        try:
            self._repo.deactivate_refresh_token_by_session
            self._db_invalidate_sessions(user["user_id"])
        except Exception:
            pass
        login_limiter.record_success(key)
        self._repo.log_auth_event(user["user_id"], "PASSWORD_RESET", "via=otp")

        response.message = "Password Changed Successfully"
        response.is_success = True
        return response

    def _db_invalidate_sessions(self, user_id: int) -> None:
        """Best-effort: deactivate all refresh tokens for a user after reset."""
        try:
            for tok in self._repo.get_active_refresh_tokens(user_id) or []:
                tid = tok.get("token_id") or tok.get("id")
                if tid:
                    self._repo.deactivate_refresh_token_by_id(tid)
        except Exception:
            pass
