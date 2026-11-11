"""
Service Key Repository — CRUD + auth lookup for ag_system.service_keys.
═══════════════════════════════════════════════════════════════════════════
Two very different callers share this class:

  • the AUTH PATH, on every request — must be cheap and must never write
  • the ADMIN PATH, occasionally — mint, list, rotate, revoke

The auth path reads by key_prefix (indexed, selective) and then verifies the
sha256 in constant time. It does NOT read by hash directly: a prefix read
returns the row even when the hash mismatches, which is what lets us log a
"wrong key presented for this prefix" event instead of an indistinguishable
"no such key".

See V040_service_api_keys.sql.
"""
import logging
import time
import threading
from typing import Any, Dict, List, Optional

from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)

# Mirrors the column DEFAULT in V040. Shaped for EmbedRateLimiter, which is the
# enforcement path (Redis sliding window, correct across workers).
#
# per_ip_per_min is 0 — DISABLED — and that is deliberate. A backend is one
# address in front of all of its end users, so an per-IP cap throttles every
# user of the calling system together. That is exactly what makes the bot
# token's 30/IP/hour unusable for this, and enabling it here would rebuild the
# same fault. The meaningful dimension is per END USER, which the limiter gets
# from a session key of "svc:{key_id}:{end_user_ref}".
DEFAULT_RATE_LIMITS = {
    "per_session_msg": 120,
    "per_ip_per_min": 0,
    "daily_token_cap": 0,
}

_KEY_COLS = (
    "key_id, name, description, key_prefix, key_hash, app_id, persona_id, "
    "service_user_id, scopes, rate_limits, allowed_ips, is_active, "
    "expires_at, revoked_at, last_used_at, created_by, created_at, updated_at, "
    "llm_api_key"
)
# The sentinel a key uses to name a config row instead of carrying a secret.
LLM_CREDENTIAL_CONFIG_PREFIX = "__config:"
LLM_CREDENTIAL_CONFIG_SUFFIX = "__"

# A public view of a key: everything except the hash. Used by every admin read,
# so "did I accidentally return the hash?" is answered in one place.
_PUBLIC_COLS = (
    "key_id, name, description, key_prefix, app_id, persona_id, "
    "service_user_id, scopes, rate_limits, allowed_ips, is_active, "
    "expires_at, revoked_at, last_used_at, created_by, created_at, updated_at, "
    # The provider credential is shown as the sentinel it was written as (a
    # reference, not a secret) or, for a raw key, by its last four characters.
    "CASE WHEN llm_api_key IS NULL THEN NULL "
    "     WHEN left(llm_api_key, 9) = '__config:' THEN llm_api_key "
    "     ELSE '••••' || right(llm_api_key, 4) END AS llm_credential"
)


def resolve_llm_credential(row: Dict[str, Any]) -> Optional[str]:
    """The provider key this service key's turns should use, or None for
    "the application profile's". Pure: works on the row find_by_prefix
    returns (llm_api_key + the joined llm_api_key_config).

    A sentinel whose config row is missing or empty resolves to None and is
    logged: the key then spends on the profile's credential, which is the
    lesser failure — an empty bearer would fail every turn, and the operator
    who mistyped a config name would learn it from an outage."""
    raw = row.get("llm_api_key")
    if not raw:
        return None
    raw = str(raw).strip()
    if (raw.startswith(LLM_CREDENTIAL_CONFIG_PREFIX)
            and raw.endswith(LLM_CREDENTIAL_CONFIG_SUFFIX)):
        val = (row.get("llm_api_key_config") or "").strip()
        if not val:
            logger.warning(
                "service key %s names LLM credential %s, which is not set — "
                "falling back to the application profile's key",
                row.get("key_id"), raw)
            return None
        return val
    return raw


