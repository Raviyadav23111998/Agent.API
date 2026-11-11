"""
Tenant Resolution Middleware (Multi-Tenancy Phase 2b)
======================================================
Faithful port of SMSystems' per-request tenant middleware (Program.cs):

    currentDomain = ?tenantDomain ?? X-Tenant-Domain ?? Host
    if localhost: → default (single-tenant dev)
    tenant = MSystemRouter.resolve(domain)        # app-scoped to 'agent'
    if tenant:
        if GetTenantEffectiveStatus(tenant) != active: 403
        bind TenantContext for the request
    else:
        proceed with the DEFAULT context (global routes: health, login, /TenantConfig)

Only active when AG_MULTI_TENANT is on — otherwise it is a pass-through and the
runtime stays single-tenant.

See MULTITENANT_MASTER_PLAN.md §6 Phase 2 and SMSystems Program.cs.
"""

from __future__ import annotations

import logging
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse

from core.tenant_context import (
    TenantContext, set_tenant_context, reset_tenant_context,
    multi_tenant_enabled,
)

logger = logging.getLogger(__name__)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


def effective_status(identity) -> str:
    """Mirror SMSystems GetTenantEffectiveStatus(tenant).

    The app-subscription gate (MSystemRouter.is_subscribed) already filters
    expired/cancelled entitlements; here we enforce the tenant-level flag.
    """
    if not identity.is_active:
        return "inactive"
    return "active"


def _origin_host(conn) -> str:
    """Host portion of the Origin header (the tenant app's own domain). For
    WebSocket upgrades the Host is the API gateway, so Origin is what carries the
    tenant for browser clients that can't set custom WS headers."""
    origin = conn.headers.get("origin", "")
    if not origin:
        return ""
    return origin.split("://", 1)[-1].split("/")[0].split(":")[0].strip().lower()


def _resolve_domain(conn, *, allow_origin: bool = False) -> str:
    dom = (conn.query_params.get("tenantDomain")
           or conn.headers.get("x-tenant-domain"))
    if not dom and allow_origin:
        dom = _origin_host(conn)
    if not dom:
        dom = conn.headers.get("host", "")
    return (dom or "").split(":")[0].strip().lower()


async def _reject_ws(scope, receive, send, status: str):
    """Deny a WebSocket handshake for a non-active tenant (HTTP gets a 403 JSON;
    WS has no response body, so we close the handshake with a policy code)."""
    try:
        await receive()
    except Exception:
        pass
    await send({"type": "websocket.close", "code": 4403})


class TenantResolutionMiddleware:
    """Pure ASGI middleware — runs in the SAME task as the endpoint, so the
    TenantContext contextvar set here reliably propagates downstream (unlike
    Starlette BaseHTTPMiddleware, which runs the app in a separate task)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        scope_type = scope.get("type")
        if scope_type not in ("http", "websocket") or not multi_tenant_enabled():
            return await self.app(scope, receive, send)

        conn = HTTPConnection(scope)
        router = getattr(scope["app"].state, "msystem_router", None)
        domain = _resolve_domain(conn, allow_origin=(scope_type == "websocket"))

        if router is None or domain in _LOCAL_HOSTS:
            return await self.app(scope, receive, send)

        try:
            identity = router.resolve(domain)
        except Exception as e:
            logger.warning("tenant.mw.resolve_failed: %s", e)
            identity = None

        if identity is None:
            return await self.app(scope, receive, send)

        status = effective_status(identity)
        if status != "active":
            if scope_type == "websocket":
                return await _reject_ws(scope, receive, send, status)
            resp = JSONResponse(
                status_code=403,
                content={
                    "error": "Tenant access restricted",
                    "tenantStatus": status,
                    "message": {
                        "inactive": "This account has been deactivated. Contact your administrator.",
                        "suspended": "This account has been suspended.",
                        "expired": "This subscription has expired. Please renew to continue.",
                    }.get(status, "Access denied."),
                },
            )
            return await resp(scope, receive, send)

        ctx = TenantContext(
            tenant_id=identity.tenant_id,
            tenant_key=identity.tenant_key,
            display_name=identity.display_name,
            tenant_domain=domain,
            is_default=False,
        )
        token = set_tenant_context(ctx)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_tenant_context(token)
