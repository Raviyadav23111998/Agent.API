"""
JWT Authentication Middleware
═══════════════════════════════
Identical to SMSystems JWT auth — uses same RSA keys from MSystems.

Architecture:
    - RSA key pair shared across Storeglance platform (SMSystems, Fleet, Agent)
    - Public key verifies tokens, Private key signs tokens
    - Claims: user_ID, user_code, email_ID, first_name, last_name, role, session_ID, tenant_id
    - Token expiry: 1440 min (24h), Refresh: 7 days

Equivalent to:
    - SolutionsKraft.Library.Security.JwtHandler
    - SolutionsKraft.Library.Security.RSAHandler
    - SolutionsKraft.Library.Security.PasswordHandler
"""

import hashlib
import hmac
import jwt
import logging
import os
import secrets
from base64 import b64decode
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Tuple

from cryptography.hazmat.primitives.serialization import (
    load_der_public_key,
    load_der_private_key,
)
from cryptography.hazmat.backends import default_backend
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


def _load_rsa_public_key(base64_key: str):
    """Load RSA public key from base64-encoded DER (same format as SMSystems)."""
    der_bytes = b64decode(base64_key)
    return load_der_public_key(der_bytes, backend=default_backend())


def _load_rsa_private_key(base64_key: str):
    """Load RSA private key from base64-encoded DER (same format as SMSystems)."""
    der_bytes = b64decode(base64_key)
    return load_der_private_key(der_bytes, password=None, backend=default_backend())


def generate_password_hash(password: str) -> Tuple[str, bytes]:
    """Generate password hash + salt (≈ PasswordHandler.GeneratePasswordHash).
    
    Uses HMAC-SHA512 with random salt, identical to SolutionsKraft.Library.
    """
    salt = os.urandom(128)
    password_bytes = password.encode('utf-8')
    hash_bytes = hmac.new(salt, password_bytes, hashlib.sha512).digest()
    password_hash = hash_bytes.hex()
    return password_hash, salt


def verify_password_hash(password: str, stored_hash: str, salt: bytes) -> bool:
    """Verify password against stored hash (≈ PasswordHandler.VerifyPasswordHash)."""
    password_bytes = password.encode('utf-8')
    computed = hmac.new(salt, password_bytes, hashlib.sha512).digest()
    return hmac.compare_digest(computed.hex(), stored_hash)


def generate_jwt_token(
    claims: Dict,
    private_key_b64: str,
    issuer: str,
    audience: str,
    expiry_minutes: int = 1440,
) -> str:
    """Generate JWT token using RSA private key (≈ JwtHandler.GenerateJwtToken("RSA", ...))."""
    private_key = _load_rsa_private_key(private_key_b64)

    now = datetime.now(timezone.utc)
    payload = {
        **claims,
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + timedelta(minutes=expiry_minutes),
        "nbf": now,
    }

    token = jwt.encode(payload, private_key, algorithm="RS256")
    return token


def generate_refresh_token() -> str:
    """Generate a cryptographic refresh token (≈ JwtHandler.GenerateRefreshToken)."""
    return secrets.token_urlsafe(64)


def verify_jwt_token(
    token: str,
    public_key_b64: str,
    issuer: str,
    audience: str,
    verify_expiry: bool = True,
) -> Dict:
    """Verify JWT token using RSA public key (shared with SMSystems/Fleet)."""
    public_key = _load_rsa_public_key(public_key_b64)

    options = {}
    if not verify_expiry:
        options["verify_exp"] = False

    payload = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        issuer=issuer,
        audience=audience,
        options=options,
    )
    return payload


class JWTConfig:
    """JWT configuration loaded from ag_system.configs at startup."""
    public_key: str = ""
    private_key: str = ""
    issuer: str = "Storeglance.MSystem"
    audience: str = "Storeglance.SolutionsKraft"
    token_expiry_minutes: int = 1440
    refresh_expiry_days: int = 7