class ServiceKeyRepository:
    """Repository for service API keys."""

    # last_used_at is a usability field ("is this key still in use?"), not an
    # audit record. Writing it on every request would turn a read-only auth
    # check into a write on the hot path, so it is coalesced per key.
    _TOUCH_INTERVAL_S = 60.0

    def __init__(self, db: TenantDB):
        self._db = db
        self._touch_lock = threading.Lock()
        self._touched: Dict[int, float] = {}

    # ══════════════════════════════ auth path ════════════════════════════

    def find_by_prefix(self, key_prefix: str) -> List[Dict[str, Any]]:
        """Candidate rows for a presented key.

        Returns a list, not a row: key_prefix is not unique (only the hash is),
        and two keys minted with the same leading characters must both be
        checkable rather than one of them being permanently unauthenticatable.
        """
        # The credential override is resolved HERE, in the one query the auth
        # path already makes: a key whose llm_api_key is
        # '__config:<name>__' brings back that config row's value as
        # llm_api_key_config; a raw key comes back as itself; NULL stays
        # NULL. substring() yields NULL for a non-sentinel, so the JOIN simply
        # finds nothing. See V058 and resolve_llm_credential().
        cols = ", ".join(f"k.{c.strip()}" for c in _KEY_COLS.split(","))
        return self._db.fetch_all(
            f"""
            SELECT {cols}, c.config_value AS llm_api_key_config
              FROM ag_system.service_keys k
              LEFT JOIN ag_system.configs c
                ON c.config_key = substring(k.llm_api_key from '^__config:(.+)__$')
               AND c.is_active = TRUE
             WHERE k.key_prefix = %s AND k.is_active = TRUE
            """,
            (key_prefix,),
        )

    def config_exists(self, config_key: str) -> bool:
        """Does an active ag_system.configs row exist under this key? The
        admin router asks before accepting a __config:…__ sentinel, so a typo
        is refused at write time instead of discovered as a fallback warning
        on the first turn."""
        row = self._db.fetch_one(
            "SELECT 1 FROM ag_system.configs WHERE config_key = %s AND is_active = TRUE",
            (config_key,))
        return row is not None

    def touch(self, key_id: int) -> None:
        """Record that a key was used — at most once per minute, best-effort."""
        now = time.time()
        with self._touch_lock:
            last = self._touched.get(key_id, 0.0)
            if (now - last) < self._TOUCH_INTERVAL_S:
                return
            self._touched[key_id] = now
        try:
            self._db.execute(
                "UPDATE ag_system.service_keys SET last_used_at = NOW() WHERE key_id = %s",
                (key_id,),
            )
        except Exception as e:
            # A failed usage stamp must never fail the request it belongs to.
            logger.debug("service key touch failed (key=%s): %s", key_id, e)

    def log_event(self, key_id: int, event: str, detail: str = "",
                  end_user_ref: str = None, source_ip: str = None) -> None:
        """Record a key event in the SHARED audit log. Best-effort by design.

        ag_system.audit_log, not a table of our own: it already carries every
        column this needs and already holds the auth events written by
        user_repo, so "what happened to this credential" is one query against
        the same place every other security event lives.

        Only denials and lifecycle changes come through here. A successful auth
        is recorded by service_keys.last_used_at instead — a row per request
        would make an auth check a write on the hot path.
        """
        import json
        try:
            self._db.execute(
                """
                INSERT INTO ag_system.audit_log
                    (action, entity_type, entity_id, user_id, details_json, ip_address)
                VALUES (%s, 'service_key', %s, NULL, %s::jsonb, %s)
                """,
                (event, str(key_id),
                 json.dumps({"detail": (detail or "")[:500],
                             "end_user_ref": end_user_ref}),
                 source_ip),
            )
        except Exception as e:
            logger.debug("service key event write failed: %s", e)

    # ══════════════════════════════ admin path ═══════════════════════════

    def create(self, *, name: str, key_prefix: str, key_hash: str, app_id: int,
               service_user_id: int, description: str = "",
               persona_id: int = None, scopes: list = None,
               rate_limits: dict = None, allowed_ips: list = None,
               expires_at=None, created_by: int = None,
               llm_api_key: str = None) -> Dict[str, Any]:
        import json
        row = self._db.execute_returning(
            f"""
            INSERT INTO ag_system.service_keys
                (name, description, key_prefix, key_hash, app_id, persona_id,
                 service_user_id, scopes, rate_limits, allowed_ips,
                 expires_at, created_by, llm_api_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s)
            RETURNING {_PUBLIC_COLS}
            """,
            (name, description, key_prefix, key_hash, app_id, persona_id,
             service_user_id, json.dumps(scopes or ["chat"]),
             json.dumps(rate_limits or DEFAULT_RATE_LIMITS),
             json.dumps(allowed_ips or []), expires_at, created_by,
             llm_api_key or None),
        )
        logger.info("service_key.created: id=%s name=%s app=%s prefix=%s",
                    row["key_id"], name, app_id, key_prefix)
        return row

    def list_keys(self, app_id: int = None,
                  include_revoked: bool = False) -> List[Dict[str, Any]]:
        conditions, params = [], []
        if app_id is not None:
            conditions.append("k.app_id = %s")
            params.append(app_id)
        if not include_revoked:
            conditions.append("k.revoked_at IS NULL")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        return self._db.fetch_all(
            f"""
            SELECT k.key_id, k.name, k.description, k.key_prefix, k.app_id,
                   k.persona_id, k.service_user_id, k.scopes,
                   k.rate_limits, k.allowed_ips, k.is_active,
                   k.expires_at, k.revoked_at, k.last_used_at, k.created_by,
                   k.created_at, k.updated_at,
                   CASE WHEN k.llm_api_key IS NULL THEN NULL
                        WHEN left(k.llm_api_key, 9) = '__config:' THEN k.llm_api_key
                        ELSE '••••' || right(k.llm_api_key, 4) END AS llm_credential,
                   a.name AS app_name,
                   p.name AS persona_name
            FROM ag_system.service_keys k
            JOIN ag_system.applications a ON a.app_id = k.app_id
            LEFT JOIN ag_system.agent_personas p ON p.persona_id = k.persona_id
            {where}
            ORDER BY k.key_id DESC
            """,
            tuple(params) if params else None,
        )

    def get(self, key_id: int) -> Optional[Dict[str, Any]]:
        return self._db.fetch_one(
            f"SELECT {_PUBLIC_COLS} FROM ag_system.service_keys WHERE key_id = %s",
            (key_id,),
        )

    def rotate(self, key_id: int, key_prefix: str, key_hash: str) -> bool:
        """Replace the secret in place, keeping the key's identity and bindings.

        The row keeps its key_id, so the audit trail and any conversations that
        reference it stay attached — which is the whole point of rotating rather
        than revoking and minting.
        """
        rows = self._db.execute(
            """
            UPDATE ag_system.service_keys
            SET key_prefix = %s, key_hash = %s, updated_at = NOW()
            WHERE key_id = %s AND revoked_at IS NULL
            """,
            (key_prefix, key_hash, key_id),
        )
        if rows:
            logger.info("service_key.rotated: id=%s", key_id)
        return rows > 0

    def update(self, key_id: int, **kwargs) -> Optional[Dict[str, Any]]:
        import json
        allowed = {"name", "description", "persona_id", "scopes",
                   "rate_limits", "allowed_ips", "is_active", "expires_at",
                   "llm_api_key"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        # An empty string CLEARS the credential override (None means "not
        # sent", like every other field here), so a key can go back to the
        # application's profile without a SQL session.
        if updates.get("llm_api_key") == "":
            updates["llm_api_key"] = None
        if not updates:
            return self.get(key_id)

        for j in ("scopes", "allowed_ips", "rate_limits"):
            if j in updates and isinstance(updates[j], (list, dict)):
                updates[j] = json.dumps(updates[j])

        set_clauses = ", ".join(f"{k} = %s" for k in updates) + ", updated_at = NOW()"
        self._db.execute(
            f"UPDATE ag_system.service_keys SET {set_clauses} WHERE key_id = %s",
            tuple(list(updates.values()) + [key_id]),
        )
        logger.info("service_key.updated: id=%s fields=%s", key_id, list(updates))
        return self.get(key_id)

    def revoke(self, key_id: int) -> bool:
        """Permanent. A revoked key is never reactivated — mint a new one."""
        rows = self._db.execute(
            """
            UPDATE ag_system.service_keys
            SET is_active = FALSE, revoked_at = NOW(), updated_at = NOW()
            WHERE key_id = %s AND revoked_at IS NULL
            """,
            (key_id,),
        )
        if rows:
            logger.info("service_key.revoked: id=%s", key_id)
        return rows > 0

    def list_events(self, key_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        return self._db.fetch_all(
            """
            SELECT log_id, action AS event, details_json, ip_address, created_at
            FROM ag_system.audit_log
            WHERE entity_type = 'service_key' AND entity_id = %s
            ORDER BY created_at DESC LIMIT %s
            """,
            (str(key_id), min(limit, 200)),
        )
