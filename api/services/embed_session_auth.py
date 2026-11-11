"""
Embed session handshake — publishable key + origin → short-lived session token.
═══════════════════════════════════════════════════════════════════════════
The embedded runtime presents its publishable key (`ag_pk_…`) and origin; this
service validates them (and optionally a signed end-user identity), then mints a
short-lived **session JWT** scoped to the integration. The WS/SSE runtime uses
that session token — never the raw key — bounding replay/abuse.

See EMBED_AGENT_PLATFORM_ARCHITECTURE.md §4 and Appendix A #4.
"""
import logging
from typing import Optional, Tuple
from urllib.parse import urlparse

from api.middleware.auth import jwt_config, generate_jwt_token
from api.security.embed_keys import is_publishable, verify_identity

logger = logging.getLogger("agent.embed")


class EmbedSessionAuth:
    SESSION_TTL_MIN = 15

    def __init__(self, db):
        self._db = db

    def _load_integration(self, pk: str) -> Optional[dict]:
        return self._db.fetch_one(
            """
            SELECT bot_id, name, mode, allowed_domains, persona_id, app_id,
                   secret_key_enc, is_active, guardrail_policy, rate_limits
            FROM ag_bot.bots
            WHERE publishable_key = %s
            """,
            (pk,),
        )

    def refresh_claims(self, claims: dict) -> Tuple[bool, Optional[str]]:
        """Re-read the integration's mutable config into a live session's claims.

        A WS connection caches `claims` for its whole lifetime, so without this
        an admin edit (persona swap, mode change, guardrail/rate-limit tweak,
        deactivation) would not reach an already-open socket until reconnect.
        Called at the start of each chat turn — one indexed single-row read.

        Returns (ok, error). ok=False means the integration was deactivated or
        deleted mid-session and the turn should be refused.
        """
        row = self._db.fetch_one(
            """
            SELECT mode, persona_id, app_id, is_active, guardrail_policy, rate_limits
            FROM ag_bot.bots
            WHERE bot_id = %s
            """,
            (claims.get("integration_id"),),
        )
        if not row:
            return False, "integration no longer exists"
        if not row.get("is_active"):
            return False, "integration is inactive"
        claims["mode"] = row["mode"]
        claims["persona_id"] = row.get("persona_id")
        claims["app_id"] = row.get("app_id")
        claims["guardrail_policy"] = row.get("guardrail_policy") or {}
        claims["rate_limits"] = row.get("rate_limits") or {}
        return True, None

    @staticmethod
    def _origin_allowed(origin: str, allowed_domains) -> bool:
        if not allowed_domains or "*" in (allowed_domains or []):
            return True
        host = urlparse(origin or "").hostname or ""
        if not host:
            return False
        return any(host == d or host.endswith(f".{d}") for d in allowed_domains)

    def handshake(self, pk: str, origin: str,
                  identity: Optional[dict] = None) -> Tuple[Optional[str], Optional[dict], Optional[str]]:
        """Validate pk + origin (+ optional identity) and mint a session token.

        Returns (session_token, claims, error). On success error is None.
        ``identity`` (optional) = {"userId": ..., "hmac": ...} where the
        customer's backend signed userId with the integration secret.
        """
        if not is_publishable(pk):
            return None, None, "invalid publishable key"

        row = self._load_integration(pk)
        if not row or not row.get("is_active"):
            return None, None, "integration not found or inactive"

        if not self._origin_allowed(origin, row.get("allowed_domains")):
            return None, None, "origin not allowed"

        end_user_id = None
        if identity and identity.get("userId"):
            raw_secret = self._decrypt_secret(row.get("secret_key_enc"))
            if not raw_secret:
                return None, None, "identity verification unavailable (no secret configured)"
            if not verify_identity(raw_secret, identity["userId"], identity.get("hmac", "")):
                return None, None, "identity signature invalid"
            end_user_id = str(identity["userId"])

        claims = {
            "scope": "embed",
            "integration_id": row["bot_id"],
            "mode": row["mode"],
            "origin": urlparse(origin or "").hostname or "",
            "app_id": row.get("app_id"),
            "persona_id": row.get("persona_id"),
            "end_user_id": end_user_id,
            "guardrail_policy": row.get("guardrail_policy") or {},
            "rate_limits": row.get("rate_limits") or {},
        }
        token = generate_jwt_token(
            claims, jwt_config.private_key, jwt_config.issuer,
            jwt_config.audience, self.SESSION_TTL_MIN,
        )
        return token, claims, None

    @staticmethod
    def _decrypt_secret(secret_key_enc: Optional[str]) -> Optional[str]:
        if not secret_key_enc:
            return None
        try:
            from core.security import decrypt_secret
            return decrypt_secret(secret_key_enc)
        except Exception as e:  # pragma: no cover
            logger.error("embed secret decrypt failed: %s", e)
            return None