jwt_config = JWTConfig()


def load_jwt_config():
    """Load JWT config from ag_system.configs (called once at startup)."""
    from core.config import app_config

    jwt_config.public_key = app_config.get_global("secret.public_key", "")
    jwt_config.private_key = app_config.get_global("secret.private_key", "")
    jwt_config.issuer = app_config.get_global("secret.issuer", "Storeglance.MSystem")
    jwt_config.audience = app_config.get_global("secret.audience", "Storeglance.SolutionsKraft")
    jwt_config.token_expiry_minutes = int(app_config.get_global("secret.token_expiry_minutes", "1440") or 1440)
    jwt_config.refresh_expiry_days = int(app_config.get_global("secret.refresh_token_expiry_days", "7") or 7)

    if not jwt_config.public_key:
        logger.warning("JWT public key not configured — auth will fail")
    else:
        logger.info("JWT config loaded (issuer=%s, expiry=%dm)",
                     jwt_config.issuer, jwt_config.token_expiry_minutes)


_MASTER_ROLES = {"superadmin", "system_admin", "system-admin", "system admin"}


def _crosscheck_domain_tenant(request: Optional[Request], claims: Dict) -> None:
    """Cross-tenant SSO spoofing enforcement — mirrors SMSystems
    TenantContextMiddleware: the JWT's tenant_id must match the tenant resolved
    from the request domain (set by TenantResolutionMiddleware). Mismatch → 403.

    Single-tenant (AG_MULTI_TENANT off) or default context → no-op. Master admins
    (superadmin/system_admin) are exempt (cross-tenant by design).
    """
    try:
        from core.tenant_context import current_tenant, multi_tenant_enabled
        if not multi_tenant_enabled():
            return
        ctx = current_tenant()
        if ctx.is_default:
            return
        claim_tid = str(claims.get("tenant_id") or "").strip()
        role = str(claims.get("role") or "").strip().lower()
        if role in _MASTER_ROLES:
            return
        if claim_tid and claim_tid != ctx.tenant_id:
            logger.warning("tenant.sso_spoof_blocked: domain_tenant=%s jwt_tid=%s",
                           ctx.tenant_id, claim_tid)
            raise HTTPException(
                status_code=403,
                detail="Cross-tenant access blocked: token belongs to a different tenant.",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.debug("tenant.crosscheck.skipped: %s", e)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict:
    """FastAPI dependency — extracts and verifies JWT from Authorization header.

    ≈ [Authorize] attribute + ClaimsPrincipal in .NET controllers.

    Returns decoded claims dict with: user_ID, user_code, email_ID, role, session_ID, tenant_id
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization header missing")

    token = credentials.credentials
    try:
        payload = verify_jwt_token(
            token,
            jwt_config.public_key,
            jwt_config.issuer,
            jwt_config.audience,
        )
        _crosscheck_domain_tenant(request, payload)
        return payload
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=401, detail="Invalid token issuer")
    except jwt.InvalidAudienceError:
        raise HTTPException(status_code=401, detail="Invalid token audience")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")


async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[Dict]:
    """Optional auth — returns None if no token provided (for public endpoints)."""
    if not credentials:
        return None
    try:
        return await get_current_user(request, credentials)
    except HTTPException:
        return None


ADMIN_ROLES = {"admin", "superadmin", "administrator", "owner", "tenant owner"}


def is_admin(current_user: Dict) -> bool:
    """True if the decoded JWT claims carry an admin role."""
    return (current_user.get("role") or "member").strip().lower() in ADMIN_ROLES


async def require_admin(
    current_user: Dict = Depends(get_current_user),
) -> Dict:
    """FastAPI dependency — ensures the current user has an admin role.

    Use as:  current_user: Dict = Depends(require_admin)

    Raises 403 if the user's role is not in the admin set.
    Returns the decoded JWT claims dict (same as get_current_user).
    """
    role = current_user.get("role", "member").lower()
    if role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

