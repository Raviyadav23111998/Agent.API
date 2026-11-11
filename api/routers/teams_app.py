"""
Channels → Microsoft Teams: per-tenant Teams app package.
═══════════════════════════════════════════════════════════════════════════════
  GET /v1/channels/teams/status    → setup readiness (M365 connected? endpoint URL)
  GET /v1/channels/teams/download  → streams a per-tenant Teams app .zip

The bot identity is the tenant's OWN M365 app (BYO); the tenant is carried on the
messaging-endpoint URL (?tenant=<domain>), mirroring the chatbot widget + VS Code.
Tenant scope comes from the TenantResolutionMiddleware (X-Tenant-Domain) → the
app.state.db proxy + current_tenant() already point at this tenant.
"""
import io
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.middleware.auth import require_admin
from api.services import teams_app_service as tas

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/channels/teams", tags=["Channels"])


def _tenant_domain(request: Request) -> str:
    return (request.headers.get("x-tenant-domain") or "").split(":")[0].strip().lower()


def _ctx():
    try:
        from core.tenant_context import current_tenant
        return current_tenant()
    except Exception:
        return None


def _m365(request: Request):
    """Resolve THIS tenant's Microsoft 365 credential (client_id/tenant_id/secret)."""
    try:
        from core.connections import Connections
        return Connections(request.app.state.db).resolve_or_none("m365")
    except Exception as e:
        logger.info("teams_app.m365_resolve_failed: %s", e)
        return None


def _branding(request: Request, domain: str) -> dict:
    """The tenant's branding from the SINGLE source (MSystem tenant_profile via the
    router) — identical to what /TenantConfig serves the web/VSCode. So the Teams
    package is branded the same as every other channel."""
    try:
        router = getattr(request.app.state, "msystem_router", None)
        if not router or not domain:
            return {}
        identity = router.resolve(domain)
        if not identity:
            return {}
        return router.get_branding(identity.tenant_id) or {}
    except Exception as e:
        logger.info("teams_app.branding_failed: %s", e)
        return {}


def _logo_bases(gateway_base: str) -> list:
    """Gateway bases to try for the master logo fetch, best first. The request-
    derived base is preferred (env-correct uat vs prod), BUT the API sits behind a
    gateway that forwards to us on localhost — so the request Host can be an INTERNAL
    address (127.0.0.1) where /api/master isn't served. Such bases are dropped, and
    we fall back to the configured public gateway (tas.GATEWAY_API). Without this,
    a wrong host silently yields the 'A' fallback icon instead of the tenant logo."""
    seen, out = set(), []
    for b in (gateway_base, tas.GATEWAY_API):
        b = (b or "").rstrip("/")
        if not b:
            continue
        host = b.split("://")[-1].split("/")[0].split(":")[0].lower()
        if host in ("127.0.0.1", "localhost", "::1") or host.startswith("127."):
            continue
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out


async def _fetch_logo(domain: str, gateway_base: str = ""):
    """Best-effort fetch of the tenant logo from the MSystem TenantLogo endpoint,
    trying each candidate gateway base until one returns an image — so an internal/
    wrong request Host can't silently fall through to the 'A' placeholder icon."""
    if not domain:
        return None
    for base in _logo_bases(gateway_base):
        try:
            async with httpx.AsyncClient(timeout=8.0) as c:
                r = await c.get(f"{base}/api/master/tenant-config/TenantLogo",
                                headers={"X-Tenant-Domain": domain})
                if (r.status_code == 200 and r.content
                        and r.headers.get("content-type", "").startswith("image")):
                    return r.content
                logger.info("teams_app.logo_fetch miss base=%s status=%s", base, r.status_code)
        except Exception as e:
            logger.info("teams_app.logo_fetch_failed base=%s: %s", base, e)
    return None


@router.get("/status")
async def teams_status(request: Request, current_user: dict = Depends(require_admin)):
    ctx = _ctx()
    domain = _tenant_domain(request) or (getattr(ctx, "tenant_key", "") or "")
    m = _m365(request)
    client_id = ((m.config.get("client_id") if m else "") or "").strip()
    ready = bool(client_id and domain)
    return {
        "tenantDomain": domain,
        "displayName": getattr(ctx, "display_name", "") or domain,
        "m365Connected": bool(client_id),
        "botClientId": (client_id[:8] + "…") if client_id else "",
        "messagingEndpoint": tas.messaging_endpoint(domain) if domain else "",
        "ready": ready,
    }


@router.get("/download")
async def teams_download(request: Request, current_user: dict = Depends(require_admin)):
    ctx = _ctx()
    domain = _tenant_domain(request) or (getattr(ctx, "tenant_key", "") or "")
    if not domain:
        raise HTTPException(status_code=400, detail="Tenant context not resolved (missing X-Tenant-Domain).")

    m = _m365(request)
    client_id = ((m.config.get("client_id") if m else "") or "").strip()
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="Connect Microsoft 365 first (Settings → Connections → Microsoft 365) "
                   "so the Teams bot has an app identity.")

    brand = _branding(request, domain)
    display = (brand.get("org_name") or getattr(ctx, "display_name", "") or domain)
    accent = (brand.get("theme_color") or tas.DEFAULT_ACCENT)
    from core.tenant_branding import gateway_base_from_request
    logo = await _fetch_logo(domain, gateway_base_from_request(request))
    try:
        zip_bytes = tas.build_zip(
            tenant_domain=domain,
            display_name=display,
            client_id=client_id,
            logo_bytes=logo,
            accent=accent,
        )
    except Exception as e:
        logger.error("teams_app.build_failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to build the Teams app package.")

    slug = (getattr(ctx, "tenant_key", "") or "agent").replace("/", "-")
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}-teams-app.zip"'},
    )
