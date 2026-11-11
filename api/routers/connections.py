"""
Connections API — the single credential surface.
═══════════════════════════════════════════════════════════════════════════
Replaces the old split /v1/credentials/* (user) + /v1/admin/credentials/*
(admin) + bindings endpoints. One resource, scope-aware authorization.

  GET    /v1/connections/providers     provider registry (kind + field schema)
  GET    /v1/connections               connections I can see (my user + org [+ app if admin])
  POST   /v1/connections               create/replace {provider, scope, owner_ref?, label, fields}
  GET    /v1/connections/{id}/detail   masked detail for the edit form
  PUT    /v1/connections/{id}          {label?, fields?, status?}
  DELETE /v1/connections/{id}
  POST   /v1/connections/{id}/test     live verify

The server splits secrets, enforces field scope + required (core/connections.py);
the browser never decides what is a secret.
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from api.middleware.auth import get_current_user
from core.connections import Connections, ConnectionValidationError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Connections"])


def _conn(request: Request) -> Optional[Connections]:
    c = getattr(request.app.state, "connections", None)
    if c is None:
        db = getattr(request.app.state, "db", None)
        if db is not None:
            c = Connections(db)
            request.app.state.connections = c
    return c


def _is_admin(user: dict) -> bool:
    return (user.get("role", "member") or "").lower() in (
        "admin", "superadmin", "administrator", "owner", "tenant owner")


def _hot_apply():
    """Re-register integration tools + flush sessions across workers (no restart)."""
    try:
        from api.services.chat_service import refresh_integrations_global
        refresh_integrations_global()
    except Exception as e:
        logger.warning("connections hot-apply failed: %s", e)


class ConnectionCreate(BaseModel):
    provider: str
    scope: str = Field("user", description="'user' | 'org' | 'app'")
    owner_ref: Optional[str] = Field(None, description="app_uuid for scope=app; ignored for user/org")
    label: str = "Default"
    fields: Dict = Field(default_factory=dict)


class ConnectionUpdate(BaseModel):
    label: Optional[str] = None
    fields: Optional[Dict] = None
    status: Optional[str] = None


@router.get("/v1/connections/providers")
async def list_providers(request: Request, current_user: Dict = Depends(get_current_user)):
    conn = _conn(request)
    if not conn:
        return []
    is_admin = _is_admin(current_user)
    out = []
    for p in conn.get_providers():
        if not is_admin and not p.supports_user:
            continue
        out.append({
            "provider_key": p.provider_key, "display_name": p.display_name,
            "category": p.category, "kind": p.kind, "fields": p.fields,
            "supports_user": p.supports_user, "supports_verify": p.supports_verify,
            "icon_url": p.icon_url, "docs_url": p.docs_url,
        })
    return out


def _summary(s, *, readonly: bool) -> dict:
    return {
        "connection_id": s.connection_id, "provider_key": s.provider_key,
        "scope": s.scope, "owner_ref": s.owner_ref, "label": s.label,
        "status": s.status, "config_keys": s.config_keys, "has_secret": s.has_secret,
        "last_used_at": s.last_used_at, "created_at": s.created_at,
        "is_readonly": readonly,
    }


@router.get("/v1/connections")
async def list_connections(request: Request, current_user: Dict = Depends(get_current_user)):
    conn = _conn(request)
    if not conn:
        return []
    uid = str(current_user.get("user_ID"))
    is_admin = _is_admin(current_user)
    out: List[dict] = []
    for s in conn.list_connections(scope="user", owner_ref=uid):
        out.append(_summary(s, readonly=False))
    for s in conn.list_connections(scope="org"):
        out.append(_summary(s, readonly=not is_admin))
    if is_admin:
        for s in conn.list_connections(scope="app"):
            out.append(_summary(s, readonly=False))
    return out


@router.post("/v1/connections")
async def create_connection(body: ConnectionCreate, request: Request,
                            current_user: Dict = Depends(get_current_user)):
    conn = _conn(request)
    if not conn:
        raise HTTPException(500, "Connections engine unavailable")
    uid = current_user.get("user_ID")
    is_admin = _is_admin(current_user)

    scope = body.scope
    owner_ref = body.owner_ref or ""
    if scope == "user":
        owner_ref = str(uid)
    elif scope in ("org", "app"):
        if not is_admin:
            raise HTTPException(403, "Admin access required for org/app connections")
    else:
        raise HTTPException(400, "scope must be 'user', 'org' or 'app'")

    p = conn.get_provider(body.provider)
    if not p:
        raise HTTPException(404, f"Unknown provider: {body.provider}")
    if scope == "user" and not p.supports_user:
        raise HTTPException(403, f"{body.provider} is not a user-configurable provider")

    fields = dict(body.fields or {})
    if scope == "user" and p.kind == "shared_app":
        own = (current_user.get("email_ID") or "").strip()
        if own:
            fields["user_email"] = own

    try:
        from core.integrations.runtime import prepare_connect_fields
        fields = prepare_connect_fields(getattr(conn, "_db", None), body.provider, fields)
    except Exception as e:
        raise HTTPException(400, f"Could not sign in to the API: {e}")

    try:
        cid = conn.upsert(body.provider, scope, owner_ref, fields,
                          label=body.label, created_by=uid)
    except ConnectionValidationError as e:
        raise HTTPException(400, e.message)
    _hot_apply()
    return {"connection_id": cid, "message": f"{body.provider} connection saved."}


def _load_owned(conn: Connections, connection_id: int, user: dict):
    detail = conn.get_masked(connection_id)
    if not detail:
        raise HTTPException(404, "Connection not found")
    is_admin = _is_admin(user)
    if not is_admin:
        if detail["scope"] != "user" or detail["owner_ref"] != str(user.get("user_ID")):
            raise HTTPException(403, "Access denied")
    return detail


@router.get("/v1/connections/{connection_id}/detail")
async def connection_detail(connection_id: int, request: Request,
                            current_user: Dict = Depends(get_current_user)):
    conn = _conn(request)
    if not conn:
        raise HTTPException(500, "Connections engine unavailable")
    return _load_owned(conn, connection_id, current_user)


@router.put("/v1/connections/{connection_id}")
async def update_connection(connection_id: int, body: ConnectionUpdate, request: Request,
                            current_user: Dict = Depends(get_current_user)):
    conn = _conn(request)
    if not conn:
        raise HTTPException(500, "Connections engine unavailable")
    detail = _load_owned(conn, connection_id, current_user)
    fields = body.fields
    if fields is not None and detail["scope"] == "user" \
            and detail["owner_ref"] == str(current_user.get("user_ID")):
        p = conn.get_provider(detail["provider_key"])
        if p and p.kind == "shared_app":
            own = (current_user.get("email_ID") or "").strip()
            if own:
                fields = {**fields, "user_email": own}
    try:
        conn.update(connection_id, fields=fields, label=body.label, status=body.status)
    except ConnectionValidationError as e:
        raise HTTPException(400, e.message)
    _hot_apply()
    return {"message": "Connection updated."}


@router.delete("/v1/connections/{connection_id}")
async def delete_connection(connection_id: int, request: Request,
                            current_user: Dict = Depends(get_current_user)):
    conn = _conn(request)
    if not conn:
        raise HTTPException(500, "Connections engine unavailable")
    _load_owned(conn, connection_id, current_user)
    conn.delete(connection_id)
    _hot_apply()
    return {"message": "Connection deleted."}


@router.post("/v1/connections/{connection_id}/test")
async def test_connection(connection_id: int, request: Request,
                          current_user: Dict = Depends(get_current_user)):
    conn = _conn(request)
    if not conn:
        raise HTTPException(500, "Connections engine unavailable")
    _load_owned(conn, connection_id, current_user)
    ok, message = await run_in_threadpool(conn.verify, connection_id)
    return {"ok": ok, "message": message}
