"""
Embed key primitives — the two-key model for embedded integrations.
═══════════════════════════════════════════════════════════════════════════
  • publishable key  'ag_pk_…'  — embedded in the customer's <script>; public,
                                  low-privilege (only opens a scoped session on
                                  an allowed origin).
  • secret key       'ag_sk_…'  — server-side only (management API + signing
                                  verified end-user identities). Stored as a
                                  hash; shown to the admin exactly once.

See EMBED_AGENT_PLATFORM_ARCHITECTURE.md §4 and Appendix A #2.
"""
import hashlib
import hmac
import re
import secrets

PUBLISHABLE_PREFIX = "ag_pk_"
SECRET_PREFIX = "ag_sk_"

PUBLISHABLE_RE = re.compile(r"^ag_pk_[A-Za-z0-9_-]{20,}$")
SECRET_RE = re.compile(r"^ag_sk_[A-Za-z0-9_-]{24,}$")


def mint_publishable() -> str:
    return PUBLISHABLE_PREFIX + secrets.token_urlsafe(24)


def mint_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def hash_secret(secret_key: str) -> str:
    """SHA-256 hash of a secret key (what we store; never the raw secret)."""
    return hashlib.sha256(secret_key.encode("utf-8")).hexdigest()


def verify_secret(secret_key: str, stored_hash: str) -> bool:
    if not secret_key or not stored_hash:
        return False
    return hmac.compare_digest(hash_secret(secret_key), stored_hash)


def sign_identity(secret_key: str, user_id: str) -> str:
    """HMAC the end-user id with the integration secret. The customer's BACKEND
    computes this and passes it to the embed's identify() so we can verify the
    end-user isn't impersonated."""
    return hmac.new(
        secret_key.encode("utf-8"), str(user_id).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify_identity(secret_key: str, user_id: str, provided_hmac: str) -> bool:
    if not (secret_key and user_id and provided_hmac):
        return False
    return hmac.compare_digest(sign_identity(secret_key, user_id), provided_hmac)


def is_publishable(token: str) -> bool:
    return bool(token and PUBLISHABLE_RE.match(token))
