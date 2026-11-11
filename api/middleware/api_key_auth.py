"""
Service API-key authentication — the server-to-server credential.
═══════════════════════════════════════════════════════════════════════════
The fourth way into this API:

  Authorization: Bearer <RSA JWT>   a signed-in human           (auth.py)
  ag_pk_… + Origin → session JWT    a browser embed             (embed_session_auth.py)
  X-Bot-Token: ag_bot_…             an embedded chat widget     (routers/bot.py)
  X-API-Key: ag_sk_live_…           a BACKEND, this module

── Why this is not just the bot token ──────────────────────────────────────
X-Bot-Token is the closest existing thing — a hashed API key bound to an app
and a persona — and it was evaluated before this module was written. It is a
WIDGET credential: it ships inside a public web page, so everything around it
assumes a browser.

  • Rate limiting is 30 requests per IP per HOUR, keyed on client_ip + token
    (BotRateLimiter). A backend is one IP for all of its users, so every one of
    its end users would share a single bucket and the 31st message anywhere on
    the platform would be refused. Disqualifying on its own.
  • A conversation is identified by a browser session_id in
    ag_bot.bot_conversations, and GET /v1/bot/history/{sessionId} will return
    any session to any holder of the token. Correct for a widget on a public
    page; not correct for one backend's end users.
  • Access control is an Origin/Referer domain allowlist. A server-to-server
    caller sends neither header, so the control degrades to "*".
  • A bot row carries its own system_prompt, competing with the persona for
    prompt authority.

So this module deliberately keeps the bot token's PROVEN conventions — sha256
in the column, raw value shown once, clear-text prefix for display, binding to
app_id + persona_id — and changes only what the browser assumptions got wrong:
an IP allowlist instead of an Origin allowlist, a per-KEY rate limit instead of
a per-IP one, and conversations owned by (key, end user) instead of by an
unguessable-but-unowned session id.

A backend also has no login and no refresh cycle, which is why neither of the
first two paths fits: a JWT would have it storing a password and
re-authenticating on a 24-hour timer.

── What the key resolves to ────────────────────────────────────────────────
A principal that looks enough like the JWT claims dict for the shared services
to consume unchanged:

    {"scope": "service", "key_id": 3, "app_id": 7, "persona_id": 9,
     "user_ID": 42,          # the key's service_user_id — budgets/audit
     "role": "service", "end_user_ref": None}

`user_ID` is a REAL user row (whoever the key spends against), so llm_scope
budgets, the token ledger and the dashboards need no notion of "service" at all.

── Why the checks are in this order ────────────────────────────────────────
shape → cache → database → hash → active → expiry → ip. Everything that can
reject without touching the database does so first, because an unauthenticated
endpoint is exactly where an attacker gets to choose our workload for us.

See V040_service_api_keys.sql and api/security/service_keys.py.
"""
import ipaddress
import logging
import threading
import time
from typing import Dict, Optional, Tuple

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.security import service_keys

# auto_error=False so a request carrying only an X-API-Key is not refused by the
# bearer scheme before require_user_or_service ever runs.
_bearer = HTTPBearer(auto_error=False)

logger = logging.getLogger("agent.servicekey")

HEADER = "X-API-Key"


class _KeyCache:
    """Short-TTL positive cache, keyed on the key's hash.

    Without it, every turn of every conversation is a database round-trip
    before any work starts. With it, an admin's revoke takes effect within
    _TTL seconds rather than instantly — which is the right trade for a
    credential that is revoked in an incident measured in minutes, and it is
    why the TTL is seconds rather than minutes.

    Keyed on the HASH, never the raw key: a heap dump of this process should
    not hand over a working credential.
    """

    _TTL = 30.0

    def __init__(self):
        self._entries: Dict[str, Tuple[dict, float]] = {}
        self._lock = threading.Lock()

    def get(self, key_hash: str) -> Optional[dict]:
        now = time.time()
        with self._lock:
            hit = self._entries.get(key_hash)
            if hit and (now - hit[1]) < self._TTL:
                return hit[0]
            if hit:
                self._entries.pop(key_hash, None)
        return None

    def put(self, key_hash: str, row: dict) -> None:
        with self._lock:
            self._entries[key_hash] = (row, time.time())

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_cache = _KeyCache()


def invalidate_key_cache() -> None:
    """Called after any admin mutation so a revoke lands on the next request."""
    _cache.clear()


def rate_limit_session_key(key_id: int, end_user_ref: str) -> str:
    """The bucket a service turn counts against.

    Per END USER, not per key and not per IP. A backend is one address serving
    all of its users, so both of the obvious choices are wrong in the same way:
    they put every end user in one bucket, and the busiest one starves the
    rest. (That is precisely why the bot token's 30/IP/hour cannot carry this.)

    Enforcement is EmbedRateLimiter — Redis sliding windows with an in-memory
    fallback. An in-process limiter would have been silently wrong here: this
    API runs multiple workers, so a per-process cap of N is really N × workers.
    """
    return f"svc:{key_id}:{end_user_ref or 'anon'}"


