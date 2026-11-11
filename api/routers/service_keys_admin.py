"""
Service Key Admin Router — mint, inspect, rotate and revoke ag_sk_live_ keys.
═══════════════════════════════════════════════════════════════════════════
Auth: Authorization: Bearer <RSA JWT>, admin role. (require_admin)

  POST   /v1/admin/service-keys              → mint   — raw key returned ONCE
  GET    /v1/admin/service-keys              → list
  GET    /v1/admin/service-keys/{id}         → one key
  PATCH  /v1/admin/service-keys/{id}         → retune bindings, limits, credential
  POST   /v1/admin/service-keys/{id}/rotate  → new secret — raw key ONCE
  DELETE /v1/admin/service-keys/{id}         → revoke (permanent)
  GET    /v1/admin/service-keys/{id}/events  → this key's audit trail

── The rule this router exists to enforce ──────────────────────────────────
The raw key leaves the server exactly twice in its life: the mint response and
the rotate response. Everything else returns the PUBLIC projection — key_prefix
and bindings, never key_hash. That is why the repository has a separate
_PUBLIC_COLS list rather than each endpoint remembering to strip a field.

── Why revoke is a DELETE that does not delete ─────────────────────────────
Revoking sets is_active/revoked_at and keeps the row. The key_id is referenced
by conversations.service_key_id and by every audit_log entry the key produced,
so removing it would detach the credential from the trail of what it did —
which is the one thing you need after a leak.
"""
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.middleware.auth import require_admin
from api.middleware.api_key_auth import invalidate_key_cache
from api.security import service_keys

logger = logging.getLogger("agent.service.keys.admin")

router = APIRouter(prefix="/v1/admin/service-keys", tags=["Service Keys (Admin)"])


class ServiceKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200,
                      description="Human label, e.g. 'PrepCrest tutor — prod'.")
    app_id: int = Field(..., alias="appId",
                        description="The application the key IS. Resolves the "
                                    "persona, knowledge scope and LLM profile.")
    description: str = Field("", max_length=2000)
    persona_id: Optional[int] = Field(
        None, alias="personaId",
        description="Pin a persona. Omit to take the application's default.")
    service_user_id: Optional[int] = Field(
        None, alias="serviceUserId",
        description="Whose budget and ledger the key spends against. "
                    "Defaults to you, the minting admin.")
    scopes: Optional[List[str]] = Field(
        None, description="Capabilities. Defaults to ['chat'].")
    rate_limits: Optional[Dict] = Field(
        None, alias="rateLimits",
        description="{per_session_msg, per_ip_per_min, daily_token_cap}. "
                    "per_session_msg is enforced PER END USER.")
    allowed_ips: Optional[List[str]] = Field(
        None, alias="allowedIps",
        description="Addresses or CIDR blocks. Empty = any source. "
                    "LEAVE THIS EMPTY on the current deployment: gateway-api "
                    "re-originates every request, so callers arrive as "
                    "127.0.0.1 and any allowlist locks them out instead of "
                    "hardening them. Check GET /v1/service/whoami — if "
                    "sourceIp is 127.0.0.1, this field is unusable.")
    expires_at: Optional[str] = Field(
        None, alias="expiresAt", description="ISO-8601. Omit for no expiry.")
    llm_api_key: Optional[str] = Field(
        None, alias="llmApiKey", max_length=500,
        description="Provider credential for THIS key's turns, replacing the "
                    "application profile's api_key and nothing else — the "
                    "model stays the profile's. Either a raw key, or "
                    "'__config:<config_key>__' naming an ag_system.configs "
                    "row (preferred: one config row per deployment, rotated "
                    "in one place). Omit for the profile's key. Never "
                    "returned; reads show llmCredential — the sentinel, or "
                    "the last four characters.")

    class Config:
        populate_by_name = True