def _client_ip(request: Request) -> str:
    """Best-effort source address.

    Read in preference order and used ONLY for the allowlist and the audit log
    — never to grant anything — so a spoofed header can lock a caller out, not
    in. That is why reading a client-supplied header at all is acceptable here.

    ── MEASURED, 26 July 2026: on the current deployment this always returns
    127.0.0.1, and an allowlist therefore CANNOT WORK. ────────────────────────
    The chain is Cloudflare → nginx:443 → nginx:8000 → gateway-api (.NET, :5082)
    → this service (:8100). Both nginx hops forward
    X-Forwarded-For correctly. gateway-api does not: it terminates the request
    and re-originates a fresh one to us, so every request arrives from the
    loopback address with no forwarding header at all.

    Verified by sending explicit headers end to end — X-Forwarded-For,
    X-Real-IP and CF-Connecting-IP are all replaced or dropped before they
    reach us. That is good in one respect (a caller cannot spoof its way past
    an allowlist) and disabling in another: we cannot see who called.

    The fix belongs in gateway-api, which must copy the inbound
    X-Forwarded-For onto the request it makes to us. Until it does,
    `allowed_ips` MUST stay empty on every service key — see _ip_allowed.
    """
    for header in ("x-forwarded-for", "cf-connecting-ip", "x-real-ip"):
        value = (request.headers.get(header) or "").strip()
        if value:
            # X-Forwarded-For is a chain; the original client is first.
            return value.split(",")[0].strip()
    return getattr(request.client, "host", "") or ""


def _ip_allowed(ip: str, allowed) -> bool:
    """Empty allowlist = any address. Entries may be addresses or CIDR blocks.

    DO NOT populate allowed_ips on this deployment. Every request currently
    arrives as 127.0.0.1 because gateway-api re-originates it (see
    _client_ip), so an allowlist naming a caller's real egress address matches
    NOTHING and locks that caller out completely — turning a hardening step
    into an outage. Re-enable it only once the gateway forwards the header and
    a whoami call reports a real address in `sourceIp`.
    """
    if not allowed:
        return True
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowed:
        try:
            if "/" in str(entry):
                if addr in ipaddress.ip_network(str(entry), strict=False):
                    return True
            elif addr == ipaddress.ip_address(str(entry)):
                return True
        except ValueError:
            logger.warning("service key allowed_ips contains an unparseable entry: %r", entry)
    return False


def _repo(request: Request):
    from api.repositories.service_key_repo import ServiceKeyRepository

    # Built per request off app.state.db so it resolves to the caller's tenant
    # database, exactly like every other repository on this API.
    return ServiceKeyRepository(request.app.state.db)


def _deny(detail: str) -> HTTPException:
    """One message for every failure mode.

    "no such key", "revoked", "expired" and "wrong hash" are four different
    facts about OUR data, and answering them separately turns this endpoint
    into an oracle for enumerating valid prefixes.
    """
    logger.info("service key denied: %s", detail)
    return HTTPException(
        status_code=401,
        detail="Invalid or inactive API key.",
        headers={"WWW-Authenticate": HEADER},
    )