class ServiceKeyUpdateRequest(BaseModel):
    """Every field optional — only what is sent is changed.

    Notably absent: app_id. The application is the key's whole security scope,
    so moving a live key to another one would silently repoint an established
    credential at a different persona and a different knowledge base. Mint a
    new key instead.
    """

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    persona_id: Optional[int] = Field(None, alias="personaId")
    scopes: Optional[List[str]] = None
    rate_limits: Optional[Dict] = Field(None, alias="rateLimits")
    allowed_ips: Optional[List[str]] = Field(None, alias="allowedIps")
    is_active: Optional[bool] = Field(None, alias="isActive")
    expires_at: Optional[str] = Field(None, alias="expiresAt")
    llm_api_key: Optional[str] = Field(
        None, alias="llmApiKey", max_length=500,
        description="See the create request. Send \"\" to clear the "
                    "override and return the key to the profile's credential.")

    class Config:
        populate_by_name = True


def _check_llm_credential(repo, value: Optional[str]) -> None:
    """A '__config:<name>__' sentinel must name a config row that exists —
    refused here, at write time, rather than discovered as a fallback
    warning on the first turn. A raw key is taken as given."""
    if not value:
        return
    from api.repositories.service_key_repo import (
        LLM_CREDENTIAL_CONFIG_PREFIX as P, LLM_CREDENTIAL_CONFIG_SUFFIX as X)
    v = value.strip()
    if v.startswith(P) and v.endswith(X):
        name = v[len(P):-len(X)]
        if not name or not repo.config_exists(name):
            raise HTTPException(
                status_code=400,
                detail=f"llmApiKey names config '{name}', which does not exist "
                       f"(ag_system.configs, is_active). Create it first.")


def _repo(request: Request):
    from api.repositories.service_key_repo import ServiceKeyRepository

    return ServiceKeyRepository(request.app.state.db)


def _require(row, key_id: int):
    if not row:
        raise HTTPException(status_code=404, detail=f"Service key {key_id} not found.")
    return row


@router.post(
    "",
    summary="Mint a service key",
    description="Returns the raw key **once**. It is stored only as sha256 and "
                "cannot be recovered — if it is lost, rotate.",
)
async def create_service_key(
    req: ServiceKeyCreateRequest,
    request: Request,
    current_user: Dict = Depends(require_admin),
) -> Dict:
    repo = _repo(request)
    admin_id = int(current_user.get("user_ID", 0))
    _check_llm_credential(repo, req.llm_api_key)

    raw = service_keys.mint()
    try:
        row = repo.create(
            name=req.name,
            description=req.description or "",
            key_prefix=service_keys.prefix_of(raw),
            key_hash=service_keys.hash_key(raw),
            app_id=req.app_id,
            persona_id=req.persona_id,
            # Defaults to the minting admin: the key has to spend against a real
            # user row for llm_scope budgets and the token ledger to work.
            service_user_id=req.service_user_id or admin_id,
            scopes=req.scopes,
            rate_limits=req.rate_limits,
            allowed_ips=req.allowed_ips,
            expires_at=req.expires_at,
            created_by=admin_id,
            llm_api_key=(req.llm_api_key or "").strip() or None,
        )
    except Exception as e:
        # app_id and persona_id are foreign keys; a bad one is the caller's
        # mistake, not a server fault.
        logger.warning("service key mint failed: %s", e)
        raise HTTPException(
            status_code=400,
            detail="Could not mint the key — check appId and personaId exist.")

    repo.log_event(row["key_id"], "key.minted",
                   f"minted by user {admin_id}", source_ip=None)
    invalidate_key_cache()

    return {
        **row,
        # The only time this value ever leaves the server, apart from a rotate.
        "key": raw,
        "warning": "Store this key now — it is not recoverable. "
                   "Only its prefix is shown from here on.",
    }


@router.get("", summary="List service keys")
async def list_service_keys(
    request: Request,
    app_id: Optional[int] = Query(None, alias="appId"),
    include_revoked: bool = Query(False, alias="includeRevoked"),
    current_user: Dict = Depends(require_admin),
) -> List[Dict]:
    return _repo(request).list_keys(app_id=app_id, include_revoked=include_revoked)


@router.get("/{key_id}", summary="Get one service key")
async def get_service_key(
    key_id: int,
    request: Request,
    current_user: Dict = Depends(require_admin),
) -> Dict:
    return _require(_repo(request).get(key_id), key_id)


@router.patch("/{key_id}", summary="Update a service key's bindings and limits")
async def update_service_key(
    key_id: int,
    req: ServiceKeyUpdateRequest,
    request: Request,
    current_user: Dict = Depends(require_admin),
) -> Dict:
    repo = _repo(request)
    _require(repo.get(key_id), key_id)
    _check_llm_credential(repo, req.llm_api_key)

    row = repo.update(
        key_id,
        name=req.name,
        description=req.description,
        persona_id=req.persona_id,
        scopes=req.scopes,
        rate_limits=req.rate_limits,
        allowed_ips=req.allowed_ips,
        is_active=req.is_active,
        expires_at=req.expires_at,
        # "" clears (repo maps it to NULL); None leaves it alone.
        llm_api_key=(None if req.llm_api_key is None else req.llm_api_key.strip()),
    )
    repo.log_event(key_id, "key.updated",
                   f"updated by user {current_user.get('user_ID')}")
    # Without this, a deactivation sits behind the auth cache for up to its TTL.
    invalidate_key_cache()
    return _require(row, key_id)


@router.post(
    "/{key_id}/rotate",
    summary="Rotate a key's secret",
    description="Issues a new raw key and invalidates the old one, keeping the "
                "same key_id — so conversations and the audit trail stay "
                "attached. Returns the new key **once**.",
)
async def rotate_service_key(
    key_id: int,
    request: Request,
    current_user: Dict = Depends(require_admin),
) -> Dict:
    repo = _repo(request)
    _require(repo.get(key_id), key_id)

    raw = service_keys.mint()
    ok = repo.rotate(key_id, service_keys.prefix_of(raw), service_keys.hash_key(raw))
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Key is revoked and cannot be rotated — mint a new one.")

    repo.log_event(key_id, "key.rotated",
                   f"rotated by user {current_user.get('user_ID')}")
    # The old secret must stop working immediately, not when the cache expires.
    invalidate_key_cache()

    return {
        **_require(repo.get(key_id), key_id),
        "key": raw,
        "warning": "Store this key now. The previous key stopped working "
                   "the moment this call returned.",
    }


@router.delete(
    "/{key_id}",
    summary="Revoke a service key (permanent)",
    description="The row is kept so conversations and audit entries stay "
                "attached to the credential that produced them. A revoked key "
                "is never reactivated — mint a new one.",
)
async def revoke_service_key(
    key_id: int,
    request: Request,
    current_user: Dict = Depends(require_admin),
) -> Dict:
    repo = _repo(request)
    _require(repo.get(key_id), key_id)

    if not repo.revoke(key_id):
        return {"revoked": True, "keyId": key_id, "note": "Already revoked."}

    repo.log_event(key_id, "key.revoked",
                   f"revoked by user {current_user.get('user_ID')}")
    invalidate_key_cache()
    logger.info("service_key.revoked: id=%s by user=%s",
                key_id, current_user.get("user_ID"))
    return {"revoked": True, "keyId": key_id}


@router.get(
    "/{key_id}/events",
    summary="This key's audit trail",
    description="Denials and lifecycle changes from ag_system.audit_log. "
                "Successful authentications are not rows here — they are "
                "represented by last_used_at, because a row per request would "
                "make an auth check a write.",
)
async def list_service_key_events(
    key_id: int,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    current_user: Dict = Depends(require_admin),
) -> List[Dict]:
    repo = _repo(request)
    _require(repo.get(key_id), key_id)
    return repo.list_events(key_id, limit=limit)