async def require_service_key(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias=HEADER),
) -> Dict:
    """FastAPI dependency — authenticates a backend by its service key.

    Returns the principal dict described in the module docstring.
    """
    key = (x_api_key or "").strip()

    # Also accept `Authorization: ApiKey ag_sk_live_…`. Some HTTP clients make a
    # custom header awkward, and refusing on that basis buys nothing.
    if not key:
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("apikey "):
            key = auth[7:].strip()

    if not key:
        raise HTTPException(
            status_code=401,
            detail=f"{HEADER} header missing.",
            headers={"WWW-Authenticate": HEADER},
        )

    if not service_keys.is_well_formed(key):
        raise _deny("malformed key")

    key_hash = service_keys.hash_key(key)
    repo = _repo(request)
    ip = _client_ip(request)

    row = _cache.get(key_hash)
    if row is None:
        candidates = repo.find_by_prefix(service_keys.prefix_of(key))
        row = next(
            (c for c in candidates if service_keys.verify(key, c["key_hash"])),
            None,
        )
        if row is None:
            # A prefix that exists but whose hash does not match is a wrong or
            # rotated key — worth recording against the key it was aimed at.
            if candidates:
                repo.log_event(candidates[0]["key_id"], "auth.denied",
                               "hash mismatch (rotated or forged key)", source_ip=ip)
            raise _deny("no matching key")
        _cache.put(key_hash, row)

    if not row.get("is_active") or row.get("revoked_at"):
        raise _deny(f"key {row['key_id']} is inactive or revoked")

    expires_at = row.get("expires_at")
    if expires_at is not None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        # Tolerate a naive timestamp from an older row rather than throwing a
        # comparison error that would read as a server fault.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            repo.log_event(row["key_id"], "auth.denied", "key expired", source_ip=ip)
            raise _deny(f"key {row['key_id']} expired")

    if not _ip_allowed(ip, row.get("allowed_ips") or []):
        repo.log_event(row["key_id"], "auth.denied", f"ip not allowed: {ip}", source_ip=ip)
        raise _deny(f"key {row['key_id']} used from disallowed ip {ip}")

    # Rate limiting is NOT done here. The correct bucket is per end user, and
    # the end user is named in the request body, which a dependency does not
    # see. The endpoint applies it via rate_limit_session_key() once it has
    # parsed the body — see routers/service_chat.py.

    repo.touch(row["key_id"])

    from api.repositories.service_key_repo import resolve_llm_credential

    return {
        "scope": "service",
        "key_id": row["key_id"],
        "key_name": row.get("name") or "",
        "app_id": row.get("app_id"),
        "persona_id": row.get("persona_id"),
        "scopes": row.get("scopes") or ["chat"],
        "rate_limits": row.get("rate_limits") or {},
        # Shaped like the JWT claims so the shared services below need no
        # branch for "which kind of caller is this".
        "user_ID": row.get("service_user_id"),
        "role": "service",
        "source_ip": ip,
        # The provider key this key's turns spend on, already resolved from
        # the row (raw, or the config row a __config:…__ sentinel names).
        # None = the application profile's. It is a secret: nothing that
        # returns the principal to a caller may include it — see
        # service_whoami, which enumerates its fields on purpose.
        "llm_api_key": resolve_llm_credential(row),
    }


def require_scope(principal: Dict, scope: str) -> None:
    """Assert a key carries a capability. 401 authenticated it; this authorises."""
    if scope not in (principal.get("scopes") or []):
        raise HTTPException(
            status_code=403,
            detail=f"This API key does not carry the '{scope}' scope.",
        )


def is_service(principal: Dict) -> bool:
    """Whether this principal is a backend rather than a signed-in human."""
    return principal.get("scope") == "service"


async def require_user_or_service(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    x_api_key: Optional[str] = Header(None, alias=HEADER),
) -> Dict:
    """FastAPI dependency — accepts EITHER a signed-in human or a backend.

    ── why an endpoint would want both ─────────────────────────────────────
    The knowledge base has two legitimate writers and they authenticate
    differently by nature. A person curating documents in the admin UI has a
    login, a session and a refresh cycle, so they arrive with a JWT. A product
    keeping the base in step with its own content has none of those — it is a
    server, it runs unattended, and giving it a login would mean storing a
    password and re-authenticating on a 24-hour timer. That is precisely the
    reasoning that produced the service key in the first place (see the module
    docstring), and it applies to ingestion exactly as it applies to chat.

    Before this existed, a backend's only route into the knowledge base was to
    write to ag_brain.documents directly — reaching around the API into another
    system's tables, past every scope, app and ownership rule this module
    exists to enforce. One dependency here removes the reason to do that.

    ── what it does NOT do ─────────────────────────────────────────────────
    It authenticates; it does not authorise. A service principal arrives
    carrying its key's scopes, and the endpoint must still assert the one it
    needs — `require_scope(principal, "brain:write")`. Chat and ingestion are
    different capabilities, and a key minted to answer learners' questions must
    not thereby be able to rewrite what the answers are drawn from.

    ── precedence ──────────────────────────────────────────────────────────
    An explicit X-API-Key wins. A caller sending both is confused, and choosing
    the one they named explicitly is more predictable than preferring whichever
    the framework happened to parse first.

    Returns the JWT claims dict or the service principal. The two are shaped
    alike on purpose — `user_ID`, `app_id`, `role` — so an endpoint consuming
    this needs no branch beyond the scope check.

    Both credentials are declared as PARAMETERS rather than read off `request`
    inside the body, so FastAPI still advertises the bearer scheme and the
    X-API-Key header on every route using this. Reading them from the raw
    request would work and would quietly empty the padlock in Swagger, leaving
    a human unable to authorise a call that still requires it.
    """
    header_auth = request.headers.get("authorization") or ""

    if x_api_key or header_auth.lower().startswith("apikey "):
        return await require_service_key(request, x_api_key)

    # No key offered — the JWT path, unchanged. It raises its own 401 when
    # there is no usable Authorization header either, so a caller presenting
    # nothing gets exactly the answer it got before this dependency existed.
    from api.middleware.auth import get_current_user

    return await get_current_user(request, credentials)
